#!/usr/bin/env python3
"""common.py — Agent-Traj-Bench v0.2-mini（MVP 最小闭环）的公共契约

出处：`docs-research/trajectory-platform/bench-mvp-plan.md` v1.2 §4 T0

本模块只放**T1-T7 都要遵守的契约**，不放业务逻辑：

  1. 目录布局：产物一律写**仓库根**（`tasks/` `meta/` `reports/`），原始层与 mirror 只读
     ⚠️ 源仓（trajectory-platform）里这一层是 `bench/v0.2-mini/`；拆仓时 subtree split
     已去掉该前缀 ⇒ 本仓的产物根就是 `REPO_ROOT`，见下方 `MVP_DIR`。
  2. `tool_input` 解析：JSON 与 Python repr 双兼容（§3.2）
  3. 路径映射：严格前缀匹配，不用模糊切分（§3.4）
  4. mirror 只读访问：一律 `git -C $MIRROR`（§3.3）
  5. 难度分档：按 `edit_ops` 现算，不用 Phase 1 的 `difficulty`（§3.7 坑二）

## 为什么与 scripts/phase0 / phase1 / phase2 隔离（§4 T0）

那三套各自已有一套目录与字段约定，再往里塞会互相污染。MVP 的脚本要能
**独立跑、独立删** —— 所以自成一套脚本目录（源仓 `scripts/mvp/`，公开仓 `scripts/`），只读它们的产物，不改它们的代码。

## 四条纪律（方案 §4 T0「关键约定」，每条都有单测盯着）

1. **`data/pulled_sessions/` 只读**。`pull.py:246` 的去重只查
   `data/pulled_sessions/<sid>/.pulled`，把会话目录移走/改名/删除，标记就跟着走，
   下次同步判为「未拉取」并重新下载 —— 上一轮把 1722 条移进 `_trash/` 正是如此。
2. **mirror 只读**。所有 git 操作走 `git -C $MIRROR`，不 clone 到工作区（T4 例外）。
3. **`bench/` v0.1 的 844 条不动**。v0.2-mini 是新目录，不覆盖、不迁移。
4. **不改 harbor 底座里的任何文件**。
   `sid-code/evals/external-benchmarks/harbor/` 是它自己的资产
   （`registry.local.json` 是已发表结论的取数源，动它等于让旧结论不可复算）。
   我们只**调用** `harbor run`，产物全部落 trajectory-platform 侧。

## TZ 实测补充的一条硬约束（不在方案原文，见 reports/tz-preflight.md R-3）

**harbor 的 jobs 目录（`-o`）必须落在 `$HOME` 之下，不许用 `/tmp`。**
harbor 的 docker environment 声明 `capabilities.mounted=True`
（`environments/docker/docker.py:303`），于是 `verifier/verifier.py:203` 跳过 download，
假定 trial 目录是 bind mount。而本机 colima 的 `mounts: []` —— VM 内只挂了
`$HOME` 一个 virtiofs，**宿主 `/tmp` 不在 VM 里**。用 `/tmp` 的形态是
`RewardFileNotFoundError`，它指向「reward 没写」这个错误方向，真因是「写了但宿主看不见」。
`assert_jobs_dir_ok()` 把这条固定住。
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
from pathlib import Path

# ── 目录布局 ────────────────────────────────────────────────────────

# ⚠️ 公开仓的布局与 trajectory-platform 不同：题集是**仓库根**，不再是 `bench/v0.2-mini/`
# 子目录，且脚本从 `scripts/mvp/` 提到了 `scripts/` ⇒ 少一级目录。
# 原写法 `parent.parent.parent` 在这里会指到**仓库外面**（`~/Code/person`），
# 形态是「所有脚本都读不到 tasks/」而不指向路径常量 —— 所以固定为 parents[1]。
REPO_ROOT = Path(__file__).resolve().parents[1]

# 只读数据湖。本模块及下游脚本**只允许 open() 读**，不许写、不许移、不许删。
# 🔴 公开仓**不含** `data/`（66G，未入库）⇒ 这两个常量在本仓指向不存在的路径是**预期的**。
# 它们只被 T1/T2（从原始轨迹反解题面）用到，而公开仓的 tasks/ 已是成品 ⇒ 无需重跑 T1/T2。
# 要重跑须用环境变量指到 trajectory-platform 那侧的真实目录。
SESSIONS_DIR = Path(os.environ.get("SESSIONS_DIR", REPO_ROOT / "data/pulled_sessions"))

# Phase 1 的产物（7692 个已标注单元），只读 —— T1 的唯一输入
LABELED_V2 = Path(os.environ.get("LABELED_V2", REPO_ROOT / "data/bench-staging/phase1/meta/labeled-v2.jsonl"))

# 本方案的产物根。⚠️ 公开仓里题集就在仓库根（tasks/ meta/ reports/ 与 scripts/ 平级），
# ⛔ 不是 `bench/v0.2-mini/` —— 拆仓时 subtree split 已把那层前缀去掉。
MVP_DIR = Path(os.environ.get("MVP_DIR", REPO_ROOT))
MVP_META = MVP_DIR / "meta"
MVP_TASKS = MVP_DIR / "tasks"
MVP_REPORTS = MVP_DIR / "reports"

#: 本脚本目录相对仓库根的写法，供**写进产物或打给用户看**的命令串使用。
#
# 🔴 ⛔ 不许在任何字符串里写死 `scripts/mvp/` —— 那是源仓（trajectory-platform）的布局。
# 公开仓拆出来后脚本在 `scripts/`，写死的形态是**提示语与 meta.json 里的命令全指向
# 一个不存在的路径**，而脚本本身照常跑通、门禁也全绿（门禁④ 只拦 `/Users/` 绝对路径）
# ⇒ 只有照着提示敲命令的人会撞上 `No such file or directory`。
# 同 `t7-report.py` 的 `SCRIPTS_REL`（§5.5），从实际布局现推。
SCRIPTS_REL = Path(__file__).resolve().parent.name

CANDIDATES = MVP_META / "candidates.jsonl"  # T1 产物
CANDIDATES_STATS = MVP_META / "candidates.stats.json"
RESOLVED = MVP_META / "resolved.jsonl"  # T2 产物

# mirror 归档（bare，只读）。§3.3：18 个仓库的归档
MIRRORS_DIR = Path(os.environ.get("MIRRORS_DIR", Path.home() / "Code/_archive/bench-mirrors"))

# 本方案只做这两个仓库（§4 T1 条件②）。值是 mirror 的 bare 目录名
REPO_MIRRORS = {
    "person/sid-code": "person_sid-code.git",
    "ruijie/iam-studio-fe": "ruijie_iam-studio-fe.git",
}

# 轨迹里的绝对路径 → 仓库。**必须严格前缀匹配**，见 map_repo_path 的 docstring
#
# ⚠️ 这里原本写死了采集那台机器的 `/Users/<user>/Code/...` 前缀。公开仓不许留本机绝对路径
# （CI 门禁④ 会拦），且**别人 clone 后前缀本来就不同** ⇒ 改为两级环境变量可覆盖：
#   CODE_ROOT      —— 存放各仓库的父目录，默认 `~/Code`
#   SID_CODE_PATH  —— 单独覆盖 sid-code 的路径（上游 §5.1 点名的那个）
# 🔴 值必须以 `/` 结尾：map_repo_path 是严格前缀匹配，少了斜杠会让
# `.../sid-code-worktrees/...` 被误判成 `person/sid-code`（单测 test_mvp.py 盯着这条）。
CODE_ROOT = Path(os.environ.get("CODE_ROOT", Path.home() / "Code"))

REPO_PATH_PREFIXES = {
    os.environ.get("SID_CODE_PATH", f"{CODE_ROOT}/person/sid-code") + "/": "person/sid-code",
    f"{CODE_ROOT}/ruijie/iam-studio-fe/": "ruijie/iam-studio-fe",
}


def ensure_mvp_dirs() -> None:
    """建齐 v0.2-mini 的产物目录。只新建，不动 bench/ 下 v0.1 的任何东西。"""
    for d in (MVP_META, MVP_TASKS, MVP_REPORTS):
        d.mkdir(parents=True, exist_ok=True)


# ── tool_input 解析（§3.2） ─────────────────────────────────────────


def parse_tool_input(value):
    """把轨迹里的 `tool_input` 解析成 dict。

    §3.2 记录的坑：**`tool_input` 可能是 Python repr 字符串，不是 JSON**
    （单引号、`False` / `True` / `None`）。所以必须 `json.loads` 与
    `ast.literal_eval` 两者都试 —— 只用 `json.loads` 会在 repr 输入上静默失败，
    形态是「patch 反解出来是空的」，不指向解析器。

    T0 实测补充（60 个候选会话、4933 个 tool 调用）：本项目切片里
    `tool_input` **全部已是 dict**（4933/4933），str 型 0 次。
    所以 dict 直返是主路径，两个解析器是**防御性**的 ——
    `data/pulled_sessions/` 是持续增长的数据湖，采集侧格式一变就会用上。

    解析不出来返回 `{}`（而不是抛异常）：调用方按「这一步没有可用参数」跳过，
    单条脏数据不该让整批反解中断。
    """
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    for fn in (json.loads, ast.literal_eval):
        try:
            parsed = fn(value)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def iter_traj_actions(sid: str, step_range: tuple[int, int] | list[int] | None = None):
    """按顺序产出某会话的 action step（已带解析好的 `tool_input`）。

    产出 `(index, tool_name, tool_input_dict)`。`step_range` 给 `[start, end]`
    闭区间时只产出区间内的 step —— 单元的 `step_range` 字段就是这个口径。

    只读 `data/pulled_sessions/<sid>/session.traj`（纪律 1）。文件不存在或解析
    失败就产出空序列，让调用方按「这条候选取不到轨迹」淘汰。
    """
    path = SESSIONS_DIR / sid / "session.traj"
    if not path.exists():
        return
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except Exception:
        return

    lo, hi = (step_range[0], step_range[1]) if step_range else (None, None)
    for i, step in enumerate(doc.get("trajectory") or []):
        if lo is not None and hi is not None and not (lo <= i <= hi):
            continue
        tool_name = step.get("tool_name")
        if not tool_name:
            continue
        yield i, tool_name, parse_tool_input(step.get("tool_input"))


# ── 路径映射（§3.4） ───────────────────────────────────────────────


def map_repo_path(abs_path: str, repo: str | None = None) -> str | None:
    """把轨迹里的绝对路径映射成仓库内相对路径；不属于目标仓库返回 None。

    §3.4 的实测结论：锚点命中率 145/205，其中 **21 次失败是路径映射粗糙导致的**
    （混进了 `.claude/projects/memory/` 与跨仓 `iam-studio-fe` 路径），
    而真实失败只有 3 次。

    所以这里**只认完整前缀**（`REPO_PATH_PREFIXES`），
    **绝不能用 `split('sid-code/')` 这类模糊切分** —— 那会把
    `~/.claude/projects/.../sid-code/xxx` 也当成仓库内文件，
    形态是「锚点校验失败率虚高」，看着像轨迹质量差，其实是映射写糙了。

    `repo` 给定时，只接受该仓库的前缀（跨仓路径返回 None）。
    """
    if not abs_path or not isinstance(abs_path, str):
        return None
    for prefix, prefix_repo in REPO_PATH_PREFIXES.items():
        if not abs_path.startswith(prefix):
            continue
        if repo is not None and prefix_repo != repo:
            return None
        rel = abs_path[len(prefix) :].lstrip("/")
        # 前缀命中但没有后续路径（就是仓库根本身），不算文件
        return rel or None
    return None


# ── mirror 只读访问（§3.3） ────────────────────────────────────────


def mirror_path(repo: str) -> Path:
    """仓库名 → mirror 的 bare 目录。仓库不在名单里直接抛，不猜。"""
    name = REPO_MIRRORS.get(repo)
    if name is None:
        raise KeyError(f"仓库不在 MVP 名单内: {repo!r}（只做 {sorted(REPO_MIRRORS)}）")
    return MIRRORS_DIR / name


def git_mirror(repo: str, *args: str, check: bool = True) -> str:
    """在 mirror 上跑只读 git 命令，返回 stdout（已 strip）。

    纪律 2：**一律 `git -C $MIRROR`，不 clone 到工作区**（T4 例外，它要出快照）。
    """
    cmd = ["git", "-C", str(mirror_path(repo)), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"git 失败（{proc.returncode}）: {' '.join(cmd)}\n{proc.stderr}")
    return proc.stdout.strip()


def resolve_base_commit(repo: str, before_iso: str) -> str | None:
    """按时间戳从 mirror 反查 base_commit（§3.3）。

    §3.3 实测：**只查 `refs/heads/main`，不要写复杂的多 ref 搜索** ——
    只查 main 与遍历 `--all` 前 30 个候选的锚点命中率完全相同（17 vs 17），
    多 ref 搜索是纯复杂度、零收益。
    """
    out = git_mirror(repo, "rev-list", "-1", f"--before={before_iso}", "refs/heads/main", check=False)
    return out or None


# ── 难度分档（§3.7 坑二） ──────────────────────────────────────────


def band(edit_ops: int) -> str:
    """按 `edit_ops` 现算难度档。

    §3.7 坑二：**不用 Phase 1 的 `difficulty` 字段** —— 它把零写单元记
    `unrated`，且档位口径与本方案的交付需求不一致。这里按改动量现算，
    口径写死在代码里，报告直接引它。
    """
    if edit_ops <= 3:
        return "S"
    if edit_ops <= 10:
        return "M"
    return "L"


# ── harbor 调用约束（TZ 实测，见 reports/tz-preflight.md） ──────────

# 遥测默认**开启**（发往 PostHog），必须显式关。`harbor/telemetry.py:45` 的
# `_DISABLED_VALUES` 不含空字符串 —— 不设 = 开着。我们的 instruction.md 含私有
# 仓库信息，所以这个前缀写进**命令本身**，不写进「注意事项」（写在注意事项里没人看）。
HARBOR_ENV = {"HARBOR_TELEMETRY": "0"}


def assert_jobs_dir_ok(jobs_dir: Path | str) -> Path:
    """校验 harbor 的 `-o` 目录落在 `$HOME` 下；否则抛。

    TZ 实测（R-3）：本机 colima `mounts: []`，VM 内只挂 `$HOME` 一个 virtiofs。
    `-o /tmp/...` 时 verifier 的产出全写在 **VM 自己的 `/private/tmp`**，
    宿主永远读不到，形态是 `RewardFileNotFoundError` —— 而这个报错指向
    「reward 文件没写」，是**错误方向**（实际写了，只是宿主看不见）。

    这条在 T5/T7 的脚本里必须调用，别靠记性。
    """
    p = Path(jobs_dir).resolve()
    home = Path.home().resolve()
    if not p.is_relative_to(home):
        raise ValueError(
            f"harbor jobs 目录必须在 $HOME 之下（colima 只挂载 $HOME），"
            f"给的是 {p} —— 用 /tmp 会得到 RewardFileNotFoundError，"
            f"见 {MVP_REPORTS.name}/tz-preflight.md R-3"
        )
    return p


def read_reward(trial_dir: Path | str) -> float | None:
    """从 harbor 的 trial 目录读 reward。

    §3.8-D 与 TZ 实测确认的坑：正确路径是
    `result.json → verifier_result.rewards.reward`（嵌套 dict）；
    而 `verifier_result.reward` **恒为 None**。写错的形态是
    「所有 task 都 0 分 / None」**且不报错** —— 这正是 R1「绿着坏掉」的经典成因。
    """
    result = Path(trial_dir) / "result.json"
    if not result.exists():
        return None
    try:
        with open(result, encoding="utf-8") as f:
            doc = json.load(f)
    except Exception:
        return None
    rewards = (doc.get("verifier_result") or {}).get("rewards") or {}
    value = rewards.get("reward")
    return float(value) if isinstance(value, (int, float)) else None


# ── jsonl 读写 ─────────────────────────────────────────────────────


def read_jsonl(path: Path | str):
    """逐行读 jsonl，跳过空行。"""
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_jsonl(path: Path | str, rows) -> int:
    """写 jsonl，返回条数。`ensure_ascii=False` —— 指令文本大量是中文。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


