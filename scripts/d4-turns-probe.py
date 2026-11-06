#!/usr/bin/env python3
"""D4 探针：放宽 `max_turns` 能把多少「撞 120 轮」的题跑完、跑过。

方案见 docs-research `20261003-评测接入CI-CD-分层门禁与基线闭环.md` §7.1 D4（建议 (a) 为主 + (b) 探针）。

## 这是探针，不是基线

- 只跑 **T15 三轮里至少撞过一次 120 轮的题**（`probe_tasks()` 从入库 trials 现算，不手写名单）。
- 只改一个变量：`max_turns` 120 → `--max-turns`（缺省 200）。二进制、模型、预算、`max_duration_ms`、
  分档、并发全部沿用 `t15-baseline.py`（直接 import，不复制常量）。
- k=1。结果**不进**基线、不进 S/ε/m，只回答 D4 的一个问题：放宽后 |S| 有没有希望 ≥ 6。
  ⛔ 不许拿它的通过率和 T15 的 15.6% 并排写成「放宽后提升到 X%」——题集不同（只挑了撞顶题）、k 不同。

## 判据（跑前写定，⛔ 看到结果后不许改）

对每题记两件事：① 是否仍撞 `max_turns`（`subtype == error_max_turns`）；② reward。

- **「放宽有用」** ⇔ 至少一半的探针题不再撞顶，**且**有 ≥ 3 题 reward=1、而它们在 T15 里不是 3/3 全过。
  后者是 |S| 从 3 到 6 的最低必要条件（S 要求 k 次全过，探针 k=1 只能给上界）。
- 不满足 ⇒ D4 选 (a)，不整套重跑。

## 用法

    # 只看会跑哪些题（$0）
    python3 scripts/d4-turns-probe.py --list

    # 正式跑（约 14 题 × 1 轮；caffeinate 包住；必须等 T16 跑完，别和它抢网关）
    caffeinate -dimsu ~/.local/share/uv/tools/harbor/bin/python scripts/d4-turns-probe.py \\
        --binary <与 T15 同一个二进制> [--max-turns 200]

    # 汇总（$0）
    python3 scripts/d4-turns-probe.py --summary
"""

from __future__ import annotations

import argparse
import importlib.util as _ilu
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def _load(name: str, file: str):
    spec = _ilu.spec_from_file_location(name, HERE / file)
    assert spec is not None and spec.loader is not None, file
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


T15_TRIALS = HERE.parent / "reports" / "t15-baseline"
#: 最低必要条件里的「3」：|S| 从 3 到 6 至少要多 3 题。
MIN_NEW_SOLVED = 3


def load_t15_rows() -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for r in (1, 2, 3):
        d = json.loads((T15_TRIALS / f"round{r}" / "trials.json").read_text(encoding="utf-8"))
        out[r] = d["rows"]
    return out


def probe_tasks(rows: dict[int, list[dict]] | None = None) -> list[str]:
    """T15 三轮里至少撞过一次 120 轮的题（现算）。"""
    rows = rows if rows is not None else load_t15_rows()
    return sorted({t["task"] for rr in rows.values() for t in rr if t.get("subtype") == "error_max_turns"})


def t15_full_pass(rows: dict[int, list[dict]] | None = None) -> set[str]:
    """T15 里 3/3 全过的题（= 现在的 S）。"""
    rows = rows if rows is not None else load_t15_rows()
    by: dict[str, list[float]] = {}
    for rr in rows.values():
        for t in rr:
            by.setdefault(t["task"], []).append(t.get("reward") or 0.0)
    return {k for k, v in by.items() if len(v) == 3 and all(x == 1.0 for x in v)}


