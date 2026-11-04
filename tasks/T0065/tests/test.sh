#!/bin/bash
# T3 生成，勿手改。task=T0065
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
restore_pinned 'tests/agent/loop-detection.test.ts' '1dbbd2b599a42257a2c7483883217d0fc18c2284'
restore_pinned 'tests/api/errors.test.ts' '08ea5de410d864635a8659b0b1b4015670d82994'
restore_pinned 'tests/llm/capabilities.test.ts' 'd89e24b2f45f2726de13db4289acecd5155581af'
restore_pinned 'tests/llm/effort.test.ts' '488d518056cfdd0576539a8af8822b1eede8ed7b'
restore_pinned 'tests/llm/errors.test.ts' 'bf04fc73d256ab3b0675113bf2134de18fc566d3'
restore_pinned 'tests/llm/mock-provider.test.ts' '8c330d0ea7bff82146fe7ede2f578b322d1ab877'
restore_pinned 'tests/permission/checker.test.ts' '22e81dd63018b98c12121331cfaf13c4091b2663'
restore_pinned 'tests/permission/path-validator.test.ts' '3780c447557369a58762b782f444472b91f49b8f'
restore_pinned 'tests/permission/shell-parser.test.ts' '8fe80041f43ffba9659441c2b1297a1379c059a6'
restore_pinned 'tests/query/empty-param.test.ts' '6d891f36ae74931e94cf21ec734c3c4e60e06424'
restore_pinned 'tests/skill/budget.test.ts' 'b60651d282062c8233f04dd5b9ec056ebf8ab064'
restore_pinned 'tests/skill/bundled.test.ts' 'f156e1f67d43703d6c7b68412207be4876ef76a2'
restore_pinned 'tests/skill/change-detector.test.ts' 'b1717d52887e4d1d8df68c763a242d0d938f3d6b'
restore_pinned 'tests/skill/ci-self-heal-chaos.test.ts' 'dcec6c8df0528c2b4db1c4cc5c68ee93785feaa0'
restore_pinned 'tests/skill/ci-self-heal.test.ts' 'b897c1904b3742a85854799441339c8cd4e6f18d'
restore_pinned 'tests/skill/code-governance.test.ts' '2b1bc4ce4e87f1b6db4e272ce296ce1bab74a17c'
restore_pinned 'tests/skill/code-review-chaos.test.ts' '50f0817ea3fddb72239d3582eb40e5ed7400fd67'
restore_pinned 'tests/skill/code-review.test.ts' '3c37b7dc506bde9442ff9c472aa08279ff9e230e'
restore_pinned 'tests/skill/dynamic-conditional.test.ts' '8a819361a1cdaec94a8382762566877d33b1304c'
restore_pinned 'tests/skill/enhancement.test.ts' 'df3a4ab08dc7aeecd7ad20faccffa384da36da6f'
restore_pinned 'tests/skill/hooks.test.ts' '8902a090198635fb63bac8aa6531f8ce3c8eadaf'
restore_pinned 'tests/skill/permission-mcp.test.ts' '4413e4d9ae8778c4d0db56f7a21960c6c881d92a'
restore_pinned 'tests/skill/prompt-processor.test.ts' '4e30b9a1f73eeca7406856f11418bd7249e343d6'
restore_pinned 'tests/skill/security-audit-scripts.test.ts' 'e78ca963643b6ad3875acbfd42205d3ea21cc991'
restore_pinned 'tests/skill/skill.test.ts' '89b2be381c291f57ca66c659c089fd0fa2db6986'
restore_pinned 'tests/tool/omission-detector.test.ts' '906829dd226926ef57e3c9ceb614cb93c9bd4ccb'
restore_pinned 'tests/trace/builder.test.ts' '40b88170d111695d745f9ba4aec6bc44f2aa3cef'
restore_pinned 'tests/trace/collector.test.ts' 'd2de3b35ba757c1d955fba54936be11f0b2c2339'
restore_pinned 'tests/ui/history-adapter.test.ts' 'be0f719c95a0580e459d84372dfa5b371015814a'
restore_pinned 'tests/ui/keybindings-full-coverage.test.ts' '94f0a57db8f7adc21cb1f0d624549392b9744082'
restore_pinned 'tests/workflow/sandbox.test.ts' '69247565076918856e8b9556fe21005afb4405da'
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
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/skill/skill.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/skill/code-review.test.ts' 'tests/skill/ci-self-heal.test.ts' 'tests/skill/security-audit-scripts.test.ts' 'tests/skill/code-governance.test.ts' 'tests/skill/ci-self-heal-chaos.test.ts' 'tests/skill/code-review-chaos.test.ts' 'tests/skill/enhancement.test.ts' 'tests/skill/prompt-processor.test.ts' 'tests/skill/bundled.test.ts' 'tests/skill/permission-mcp.test.ts' 'tests/skill/dynamic-conditional.test.ts' 'tests/skill/budget.test.ts' 'tests/skill/hooks.test.ts' 'tests/skill/change-detector.test.ts' 'tests/trace/collector.test.ts' 'tests/tool/omission-detector.test.ts' 'tests/agent/loop-detection.test.ts' 'tests/llm/errors.test.ts' 'tests/permission/path-validator.test.ts' 'tests/llm/effort.test.ts' 'tests/workflow/sandbox.test.ts' 'tests/trace/builder.test.ts' 'tests/api/errors.test.ts' 'tests/llm/mock-provider.test.ts' 'tests/permission/checker.test.ts' 'tests/permission/shell-parser.test.ts' 'tests/ui/history-adapter.test.ts' 'tests/llm/capabilities.test.ts' 'tests/query/empty-param.test.ts' 'tests/ui/keybindings-full-coverage.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