# ── 写操作迭代（T2 实测补充，不在方案原文） ────────────────────────

# Edit / Write / MultiEdit —— 唯一会改变工作区的三个工具
WRITE_TOOLS = frozenset({"Edit", "Write", "MultiEdit"})


def load_trajectory(sid: str) -> list[dict]:
    """读某会话的 `trajectory` 数组。读不到就返回 `[]`（调用方按「取不到轨迹」淘汰）。

    只读 `data/pulled_sessions/<sid>/session.traj`（纪律 1）。
    """
    path = SESSIONS_DIR / sid / "session.traj"
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except Exception:
        return []
    return doc.get("trajectory") or []


def observation_errors(trajectory: list[dict]) -> dict[str, bool]:
    """`tool_use_id` → 该调用在**采集当时**是否报错。

    轨迹是 action / observation 成对的：`message_type == 'observation'` 的 step
    带 `tool_use_id` 与 `is_error`，指向前面那个 action 的执行结果。
    """
    out: dict[str, bool] = {}
    for step in trajectory:
        if step.get("message_type") != "observation":
            continue
        tuid = step.get("tool_use_id")
        if tuid:
            out[tuid] = bool(step.get("is_error"))
    return out


def iter_write_actions(sid: str, step_range=None):
    """产出区间内的写操作 `(index, tool_name, tool_input, failed)`。

    `failed=True` 表示**这次调用在采集当时就失败了**（observation 的
    `is_error`）—— 调用方必须跳过它。

    ## 为什么必须按 `is_error` 过滤（T2 实测，方案 §3.2/§4 T2 都没记这条）

    轨迹忠实记录了 agent 的**每一次尝试**，包含失败的那些。182 条候选的区间内
    有 **43 次写操作是失败的**（Edit 41 / Write 2），三种形态：

      - `String to replace not found in file.` —— agent 自己记错了原文
      - `No changes to make: old_string and new_string are exactly the same.`
      - `File has been modified since read...` —— 期间被 linter 或用户改过

    把这些当成成功的改动重放，得到的 patch 就不是开发者真正落下的那份。形态是
    「重建到某个文件时 `old_string` 对不上」，而它看着像**轨迹质量差或 base 反查
    偏了**，其实是我们重放了一次本就没生效的编辑。实测跳掉之后，
    全文件重建成功的候选从 **99 → 110**，锚点命中率 95.9% → 96.1%。

    `failed` 由调用方判读而不是在这里直接跳过：T2 要把跳过的次数写进
    `resolved.jsonl` 留痕，静默丢弃等于让后面的人无法判断「这条 patch 缺不缺东西」。
    """
    trajectory = load_trajectory(sid)
    if not trajectory:
        return
    errors = observation_errors(trajectory)
    lo, hi = (step_range[0], step_range[1]) if step_range else (None, None)
    for i, step in enumerate(trajectory):
        if lo is not None and not (lo <= i <= hi):
            continue
        tool_name = step.get("tool_name")
        if tool_name not in WRITE_TOOLS:
            continue
        failed = errors.get(step.get("tool_use_id"), False)
        yield i, tool_name, parse_tool_input(step.get("tool_input")), failed
