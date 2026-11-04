#!/bin/bash
# T3 生成，勿手改。task=T0063
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
restore_pinned 'tests/permission/bash-security.test.ts' '0bee2f56752ebcfecd9312d82bf5272159477d72'
restore_pinned 'tests/skill/code-review.test.ts' '3c37b7dc506bde9442ff9c472aa08279ff9e230e'
restore_pinned 'tests/tool/ask-user-question.test.ts' '8930deeccbc93c566868ad5b36317fa7dbc2d5ab'
restore_pinned 'tests/tool/bash-background-reader.test.ts' '8091776f4e5c9fc9976411673270f27a921b8f5b'
restore_pinned 'tests/tool/bash-cwd-tracking.test.ts' '09f94f57be23711cd351047a891768803bc4a57f'
restore_pinned 'tests/tool/cron-create.test.ts' '1f8bee025350ab31080c8b284b897c163e9dc129'
restore_pinned 'tests/tool/diff-output.test.ts' 'c15c8a4d947a9b1d3da080af1fe69673852ca0b4'
restore_pinned 'tests/tool/edit.test.ts' '5b62e72c2a3628055d57eecc8679433b4bc99cf0'
restore_pinned 'tests/tool/enter-plan-mode.test.ts' '3c4cbc493401c090a5a271003b5659f41021a030'
restore_pinned 'tests/tool/exit-plan-mode.test.ts' 'b029247837b838c8024290642d25d1ebb30fcc4e'
restore_pinned 'tests/tool/glob.test.ts' 'c79228376e829b404d946fcb26c748a6ffdb5b49'
restore_pinned 'tests/tool/grep.test.ts' 'd7356f99c659866bdedc6c84b853aebff0408b74'
restore_pinned 'tests/tool/input-validator.test.ts' '30d98ce770ee6f71f9933f33a9952b761458a5ff'
restore_pinned 'tests/tool/lsp-gitignore-timeout.test.ts' '87c5b83f95eb96b2d2bb89fbcff1a8ab502b1e1b'
restore_pinned 'tests/tool/memory.test.ts' '1332e680a41ac5debf6eb42bbcee8094aa67f3e6'
restore_pinned 'tests/tool/omission-detector.test.ts' 'c4d35a8ad4532264dbe36bce3976391c43af9afa'
restore_pinned 'tests/tool/path-utils.test.ts' '66aaeb3894e73b0935ed8e49d50d0fd1a64f8f22'
restore_pinned 'tests/tool/read-tool.test.ts' 'a58bed7697765eb98129ccd237def5427a8b4d31'
restore_pinned 'tests/tool/registry-modernization.test.ts' '437d057a89fa177248d047fe48b253a6b8ca8868'
restore_pinned 'tests/tool/registry.test.ts' '078d768361a9c974e84a57a1335b57c134e17ed0'
restore_pinned 'tests/tool/repro-snapshot-race.test.ts' '999f8dabc40beaa0616ac08fca211dc24d689430'
restore_pinned 'tests/tool/ripgrep.test.ts' '4451e14c4887d86220cdce36e49ac06f9db058e3'
restore_pinned 'tests/tool/schedule-wakeup.test.ts' '74e07ab01263cacf22b8f0b416b51e5c4ec95d6d'
restore_pinned 'tests/tool/todo-write.test.ts' 'be636ffa491af68f7dad26afd3e2454c19ea667e'
restore_pinned 'tests/tool/tool-search-auto.test.ts' '536e0dcdde99e27087c28d00a63abb2d19411c52'
restore_pinned 'tests/tool/tool-search-scoring.test.ts' 'a4403055a0719d47739c13063d15fd9bd40a661a'
restore_pinned 'tests/tool/tool-search.test.ts' '18258c6bc75b07f2dba23b42ccfce00846a6ff48'
restore_pinned 'tests/tool/truncation-detector.test.ts' '031c1e72a65e8a38161af38cfbd629d843da7d40'
restore_pinned 'tests/tool/web-fetch.test.ts' '7485518c3b6232f23f0e058af50641755f41f6b3'
restore_pinned 'tests/tool/write-guard.test.ts' 'fecb19fbebb490f2302249f17e2eaa322e4db89f'
restore_pinned 'tests/trace/collector.test.ts' '6036ad33e48ed9183e5fdb5446448767ca75563c'
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
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/tool/path-utils.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/tool/omission-detector.test.ts' 'tests/tool/read-tool.test.ts' 'tests/tool/tool-search-auto.test.ts' 'tests/tool/edit.test.ts' 'tests/tool/grep.test.ts' 'tests/tool/tool-search-scoring.test.ts' 'tests/tool/tool-search.test.ts' 'tests/tool/todo-write.test.ts' 'tests/tool/web-fetch.test.ts' 'tests/tool/ask-user-question.test.ts' 'tests/tool/glob.test.ts' 'tests/tool/truncation-detector.test.ts' 'tests/tool/ripgrep.test.ts' 'tests/tool/write-guard.test.ts' 'tests/tool/diff-output.test.ts' 'tests/tool/enter-plan-mode.test.ts' 'tests/tool/input-validator.test.ts' 'tests/tool/registry-modernization.test.ts' 'tests/tool/memory.test.ts' 'tests/tool/cron-create.test.ts' 'tests/tool/schedule-wakeup.test.ts' 'tests/tool/bash-cwd-tracking.test.ts' 'tests/tool/registry.test.ts' 'tests/tool/bash-background-reader.test.ts' 'tests/tool/exit-plan-mode.test.ts' 'tests/tool/lsp-gitignore-timeout.test.ts' 'tests/tool/repro-snapshot-race.test.ts' 'tests/skill/code-review.test.ts' 'tests/permission/bash-security.test.ts' 'tests/trace/collector.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
