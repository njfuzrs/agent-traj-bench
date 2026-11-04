#!/bin/bash
# T3 生成，勿手改。task=T0024
# 规则1：每条代码路径都必须写 reward —— 绝不能有「文件已存在就不写」的分支，
#        否则 agent 可以自己往 reward 文件里写个 1
# 规则2：先无条件覆盖为 0，跑完再按结果改写
mkdir -p /logs/verifier
echo 0 > /logs/verifier/reward.txt
# ⚠️ reward.json **只能放标量**（T5 实测）：harbor 的 rewards 是
#    dict[str, float | int]，放字符串会让整条 trial 判 ValidationError ——
#    比 reward=0 更糟，因为它进的是 Exceptions 而不是「没解出来」。
#    所以错误用数值编码：1=test.sh 没跑完，2=test_patch 打不上，
#    3/4/5 见 score.py 的 ERROR_CODES。
printf '{"reward":0.0,"f2p":0.0,"p2p":0.0,"error_code":1}\n' \
  > /logs/verifier/reward.json

cd /repo

# ── 规则4：测试保护 ────────────────────────────────────────────────
# ⚠️ 按**路径逐个**还原，不按目录 —— 65 条 task 里有 4 条的测试文件不在 tests/ 下
# （src/ 3 个、packages/ 2 个），只还原 tests/ 会漏掉它们；
# 而 `git clean -fd src/` 会删掉 agent 新建的源码，即删掉它的解答本体。
# 名单由 T3 生成时字面写入。
# 🔴 按 base blob 还原（T02）：git checkout -- 会还原出 agent 自己 commit 进去的版本
restore_pinned() {
  mkdir -p "$(dirname "$1")"
  if ! git cat-file blob "$2" > "$1" 2>/dev/null; then
    echo "PROTECTED_BLOB_MISSING $1 $2" >> /logs/verifier/apply.log
    # error_code=6 = 被保护文件的 base blob 取不到（对象库被动过）
    printf '{"reward":0.0,"f2p":0.0,"p2p":0.0,"error_code":6}\n' > /logs/verifier/reward.json
    echo 0 > /logs/verifier/reward.txt
    exit 0
  fi
}
restore_pinned 'tests/llm/availability.test.ts' '7aa5b2c8597fe62b498151f1d89f4c4080e53dd2'
restore_pinned 'tests/llm/capabilities.test.ts' 'd89e24b2f45f2726de13db4289acecd5155581af'
restore_pinned 'tests/llm/capability-wiring-regression.test.ts' '1aa36b1104296ceb09a536501435e6b757e6750d'
restore_pinned 'tests/llm/effort.test.ts' 'c4805598d4b8eaa56adea6b6d4d6b7ee8eac63a4'
restore_pinned 'tests/llm/error-messages.test.ts' '8787a9f15f21c544b471f28f2d573edd12c75543'
restore_pinned 'tests/llm/errors.test.ts' '78adffa364f15aeb964a149095a43f1d03876377'
restore_pinned 'tests/llm/fallback.test.ts' '1a5464ae4a641bbc14666357169c6c3f16517c91'
restore_pinned 'tests/llm/gateway-pricing.test.ts' '4ff468f6a35c37ad207a36fa850b746f42005673'
restore_pinned 'tests/llm/mock-provider.test.ts' '8c330d0ea7bff82146fe7ede2f578b322d1ab877'
restore_pinned 'tests/llm/model-capabilities.test.ts' '7720340cd586164c15aa3af3a1f1390ccaf924a5'
restore_pinned 'tests/llm/openai-protocol-edge.test.ts' '05743bd6ea2381ba221fd8d60711305e1fe7c302'
restore_pinned 'tests/llm/openai.test.ts' '7a2a881ae1f37cb3ac6e78444abb5748ee06f055'
restore_pinned 'tests/llm/provider-anthropic-conformance.test.ts' 'da17ad81e6cb0a3554e38e65f7caffb12f0de833'
restore_pinned 'tests/llm/provider-conformance.test.ts' 'b835f4412e35385b7d38778c3ea288773b9762ad'
restore_pinned 'tests/llm/quota.test.ts' '2997a739aa369422ac9f04b4b183dfda98390c0a'
restore_pinned 'tests/llm/registry.test.ts' 'fb17fc9d0e25b11d31e12f97d7079e93b91dae90'
restore_pinned 'tests/llm/resilience-b5-gates.test.ts' '55189b19186b9f06b73042313840393b46b386eb'
restore_pinned 'tests/llm/resilience-b6-gates.test.ts' '126d957d5e161eef6493e18cc3cf78af62b62a74'
restore_pinned 'tests/llm/secret-redact.test.ts' '048fa05523661cd9f799392f7ec4d2666237c2bf'
restore_pinned 'tests/llm/sse-event-line-shim.test.ts' '084f23bc5fb043b6a65b25359f4355227295cdbc'
restore_pinned 'tests/llm/strict-model-gate-sentinel.test.ts' '151f20c65d7bc4451ba4f4d96d6b8427201ae934'
restore_pinned 'tests/llm/strict-wire-contract-reconciliation.test.ts' '44a0f10d30006c2f5deeda0ae7a9b3c43b8eacf5'
restore_pinned 'tests/llm/subagent-model-tier.test.ts' '5817dc9ad1f6c96702ccb0affb643bfa3a254772'
restore_pinned 'tests/llm/token-estimator.test.ts' '8042f50270bfb794f3b1787ad21442d6127d0236'
restore_pinned 'tests/llm/wire-model-consumer-gaps.test.ts' '18c5cc7ddd073b28164f8f35a2478bf03316b7b4'
restore_pinned 'tests/llm/wire-model.test.ts' 'a730676a96d80a0b5f07afbf686054ecd15dcc4f'
restore_pinned 'tests/preload-isolate-sid-home.ts' '541abfc175dc7e4804aefa3714fb889d87a60226'
restore_pinned 'tests/telemetry/cost-attribution.test.ts' '91e9c418ce674f3d44532bff03e371ca46fce9bb'
restore_pinned 'tests/telemetry/hook-probe.test.ts' '1db88e26a59cccf6d4ab3b5423fb3fdc52f518e0'
restore_pinned 'tests/telemetry/otlp-exporter.test.ts' 'bc521f1ab89aa5e77b11a9db3eb681cd22c0eaf9'
restore_pinned 'tests/telemetry/usage-ledger.test.ts' '552f5031b21dafc76989a8df070cd84773ef428b'
rm -f 'tests/llm/replay-provider.test.ts'
rm -f 'tests/telemetry/content-tracing-wiring.test.ts'
rm -f 'tests/telemetry/content-tracing.test.ts'

