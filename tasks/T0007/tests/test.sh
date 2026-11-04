#!/bin/bash
# T3 生成，勿手改。task=T0007
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
restore_pinned 'tests/agent/agent-frontmatter-fields.test.ts' 'b8563b1e8a5f38e760fa014bddf4b767a5da079c'
restore_pinned 'tests/agent/loop-detection.test.ts' '5bd2ab71a2cd62bf858546c4664a907a6ebfa257'
restore_pinned 'tests/agent/message-invariants.test.ts' 'b42bc0d402201dc3f72edeb2d4adc68e68ecf5d8'
restore_pinned 'tests/agent/sub-agent.test.ts' '71e77a4a2e9a508c562ce081cd73e4b45a43076a'
restore_pinned 'tests/llm/capabilities.test.ts' 'd89e24b2f45f2726de13db4289acecd5155581af'
restore_pinned 'tests/llm/capability-wiring-regression.test.ts' '1aa36b1104296ceb09a536501435e6b757e6750d'
restore_pinned 'tests/llm/effort.test.ts' 'c4805598d4b8eaa56adea6b6d4d6b7ee8eac63a4'
restore_pinned 'tests/llm/errors.test.ts' '78adffa364f15aeb964a149095a43f1d03876377'
restore_pinned 'tests/llm/fallback.test.ts' '1a5464ae4a641bbc14666357169c6c3f16517c91'
restore_pinned 'tests/llm/gateway-pricing.test.ts' '4ff468f6a35c37ad207a36fa850b746f42005673'
restore_pinned 'tests/llm/mock-provider.test.ts' '8c330d0ea7bff82146fe7ede2f578b322d1ab877'
restore_pinned 'tests/llm/model-capabilities.test.ts' '7720340cd586164c15aa3af3a1f1390ccaf924a5'
restore_pinned 'tests/llm/openai-protocol-edge.test.ts' '05743bd6ea2381ba221fd8d60711305e1fe7c302'
restore_pinned 'tests/llm/provider-anthropic-conformance.test.ts' 'da17ad81e6cb0a3554e38e65f7caffb12f0de833'
restore_pinned 'tests/llm/provider-conformance.test.ts' 'b835f4412e35385b7d38778c3ea288773b9762ad'
restore_pinned 'tests/llm/quota.test.ts' '2997a739aa369422ac9f04b4b183dfda98390c0a'
restore_pinned 'tests/llm/secret-redact.test.ts' '048fa05523661cd9f799392f7ec4d2666237c2bf'
restore_pinned 'tests/llm/token-estimator.test.ts' '8042f50270bfb794f3b1787ad21442d6127d0236'
restore_pinned 'tests/tool/ask-user-question.test.ts' 'db7b082d4765dad17f7a2b2ddccb7d52301c8f29'
restore_pinned 'tests/tool/bash-write-targets.test.ts' '3f18950cfb9027d0cdd3a9bb836f19cae402f1f6'
restore_pinned 'tests/tool/edit.test.ts' '5b62e72c2a3628055d57eecc8679433b4bc99cf0'
restore_pinned 'tests/tool/grep.test.ts' '811b2adbe21363954394c06f850f76320ed410c0'
restore_pinned 'tests/tool/omission-detector.test.ts' 'b0fb5707410b8c4b404159cf09de4ad483f8e4b8'
restore_pinned 'tests/tool/path-utils.test.ts' '9ba98e5a0ccef67863e36929e458b9f0bfd17961'
restore_pinned 'tests/tool/read-tool.test.ts' '05c716e1749f9bd96cd088169248a667c3d5f05a'
restore_pinned 'tests/tool/todo-write.test.ts' '49ad2abc37697fcb9663e6939f4adc353f66de2a'
restore_pinned 'tests/tool/tool-search-auto.test.ts' '536e0dcdde99e27087c28d00a63abb2d19411c52'
restore_pinned 'tests/tool/tool-search-scoring.test.ts' '0f96e56948e183f5f95149b53602e02d3f91b9e3'
restore_pinned 'tests/tool/tool-search.test.ts' 'dadb9427be973ba3ba9eeeecbdf3911b72341d24'
restore_pinned 'tests/tool/web-fetch.test.ts' '7e037158a4feea42e84ebbabfa7234252b1775e8'
rm -f 'tests/agent/sub-agent-model-whitelist.test.ts'
rm -f 'tests/llm/strict-wire-contract-reconciliation.test.ts'
rm -f 'tests/tool/nullish-normalize.test.ts'

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
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/agent/sub-agent-model-whitelist.test.ts' 'tests/llm/strict-wire-contract-reconciliation.test.ts' 'tests/tool/nullish-normalize.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/llm/errors.test.ts' 'tests/tool/omission-detector.test.ts' 'tests/llm/effort.test.ts' 'tests/tool/read-tool.test.ts' 'tests/agent/loop-detection.test.ts' 'tests/llm/capability-wiring-regression.test.ts' 'tests/llm/fallback.test.ts' 'tests/llm/model-capabilities.test.ts' 'tests/llm/openai-protocol-edge.test.ts' 'tests/tool/todo-write.test.ts' 'tests/tool/web-fetch.test.ts' 'tests/agent/sub-agent.test.ts' 'tests/llm/gateway-pricing.test.ts' 'tests/llm/mock-provider.test.ts' 'tests/tool/tool-search-scoring.test.ts' 'tests/llm/capabilities.test.ts' 'tests/agent/message-invariants.test.ts' 'tests/llm/token-estimator.test.ts' 'tests/tool/tool-search-auto.test.ts' 'tests/llm/provider-conformance.test.ts' 'tests/llm/secret-redact.test.ts' 'tests/tool/ask-user-question.test.ts' 'tests/tool/tool-search.test.ts' 'tests/tool/edit.test.ts' 'tests/tool/grep.test.ts' 'tests/agent/agent-frontmatter-fields.test.ts' 'tests/llm/provider-anthropic-conformance.test.ts' 'tests/tool/bash-write-targets.test.ts' 'tests/tool/path-utils.test.ts' 'tests/llm/quota.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
