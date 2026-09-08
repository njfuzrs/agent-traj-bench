#!/bin/bash
# T3 生成，勿手改。task=T0002
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
git checkout -- 'tests/agent/loop-detection.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/language-preference.test.ts' 2>/dev/null || true
git checkout -- 'tests/llm/capability-wiring-regression.test.ts' 2>/dev/null || true
git checkout -- 'tests/llm/effort.test.ts' 2>/dev/null || true
git checkout -- 'tests/llm/errors.test.ts' 2>/dev/null || true
git checkout -- 'tests/llm/fallback.test.ts' 2>/dev/null || true
git checkout -- 'tests/llm/strict-wire-contract-reconciliation.test.ts' 2>/dev/null || true
git checkout -- 'tests/permission/bash-security.test.ts' 2>/dev/null || true
git checkout -- 'tests/permission/checker.test.ts' 2>/dev/null || true
git checkout -- 'tests/query/hypothesis-gaps.test.ts' 2>/dev/null || true
git checkout -- 'tests/query/hypothesis-ledger.test.ts' 2>/dev/null || true
git checkout -- 'tests/skill/ci-self-heal.test.ts' 2>/dev/null || true
git checkout -- 'tests/skill/code-review.test.ts' 2>/dev/null || true
git checkout -- 'tests/telemetry/cache-telemetry-rotation.test.ts' 2>/dev/null || true
git checkout -- 'tests/telemetry/cost-attribution.test.ts' 2>/dev/null || true
git checkout -- 'tests/telemetry/hook-probe.test.ts' 2>/dev/null || true
git checkout -- 'tests/telemetry/no-real-path-writes.test.ts' 2>/dev/null || true
git checkout -- 'tests/telemetry/otlp-exporter.test.ts' 2>/dev/null || true
git checkout -- 'tests/telemetry/otlp-wiring.test.ts' 2>/dev/null || true
git checkout -- 'tests/telemetry/provider-health.test.ts' 2>/dev/null || true
git checkout -- 'tests/telemetry/telemetry.test.ts' 2>/dev/null || true
git checkout -- 'tests/telemetry/tracing-enhanced.test.ts' 2>/dev/null || true
git checkout -- 'tests/telemetry/usage-ledger.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/grep-type-alias.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/omission-detector.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/read-tool.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/web-fetch.test.ts' 2>/dev/null || true
git checkout -- 'tests/trace/collector.test.ts' 2>/dev/null || true
git checkout -- 'tests/ui/keybindings-full-coverage.test.ts' 2>/dev/null || true
git checkout -- 'tests/website/changelog-curated.test.ts' 2>/dev/null || true
rm -f 'tests/telemetry/config-undefined-defaults.test.ts'

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
bun test --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/telemetry/config-undefined-defaults.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/telemetry/otlp-exporter.test.ts' 'tests/telemetry/usage-ledger.test.ts' 'tests/telemetry/hook-probe.test.ts' 'tests/telemetry/cost-attribution.test.ts' 'tests/telemetry/telemetry.test.ts' 'tests/telemetry/cache-telemetry-rotation.test.ts' 'tests/telemetry/otlp-wiring.test.ts' 'tests/telemetry/tracing-enhanced.test.ts' 'tests/telemetry/provider-health.test.ts' 'tests/telemetry/no-real-path-writes.test.ts' 'tests/skill/code-review.test.ts' 'tests/llm/strict-wire-contract-reconciliation.test.ts' 'tests/permission/bash-security.test.ts' 'tests/trace/collector.test.ts' 'tests/config/language-preference.test.ts' 'tests/query/hypothesis-gaps.test.ts' 'tests/llm/errors.test.ts' 'tests/tool/omission-detector.test.ts' 'tests/llm/effort.test.ts' 'tests/ui/keybindings-full-coverage.test.ts' 'tests/permission/checker.test.ts' 'tests/tool/read-tool.test.ts' 'tests/agent/loop-detection.test.ts' 'tests/llm/capability-wiring-regression.test.ts' 'tests/llm/fallback.test.ts' 'tests/skill/ci-self-heal.test.ts' 'tests/query/hypothesis-ledger.test.ts' 'tests/tool/grep-type-alias.test.ts' 'tests/website/changelog-curated.test.ts' 'tests/tool/web-fetch.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
