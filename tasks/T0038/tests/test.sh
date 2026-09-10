#!/bin/bash
# T3 生成，勿手改。task=T0038
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
git checkout -- 'tests/config/attachments.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/system-prompt.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/config.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/env-interpolation.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/env-sanitizer.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/import-processor.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/managed-env.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/max-thinking-tokens-config.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/max-tokens-recompute.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/network-profile.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/output-styles.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/patch-settings.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/rules-layered.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/rules.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/schema.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/settings.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/system-prompt-cache-key.test.ts' 2>/dev/null || true
git checkout -- 'tests/config/token-utils.test.ts' 2>/dev/null || true
git checkout -- 'tests/plan/executing-state.test.ts' 2>/dev/null || true
git checkout -- 'tests/plan/fidelity.test.ts' 2>/dev/null || true
git checkout -- 'tests/plan/prompt-recovery-section.test.ts' 2>/dev/null || true
git checkout -- 'tests/plan/recovery.test.ts' 2>/dev/null || true
git checkout -- 'tests/plan/spec18-optimizations.test.ts' 2>/dev/null || true
git checkout -- 'tests/plan/state-update-count.test.ts' 2>/dev/null || true
git checkout -- 'tests/session/cache-usage.test.ts' 2>/dev/null || true
git checkout -- 'tests/session/fork-session.test.ts' 2>/dev/null || true
git checkout -- 'tests/session/hypothesis-persistence.test.ts' 2>/dev/null || true
git checkout -- 'tests/session/per-message-usage.test.ts' 2>/dev/null || true
git checkout -- 'tests/session/persistence-features.test.ts' 2>/dev/null || true
git checkout -- 'tests/session/rewind-manager.test.ts' 2>/dev/null || true
git checkout -- 'tests/session/store.test.ts' 2>/dev/null || true
git checkout -- 'tests/session/todo-persistence.test.ts' 2>/dev/null || true
rm -f 'tests/config/dynamic-boundary-multiprovider.test.ts'
rm -f 'tests/plan/plan-reminder-gate.test.ts'
rm -f 'tests/session/reminder-dedup-reset.test.ts'

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
bun test --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/config/attachments.test.ts' 'tests/config/dynamic-boundary-multiprovider.test.ts' 'tests/config/system-prompt.test.ts' 'tests/plan/plan-reminder-gate.test.ts' 'tests/session/reminder-dedup-reset.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/config/schema.test.ts' 'tests/plan/recovery.test.ts' 'tests/session/cache-usage.test.ts' 'tests/config/system-prompt-cache-key.test.ts' 'tests/plan/spec18-optimizations.test.ts' 'tests/config/network-profile.test.ts' 'tests/config/settings.test.ts' 'tests/config/rules-layered.test.ts' 'tests/config/rules.test.ts' 'tests/plan/fidelity.test.ts' 'tests/session/store.test.ts' 'tests/config/config.test.ts' 'tests/session/persistence-features.test.ts' 'tests/config/token-utils.test.ts' 'tests/session/rewind-manager.test.ts' 'tests/config/import-processor.test.ts' 'tests/session/hypothesis-persistence.test.ts' 'tests/session/todo-persistence.test.ts' 'tests/config/output-styles.test.ts' 'tests/session/fork-session.test.ts' 'tests/config/env-interpolation.test.ts' 'tests/config/env-sanitizer.test.ts' 'tests/plan/executing-state.test.ts' 'tests/plan/state-update-count.test.ts' 'tests/config/managed-env.test.ts' 'tests/config/max-thinking-tokens-config.test.ts' 'tests/config/max-tokens-recompute.test.ts' 'tests/config/patch-settings.test.ts' 'tests/session/per-message-usage.test.ts' 'tests/plan/prompt-recovery-section.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
