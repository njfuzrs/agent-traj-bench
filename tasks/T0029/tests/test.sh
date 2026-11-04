#!/bin/bash
# T3 生成，勿手改。task=T0029
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
restore_pinned 'tests/agent/loop-detection.test.ts' '37d960690e1860c5c1822c468067a99f5977e3d2'
restore_pinned 'tests/api/errors.test.ts' '08ea5de410d864635a8659b0b1b4015670d82994'
restore_pinned 'tests/config/app-config.test.ts' '68a511a89a523efd43b509f439772320d633f76d'
restore_pinned 'tests/config/attachments.test.ts' '8585fc27a239f17be178f14cd4d350b3fb82315a'
restore_pinned 'tests/config/config.test.ts' 'ec450c5c87512e982553a83abe3def01836f5292'
restore_pinned 'tests/config/env-interpolation.test.ts' 'a32110767477c42dd95518c229d98c951f5a6f1a'
restore_pinned 'tests/config/env-sanitizer.test.ts' 'c2de8518a09be25ed15c37de12c01dc675895a17'
restore_pinned 'tests/config/import-processor.test.ts' '2894cb922b00ed40d27f3e7fde090eb915cda9e7'
restore_pinned 'tests/config/integration.test.ts' '381661c606a1a5487c80a00da923019769bcb153'
restore_pinned 'tests/config/managed-env.test.ts' '45cc510557cf6466e077adbc49d15cf1b10fc4af'
restore_pinned 'tests/config/rules-layered.test.ts' 'fb0b249f1b9fbe45d0b724be627847a854741049'
restore_pinned 'tests/config/rules.test.ts' 'b97e2d0b0068009be15e96a79146b4e772b67e89'
restore_pinned 'tests/config/schema.test.ts' 'a58a41fc95a83f2a2d6a920fb4708ff33f6c855c'
restore_pinned 'tests/config/settings.test.ts' '75287efe4f16687b35cbded1ba0581097158de74'
restore_pinned 'tests/config/system-prompt.test.ts' '872204d6c767f4a41c2eef729749d98b7c7a5def'
restore_pinned 'tests/config/token-utils.test.ts' 'e84b61fdb88609428dc67d9d8ac74dca0d7e06f9'
restore_pinned 'tests/llm/capabilities.test.ts' 'c7200ff90d85893ba49dbf52cfef66bddf3b018a'
restore_pinned 'tests/llm/errors.test.ts' 'b17303569b235cc0b9f75798634786d2fd115cf3'
restore_pinned 'tests/llm/mock-provider.test.ts' 'cb554e25797143ccf394ce06867c6f4f942faee4'
restore_pinned 'tests/permission/checker.test.ts' '681ee04d406a982baf5e8ea3c0df2d0e30abed79'
restore_pinned 'tests/permission/shell-parser.test.ts' '8fe80041f43ffba9659441c2b1297a1379c059a6'
restore_pinned 'tests/query/empty-param.test.ts' '6d891f36ae74931e94cf21ec734c3c4e60e06424'
restore_pinned 'tests/skill/ci-self-heal-chaos.test.ts' 'dcec6c8df0528c2b4db1c4cc5c68ee93785feaa0'
restore_pinned 'tests/skill/ci-self-heal.test.ts' 'b897c1904b3742a85854799441339c8cd4e6f18d'
restore_pinned 'tests/skill/code-governance.test.ts' '2b1bc4ce4e87f1b6db4e272ce296ce1bab74a17c'
restore_pinned 'tests/skill/code-review.test.ts' '3c37b7dc506bde9442ff9c472aa08279ff9e230e'
restore_pinned 'tests/skill/security-audit-scripts.test.ts' 'e78ca963643b6ad3875acbfd42205d3ea21cc991'
restore_pinned 'tests/tool/omission-detector.test.ts' '906829dd226926ef57e3c9ceb614cb93c9bd4ccb'
restore_pinned 'tests/trace/builder.test.ts' '40b88170d111695d745f9ba4aec6bc44f2aa3cef'
restore_pinned 'tests/trace/collector.test.ts' '23bfbafa29baf67c738f64293ce56c077255ba2a'
restore_pinned 'tests/ui/keybindings-full-coverage.test.ts' '94f0a57db8f7adc21cb1f0d624549392b9744082'
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
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/config/token-utils.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/config/settings.test.ts' 'tests/config/system-prompt.test.ts' 'tests/config/rules.test.ts' 'tests/config/rules-layered.test.ts' 'tests/config/attachments.test.ts' 'tests/config/env-interpolation.test.ts' 'tests/config/env-sanitizer.test.ts' 'tests/config/schema.test.ts' 'tests/config/managed-env.test.ts' 'tests/config/import-processor.test.ts' 'tests/config/app-config.test.ts' 'tests/config/integration.test.ts' 'tests/config/config.test.ts' 'tests/skill/code-review.test.ts' 'tests/tool/omission-detector.test.ts' 'tests/skill/ci-self-heal.test.ts' 'tests/trace/collector.test.ts' 'tests/llm/errors.test.ts' 'tests/skill/security-audit-scripts.test.ts' 'tests/agent/loop-detection.test.ts' 'tests/trace/builder.test.ts' 'tests/api/errors.test.ts' 'tests/llm/mock-provider.test.ts' 'tests/permission/shell-parser.test.ts' 'tests/ui/keybindings-full-coverage.test.ts' 'tests/llm/capabilities.test.ts' 'tests/query/empty-param.test.ts' 'tests/skill/code-governance.test.ts' 'tests/permission/checker.test.ts' 'tests/skill/ci-self-heal-chaos.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
