#!/usr/bin/env python3
"""T7 前置 —— 给存活 39 条补上 `[environment].network_mode`。

## 为什么必须补：题面 39/39 在对模型撒谎

每条 `instruction.md` 都写着「容器**离线运行**（`--network none`），依赖已装好，
不要尝试联网安装」，而 **39 条 `task.toml` 一个都没写 `network_mode`**，
harbor 的默认是 `NetworkMode.PUBLIC`（`models/task/config.py:69`）。

2026-09-12 实测（容器内 curl）：`github.com` → 200、`registry.npmjs.org` → 200。
所以此前 T5/T6 的门禁、以及不补就开跑的基线，**都是在联网容器里跑的**。

后果不是「跑不起来」而是三条各自独立的失真：
  ① 题面承诺与执行环境不一致 —— 对外发布基线时这条会被直接质疑；
  ② `github.com/njfuzrs/sid-code` 是**公开仓库**（实测 `private=false`），
     base_commit 可见 ⇒ 存在「联网抄答案」这条路径；
  ③ 联网带来的间歇失败（TZ 的 R-4 就是 uv 装不上导致的**假 0 分**）会混进分数。

⚠️ ②的实际泄漏面比看着小，已量化（2026-09-12）：公开树里**没有 `src/` 也没有
`docs/`**，39 条 gold_patch 涉及的 530 个文件路径只有 4 个命中公开侧，
35 条题面点名的 `docs/` 路径公开侧**一个都不存在**。真正可抄的只有 `T0010`
的 `bunfig.toml`（3 行）。**但「泄漏面小」不是「可以联网」的理由** —— ①③ 与它无关。

## 为什么是 allowlist 而不是 no-network

`no-network` 更贴题面字面，但 sid-code **必须**连宿主网关 shim
（`http://192.168.5.2:4101`）才能调模型 —— 断网等于整条臂跑不起来。
所以取 `allowlist` 且**只放网关这一个 IP**：对被测模型而言 github / npm 全不可达，
与题面承诺的效果一致；差别只在多了一个它必须用的模型出口。

⚠️ 这个差别**必须写进 dataset card 与基线报告**，不能含糊成「已按题面离线运行」。

两种模式都在 2026-09-12 用**免费的 `nop`** 实测跑通（各 1 条，Trials=1 /
Exceptions=0 / f2p=0 / p2p=1，与 nop 预期逐字一致）。

## 🔴 补完必须重跑 oracle 门禁（$0）

T5 的三道门禁是在 **PUBLIC** 下过的。改了网络策略就等于换了执行环境，
旧门禁结论**不再直接适用**。oracle 零 LLM 依赖 ⇒ 重跑不花钱，
所以没有任何理由用「大概不影响」代替实测。

（判断上 `bun install` 在**镜像构建期**跑，不受运行期策略约束；
test.sh 只跑本地 `bun test`。但这是推理，不是证据 —— 证据由重跑给。）

## 踩过的两个环境坑（都不在方案里）

1. **`docker buildx` 没装**：`allowlist` / `no-network` 都会触发 harbor 构建
   egress-control sidecar，走的是 `docker buildx build`。本机只有 compose 插件 ⇒
   `RuntimeError: ... exit code 125, output: unknown flag: --file`。
   报错完全不指向「缺 buildx」。已装 v0.37.1 到 `~/.docker/cli-plugins/`。
2. **sidecar 基础镜像要联网拉**：`gogost/gost:3.2.7-nightly...` 首次拉会
   TLS handshake timeout。已 `docker pull` 预热。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

#: 宿主网关 shim 的地址。⚠️ 与 `run-model-switch.sh:87` 的
#: `SID_HARBOR_GATEWAY_URL` 同源 —— 那边写死 `192.168.5.2`（colima 的宿主 IP）。
#: ⛔ 不能写 `host.docker.internal`：那是 Docker Desktop 的特性，
#: 本机 colima 下**解析不到**（2026-09-12 实测 `getent hosts` 无输出），
#: 而 sid_code_agent.py 的 DEFAULT_GATEWAY_URL 恰好用的就是它。
GATEWAY_HOST = "192.168.5.2"

SURVIVORS = c.MVP_REPORTS / "t6-recheck/survivors.json"

#: 要插入的两行。写在 `[environment]` 段首 —— 该段已存在（T3 生成时就有
#: `build_timeout_sec`），所以不必新建段。
POLICY_LINES = f'network_mode = "allowlist"\nallowed_hosts = ["{GATEWAY_HOST}"]\n'


def survivors() -> list[str]:
    """存活名单。⚠️ 只读 survivors.json，**不读 `meta/gate.jsonl` 的 survives`**
    —— 后者是 T5 三道门禁的结论（40 条），不含 T6 的人工淘汰，
    照它取会把 `T0005` 算进基线（T6→T7 交接第 1b 条）。"""
    doc = json.loads(SURVIVORS.read_text(encoding="utf-8"))
    got = doc["survivors"]
    if len(got) != doc["survivors_n"]:
        raise SystemExit(f"survivors.json 自相矛盾：列表 {len(got)} 条 vs survivors_n {doc['survivors_n']}")
    return sorted(got)


def patch(task_id: str) -> str:
    """给一条 task.toml 补网络策略。返回 'patched' / 'already' / 报错。

    **幂等**：已经有 network_mode 就不动。重复跑不会插两遍 ——
    插两遍的形态是 toml 里同键重复，pydantic 那边会报错，但要等到开跑才暴露。
    """
    p = c.MVP_TASKS / task_id / "task.toml"
    text = p.read_text(encoding="utf-8")
    if "network_mode" in text:
        return "already"
    if "[environment]\n" not in text:
        raise SystemExit(f"{task_id}: task.toml 里没有 [environment] 段，形态与 T3 生成的不一致，人工看一眼")
    p.write_text(text.replace("[environment]\n", f"[environment]\n{POLICY_LINES}", 1), encoding="utf-8")
    return "patched"


def verify(task_id: str) -> None:
    """用 harbor 自己的 pydantic 模型回读，确认策略真的生效。

    ⚠️ 不能只 grep 文件里有没有那两行 —— 那只证明**写进去了**，
    不证明 harbor **解析成**那个策略。TZ/T5 一路的教训都是同一形态：
    「写对了」与「被读成对的」是两件事。这里直接调 harbor 的
    `resolve_baseline()`，与开跑时同一条代码路径。
    """
    import tomllib

    # ⚠️ 必须用 harbor 自己那个 venv 的解释器跑本脚本：
    #   ~/.local/share/uv/tools/harbor/bin/python scripts/t7-netpolicy.py
    # harbor 是 uv tool 装的，不在本仓依赖里 ⇒ 本地静态检查会报
    # reportMissingImports，那是**预期**的，不是缺依赖。
    from harbor.models.task.config import NetworkMode, TaskConfig  # noqa: PLC0415

    cfg = TaskConfig.model_validate(tomllib.loads((c.MVP_TASKS / task_id / "task.toml").read_text()))
    got = cfg.environment.resolve_baseline()
    if got.network_mode != NetworkMode.ALLOWLIST or got.allowed_hosts != [GATEWAY_HOST]:
        raise SystemExit(f"{task_id}: harbor 解析出的策略不对 —— {got}")


def main() -> int:
    tasks = survivors()
    print(f"存活 {len(tasks)} 条（读 {SURVIVORS.relative_to(c.REPO_ROOT)}）")

    stats = {"patched": 0, "already": 0}
    for t in tasks:
        stats[patch(t)] += 1
    print(f"  补策略：新写 {stats['patched']} 条，已有 {stats['already']} 条（幂等）")

    # 回读校验：用 harbor 的模型，不是 grep
    for t in tasks:
        verify(t)
    print(f"  ✅ 回读校验 {len(tasks)}/{len(tasks)} 条：harbor 解析为 allowlist + [{GATEWAY_HOST}]")

    # ⚠️ 未存活的 26 条**刻意不动**：它们不进交付集，改了反而让
    # 「哪些是交付物」这件事变模糊。
    others = sorted(p.name for p in c.MVP_TASKS.iterdir() if p.is_dir() and p.name not in set(tasks))
    print(f"  未存活 {len(others)} 条刻意不动（不进交付集）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
