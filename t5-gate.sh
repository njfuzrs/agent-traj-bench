#!/usr/bin/env bash
#
# T5 — oracle/nop 双向门禁【T0 阶段：骨架，未启用】
#
# 出处：docs-research/trajectory-platform/bench-mvp-plan.md v1.2 §4 T5（0.5 天）
#
# ⚠️ 这是 T0 产出的骨架，直接以非零码退出。T5 开工时删掉 NOT_IMPLEMENTED 那段即可 ——
#    下面的 harbor 命令已按实测修正过参数名（见「方案原文的三处参数名过期」）。
#
# ## 三道门禁（§4 T5 判据表）
#
#   | 门禁      | agent  | 期望            | 不符合说明什么                    |
#   |-----------|--------|-----------------|-----------------------------------|
#   | ① 可解性  | oracle | reward = 1      | gold patch 打不上、或测试本身坏了 |
#   | ② 有效性  | nop    | f2p = 0 且 p2p = 1 | 🔴 f2p=1 是假 task；p2p=0 是坏环境 |
#   | ③ 稳定性  | oracle -k 3 | 三次一致    | 测试有随机性或依赖外部状态        |
#
# 🔴 **门禁②看 f2p 分量，不是总 reward**（v1.2 修正）。nop 什么都不改，P2P 本该全绿、
#    F2P 本该全红；总 reward 是两者的与，等于 0 **无法区分**「F2P 正确失败」与
#    「P2P 意外失败」。后者是快照缺文件/依赖装不上/P2P 采到被剔除的测试 ——
#    是基础设施问题，**不要去动 task**。
#
# ## 方案原文的三处参数名过期（harbor 0.22.0 实测）
#
#   | 方案原文（§4 T5 代码块）        | 实际可用                                  |
#   |---------------------------------|-------------------------------------------|
#   | `--task-path <d>`（可重复）     | **不存在**。用 `-p <dir>`，它接受「装着一堆 task 目录的目录」 |
#   | `--agent oracle`                | 可用；短写 `-a oracle`                    |
#   | `-k 3` 表示「连跑 3 次」        | 语义对上了：`-k/--n-attempts`             |
#
# ## TZ 实测的两条硬约束（reports/tz-preflight.md）
#
#   1. **`-o` 必须落在 $HOME 之下**（R-3）。本机 colima `mounts: []`，VM 内只挂了
#      $HOME 一个 virtiofs，宿主 /tmp 不在 VM 里 —— 用 /tmp 的形态是
#      `RewardFileNotFoundError`，而它指向「reward 没写」这个**错误方向**。
#   2. **`HARBOR_TELEMETRY=0` 写进命令本身**（R-2）。遥测默认开（发往 PostHog），
#      我们的 instruction.md 含私有仓库信息。写进「注意事项」里没人看。
#
# ## 另外两条（harbor README，实测复现过）
#
#   - **`-n 1` 是硬要求**，不是保守。README ⑤ 实测 `-n` 并发在慢网络下直接决定
#     verifier 坏掉的比例，是它记录的「最大的单一失真源，而且伪装成能力差」。
#   - **不能看退出码**。`harbor run` 失败时退出码仍是 0（TZ 期间四次失败运行全部复现），
#     判据只有 `Trials` / `Exceptions` 两个数，以及 result.json 里的 reward。
#
# ## reward 双源核对（§3.8-D，TZ 已实测确认）
#
#     源 A: result.json → verifier_result.rewards.reward   ← 正确路径（嵌套 dict）
#     源 B: verifier/reward.txt                            ← verifier 自己写的
#     ⚠️ verifier_result.reward 恒为 None —— 写错它的形态是「所有 task 都 0 分」**且不报错**
#   用 scripts/mvp/common.py 的 read_reward() 读，别自己拼路径。
#
# ## 四条反向自证（§4 T5，v1.2 增到四条，都要做）
#
#   1. 某条 task 的 tests/test.sh 改成无条件 `echo 1` → 门禁② 必须报红
#   2. 某条 task 的 solution/solve.sh 改成空      → 门禁① 必须报红
#   3. test_patch 改成故意冲突 → reward=0 且 rewards.json 带
#      error: test_patch_apply_failed，**且 trial 状态不是 error**
#   4. tests/ 下预置一个与 test_patch 同名的文件（模拟 agent 改测试）
#      → git checkout + git clean 应清掉它，门禁① 仍为 1
#
# ## 已知坑
#
#   - 用 harbor 侧已有的 verifier_health.py 分辨「真 0 分」与「假 0 分」，
#     它的 agent_started / llm_fatal 判据正是为此写的，**别自己重写**
#   - 报 `Error getting dataset` 先复跑一次，不要去查数据集名字（README ④：网络，
#     7% 概率且无重试）。本方案走本地 -p 模式理论上不撞，撞上说明配置退化了
set -euo pipefail

echo "T5 尚未实现 —— T0 只交付骨架。实现契约见本文件注释与方案 §4 T5。" >&2
exit 64

# shellcheck disable=SC2317  # 以下为 T5 开工时启用的骨架
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TASKS="$ROOT/bench/v0.2-mini/tasks"
OUT="$ROOT/bench/v0.2-mini/reports/t5-gate"   # 在 $HOME 下 ✅（见 TZ R-3）

# 门禁① oracle：参考解必须全绿（reward == 1）
HARBOR_TELEMETRY=0 harbor run -p "$TASKS" -a oracle -n 1 \
  -o "$OUT/oracle" --verifier-timeout-multiplier 6 -y

# 门禁② nop：什么都不做 → f2p 必须全为 0，且 p2p 必须全为 1
#          ← 这是整个方案最重要的一道门禁
HARBOR_TELEMETRY=0 harbor run -p "$TASKS" -a nop -n 1 \
  -o "$OUT/nop" --verifier-timeout-multiplier 6 -y

# 门禁③ 一致性：oracle 连跑 3 次，三次结果必须相同
HARBOR_TELEMETRY=0 harbor run -p "$TASKS" -a oracle -k 3 -n 1 \
  -o "$OUT/oracle-k3" --verifier-timeout-multiplier 6 -y
