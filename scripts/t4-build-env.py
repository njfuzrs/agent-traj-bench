#!/usr/bin/env python3
"""T4 — env 镜像 + 仓库快照（剔除泄漏面）+ 步骤④与 T2 的交叉验收

出处：`docs-research/trajectory-platform/bench-mvp-plan.md` v1.2 §4 T4（1.5 天）

输入：mirror（只读）+ `resolved.jsonl`（T2 产物，70 条 ok）
输出：`bench/v0.2-mini/tasks/T####/environment/{Dockerfile,repo-snapshot.tar.gz}`
      + `meta/snapshots.jsonl`（剔除清单 + 校验和，供 T3 回写 meta.json 的 snapshot 字段）
      + `reports/t4-env.md`

## 四个步骤（方案原文顺序即实现顺序）

    ① git archive 导出 base 状态       —— 不用 bundle（refspec 对裸 commit 不友好）
    ② 容器内 git init 重建单 commit    —— test.sh 要 git apply / git checkout -- tests/
    ③ 剔除泄漏面（§3.8-E，不能省）
    ④ 与 T2 的交叉验收（§4.9 衔接②）  —— 在**剔除后的快照**上重验 apply --check

## 为什么步骤④不能省（这是本 task 的核心价值）

T2 在 **mirror 真实 commit** 上验 `git apply --check`，T4 的快照**剔除过泄漏路径**。
patch 若触及被剔除的路径，**两处验收都通过、容器里必然失败** —— 单看 T2 或单看 T4
都发现不了。这是 §3.8-F「绿着坏掉」的典型形态。

## ⚠️ 实测推翻了方案的一个前提（本轮最重要的一条）

方案 §3.8-E 假定「剔除 `packages/eval-framework/` 会打断 `bun install`，
打断就淘汰该 task」。**实测证明这个因果是错的，照方案的预案执行会白淘汰 47 条。**

用**未剔除的对照镜像**跑同一条 `bun install --frozen-lockfile`：
同样报 `ENOENT: failed opening cache/package/version dir for package eval-framework`。
根因是 50 条 sid base 里有 47 条把它声明成 **`file:../eval-framework`** ——
指向**仓库外**的兄弟目录，**任何快照里都不可能有它**，与剔除无关。

所以两个分支的机理必须分开处理（判据写在 `_eval_framework_mode()`）：

  - `file:` 外部路径（47 条）：**剔除无关**。在镜像里 `/eval-framework` 造一个
    最小 stub 闭合 resolver。stub 在 `/repo` **之外**，不属于仓库内容；且实测
    快照内**零处 import 它**（`grep -rlE "from|require\\(|import\\(" 'eval-framework'`
    命中 0），所以它是**可证不参与判分**的死物。
  - `workspace:*` 仓库内（3 条 monorepo base）：**剔除确实打断它**。此时保留
    `packages/eval-framework/package.json` **这一个 manifest**、剔掉其余全部内容。
    ⚠️ 合成一个 stub manifest 试过，破 `--frozen-lockfile`（真 manifest 的 deps
    在 bun.lock 里有记录），所以必须留真的那份。残余泄漏面已核：它只有
    name/version/deps 与 `"eval:run": "bun run core/runner.ts"` 一条指针，
    而 `core/runner.ts` 已被剔除 —— **判分逻辑本体不在里面**。

教训与 §3.8-F 同源：**「剔除后坏了」≠「剔除导致坏了」**。要先跑未剔除的对照，
否则会把「本来就坏」记成自己的锅，反向淘汰掉一批本可用的 task。

## ⚠️ `lstrip('./')` 是字符集剥离，不是前缀剥离（我自己的探针中过这一枪）

`'.claude/x'.lstrip('./')` → `'claude/x'`，于是 `.claude/` 前缀**整个漏剔**。
必须用 `removeprefix('./')`。这一枪是**容器内泄漏扫描**抓出来的 ——
所以扫描要在容器内查实际文件树（§4.9 T4 行「泄漏扫描在容器内查」），
不能只信自己的剔除计数。

## ⚠️ 剔除必须「顶层锚定」，不能按子串匹配

实测：`packages/core/src/skill/builtin/*/evals/` 下有 61 个文件是 **skill 的
baseline case，属于真实仓库资产**，且 `tests/skill/code-review.test.ts:66`
明确断言 `evals/` 目录存在。按子串剔 `evals` 会打断这些**存活测试**。
所以判据是 `n == p or n.startswith(p)`（p 自带尾 `/`），只锚顶层。

## ⚠️ `git add -A` 会漏掉「被 gitignore 但已入库」的文件

iam 的 `anka-app/pnpm-lock.yaml` 正是这种。漏了它 `--frozen-lockfile` 直接失败。
必须 `git add -A -f`。

## 运行期网络

运行期 `--network none`（避免 agent 联网找答案），所以依赖**必须在构建期装好**。
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common as c  # noqa: E402

EXIT_OK = 0
EXIT_GATE = 1  # 交叉验收未过
EXIT_LEAK = 3  # 泄漏守卫触发（反向自证的期望结果）

# ── 泄漏面清单（§3.8-E + scripts/phase0/excluded-paths.txt） ──────────
#
# 语义 = **顶层前缀**匹配。尾 `/` 是契约的一部分，别删（`evals` 会误命中
# `evals-foo/`，也会命中嵌套的 skill evals —— 后者是真实资产，见模块 docstring）。
LEAK_PREFIXES = (
    "evals/",  # §3.8-E：harbor 自身 + 判分校准集，705 文件
    "packages/eval-framework/",  # 判分引擎本体（monorepo 布局下）
    "scripts/eval/",  # 评测 runner
    "tests/eval/",  # 评测自身的测试
    "docs/bugfixes/",  # §3.7 坑一：直接写着解法
    ".claude/",  # agent 会话上下文
)

#: 精确路径剔除（**文件粒度，不是前缀**）。
#:
#: 这四个是**容器内泄漏扫描抓出来的漏网**（不是推演出来的）—— 前缀清单只锚顶层目录，
#: 而这些评测工作流散落在 `.github/workflows/` 下，与 `ci.yml` / `docs-lint.yml`
#: 这类无关资产同目录，所以**不能整剔 `.github/`**，只能点名。
#:
#: 判据（每条都实测过）：
#:   - 它们点名 `evals/**`、`scripts/eval/**`、`evals/_judge/calibration-set/`
#:     —— 正是 §3.8-E 列的「harbor 自身 + 判分校准集」，且 `judge-calibration.yml`
#:     把校准集路径与 pairwise 判分方法写在注释里，是**直接的判分逻辑泄漏**。
#:   - 存活测试不依赖仓库这份 `.github`：`tests/tool/glob.test.ts:19` 是
#:     `mkdirSync(join(root, ".github"))` 在**临时目录**里自建的，剔除不影响它。
LEAK_FILES = frozenset(
    {
        ".github/workflows/eval-weekly.yml",
        ".github/workflows/eval-pr-smoke.yml",
        ".github/workflows/judge-calibration.yml",
        ".github/workflows/northstar-weekly.yml",
    }
)

#: monorepo 分支唯一被豁免的路径 —— 只保留 manifest，内容全剔。理由见 docstring。
WORKSPACE_ANCHOR = "packages/eval-framework/package.json"

#: 容器内 stub 的挂载点。**在 /repo 之外**，所以不属于仓库内容、不进泄漏面。
EXTERNAL_STUB_DIR = "/eval-framework"

SNAPSHOTS = c.MVP_META / "snapshots.jsonl"
REPORT = c.MVP_REPORTS / "t4-env.md"

# iam-studio-fe：内网 registry + 凭据，构建期装不了依赖。判据见 IAM_BLOCK_REASON。
IAM_REPO = "ruijie/iam-studio-fe"
#: ⚠️ 措辞刻意不写内网 registry 的 IP:端口。判读只需要「私有 registry + 需凭据」这个
#: 事实，具体地址对下游零价值，而 `snapshots.jsonl` 是要入库的产物 —— 写进去等于凭
#: 白增加一处内网拓扑暴露面。要查实际地址去看 base 时点的 `anka-app/.npmrc`。
IAM_BLOCK_REASON = (
    "依赖私有 registry（内网，地址见 base 时点的 anka-app/.npmrc）且该 .npmrc 携带 "
    "_authToken：@ruijie/{utils,eslint-config,typescript-config,crypto-interceptor} "
    "只在内网有，公网 registry 404（实测 ERR_PNPM_FETCH_404）。运行期 --network none "
    "要求依赖在构建期装好，而装它必须把凭据烤进镜像 —— 违反「不在容器里配私钥」（§T4）。"
)


def strip_leaks(name: str) -> bool:
    """这个 tar 成员是否该被剔除。

    `removeprefix` 而不是 `lstrip` —— 后者是字符集剥离，会把 `.claude/` 啃成
    `claude/` 导致整个前缀漏剔（模块 docstring 有实测）。
    """
    n = name.removeprefix("./")
    if n == WORKSPACE_ANCHOR:  # 是否真豁免由调用方按 base 的依赖形态决定
        return False
    if n in LEAK_FILES:
        return True
    return any(n == p.rstrip("/") or n.startswith(p) for p in LEAK_PREFIXES)


def _read_blob(repo: str, base: str, rel: str) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(c.mirror_path(repo)), "show", f"{base}:{rel}"],
        capture_output=True,
        text=True,
    )
    return proc.stdout if proc.returncode == 0 else None


def eval_framework_mode(repo: str, base: str) -> str:
    """这条 base 的 `eval-framework` 依赖是哪种形态 —— 决定用哪个分支的处置。

    返回 `workspace` / `external` / `absent`。判据取自 base 时点的
    `package.json`，不看 HEAD（§3.5：工具链在漂移）。
    """
    txt = _read_blob(repo, base, "package.json")
    if txt is None:
        return "absent"
    try:
        pkg = json.loads(txt)
    except json.JSONDecodeError:
        return "absent"
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    spec = deps.get("eval-framework")
    if spec is None:
        return "absent"
    if isinstance(spec, str) and spec.startswith("workspace:"):
        return "workspace"
    return "external"


def build_snapshot(repo: str, base: str, mode: str) -> tuple[bytes, dict]:
    """步骤①+③：`git archive` 导出 base，边流边剔泄漏面，返回 (gz 字节, 统计)。

    不落中间 tar 到磁盘 —— 54 个 base 各 23MB，没必要在工作区堆一遍。
    """
    raw = subprocess.run(
        ["git", "-C", str(c.mirror_path(repo)), "archive", "--format=tar", base],
        capture_output=True,
    )
    if raw.returncode != 0:
        raise RuntimeError(f"git archive 失败: {repo}@{base[:8]}\n{raw.stderr.decode()[:400]}")

    keep_anchor = mode == "workspace"
    stripped: list[str] = []
    kept = 0
    buf = io.BytesIO()
    with tarfile.open(fileobj=io.BytesIO(raw.stdout)) as src, tarfile.open(fileobj=buf, mode="w") as dst:
        for m in src.getmembers():
            n = m.name.removeprefix("./")
            if n == WORKSPACE_ANCHOR and not keep_anchor:
                # 不是 monorepo 分支：这个 manifest 也是泄漏面的一部分，照剔
                stripped.append(n)
                continue
            if strip_leaks(m.name):
                if m.isfile():
                    stripped.append(n)
                continue
            dst.addfile(m, src.extractfile(m) if m.isfile() else None)
            if m.isfile():
                kept += 1

    gz = gzip.compress(buf.getvalue(), 6)
    return gz, {
        "n_files_kept": kept,
        "n_files_stripped": len(stripped),
        "stripped_sample": sorted(stripped)[:20],
        "stripped_top_dirs": sorted({s.split("/")[0] for s in stripped}),
        "workspace_anchor_kept": keep_anchor,
    }


def dockerfile_for(repo: str, mode: str, test_cmd: str) -> str:
    """生成 Dockerfile。

    `git add -A -f` 的 `-f` 不能省 —— 「被 gitignore 但已入库」的文件（iam 的
    `pnpm-lock.yaml`）否则会被漏掉，`--frozen-lockfile` 直接失败。
    """
    stub = ""
    if mode == "external":
        # `file:../eval-framework` 指向仓库外，任何快照都没有它（**剔除前就没有**，
        # 已用未剔除的对照镜像证过）。造最小 stub 闭合 resolver；它在 /repo 之外，
        # 且快照内零处 import 它 —— 可证不参与判分。
        stub = (
            f"RUN mkdir -p {EXTERNAL_STUB_DIR} \\\n"
            f' && printf \'{{"name":"eval-framework","version":"0.1.0","private":true}}\\n\''
            f" > {EXTERNAL_STUB_DIR}/package.json\n"
        )
    return f"""# T4 生成，勿手改。repo={repo} mode={mode}
