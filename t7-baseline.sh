#!/usr/bin/env bash
#
# T7 — 基线评测 + 成果报告【T0 阶段：骨架，未启用】
#
# 出处：docs-research/trajectory-platform/bench-mvp-plan.md v1.2 §4 T7（1.5 天）
#
# ⚠️ 这是 T0 产出的骨架，直接以非零码退出。
#
# 输入：通过 T6 人工过目的存活 task
# 输出：reports/baseline-v0.2-mini.md（六节齐全）+ version.json（冻结）
#
# ## 做法：复用 harbor 侧已有的多模型脚本，不自己写 harness
#
# harbor 底座已跑过 59 个 run，run-model-switch.sh / run-claude-code-contrast.sh
# 这类多模型编排脚本都在 sid-code/evals/external-benchmarks/harbor/ 下。
# ⚠️ **纪律 4：不改 harbor 底座里的任何文件**（§4 T0）——
#    registry.local.json 是已发表结论的取数源，动它等于让旧结论不可复算。
#    我们只**调用**，产物全部落 trajectory-platform 侧。
#
# ## 同样的两条 TZ 硬约束（reports/tz-preflight.md）
#
#   1. `-o` 必须在 $HOME 之下（R-3），否则 RewardFileNotFoundError
#   2. HARBOR_TELEMETRY=0 写进命令本身（R-2）
#
# ## 健康度三条判据（§7.2 检查点 F）
#
# 跑完先用 harbor 侧的 verifier_health.py 过一遍，分辨「真 0 分」与「假 0 分」。
# TZ 期间实测过一次「假 0 分」的真实形态（R-4）：oracle 拿 0 分，但
# Exceptions=0，读 verifier/test-stdout.txt 才看到是 github.com 间歇性不可达
# 导致 uv 装不上。**Exceptions=0 但 reward=0 时，第一件事是读 test-stdout.txt，
# 不要先怀疑 task 质量。**
#
# ## -n 1 与退出码
#
#   - `-n 1` 是硬要求（README ⑤：并发是最大的单一失真源，且伪装成能力差）
#   - `harbor run` 失败时退出码仍是 0，判据只有 Trials / Exceptions 与 reward
set -euo pipefail

echo "T7 尚未实现 —— T0 只交付骨架。实现契约见本文件注释与方案 §4 T7。" >&2
exit 64
