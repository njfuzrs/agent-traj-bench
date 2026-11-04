#!/bin/bash
# T3 生成，勿手改。task=T0009
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
restore_pinned 'tests/context/auto-compact-context.test.ts' '57e6647ebf7bf3d10eca099230f71145dfcfb9b8'
restore_pinned 'tests/context/enhancement.test.ts' '28ff557d6dd0939b02198f9b5673ae9ea22f7851'
restore_pinned 'tests/context/manager.test.ts' '4b56c7dbed67564ac198c2a8ec327e8e33375bbe'
restore_pinned 'tests/context/truncation.test.ts' '40bba1c7243b33b13b8cc2b8f7af47f0d666c490'
restore_pinned 'tests/llm/availability.test.ts' '7aa5b2c8597fe62b498151f1d89f4c4080e53dd2'
restore_pinned 'tests/llm/capabilities.test.ts' 'd89e24b2f45f2726de13db4289acecd5155581af'
restore_pinned 'tests/llm/effort.test.ts' '782ef969b124c862563c701b74a4e45b9d831e1d'
restore_pinned 'tests/llm/error-messages.test.ts' '8787a9f15f21c544b471f28f2d573edd12c75543'
restore_pinned 'tests/llm/errors.test.ts' '78adffa364f15aeb964a149095a43f1d03876377'
restore_pinned 'tests/llm/fallback.test.ts' '1a5464ae4a641bbc14666357169c6c3f16517c91'
restore_pinned 'tests/llm/gateway-pricing.test.ts' '0bef948ac617d328a6b647305ea69f11700cf12c'
restore_pinned 'tests/llm/mock-provider.test.ts' '8c330d0ea7bff82146fe7ede2f578b322d1ab877'
restore_pinned 'tests/llm/model-registry.test.ts' 'af9635f8fb2e4641e25189817f3aa7fabb723178'
restore_pinned 'tests/llm/openai-protocol-edge.test.ts' '05743bd6ea2381ba221fd8d60711305e1fe7c302'
restore_pinned 'tests/llm/openai.test.ts' '7a2a881ae1f37cb3ac6e78444abb5748ee06f055'
restore_pinned 'tests/llm/provider-anthropic-conformance.test.ts' 'da17ad81e6cb0a3554e38e65f7caffb12f0de833'
restore_pinned 'tests/llm/provider-conformance.test.ts' '9808b3dda7c6baf4011ff6b09ead5e48ea90e92e'
restore_pinned 'tests/llm/quota.test.ts' '2997a739aa369422ac9f04b4b183dfda98390c0a'
restore_pinned 'tests/llm/registry.test.ts' '3efc7cbb0617947f680c934a3c16066a7af7f9fd'
restore_pinned 'tests/llm/secret-redact.test.ts' '048fa05523661cd9f799392f7ec4d2666237c2bf'
restore_pinned 'tests/llm/sse-event-line-shim.test.ts' '084f23bc5fb043b6a65b25359f4355227295cdbc'
restore_pinned 'tests/llm/subagent-model-tier.test.ts' '5817dc9ad1f6c96702ccb0affb643bfa3a254772'
restore_pinned 'tests/llm/token-estimator.test.ts' '690efd9d0d455a0807c754d3160d5f34d7a28746'
restore_pinned 'tests/ui/chord.test.ts' 'a6d70ffb2559055d3c1ede3fa5e4168ee54b56fd'
restore_pinned 'tests/ui/focus-manager.test.ts' 'a536c7e57b568ee75966a72eb78b10e9d7eb164b'
restore_pinned 'tests/ui/history-adapter.test.ts' '1560b6d0ff66356417c8df1836c06e9b85bece36'
restore_pinned 'tests/ui/keybindings-full-coverage.test.ts' '94f0a57db8f7adc21cb1f0d624549392b9744082'
restore_pinned 'tests/ui/scroll-quantum.test.ts' '8e5324cf99233693cf78319fe12bb8444b87e190'
restore_pinned 'tests/ui/status-line-data.test.ts' 'fa5983f2b9e543f45c4a5c0e767856423409b31d'
restore_pinned 'tests/ui/vim-state-machine.test.ts' '7d408512e550d261ee7a9c3287fe7c8d29d84c02'
rm -f 'tests/context/meta-preservation.test.ts'
rm -f 'tests/llm/openai-block-fidelity.test.ts'
rm -f 'tests/ui/hidden-path-tool-result.test.ts'

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
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/context/meta-preservation.test.ts' 'tests/llm/openai-block-fidelity.test.ts' 'tests/ui/hidden-path-tool-result.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/llm/errors.test.ts' 'tests/llm/effort.test.ts' 'tests/ui/keybindings-full-coverage.test.ts' 'tests/ui/history-adapter.test.ts' 'tests/llm/fallback.test.ts' 'tests/llm/openai-protocol-edge.test.ts' 'tests/ui/vim-state-machine.test.ts' 'tests/context/manager.test.ts' 'tests/llm/mock-provider.test.ts' 'tests/llm/capabilities.test.ts' 'tests/context/enhancement.test.ts' 'tests/llm/token-estimator.test.ts' 'tests/llm/provider-conformance.test.ts' 'tests/llm/secret-redact.test.ts' 'tests/llm/provider-anthropic-conformance.test.ts' 'tests/llm/quota.test.ts' 'tests/llm/registry.test.ts' 'tests/context/truncation.test.ts' 'tests/ui/status-line-data.test.ts' 'tests/llm/gateway-pricing.test.ts' 'tests/llm/error-messages.test.ts' 'tests/llm/openai.test.ts' 'tests/llm/sse-event-line-shim.test.ts' 'tests/ui/scroll-quantum.test.ts' 'tests/context/auto-compact-context.test.ts' 'tests/llm/subagent-model-tier.test.ts' 'tests/ui/chord.test.ts' 'tests/ui/focus-manager.test.ts' 'tests/llm/availability.test.ts' 'tests/llm/model-registry.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
