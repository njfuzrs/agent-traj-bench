#!/usr/bin/env python3
"""T7 前置 —— 单独重跑复检里失败的那几条，分辨 flaky 与真缺陷（**$0**）。

## 为什么需要这一步

`t7-regate.py` 在 39 条上重跑 oracle 时，`T0049` / `T0064` 两条挂了。
两条都不是判分红，而是**镜像构建期** `bun install` 报
`Integrity check failed for tarball`（typescript / marked / bun-types 等多个包）。

已经排除的两种解释：

  - **不是 task 自身缺陷**：两条在 T5 三道门禁下 oracle/nop/oracle-k3 **全绿且三次一致**。
  - **不是「单独构建就不行」**：两条**裸构建**（`docker build`，不经 harbor、
    无任何 egress 策略）都成功 —— 786MB / 793MB、零 integrity 报错，
    且 `bun install` 那层实测**未命中缓存**（日志里 `#10` 真的在跑 install）。

⚠️ 我在归因上**错过一次**，记在这里防止再犯：曾数出「只有 2 条 trial.log 里出现
`bake`，而它们正是失败的 2 条」，据此宣布因果确认。**这个推论是错的** ——
`docker compose` v5 默认就用 bake，所有条都走它；只是**失败的那条会把 buildx
的完整输出打进日志，成功的不打**。那是**日志差异，不是构建路径差异**。
教训与 08 号 §4.11 那次 SE 算错同源：**相关不等于因果，先怀疑仪器和自己的读数。**

剩下最可能的解释是并发/资源争抢或上游抖动（T0064 那次卡了 20 分钟才报错）。
分辨方法只有一个：**在同样的 allowlist 策略下、串行、单独重跑**。

  - 两条都过 ⇒ **flaky**（infra 抖动）。可以开跑基线；
    这两条若在基线里再失败，按 infra 排除出分母（不记为答错）。
  - 仍然红 ⇒ 不是抖动。那就别开跑，回去查 egress 策略对构建期的影响
    （回退方案：只在 verifier 阶段收紧，`[verifier].network_mode`）。

## 判据

与 T5/复检完全同一套：**不看退出码**（harbor 失败时也返 0），只看
`Trials` / `Exceptions` + 逐 task `reward`。oracle 打了 gold patch ⇒ 必须 reward=1。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402
import t7_report_lib as lib  # noqa: E402

OUT = c.MVP_REPORTS / "t7-regate/retry"

#: 复检里失败的两条。刻意写死而不是从产物里扫 —— 重跑对象要**显式可见**，
#: 免得将来有人改了扫描逻辑就悄悄换了重跑范围。
DEFAULT_TASKS = ["T0049", "T0064"]


def stage(tasks: list[str], where: Path) -> Path:
    """symlink 出一个只含待重跑 task 的目录（harbor 的 `-p` 收目录）。"""
    if where.exists():
        for p in where.iterdir():
            p.unlink() if p.is_symlink() else None
    where.mkdir(parents=True, exist_ok=True)
    for t in tasks:
        (where / t).symlink_to((c.MVP_TASKS / t).resolve())
    got = sorted(p.name for p in where.iterdir())
    if got != sorted(tasks):
        raise SystemExit(f"stage 与名单不一致：{got} vs {tasks}")
    return where


def run(task_path: Path, out: Path) -> float:
    out.mkdir(parents=True, exist_ok=True)
    c.assert_jobs_dir_ok(out)                      # R-3：必须在 $HOME 下
    cmd = [
        "harbor", "run",
        "-p", str(task_path),
        "-a", "oracle",
        "-n", "1",                                  # 串行 —— 正是要排除并发争抢
        "-o", str(out),
        "--verifier-timeout-multiplier", "6",
        "-y",
    ]
    env = {**os.environ, "HARBOR_TELEMETRY": "0"}   # R-2
    t0 = time.time()
    with open(out / "run.log", "w", encoding="utf-8") as f:
        # stdin=DEVNULL：不给会挂死在 `buildx bake --file -` 读 stdin（实测挂 20min，
        # 形态是 %CPU=0、日志停在 "Building Docker image" 不动，不报错不超时）
        subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env=env,
                       check=False, stdin=subprocess.DEVNULL)
    return time.time() - t0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", nargs="*", default=DEFAULT_TASKS)
    ap.add_argument("--round", type=int, default=1, help="第几轮重跑（产物分目录，便于看是否稳定复现）")
    args = ap.parse_args()

    tasks = sorted(args.tasks)
    out = OUT / f"round{args.round}"
    print(f"重跑 {tasks}（oracle，串行，$0）→ {out.name}")

    elapsed = run(stage(tasks, out / "tasks"), out)
    print(f"  跑完 {elapsed / 60:.1f} 分钟")

    run_dir = lib.latest_run(out)
    rows = lib.collect(run_dir) if run_dir else []
    got = {r.task for r in rows}

    verdicts = {}
    for t in tasks:
        row = next((r for r in rows if r.task == t), None)
        if row is None:
            verdicts[t] = {"ok": False, "why": "产物里没有这条 trial —— 看 run.log"}
        elif row.reward == 1.0:
            verdicts[t] = {"ok": True, "why": "oracle 通过 ⇒ 上一轮那次是 flaky（infra 抖动）"}
        else:
            # 取构建期报错的关键行，别整段贴 —— 整段会把 Dockerfile 全文带进来
            exc_file = (row.trial_dir or Path()) / "exception.txt"
            hint = ""
            if exc_file.exists():
                errs = {ln.strip() for ln in exc_file.read_text(errors="replace").splitlines()
                        if "error:" in ln or "Integrity" in ln}
                hint = "；".join(sorted(errs)[:3])[:200]
            verdicts[t] = {"ok": False, "reward": row.reward,
                           "exception": row.exception, "hint": hint,
                           "why": "仍然红 ⇒ 不是抖动，别开跑基线，回查 egress 对构建期的影响"}

    all_ok = all(v["ok"] for v in verdicts.values())
    (out / "verdict.json").write_text(json.dumps({
        "purpose": "单独串行重跑复检失败条，分辨 flaky 与真缺陷",
        "round": args.round,
        "tasks": tasks,
        "n_trials": len(rows),
        "missing": sorted(set(tasks) - got),
        "verdicts": verdicts,
        "all_pass": all_ok,
        "elapsed_min": round(elapsed / 60, 1),
        "cost_usd": 0,
        "ruled_out": [
            "task 自身缺陷：T5 三道门禁 oracle/nop/oracle-k3 全绿且三次一致",
            "单独构建不行：裸 docker build 两条都成功（786MB/793MB，零 integrity 报错，bun install 层未命中缓存）",
        ],
        "attribution_mistake_logged": (
            "曾据「只有 2 条 trial.log 出现 bake」宣布因果，实为 compose v5 默认用 bake、"
            "只有失败条会打完整 buildx 输出 —— 日志差异被误读成构建路径差异。相关≠因果。"
        ),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    for t, v in verdicts.items():
        print(f"  {'✅' if v['ok'] else '🔴'} {t}: {v['why']}")
    print("  ⇒ 可以开跑基线" if all_ok else "  ⇒ 🔴 别开跑，先查清")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
