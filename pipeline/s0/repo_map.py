#!/usr/bin/env python3
"""repo_map.py — 路径 → 仓库的映射，以及 working_directory 的三路反解

出处：bench-curation-design.md §2.5「仓库锚定情况」+ §9 Phase 0「S0 的 working_directory 反解」

为什么需要三路而不是一路：
  方案原文假设 metadata.working_directory 是真值、反解只用来补空缺。实测不成立 ——
  两个信号都存在时冲突率 10.5%，且抽查 4 个冲突案例中 metadata.wd 全部是错的
  （采集侧多实例会话匹配串号：一条 wd=iam-studio-fe 的会话，轨迹里 44 次路径
  全部指向 sid-code，raw.jsonl 的 system prompt 也 50 次声明 sid-code）。
  因此改为「三路信号投票」，并把置信度落进 repo_resolution 字段供下游筛选。

三路信号与权重（权重经 mirror 客观裁判实测标定，见下）：
  A. metadata.working_directory  权重 1 —— 直接可得，但存在串号
  B. raw.jsonl 的 system prompt  权重 1 —— agent 自己看到的 env 声明
  C. 轨迹内 file_path 的仓库众数  权重 3 —— 实际动过的文件，证据最硬

为什么 C 要压倒 A+B：用 §9.0 的 mirror 全历史路径集当客观裁判（把轨迹操作过的
路径按候选仓库转相对路径查存在性，命中最多者为事实），500 条抽样实测：
  等权 1/1/1  → 93.9%
  C 权重 2    → 95.9%
  C 权重 3    → 97.3%   ← 采用
且在「wd 与 raw 互相印证」的 131 条金标准子集（其定义与信号 C 独立，故不构成
循环论证）上，C 权重 3 同样把正确率从 93.0% 抬到 98.2%，只翻转 1 例。

路径口径也经实测：只认 file_path / path / notebook_path / filePath 这几个
「操作对象」字段，不要把 Bash command 等自由文本里的路径算进去 —— 后者
把正确率从 97.3% 拉低到 95.9%（命令里常引用其他仓库的路径做参照）。

置信度分级（写入 repo_resolution）：
  direct     三路全部一致
  voted      加权后有明确胜者且 ≥2 路支持
  inferred   仅单路可得
  conflict   多路都有值但互不相同（由 C 的权重裁决，下游应降权或排除）
  unresolved 无任何信号
"""

import collections
import json
import os
import re
from pathlib import Path

# 已知仓库清单 —— 与 archive-repos.sh 的 REPOS 同源，两处读同一个 JSON。
# 原先两处各写一份数组、靠注释保持同源，改一处忘另一处就会让反解出的仓库不在
# 归档内 ⇒ base_commit 无从定位（test_known_repos_matches_archive_manifest 盯的正是这条）。
#
# 仓内默认值只含**已公开披露**的 10 个仓。真实清单 18 个，另外 8 个是未披露的
# 内网仓，不入库 ⇒ 跑真清洗要指到仓外的完整清单：
#   export REPO_MAP_CONFIG=<trajectory-platform>/data/bench-staging/repos.json
# 清单不全的后果是「少反解出几个仓」（那些会话记 unresolved），不会算错。
_CFG = os.environ.get(
    "REPO_MAP_CONFIG",
    str(Path(__file__).resolve().parent.parent / "config/repos.example.json"),
)
KNOWN_REPOS = json.loads(Path(_CFG).read_text(encoding="utf-8"))["repos"]

# 长前缀优先，避免 person/sid-code 被 person/sid 之类的短前缀抢走
_REPOS_BY_LEN = sorted(KNOWN_REPOS, key=len, reverse=True)

CODE_ROOT = os.environ.get("CODE_ROOT", os.path.expanduser("~/Code")).rstrip("/") + "/"

# system prompt 里的 cwd 声明。锚在行尾（\s*\n）而不是 \S+：
# 路径含中文目录名与空格（实测 docs-research/ai-agent-inter/02-工程（agent）/...），
# \S+ 会在第一个空格处截断。
_WD_DECL = re.compile(
    r"(?:Primary working directory|Working directory|Current working directory)"
    r"\s*[:=]\s*(/[^\n\"\\'`]+?)\s*\n"
)

# 轨迹里代表「操作对象」的入参键。只认这几个，不扫 Bash command 等自由文本 ——
# 实测把自由文本里的路径算进来会让仓库正确率从 97.3% 掉到 95.9%。
FILE_INPUT_KEYS = ("file_path", "path", "notebook_path", "filePath")

# 三路信号的投票权重（见模块 docstring 的标定实测）
W_WD = 1
W_RAW = 1
W_TRAJ = 3

# raw.jsonl 只读前 N 行。实测 N=3 时命中率已到顶（96/127），
# 且与 N=1 结果零分歧；放大到 40 只多出 3 条分歧、耗时翻 6 倍。
RAW_MAX_LINES = 3

