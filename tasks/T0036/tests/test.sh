#!/bin/bash
# T3 生成，勿手改。task=T0036
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
restore_pinned 'src/ui/derive-streaming-state.test.ts' '7c2e847690565004938569329b14778ad1f7bee1'
restore_pinned 'tests/agent/loop-detection.test.ts' '1dbbd2b599a42257a2c7483883217d0fc18c2284'
restore_pinned 'tests/llm/effort.test.ts' 'ab5bfc47682d5a810e647c154fb85a2a1bec8af4'
restore_pinned 'tests/llm/errors.test.ts' 'bf04fc73d256ab3b0675113bf2134de18fc566d3'
restore_pinned 'tests/permission/bash-security.test.ts' '0bee2f56752ebcfecd9312d82bf5272159477d72'
restore_pinned 'tests/skill/ci-self-heal.test.ts' 'b897c1904b3742a85854799441339c8cd4e6f18d'
restore_pinned 'tests/skill/code-review.test.ts' '3c37b7dc506bde9442ff9c472aa08279ff9e230e'
restore_pinned 'tests/skill/security-audit-scripts.test.ts' 'e78ca963643b6ad3875acbfd42205d3ea21cc991'
restore_pinned 'tests/task/agent-task-terminal-guard.test.ts' '5f9d335b2a2d5050497b0bcaf173a5e4f34bedf2'
restore_pinned 'tests/task/clear-inactive-tasks.test.ts' 'b854b4ec09489b0e119ed550189d66c892e07549'
restore_pinned 'tests/task/evict-terminal-tasks.test.ts' 'd55c7fdf54e04e49d59ea52c656d69b1c938b67a'
restore_pinned 'tests/tool/omission-detector.test.ts' '906829dd226926ef57e3c9ceb614cb93c9bd4ccb'
restore_pinned 'tests/trace/collector.test.ts' 'd2de3b35ba757c1d955fba54936be11f0b2c2339'
restore_pinned 'tests/ui/accessibility-detect.test.ts' '84fc33c4c2529676de7d35c9df83367119195ffd'
restore_pinned 'tests/ui/chord.test.ts' 'a6d70ffb2559055d3c1ede3fa5e4168ee54b56fd'
restore_pinned 'tests/ui/derive-streaming-state.test.ts' '1787a68ff51b7e0cfd8d90ced394d81b72814bc0'
restore_pinned 'tests/ui/event-dispatcher.test.ts' '82b14d17dfb3f32f3f54e1a48ea446671c0e6bf6'
restore_pinned 'tests/ui/focus-manager.test.ts' 'a536c7e57b568ee75966a72eb78b10e9d7eb164b'
restore_pinned 'tests/ui/history-adapter.test.ts' 'be0f719c95a0580e459d84372dfa5b371015814a'
restore_pinned 'tests/ui/interaction-state-machine.test.ts' '7c7ef4900e4bef6abe6ac220b2b8c968df9ded26'
restore_pinned 'tests/ui/keybindings-full-coverage.test.ts' '94f0a57db8f7adc21cb1f0d624549392b9744082'
restore_pinned 'tests/ui/main-screen-layout.test.ts' 'f1b50f19aaeca8f139ca5e545ec7717129ca2422'
restore_pinned 'tests/ui/pasted-contents.test.ts' '691a18f05e470ffd8e054c500eae8e596b244059'
restore_pinned 'tests/ui/pending-input.test.ts' '522f184dcb1ed4a6a2dd84ddd1adc433d724328d'
restore_pinned 'tests/ui/scroll-quantum.test.ts' '8e5324cf99233693cf78319fe12bb8444b87e190'
restore_pinned 'tests/ui/state-bridge.test.ts' '1adfc80b12d8b5e5744fd4ad9d4fe70be78d0b83'
restore_pinned 'tests/ui/status-line-data.test.ts' '1c0c61548e477417b0090b64dfb90e43de11b4d6'
restore_pinned 'tests/ui/status-line-effort.test.ts' 'addb7306838e4bf3634127feceec11babbd32197'
restore_pinned 'tests/ui/streaming-scroll.test.ts' 'a3fcb303dc0a23f7efef399d98452f2d576ef56d'
restore_pinned 'tests/ui/sync-output.test.ts' '191c858af7157e4db80ca365346eb09c6e8bfe5c'
restore_pinned 'tests/ui/ui-utils.test.ts' 'af4cd31f7a3d606b48e4e561da02f36dfc4413f8'
rm -f 'tests/task/notification-truncate.test.ts'

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
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/task/notification-truncate.test.ts' 'tests/ui/history-adapter.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/ui/keybindings-full-coverage.test.ts' 'tests/ui/scroll-quantum.test.ts' 'tests/ui/chord.test.ts' 'tests/ui/focus-manager.test.ts' 'tests/ui/interaction-state-machine.test.ts' 'tests/ui/event-dispatcher.test.ts' 'tests/ui/status-line-data.test.ts' 'tests/ui/pending-input.test.ts' 'tests/ui/streaming-scroll.test.ts' 'tests/ui/sync-output.test.ts' 'tests/ui/pasted-contents.test.ts' 'src/ui/derive-streaming-state.test.ts' 'tests/ui/derive-streaming-state.test.ts' 'tests/ui/status-line-effort.test.ts' 'tests/task/evict-terminal-tasks.test.ts' 'tests/task/agent-task-terminal-guard.test.ts' 'tests/ui/main-screen-layout.test.ts' 'tests/task/clear-inactive-tasks.test.ts' 'tests/ui/accessibility-detect.test.ts' 'tests/ui/ui-utils.test.ts' 'tests/ui/state-bridge.test.ts' 'tests/skill/code-review.test.ts' 'tests/permission/bash-security.test.ts' 'tests/trace/collector.test.ts' 'tests/tool/omission-detector.test.ts' 'tests/skill/ci-self-heal.test.ts' 'tests/agent/loop-detection.test.ts' 'tests/llm/errors.test.ts' 'tests/llm/effort.test.ts' 'tests/skill/security-audit-scripts.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
