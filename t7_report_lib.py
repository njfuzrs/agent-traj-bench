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

    @property
    def infra_failure(self) -> bool:
        """基础设施故障 ⇒ 排除出分母，**不记为答错**。

        判据刻意只有两条硬的：抛异常、或 verifier 没写分。
        ⛔ 不把 `reward=0` 归到这里 —— 那是「答错」的正常形态；
        真要怀疑假 0 分得去读 test-stdout.txt（见模块 docstring）。
        """
        return bool(self.exception) or self.reward is None

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
    """一个分组格子的统计。"""

    label: str
    tasks: list[str] = field(default_factory=list)
    solved: int = 0
    excluded: int = 0

    @property
    def scored(self) -> int:
        return len(self.tasks) - self.excluded

    @property
    def report_pct(self) -> bool:
        """够不够报百分比。< 5 条只报绝对条数（交接 2b）。"""
        return self.scored >= SMALL_CELL

    def fmt(self) -> str:
        """格内结果的字符串形态。**小格刻意不出百分比。**"""
        if self.scored == 0:
            return f"0/0（全部排除，n={len(self.tasks)}）"
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
    meta = ai.get("metadata") or {}

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
    """按给定分组切格。**一个维度一张表，不交叉**（交接 2b）。"""
    out: dict[str, Cell] = {}
    for label, members in groups.items():
        cell = Cell(label=label, tasks=sorted(members))
        for t in members:
            if t in excluded_tasks:
                cell.excluded += 1
            else:
                cell.solved += round(per_task_rate.get(t, 0.0))
        out[label] = cell
    return out
