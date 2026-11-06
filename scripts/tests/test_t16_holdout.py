"""T16 样本外比对的纯逻辑（$0，不跑 harbor）。"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

MVP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MVP))
import t7_report_lib as rlib  # noqa: E402


def _load():
    spec = importlib.util.spec_from_file_location("_t16", MVP / "t16-holdout.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


t16 = _load()


def _t(task, reward=0.0, exception=None, subtype="success", errors=()):
    return rlib.Trial(task=task, reward=reward, f2p=None, p2p=None, error_code=0,
                      exception=exception, subtype=subtype, errors=tuple(errors))


def test_infra_is_dropped_not_counted_as_fail():
    # T15 R3 的 T0007/T0018 形态：NonZeroAgentExitCodeError ⇒ infra，不进可比题
    u = t16.usable([_t("A", 1.0), _t("B", 0.0, exception="NonZeroAgentExitCodeError",
                                       subtype="error_during_execution")])
    assert u == {"A": True}


def test_duplicate_task_in_one_round_is_rejected():
    with pytest.raises(SystemExit):
        t16.usable([_t("A"), _t("A")])


def test_flips_only_over_common_tasks():
    fl, n = t16.flips({"A": True, "B": False, "C": True}, {"A": False, "B": False})
    assert (fl, n) == (["A"], 2)


def test_ceiling_is_max_pair_and_boundary_passes():
    # R1-R2 翻 1/4（B）、R1-R3 翻 2/4（B C）、R2-R3 翻 1/4（C）⇒ 上限 50%
    r1 = {"A": True, "B": True, "C": False, "D": False}
    r2 = {"A": True, "B": False, "C": False, "D": False}
    r3 = {"A": True, "B": False, "C": True, "D": False}
    hold_eq = {"A": False, "B": False, "C": False, "D": False}       # vs R1 翻 2/4 = 50% ⇒ 通过（≤）
    hold_over = {"A": False, "B": False, "C": True, "D": False}      # 翻 3/4 ⇒ 越界
    res = t16.compare([r1, r2, r3], hold_eq)
    assert res["flip_ceiling"] == 0.5 and res["pass"]
    assert res["holdout_vs_r1"]["r1_only"] == ["A", "B"]
    assert not t16.compare([r1, r2, r3], hold_over)["pass"]


def test_real_t15_rounds_ceiling():
    """入库的 T15 三轮：两两翻转 3/32、3/30、2/30 ⇒ 上限 10%（判据写定时的事实）。"""
    base = [t16.usable(rlib.load_trials_json(r)) for r in t16.BASE_ROUNDS]
    res = t16.compare(base, base[0])
    assert [len(p["flips"]) for p in res["baseline_pairs"]] == [3, 3, 2]
    assert res["flip_ceiling"] == pytest.approx(0.10)
    assert res["holdout_vs_r1"]["rate"] == 0 and res["pass"]


def test_epsilon_refuses_holdout_missing_s_task():
    # S 中题在 holdout 是 infra ⇒ 缺题 ⇒ 必须抛错，不许当「未失败」
    hold = [_t(t, 1.0) for t in ("T0040", "T0050")] + [
        _t("T0059", 0.0, exception="NonZeroAgentExitCodeError", subtype="error_during_execution")]
    with pytest.raises(SystemExit):
        t16.epsilon(hold)


def test_epsilon_from_holdout_failures():
    # S = {T0040, T0050, T0059}；holdout 挂 1 题 ⇒ ε = 1/3
    hold = [_t("T0040", 1.0), _t("T0050", 1.0), _t("T0059", 0.0)]
    res = t16.epsilon(hold)
    assert res["S"] == ["T0040", "T0050", "T0059"] and res["eps_frac"] == "1/3"


def test_dump_roundtrips_through_load_trials_json(tmp_path):
    rnd = tmp_path / "round1"
    run = rnd / "t1800" / "2026-11-06__10-00-00"
    trial = run / "T0040__abc"
    (trial / "verifier").mkdir(parents=True)
    (run / "config.json").write_text(json.dumps({"n_concurrent_trials": 6}))
    (trial / "result.json").write_text(json.dumps({
        "task_name": "T0040", "verifier_result": {"rewards": {"reward": 1.0}},
        "agent_result": {"metadata": {"sid_subtype": "success"}}}))
    (trial / "verifier" / "reward.txt").write_text("1.0")
    out = tmp_path / "out" / "trials.json"
    t16.dump(rnd, out, "note", "t16-holdout")
    doc = json.loads(out.read_text())
    assert "/Users/" not in out.read_text() and str(tmp_path) not in out.read_text()
    assert doc["run_meta"]["tier_of_task"] == {"T0040": "t1800"}
    back = rlib.load_trials_json(out.parent)
    assert [(t.task, t.reward) for t in back] == [("T0040", 1.0)]
