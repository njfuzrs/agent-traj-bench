"""D4 探针的纯逻辑：探针题现算、S 现算、判据。不跑 harbor（$0）。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

MVP = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("_d4", MVP / "d4-turns-probe.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


d4 = _load()


def _rows(spec: dict[str, list[tuple[str, float]]]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {1: [], 2: [], 3: []}
    for task, triples in spec.items():
        for r, (st, rw) in enumerate(triples, start=1):
            out[r].append({"task": task, "subtype": st, "reward": rw})
    return out


ROWS = _rows({
    "TA": [("success", 1.0)] * 3,                                         # 在 S 里
    "TB": [("error_max_turns", 0.0), ("success", 0.0), ("success", 0.0)],  # 撞过顶
    "TC": [("success", 0.0)] * 3,                                         # 从没撞顶
    "TD": [("error_max_turns", 1.0), ("success", 1.0), ("success", 1.0)],  # 撞过顶且在 S 里
})


def test_probe_tasks_from_trials():
    assert d4.probe_tasks(ROWS) == ["TB", "TD"]


def test_s_is_full_pass_only():
    assert d4.t15_full_pass(ROWS) == {"TA", "TD"}


def test_real_t15_probe_set_is_14():
    # 入库产物：T15 三轮里撞过 120 轮的题。数变了说明 trials 被改过，探针名单要重看。
    assert len(d4.probe_tasks()) == 14
    assert d4.t15_full_pass() == {"T0040", "T0050", "T0059"}


def test_verdict_useful_needs_both_conditions():
    s = {"T0050"}
    # 4 题判分：1 题仍撞顶（≤ 一半），3 题新过 ⇒ 有用
    res = {"A": ("success", 1.0), "B": ("success", 1.0), "C": ("success", 1.0), "D": ("error_max_turns", 0.0)}
    assert d4.verdict(res, s)["useful"] is True
    # 新过的里有一题本来就在 S ⇒ 只算 2 题 ⇒ 没用
    res2 = dict(res, A=("success", 1.0))
    assert d4.verdict(res2, {"A"})["useful"] is False
    # 一半以上仍撞顶 ⇒ 没用（哪怕新过够数）
    res3 = {"A": ("success", 1.0), "B": ("success", 1.0), "C": ("success", 1.0),
            "D": ("error_max_turns", 0.0), "E": ("error_max_turns", 0.0), "F": ("error_max_turns", 0.0),
            "G": ("error_max_turns", 0.0)}
    assert d4.verdict(res3, s)["useful"] is False


def test_verdict_infra_not_counted():
    # reward=None 是 infra：不进分母，也不算「没跑完」
    res = {"A": ("success", 1.0), "B": ("success", 1.0), "C": ("success", 1.0), "X": ("error_during_execution", None)}
    v = d4.verdict(res, set())
    assert v["n_judged"] == 3 and v["n_infra"] == 1 and v["useful"] is True


def test_verdict_empty_is_not_useful():
    assert d4.verdict({}, set())["useful"] is False


def test_summary_without_results_returns_1_and_writes_nothing(tmp_path, monkeypatch):
    # 探针还没跑时 --summary 不许崩，也不许写一份「0 题、判 (a)」的假结论
    t15 = d4._load("t15_baseline", "t15-baseline.py")
    monkeypatch.setattr(t15.c, "MVP_REPORTS", tmp_path)
    monkeypatch.setattr(d4, "_load", lambda *_: t15)
    assert d4.main(["--summary"]) == 1
    assert not list(tmp_path.rglob("summary.json"))