# 反解出的路径落在 worktree 内时，归到其宿主仓库。
# 依据 §2.6：11 个活跃 worktree，已有 14 条会话的 wd 落在其中。
_WORKTREE_SEG = "/.claude/worktrees/"


def to_repo(path: str) -> str | None:
    """绝对路径 → 已知仓库名（person/sid-code 形式），无法归属返回 None"""
    if not path:
        return None
    path = path.rstrip("/")

    # worktree 副本归到宿主仓库：
    # /Users/.../person/sid-code/.claude/worktrees/foo → person/sid-code
    idx = path.find(_WORKTREE_SEG)
    if idx > 0:
        path = path[:idx]

    if not path.startswith(CODE_ROOT):
        return None
    rel = path[len(CODE_ROOT):]
    for repo in _REPOS_BY_LEN:
        if rel == repo or rel.startswith(repo + "/"):
            return repo
    return None


def wd_from_raw(raw_path: str, max_lines: int = RAW_MAX_LINES) -> str | None:
    """信号 B：从 raw.jsonl 的 request.system 里取 cwd 声明（取众数）

    只解析 request.system 字段，不在整行原文上做正则 —— 后者会命中消息正文里
    提到的其他仓库路径，实测使仓库级准确率从 91% 掉到 79%。
    """
    if not os.path.exists(raw_path):
        return None
    votes: collections.Counter = collections.Counter()
    try:
        with open(raw_path, errors="replace") as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                system = (rec.get("request") or {}).get("system")
                if not system:
                    continue
                if isinstance(system, list):
                    text = "\n".join(
                        b.get("text", "") for b in system if isinstance(b, dict)
                    )
                else:
                    text = str(system)
                for m in _WD_DECL.finditer(text):
                    votes[m.group(1).rstrip("/,;. ")] += 1
    except OSError:
        return None
    return votes.most_common(1)[0][0] if votes else None


def repo_from_trajectory(trajectory: list) -> tuple[str | None, int]:
    """信号 C：轨迹内被操作文件的仓库众数

    返回 (仓库名, 命中次数)。次数落进 repo_signals.traj_hits，供下游判断证据
    强度 —— 1 次命中和 44 次命中不是一个可信度。
    """
    votes: collections.Counter = collections.Counter()
    for step in trajectory:
        tool_input = step.get("tool_input")
        if not isinstance(tool_input, dict):
            continue
        for key in FILE_INPUT_KEYS:
            value = tool_input.get(key)
            if isinstance(value, str) and value.startswith("/"):
                repo = to_repo(value)
                if repo:
                    votes[repo] += 1
    if not votes:
        return None, 0
    repo, n = votes.most_common(1)[0]
    return repo, n


def resolve_repo(
    metadata: dict, trajectory: list, raw_path: str
) -> dict:
    """三路投票，返回 {repo, repo_resolution, repo_signals}

    repo_resolution ∈ {direct, voted, inferred, conflict, unresolved}
    """
    wd_direct = metadata.get("working_directory") or ""
    r_wd = to_repo(wd_direct)
    r_raw = to_repo(wd_from_raw(raw_path) or "")
    r_traj, traj_hits = repo_from_trajectory(trajectory)

    signals = {"wd": r_wd, "raw": r_raw, "traj": r_traj, "traj_hits": traj_hits}
    present = [r for r in (r_wd, r_raw, r_traj) if r]

    if not present:
        return {"repo": None, "repo_resolution": "unresolved", "repo_signals": signals}

    # 加权投票：轨迹证据（权重 3）压倒 wd + raw（各 1）。
    # 理由见模块 docstring —— wd 存在采集侧串号，raw 会读到 CLAUDE.md 里
    # 提及的其他仓库路径，而「实际动过哪些文件」几乎不会错。
    weighted: collections.Counter = collections.Counter()
    if r_wd:
        weighted[r_wd] += W_WD
    if r_raw:
        weighted[r_raw] += W_RAW
    if r_traj:
        weighted[r_traj] += W_TRAJ
    top = weighted.most_common(1)[0][0]

    distinct = set(present)
    n_agree = sum(1 for r in present if r == top)

    if len(present) == 3 and len(distinct) == 1:
        resolution = "direct"
    elif len(distinct) == 1:
        # 全部有值的信号都指向同一个，但不足三路
        resolution = "voted" if len(present) >= 2 else "inferred"
    elif n_agree >= 2:
        resolution = "voted"
    elif len(present) == 1:
        resolution = "inferred"
    else:
        # 多路有值且互不相同 —— 结论由权重裁决，但如实标为 conflict
        resolution = "conflict"

    return {"repo": top, "repo_resolution": resolution, "repo_signals": signals}


# ── 会话目录枚举（S0 与验收必须用同一口径）──────────────────────

