#!/bin/bash
# T3 生成，勿手改。task=T0054
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
git checkout -- 'tests/command/adapter.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/alias-collision.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/args.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/batch.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/btw.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/clear-resets-cache-state.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/color.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/compact-focus.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/custom.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/keybindings.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/mid-input.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/model.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/parser.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/plugin-commands.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/queue.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/registry.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/review.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/self-check.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/skill-command-adapter.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/status.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/statusline.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/suggestions.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/terminal-setup.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/todos.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/tui-fast.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/unified-registry.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/update.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/usage-tracking.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/vim.test.ts' 2>/dev/null || true
git checkout -- 'tests/command/workflows.test.ts' 2>/dev/null || true
rm -f 'tests/command/language-dialog.test.ts'

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
bun test --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/command/language-dialog.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/command/custom.test.ts' 'tests/command/registry.test.ts' 'tests/command/args.test.ts' 'tests/command/compact-focus.test.ts' 'tests/command/review.test.ts' 'tests/command/terminal-setup.test.ts' 'tests/command/model.test.ts' 'tests/command/parser.test.ts' 'tests/command/statusline.test.ts' 'tests/command/suggestions.test.ts' 'tests/command/adapter.test.ts' 'tests/command/queue.test.ts' 'tests/command/skill-command-adapter.test.ts' 'tests/command/unified-registry.test.ts' 'tests/command/update.test.ts' 'tests/command/clear-resets-cache-state.test.ts' 'tests/command/color.test.ts' 'tests/command/mid-input.test.ts' 'tests/command/tui-fast.test.ts' 'tests/command/btw.test.ts' 'tests/command/plugin-commands.test.ts' 'tests/command/self-check.test.ts' 'tests/command/usage-tracking.test.ts' 'tests/command/vim.test.ts' 'tests/command/workflows.test.ts' 'tests/command/todos.test.ts' 'tests/command/keybindings.test.ts' 'tests/command/status.test.ts' 'tests/command/alias-collision.test.ts' 'tests/command/batch.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
