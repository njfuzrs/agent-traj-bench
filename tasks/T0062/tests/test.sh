#!/bin/bash
# T3 生成，勿手改。task=T0062
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
restore_pinned 'tests/llm/effort.test.ts' 'e1deb0356c4ab1b53a0bc41384016b6bfb5a4967'
restore_pinned 'tests/llm/error-messages.test.ts' '8787a9f15f21c544b471f28f2d573edd12c75543'
restore_pinned 'tests/llm/errors.test.ts' '8c1144943355355f4da731c020819e161b813537'
restore_pinned 'tests/llm/fallback.test.ts' 'c5ed2543efd93251a92ce3b732861f3e3b59db22'
restore_pinned 'tests/llm/gateway-pricing.test.ts' '0bef948ac617d328a6b647305ea69f11700cf12c'
restore_pinned 'tests/llm/mock-provider.test.ts' '8c330d0ea7bff82146fe7ede2f578b322d1ab877'
restore_pinned 'tests/llm/model-registry.test.ts' 'af9635f8fb2e4641e25189817f3aa7fabb723178'
restore_pinned 'tests/llm/openai-protocol-edge.test.ts' '05743bd6ea2381ba221fd8d60711305e1fe7c302'
restore_pinned 'tests/llm/openai-responses-strict-schema.test.ts' '7d2cfbf4b8abf9e5cbdbcb4a41739979f35fc209'
restore_pinned 'tests/llm/openai-responses.test.ts' '5e4f77bfd35db1b12026724447a6d38d8a00dcfc'
restore_pinned 'tests/llm/openai.test.ts' '80e26c6abb1c4438c7e3eaa29e6a27175efbe227'
restore_pinned 'tests/llm/parseSSE-signal-abort.test.ts' '4d3dabbcab244d5e41d912cdc74205d91de69d77'
restore_pinned 'tests/llm/protocol-sentinel.test.ts' '8febdce3c47d1dceeea396cea3c12f820a7fa584'
restore_pinned 'tests/llm/provider-anthropic-conformance.test.ts' 'da17ad81e6cb0a3554e38e65f7caffb12f0de833'
restore_pinned 'tests/llm/provider-conformance.test.ts' '9808b3dda7c6baf4011ff6b09ead5e48ea90e92e'
restore_pinned 'tests/llm/provider-protocol-contract.test.ts' 'd1a413421fc69165ca85b0130e208d89f000c6e8'
restore_pinned 'tests/llm/quota.test.ts' '2997a739aa369422ac9f04b4b183dfda98390c0a'
restore_pinned 'tests/llm/registry.test.ts' 'aa18fb8d52442ff010e3551daa6e93fd172af26f'
restore_pinned 'tests/llm/retry-telemetry.test.ts' '62ac965ed105df9135904406de38afeda54ee6c5'
restore_pinned 'tests/llm/router-mock-integration.test.ts' '118209ae15234a7e8a59e69fc3fb975320b68922'
restore_pinned 'tests/llm/sanitize-unicode.test.ts' '5908ade75efbfed79dc267053c35015b45e924aa'
restore_pinned 'tests/llm/secret-redact.test.ts' '048fa05523661cd9f799392f7ec4d2666237c2bf'
restore_pinned 'tests/llm/sse-chunk-dumper.test.ts' 'f0733db4dd84b4dee226a61f42d1b4752c2b4991'
restore_pinned 'tests/llm/sse-event-line-shim.test.ts' '084f23bc5fb043b6a65b25359f4355227295cdbc'
restore_pinned 'tests/llm/sse-reasoning-leak-e2e.test.ts' 'f6fcf25f005d54c505bcdb1569cba3dad7a261ff'
restore_pinned 'tests/llm/stream-interrupt-recovery.test.ts' '4e4e9b9fa7a7daa1c8061fd334c8bc0039d565ee'
restore_pinned 'tests/llm/stream-level-error.test.ts' '80256bb5c7e2a696c5df5318c4eaea3e967d33f1'
restore_pinned 'tests/llm/stream-lifecycle.test.ts' 'dab8a4fe29fb603209d9a02eb2adf45624b5310f'
restore_pinned 'tests/llm/token-estimator.test.ts' '690efd9d0d455a0807c754d3160d5f34d7a28746'
# （本条 task 无 agent 可能新建的测试文件需删除）

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
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/llm/effort.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/llm/errors.test.ts' 'tests/llm/fallback.test.ts' 'tests/llm/openai-protocol-edge.test.ts' 'tests/llm/mock-provider.test.ts' 'tests/llm/capabilities.test.ts' 'tests/llm/token-estimator.test.ts' 'tests/llm/provider-conformance.test.ts' 'tests/llm/secret-redact.test.ts' 'tests/llm/provider-anthropic-conformance.test.ts' 'tests/llm/quota.test.ts' 'tests/llm/gateway-pricing.test.ts' 'tests/llm/registry.test.ts' 'tests/llm/error-messages.test.ts' 'tests/llm/sse-event-line-shim.test.ts' 'tests/llm/openai.test.ts' 'tests/llm/availability.test.ts' 'tests/llm/model-registry.test.ts' 'tests/llm/stream-interrupt-recovery.test.ts' 'tests/llm/stream-lifecycle.test.ts' 'tests/llm/openai-responses-strict-schema.test.ts' 'tests/llm/stream-level-error.test.ts' 'tests/llm/provider-protocol-contract.test.ts' 'tests/llm/router-mock-integration.test.ts' 'tests/llm/sanitize-unicode.test.ts' 'tests/llm/openai-responses.test.ts' 'tests/llm/protocol-sentinel.test.ts' 'tests/llm/sse-chunk-dumper.test.ts' 'tests/llm/parseSSE-signal-abort.test.ts' 'tests/llm/retry-telemetry.test.ts' 'tests/llm/sse-reasoning-leak-e2e.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
