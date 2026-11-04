#!/bin/bash
# T3 生成，勿手改。task=T0051
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
restore_pinned 'src/ide/integration.test.ts' '162fd540fd4333bb78f889f23f15b94f909f44c8'
restore_pinned 'tests/agent/custom-agent.test.ts' 'f64d49b300e6856d6a214e2a2524d246ecea4e13'
restore_pinned 'tests/agent/followup-ordering-invariant.test.ts' 'a8cee8d98cb23ca729749c085c85c4e3b76a063c'
restore_pinned 'tests/agent/forked-agent.test.ts' 'aefffd3c11946e76d1b4c39faf35e275869fe0d0'
restore_pinned 'tests/agent/interrupt-abort-e2e.test.ts' '9a0831cbab6893920055f079bf01b6a92461067d'
restore_pinned 'tests/agent/interrupt-history-integrity.test.ts' '1b99eb4d431da7b3a4b635d8adc6766bdb41d2c0'
restore_pinned 'tests/agent/kernel-coverage-audit.test.ts' '8b1c3c69fcab237d99790ee1983d2266f838dca1'
restore_pinned 'tests/agent/loop-detection.test.ts' 'd04467f09c767909ed3f067e4912e9f6988291a9'
restore_pinned 'tests/agent/message-invariants.test.ts' '76251dbc87b34e04bc39581d20839b6f59382fd3'
restore_pinned 'tests/agent/parallel-tools.test.ts' 'b241e16d5e45461a8d08ab487c627dc55f54860c'
restore_pinned 'tests/agent/plan-approval-ordering.test.ts' 'ef8be6d2943884117c6463023c5a22598a4d89f2'
restore_pinned 'tests/agent/spec18-subagent.test.ts' '2ff5a7c56809e66376298d254bb482b3835ad583'
restore_pinned 'tests/agent/sub-agent.test.ts' 'd691ed56db3d212d6fbcf9b4d8b608a474bb6c68'
restore_pinned 'tests/agent/tool-result-invariant.test.ts' '1f8469b463af8b43478aa633a48dbe515893a94e'
restore_pinned 'tests/api/errors.test.ts' '08ea5de410d864635a8659b0b1b4015670d82994'
restore_pinned 'tests/llm/capabilities.test.ts' '9178a2a1efcfe384a028b69f83273b155fe68b40'
restore_pinned 'tests/llm/errors.test.ts' 'f873b1e2efed815df00d1271bed58ce6631f70c6'
restore_pinned 'tests/llm/mock-provider.test.ts' 'cb554e25797143ccf394ce06867c6f4f942faee4'
restore_pinned 'tests/llm/secret-redact.test.ts' '048fa05523661cd9f799392f7ec4d2666237c2bf'
restore_pinned 'tests/permission/checker.test.ts' '681ee04d406a982baf5e8ea3c0df2d0e30abed79'
restore_pinned 'tests/permission/shell-parser.test.ts' '8fe80041f43ffba9659441c2b1297a1379c059a6'
restore_pinned 'tests/sdk/schemas.test.ts' '63948e02a004ef3c79cdae13687fc947e0e66aca'
restore_pinned 'tests/skill/ci-self-heal-chaos.test.ts' 'ecb528e2142b101c81260b23c2af9873f055c046'
restore_pinned 'tests/skill/ci-self-heal.test.ts' '05685234fa13290f46fb489e903012ab118cb3b1'
restore_pinned 'tests/skill/code-governance.test.ts' '2b1bc4ce4e87f1b6db4e272ce296ce1bab74a17c'
restore_pinned 'tests/skill/code-review-chaos.test.ts' '50f0817ea3fddb72239d3582eb40e5ed7400fd67'
restore_pinned 'tests/skill/code-review.test.ts' '3c37b7dc506bde9442ff9c472aa08279ff9e230e'
restore_pinned 'tests/skill/security-audit-scripts.test.ts' 'e78ca963643b6ad3875acbfd42205d3ea21cc991'
restore_pinned 'tests/trace/builder.test.ts' '40b88170d111695d745f9ba4aec6bc44f2aa3cef'
restore_pinned 'tests/trace/collector.test.ts' '8d6461cc47e28ae22ca714cd94330b02f3466664'
restore_pinned 'tests/ui/keybindings-full-coverage.test.ts' '94f0a57db8f7adc21cb1f0d624549392b9744082'
rm -f 'tests/agent/loop-recovery-history-integrity.test.ts'

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
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/agent/loop-recovery-history-integrity.test.ts' 'tests/agent/message-invariants.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/agent/loop-detection.test.ts' 'tests/agent/sub-agent.test.ts' 'tests/agent/forked-agent.test.ts' 'tests/agent/custom-agent.test.ts' 'tests/agent/spec18-subagent.test.ts' 'tests/agent/parallel-tools.test.ts' 'tests/agent/kernel-coverage-audit.test.ts' 'tests/agent/tool-result-invariant.test.ts' 'tests/agent/followup-ordering-invariant.test.ts' 'tests/agent/interrupt-history-integrity.test.ts' 'tests/agent/plan-approval-ordering.test.ts' 'tests/agent/interrupt-abort-e2e.test.ts' 'tests/skill/code-review.test.ts' 'tests/skill/ci-self-heal.test.ts' 'tests/trace/collector.test.ts' 'tests/llm/errors.test.ts' 'tests/skill/security-audit-scripts.test.ts' 'tests/trace/builder.test.ts' 'tests/api/errors.test.ts' 'tests/llm/mock-provider.test.ts' 'tests/permission/shell-parser.test.ts' 'tests/llm/capabilities.test.ts' 'tests/skill/code-governance.test.ts' 'tests/permission/checker.test.ts' 'tests/ui/keybindings-full-coverage.test.ts' 'tests/skill/ci-self-heal-chaos.test.ts' 'tests/llm/secret-redact.test.ts' 'tests/skill/code-review-chaos.test.ts' 'src/ide/integration.test.ts' 'tests/sdk/schemas.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
