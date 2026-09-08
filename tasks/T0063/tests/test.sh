#!/bin/bash
# T3 生成，勿手改。task=T0063
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
git checkout -- 'tests/tool/path-utils.test.ts' 2>/dev/null || true
git checkout -- 'tests/permission/bash-security.test.ts' 2>/dev/null || true
git checkout -- 'tests/skill/code-review.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/ask-user-question.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/bash-background-reader.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/bash-cwd-tracking.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/cron-create.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/diff-output.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/edit.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/enter-plan-mode.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/exit-plan-mode.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/glob.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/grep.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/input-validator.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/lsp-gitignore-timeout.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/memory.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/omission-detector.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/read-tool.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/registry-modernization.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/registry.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/repro-snapshot-race.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/ripgrep.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/schedule-wakeup.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/todo-write.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/tool-search-auto.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/tool-search-scoring.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/tool-search.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/truncation-detector.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/web-fetch.test.ts' 2>/dev/null || true
git checkout -- 'tests/tool/write-guard.test.ts' 2>/dev/null || true
git checkout -- 'tests/trace/collector.test.ts' 2>/dev/null || true
# （本条 task 无 agent 可能新建的测试文件需删除）

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
bun test --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/tool/path-utils.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/tool/omission-detector.test.ts' 'tests/tool/read-tool.test.ts' 'tests/tool/tool-search-auto.test.ts' 'tests/tool/edit.test.ts' 'tests/tool/grep.test.ts' 'tests/tool/tool-search-scoring.test.ts' 'tests/tool/tool-search.test.ts' 'tests/tool/todo-write.test.ts' 'tests/tool/web-fetch.test.ts' 'tests/tool/ask-user-question.test.ts' 'tests/tool/glob.test.ts' 'tests/tool/truncation-detector.test.ts' 'tests/tool/ripgrep.test.ts' 'tests/tool/write-guard.test.ts' 'tests/tool/diff-output.test.ts' 'tests/tool/enter-plan-mode.test.ts' 'tests/tool/input-validator.test.ts' 'tests/tool/registry-modernization.test.ts' 'tests/tool/memory.test.ts' 'tests/tool/cron-create.test.ts' 'tests/tool/schedule-wakeup.test.ts' 'tests/tool/bash-cwd-tracking.test.ts' 'tests/tool/registry.test.ts' 'tests/tool/bash-background-reader.test.ts' 'tests/tool/exit-plan-mode.test.ts' 'tests/tool/lsp-gitignore-timeout.test.ts' 'tests/tool/repro-snapshot-race.test.ts' 'tests/skill/code-review.test.ts' 'tests/permission/bash-security.test.ts' 'tests/trace/collector.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
