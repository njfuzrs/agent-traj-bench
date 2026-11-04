#!/usr/bin/env python3
"""T13：功效计算（§3.3）与 S/ε/m 阈值计算（§5.2）。

出处：docs-research `sid-code/bugfixes/todo/20261003-评测接入CI-CD-分层门禁与基线闭环.md`
§3.3（题量与统计功效）、§5.2（L2 判定规则）、§6.6 T13（本脚本的任务定义）。

## 为什么数字必须由脚本生成

方案 §3.3 / §5.2 有三张数字表。它们此前的来源是**手算**，而手算已经偏过一次：
§3.3 表① 的 n=37 行文档写 «≈27 pp»，按同一段写死的口径（两比例 arcsine
正态近似、α=0.05 双侧、功效 0.8、p≈0.378）复算是 **31.9 pp**。差 5 pp 不是
舍入，是口径执行得不一样 —— 而这张表正是「39 题到底能拦多大退化」的唯一依据。

⇒ 本脚本是这三张表的**唯一取数源**，文档只引用它的输出（`--tables`）。

## 三张表分别回答什么

| 表 | 问题 | 本文件的函数 |
| --- | --- | --- |
| §3.3 表① 不配对 | 两次各跑 n 题、各自比总分，能检出多大差距 | `min_detectable_delta()` |
| §3.3 表② 配对 | 同一批题前后比，翻转多少题才判显著 | `mcnemar_min_split()` |
| §5.2 m 表 | 稳定子集大小 |S| 与 ε 给定后，阻断阈值 m 该设几 | `block_threshold()` |

外加 §5.2 的三个冻结量本身（T15→T17 用真实基线算）：
`stability_set()` → S、`epsilon_from_holdout()` → ε、`block_threshold()` → m。

## 三条纪律

1. **口径写死在常量里**（ALPHA / POWER / P_BASE / EPS_FLOOR / MIN_S）。
   改它们 = 改判据，必须走 review。⛔ 不许在调用处临时传参把结果调好看。
2. **只用 stdlib**：`math.comb` + `fractions.Fraction`。⛔ 不引 scipy ——
   与 gate10「pipeline 零第三方依赖」同一条纪律，也让 CI 不必多装东西。
   `Fraction` 不是洁癖：|S|=10、ε=0.15 的 P(X≥4)=0.04997，离 α=0.05 只有
   **3e-5**，浮点近似能否「恰好」判对取决于舍入方向。实测这条边界换一组
   参数就会翻，所以尾概率一律精确有理数。
3. **`--check` 与文档对账**：`DOC_*` 常量是方案文档三张表的镜像，现算与它
   逐格比对，不一致退出 1。要么算法漂了、要么文档没跟上 —— 两种都要人看
   一眼，⛔ 不许自动改任何一侧（那等于让尺子自己改刻度）。

## 用法

    python3 scripts/eval-stats.py                    # 打印三张表（markdown，可直接粘文档）
    python3 scripts/eval-stats.py --check            # 与文档冻结值对账，不一致退出 1
    python3 scripts/eval-stats.py --baseline A.json B.json C.json --holdout H.json
                                                     # 由真实 k 份基线算 S / ε / m（T15→T17）

`--baseline` 的输入口径：k 份 `trials.json`（`{"rows":[{"task","reward"}]}`，
即 `t7_report_lib.collect_all()` 的序列化结果 —— 它是 `.gitignore` 里唯一
保留的 trial 取数源，run 目录不入库）。**只统计计分集**（`meta/scoring-set.json`
的 `groups.scored`）；交付集里的 audit / excluded 题累计进来会让阻断判据
覆盖到不该覆盖的题。

⚠️ `--baseline` 需要 k≥2；`--holdout` 缺省时 ε 取预登记下限 0.10 并**明示**
「样本内估计有偏，不许拿 k 份结果自己估 ε」（§5.2 原文）。
"""

from __future__ import annotations

import argparse
import json
import math
from fractions import Fraction
from math import comb
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCORING_SET = REPO_ROOT / "meta" / "scoring-set.json"

# ── 口径（改它们 = 改判据，必须走 review）────────────────────────────

#: 基线通过率：t8-rerun 那批 14/37（deepseek-v4.1-flash，k=1）。
#: ⚠️ 功效表是**工作点相关**的：换模型或换题集后 p 变了，同一张表不能沿用。
P_BASE = 14 / 37

