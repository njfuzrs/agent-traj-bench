#!/bin/bash
# T3 生成，勿手改。task=T0010
# 规则1：每条代码路径都必须写 reward —— 绝不能有「文件已存在就不写」的分支，
#        否则 agent 可以自己往 reward 文件里写个 1
# 规则2：先无条件覆盖为 0，跑完再按结果改写
mkdir -p /logs/verifier
echo 0 > /logs/verifier/reward.txt
printf '{"reward":0.0,"f2p":0.0,"p2p":0.0,"error":"test_sh_did_not_finish"}\n' \
  > /logs/verifier/reward.json

cd /repo

# ── 规则4：测试保护 ────────────────────────────────────────────────
# ⚠️ 按**路径逐个**还原，不按目录 —— 65 条 task 里有 4 条的测试文件不在 tests/ 下
# （src/ 3 个、packages/ 2 个），只还原 tests/ 会漏掉它们；
# 而 `git clean -fd src/` 会删掉 agent 新建的源码，即删掉它的解答本体。
# 名单由 T3 生成时字面写入。
git checkout -- 'tests/api/cache-detection.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/clear-resets-cache-state.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/patch-settings.test.ts' 2>/dev/null || true
git checkout -- 'tests/guard/test-isolation-guard.test.ts' 2>/dev/null || true
git checkout -- 'tests/migrations/backfill-team-defaults.test.ts' 2>/dev/null || true
git checkout -- 'tests/migrations/relocate-lossy-project-key.test.ts' 2>/dev/null || true
git checkout -- 'tests/migrations/runner-fs-failure.test.ts' 2>/dev/null || true
git checkout -- 'tests/telemetry/cache-telemetry-rotation.test.ts' 2>/dev/null || true
git checkout -- 'tests/trace/crash-marker.test.ts' 2>/dev/null || true
git checkout -- 'tests/trace/pid-manager.test.ts' 2>/dev/null || true
git checkout -- 'tests/api/cache-strategy.test.ts' 2>/dev/null || true
git checkout -- 'tests/api/cost-tracker.test.ts' 2>/dev/null || true
git checkout -- 'tests/api/error-utils.test.ts' 2>/dev/null || true
git checkout -- 'tests/api/errors.test.ts' 2>/dev/null || true
git checkout -- 'tests/api/rate-limit.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/custom.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/registry.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/config.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/language-preference.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/network-profile.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/rules-layered.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/rules.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/schema.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/settings.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/system-prompt-cache-key.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/system-prompt.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/token-utils.test.ts' 2>/dev/null || true
git checkout -- 'tests/edit-failure-tracker.test.ts' 2>/dev/null || true
git checkout -- 'tests/release-flow-contract.test.ts' 2>/dev/null || true
git checkout -- 'tests/telemetry/cost-attribution.test.ts' 2>/dev/null || true
git checkout -- 'tests/telemetry/hook-probe.test.ts' 2>/dev/null || true
git checkout -- 'tests/telemetry/telemetry.test.ts' 2>/dev/null || true
git checkout -- 'tests/telemetry/usage-ledger.test.ts' 2>/dev/null || true
git checkout -- 'tests/trace/builder.test.ts' 2>/dev/null || true
git checkout -- 'tests/trace/collector.test.ts' 2>/dev/null || true
git checkout -- 'tests/trace/digest.test.ts' 2>/dev/null || true
git checkout -- 'tests/trace/jit-digest.test.ts' 2>/dev/null || true
git checkout -- 'tests/trace/stream-observer.test.ts' 2>/dev/null || true
git checkout -- 'tests/trace/todo-digest.test.ts' 2>/dev/null || true
git checkout -- 'tests/trace/uploader.test.ts' 2>/dev/null || true
rm -f 'tests/preload-isolate-sid-home.ts'
rm -f 'tests/telemetry/no-real-path-writes.test.ts'

# ── 规则3：test_patch 在 verifier 阶段应用，不在 agent 阶段 ────────
# ⚠️ 先刷 index：tar 解包出来的文件全是 stat-dirty（实测 1215/1215），
#    而 --3way 要查 index，不刷必报 `does not match index`（见 solve_sh docstring）
git update-index -q --refresh || true
if ! git apply --3way /tests/test_patch.diff 2>>/logs/verifier/apply.log; then
  echo "TEST_PATCH_APPLY_FAILED" >> /logs/verifier/apply.log
  printf '{"reward":0.0,"f2p":0.0,"p2p":0.0,"error":"test_patch_apply_failed"}\n' \
    > /logs/verifier/reward.json
  echo 0 > /logs/verifier/reward.txt
  exit 0    # 注意：exit 0 —— 要 reward=0，不要 trial error（§4 T3）
fi

# ── 规则5+6：名单字面写入，走 --reporter=junit 结构化输出 ──────────
# ⚠️ 不许 grep 日志文本判分（R1 经典成因：格式一变就恒真/恒假且不报错）
# ⚠️ test_cmd 取自 base 时点的 package.json（§3.5），不同 base 可能不同
bun test --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/api/cache-detection.test.ts' 'tests/command/clear-resets-cache-state.test.ts' 'tests/config/patch-settings.test.ts' 'tests/guard/test-isolation-guard.test.ts' 'tests/migrations/backfill-team-defaults.test.ts' 'tests/migrations/relocate-lossy-project-key.test.ts' 'tests/migrations/runner-fs-failure.test.ts' 'tests/telemetry/cache-telemetry-rotation.test.ts' 'tests/telemetry/no-real-path-writes.test.ts' 'tests/trace/crash-marker.test.ts' 'tests/trace/pid-manager.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/trace/collector.test.ts' 'tests/config/language-preference.test.ts' 'tests/trace/builder.test.ts' 'tests/trace/digest.test.ts' 'tests/config/schema.test.ts' 'tests/config/system-prompt.test.ts' 'tests/api/errors.test.ts' 'tests/api/cache-strategy.test.ts' 'tests/config/system-prompt-cache-key.test.ts' 'tests/trace/uploader.test.ts' 'tests/command/custom.test.ts' 'tests/config/network-profile.test.ts' 'tests/config/settings.test.ts' 'tests/release-flow-contract.test.ts' 'tests/telemetry/usage-ledger.test.ts' 'tests/api/cost-tracker.test.ts' 'tests/api/error-utils.test.ts' 'tests/config/rules-layered.test.ts' 'tests/telemetry/hook-probe.test.ts' 'tests/config/rules.test.ts' 'tests/telemetry/cost-attribution.test.ts' 'tests/trace/jit-digest.test.ts' 'tests/api/rate-limit.test.ts' 'tests/edit-failure-tracker.test.ts' 'tests/trace/todo-digest.test.ts' 'tests/command/registry.test.ts' 'tests/config/config.test.ts' 'tests/telemetry/telemetry.test.ts' 'tests/trace/stream-observer.test.ts' 'tests/config/token-utils.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
