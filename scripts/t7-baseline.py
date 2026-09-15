#!/usr/bin/env python3
"""T7 — 基线评测：跑 sid-code + deepseek 的一条臂，落原始产物。

判定与报告在 `t7_report.py`（可单测、可纯复算）；本文件只负责**把批跑完**。
这与 T5 的 `t5-gate.py` / `t5_gate_lib.py` 分工同源。

## 配置（与 X2-Evaluation 08 号的 A1 臂完全对齐，只换题集）

| 项 | 值 | 出处 |
|---|---|---|
| agent | `sid_code_agent:SidCodeAgent` | harbor 侧现成的，不自研（方案 §4 T7） |
| 模型 | `openai/origin-deepseek-v4-1-flash` | 08 号 §4.11 的 A1 臂 |
| 网关 | `http://192.168.5.2:4101` | ⛔ 不是 host.docker.internal（colima 下解析不到） |
| 并发 | `-n 1` | README ⑤：并发是最大单一失真源 |
| k | 由 `--k` 给，默认 1 | 用户 2026-09-12 定：先 k=1 看结果再决定加不加 |
| 网络 | allowlist + 只放网关 IP | `t7-netpolicy.py` 已写进 39 条 task.toml |

## 🔴 开跑前六条闸（任一红就别跑，红着跑等于烧钱换废数）

参照 `run-model-switch.sh` 的跑前闸设计，但**只留与本批相关的**：

  1. **存活集 39 条**读 `survivors.json`（⛔ 不是 `gate.jsonl` 的 survives，
     那是 40 条、不含 T6 人工淘汰 → 会把 `T0005` 算进基线）。
  2. **网络策略已落地**：39 条都解析成 allowlist + 网关 IP。
     不校验的形态是「以为离线、实际联网」，而两侧都不报错。
  3. **shim 活着且上游是点名的那个模型**。`__stats` 的 `upstream_model`
     必须逐字等于 `--model`。08 号 §00 踩过「闸探 A 模型、真跑 B 模型」——
     三处各写死一遍，改一处漏两处，两侧都不报错。
  4. **shim 只认占位 token**：拿真 key 探会 401，拿 `no-auth-dummy` 探应 200。
     这一条同时验证**上游可达**（否则整批全 0 分，且长得像「模型能力差」）。
  5. **宿主 settings.json 里那个模型有 pricing**。缺了会顺网关采集缓存落到
     占位价 **75/75 USD/1M** ⇒ 成本**高报 355 倍**，而
     `cost_usd` 照样是个数、汇总照样出表、`pricing_ratio` 那条判据对
     换模型臂**刻意不判** ⇒ **没有任何一层会拦住它**（08 号 §00.3）。
  6. **pin 二进制存在且 ELF 架构与容器匹配**。目录名不含架构 ⇒ 同 commit 编两个
     架构会互相覆盖 ⇒ 「按 commit 匹配」可能拿到错架构的包，
     形态是容器里 `exit 127: not found`，**报错完全不指向架构**。
     容器是 aarch64 ⇒ 用 arm64 包。
     ⚠️ 08 号交接写的 sha256 `4e51bda52f9c` 是 **x64** 那个；
     本机 arm64 包是 `56203ccef6af`。照文档逐字核对会误判成「跑的不是同一个二进制」。

## 不作判据的东西

  - **退出码**：harbor 失败时退出码仍是 0（TZ 四次失败全复现）。
  - **汇总表的 Mean**：它把 f2p/p2p/error_code 混在一列（本批 reward.json 是多键），
    实测长得像「Reward 列有 8 行」。真判据是逐 trial 的 `verifier_result.rewards.reward`。

## 两条 TZ 硬约束 + 一条本轮新踩的

  1. `-o` 必须在 `$HOME` 之下（R-3）。
  2. `HARBOR_TELEMETRY=0` 写进命令本身（R-2）。
  3. `stdin=DEVNULL`：harbor 构建 egress sidecar 走 `buildx bake --file -`，
     从 stdin 读 bake 文件。stdin 是已关闭的管道时**永久阻塞**，
     形态是 %CPU=0、日志停在 "Building Docker image" 不动，**不报错不超时**
     （2026-09-12 实测挂了 20 分钟）。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

HARBOR_DIR = Path("~/Code/person/sid-code/evals/external-benchmarks/harbor").expanduser()

MODEL = os.environ.get("T7_MODEL", "origin-deepseek-v4-1-flash")
FAMILY = "openai"
GW_PORT = int(os.environ.get("T7_GW_PORT", "4101"))
#: 容器侧走 colima host-gateway。⛔ 不是 172.17.0.1（VM 内 docker bridge，
#: 宿主服务不在上面），⛔ 也不是 host.docker.internal（colima 下不解析）。
GW_HOST = "192.168.5.2"
#: 宿主侧探针用 127.0.0.1 —— 同一个 shim，两个视角。
GW_LOCAL = f"http://127.0.0.1:{GW_PORT}"
PLACEHOLDER_TOKEN = "no-auth-dummy"   # 与 gateway.py:71 / sid_code_agent 逐字一致

OUT = c.MVP_REPORTS / "baseline"
STAGE = OUT / "survivors"


def survivors() -> list[str]:
    doc = json.loads((c.MVP_REPORTS / "t6-recheck/survivors.json").read_text(encoding="utf-8"))
    got = sorted(doc["survivors"])
    if len(got) != doc["survivors_n"]:
        raise SystemExit("survivors.json 自相矛盾")
    return got


def _get(url: str, *, data: bytes | None = None, headers: dict | None = None, timeout: int = 60):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:                      # 连不上也要返回，不抛 —— 闸自己判红
        return None, str(e)


def preflight(tasks: list[str]) -> list[str]:
    """六条闸。返回红项列表（空 = 全绿）。**每条都实测，不读文档、不靠记性。**"""
    red: list[str] = []

    # 闸 1：存活集
    if len(tasks) != 39:
        red.append(f"闸1 存活集应 39 条，得到 {len(tasks)}")
    print(f"  闸1 存活集 {len(tasks)} 条 —— 读 survivors.json（不是 gate.jsonl）")

    # 闸 2：网络策略真的被 harbor 解析成 allowlist
    import tomllib

    from harbor.models.task.config import NetworkMode, TaskConfig  # noqa: PLC0415

    bad = []
    for t in tasks:
        cfg = TaskConfig.model_validate(tomllib.loads((c.MVP_TASKS / t / "task.toml").read_text()))
        p = cfg.environment.resolve_baseline()
        if p.network_mode != NetworkMode.ALLOWLIST or p.allowed_hosts != [GW_HOST]:
            bad.append(t)
    if bad:
        red.append(f"闸2 网络策略未落地：{bad[:5]}（共 {len(bad)} 条）")
    print(f"  闸2 网络策略 {len(tasks) - len(bad)}/{len(tasks)} 条 = allowlist + [{GW_HOST}]")

    # 闸 3：shim 活着，且上游逐字等于点名的模型
    code, body = _get(f"{GW_LOCAL}/__stats", timeout=15)
    upstream = None
    if code == 200:
        try:
            upstream = json.loads(body).get("upstream_model")
        except Exception:
            pass
    if upstream != MODEL:
        red.append(f"闸3 shim 上游是 {upstream!r}，点名的是 {MODEL!r} —— 起 shim 时 --model-name 给错，或端口指到了别的族")
    print(f"  闸3 shim {GW_LOCAL} 上游 = {upstream!r}")

    # 闸 4：占位 token 能通到上游（顺带证明上游可达）
    code, body = _get(
        f"{GW_LOCAL}/v1/chat/completions",
        data=json.dumps({"model": MODEL, "messages": [{"role": "user", "content": "ping"}],
                         "max_tokens": 4}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {PLACEHOLDER_TOKEN}"},
        timeout=90,
    )
    if code != 200:
        red.append(f"闸4 占位 token 探针 http={code} —— 上游不可达或 shim 配错。红着跑会整批 0 分，且长得像「模型能力差」")
    print(f"  闸4 占位 token 探针 http={code}")

    # 闸 5：pricing（不补 = 成本高报 355 倍，且无一层会拦）
    st = json.loads(Path("~/.sid-code/settings.json").expanduser().read_text(encoding="utf-8"))
    entry = next((m for m in st.get("availableModels", []) if m.get("name") == MODEL), None)
    pricing = (entry or {}).get("pricing")
    if not isinstance(pricing, dict) or not pricing:
        red.append(f"闸5 宿主 settings.json 里 {MODEL} 没有 pricing —— 会落到网关占位价 75/75，成本高报 355 倍")
    else:
        print(f"  闸5 pricing 已配：in={pricing.get('input')} out={pricing.get('output')} "
              f"{pricing.get('currency')} asOf={pricing.get('asOf')}")

    # 闸 6：pin 二进制 + ELF 架构与容器匹配
    arch = subprocess.run(["docker", "run", "--rm", "oven/bun:1.3.14", "uname", "-m"],
                          capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout.strip()
    want = "arm64" if arch in ("aarch64", "arm64") else "x64"
    binp = Path(f"~/.local/share/sid-harbor-gateway/bins/sid-code-{want}-30586ff003c9").expanduser()
    if not binp.is_file():
        red.append(f"闸6 pin 二进制不存在：{binp}")
    else:
        # 读 ELF 字节判架构（目录名与期望值都不是判据 —— 见 sid_code_agent 的教训）
        head = binp.open("rb").read(20)
        machine = int.from_bytes(head[18:20], "little")
        got = {0xB7: "arm64", 0x3E: "x64"}.get(machine, f"0x{machine:x}")
        if got != want:
            red.append(f"闸6 二进制 ELF 架构 {got}，容器是 {arch}（需要 {want}）")
        sha = subprocess.run(["shasum", "-a", "256", str(binp)], capture_output=True, text=True).stdout[:16]
        print(f"  闸6 容器 {arch} → 用 {want} 包，ELF={got}，sha256={sha}")
    return red


def stage(tasks: list[str]) -> Path:
    if STAGE.exists():
        for p in STAGE.iterdir():
            p.unlink() if p.is_symlink() else None
    STAGE.mkdir(parents=True, exist_ok=True)
    for t in tasks:
        (STAGE / t).symlink_to((c.MVP_TASKS / t).resolve())
    got = sorted(p.name for p in STAGE.iterdir())
    if got != tasks:
        raise SystemExit(f"stage 与名单不一致：{len(got)} vs {len(tasks)}")
    return STAGE


def run(task_path: Path, out: Path, k: int) -> float:
    out.mkdir(parents=True, exist_ok=True)
    c.assert_jobs_dir_ok(out)                       # R-3
    cmd = [
        "harbor", "run",
        "-p", str(task_path),
        "-a", "sid_code_agent:SidCodeAgent",
        "-m", f"{FAMILY}/{MODEL}",
        "-n", "1",                                   # README ⑤
        "-k", str(k),
        "-o", str(out),
        "--verifier-timeout-multiplier", "6",
        "-y",
    ]
    env = {
        **os.environ,
        "HARBOR_TELEMETRY": "0",                     # R-2
        "PYTHONPATH": str(HARBOR_DIR),               # agent 从 harbor 侧 import
        "SID_HARBOR_GATEWAY_URL": f"http://{GW_HOST}:{GW_PORT}",
        "SID_HARBOR_PROVIDER": FAMILY,               # 显式写，别只靠 -m 前缀解析
        "SID_HARBOR_BINARY_ARM64": str(Path("~/.local/share/sid-harbor-gateway/bins/sid-code-arm64-30586ff003c9").expanduser()),
        "SID_HARBOR_BINARY_X64": str(Path("~/.local/share/sid-harbor-gateway/bins/sid-code-x64-30586ff003c9").expanduser()),
        "no_proxy": "127.0.0.1,localhost",
        "NO_PROXY": "127.0.0.1,localhost",
    }
    t0 = time.time()
    with open(out / "run.log", "w", encoding="utf-8") as f:
        subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env=env,
                       check=False, stdin=subprocess.DEVNULL)   # stdin 见 docstring
    return time.time() - t0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=1, help="每题跑几次（默认 1）")
    ap.add_argument("--dry-run", action="store_true", help="只过闸，不跑（$0）")
    args = ap.parse_args()

    tasks = survivors()
    print(f"T7 基线：{len(tasks)} 条 × k={args.k}，模型 {FAMILY}/{MODEL}")
    print("跑前闸：")
    red = preflight(tasks)
    if red:
        print("\n🔴 闸没全绿，不开跑：")
        for r in red:
            print(f"   - {r}")
        return 1
    print("  ✅ 六条闸全绿")

    if args.dry_run:
        print("--dry-run：到此为止，$0")
        return 0

    path = stage(tasks)
    elapsed = run(path, OUT, args.k)
    print(f"跑完，{elapsed / 60:.1f} 分钟。产物 {OUT}")
    print("下一步：scripts/t7-report.py 出报告（判定与统计都在那边）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