#: 双侧显著性水平 0.05（§3.3 与 §5.2 同一口径）。
ALPHA = Fraction(1, 20)

#: 统计功效 0.8（§3.3）。
POWER = 0.8

#: 标准正态分位数：z_{1-ALPHA/2} = z_{0.975}，z_{POWER} = z_{0.8}。
Z_ALPHA_2 = 1.959963984540054
Z_POWER = 0.8416212335729143

#: ε 的预登记下限（§5.2）：样本外实测更低时仍取 0.10。
#: 理由是 S 从 k=3 里按「3/3 全过」挑出来，天然偏「稳」；样本外一轮也只有 |S| 个观测。
EPS_FLOOR = Fraction(1, 10)

#: 稳定子集规模下限（§5.2 降级规则）：|S| < 6 ⇒ REGRESSION 停用，只看趋势。
MIN_S = 6


# ── §3.3 表①：不配对（两比例 arcsine 正态近似）──────────────────────


def min_detectable_delta(
    n: int,
    p: float = P_BASE,
    z_alpha: float = Z_ALPHA_2,
    z_power: float = Z_POWER,
) -> float | None:
    """两次各 n 题、各自比总分时，能检出的最小绝对差（百分点）。

    口径写死在 §3.3：「不配对用两比例 arcsine 正态近似」。
    Cohen's h = 2·asin(√p₂) − 2·asin(√p₁)；每组 n 题时
        h = √(2·(z_{α/2} + z_β)² / n)
    反解 p₂ 即得最小可检出差距。

    返回 None ⇒ **n 太小、arcsine 近似饱和**（h 大到把 p₂ 顶出 [0,1] 的可用
    区间）。此时表里不能写数字 —— 写一个 100 pp 出来比报错更危险。
    """
    if n < 2:
        raise ValueError(f"n 至少 2，收到 {n}")
    h = math.sqrt(2 * (z_alpha + z_power) ** 2 / n)
    phi1 = 2 * math.asin(math.sqrt(p))
    phi2 = phi1 + h
    if phi2 >= math.pi:
        # p₂ 已贴到 1.0：说明这个 n 连「两次全绿」的差别都检不出，
        # 不是「差距 = 100 pp」这种有意义的读数。
        return None
    p2 = math.sin(phi2 / 2) ** 2
    return 100 * (p2 - p)


# ── §3.3 表②：配对（McNemar 精确检验）────────────────────────────────


def discordant_count(n: int, flip_rate: float) -> int:
    """翻转率 → 不一致题数。

    §3.3 的表用**四舍五入**（n=37 时 10%→3.7→4、20%→7.4→7、30%→11.1→11），
    ⛔ 不是向下取整 —— 那会把 3.7 条写成 3 条，判据随之偏严。
    """
    return round(flip_rate * n)


def binom_tail(n: int, p: Fraction, m: int) -> Fraction:
    """P(X ≥ m)，X ~ Binomial(n, p)。**精确有理数**，不经过浮点。

    ⚠️ 精度不是可选项：§5.2 的 |S|=10、ε=0.15 一行恰好落在 0.04997，
    与 α=0.05 只差 3e-5。浮点累加的顺序一变，这一格就会在「显著 / 不显著」
    之间翻转，而表里没有任何东西会提示你它翻过。
    """
    if not 0 <= m <= n + 1:
        raise ValueError(f"m 超出 [0, {n + 1}]：{m}")
    p = Fraction(p)
    return sum(comb(n, k) * p**k * (1 - p) ** (n - k) for k in range(m, n + 1))


