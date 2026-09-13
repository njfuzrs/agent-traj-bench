#!/usr/bin/env python3
"""T7 的判定与统计层 —— 与跑批解耦，便于单测与纯复算。

分工同 T5：`t7-baseline.py` 跑批，本文件判分与算数，`t7-report.py` 出报告。

## 🔴 三条来自 T6→T7 交接的硬约束（都会改判据，不是建议）

**① 分母是 39，不是 40。** 存活集读 `survivors.json`；`meta/gate.jsonl` 的
`survives` 是 T5 三道门禁的结论（40 条），不含 T6 的人工淘汰 ⇒ 照它取会把
`T0005` 算进基线（交接 1b）。

**② 必须按「题面信息量」分级分组报**（A2 20 / A1 11 / B 4 / C 4）。
混在一起报会把「题面缺信息」误读成「模型能力差」—— 本批最大的解读陷阱（交接 2）。

**③ 难度维度与题面维度分开各一张表，不交叉。** 39 条切成 2 档 × 4 级 = 8 格、
每格 1-14 条，交叉报会碎到没有统计意义。**任一格 < 5 条只报绝对条数、不报百分比**
—— 5 条以下的比例会被单条结果整数级拉动（交接 2b）。

**④ 难度只有 M / L 两档，S 档为 0。** 方案原写的「S > M > L 单调梯度」判据
**整条失效**，不是「可能不达标」（交接 2c）。dataset card 必须写明
「S 档为 0，不构成三档单调性证据」。

## 分母纪律：基础设施故障不算答错

`excluded` 与 `scored` 分开算。把 infra 故障算进分母等于把它记成答错 ——
A1 那边就是这么处理的（08 号 §4.11 的 `denominators`）。
本批的 infra 判据：trial 抛异常，或 reward 为 None（verifier 没写分）。

⚠️ **reward=0 但 Exceptions=0 时，第一件事是读 `verifier/test-stdout.txt`，
不要先怀疑 task 质量**。TZ 实测过这个形态（R-4）：oracle 拿 0 分、Exceptions=0，
真因是 github 间歇不可达导致 uv 装不上 —— 那是**假 0 分**。

## Wilson 区间而不是正态近似

n=39 且 p 可能靠近 0/1，正态近似的区间会跑出 [0,1] 之外。与 A1 同口径
（`method=wilson-score-95`），便于两批横向比。

⚠️ 08 号 §4.11 记着一次真实的算错：配对差的 SE 公式**多除了一次 N**，
得出的 CI 与 McNemar 的 p 值直接矛盾。**两个结果互相矛盾时先怀疑仪器。**
本文件只算单臂比例，不算配对差，但同一条纪律保留。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

#: 小样本阈值：格内条数 < 这个数就只报绝对条数、不报百分比（交接 2b）。
SMALL_CELL = 5

#: agent 侧**预算耗尽**类异常 —— 是评测结果，⛔ 不是仪器故障，不排除出分母。
#:
#: 只有一个成员，但刻意写成集合而不是 `== "AgentTimeoutError"`：
#: harbor 未来若给「预算触顶」加新异常类（如 token 上限），加进这里一处即可，
#: 而漏加的形态是**静默低报 pass@1**（见 `Trial.infra_failure` 的 T0011 实例）。
#:
#: ⛔ 不要往里加 `RewardFileNotFoundError` / 环境构建类异常 —— 那些是真 infra。
AGENT_BUDGET_EXCEPTIONS = frozenset({"AgentTimeoutError"})

#: 上游 LLM 链路故障的签名（小写匹配）。命中 ⇒ **假 0 分**，排除出分母。
#:
#: 🔴 T0022 实测（2026-09-14）：61 轮 / 73 分钟后上游断连，agent 以
#: `error_during_execution` 收尾，而 verifier 照常打分 ⇒ `reward=0.0`
#: ⇒ 一次网络抖动被记成「模型改错了」，两者形态**逐字节一样**。
#:
#: ⛔ 别往里加 agent 自身的崩溃签名（`TypeError`、`assertion` …）——
#: 那些是真失败，排除掉等于替模型擦屁股。这里只放**链路**层面的。
UPSTREAM_ERROR_SIGNS = (
    "socket connection",        # T0022 实测原文：socket connection was closed unexpectedly
    "closed unexpectedly",
    "econnreset",
    "etimedout",
    "fetch failed",
    "502 bad gateway",
    "503 service unavailable",
    "504 gateway",
)


@dataclass
class Trial:
    """一条 trial 的判定输入。"""

    task: str
    reward: float | None
    f2p: float | None
    p2p: float | None
    error_code: int | None
    exception: str | None
    #: verifier 自己写的 reward.txt，用于双源核对
    reward_txt: float | None = None
    cost_usd: float | None = None
    model: str | None = None
    binary_sha: str | None = None
    n_input_tokens: int | None = None
    n_output_tokens: int | None = None
    n_cache_tokens: int | None = None
    trial_dir: Path | None = None
    #: agent 自报的终止形态（`sid_subtype`）：success / error_max_turns /
    #: error_max_budget_usd / error_during_execution。
    #: ⚠️ 与 `exception` 是**两个不同的出口** —— 撞轮数上限时 exception 为 None，
    #: 只有这里写着 `error_max_turns`（2026-09-14 我取错过一次，把 13 条报成 0 条）。
    subtype: str | None = None
    #: agent 自报的错误列表（`sid_errors`），用于分辨「上游断连」这类假 0 分。
    errors: tuple[str, ...] = ()

    @property
    def upstream_failure(self) -> bool:
        """上游 LLM 链路断了 ⇒ **假 0 分**，按 infra 排除出分母。

        🔴 2026-09-14 全量重跑实测（T0022）：跑到第 61 轮、73 分钟时上游断连
        （`The socket connection was closed unexpectedly`），
        agent 以 `error_during_execution` 终止，**verifier 照常打了分 ⇒ reward=0.0**。

        形态之所以危险：它与「模型改了但改错」**逐字节一样**（都是 reward=0、
        Exceptions=0、有仓库写操作）。不识别就等于把**一次网络抖动记成模型能力不足** ——
        这正是模块 docstring 里 TZ 那次「假 0 分」（R-4）的同一个坑，换了个出口。

        ⛔ 判据必须同时满足「终止形态是 error_during_execution」与「错误里有网络签名」：
        只看 subtype 会把 agent 自身的崩溃也排除掉（那不是仪器故障，是真失败）。
        """
        if self.subtype != "error_during_execution":
            return False
        joined = " ".join(self.errors).lower()
        return any(sig in joined for sig in UPSTREAM_ERROR_SIGNS)

    @property
    def budget_exhausted(self) -> bool:
        """agent 侧预算耗尽（墙钟）⇒ **是评测结果，不是仪器故障**。

        与 `error_max_turns` / `error_max_budget_usd` 同族 —— 都是「给定预算内没做完」，
        区别只在**哪个预算先触顶**。前两者 harbor 记成 `subtype` 干净终止，
        而墙钟触顶是**抛异常**，于是会被 `bool(self.exception)` 误判成 infra。
        """
        return self.exception in AGENT_BUDGET_EXCEPTIONS

    @property
    def infra_failure(self) -> bool:
        """基础设施故障 ⇒ 排除出分母，**不记为答错**。

        判据只有两条硬的：**verifier 没写分**，或抛出**非预算类**异常。
        ⛔ 不把 `reward=0` 归到这里 —— 那是「答错」的正常形态；
        真要怀疑假 0 分得去读 test-stdout.txt（见模块 docstring）。

        🔴 **`AgentTimeoutError` 刻意不算 infra** —— 这条是 E3 实测踩出来的，
        写错的形态是**静默低报 pass@1**：

          T0011  reward=1.0（f2p 全 pass、p2p 30/30）  exception=AgentTimeoutError
          ⇒ 旧判据 `bool(self.exception)` 把它排除出分母
          ⇒ 一条**真解出**的题被记成仪器故障，pass@1 从 1/1 变 0/0

        根因是把「抛异常」当成了「没拿到分」的代理。但 verifier 跑在 agent 终止
        **之后**，agent 超时不妨碍它打分 —— 判「有没有分」要直接看 `reward`，
        ⛔ 不要拿异常去推断。

        ⚠️ 反过来也不能一刀切成「只看 reward is None」：环境构建失败、
        `RewardFileNotFoundError` 那些**真** infra 故障必须继续排除
        （它们本来就 reward=None，但异常类型是唯一能区分「机器坏了」与
        「预算用完了」的信号，丢掉它下一次就分不出来了）。
        """
        if self.reward is None:
            return True
        if self.upstream_failure:       # 假 0 分：上游断连，题根本没跑完（T0022）
            return True
        return bool(self.exception) and not self.budget_exhausted

    @property
    def solved(self) -> bool:
        return self.reward == 1.0


def wilson(passed: int, n: int, z: float = 1.959963984540054) -> tuple[float, float, float]:
    """Wilson score 95% 区间。返回 (p, lo, hi)。

    n=0 时返回 (0,0,0) —— 让调用方自己决定怎么写「无数据」，
    在这里编一个 0.5 出来才是真的坏。
    """
    if n == 0:
        return 0.0, 0.0, 0.0
    p = passed / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, centre - half), min(1.0, centre + half)


@dataclass
class Cell:
    """一个分组格子的统计。

    ⚠️ `missing` 与 `excluded` 是**两件不同的事**，刻意分开存：

      - `excluded` —— 跑了，但 infra 故障（抛异常 / verifier 未写分）
      - `missing`  —— **压根没跑**（跑批未完成、或该 task 不在这一轮的 `-p` 名单里）

    两者都不进分母，但混成一个字段就无法回答「这张表覆盖了多少」。
    ⛔ 更不能让 `missing` 留在分母里 —— 那等于**把没跑的题记成答错**，
    形态是「A1 报 0/11 而实际只跑了 1 条」，且主表分母（3）与分组表分母（39）
    互相矛盾却不报错。2026-09-13 用跑到 3/39 的中途产物实测撞到：
    这正是 R1「绿着坏掉」——跑完 39 条时数字会碰巧对上，缺陷仍在，
    此后任何一条 infra 排除都会重新触发。
    """

    label: str
    tasks: list[str] = field(default_factory=list)
    solved: int = 0
    excluded: int = 0
    #: 分组名单里、但这一轮产物里没有任何 trial 的 task 数
    missing: int = 0

    @property
    def scored(self) -> int:
        return len(self.tasks) - self.excluded - self.missing

    @property
    def report_pct(self) -> bool:
        """够不够报百分比。< 5 条只报绝对条数（交接 2b）。"""
        return self.scored >= SMALL_CELL

    @property
    def coverage_note(self) -> str:
        """这一格的覆盖情况。**没跑的与被排除的分开写**，空串表示全跑齐了。"""
        bits = []
        if self.missing:
            bits.append(f"{self.missing} 条未跑")
        if self.excluded:
            bits.append(f"{self.excluded} 条 infra 排除")
        return "，".join(bits)

    def fmt(self) -> str:
        """格内结果的字符串形态。**小格刻意不出百分比。**"""
        if self.scored == 0:
            why = self.coverage_note or "全部排除"
            return f"0/0（{why}，n={len(self.tasks)}）"
        if not self.report_pct:
            return f"{self.solved}/{self.scored} 条（n<{SMALL_CELL}，刻意不报百分比）"
        p, lo, hi = wilson(self.solved, self.scored)
        return f"{self.solved}/{self.scored} = {p:.1%}　[{lo:.1%}, {hi:.1%}]"


def read_trial(trial_dir: Path) -> Trial | None:
    """读一个 trial 目录。不是 trial 目录（如 job 根）返回 None。

    ⚠️ reward 取 `verifier_result.rewards.reward`（嵌套 dict），
    ⛔ 不是 `verifier_result.reward` —— 后者恒为 None，
    写错的形态是**所有 task 都 0 分且不报错**（R1「绿着坏掉」的经典成因）。
    """
    result = trial_dir / "result.json"
    if not result.exists():
        return None
    try:
        doc = json.loads(result.read_text(encoding="utf-8"))
    except Exception:
        return None
    task = doc.get("task_name")
    if not task:                        # job 根的 result.json 没有 task_name
        return None

    rewards = (doc.get("verifier_result") or {}).get("rewards") or {}
    exc = doc.get("exception_info")
    exc_str = None
    if exc:
        exc_str = exc.get("exception_type") if isinstance(exc, dict) else str(exc)
        if isinstance(exc, dict) and not exc_str:
            exc_str = json.dumps(exc, ensure_ascii=False)[:200]

    txt = trial_dir / "verifier" / "reward.txt"
    reward_txt = None
    if txt.exists():
        try:
            reward_txt = float(txt.read_text(encoding="utf-8").strip())
        except Exception:
            reward_txt = None

    def num(key: str) -> float | None:
        v = rewards.get(key)
        return float(v) if isinstance(v, (int, float)) else None

    ar = doc.get("agent_result") or {}
    ai = doc.get("agent_info") or {}
    mi = ai.get("model_info") or {}
    # 🔴 metadata 在 **`agent_result`** 下，不是 `agent_info` 下。
    # 2026-09-13 冒烟实测：写成 `ai.get("metadata")` 时 `sid_binary_sha256` 永远读不到，
    # 报告 §5 的必控变量表报「观测值 []，缺失 3」—— 看着像「agent 没回填这个字段」，
    # 真相是**取错了位置**。而那张表的唯一作用就是证明「只换了模型、二进制没变」，
    # 它静默失效等于这一轮的必控变量根本没被核对过（R1「绿着坏掉」的又一例）。
    # 两个位置都试：真实产物在 agent_result.metadata，留 agent_info 作兜底。
    meta = ar.get("metadata") or ai.get("metadata") or {}

    ec = rewards.get("error_code")
    return Trial(
        task=task,
        reward=num("reward"),
        f2p=num("f2p"),
        p2p=num("p2p"),
        error_code=int(ec) if isinstance(ec, (int, float)) else None,
        exception=exc_str,
        reward_txt=reward_txt,
        cost_usd=ar.get("cost_usd"),
        # 模型名两个出口都试：harbor 的 model_info，与 agent 自己写的 metadata
        model=mi.get("name") or meta.get("sid_model"),
        binary_sha=meta.get("sid_binary_sha256") or meta.get("binary_sha256"),
        n_input_tokens=ar.get("n_input_tokens"),
        n_output_tokens=ar.get("n_output_tokens"),
        n_cache_tokens=ar.get("n_cache_tokens"),
        trial_dir=trial_dir,
        # ⚠️ 终止形态只在 metadata 里，⛔ 不在 exception —— 撞轮数上限时 exception 是 None
        subtype=meta.get("sid_subtype"),
        errors=tuple(str(e) for e in (meta.get("sid_errors") or [])),
    )


def collect(run_dir: Path) -> list[Trial]:
    """收一个 job 目录下所有 trial。`-k 3` 时同一 task 多行，**刻意不去重**。"""
    out = []
    for d in sorted(Path(run_dir).iterdir()):
        if not d.is_dir():
            continue
        t = read_trial(d)
        if t is not None:
            out.append(t)
    return out


def collect_all(jobs_dir: Path) -> list[Trial]:
    """跨**所有** run 目录收 trial —— 续跑（`t8-rerun.py --resume`）用。

    🔴 为什么不能只用 `latest_run`：harbor 每次调用新建一个带时间戳的目录，
    续跑一次就多一个。只读最后那个的形态是**静默漏掉第一轮跑出的那些 trial** ——
    报告每张表都有数，只有分母悄悄小了一圈，而完整性守卫只会报「没跑齐」，
    不会说「其实跑了、但你没读」。归因方向完全错。

    ⚠️ 同一 task 在多个目录里出现时（被杀时在跑的那条会重跑）取**最新**那个：
    续跑的结果比被中断的旧结果可信。⛔ 不能像 `collect()` 那样全留 ——
    那会让 k=1 的批次里某些 task 有两行，`pass_at_1` 把它当成 k=2 平均，
    静默改变分母口径。
    """
    jobs_dir = Path(jobs_dir)
    if not jobs_dir.exists():
        return []
    runs = sorted(p for p in jobs_dir.iterdir() if p.is_dir() and p.name[:2] == "20")
    if len(runs) <= 1:
        return collect(runs[0]) if runs else []

    # 后面的 run 覆盖前面的同名 task；同一 run 内的多次尝试（k>1）全留
    by_task: dict[str, list[Trial]] = {}
    for run in runs:
        seen_here: dict[str, list[Trial]] = {}
        for t in collect(run):
            seen_here.setdefault(t.task, []).append(t)
        by_task.update(seen_here)
    return [t for rows in by_task.values() for t in rows]


def latest_run(jobs_dir: Path) -> Path | None:
    jobs_dir = Path(jobs_dir)
    if not jobs_dir.exists():
        return None
    runs = sorted(p for p in jobs_dir.iterdir() if p.is_dir() and p.name[:2] == "20")
    return runs[-1] if runs else None


def pass_at_1(trials: list[Trial]) -> dict:
    """按 task 聚合成 pass@1。

    k>1 时同一 task 有多行：pass@1 的定义是**单次尝试的期望通过率**
    ⇒ 取该 task 所有 trial 的**通过比例**，再对 task 取平均。
    ⛔ 不是「任一次通过就算通过」—— 那是 pass@k，会把数字报高。
    """
    by_task: dict[str, list[Trial]] = {}
    for t in trials:
        by_task.setdefault(t.task, []).append(t)

    scored, excluded, excluded_tasks = 0, 0, []
    per_task_rate: dict[str, float] = {}
    for task, rows in sorted(by_task.items()):
        usable = [r for r in rows if not r.infra_failure]
        if not usable:
            excluded += 1
            excluded_tasks.append(task)
            continue
        scored += 1
        per_task_rate[task] = sum(1 for r in usable if r.solved) / len(usable)

    # k=1 时 rate 只能是 0/1 ⇒ sum 就是解出条数，与 A1 的 `ci.passed` 同口径
    passed_equiv = sum(per_task_rate.values())
    p, lo, hi = wilson(round(passed_equiv), scored) if scored else (0.0, 0.0, 0.0)
    return {
        "n": scored,
        "passed": round(passed_equiv, 4),
        "p": p,
        "lo": lo,
        "hi": hi,
        "halfwidth_pp": (hi - lo) / 2 * 100,
        "method": "wilson-score-95",
        "excluded": excluded,
        "excluded_tasks": excluded_tasks,
        "per_task_rate": per_task_rate,
        "denominator_note": (
            "分母是 scored（参与计分的 task）。基础设施故障（抛异常 / verifier 未写分）"
            "排除出分母 —— 算进去等于把它记成答错。⛔ 不是 40（那是 T5 门禁的结论，含 T0005）。"
        ),
    }


def group(per_task_rate: dict[str, float], groups: dict[str, list[str]],
          excluded_tasks: list[str]) -> dict[str, Cell]:
    """按给定分组切格。**一个维度一张表，不交叉**（交接 2b）。

    ⚠️ 三分而不是二分：分组名单里的每个 task 要么**被排除**、要么**没跑**、
    要么**跑了**（解出与否看 `per_task_rate`）。

    ⛔ 不能写成 `per_task_rate.get(t, 0.0)` —— 那把「没跑」和「跑了没解出」
    压成同一个 0，没跑的 task 就静默留在分母里被记成答错。
    判据只能是 `t in per_task_rate`（键在不在），不是取值是不是 0：
    真正跑出 0 分的 task 键**是在**的，值也是 0.0，两者取值完全一样。
    """
    out: dict[str, Cell] = {}
    for label, members in groups.items():
        cell = Cell(label=label, tasks=sorted(members))
        for t in members:
            if t in excluded_tasks:
                cell.excluded += 1
            elif t not in per_task_rate:
                cell.missing += 1
            else:
                cell.solved += round(per_task_rate[t])
        out[label] = cell
    return out