def iter_session_dirs(sessions_dir: str) -> list[str]:
    """列出 sessions_dir 下的会话目录，排序返回

    为什么要抽出来共用：S0 原先用 `s != "_trash"`，验收用
    `not s.startswith("_")` —— 两边口径不同，对账就有系统性偏差。实测
    `data/pulled_sessions/` 下有个 2.2MB 的 `.DS_Store` 文件，S0 会把它
    当会话去 open() 然后计入 `no_traj` 计数，掩盖真正缺主文件的会话。

    口径：必须是目录，且名字不以 `_`（历史 `_trash` 之类）或 `.`
    （`.DS_Store` 等系统产物）开头。
    """
    out = []
    for name in os.listdir(sessions_dir):
        if name.startswith(("_", ".")):
            continue
        if not os.path.isdir(os.path.join(sessions_dir, name)):
            continue
        out.append(name)
    return sorted(out)


# ── 历史清洗清单（上一轮手工 _trash 的会话）────────────────────

_TRASHED_CACHE: set[str] | None = None


def load_legacy_trashed(path: str | None = None) -> set[str]:
    """加载 legacy-trashed-sids.txt —— 上一轮被手工移入 _trash/ 的会话

    为什么这份清单必须存在而不能靠规则重算：这批的判据是 steps==0，但操作
    **不完整** —— 移出 1721 条，主目录里还剩 769 条同样 steps==0 的没被移。
    所以「谁进过 _trash」不可由规则复现，属于历史事实。

    为什么目录移回了主目录：pull.py:246 的去重只查
    `data/pulled_sessions/<sid>/.pulled`，目录移走时标记跟着走了，
    should_skip 判为「未拉取」→ 下次 pull 会把这 1722 条全部重下（实测
    --list-only：待拉取 2601 条里 1722 条正是它们）。改为「原始层只增不删，
    淘汰在元数据层表达」，移回后待拉取从 2601 降到 879。
    """
    global _TRASHED_CACHE
    use_cache = path is None
    if use_cache and _TRASHED_CACHE is not None:
        return _TRASHED_CACHE
    if path is None:
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "legacy-trashed-sids.txt"
        )
    sids: set[str] = set()
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    sids.add(line)
    if use_cache:
        _TRASHED_CACHE = sids
    return sids


# ── 采集源判定 ────────────────────────────────────────────────────

def detect_agent_source(sid: str, metadata: dict) -> str:
    """判定会话来自哪条采集通道

    线上 8591 条不是单一来源，实测三种 session_id 形态各对应不同通道：

      claude_code  UUID（36 位带连字符），7132 条。Claude Code 主通道，
                   模型清一色 claude-*
      codex        日期戳 `YYYYMMDD-HHMMSS-xxxxxxxx`，492 条。Codex 通道
                   （见 claude-trace 02a82e6「codex 轨迹数据采集」），
                   模型以 glm-5.2 / deepseek-v4-pro / gpt-5.6 为主
      short_id     8 位短 id，296 条。多为 sid-code 自身产出
                   （metadata.tool_source == "sid-code"）

    这个区分对 benchmark 很重要：不同通道的 metadata 字段集不同（日期戳组
    特有 data_quality / files_read），且模型分布完全不同 —— 混在一起统计
    模型分布会得出错误结论。metadata 里的 source_kind / capture_channel
    覆盖率不足 1%（900 条抽样仅 3 条有值），无法作为判据，故按 id 形态判定。
    """
    tool_source = (metadata.get("tool_source") or "").lower()
    if tool_source == "sid-code":
        return "sid_code"
    if len(sid) == 36 and sid.count("-") == 4:
        return "claude_code"
    if len(sid) >= 8 and sid[:8].isdigit():
        return "codex"
    return "short_id"


# ── 自指污染排除清单 ──────────────────────────────────────────────

_EXCLUDED_CACHE: list[str] | None = None


def load_excluded_prefixes(path: str | None = None) -> list[str]:
    """加载 excluded-paths.txt（S4 强制引用的自指污染排除清单）"""
    global _EXCLUDED_CACHE
    use_cache = path is None
    if use_cache and _EXCLUDED_CACHE is not None:
        return _EXCLUDED_CACHE
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "excluded-paths.txt")
    prefixes = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            prefixes.append(line.rstrip("/"))
    if use_cache:
        _EXCLUDED_CACHE = prefixes
    return prefixes


def is_excluded_path(rel_path: str, prefixes: list[str] | None = None) -> bool:
    """仓库相对路径是否命中自指污染排除前缀

    按 / 分段比对而非裸字符串前缀 —— 否则 evals-foo/x.ts 会被 evals/ 误命中。
    """
    if prefixes is None:
        prefixes = load_excluded_prefixes()
    rel = rel_path.lstrip("/")
    for prefix in prefixes:
        if rel == prefix or rel.startswith(prefix + "/"):
            return True
    return False