def mcnemar_min_split(k: int, alpha: Fraction = ALPHA) -> int | None:
    """k 条不一致题里，判「显著回退」所需的最小同向题数 b。

    McNemar 精确检验：H₀ 下 b ~ Binomial(k, 1/2)，双侧 p = 2·P(X ≥ b)。
    从 b = ⌊k/2⌋+1 向上找第一个 p ≤ α 的 b（必须 b > k/2，否则方向是「改善」）。

    返回 None ⇒ **即便 k 条全部同向也不显著**（§3.3 表② 的 10% 行）。
    """
    if k <= 0:
        raise ValueError(f"k 必须为正，收到 {k}")
    for b in range(k // 2 + 1, k + 1):
        if 2 * binom_tail(k, Fraction(1, 2), b) <= alpha:
            return b
    return None


# ── §5.2：m 表与检定力 ──────────────────────────────────────────────


def block_threshold(n_s: int, eps: Fraction, alpha: Fraction = ALPHA) -> int | None:
    """§5.2 的 m：P(X ≥ m | Binomial(|S|, ε)) ≤ α 的**最小** m。

    返回 None ⇒ 连「|S| 题全部失手」都不显著（|S| 太小或 ε 太大）。
    这不是「随便挑一个 m」，而是 §5.2 降级规则的触发条件之一：
    此时 REGRESSION 判不出来，只能走「只看趋势」。
    """
    if n_s <= 0:
        raise ValueError(f"|S| 必须为正，收到 {n_s}")
    eps = Fraction(eps)
    for m in range(n_s + 1):
        if binom_tail(n_s, eps, m) <= alpha:
            return m
    return None


def detection_prob(n_s: int, m: int, p_after: Fraction = Fraction(1, 2)) -> Fraction:
    """退化后单题失败率为 p_after 时，判据的检出概率 P(X ≥ m)。

    §5.2 表最后一列口径：ε=0.10 算出的 m、退化后单题失败率 0.5。
    """
    return binom_tail(n_s, p_after, m)


# ── §5.2 的三个冻结量：由真实基线算（T15 → T17）───────────────────────


def scored_tasks() -> list[str]:
    """计分集（`meta/scoring-set.json` 的 `groups.scored`）。

    ⛔ 不用交付集 39 题：audit / excluded 的题不计分，把它们算进 S 会让
    阻断判据覆盖到「本来就不判对错」的题（traj 缺陷 8）。
    """
    doc = json.loads(SCORING_SET.read_text(encoding="utf-8"))
    return list(doc["groups"]["scored"])


def load_run(path: Path) -> dict[str, float]:
    """读一份逐题结果 → {task: reward}。

    只认 `trials.json` 的 rows 形态（`{"rows":[{"task","reward",...}]}`）：
    那是 `.gitignore` 明确保留的唯一 trial 取数源（run 目录 1.9G，不入库）。

    reward 为 None 或缺字段的题**直接丢出结果**（不是记 0）：verifier 没写分
    是仪器故障，记 0 等于把它算成答错，而这一步会被后面的 S 判定当成
    「这题不稳定」——形态是「一条 infra 故障把好题踢出了 S」，不报错。
    """
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = doc.get("rows") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise SystemExit(
            f"⛔ {path}：只认 trials.json 的 rows 形态（{{\"rows\":[{{\"task\",\"reward\"}}]}}）"
        )
    out: dict[str, float] = {}
    for r in rows:
        task, reward = r.get("task"), r.get("reward")
        if task and reward is not None:
            out[task] = float(reward)
    return out


def stability_set(
    runs: list[dict[str, float]], scored: set[str] | None = None
) -> tuple[list[str], dict[str, str]]:
    """§5.2 的 S：k 份结果里**每一份都 reward == 1.0** 的题。

    返回 (S, notes)。notes 记录每题没进 S 的原因，供报告如实披露：
      - 「只出现在 m/k 份结果里」—— 覆盖不全，不能判「稳定」
      - 「k 次里 x/k 过」—— 不稳定题，§5.2 规定只能触发 WARN

    ⛔ 不许放宽成「k 次里过一次就算稳定」：那等于把「有时过有时不过」的
    题放进阻断判据，阈值会被它们抬到失去意义（§5.2 的立论基础）。
    ⛔ 也不许给缺失补一个 0：缺失是「没跑」，不是「跑了没过」。
    """
    if len(runs) < 2:
        raise SystemExit("⛔ 至少两份结果才能谈稳定性（k≥2）")
    tasks: set[str] = set()
    for r in runs:
        tasks |= set(r)
    if scored is not None:
        tasks &= scored

    s: list[str] = []
    notes: dict[str, str] = {}
    for t in sorted(tasks):
        vals = [r[t] for r in runs if t in r]
        if len(vals) < len(runs):
            notes[t] = f"只出现在 {len(vals)}/{len(runs)} 份结果里"
        elif all(v == 1.0 for v in vals):
            s.append(t)
        elif any(v == 1.0 for v in vals):
            notes[t] = f"k 次里 {sum(v == 1.0 for v in vals)}/{len(vals)} 过（不稳定题）"
        # 全 0 的题：既不是 S 也不是「不稳定」，不进 notes（那是正常的难/没解出）
    return s, notes


def epsilon_from_holdout(
    holdout: dict[str, float], s: list[str], floor: Fraction = EPS_FLOOR
) -> Fraction:
    """样本外的 ε：S 中题在 holdout 那一轮里失败的比例；取 max(实测, 0.10)。

    §5.2 原文：S 是从 k=3 里按「3/3 全过」挑的，用同一份数据估 ε 有入选偏差
    （真实通过率 0.7 的题也有约 34% 概率 3/3 全过），所以 ε 必须用**样本外**
    数据估。样本内估计一律禁止。

    ⛔ 缺题必须抛错，不许按「未失败」算：那会让分母变小、ε 被低报，
    而 ε 低报 ⇒ m 变小 ⇒ 误拦率上升（§5.2 的独立性假设本来就偏乐观）。
    """
    if not s:
        raise SystemExit("⛔ S 为空，ε 无从估起")
    missing = [t for t in s if t not in holdout]
    if missing:
        raise SystemExit(
            f"⛔ holdout 缺 S 中 {len(missing)} 题（{', '.join(missing[:6])}{'…' if len(missing) > 6 else ''}）"
            "；ε 不可估 —— ⛔ 不许当作「未失败」"
        )
    failed = sum(1 for t in s if holdout[t] != 1.0)
    return max(Fraction(failed, len(s)), floor)


def thresholds(
    runs: list[dict[str, float]],
    holdout: dict[str, float] | None = None,
    scored: set[str] | None = None,
) -> dict:
    """由真实基线算 §5.2 的三个冻结量：S / ε / m（T17 写回文档用）。

    `holdout is None` 时 ε 取预登记下限 0.10，并在结果里标明来源 ——
    §5.2 禁止用样本内数据估 ε，所以**没有第三个选项**。
    """
    s, notes = stability_set(runs, scored)
    if holdout is not None:
        eps = epsilon_from_holdout(holdout, s)
        eps_source = "样本外实测（max 预登记下限 0.10）"
    else:
        eps = EPS_FLOOR
        eps_source = "预登记下限 0.10（未提供 --holdout；§5.2 禁止样本内估 ε）"

    n_s = len(s)
    m = block_threshold(n_s, eps) if n_s else None
    detect = detection_prob(n_s, m) if m is not None else None
    # 降级规则的触发条件（§5.2 预先登记）：|S| < 6，或连全部失手都不显著
    degraded = n_s < MIN_S or m is None
    return {
        "k": len(runs),
        "n_s": n_s,
        "S": s,
        "eps": float(eps),
        "eps_frac": f"{eps.numerator}/{eps.denominator}",
        "eps_source": eps_source,
        "m": m,
        "detect_prob": None if detect is None else float(detect),
        "degraded": degraded,
        "degrade_reason": (
            None
            if not degraded
            else f"|S|={n_s} < {MIN_S}" if n_s < MIN_S else "m 不存在（|S| 太小或 ε 太大）"
        ),
        "notes": notes,
    }


# ── 文档冻结值（方案 §3.3 / §5.2 的镜像）──────────────────────────────
#
# 🔴 这些常量**抄自方案文档**，不是这里定义的判据。`--check` 现算后逐格比对：
#    不一致 ⇒ 要么算法漂了、要么文档没跟上，两种都要人看一眼。
# ⛔ 不许「发现不一致就自动改常量」—— 那等于让尺子自己改刻度。
# 改法只有一条：先确认现算正确，再改文档，最后同步这里（PR 里写明三处）。

#: §3.3 表①「不配对」：题量 → 可检出最小差距（pp，一位小数）。
DOC_UNPAIRED: dict[int, float] = {
    32: 34.1,  # v0.2.1 计分集（T00 裁决后）——功效按它算，⛔ 不沿用 37
    37: 31.9,  # t8-rerun 的分母（37.8% 那批），留作对照
    100: 19.7,
    300: 11.3,
    500: 8.7,
}

#: §3.3 表②「配对」：翻转率 → (不一致题数, 最小显著分割 (b, c), 净回退题数, 净回退 pp)。
#: 分割写 None 表示「即便全部同向也不显著」。
DOC_PAIRED: dict[float, tuple[int, tuple[int, int] | None, int | None, float | None]] = {
    0.10: (3, None, None, None),
    0.20: (6, (6, 0), 6, 18.8),
    0.30: (10, (9, 1), 8, 25.0),
}

#: §5.2 表「m 的取值参考」：(|S|, ε 的百分数) → m。
DOC_M: dict[tuple[int, int], int] = {
    (6, 5): 2, (6, 10): 3, (6, 15): 3,
    (8, 5): 3, (8, 10): 3, (8, 15): 4,
    (10, 5): 3, (10, 10): 4, (10, 15): 4,
    (12, 5): 3, (12, 10): 4, (12, 15): 5,
    (14, 5): 3, (14, 10): 4, (14, 15): 5,
}

#: §5.2 表最后一列：ε=0.10 时，退化后单题失败率 0.5 的检出概率（%）。
DOC_DETECT: dict[int, int] = {6: 66, 8: 86, 10: 83, 12: 93, 14: 97}

#: §3.3 表① 的题量清单与 §5.2 m 表的 |S| 清单（渲染用，顺序即文档顺序）。
DOC_UNPAIRED_NS = (32, 37, 100, 300, 500)
DOC_M_SIZES = (6, 8, 10, 12, 14)
DOC_EPS_PCTS = (5, 10, 15)


def check_tables(n_scored: int | None = None) -> list[str]:
    """现算三张表并与文档冻结值逐格比对，返回不一致的描述（空 = 全一致）。"""
    n = n_scored if n_scored is not None else len(scored_tasks())
    bad: list[str] = []

    for n_i in DOC_UNPAIRED_NS:
        want = DOC_UNPAIRED[n_i]
        got = min_detectable_delta(n_i)
        if got is None:
            bad.append(f"§3.3 不配对 n={n_i}：现算饱和（n 太小），文档写 {want} pp")
        elif round(got, 1) != want:
            bad.append(f"§3.3 不配对 n={n_i}：现算 {got:.1f} pp，文档写 {want} pp")

    for rate in DOC_PAIRED:
        k_want, split_want, back_want, back_pp_want = DOC_PAIRED[rate]
        k = discordant_count(n, rate)
        if k != k_want:
            bad.append(f"§3.3 配对 翻转率 {rate:.0%}：现算不一致题 {k}，文档写 {k_want}")
            continue
        b = mcnemar_min_split(k)
        split = None if b is None else (b, k - b)
        if split != split_want:
            bad.append(f"§3.3 配对 翻转率 {rate:.0%}：现算最小显著分割 {split}，文档写 {split_want}")
            continue
        back = None if b is None else b - (k - b)
        back_pp = None if back is None else round(100 * back / n, 1)
        if back != back_want or back_pp != back_pp_want:
            bad.append(
                f"§3.3 配对 翻转率 {rate:.0%}：现算净回退 {back} 题 {back_pp} pp，"
                f"文档写 {back_want} 题 {back_pp_want} pp"
            )

    for (n_s, eps_pct), want in DOC_M.items():
        got = block_threshold(n_s, Fraction(eps_pct, 100))
        if got != want:
            bad.append(f"§5.2 m 表 |S|={n_s}, ε=0.{eps_pct:02d}：现算 m={got}，文档写 m={want}")

    for n_s, want in DOC_DETECT.items():
        got = round(100 * detection_prob(n_s, DOC_M[(n_s, 10)]))
        if got != want:
            bad.append(f"§5.2 检出概率 |S|={n_s}：现算 {got}%，文档写 {want}%")

    return bad


# ── 渲染与 CLI ──────────────────────────────────────────────────────


def render_tables(n_scored: int | None = None) -> str:
    """三张表的 markdown 渲染 —— 文档里的表**直接粘这里**，⛔ 不要手改数字。"""
    n = n_scored if n_scored is not None else len(scored_tasks())
    out: list[str] = []

    out.append("### §3.3 表①：不配对（两次各自比总分）可检出的最小差距\n")
    out.append("口径：α=0.05 双侧、功效 0.8、基线通过率 p≈14/37，两比例 arcsine 正态近似。\n")
    out.append("| 题量 n | 可检出差距 |")
    out.append("|---|---|")
    for n_i in DOC_UNPAIRED_NS:
        d = min_detectable_delta(n_i)
        note = "" if n_i != n else "（v0.2.1 计分集）"
        val = "近似饱和（n 太小）" if d is None else f"≈ {d:.1f} pp"
        out.append(f"| {n_i}{note} | {val} |")

    out.append("\n### §3.3 表②：配对（同一批题前后比、只看翻转的题）\n")
    out.append(f"口径：McNemar 精确检验，双侧 α=0.05，n={n}（计分集题数）。")
    out.append("翻转率是两次之间的不一致比例，不一致题数 = round(翻转率 × n)。\n")
    out.append("| 两次之间的翻转率 | 不一致题数 | 判显著需要 | 净回退 |")
    out.append("|---|---|---|---|")
    for rate in DOC_PAIRED:
        k = discordant_count(n, rate)
        b = mcnemar_min_split(k)
        if b is None:
            out.append(f"| {rate:.0%} | {k} | 不可能（全部同向也不显著） | — |")
        else:
            c = k - b
            out.append(f"| {rate:.0%} | {k} | {b} : {c} | {b - c} 题 ≈ {100 * (b - c) / n:.1f} pp |")

    out.append("\n### §5.2：阻断阈值 m 的取值参考\n")
    out.append("m = 在「S 里每题独立以 ε 失手」的零假设下，S 中失败 ≥ m 题的概率 ≤ 5% 的最小 m。\n")
    head = " | ".join(f"ε=0.{e:02d}" for e in DOC_EPS_PCTS)
    out.append(f"| \\|S\\| | {head} | 检出概率（ε=0.10，退化后单题失败率 0.5） |")
    out.append("|---|---|---|---|---|")
    for n_s in DOC_M_SIZES:
        cells = " | ".join(f"m={block_threshold(n_s, Fraction(e, 100))}" for e in DOC_EPS_PCTS)
        det = detection_prob(n_s, DOC_M[(n_s, 10)])
        out.append(f"| {n_s} | {cells} | {round(100 * det)}% |")

    return "\n".join(out) + "\n"


def _render_thresholds(res: dict) -> str:
    """`--baseline` 的结论渲染（T17 写回文档时直接引用）。"""
    out = [
        f"k = {res['k']}",
        f"|S| = {res['n_s']}",
        f"ε = {res['eps']:.4f}（{res['eps_source']}）",
        f"m = {res['m']}",
    ]
    if res["detect_prob"] is not None:
        out.append(f"检出概率（退化后单题失败率 0.5）= {res['detect_prob']:.1%}")
    if res["degraded"]:
        out.append(f"⚠️ 降级：{res['degrade_reason']} ⇒ REGRESSION 停用，L2 只看趋势（§5.2 预登记）")
    if res["notes"]:
        out.append(f"未进 S 的题 {len(res['notes'])} 条（前 5）："
                   + "，".join(f"{t}（{w}）" for t, w in list(res["notes"].items())[:5]))
    out.append("S = " + (", ".join(res["S"]) if res["S"] else "（空）"))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="T13：§3.3 功效计算 + §5.2 S/ε/m 阈值计算（纯 stdlib）",
    )
    ap.add_argument("--tables", action="store_true",
                    help="打印三张表（markdown）；无参数时的默认动作")
    ap.add_argument("--check", action="store_true",
                    help="现算三张表并与文档冻结值逐格对账，不一致退出 1")
    ap.add_argument("--baseline", nargs="+", type=Path, metavar="TRIALS_JSON",
                    help="k 份逐题结果（k≥2，trials.json 形态），算 S")
    ap.add_argument("--holdout", type=Path, metavar="TRIALS_JSON",
                    help="样本外一轮的逐题结果，估 ε（缺省 ⇒ 取预登记下限 0.10）")
    ap.add_argument("--scored", type=Path, metavar="JSON",
                    help="覆盖计分集来源（默认 meta/scoring-set.json）")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args(argv)

    if args.baseline:
        global SCORING_SET
        if args.scored:
            SCORING_SET = args.scored
        runs = [load_run(p) for p in args.baseline]
        holdout = load_run(args.holdout) if args.holdout else None
        res = thresholds(runs, holdout, set(scored_tasks()))
        print(json.dumps(res, ensure_ascii=False, indent=1) if args.json else _render_thresholds(res))
        return 0

    if args.check:
        bad = check_tables()
        for line in bad:
            print(f"::error::{line}")
        if bad:
            print(f"❌ {len(bad)} 处与文档冻结值不一致 —— 先确认现算正确，再改文档，最后同步 DOC_* 常量")
            return 1
        print("✅ 三张表与文档冻结值一致"
              "（§3.3 不配对 / §3.3 配对 / §5.2 m 表）")
        return 0

    # 默认（含显式 --tables）：打印 markdown
    print(render_tables(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
