#!/usr/bin/env python3
"""T7 前置 —— 网络策略改动后重跑 oracle 门禁（**$0**）。

## 为什么必须重跑

T5 的三道门禁是在 `NetworkMode.PUBLIC`（harbor 默认）下过的。
`t7-netpolicy.py` 把 39 条改成了 `allowlist`（只放宿主网关）⇒ **执行环境变了**。
旧门禁结论不再直接适用。

推理上不该有影响（`bun install` 在镜像构建期跑、test.sh 只跑本地 `bun test`），
但**推理不是证据**。oracle 零 LLM 依赖 ⇒ 重跑不花钱 ⇒ 没有任何理由
拿「大概不影响」代替一次实测。这条纪律就是 T5/T6 一路的教训。

## 判据（与 T5 完全同一套，刻意不另立标准）

  - **不看退出码**：harbor 失败时退出码仍是 0（TZ 四次失败全复现）。
  - 判据只有：`Trials` / `Exceptions` + 逐 task `reward`。
  - oracle 打了 gold patch ⇒ **每条都必须 reward=1**。
    任一条掉到 0 就说明网络策略动到了判分链路，**开跑前必须查清**。
  - reward 取 `result.json → verifier_result.rewards.reward`（`common.read_reward`），
    ⛔ 不是 `verifier_result.reward`（那个恒为 None，写错的形态是全体 0 分且不报错）。

## 两条 TZ 硬约束

  1. `-o` 必须在 `$HOME` 之下（R-3）——否则 verifier 产物写进 VM 自己的 /private/tmp，
     宿主读不到，形态是 `RewardFileNotFoundError`（指向「没写分」，是**错误方向**）。
  2. `HARBOR_TELEMETRY=0` 写进命令本身（R-2）。

## 一条本轮新踩的坑：stdin 必须给 /dev/null

harbor 构建 egress sidecar 时走 `docker compose build` → `docker buildx bake --file -`，
**bake 从 stdin 读 bake 文件**。若父进程的 stdin 是个已关闭/无输出的管道，
bake 会**永久阻塞在读 stdin**：形态是进程 %CPU=0、日志停在
"Building Docker image ..." 一行不动，**既不报错也不超时**（实测挂了 20 分钟）。
所以 `subprocess.run` 必须显式 `stdin=DEVNULL`。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402
import t5_gate_lib as lib  # noqa: E402

OUT = c.MVP_REPORTS / "t7-regate"
#: harbor 的 `-p` 收「装着一堆 task 目录的目录」，要只跑存活 39 条就得单独建一个。
#: 与 T5 同样用 symlink（T5 实测 harbor 认）。
STAGE = OUT / "survivors"


def survivors() -> list[str]:
    doc = json.loads((c.MVP_REPORTS / "t6-recheck/survivors.json").read_text(encoding="utf-8"))
    return sorted(doc["survivors"])


def stage(tasks: list[str]) -> Path:
    """把存活集 symlink 到一个干净目录。

    ⚠️ 每次都先清空：残留的旧 symlink 会让「跑了 39 条」变成「跑了 40 条」，
    而汇总表只报总数、不报名单 —— 这种错不会自己暴露。
    """
    if STAGE.exists():
        for p in STAGE.iterdir():
            p.unlink() if p.is_symlink() else None
    STAGE.mkdir(parents=True, exist_ok=True)
    for t in tasks:
        (STAGE / t).symlink_to((c.MVP_TASKS / t).resolve())
    got = sorted(p.name for p in STAGE.iterdir())
    if got != tasks:
        raise SystemExit(f"stage 目录与存活名单不一致：{len(got)} vs {len(tasks)}")
    return STAGE


def run(task_path: Path, out: Path) -> float:
    out.mkdir(parents=True, exist_ok=True)
    c.assert_jobs_dir_ok(out)          # R-3，别靠记性
    cmd = [
        "harbor", "run",
        "-p", str(task_path),
        "-a", "oracle",
        "-n", "1",                      # README ⑤：并发是最大单一失真源
        "-o", str(out),
        "--verifier-timeout-multiplier", "6",
        "-y",
    ]
    env = {**os.environ, "HARBOR_TELEMETRY": "0"}   # R-2
    t0 = time.time()
    with open(out / "run.log", "w", encoding="utf-8") as f:
        subprocess.run(
            cmd, stdout=f, stderr=subprocess.STDOUT, env=env, check=False,
            stdin=subprocess.DEVNULL,   # ⚠️ 见 docstring：不给会挂死在 buildx bake
        )
    return time.time() - t0


def main() -> int:
    tasks = survivors()
    print(f"重跑 oracle 门禁：{len(tasks)} 条（网络策略已改 allowlist）")
    path = stage(tasks)
    elapsed = run(path, OUT)
    print(f"  跑完，{elapsed / 60:.1f} 分钟")

    run_dir = lib.latest_run(OUT)
    if run_dir is None:
        raise SystemExit("没找到 run 目录 —— 看 run.log")
    rows = lib.collect_run(run_dir)

    got = {r.task for r in rows}
    missing = sorted(set(tasks) - got)
    red = sorted(r.task for r in rows if r.reward != 1.0)
    exc = sorted(r.task for r in rows if r.exception)
    dual_bad = sorted(r.task for r in rows if not r.dual_source_ok)

    print(f"  trial 行数 {len(rows)} / 应有 {len(tasks)}")
    print(f"  未出现在产物里: {missing or '无'}")
    print(f"  reward != 1: {red or '无'}")
    print(f"  抛异常: {exc or '无'}")
    print(f"  双源不一致: {dual_bad or '无'}")

    verdict = not (missing or red or exc or dual_bad)
    (OUT / "verdict.json").write_text(json.dumps({
        "purpose": "网络策略改为 allowlist 后重跑 oracle 门禁，确认判分链路未受影响",
        "network_mode": "allowlist + [192.168.5.2]",
        "n_tasks": len(tasks),
        "n_trials": len(rows),
        "all_oracle_pass": verdict,
        "missing": missing, "reward_not_1": red, "exceptions": exc, "dual_source_bad": dual_bad,
        "elapsed_min": round(elapsed / 60, 1),
        "cost_usd": 0,
        "cost_basis": "oracle 零 LLM 依赖（未声明 MODEL_CONNECTION、未 import litellm/anthropic/openai）",
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print("  ✅ 39/39 oracle 通过 —— 网络策略改动未影响判分链路" if verdict
          else "  🔴 有红项 —— 开跑前必须查清，别拿基线去撞")
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
