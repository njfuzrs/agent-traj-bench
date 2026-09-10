#!/bin/bash
# T3 生成，勿手改。task=T0050
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
git checkout -- 'tests/agent/custom-agent.test.ts' 2>/dev/null || true
git checkout -- 'tests/agent/forked-agent.test.ts' 2>/dev/null || true
git checkout -- 'tests/agent/interrupt-abort-e2e.test.ts' 2>/dev/null || true
git checkout -- 'tests/agent/kernel-coverage-audit.test.ts' 2>/dev/null || true
git checkout -- 'tests/agent/loop-detection.test.ts' 2>/dev/null || true
git checkout -- 'tests/agent/loop-recovery-history-integrity.test.ts' 2>/dev/null || true
git checkout -- 'tests/agent/message-invariants.test.ts' 2>/dev/null || true
git checkout -- 'tests/agent/parallel-tools.test.ts' 2>/dev/null || true
git checkout -- 'tests/agent/plan-approval-ordering.test.ts' 2>/dev/null || true
git checkout -- 'tests/agent/spec18-subagent.test.ts' 2>/dev/null || true
git checkout -- 'tests/agent/sub-agent-spawn.test.ts' 2>/dev/null || true
git checkout -- 'tests/agent/sub-agent.test.ts' 2>/dev/null || true
git checkout -- 'tests/agent/subagent-capability-visibility.test.ts' 2>/dev/null || true
git checkout -- 'tests/agent/tool-filter-async.test.ts' 2>/dev/null || true
git checkout -- 'tests/agent/tool-result-invariant.test.ts' 2>/dev/null || true
git checkout -- 'tests/api/errors.test.ts' 2>/dev/null || true
git checkout -- 'tests/llm/capabilities.test.ts' 2>/dev/null || true
git checkout -- 'tests/llm/errors.test.ts' 2>/dev/null || true
git checkout -- 'tests/llm/mock-provider.test.ts' 2>/dev/null || true
git checkout -- 'tests/permission/checker.test.ts' 2>/dev/null || true
git checkout -- 'tests/permission/path-validator.test.ts' 2>/dev/null || true
git checkout -- 'tests/permission/shell-parser.test.ts' 2>/dev/null || true
git checkout -- 'tests/query/empty-param.test.ts' 2>/dev/null || true
git checkout -- 'tests/skill/ci-self-heal.test.ts' 2>/dev/null || true
git checkout -- 'tests/skill/code-governance.test.ts' 2>/dev/null || true
git checkout -- 'tests/skill/code-review.test.ts' 2>/dev/null || true
git checkout -- 'tests/skill/security-audit-scripts.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/omission-detector.test.ts' 2>/dev/null || true
git checkout -- 'tests/trace/builder.test.ts' 2>/dev/null || true
git checkout -- 'tests/trace/collector.test.ts' 2>/dev/null || true
rm -f 'tests/agent/subagent-tracker-isolation.test.ts'

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
bun test --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/agent/subagent-tracker-isolation.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/agent/loop-detection.test.ts' 'tests/agent/message-invariants.test.ts' 'tests/agent/sub-agent.test.ts' 'tests/agent/forked-agent.test.ts' 'tests/agent/sub-agent-spawn.test.ts' 'tests/agent/custom-agent.test.ts' 'tests/agent/subagent-capability-visibility.test.ts' 'tests/agent/spec18-subagent.test.ts' 'tests/agent/parallel-tools.test.ts' 'tests/agent/tool-filter-async.test.ts' 'tests/agent/kernel-coverage-audit.test.ts' 'tests/agent/tool-result-invariant.test.ts' 'tests/agent/loop-recovery-history-integrity.test.ts' 'tests/agent/plan-approval-ordering.test.ts' 'tests/agent/interrupt-abort-e2e.test.ts' 'tests/skill/code-review.test.ts' 'tests/trace/collector.test.ts' 'tests/tool/omission-detector.test.ts' 'tests/skill/ci-self-heal.test.ts' 'tests/llm/errors.test.ts' 'tests/skill/security-audit-scripts.test.ts' 'tests/permission/path-validator.test.ts' 'tests/trace/builder.test.ts' 'tests/api/errors.test.ts' 'tests/llm/mock-provider.test.ts' 'tests/permission/checker.test.ts' 'tests/permission/shell-parser.test.ts' 'tests/llm/capabilities.test.ts' 'tests/query/empty-param.test.ts' 'tests/skill/code-governance.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
