#!/bin/bash
# T3 生成，勿手改。task=T0002
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
restore_pinned 'tests/agent/loop-detection.test.ts' '5bd2ab71a2cd62bf858546c4664a907a6ebfa257'
restore_pinned 'tests/config/language-preference.test.ts' 'cb98c05c628f392e8f43209422380e63533662f2'
restore_pinned 'tests/llm/capability-wiring-regression.test.ts' '1aa36b1104296ceb09a536501435e6b757e6750d'
restore_pinned 'tests/llm/effort.test.ts' 'c4805598d4b8eaa56adea6b6d4d6b7ee8eac63a4'
restore_pinned 'tests/llm/errors.test.ts' '78adffa364f15aeb964a149095a43f1d03876377'
restore_pinned 'tests/llm/fallback.test.ts' '1a5464ae4a641bbc14666357169c6c3f16517c91'
restore_pinned 'tests/llm/strict-wire-contract-reconciliation.test.ts' '44a0f10d30006c2f5deeda0ae7a9b3c43b8eacf5'
restore_pinned 'tests/permission/bash-security.test.ts' '8b8b9ef6ed466bab1da35f10c0e34f9b3c2b7be8'
restore_pinned 'tests/permission/checker.test.ts' 'efd1c9f18b282913226c772c7a0262ef81e7e75a'
restore_pinned 'tests/preload-isolate-sid-home.ts' '541abfc175dc7e4804aefa3714fb889d87a60226'
restore_pinned 'tests/query/hypothesis-gaps.test.ts' '5b638f43c05954979df8dcdff27ed8de063afc1c'
restore_pinned 'tests/query/hypothesis-ledger.test.ts' 'c88b37d1910a58ee809f88d3127ae6167e4b3b2b'
restore_pinned 'tests/skill/ci-self-heal.test.ts' 'b897c1904b3742a85854799441339c8cd4e6f18d'
restore_pinned 'tests/skill/code-review.test.ts' '3c37b7dc506bde9442ff9c472aa08279ff9e230e'
restore_pinned 'tests/telemetry/cache-telemetry-rotation.test.ts' 'b7651cf21c9e2e046fb704ed5294e9915a12a614'
restore_pinned 'tests/telemetry/cost-attribution.test.ts' '91e9c418ce674f3d44532bff03e371ca46fce9bb'
restore_pinned 'tests/telemetry/hook-probe.test.ts' '1db88e26a59cccf6d4ab3b5423fb3fdc52f518e0'
restore_pinned 'tests/telemetry/no-real-path-writes.test.ts' '9887701df9a2f280d3248ab8747c7031315e62bd'
restore_pinned 'tests/telemetry/otlp-exporter.test.ts' 'bc521f1ab89aa5e77b11a9db3eb681cd22c0eaf9'
restore_pinned 'tests/telemetry/otlp-wiring.test.ts' 'c966c10c5733676a7213edfee1bae048340ed57b'
restore_pinned 'tests/telemetry/provider-health.test.ts' '5516d8300ed1d8fcf8773d939b9d70f16449725c'
restore_pinned 'tests/telemetry/telemetry.test.ts' 'c88899fc2c999d3c5aa94c4490faddb869266b58'
restore_pinned 'tests/telemetry/tracing-enhanced.test.ts' '288e2a90d57c9598387ca50177bb964c2eca23d3'
restore_pinned 'tests/telemetry/usage-ledger.test.ts' '552f5031b21dafc76989a8df070cd84773ef428b'
restore_pinned 'tests/tool/grep-type-alias.test.ts' '9f24380f8b888c7354eeb44863fbdba545be1501'
restore_pinned 'tests/tool/omission-detector.test.ts' 'b0fb5707410b8c4b404159cf09de4ad483f8e4b8'
restore_pinned 'tests/tool/read-tool.test.ts' '05c716e1749f9bd96cd088169248a667c3d5f05a'
restore_pinned 'tests/tool/web-fetch.test.ts' 'ce85a967fea888a217b6e4b09714aa9e0ddb3de0'
restore_pinned 'tests/trace/collector.test.ts' 'c9510574a5b678acd181c830009c43454469aace'
restore_pinned 'tests/ui/keybindings-full-coverage.test.ts' '94f0a57db8f7adc21cb1f0d624549392b9744082'
restore_pinned 'tests/website/changelog-curated.test.ts' 'd76c18dae7687eb898dac08f9567b64404c558ea'
rm -f 'tests/telemetry/config-undefined-defaults.test.ts'

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
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/telemetry/config-undefined-defaults.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/telemetry/otlp-exporter.test.ts' 'tests/telemetry/usage-ledger.test.ts' 'tests/telemetry/hook-probe.test.ts' 'tests/telemetry/cost-attribution.test.ts' 'tests/telemetry/telemetry.test.ts' 'tests/telemetry/cache-telemetry-rotation.test.ts' 'tests/telemetry/otlp-wiring.test.ts' 'tests/telemetry/tracing-enhanced.test.ts' 'tests/telemetry/provider-health.test.ts' 'tests/telemetry/no-real-path-writes.test.ts' 'tests/skill/code-review.test.ts' 'tests/llm/strict-wire-contract-reconciliation.test.ts' 'tests/permission/bash-security.test.ts' 'tests/trace/collector.test.ts' 'tests/config/language-preference.test.ts' 'tests/query/hypothesis-gaps.test.ts' 'tests/llm/errors.test.ts' 'tests/tool/omission-detector.test.ts' 'tests/llm/effort.test.ts' 'tests/ui/keybindings-full-coverage.test.ts' 'tests/permission/checker.test.ts' 'tests/tool/read-tool.test.ts' 'tests/agent/loop-detection.test.ts' 'tests/llm/capability-wiring-regression.test.ts' 'tests/llm/fallback.test.ts' 'tests/skill/ci-self-heal.test.ts' 'tests/query/hypothesis-ledger.test.ts' 'tests/tool/grep-type-alias.test.ts' 'tests/website/changelog-curated.test.ts' 'tests/tool/web-fetch.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
