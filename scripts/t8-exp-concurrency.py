"""实验 E1：并发安全性 —— oracle 在 -n 6 下是否仍 39/39 全绿。

## 为什么这个实验能证伪「-n 1 是硬要求」

那条结论来自 Terminal-Bench，机制是 **verifier 现场从 GitHub 下载 uv（17–21MB）**，
并发一上去就抢同一条出口带宽 ⇒ verifier 成批坏掉。README 自己写了
「`-n 1` 不是判据，吞吐才是判据」。

我们这批的 verifier **零网络请求**（已逐条 grep 39 条 tests/*.sh：
无 curl/wget/pip/apt/npm），依赖在镜像构建期装好，运行期 allowlist 只放网关 IP。
所以那条结论的**前提在我们这批不存在**。

但「机制上不该受影响」是推理，不是证据 —— 这正是 T5/T6 一路强调要实测的地方。
oracle 打 gold patch ⇒ 每条必须 reward=1 ⇒ 任何一条掉 0 就是并发在破坏判分链路。
且 oracle 零 LLM 依赖 ⇒ **本实验 $0**。

## 判据（与 t7-regate 完全同一套，刻意不另立标准）

  - 不看退出码（harbor 失败时退出码仍是 0）
  - reward 取 `verifier_result.rewards.reward`，⛔ 不是 `verifier_result.reward`（恒 None）
  - 39/39 全 1 ⇒ 并发安全；任一条掉 0 或抛异常 ⇒ 并发不安全，退回 -n 1
"""
import json, os, subprocess, sys, time
from pathlib import Path
# ⚠️ 用 __file__ 自定位同目录，⛔ 不写死本机绝对路径（CI 门禁④ 会拦，且别人 clone 后路径不同）
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c
import t5_gate_lib as lib

N = int(sys.argv[1]) if len(sys.argv) > 1 else 6
OUT = c.MVP_REPORTS / f"t8-fix/exp-concurrency-n{N}"
STAGE = OUT / "survivors"

tasks = sorted(json.loads((c.MVP_REPORTS / "t6-recheck/survivors.json").read_text())["survivors"])
if STAGE.exists():
    for p in STAGE.iterdir():
        if p.is_symlink(): p.unlink()
STAGE.mkdir(parents=True, exist_ok=True)
for t in tasks:
    (STAGE / t).symlink_to((c.MVP_TASKS / t).resolve())

OUT.mkdir(parents=True, exist_ok=True)
c.assert_jobs_dir_ok(OUT)      # R-3：-o 必须在 $HOME 下
cmd = ["harbor", "run", "-p", str(STAGE), "-a", "oracle",
       "-n", str(N), "-o", str(OUT), "--verifier-timeout-multiplier", "6", "-y"]
print(f"实验 E1：oracle × {len(tasks)} 条 × -n {N}（$0）")
t0 = time.time()
with open(OUT / "run.log", "w", encoding="utf-8") as f:
    subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, check=False,
                   env={**os.environ, "HARBOR_TELEMETRY": "0"},
                   stdin=subprocess.DEVNULL)   # 不给会挂死在 buildx bake 读 stdin
el = time.time() - t0

run_dir = lib.latest_run(OUT)
rows = lib.collect_run(run_dir) if run_dir else []
bad = sorted(r.task for r in rows if r.reward != 1.0)
exc = sorted(r.task for r in rows if r.exception)
verdict = {
    "n_concurrent": N, "n_tasks": len(tasks), "n_trials": len(rows),
    "elapsed_min": round(el / 60, 1),
    "all_pass": len(rows) == len(tasks) and not bad and not exc,
    "reward_not_1": bad, "exceptions": exc,
    "missing": sorted(set(tasks) - {r.task for r in rows}),
    "cost_usd": 0, "cost_basis": "oracle 零 LLM 依赖",
}
(OUT / "verdict.json").write_text(json.dumps(verdict, ensure_ascii=False, indent=1))
print(json.dumps(verdict, ensure_ascii=False, indent=1))
