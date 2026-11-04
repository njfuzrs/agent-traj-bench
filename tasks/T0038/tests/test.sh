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
restore_pinned 'tests/config/attachments.test.ts' '4e8348502fec59f98f82ce9bbda1fc55132a5ea6'
restore_pinned 'tests/config/config.test.ts' '771410ae5a0d376f95b23473fe6a9603498d23aa'
restore_pinned 'tests/config/env-interpolation.test.ts' 'a32110767477c42dd95518c229d98c951f5a6f1a'
restore_pinned 'tests/config/env-sanitizer.test.ts' 'c2de8518a09be25ed15c37de12c01dc675895a17'
restore_pinned 'tests/config/import-processor.test.ts' '4c1a70de0590e665ff15a09a51aa636a1a36d04e'
restore_pinned 'tests/config/managed-env.test.ts' '45cc510557cf6466e077adbc49d15cf1b10fc4af'
restore_pinned 'tests/config/max-thinking-tokens-config.test.ts' '7c596bfc905e9ab402b4b3d56d30faf5b4f2ac00'
restore_pinned 'tests/config/max-tokens-recompute.test.ts' 'b461f9c1a440ba0826ffdeaa938a937fb7e2f243'
restore_pinned 'tests/config/network-profile.test.ts' 'c17a69fa06dae2809627fe405093dd0eb93bbb10'
restore_pinned 'tests/config/output-styles.test.ts' '390dd1294873dc79c9294437ed1a187e3fd1c663'
restore_pinned 'tests/config/patch-settings.test.ts' '51adc648b760de30380077f064466abfc66b8ec2'
restore_pinned 'tests/config/rules-layered.test.ts' '865b3783b0d45305658d03bfbb98ca13410e466a'
restore_pinned 'tests/config/rules.test.ts' 'b97e2d0b0068009be15e96a79146b4e772b67e89'
restore_pinned 'tests/config/schema.test.ts' '898240953195cf22178134f852d56eddcac5f9f2'
restore_pinned 'tests/config/settings.test.ts' '75287efe4f16687b35cbded1ba0581097158de74'
restore_pinned 'tests/config/system-prompt-cache-key.test.ts' '6c59d1c4d103c40b6b8fbb59232a0ab627ffb098'
restore_pinned 'tests/config/system-prompt.test.ts' '4d56b39331ec3305958d05fcbf3db6ab4ee47049'
restore_pinned 'tests/config/token-utils.test.ts' '82a184c67621948cd7013fdd6e60ab2805b57339'
restore_pinned 'tests/plan/executing-state.test.ts' 'cdd05c9f3063c14099ab62a06a541dabd241bd16'
restore_pinned 'tests/plan/fidelity.test.ts' 'a19d1783f58455093cb62efbfc6a2975cff5bd16'
restore_pinned 'tests/plan/prompt-recovery-section.test.ts' 'f8815baaca992a25100f95a2e437709aa3e1a5b6'
restore_pinned 'tests/plan/recovery.test.ts' 'ea1d6c8d807f8f509cd3da94e4dfceb9d234ea87'
restore_pinned 'tests/plan/spec18-optimizations.test.ts' 'f928777a40775598125a7b29b7696277e4532c7d'
restore_pinned 'tests/plan/state-update-count.test.ts' '3517c10d6bf9e4d7829f97028602385bee5e84fd'
restore_pinned 'tests/session/cache-usage.test.ts' '0c0d41a2e08406b943adfcc7c513e8ae16c00275'
restore_pinned 'tests/session/fork-session.test.ts' 'fbb535f00e12bfb3621406ce48d558244567e204'
restore_pinned 'tests/session/hypothesis-persistence.test.ts' 'eae5e74fd6d409b5ec883d3421f421dece3f3ea8'
restore_pinned 'tests/session/per-message-usage.test.ts' 'ae8db1a4c4ecee3a499018fe11c965f3c30d2ca6'
restore_pinned 'tests/session/persistence-features.test.ts' '5cb263e2f857dfeced3bf6ece995c5fc3ee6677d'
restore_pinned 'tests/session/rewind-manager.test.ts' '0c055b73332714def70da2967ac2984db6d9e963'
restore_pinned 'tests/session/store.test.ts' '42a9918876243c2f5fe7ae1ffcf588ad8572253d'
restore_pinned 'tests/session/todo-persistence.test.ts' '155fa715dd4025f6c2e27054e259af13772fb291'
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
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/config/attachments.test.ts' 'tests/config/dynamic-boundary-multiprovider.test.ts' 'tests/config/system-prompt.test.ts' 'tests/plan/plan-reminder-gate.test.ts' 'tests/session/reminder-dedup-reset.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/config/schema.test.ts' 'tests/plan/recovery.test.ts' 'tests/session/cache-usage.test.ts' 'tests/config/system-prompt-cache-key.test.ts' 'tests/plan/spec18-optimizations.test.ts' 'tests/config/network-profile.test.ts' 'tests/config/settings.test.ts' 'tests/config/rules-layered.test.ts' 'tests/config/rules.test.ts' 'tests/plan/fidelity.test.ts' 'tests/session/store.test.ts' 'tests/config/config.test.ts' 'tests/session/persistence-features.test.ts' 'tests/config/token-utils.test.ts' 'tests/session/rewind-manager.test.ts' 'tests/config/import-processor.test.ts' 'tests/session/hypothesis-persistence.test.ts' 'tests/session/todo-persistence.test.ts' 'tests/config/output-styles.test.ts' 'tests/session/fork-session.test.ts' 'tests/config/env-interpolation.test.ts' 'tests/config/env-sanitizer.test.ts' 'tests/plan/executing-state.test.ts' 'tests/plan/state-update-count.test.ts' 'tests/config/managed-env.test.ts' 'tests/config/max-thinking-tokens-config.test.ts' 'tests/config/max-tokens-recompute.test.ts' 'tests/config/patch-settings.test.ts' 'tests/session/per-message-usage.test.ts' 'tests/plan/prompt-recovery-section.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
