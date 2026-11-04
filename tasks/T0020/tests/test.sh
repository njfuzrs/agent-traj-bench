#!/bin/bash
# T3 生成，勿手改。task=T0020
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
restore_pinned 'src/ui/derive-streaming-state.test.ts' '71957aa934eeddfb4865120201e473333ef927ed'
restore_pinned 'tests/tool/cron-create.test.ts' '1f8bee025350ab31080c8b284b897c163e9dc129'
restore_pinned 'tests/tool/diff-output.test.ts' 'c15c8a4d947a9b1d3da080af1fe69673852ca0b4'
restore_pinned 'tests/tool/edit.test.ts' '6d34e25d978616c58fb5cb25e305fd7673c5addd'
restore_pinned 'tests/tool/enter-plan-mode.test.ts' '3c4cbc493401c090a5a271003b5659f41021a030'
restore_pinned 'tests/tool/grep.test.ts' '1b9136b5aa65f15004805ff8db2cac5787606619'
restore_pinned 'tests/tool/input-validator.test.ts' '30d98ce770ee6f71f9933f33a9952b761458a5ff'
restore_pinned 'tests/tool/ls.test.ts' 'b159eccc20ae59dcd7956e9059356119559f4d95'
restore_pinned 'tests/tool/memory.test.ts' '1332e680a41ac5debf6eb42bbcee8094aa67f3e6'
restore_pinned 'tests/tool/omission-detector.test.ts' '906829dd226926ef57e3c9ceb614cb93c9bd4ccb'
restore_pinned 'tests/tool/path-utils.test.ts' '66aaeb3894e73b0935ed8e49d50d0fd1a64f8f22'
restore_pinned 'tests/tool/registry-modernization.test.ts' '437d057a89fa177248d047fe48b253a6b8ca8868'
restore_pinned 'tests/tool/ripgrep.test.ts' 'cb32dd0b402a83211c0213f2ab134641d0fadcb1'
restore_pinned 'tests/tool/schedule-wakeup.test.ts' '74e07ab01263cacf22b8f0b416b51e5c4ec95d6d'
restore_pinned 'tests/tool/todo-write.test.ts' 'be636ffa491af68f7dad26afd3e2454c19ea667e'
restore_pinned 'tests/tool/tool-search.test.ts' '18258c6bc75b07f2dba23b42ccfce00846a6ff48'
restore_pinned 'tests/tool/web-fetch.test.ts' '7485518c3b6232f23f0e058af50641755f41f6b3'
restore_pinned 'tests/ui/chord.test.ts' 'a6d70ffb2559055d3c1ede3fa5e4168ee54b56fd'
restore_pinned 'tests/ui/derive-streaming-state.test.ts' '1a13249fccf5df40694aa63bd904288b1501bdf3'
restore_pinned 'tests/ui/event-dispatcher.test.ts' '82b14d17dfb3f32f3f54e1a48ea446671c0e6bf6'
restore_pinned 'tests/ui/focus-manager.test.ts' 'a536c7e57b568ee75966a72eb78b10e9d7eb164b'
restore_pinned 'tests/ui/history-adapter.test.ts' 'be0f719c95a0580e459d84372dfa5b371015814a'
restore_pinned 'tests/ui/interaction-state-machine.test.ts' '7c7ef4900e4bef6abe6ac220b2b8c968df9ded26'
restore_pinned 'tests/ui/keybindings-full-coverage.test.ts' '94f0a57db8f7adc21cb1f0d624549392b9744082'
restore_pinned 'tests/ui/main-screen-layout.test.ts' 'f1b50f19aaeca8f139ca5e545ec7717129ca2422'
restore_pinned 'tests/ui/pasted-contents.test.ts' '691a18f05e470ffd8e054c500eae8e596b244059'
restore_pinned 'tests/ui/pending-input.test.ts' '522f184dcb1ed4a6a2dd84ddd1adc433d724328d'
restore_pinned 'tests/ui/scroll-quantum.test.ts' '8e5324cf99233693cf78319fe12bb8444b87e190'
restore_pinned 'tests/ui/status-line-data.test.ts' '1c0c61548e477417b0090b64dfb90e43de11b4d6'
restore_pinned 'tests/ui/status-line-effort.test.ts' 'addb7306838e4bf3634127feceec11babbd32197'
restore_pinned 'tests/ui/streaming-scroll.test.ts' 'a3fcb303dc0a23f7efef399d98452f2d576ef56d'
restore_pinned 'tests/ui/sync-output.test.ts' '191c858af7157e4db80ca365346eb09c6e8bfe5c'
rm -f 'tests/tool/ask-user-question.test.ts'

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
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'src/ui/derive-streaming-state.test.ts' 'tests/tool/ask-user-question.test.ts' 'tests/ui/derive-streaming-state.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/tool/omission-detector.test.ts' 'tests/ui/history-adapter.test.ts' 'tests/ui/keybindings-full-coverage.test.ts' 'tests/tool/tool-search.test.ts' 'tests/tool/todo-write.test.ts' 'tests/tool/web-fetch.test.ts' 'tests/tool/grep.test.ts' 'tests/tool/path-utils.test.ts' 'tests/ui/scroll-quantum.test.ts' 'tests/ui/chord.test.ts' 'tests/ui/focus-manager.test.ts' 'tests/ui/interaction-state-machine.test.ts' 'tests/ui/event-dispatcher.test.ts' 'tests/ui/status-line-data.test.ts' 'tests/tool/edit.test.ts' 'tests/ui/pending-input.test.ts' 'tests/ui/streaming-scroll.test.ts' 'tests/tool/ripgrep.test.ts' 'tests/ui/sync-output.test.ts' 'tests/tool/diff-output.test.ts' 'tests/tool/enter-plan-mode.test.ts' 'tests/ui/pasted-contents.test.ts' 'tests/tool/ls.test.ts' 'tests/tool/input-validator.test.ts' 'tests/tool/registry-modernization.test.ts' 'tests/ui/status-line-effort.test.ts' 'tests/tool/memory.test.ts' 'tests/tool/cron-create.test.ts' 'tests/tool/schedule-wakeup.test.ts' 'tests/ui/main-screen-layout.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
