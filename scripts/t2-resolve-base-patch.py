#!/usr/bin/env python3
"""T2 — base_commit 反查 + patch 反解

出处：`docs-research/trajectory-platform/bench-mvp-plan.md` v1.2 §4 T2（2 天，最重的一步）

输入：`bench/v0.2-mini/meta/candidates.jsonl`（T1 产物，182 条）
      + `data/pulled_sessions/<sid>/session.traj`（只读，纪律 1）
      + mirror（只读，纪律 2）
输出：`bench/v0.2-mini/meta/resolved.jsonl` + `resolved.stats.json`

## 七个步骤（方案 §4 T2 原文，顺序即实现顺序）

    ① base_commit 反查   git rev-list -1 --before={started_at} refs/heads/main
    ② 写操作提取         step_range 内的 Edit / Write / MultiEdit
    ③ 路径映射（严格）   common.map_repo_path，非目标仓库一律丢弃并计数
    ④ test / code 分侧   IS_TEST 正则
    ⑤ code 侧剔除文档     docs/ 前缀与 *.md，记入 excluded_files（§3.7 坑一）
    ⑥ 锚点校验           每个文件的**首次** Edit，old_string 首行是否在 base 中
    ⑦ 生成 unified diff  按 Edit 序列重建全文，再与 base 原文做 diff

## ⚠️ 实测补充的一条（方案没写，但不做就会产出错的 patch）

**必须按 observation 的 `is_error` 跳过采集当时就失败的写操作。**
轨迹忠实记录 agent 的每一次尝试，包含失败的。182 条候选区间内有 **43 次**写操作
是失败的（`String to replace not found` / `old_string 与 new_string 相同` /
`File has been modified since read`）。把它们当成生效的改动重放，得到的就不是
开发者真正落下的那份 patch。

形态很坑：它表现为「重建某文件时 old_string 对不上」，看着像**轨迹质量差**或
**base 反查偏了**，实际是我们重放了一次本就没生效的编辑。
实测跳掉后：全文件重建成功的候选 **99 → 110**，锚点命中率 95.9% → 96.1%。
见 `common.iter_write_actions()`。

## 三类被丢弃的路径要分开判读，不能都当「无害」

`map_repo_path` 严格前缀会丢掉三种路径，**后果完全不同**：

  - `out_of_scope`  —— `~/.claude/projects/*/memory/*.md`、`/tmp/*`、
                        `docs-research/*`。真的不是仓库内容，丢掉无损。
  - `same_repo_worktree` —— `sid-code-worktrees/obs-batch/packages/...`。
                        **这是同一个仓库的 git worktree，内容是真代码。**
                        丢掉它 = patch 缺了一块，所以该候选必须淘汰而不是照发。
  - `cross_repo`    —— 映射到了另一个目标仓库。同理，混仓单元淘汰。

把三者混为一谈的后果是「patch 静默残缺」—— 这正是 §3.8-F「绿着坏掉」那一类。

## 反向自证（方案 §4 T2 验收第 4 条）

`--selftest-fuzzy-path` 让**主路径**带着 `split('sid-code/')` 这种模糊切分跑一遍。
守卫是主路径上的**往返不变式**：`前缀 + 相对路径 == 原绝对路径`。
严格映射下实测 0 违反；模糊切分下 `.claude/projects/.../memory/MEMORY.md` 会被
切成仓库内的 `memory/MEMORY.md`，不变式立刻破，以退出码 3 报红并列出泄漏路径。

自证的对象是**主路径的泄漏守卫**，不是另写一段只验自己的分支 —— 这一点沿用 T1
的做法（见 T1 的 `--selftest-strict-secret`）。

用法：
    python3 scripts/t2-resolve-base-patch.py
    python3 scripts/t2-resolve-base-patch.py --selftest-fuzzy-path   # 反向自证
    python3 scripts/t2-resolve-base-patch.py --limit 20              # 抽样快跑
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common as c  # noqa: E402

# ④ test / code 分侧（方案 §4 T2 原文给的正则，逐字照用）
IS_TEST = re.compile(r"(\.(test|spec)\.(ts|tsx|js|jsx)$|(^|/)tests?/)")

# ⑤ 文档剔除（§3.7 坑一：docs/bugfixes/*.md 直接写明根因与修复方案 = 答案泄漏）
DOC_PREFIXES = ("docs/",)
DOC_SUFFIXES = (".md",)

# 验收阈值（方案 §4 T2「验收」）
MIN_EXACT_RATE = 0.85
MIN_ANCHOR_RATE = 0.7
MIN_ANCHOR_QUALIFIED = 100

# 退出码
EXIT_OK = 0
EXIT_LEAK = 3  # 泄漏守卫触发（反向自证的期望结果）
EXIT_GATE = 4  # 验收未达标
#: 自证跑不起来（没有输入），⛔ 与 EXIT_LEAK/1 都不同 —— 见 main 里那段说明
EXIT_NO_INPUT = 5


def is_doc(rel: str) -> bool:
    """⑤ 是否文档路径（要从 code patch 剔除并留痕）。"""
    return rel.startswith(DOC_PREFIXES) or rel.endswith(DOC_SUFFIXES)


def fuzzy_map_repo_path(abs_path: str, repo: str | None = None) -> str | None:
    """**故意写错的**路径映射，只给 `--selftest-fuzzy-path` 用。

    这就是 §3.4 记录的那个粗糙写法 —— 它把
    `~/.claude/projects/-Users-...-person-sid-code/memory/MEMORY.md`
    也切成仓库内文件 `memory/MEMORY.md`。永远不要在主路径调用它。
    """
    if not abs_path or not isinstance(abs_path, str):
        return None
    for prefix, prefix_repo in c.REPO_PATH_PREFIXES.items():
        name = prefix.rstrip("/").rsplit("/", 1)[-1] + "/"
        if name not in abs_path:
            continue
        if repo is not None and prefix_repo != repo:
            continue
        rel = abs_path.split(name)[-1].lstrip("/")
        return rel or None
    return None


def roundtrip_ok(abs_path: str, rel: str, repo: str) -> bool:
    """泄漏守卫：`前缀 + 相对路径` 必须还原出原绝对路径。

    严格映射下这条恒成立（182 条候选实测 0 违反）。模糊切分下立刻破 ——
    所以它能同时充当「主路径守卫」与「反向自证的观测点」。
    """
    for prefix, prefix_repo in c.REPO_PATH_PREFIXES.items():
        if prefix_repo == repo:
            return prefix + rel == abs_path
    return False


def classify_dropped(abs_path: str, repo: str) -> str:
    """被严格映射丢弃的路径归类。三类后果不同，见模块 docstring。"""
    for prefix, prefix_repo in c.REPO_PATH_PREFIXES.items():
        if abs_path.startswith(prefix) and prefix_repo != repo:
            return "cross_repo"
    if "-worktrees/" in abs_path:
        return "same_repo_worktree"
    return "out_of_scope"


# ── 「是不是仓库内容」的判据：用 base 那一刻的 .gitignore ──────────

_IGNORE_DIR_CACHE: dict[tuple[str, str], Path | None] = {}
_TMPDIRS: list[tempfile.TemporaryDirectory] = []


def _ignore_workdir(repo: str, base: str) -> Path | None:
    """建一个只含 `base` 那一刻 `.gitignore` 的空仓库，供 `git check-ignore` 用。

    为什么必须取 **base 时点**而不是 HEAD 的 `.gitignore`：§3.5 已经证明工具链在漂移，
    `.gitignore` 也一样在长 —— sid-code 的 `.claude/*` 规则是后来才加的。用 HEAD 的
    规则去判一个 2026-06 的 commit，等于拿今天的标准判过去。
    """
    key = (repo, base)
    if key in _IGNORE_DIR_CACHE:
        return _IGNORE_DIR_CACHE[key]
    text = show_blob(repo, base, ".gitignore")
    if text is None:
        _IGNORE_DIR_CACHE[key] = None
        return None
    td = tempfile.TemporaryDirectory(prefix="t2-ignore-")
    _TMPDIRS.append(td)  # 进程存活期间不回收：同一个 base 会被几十条候选反复问
    work = Path(td.name)
    subprocess.run(["git", "-C", str(work), "init", "-q", "."], check=True)
    (work / ".gitignore").write_text(text, encoding="utf-8")
    _IGNORE_DIR_CACHE[key] = work
    return work


def gitignored(repo: str, base: str, rels: list[str]) -> set[str]:
    """这些相对路径里，哪些被 base 时点的 `.gitignore` 判为「不入库」。

    用 `git check-ignore` 而不是自己写 pattern 匹配 —— 因为 `.gitignore` 的语义
    远不止 glob：`.claude/*` 配 `!.claude/skills/` 的否定放行、目录不下降、
    `**` 与前导 `/` 的差别，自己实现一定漏。实测 git 的判据是对的：
    `.claude/worktrees/...` 判 ignore，`.claude/skills/eval-session/SKILL.md` 放行。
    """
    if not rels:
        return set()
    work = _ignore_workdir(repo, base)
    if work is None:
        return set()
    proc = subprocess.run(
        ["git", "-C", str(work), "check-ignore", "--stdin", "--no-index"],
        input="\n".join(rels) + "\n",
        capture_output=True,
        text=True,
    )
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


# ── base 原文读取（带缓存） ────────────────────────────────────────

_BLOB_CACHE: dict[tuple[str, str, str], str | None] = {}


def show_blob(repo: str, base: str, rel: str) -> str | None:
    """读 `base_commit` 下某文件的原文；文件在该 commit 不存在返回 None。

    返回 None **不代表失败** —— §3.4 的 36 次「文件存在于历史但不在该 commit」
    多数是会话内新建的文件，本来就不该存在，不能计入锚点失败。

    二进制文件（decode 不了）也返回 None 并计入 `binary`，让调用方淘汰该候选：
    F2P 判分靠跑测试，二进制改动既不可 diff 也不该出现在这批 task 里。
    """
    key = (repo, base, rel)
    if key in _BLOB_CACHE:
        return _BLOB_CACHE[key]
    proc = subprocess.run(
        ["git", "-C", str(c.mirror_path(repo)), "show", f"{base}:{rel}"],
        capture_output=True,
    )
    value: str | None = None
    if proc.returncode == 0:
        try:
            value = proc.stdout.decode("utf-8")
        except UnicodeDecodeError:
            value = None
    _BLOB_CACHE[key] = value
    return value


# ── ⑦ 按 Edit 序列重建全文 ────────────────────────────────────────


def apply_edits(original: str | None, seq: list[tuple[str, dict]]) -> tuple[str | None, str | None]:
    """按写操作序列重建文件终态。返回 `(终态内容, 失败原因)`。

    - `Write` 视为整文件替换（方案 §4 T2 步骤⑦原文）
    - `Edit` 用 `old_string` → `new_string`，`replace_all` 决定替换次数
    - `MultiEdit` 展开成它的 `edits` 数组依次应用

    失败即返回 `(None, 原因)` 而不是「尽力而为地跳过」：一个对不上的 Edit
    意味着后续所有 Edit 的上下文都不可信了，硬跑下去会产出一份**看着像**
    gold patch 但实际错位的 diff。宁可淘汰这条候选。

    ⚠️ `original is None`（base 里没这个文件）时从空串起手。此时首个 Edit 若带
    非空 `old_string`，说明该文件在**开发者的工作区里存在、但从未进 main**
    （实测 122 例：78 条分支未合/后被删、36 条只在别的 ref、8 条 base 之后才合入）。
    这类无法重建，按 `phantom_file` 淘汰。
    """
    current = "" if original is None else original
    is_new = original is None

    for tool_name, tool_input in seq:
        if tool_name == "Write":
            content = tool_input.get("content")
            if not isinstance(content, str):
                return None, "write_without_content"
            current = content
            continue

        edits = [tool_input] if tool_name == "Edit" else (tool_input.get("edits") or [])
        if not edits:
            return None, "empty_multiedit"
        for edit in edits:
            if not isinstance(edit, dict):
                return None, "bad_edit_entry"
            old = edit.get("old_string") or ""
            new = edit.get("new_string") or ""
            if old == "":
                # 空 old_string = 新建文件的整体写入（Edit 形态的 Write）
                current = new
                continue
            if old not in current:
                return None, "phantom_file" if is_new else "old_string_not_found"
            current = current.replace(old, new, -1 if edit.get("replace_all") else 1)
    return current, None


def make_diff(work: Path, paths: list[str]) -> str:
    """在临时 git 仓库里对指定路径出 unified diff。

    为什么用**临时 git 仓库**而不是 `git diff --no-index`：后者在新建文件上会把
    a 侧写成 `a/b/src/x.ts`（把两个比较目录名也带进了路径），需要靠 `-p2` 去凑，
    换个目录层级就错。临时仓库出的是标准 `a/<rel>` / `b/<rel>` 头，
    `git apply -p1` 直接吃，新建/删除/无末尾换行/中文全部实测通过。
    """
    if not paths:
        return ""
    proc = subprocess.run(
        ["git", "-C", str(work), "diff", "--cached", "--no-color", "--", *paths],
        capture_output=True,
        text=True,
    )
    return proc.stdout


def build_patches(repo: str, base: str, byfile: dict[str, list[tuple[str, dict]]]):
    """把每个文件的写操作序列变成 `(code_patch, test_patch, 明细)`。

    做法：临时 git 仓库里先落 base 原文并 commit，再落终态、`git add -A`，
    然后按路径分侧各出一份 diff（`--cached`）。分侧用 `git diff -- <paths>`
    而不是自己切 diff 文本 —— 切文本要处理 hunk 头、`\\ No newline`、
    重命名检测，全是自找的坑。
    """
    detail: dict[str, dict] = {}
    finals: dict[str, str] = {}
    originals: dict[str, str] = {}

    for rel, seq in byfile.items():
        original = show_blob(repo, base, rel)
        exists = original is not None
        first_tool, first_input = seq[0]

        # ⑥ 锚点校验：只看**首次** Edit（后续 Edit 的 old_string 来自前一次结果，
        #    算进去会产生假阴性 —— 方案 §4 T2 步骤⑥强调的「首次很关键」）
        anchor: bool | None = None
        if exists and first_tool != "Write":
            first_line = (first_input.get("old_string") or "").split("\n")[0]
            anchor = bool(first_line) and first_line in original

        final, reason = apply_edits(original, seq)
        detail[rel] = {
            "base_exists": exists,
            "anchor": anchor,
            "n_ops": len(seq),
            "rebuilt": final is not None,
            "fail_reason": reason,
            "is_test": bool(IS_TEST.search(rel)),
        }
        if final is None:
            continue
        finals[rel] = final
        if exists:
            originals[rel] = original

    if not finals:
        return "", "", detail

    with tempfile.TemporaryDirectory(prefix="t2-diff-") as tmp:
        work = Path(tmp)
        subprocess.run(["git", "-C", str(work), "init", "-q", "."], check=True)
        # 关掉重命名/相似度检测：我们要的是逐文件改动，不是 git 猜的重命名
        for k, v in (("user.email", "t2@bench.local"), ("user.name", "t2"), ("diff.renames", "false")):
            subprocess.run(["git", "-C", str(work), "config", k, v], check=True)

        # base 状态
        for rel, text in originals.items():
            p = work / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        subprocess.run(["git", "-C", str(work), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(work), "commit", "-q", "--allow-empty", "-m", "base"],
            check=True,
        )

        # 终态
        for rel, text in finals.items():
            p = work / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        subprocess.run(["git", "-C", str(work), "add", "-A"], check=True)

        code_paths = sorted(r for r in finals if not IS_TEST.search(r))
        test_paths = sorted(r for r in finals if IS_TEST.search(r))
        code_patch = make_diff(work, code_paths)
        test_patch = make_diff(work, test_paths)

    return code_patch, test_patch, detail


def verify_apply(repo: str, base: str, patches: list[str], rels: list[str]) -> tuple[bool, str]:
    """验收第 3 条：`code_patch` 能在 base 的 checkout 上 `git apply --check` 通过。

    在临时目录里只铺 patch 涉及的那些文件的 base 原文（不做整仓 checkout ——
    整仓要几秒，182 条就是十几分钟，而 `git apply --check` 只看它要动的文件）。
    """
    joined = "".join(p for p in patches if p)
    if not joined.strip():
        return True, "empty_patch"
    with tempfile.TemporaryDirectory(prefix="t2-apply-") as tmp:
        work = Path(tmp)
        for rel in rels:
            original = show_blob(repo, base, rel)
            if original is None:
                continue
            p = work / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(original, encoding="utf-8")
        proc = subprocess.run(
            ["git", "apply", "--check", "-p1", "-"],
            cwd=work,
            input=joined,
            capture_output=True,
            text=True,
        )
        return proc.returncode == 0, (proc.stderr.strip()[:200] or "ok")


# ── 单条候选的反解 ────────────────────────────────────────────────


def resolve_one(row: dict, *, path_mapper) -> dict:
    """反解一条候选，返回 `resolved.jsonl` 的一行（含淘汰原因时 `ok=False`）。

    `path_mapper` 注入是为了让 `--selftest-fuzzy-path` 能把模糊切分喂给**主路径**，
    而不是另写一段只验自己的自证分支。
    """
    repo = row["repo"]
    out: dict = {
        "unit_id": row["unit_id"],
        "sid": row["sid"],
        "repo": repo,
        "band": row.get("band"),
        "category": row.get("category"),
        "started_at": row["started_at"],
        # 源信息贯穿每一层：四条采集通道的模型分布不同，混算即错
        "agent_source": row.get("agent_source"),
        "model": row.get("model"),
        "vendor": row.get("vendor"),
        "batch_version": row.get("batch_version"),
    }

    # ① base_commit 反查（只查 refs/heads/main，§3.3 实测跨 ref 零收益）
    base = c.resolve_base_commit(repo, row["started_at"])
    if not base:
        out.update(base_commit=None, base_resolution="failed", ok=False, drop_reason="base_not_found")
        return out
    out["base_commit"] = base
    # 时间戳落在 mirror 的 commit 区间内就是 exact：rev-list --before 给的是
    # 「该时刻 main 的真实 HEAD」，不是近似值。nearest 只留给需要放宽的场景
    out["base_resolution"] = "exact"

    # ②③ 写操作提取 + 严格路径映射
    byfile: dict[str, list[tuple[str, dict]]] = collections.OrderedDict()
    excluded_files: list[str] = []
    dropped = collections.Counter()
    leaks: list[str] = []
    n_failed_ops = 0
    n_unparseable = 0
    n_write_actions_seen = 0

    for _, tool_name, tool_input, failed in c.iter_write_actions(row["sid"], row["step_range"]):
        n_write_actions_seen += 1
        if failed:
            # 采集当时就失败的写操作 —— 重放它等于伪造一个没发生过的改动
            n_failed_ops += 1
            continue
        if "_parse_error" in tool_input or not tool_input.get("file_path"):
            n_unparseable += 1
            continue
        abs_path = tool_input["file_path"]
        rel = path_mapper(abs_path, repo)
        if rel is None:
            dropped[classify_dropped(abs_path, repo)] += 1
            continue
        # 泄漏守卫：往返不变式。严格映射恒成立，模糊切分立刻破
        if not roundtrip_ok(abs_path, rel, repo):
            leaks.append(abs_path)
            continue
        if is_doc(rel):
            # ⑤ 文档剔除（§3.7 坑一：它写明根因与修复方案 = 答案泄漏）
            excluded_files.append(rel)
            continue
        byfile.setdefault(rel, []).append((tool_name, tool_input))

    # ③b 「在仓库目录下」不等于「是仓库内容」：用 base 时点的 .gitignore 复核一遍。
    #
    # 实测抓到的真实泄漏：`.claude/worktrees/fix-lsp-client-frame-protocol/...`。
    # 它**通过了严格前缀映射**（确实在 `/Code/person/sid-code/` 下面），但那是
    # git worktree —— 另一个分支的临时检出，本仓 .gitignore 用 `.claude/*`
    # fail-closed 挡住了它。12 条候选、214 次写操作命中。
    #
    # 后果与 `same_repo_worktree` 同级：patch 里混进了不属于 base 的文件树，
    # apply 得上去也是错的（还会把 `.git-commit-msg.tmp`、`.pr-body.tmp` 这类
    # 过程垃圾一起带进 task）。所以照 `incomplete_paths` 淘汰，不做「悄悄删掉」。
    ignored = gitignored(repo, base, sorted(byfile))
    if ignored:
        for rel in ignored:
            byfile.pop(rel, None)
        dropped["gitignored"] += len(ignored)

    out["excluded_files"] = sorted(set(excluded_files))
    out["dropped_paths"] = dict(dropped)
    out["gitignored_files"] = sorted(ignored)
    out["n_failed_ops_skipped"] = n_failed_ops
    out["n_unparseable_ops"] = n_unparseable
    #: 本条候选**读到**的写操作总数（含被跳过的）。
    # ⚠️ 它是 `--selftest-fuzzy-path` 分辨「守卫失效」与「没有输入」的唯一依据 ——
    # 没有它，两种情形在输出上逐字节一样（都是 leaked 为空）。
    out["n_write_actions_seen"] = n_write_actions_seen
    out["leaked_paths"] = leaks

    if leaks:
        out.update(ok=False, drop_reason="path_leak")
        return out
    # worktree / 跨仓 / 被 ignore 的路径 = patch 混进或缺失真代码，不能照发
    if dropped["same_repo_worktree"] or dropped["cross_repo"]:
        out.update(ok=False, drop_reason="incomplete_paths")
        return out
    if ignored:
        out.update(ok=False, drop_reason="gitignored_paths")
        return out
    if n_unparseable:
        # tool_input 被截断，这一步的改动无从恢复 → patch 必然残缺
        out.update(ok=False, drop_reason="truncated_tool_input")
        return out
    if not byfile:
        out.update(ok=False, drop_reason="no_code_ops")
        return out

    # ⑥⑦ 锚点校验 + 生成双侧 diff
    code_patch, test_patch, detail = build_patches(repo, base, byfile)
    out["files"] = detail

    anchors = [d["anchor"] for d in detail.values() if d["anchor"] is not None]
    out["anchor_hit_rate"] = round(sum(anchors) / len(anchors), 4) if anchors else None
    out["n_anchor_checked"] = len(anchors)
    out["n_new_files"] = sum(1 for d in detail.values() if not d["base_exists"])

    failed_files = {rel: d["fail_reason"] for rel, d in detail.items() if not d["rebuilt"]}
    if failed_files:
        out.update(ok=False, drop_reason="rebuild_failed", rebuild_failures=failed_files)
        return out

    out["code_patch"] = code_patch
    out["test_patch"] = test_patch
    out["n_code_files"] = sum(1 for d in detail.values() if not d["is_test"])
    out["n_test_files"] = sum(1 for d in detail.values() if d["is_test"])

    # F2P 前提（§3.6）：test 与 code 双侧都得有，否则做不出 FAIL→PASS
    if not out["n_test_files"] or not out["n_code_files"]:
        out.update(ok=False, drop_reason="not_two_sided")
        return out

    # 验收第 3 条：patch 能在 base 上 apply --check 通过
    ok_apply, apply_msg = verify_apply(repo, base, [code_patch, test_patch], sorted(detail))
    out["apply_check"] = apply_msg
    if not ok_apply:
        out.update(ok=False, drop_reason="apply_check_failed")
        return out

    rate = out["anchor_hit_rate"]
    if rate is not None and rate < MIN_ANCHOR_RATE:
        out.update(ok=False, drop_reason="anchor_below_threshold")
        return out

    out["ok"] = True
    out["drop_reason"] = None
    return out


# ── 统计与门禁 ────────────────────────────────────────────────────


def build_stats(rows: list[dict]) -> dict:
    """汇总 resolved.jsonl，并算出方案 §4 T2 的三项验收数字。"""
    ok_rows = [r for r in rows if r.get("ok")]
    exact = [r for r in rows if r.get("base_resolution") == "exact"]
    anchored = [
        r
        for r in rows
        if r.get("anchor_hit_rate") is None or (r.get("anchor_hit_rate") or 0) >= MIN_ANCHOR_RATE
    ]
    # 「锚点达标」只在真正走到锚点校验这一步的候选里算，没走到的不算达标
    anchored = [r for r in anchored if "files" in r]

    drop = collections.Counter(r.get("drop_reason") for r in rows if not r.get("ok"))
    dropped_paths = collections.Counter()
    for r in rows:
        for k, v in (r.get("dropped_paths") or {}).items():
            dropped_paths[k] += v

    return {
        "task": "T2",
        "source": str(c.CANDIDATES.relative_to(c.REPO_ROOT)),
        "n_input": len(rows),
        "n_ok": len(ok_rows),
        "acceptance": {
            "exact_rate": round(len(exact) / len(rows), 4) if rows else 0.0,
            "exact_rate_min": MIN_EXACT_RATE,
            "n_anchor_qualified": len(anchored),
            "n_anchor_qualified_min": MIN_ANCHOR_QUALIFIED,
            "n_apply_check_passed": sum(1 for r in ok_rows if r.get("apply_check")),
        },
        "drop_reasons": dict(drop.most_common()),
        "dropped_paths": dict(dropped_paths),
        "n_failed_ops_skipped": sum(r.get("n_failed_ops_skipped") or 0 for r in rows),
        "n_excluded_doc_files": sum(len(r.get("excluded_files") or []) for r in rows),
        "distributions": {
            "by_band": dict(collections.Counter(r.get("band") for r in ok_rows)),
            "by_category": dict(collections.Counter(r.get("category") for r in ok_rows)),
            "by_repo": dict(collections.Counter(r.get("repo") for r in ok_rows)),
            "by_month": dict(collections.Counter((r.get("started_at") or "")[:7] for r in ok_rows)),
        },
        "totals": {
            "code_files": sum(r.get("n_code_files") or 0 for r in ok_rows),
            "test_files": sum(r.get("n_test_files") or 0 for r in ok_rows),
            "new_files": sum(r.get("n_new_files") or 0 for r in ok_rows),
        },
    }


def check_gate(stats: dict) -> list[str]:
    """验收未达标的项。空列表 = 检查点通过。"""
    a = stats["acceptance"]
    problems = []
    if a["exact_rate"] < MIN_EXACT_RATE:
        problems.append(f"exact 占比 {a['exact_rate']:.1%} < {MIN_EXACT_RATE:.0%}")
    if a["n_anchor_qualified"] < MIN_ANCHOR_QUALIFIED:
        problems.append(f"锚点达标候选 {a['n_anchor_qualified']} < {MIN_ANCHOR_QUALIFIED}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="T2 — base_commit 反查 + patch 反解")
    ap.add_argument(
        "--selftest-fuzzy-path",
        action="store_true",
        help="反向自证：用 split('sid-code/') 模糊切分喂主路径，泄漏守卫必须报红（退出码 3）",
    )
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条（抽样快跑，不写产物）")
    args = ap.parse_args()

    if not c.CANDIDATES.exists():
        print(f"缺 T1 产物：{c.CANDIDATES}，先跑 t1-select-candidates.py", file=sys.stderr)
        return 2

    c.ensure_mvp_dirs()
    rows_in = list(c.read_jsonl(c.CANDIDATES))
    if args.limit:
        rows_in = rows_in[: args.limit]

    mapper = fuzzy_map_repo_path if args.selftest_fuzzy_path else c.map_repo_path
    if args.selftest_fuzzy_path:
        print("【反向自证】主路径改用模糊切分，期望泄漏守卫报红\n", file=sys.stderr)

    resolved = []
    for i, row in enumerate(rows_in, 1):
        resolved.append(resolve_one(row, path_mapper=mapper))
        if i % 20 == 0:
            print(f"  ... {i}/{len(rows_in)}", file=sys.stderr)

    # 反向自证：泄漏守卫必须抓到东西
    leaked = [r for r in resolved if r.get("leaked_paths")]
    if args.selftest_fuzzy_path:
        # 🔴 先分辨两件**完全不同**的事，⛔ 不许都报「守卫是失效的」：
        #
        #   ① 有写操作可读、模糊切分下守卫却没抓到 ⇒ 守卫真失效（退出 1，自证失败）
        #   ② 压根没有写操作可读 ⇒ 自证**跑不起来**（退出 EXIT_NO_INPUT）
        #
        # ② 正是公开仓的常态：`data/pulled_sessions/`（66G 原始轨迹）未随仓迁出
        # ⇒ `iter_write_actions()` 恒返回 0 条 ⇒ 守卫无从触发。
        # 把它报成「守卫是失效的」是一句**假指控**：守卫的代码好着，缺的是输入。
        # 而假指控比没有守卫更糟 —— 它训练读者忽略这行红字（同 t7-report 陈旧性守卫的纪律）。
        n_actions = sum((r.get("n_write_actions_seen") or 0) for r in resolved)
        if not leaked and not n_actions:
            print(
                f"⚠️ 自证跑不起来：{len(rows_in)} 条候选里**一个写操作都没读到** ——\n"
                f"   数据湖 {c.SESSIONS_DIR} "
                f"{'不存在' if not c.SESSIONS_DIR.exists() else '里没有对应会话'}。\n"
                "   ⛔ 这**不是**「守卫失效」：守卫要有写操作才可能触发。\n"
                "   → 要真跑这条自证，export SESSIONS_DIR 指到 trajectory-platform 的 "
                "data/pulled_sessions/",
                file=sys.stderr)
            return EXIT_NO_INPUT
        if not leaked:
            print(f"❌ 自证失败：读到 {n_actions} 个写操作，"
                  "模糊切分下泄漏守卫却一条都没抓到，守卫是失效的", file=sys.stderr)
            return 1
        samples = sorted({p for r in leaked for p in r["leaked_paths"]})
        print(f"✅ 泄漏守卫生效：{len(leaked)} 条候选被拦下，泄漏路径 {len(samples)} 个", file=sys.stderr)
        for p in samples[:5]:
            print(f"   LEAK  {p}", file=sys.stderr)
        print(f"\n退出码 {EXIT_LEAK} = 守卫按预期报红（这是自证的期望结果）", file=sys.stderr)
        return EXIT_LEAK

    if leaked:
        # 主路径不该出现泄漏。出现了就是 REPO_PATH_PREFIXES 被改坏了
        print(f"❌ 主路径出现 {len(leaked)} 条路径泄漏，往返不变式被破 —— 检查 REPO_PATH_PREFIXES", file=sys.stderr)
        for r in leaked[:3]:
            print(f"   {r['unit_id']}: {r['leaked_paths'][:2]}", file=sys.stderr)
        return EXIT_LEAK

    stats = build_stats(resolved)
    if args.limit:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        print(f"\n（--limit {args.limit} 抽样模式，未写产物）", file=sys.stderr)
        return EXIT_OK

    c.write_jsonl(c.RESOLVED, resolved)
    stats_path = c.MVP_META / "resolved.stats.json"
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    a = stats["acceptance"]
    print(f"\n输入 {stats['n_input']} 条 → 反解成功 {stats['n_ok']} 条")
    print(f"  exact 占比        {a['exact_rate']:.1%}  (阈值 ≥{MIN_EXACT_RATE:.0%})")
    print(f"  锚点达标候选      {a['n_anchor_qualified']}  (阈值 ≥{MIN_ANCHOR_QUALIFIED})")
    print(f"  apply --check 过  {a['n_apply_check_passed']}")
    print(f"  跳过的失败写操作  {stats['n_failed_ops_skipped']}")
    print(f"  剔除的文档文件    {stats['n_excluded_doc_files']}")
    print("\n淘汰原因：")
    for k, v in stats["drop_reasons"].items():
        print(f"  {v:4d}  {k}")
    print(f"\n产物：{c.RESOLVED}\n      {stats_path}")

    problems = check_gate(stats)
    if problems:
        print("\n❌ 检查点未通过：", file=sys.stderr)
        for p in problems:
            print(f"   - {p}", file=sys.stderr)
        return EXIT_GATE
    print("\n✅ 检查点通过（exact 与锚点两项均达标）")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
