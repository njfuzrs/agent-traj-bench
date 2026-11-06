#!/usr/bin/env python3
"""T16 — 样本外一轮：与 T15 第 1 轮比对，并给出 ε 的样本外估计。

方案见 docs-research `20261003-评测接入CI-CD-分层门禁与基线闭环.md` §6.6 T16 与 P2 验收：

    在另一个干净目录按 README 一条命令跑出的逐题结果，与基线第 1 轮的差异落在实测翻转率之内。

## 判据（跑出结果之前写定，⛔ 看到结果后不许改）

- **翻转** = 同一题两轮之间「solved（reward == 1.0）」不同。
- **可比题** = 两轮都有、且两边都不是 infra 故障（`Trial.infra_failure`，与 T15 同一判据）。
  ⛔ infra 那条不记成「没过」：那会把一次仪器故障记成一次翻转。
- **实测翻转率** = T15 三轮两两之间翻转率的**最大值**（k=3 只有 3 对，样本太少，
  取均值会把「本来就会出现的那一对」判成越界）。
- **通过** ⇔ 样本外轮 vs T15 第 1 轮的翻转率 ≤ 实测翻转率。

## ε

复用 `eval-stats.py` 的 `thresholds()`（不复制实现）：S 由 T15 三轮算，holdout = 本轮。
holdout 里 infra 故障的题**从 holdout 剔除** ⇒ 若 S 中有题落在 infra 上，
`epsilon_from_holdout` 会按「缺题」抛错 —— ⛔ 不许当作「未失败」，也不许当作「失败」。

## 用法

    # ① 把样本外轮的 run 目录（两档）序列化成 trials.json（与 T15 入库的形态一致）
    python3 scripts/t16-holdout.py dump <干净目录>/reports/t15-baseline/round1 \\
        --out reports/t16-holdout/trials.json --note "..."

    # ② 比对（纯复算，$0）
    python3 scripts/t16-holdout.py compare
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util as _ilu
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402
import t7_report_lib as rlib  # noqa: E402

T15_DIR = c.MVP_REPORTS / "t15-baseline"
T16_DIR = c.MVP_REPORTS / "t16-holdout"
BASE_ROUNDS = [T15_DIR / f"round{i}" for i in (1, 2, 3)]


def _load(name: str, file: str):
    spec = _ilu.spec_from_file_location(name, Path(__file__).parent / file)
    assert spec is not None and spec.loader is not None, file
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ───────────────────────────────────────────────────────────── 比对


def usable(trials: list[rlib.Trial]) -> dict[str, bool]:
    """{task: solved}，剔除 infra 故障。同一题出现两次 ⇒ 报错（k=1 轮次不该有重复）。"""
    out: dict[str, bool] = {}
    for t in trials:
        if t.task in out:
            raise SystemExit(f"⛔ {t.task} 在同一轮里出现两次 —— 这不是 k=1 的一轮")
        if not t.infra_failure:
            out[t.task] = t.solved
    return out


def flips(a: dict[str, bool], b: dict[str, bool]) -> tuple[list[str], int]:
    """(翻转题, 可比题数)。"""
    common = sorted(set(a) & set(b))
    return [t for t in common if a[t] != b[t]], len(common)


def compare(base: list[dict[str, bool]], hold: dict[str, bool]) -> dict:
    if len(base) < 2:
        raise SystemExit("⛔ 实测翻转率至少要两轮基线")
    pairs = []
    for (i, a), (j, b) in itertools.combinations(enumerate(base, 1), 2):
        fl, n = flips(a, b)
        pairs.append({"pair": f"R{i}-R{j}", "flips": fl, "n": n, "rate": len(fl) / n})
    ceiling = max(p["rate"] for p in pairs)
    fl, n = flips(base[0], hold)
    rate = len(fl) / n
    return {
        "baseline_pairs": pairs,
        "flip_ceiling": ceiling,
        "holdout_vs_r1": {"flips": fl, "n": n, "rate": rate,
                          "r1_only": sorted(t for t in fl if base[0][t]),
                          "holdout_only": sorted(t for t in fl if hold[t])},
        "pass": rate <= ceiling,
    }


def epsilon(holdout_trials: list[rlib.Trial]) -> dict:
    es = _load("eval_stats", "eval-stats.py")
    runs = [es.load_run(p / "trials.json") for p in BASE_ROUNDS]
    # infra_failure 已含 reward is None；显式再判一次给类型检查看
    hold = {t.task: float(t.reward) for t in holdout_trials if not t.infra_failure and t.reward is not None}
    return es.thresholds(runs, hold, set(es.scored_tasks()))


# ───────────────────────────────────────────────────────────── dump


def dump(round_dir: Path, out: Path, note: str, batch: str) -> None:
    """把一轮（t1800 + t2700 两个 jobs 目录）序列化成与 T15 入库同形态的 trials.json。"""
    rows, run_dirs, tier_of = [], [], {}
    for jobs in sorted(p for p in round_dir.iterdir() if p.is_dir() and p.name.startswith("t")):
        run_dirs += [f"{jobs.name}/{r.name}" for r in sorted(jobs.iterdir()) if r.is_dir() and r.name[:2] == "20"]
        for t in rlib.collect_all(jobs):
            d = dataclasses.asdict(t)
            d["errors"] = list(d["errors"])
            d["trial_dir"] = t.trial_dir.name if t.trial_dir else None   # ⛔ 不留本机绝对路径
            rows.append(d)
            tier_of[t.task] = jobs.name
    rows.sort(key=lambda r: r["task"])
    cfg = json.loads((round_dir / run_dirs[0] / "config.json").read_text(encoding="utf-8"))
    doc = {
        "_note": note,
        "_batch": batch,
        "n_trials": len(rows),
        "run_meta": {"n_concurrent_trials": cfg.get("n_concurrent_trials"), "run_dirs": run_dirs,
                     "tier_of_task": dict(sorted(tier_of.items()))},
        "rows": rows,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"写出 {out}（{len(rows)} 条）")


# ───────────────────────────────────────────────────────────── CLI


def _render(res: dict, eps: dict) -> str:
    h = res["holdout_vs_r1"]
    out = ["## T16 样本外一轮 vs T15 第 1 轮", "", "| 对 | 可比题 | 翻转 | 翻转率 | 翻转题 |", "|---|---|---|---|---|"]
    for p in res["baseline_pairs"]:
        out.append(f"| {p['pair']} | {p['n']} | {len(p['flips'])} | {p['rate']:.1%} | {' '.join(p['flips'])} |")
    out.append(f"| **H-R1** | {h['n']} | {len(h['flips'])} | {h['rate']:.1%} | {' '.join(h['flips'])} |")
    out += ["", f"实测翻转率上限（T15 两两最大）= {res['flip_ceiling']:.1%}；"
            f"H-R1 = {h['rate']:.1%} ⇒ **{'通过' if res['pass'] else '越界'}**",
            f"R1 过、H 没过：{h['r1_only'] or '无'}；H 过、R1 没过：{h['holdout_only'] or '无'}", "",
            f"S = {eps['S']}（|S|={eps['n_s']}），ε = {eps['eps_frac']}（{eps['eps_source']}），"
            f"m = {eps['m']}，降级 = {eps['degraded']}（{eps['degrade_reason']}）"]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="T16 样本外一轮")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump")
    d.add_argument("round_dir", type=Path)
    d.add_argument("--out", type=Path, default=T16_DIR / "trials.json")
    d.add_argument("--note", required=True)
    d.add_argument("--batch", default="t16-holdout")
    p = sub.add_parser("compare")
    p.add_argument("--holdout", type=Path, default=T16_DIR, help="装着 trials.json 的目录")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "dump":
        dump(a.round_dir, a.out, a.note, a.batch)
        return 0
    base = [usable(rlib.load_trials_json(r)) for r in BASE_ROUNDS]
    hold_trials = rlib.load_trials_json(a.holdout)
    if not hold_trials:
        raise SystemExit(f"⛔ {a.holdout}/trials.json 不存在或为空")
    res = compare(base, usable(hold_trials))
    res["infra_excluded"] = sorted(t.task for t in hold_trials if t.infra_failure)
    eps = epsilon(hold_trials)
    print(json.dumps({**res, "thresholds": eps}, ensure_ascii=False, indent=1) if a.json else _render(res, eps))
    if res["infra_excluded"]:
        print(f"⚠️ 样本外轮 infra 排除 {len(res['infra_excluded'])} 条：{res['infra_excluded']}")
    return 0 if res["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
