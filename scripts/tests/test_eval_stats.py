"""T13：§3.3 功效表与 §5.2 S/ε/m 阈值表。

阳性对照用方案文档里已冻结的三张表（现算必须逐格一致），
变异自证用**改参数**的调用证明每一格确实由对应参数决定 ——
一个恒绿的统计脚本比没有脚本更危险（它会把错误的表锁进文档）。
"""

from __future__ import annotations

import importlib.util
from fractions import Fraction
from pathlib import Path

import pytest

MVP = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("_eval_stats", MVP / "eval-stats.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


es = _load()


# ── §3.3 表①：不配对 ────────────────────────────────────────────────


def test_unpaired_matches_doc():
    """文档表① 逐格复现。

    ⚠️ n=37 的 31.9 是**修正值**：文档原写 ≈27 pp（手算偏了 5 pp）。
    T13 的口径是「不一致就以脚本为准改文档」，这里锁住脚本这一侧。
    """
    got = [round(es.min_detectable_delta(n), 1) for n in (32, 37, 100, 300, 500)]
    assert got == [34.1, 31.9, 19.7, 11.3, 8.7]


def test_unpaired_is_monotone():
    """题量越大，可检出差距越小 —— 公式写反方向会立刻在此暴露。"""
    ds = [es.min_detectable_delta(n) for n in (10, 37, 100, 300, 500)]
    assert all(a is not None and b is not None and a > b for a, b in zip(ds, ds[1:]))


def test_unpaired_saturates_for_tiny_n():
    """n 太小时 arcsin 域被顶满，必须返回 None，⛔ 不许编一个「100 pp」的读数。

    n=4 时 φ₂ = φ₁ + h 已越过 π（asin 域顶满），此时的「p₂」不是读数。
    n=5 能算出值，但已 >60 pp —— 说明那个题量根本没有判别力，
    把它当「可检出差距」写进表里会误导人。
    """
    assert es.min_detectable_delta(4) is None
    assert es.min_detectable_delta(5) > 60
    with pytest.raises(ValueError):
        es.min_detectable_delta(1)


def test_unpaired_depends_on_p_base():
    """变异自证：工作点 p 变了，同一 n 的可检出差距必须跟着变。

    §3.3 的「换模型 = 换指纹 = 重建基线」在功效上有直接后果：
    p 靠近 0.5 时方差最大，同样 n 能检出的差距更大。
    """
    assert es.min_detectable_delta(100, p=0.10) < es.min_detectable_delta(100, p=0.378)
    assert es.min_detectable_delta(100, p=0.50) > es.min_detectable_delta(100, p=0.10)


# ── §3.3 表②：配对（McNemar 精确）────────────────────────────────────


def test_discordant_count_rounds():
    """§3.3 的口径是四舍五入（3.7→4、7.4→7、11.1→11），⛔ 不是向下取整。"""
    assert [es.discordant_count(37, r) for r in (0.10, 0.20, 0.30)] == [4, 7, 11]
    assert [es.discordant_count(32, r) for r in (0.10, 0.20, 0.30)] == [3, 6, 10]


def test_mcnemar_matches_doc():
    """文档表② 的两组数字：旧口径 37 题、v0.2.1 计分集 32 题。"""
    assert es.mcnemar_min_split(4) is None            # 4 条全部同向也不显著
    assert es.mcnemar_min_split(7) == 7               # 7 : 0
    assert es.mcnemar_min_split(11) == 10             # 10 : 1
    assert es.mcnemar_min_split(3) is None            # 32 题 × 10%
    assert es.mcnemar_min_split(6) == 6               # 32 题 × 20% → 6 : 0
    assert es.mcnemar_min_split(10) == 9              # 32 题 × 30% → 9 : 1


def test_mcnemar_requires_direction():
    """b 必须 > k/2。3:0 单侧 p=0.125、双侧 0.25 ⇒ ⛔ 不能因为「全同向」就判显著。"""
    assert es.mcnemar_min_split(3) is None
    assert es.mcnemar_min_split(2) is None


# ── §5.2：m 表 ─────────────────────────────────────────────────────


def test_m_table_matches_doc():
    for (n_s, eps_pct), want in es.DOC_M.items():
        assert es.block_threshold(n_s, Fraction(eps_pct, 100)) == want, (n_s, eps_pct)


def test_m_boundary_is_exact_not_float():
    """|S|=10、ε=0.15：P(X≥4)=0.04997，离 α=0.05 只有 3e-5 —— 这一格必须精确。

    浮点实现能「碰巧」判对与否取决于累加顺序；这条断言锁住精确有理数这条实现路径。
    """
    eps = Fraction(15, 100)
    assert es.binom_tail(10, eps, 4) <= es.ALPHA
    assert es.binom_tail(10, eps, 3) > es.ALPHA
    assert abs(float(es.binom_tail(10, eps, 4)) - 0.04997) < 5e-6


def test_m_monotone_in_eps():
    """ε 越大，m 不减：同样的零假设下需要更多失败才显著。"""
    for n_s in (6, 8, 10, 12, 14):
        ms = [es.block_threshold(n_s, Fraction(e, 100)) for e in (5, 10, 15)]
        assert ms == sorted(ms), (n_s, ms)


def test_m_none_when_not_significant():
    """|S| 太小 / ε 太大时 m 不存在 —— 这是 §5.2 降级规则的触发条件，⛔ 不是可以编个数。"""
    assert es.block_threshold(1, Fraction(1, 2)) is None
    assert es.block_threshold(2, Fraction(1, 2)) is None


def test_detect_prob_matches_doc():
    got = [round(100 * es.detection_prob(n, es.DOC_M[(n, 10)])) for n in (6, 8, 10, 12, 14)]
    assert got == [66, 86, 83, 93, 97]


# ── §5.2 三个冻结量（真实数据路径，T15 → T17 用）──────────────────────


def test_stability_set_requires_all_runs():
    """S = k 份里**每一份**都过。2/3 过的是不稳定题，§5.2 规定只能触发 WARN。"""
    runs = [
        {"T1": 1.0, "T2": 1.0, "T3": 0.0, "T4": 1.0},
        {"T1": 1.0, "T2": 0.0, "T3": 0.0, "T4": 0.0},
        {"T1": 1.0, "T2": 1.0, "T3": 0.0, "T4": 0.0},
    ]
    s, notes = es.stability_set(runs)
    assert s == ["T1"]
    assert "2/3" in notes["T2"]
    assert "T3" not in notes      # 全 0 的题既不是 S 也不是「不稳定」（那是难/没解出）
    assert "1/3" in notes["T4"]   # 偶尔过也是不稳定题


def test_stability_set_drops_missing():
    """某题只出现在 2/3 份结果里 → 不进 S（覆盖不全不能判「稳定」）。"""
    runs = [{"T1": 1.0}, {"T1": 1.0}, {"T2": 1.0}]
    s, notes = es.stability_set(runs)
    assert s == []
    assert "只出现在 2/3" in notes["T1"]


def test_stability_set_respects_scored():
    """计分集之外的题（audit / excluded）不进 S。"""
    runs = [{"T1": 1.0, "AUDIT": 1.0}] * 3
    s, _ = es.stability_set(runs, scored={"T1"})
    assert s == ["T1"]


def test_epsilon_floor():
    """样本外 0 失败也要取预登记下限 0.10（§5.2：样本内估计有偏，且下限预先登记）。"""
    assert es.epsilon_from_holdout({"T1": 1.0, "T2": 1.0}, ["T1", "T2"]) == Fraction(1, 10)


def test_epsilon_above_floor():
    """样本外实测更大时以实测为准（floor 只兜底）。"""
    assert es.epsilon_from_holdout({"T1": 1.0, "T2": 0.0}, ["T1", "T2"]) == Fraction(1, 2)


def test_epsilon_missing_task_fails_closed():
    """缺题必须报错，⛔ 不许当作「未失败」—— 那会低报 ε、进而低报 m。"""
    with pytest.raises(SystemExit):
        es.epsilon_from_holdout({"T1": 1.0}, ["T1", "T2"])


def test_thresholds_degrades_below_min_s():
    """|S| < 6 ⇒ 降级（§5.2 预先登记的规则，不是看到数据再决定）。"""
    runs = [{f"T{i}": 1.0 for i in range(5)}] * 3
    res = es.thresholds(runs, scored={f"T{i}" for i in range(5)})
    assert res["n_s"] == 5
    assert res["degraded"] is True
    assert "|S|=5" in res["degrade_reason"]


def test_thresholds_full_path():
    """端到端：10 题全过、样本外 1 题失手 ⇒ ε=0.10、m=4、不降级。"""
    scored = {f"T{i}" for i in range(10)}
    runs = [{t: 1.0 for t in scored}] * 3
    holdout = {f"T{i}": 1.0 for i in range(9)} | {"T9": 0.0}
    res = es.thresholds(runs, holdout, scored=scored)
    assert res["n_s"] == 10
    assert res["eps"] == 0.1
    assert res["m"] == 4
    assert res["degraded"] is False
    assert res["detect_prob"] == pytest.approx(0.8281, abs=1e-4)


def test_thresholds_without_holdout_uses_floor():
    """没给样本外数据 ⇒ ε 取下限并在结果里标明来源（⛔ 不许拿 k 份自己估）。"""
    scored = {f"T{i}" for i in range(8)}
    runs = [{t: 1.0 for t in scored}] * 3
    res = es.thresholds(runs, scored=scored)
    assert res["eps"] == 0.1
    assert "预登记下限" in res["eps_source"]


def test_load_run_rejects_other_shapes(tmp_path):
    """只认 trials.json 的 rows 形态 —— 别的形态静默返回空 dict 会让 S 变空而不报错。"""
    p = tmp_path / "x.json"
    p.write_text('{"per_task": {}}', encoding="utf-8")
    with pytest.raises(SystemExit):
        es.load_run(p)


def test_load_run_drops_null_reward(tmp_path):
    """reward=None（verifier 没写分）必须丢弃，⛔ 不许记 0 —— 那是把仪器故障记成答错。"""
    p = tmp_path / "x.json"
    p.write_text(
        '{"rows": [{"task": "T1", "reward": 1.0}, {"task": "T2", "reward": null}]}',
        encoding="utf-8",
    )
    assert es.load_run(p) == {"T1": 1.0}


# ── 文档对账 ───────────────────────────────────────────────────────


def test_check_tables_all_green():
    """现算三张表必须与 DOC_* 冻结值逐格一致。"""
    assert es.check_tables(n_scored=32) == []


def test_check_detects_drift(monkeypatch):
    """变异自证：把冻结值改一格，对账必须报出来 —— 恒绿的对账等于没有对账。"""
    monkeypatch.setitem(es.DOC_UNPAIRED, 37, 27.0)   # 文档修订前的旧值
    bad = es.check_tables(n_scored=32)
    assert any("n=37" in b and "31.9" in b for b in bad), bad


def test_check_detects_m_drift(monkeypatch):
    """变异自证（第二处）：m 表改一格也必须报出。"""
    monkeypatch.setitem(es.DOC_M, (10, 15), 3)
    bad = es.check_tables(n_scored=32)
    assert any("|S|=10, ε=0.15" in b for b in bad), bad


def test_render_contains_all_three_tables():
    md = es.render_tables(n_scored=32)
    assert "≈ 34.1 pp" in md and "9 : 1" in md and "| 10 |" in md
    assert "m=2" in md and "m=5" in md
