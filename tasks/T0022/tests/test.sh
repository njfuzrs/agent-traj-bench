#!/bin/bash
# T3 生成，勿手改。task=T0022
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
restore_pinned 'tests/config/attachments.test.ts' 'fc828e89f2bff0ad0ada332a8e5fa23dc5d721be'
restore_pinned 'tests/config/config.test.ts' '951fce29f328e766db59e03f2e729df792dee8da'
restore_pinned 'tests/config/network-profile.test.ts' 'c17a69fa06dae2809627fe405093dd0eb93bbb10'
restore_pinned 'tests/config/output-styles.test.ts' '390dd1294873dc79c9294437ed1a187e3fd1c663'
restore_pinned 'tests/config/rules-layered.test.ts' 'fb0b249f1b9fbe45d0b724be627847a854741049'
restore_pinned 'tests/config/rules.test.ts' 'b97e2d0b0068009be15e96a79146b4e772b67e89'
restore_pinned 'tests/config/schema.test.ts' '476d9b861e2a17a18c9ea5fd9b24129bbdfdc21f'
restore_pinned 'tests/config/settings.test.ts' '75287efe4f16687b35cbded1ba0581097158de74'
restore_pinned 'tests/config/system-prompt.test.ts' 'd10a50f9f53ddd66e7a52addb4971e8b703cdc51'
restore_pinned 'tests/config/token-utils.test.ts' '82a184c67621948cd7013fdd6e60ab2805b57339'
restore_pinned 'tests/permission/bash-classifier.test.ts' '5bbbab085195c65bafb903e6ea96e577f3456cb8'
restore_pinned 'tests/permission/bash-security.test.ts' '8b8b9ef6ed466bab1da35f10c0e34f9b3c2b7be8'
restore_pinned 'tests/permission/checker.test.ts' '362950f8984ded59185cc202ac6e59a9eb81cc1b'
restore_pinned 'tests/permission/deny-rules-visibility.test.ts' '25f28654a66b832ad8367f8800fbde1ed23feee9'
restore_pinned 'tests/permission/enhanced.test.ts' '751fc7a4e64e46cbfb6e557850b64b1a74fed3e7'
restore_pinned 'tests/permission/mode.test.ts' '3e9b5e62b88a44d4d67b8d9c233d2bc7fed79d05'
restore_pinned 'tests/permission/path-validator.test.ts' '3780c447557369a58762b782f444472b91f49b8f'
restore_pinned 'tests/permission/rule-loader.test.ts' '118fbfe00d768d61a037bb0bfb86af5144e43b6f'
restore_pinned 'tests/permission/rules.test.ts' '87563fadd28dcad169dab1155cc189764d827734'
restore_pinned 'tests/permission/sensitive.test.ts' '8a79f9b2e3c1b5329dd115eb272b3828bb4e4291'
restore_pinned 'tests/permission/shell-parser.test.ts' '8fe80041f43ffba9659441c2b1297a1379c059a6'
restore_pinned 'tests/ui/chord.test.ts' 'a6d70ffb2559055d3c1ede3fa5e4168ee54b56fd'
restore_pinned 'tests/ui/derive-streaming-state-priority.test.ts' '7dc6bd42d29f68e7f87b8f723d6a610e20850581'
restore_pinned 'tests/ui/event-dispatcher.test.ts' '82b14d17dfb3f32f3f54e1a48ea446671c0e6bf6'
restore_pinned 'tests/ui/focus-manager.test.ts' 'a536c7e57b568ee75966a72eb78b10e9d7eb164b'
restore_pinned 'tests/ui/history-adapter.test.ts' '740e6319eaf127c597ee3d79580e1e8197b46234'
restore_pinned 'tests/ui/interaction-state-machine.test.ts' '7c7ef4900e4bef6abe6ac220b2b8c968df9ded26'
restore_pinned 'tests/ui/keybindings-full-coverage.test.ts' '94f0a57db8f7adc21cb1f0d624549392b9744082'
restore_pinned 'tests/ui/pasted-contents.test.ts' '691a18f05e470ffd8e054c500eae8e596b244059'
restore_pinned 'tests/ui/pending-input.test.ts' '522f184dcb1ed4a6a2dd84ddd1adc433d724328d'
restore_pinned 'tests/ui/scroll-quantum.test.ts' '8e5324cf99233693cf78319fe12bb8444b87e190'
restore_pinned 'tests/ui/status-line-data.test.ts' '04ec803263866ae97893e937f90cc6c71def5710'
restore_pinned 'tests/ui/streaming-scroll.test.ts' 'a3fcb303dc0a23f7efef399d98452f2d576ef56d'
restore_pinned 'tests/ui/sync-output.test.ts' '191c858af7157e4db80ca365346eb09c6e8bfe5c'
rm -f 'tests/permission/mode-policy.test.ts'
rm -f 'tests/permission/path-rule-matching.test.ts'
rm -f 'tests/permission/rule-persistence.test.ts'
rm -f 'tests/permission/shell-rule-matching.test.ts'

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
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/config/schema.test.ts' 'tests/permission/mode-policy.test.ts' 'tests/permission/mode.test.ts' 'tests/permission/path-rule-matching.test.ts' 'tests/permission/rule-loader.test.ts' 'tests/permission/rule-persistence.test.ts' 'tests/permission/shell-rule-matching.test.ts' 'tests/ui/status-line-data.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/permission/bash-security.test.ts' 'tests/ui/history-adapter.test.ts' 'tests/permission/checker.test.ts' 'tests/permission/path-validator.test.ts' 'tests/config/system-prompt.test.ts' 'tests/ui/keybindings-full-coverage.test.ts' 'tests/permission/shell-parser.test.ts' 'tests/config/network-profile.test.ts' 'tests/config/settings.test.ts' 'tests/permission/sensitive.test.ts' 'tests/permission/enhanced.test.ts' 'tests/config/rules.test.ts' 'tests/ui/scroll-quantum.test.ts' 'tests/permission/bash-classifier.test.ts' 'tests/ui/chord.test.ts' 'tests/ui/focus-manager.test.ts' 'tests/permission/rules.test.ts' 'tests/ui/interaction-state-machine.test.ts' 'tests/config/token-utils.test.ts' 'tests/config/attachments.test.ts' 'tests/config/config.test.ts' 'tests/config/rules-layered.test.ts' 'tests/ui/event-dispatcher.test.ts' 'tests/ui/pending-input.test.ts' 'tests/ui/streaming-scroll.test.ts' 'tests/ui/sync-output.test.ts' 'tests/ui/pasted-contents.test.ts' 'tests/config/output-styles.test.ts' 'tests/permission/deny-rules-visibility.test.ts' 'tests/ui/derive-streaming-state-priority.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
