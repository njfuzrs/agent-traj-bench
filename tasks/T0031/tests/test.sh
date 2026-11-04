#!/bin/bash
# T3 生成，勿手改。task=T0031
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
restore_pinned 'tests/agent/loop-detection.test.ts' '1dbbd2b599a42257a2c7483883217d0fc18c2284'
restore_pinned 'tests/llm/effort.test.ts' 'ab5bfc47682d5a810e647c154fb85a2a1bec8af4'
restore_pinned 'tests/llm/errors.test.ts' 'bf04fc73d256ab3b0675113bf2134de18fc566d3'
restore_pinned 'tests/permission/path-validator.test.ts' '3780c447557369a58762b782f444472b91f49b8f'
restore_pinned 'tests/skill/ci-self-heal.test.ts' 'b897c1904b3742a85854799441339c8cd4e6f18d'
restore_pinned 'tests/skill/code-review.test.ts' '3c37b7dc506bde9442ff9c472aa08279ff9e230e'
restore_pinned 'tests/skill/security-audit-scripts.test.ts' 'e78ca963643b6ad3875acbfd42205d3ea21cc991'
restore_pinned 'tests/tool/bash-cwd-tracking.test.ts' '09f94f57be23711cd351047a891768803bc4a57f'
restore_pinned 'tests/tool/cron-create.test.ts' '1f8bee025350ab31080c8b284b897c163e9dc129'
restore_pinned 'tests/tool/diff-output.test.ts' 'c15c8a4d947a9b1d3da080af1fe69673852ca0b4'
restore_pinned 'tests/tool/edit.test.ts' '6d34e25d978616c58fb5cb25e305fd7673c5addd'
restore_pinned 'tests/tool/enter-plan-mode.test.ts' '3c4cbc493401c090a5a271003b5659f41021a030'
restore_pinned 'tests/tool/exit-plan-mode.test.ts' 'b029247837b838c8024290642d25d1ebb30fcc4e'
restore_pinned 'tests/tool/grep.test.ts' '1b9136b5aa65f15004805ff8db2cac5787606619'
restore_pinned 'tests/tool/input-validator.test.ts' '30d98ce770ee6f71f9933f33a9952b761458a5ff'
restore_pinned 'tests/tool/ls.test.ts' 'b159eccc20ae59dcd7956e9059356119559f4d95'
restore_pinned 'tests/tool/memory.test.ts' '1332e680a41ac5debf6eb42bbcee8094aa67f3e6'
restore_pinned 'tests/tool/omission-detector.test.ts' '906829dd226926ef57e3c9ceb614cb93c9bd4ccb'
restore_pinned 'tests/tool/path-utils.test.ts' '66aaeb3894e73b0935ed8e49d50d0fd1a64f8f22'
restore_pinned 'tests/tool/registry-modernization.test.ts' '437d057a89fa177248d047fe48b253a6b8ca8868'
restore_pinned 'tests/tool/registry.test.ts' '078d768361a9c974e84a57a1335b57c134e17ed0'
restore_pinned 'tests/tool/repro-snapshot-race.test.ts' '999f8dabc40beaa0616ac08fca211dc24d689430'
restore_pinned 'tests/tool/ripgrep.test.ts' 'cb32dd0b402a83211c0213f2ab134641d0fadcb1'
restore_pinned 'tests/tool/schedule-wakeup.test.ts' '74e07ab01263cacf22b8f0b416b51e5c4ec95d6d'
restore_pinned 'tests/tool/todo-write.test.ts' 'be636ffa491af68f7dad26afd3e2454c19ea667e'
restore_pinned 'tests/tool/tool-search.test.ts' '18258c6bc75b07f2dba23b42ccfce00846a6ff48'
restore_pinned 'tests/tool/web-fetch.test.ts' '7485518c3b6232f23f0e058af50641755f41f6b3'
restore_pinned 'tests/trace/builder.test.ts' '40b88170d111695d745f9ba4aec6bc44f2aa3cef'
restore_pinned 'tests/trace/collector.test.ts' 'd2de3b35ba757c1d955fba54936be11f0b2c2339'
restore_pinned 'tests/workflow/sandbox.test.ts' '69247565076918856e8b9556fe21005afb4405da'
rm -f 'tests/tool/tool-search-auto.test.ts'
rm -f 'tests/tool/tool-search-scoring.test.ts'

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
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/tool/tool-search-auto.test.ts' 'tests/tool/tool-search-scoring.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/tool/omission-detector.test.ts' 'tests/tool/tool-search.test.ts' 'tests/tool/todo-write.test.ts' 'tests/tool/web-fetch.test.ts' 'tests/tool/grep.test.ts' 'tests/tool/path-utils.test.ts' 'tests/tool/edit.test.ts' 'tests/tool/ripgrep.test.ts' 'tests/tool/diff-output.test.ts' 'tests/tool/enter-plan-mode.test.ts' 'tests/tool/ls.test.ts' 'tests/tool/input-validator.test.ts' 'tests/tool/registry-modernization.test.ts' 'tests/tool/memory.test.ts' 'tests/tool/cron-create.test.ts' 'tests/tool/schedule-wakeup.test.ts' 'tests/tool/bash-cwd-tracking.test.ts' 'tests/tool/registry.test.ts' 'tests/tool/exit-plan-mode.test.ts' 'tests/tool/repro-snapshot-race.test.ts' 'tests/skill/code-review.test.ts' 'tests/trace/collector.test.ts' 'tests/skill/ci-self-heal.test.ts' 'tests/agent/loop-detection.test.ts' 'tests/llm/errors.test.ts' 'tests/llm/effort.test.ts' 'tests/skill/security-audit-scripts.test.ts' 'tests/permission/path-validator.test.ts' 'tests/workflow/sandbox.test.ts' 'tests/trace/builder.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
