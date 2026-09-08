#!/bin/bash
# T3 生成，勿手改。task=T0070
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
git checkout -- 'tests/extension/loader.test.ts' 2>/dev/null || true
git checkout -- 'tests/memory/paths-scan.test.ts' 2>/dev/null || true
git checkout -- 'tests/agent/loop-detection.test.ts' 2>/dev/null || true
git checkout -- 'tests/app/plan-mode-record-write.test.ts' 2>/dev/null || true
git checkout -- 'tests/context/manager.test.ts' 2>/dev/null || true
git checkout -- 'tests/extension/managed-layer.test.ts' 2>/dev/null || true
git checkout -- 'tests/extension/naming.test.ts' 2>/dev/null || true
git checkout -- 'tests/extension/trust.test.ts' 2>/dev/null || true
git checkout -- 'tests/llm/effort.test.ts' 2>/dev/null || true
git checkout -- 'tests/llm/errors.test.ts' 2>/dev/null || true
git checkout -- 'tests/llm/fallback.test.ts' 2>/dev/null || true
git checkout -- 'tests/llm/openai-protocol-edge.test.ts' 2>/dev/null || true
git checkout -- 'tests/memory/agent-store.test.ts' 2>/dev/null || true
git checkout -- 'tests/memory/auto-memory-gate.test.ts' 2>/dev/null || true
git checkout -- 'tests/memory/dream.test.ts' 2>/dev/null || true
git checkout -- 'tests/memory/prompt-injection.test.ts' 2>/dev/null || true
git checkout -- 'tests/memory/recall.test.ts' 2>/dev/null || true
git checkout -- 'tests/memory/store.test.ts' 2>/dev/null || true
git checkout -- 'tests/migrations/backfill-team-defaults.test.ts' 2>/dev/null || true
git checkout -- 'tests/permission/bash-security.test.ts' 2>/dev/null || true
git checkout -- 'tests/permission/checker.test.ts' 2>/dev/null || true
git checkout -- 'tests/permission/path-validator.test.ts' 2>/dev/null || true
git checkout -- 'tests/skill/ci-self-heal.test.ts' 2>/dev/null || true
git checkout -- 'tests/skill/code-review.test.ts' 2>/dev/null || true
git checkout -- 'tests/skill/security-audit-scripts.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/omission-detector.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/read-tool.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/web-fetch.test.ts' 2>/dev/null || true
git checkout -- 'tests/trace/collector.test.ts' 2>/dev/null || true
git checkout -- 'tests/ui/history-adapter.test.ts' 2>/dev/null || true
git checkout -- 'tests/ui/keybindings-full-coverage.test.ts' 2>/dev/null || true
git checkout -- 'tests/ui/vim-state-machine.test.ts' 2>/dev/null || true
rm -f 'tests/app/at-reference-path-permission.test.ts'
rm -f 'tests/extension/frontmatter-fail-closed.test.ts'
rm -f 'tests/migrations/relocate-lossy-project-key.test.ts'

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
bun test --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/app/at-reference-path-permission.test.ts' 'tests/extension/frontmatter-fail-closed.test.ts' 'tests/extension/loader.test.ts' 'tests/memory/paths-scan.test.ts' 'tests/migrations/relocate-lossy-project-key.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/memory/prompt-injection.test.ts' 'tests/memory/store.test.ts' 'tests/memory/recall.test.ts' 'tests/memory/dream.test.ts' 'tests/memory/auto-memory-gate.test.ts' 'tests/app/plan-mode-record-write.test.ts' 'tests/extension/naming.test.ts' 'tests/extension/trust.test.ts' 'tests/migrations/backfill-team-defaults.test.ts' 'tests/memory/agent-store.test.ts' 'tests/extension/managed-layer.test.ts' 'tests/skill/code-review.test.ts' 'tests/permission/bash-security.test.ts' 'tests/trace/collector.test.ts' 'tests/llm/errors.test.ts' 'tests/tool/omission-detector.test.ts' 'tests/llm/effort.test.ts' 'tests/ui/keybindings-full-coverage.test.ts' 'tests/ui/history-adapter.test.ts' 'tests/agent/loop-detection.test.ts' 'tests/llm/fallback.test.ts' 'tests/skill/ci-self-heal.test.ts' 'tests/tool/read-tool.test.ts' 'tests/llm/openai-protocol-edge.test.ts' 'tests/permission/checker.test.ts' 'tests/tool/web-fetch.test.ts' 'tests/ui/vim-state-machine.test.ts' 'tests/skill/security-audit-scripts.test.ts' 'tests/permission/path-validator.test.ts' 'tests/context/manager.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