FROM oven/bun:1.3.14
RUN apt-get update && apt-get install -y --no-install-recommends \\
        git make python3 ripgrep \\
    && rm -rf /var/lib/apt/lists/*
{stub}WORKDIR /repo
COPY repo-snapshot.tar.gz /tmp/
# ② 容器内 git init 重建 base：test.sh 需要 git apply 打 test_patch、
#    以及 git checkout -- tests/ 还原被 agent 动过的测试。且**不带任何历史** ——
#    顺带消除「agent 翻 git log 找答案」这条泄漏路径。
#    -f：见本文件 dockerfile_for() 的 docstring（gitignore 但已入库的文件）
RUN tar -xzf /tmp/repo-snapshot.tar.gz -C /repo \\
    && rm /tmp/repo-snapshot.tar.gz \\
    && git init -q -b main \\
    && git add -A -f \\
    && git -c user.email=bench@local -c user.name=bench commit -qm "base state" \\
    && bun install --frozen-lockfile
# 运行期 --network none，所以依赖必须在上面这层装好
ENV CI=1
# 判分用的测试命令（从 base 时点的 package.json 读，§3.5）：{test_cmd}
"""


def cross_verify(gz: bytes, row: dict) -> dict:
    """步骤④：在**剔除后的快照**上重验 T2 的 patch（§4.9 衔接②）。

    在宿主解包到临时目录做 `git apply --check`，与容器内 `git init` 后的文件树
    等价（同一份 tar、同一套剔除）。不起容器是因为这一步只看文件在不在、
    上下文对不对 —— 起 54 个容器纯浪费。
    """
    import tempfile

    result: dict = {"cross_apply_check": {}, "cross_ok": True, "cross_fail_reason": None}
    with tempfile.TemporaryDirectory(prefix="t4-cross-") as td:
        work = Path(td)
        with tarfile.open(fileobj=io.BytesIO(gzip.decompress(gz))) as tf:
            tf.extractall(work, filter="data")
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=work, check=True)
        subprocess.run(["git", "add", "-A", "-f"], cwd=work, capture_output=True)
        subprocess.run(
            ["git", "-c", "user.email=b@l", "-c", "user.name=b", "commit", "-qm", "base"],
            cwd=work,
            capture_output=True,
        )
        # ① patch 触及的路径是否被剔掉了 —— 这正是「两层各自都绿」的破口
        touched = sorted(row.get("files") or {})
        killed = [p for p in touched if strip_leaks(p)]
        if killed:
            result.update(cross_ok=False, cross_fail_reason=f"patch 触及被剔除路径: {killed}")
            result["cross_killed_paths"] = killed
            return result
        for kind in ("test_patch", "code_patch"):
            patch = row.get(kind) or ""
            if not patch.strip():
                result["cross_apply_check"][kind] = "empty"
                continue
            proc = subprocess.run(
                ["git", "apply", "--check", "-p1", "-"],
                cwd=work,
                input=patch,
                capture_output=True,
                text=True,
            )
            ok = proc.returncode == 0
            result["cross_apply_check"][kind] = "ok" if ok else proc.stderr.strip()[:300]
            if not ok:
                result.update(cross_ok=False, cross_fail_reason=f"{kind} apply --check 失败")
    return result


def selftest_substring_leak(rows: list[dict]) -> int:
    """反向自证：把「顶层锚定」退化成「子串匹配」，泄漏守卫必须报红。

    ⚠️ **这个自证自己坏过一次，值得记下形态。** 第一版写成「剔除量 > 900 就算报红」，
    实测最大只有 829 —— 阈值是拍的，于是自证**自称检查却永远是绿的**，
    正是它要防的那类「绿着坏掉」。

    修法：不比绝对值，比**同一个 base 上严格版与退化版的差分**。
    判据是不变式而非魔法数 —— 退化后必然多剔到 `packages/.../skill/builtin/*/evals/`
    这类真实资产（`tests/skill/code-review.test.ts:66` 明确断言它们存在），
    所以「多剔量 > 0」就是守卫该报红的充分条件。
    """
    strict = t = 0
    worst: list[tuple[str, int, list[str]]] = []
    for row in rows:
        if row["repo"] == IAM_REPO:
            continue
        repo, base = row["repo"], row["base_commit"]
        mode = eval_framework_mode(repo, base)
        _, s_strict = build_snapshot(repo, base, mode)

        global strip_leaks
        keep = strip_leaks
        try:
            strip_leaks = lambda name: any(  # noqa: E731
                p.rstrip("/") in name.removeprefix("./") for p in LEAK_PREFIXES
            )
            _, s_loose = build_snapshot(repo, base, mode)
        finally:
            strip_leaks = keep

        extra = s_loose["n_files_stripped"] - s_strict["n_files_stripped"]
        t += 1
        if extra > 0:
            strict += 1
            worst.append((base[:8], extra, s_loose["stripped_sample"][:2]))

    if strict == 0:
        print(f"🔴 自证失败：{t} 条 base 退化成子串匹配后，剔除量一条都没变", file=sys.stderr)
        return EXIT_GATE
    print(f"✅ 泄漏守卫生效：{strict}/{t} 条 base 在退化后误剔了真实资产", file=sys.stderr)
    for b, n, sample in worst[:5]:
        print(f"   {b} 多剔 {n} 个，例如 {sample}", file=sys.stderr)
    print(f"\n退出码 {EXIT_LEAK} = 反向自证的期望结果", file=sys.stderr)
    return EXIT_LEAK


def main() -> int:
    ap = argparse.ArgumentParser(description="T4 — env 镜像 + 仓库快照 + 步骤④交叉验收")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条（调试用）")
    ap.add_argument("--tasks-dir", default=None, help="覆盖 task 输出根目录")
    ap.add_argument(
        "--selftest-substring-leak",
        action="store_true",
        help="反向自证：把顶层锚定退化成子串匹配，泄漏守卫必须报红（退出码 3）",
    )
    ap.add_argument("--no-write", action="store_true", help="只跑验收，不落快照")
    args = ap.parse_args()

    c.ensure_mvp_dirs()
    tasks_dir = Path(args.tasks_dir) if args.tasks_dir else c.MVP_TASKS
    tasks_dir.mkdir(parents=True, exist_ok=True)

    rows = [r for r in c.read_jsonl(c.RESOLVED) if r.get("ok")]
    if args.limit:
        rows = rows[: args.limit]
    print(f"T2 交付 ok 候选：{len(rows)} 条", file=sys.stderr)

    if args.selftest_substring_leak:
        return selftest_substring_leak(rows)

    out_rows: list[dict] = []
    for i, row in enumerate(sorted(rows, key=lambda r: r["unit_id"]), start=1):
        tid = f"T{i:04d}"
        repo, base = row["repo"], row["base_commit"]
        rec: dict = {
            "task_id": tid,
            "unit_id": row["unit_id"],
            "repo": repo,
            "base_commit": base,
            "band": row.get("band"),
        }
        if repo == IAM_REPO:
            rec.update(ok=False, drop_reason="registry_unreachable", detail=IAM_BLOCK_REASON)
            out_rows.append(rec)
            continue
        mode = eval_framework_mode(repo, base)
        test_cmd = "bun test"
        pj = _read_blob(repo, base, "package.json")
        if pj:
            try:
                test_cmd = (json.loads(pj).get("scripts") or {}).get("test") or "bun test"
            except json.JSONDecodeError:
                pass
        gz, snap = build_snapshot(repo, base, mode)
        rec.update(snap)
        rec["eval_framework_mode"] = mode
        rec["test_cmd"] = test_cmd
        rec["tar_sha256"] = hashlib.sha256(gz).hexdigest()
        rec["tar_bytes"] = len(gz)
        rec.update(cross_verify(gz, row))
        rec["ok"] = bool(rec["cross_ok"])
        if not args.no_write and rec["ok"]:
            env = tasks_dir / tid / "environment"
            env.mkdir(parents=True, exist_ok=True)
            (env / "repo-snapshot.tar.gz").write_bytes(gz)
            (env / "Dockerfile").write_text(dockerfile_for(repo, mode, test_cmd), encoding="utf-8")
        out_rows.append(rec)
        if i % 10 == 0:
            print(f"  ... {i}/{len(rows)}", file=sys.stderr)

    built = [r for r in out_rows if r.get("ok")]
    crossfail = [r for r in out_rows if r.get("cross_ok") is False]
    blocked = [r for r in out_rows if r.get("drop_reason") == "registry_unreachable"]

    if not args.no_write:
        c.write_jsonl(SNAPSHOTS, out_rows)

    print(
        f"\n快照产出 {len(built)} / 交叉验收失败 {len(crossfail)} / env 不可构建 {len(blocked)}",
        file=sys.stderr,
    )

    if crossfail:
        print("🔴 步骤④交叉验收未过：", file=sys.stderr)
        for r in crossfail[:10]:
            print(f"   {r['task_id']} {r['unit_id'][:12]} {r['cross_fail_reason']}", file=sys.stderr)
        return EXIT_GATE
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