# ── 规则3：test_patch 在 verifier 阶段应用，不在 agent 阶段 ────────
# ⚠️ 先刷 index：tar 解包出来的文件全是 stat-dirty（实测 1215/1215），
#    而 --3way 要查 index，不刷必报 `does not match index`（见 solve_sh docstring）
git update-index -q --refresh || true
if ! git apply --3way /tests/test_patch.diff 2>>/logs/verifier/apply.log; then
  echo "TEST_PATCH_APPLY_FAILED" >> /logs/verifier/apply.log
  # error_code=2 = test_patch 打不上（同上：只能放标量）
  printf '{"reward":0.0,"f2p":0.0,"p2p":0.0,"error_code":2}\n' \
    > /logs/verifier/reward.json
  echo 0 > /logs/verifier/reward.txt
  exit 0    # 注意：exit 0 —— 要 reward=0，不要 trial error（§4 T3）
fi

# ── 规则5+6：名单字面写入，走 --reporter=junit 结构化输出 ──────────
# ⚠️ 不许 grep 日志文本判分（R1 经典成因：格式一变就恒真/恒假且不报错）
# ⚠️ test_cmd 取自 base 时点的 package.json（§3.5），不同 base 可能不同
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/llm/replay-provider.test.ts' 'tests/telemetry/content-tracing-wiring.test.ts' 'tests/telemetry/content-tracing.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/llm/strict-wire-contract-reconciliation.test.ts' 'tests/llm/errors.test.ts' 'tests/llm/effort.test.ts' 'tests/llm/capability-wiring-regression.test.ts' 'tests/llm/fallback.test.ts' 'tests/llm/model-capabilities.test.ts' 'tests/llm/openai-protocol-edge.test.ts' 'tests/llm/resilience-b5-gates.test.ts' 'tests/llm/strict-model-gate-sentinel.test.ts' 'tests/llm/gateway-pricing.test.ts' 'tests/llm/mock-provider.test.ts' 'tests/llm/capabilities.test.ts' 'tests/llm/token-estimator.test.ts' 'tests/telemetry/otlp-exporter.test.ts' 'tests/llm/registry.test.ts' 'tests/llm/provider-conformance.test.ts' 'tests/llm/secret-redact.test.ts' 'tests/llm/resilience-b6-gates.test.ts' 'tests/llm/provider-anthropic-conformance.test.ts' 'tests/llm/quota.test.ts' 'tests/telemetry/usage-ledger.test.ts' 'tests/telemetry/hook-probe.test.ts' 'tests/llm/wire-model-consumer-gaps.test.ts' 'tests/telemetry/cost-attribution.test.ts' 'tests/llm/error-messages.test.ts' 'tests/llm/openai.test.ts' 'tests/llm/sse-event-line-shim.test.ts' 'tests/llm/subagent-model-tier.test.ts' 'tests/llm/wire-model.test.ts' 'tests/llm/availability.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