def verdict(results: dict[str, tuple[str | None, float | None]], s_now: set[str]) -> dict:
    """按跑前写定的判据出结论。results: task → (subtype, reward)。infra（reward 为 None）不计入分母。"""
    judged = {k: v for k, v in results.items() if v[1] is not None}
    n = len(judged)
    still_capped = sorted(k for k, (st, _) in judged.items() if st == "error_max_turns")
    new_solved = sorted(k for k, (_, rw) in judged.items() if rw == 1.0 and k not in s_now)
    uncapped_ok = n > 0 and (n - len(still_capped)) * 2 >= n
    useful = uncapped_ok and len(new_solved) >= MIN_NEW_SOLVED
    return {
        "n_judged": n,
        "n_infra": len(results) - n,
        "still_capped": still_capped,
        "new_solved": new_solved,
        "half_uncapped": uncapped_ok,
        "useful": useful,
        "decision": "(b) 有希望：可考虑整套重跑" if useful else "(a)：不整套重跑",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="D4 max_turns 探针")
    ap.add_argument("--binary", type=Path)
    ap.add_argument("--max-turns", type=int, default=200)
    ap.add_argument("--list", action="store_true", help="只列探针题（$0）")
    ap.add_argument("--summary", action="store_true", help="只汇总已有结果（$0）")
    a = ap.parse_args(argv)

    tasks = probe_tasks()
    if a.list:
        print(f"{len(tasks)} 题：{' '.join(tasks)}")
        return 0

    t15 = _load("t15_baseline", "t15-baseline.py")
    out = t15.c.MVP_REPORTS / "d4-turns-probe" / f"mt{a.max_turns}"

    if not a.summary:
        if a.binary is None:
            ap.error("正式跑必须给 --binary")
        t15.bypass_loopback_proxy()
        setattr(t15, "MAX_TURNS", a.max_turns)   # ← 唯一改动的变量（build_cmd 调用时读模块全局）
        red, commit = t15.preflight(a.binary.expanduser().resolve(), t15.t7.HARBOR_DIR.parents[2])
        if red:
            print("🔴 闸未过，拒绝开跑：", *red, sep="\n  - ")
            return 1
        env = t15.build_env(a.binary.expanduser().resolve())
        for sec, ts in sorted(t15.tiers().items()):
            todo = [t for t in ts if t in tasks]
            if not todo:
                continue
            path = t15.stage_tier(sec, todo)
            jobs = out / f"t{sec}"
            jobs.mkdir(parents=True, exist_ok=True)
            t15.c.assert_jobs_dir_ok(jobs)
            print(f"t{sec}：{len(todo)} 题，max_turns={a.max_turns}，max_duration_ms={t15.DURATION_BY_TIMEOUT[sec]} …",
                  flush=True)
            t0 = time.time()
            with open(jobs / f"run-{time.strftime('%Y%m%d-%H%M%S')}.log", "w", encoding="utf-8") as f:
                subprocess.run(t15.build_cmd(path, jobs, t15.DURATION_BY_TIMEOUT[sec]), stdout=f,
                               stderr=subprocess.STDOUT, env=env, check=False, stdin=subprocess.DEVNULL)
            print(f"  用时 {(time.time() - t0) / 60:.1f} 分钟")
        print(f"二进制 commit {str(commit)[:12]}")

    results: dict[str, tuple[str | None, float | None]] = {}
    cost = 0.0
    for f in sorted(out.glob("t*/20*/T0*/result.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        md = (d.get("agent_result") or {}).get("metadata") or {}
        rw = ((d.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        results[f.parent.name.split("__")[0]] = (md.get("sid_subtype"), rw if isinstance(rw, (int, float)) else None)
        cost += float((d.get("agent_result") or {}).get("cost_usd") or 0.0)
    v = verdict(results, t15_full_pass())
    v["cost_usd"] = round(cost, 2)
    v["max_turns"] = a.max_turns
    v["per_task"] = {k: {"subtype": st, "reward": rw} for k, (st, rw) in sorted(results.items())}
    if not results:
        print(f"⚠️ {out} 下没有任何已判分的 trial —— 探针还没跑，或 harbor 没产出（不写 summary）")
        return 1
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(v, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v[k] for k in v if k != "per_task"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
