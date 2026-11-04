#!/bin/bash
# T3 生成，勿手改。task=T0003
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
restore_pinned 'tests/agent/loop-detection.test.ts' '5bd2ab71a2cd62bf858546c4664a907a6ebfa257'
restore_pinned 'tests/config/system-prompt.test.ts' 'd10a50f9f53ddd66e7a52addb4971e8b703cdc51'
restore_pinned 'tests/context/manager.test.ts' '4b56c7dbed67564ac198c2a8ec327e8e33375bbe'
restore_pinned 'tests/ide/integration.test.ts' '5368540244b89f76a3f705dfbdce35edb1bf7782'
restore_pinned 'tests/llm/effort.test.ts' '782ef969b124c862563c701b74a4e45b9d831e1d'
restore_pinned 'tests/llm/errors.test.ts' '78adffa364f15aeb964a149095a43f1d03876377'
restore_pinned 'tests/llm/fallback.test.ts' '1a5464ae4a641bbc14666357169c6c3f16517c91'
restore_pinned 'tests/llm/openai-protocol-edge.test.ts' '05743bd6ea2381ba221fd8d60711305e1fe7c302'
restore_pinned 'tests/memory/team/paths.test.ts' 'd5f855bf3c6fe93e7a45af77d275d28b2f6a5361'
restore_pinned 'tests/memory/team/secret-guard.test.ts' '2b805a4bed2158ef397a04990f998c931a5a37ad'
restore_pinned 'tests/memory/team/secret-scanner.test.ts' '3d51a2fc5780448917f7646cbba7f00c550f6515'
restore_pinned 'tests/memory/team/store.test.ts' '6ec58115b6016a8e71043fbb95394ea5c1976500'
restore_pinned 'tests/memory/team/sync.test.ts' 'd022648016949b0ef78b04e6ff3c4171c3a00d4e'
restore_pinned 'tests/memory/team/watcher.test.ts' '1f3018a4a711a9324a68a7cea25d67e6b1e9af48'
restore_pinned 'tests/permission/bash-security.test.ts' '8b8b9ef6ed466bab1da35f10c0e34f9b3c2b7be8'
restore_pinned 'tests/permission/checker.test.ts' '362950f8984ded59185cc202ac6e59a9eb81cc1b'
restore_pinned 'tests/permission/path-validator.test.ts' '3780c447557369a58762b782f444472b91f49b8f'
restore_pinned 'tests/query/empty-param.test.ts' '6d276401b08799d53ccb8c7d5a2e3b28f0ada411'
restore_pinned 'tests/skill/ci-self-heal.test.ts' 'b897c1904b3742a85854799441339c8cd4e6f18d'
restore_pinned 'tests/skill/code-review.test.ts' '3c37b7dc506bde9442ff9c472aa08279ff9e230e'
restore_pinned 'tests/skill/security-audit-scripts.test.ts' 'e78ca963643b6ad3875acbfd42205d3ea21cc991'
restore_pinned 'tests/tool/omission-detector.test.ts' 'b0fb5707410b8c4b404159cf09de4ad483f8e4b8'
restore_pinned 'tests/tool/read-tool.test.ts' '0f606907f8c9da6e4688470faeeb38d838db77c0'
restore_pinned 'tests/tool/web-fetch.test.ts' '7e037158a4feea42e84ebbabfa7234252b1775e8'
restore_pinned 'tests/trace/builder.test.ts' 'c8ede8326abb1822def2846c6c3526db454c4f5b'
restore_pinned 'tests/trace/collector.test.ts' 'c9510574a5b678acd181c830009c43454469aace'
restore_pinned 'tests/trace/digest.test.ts' '4fb6632a34e7ce9d0e50da8da01f3a74bb35f34d'
restore_pinned 'tests/ui/history-adapter.test.ts' '1560b6d0ff66356417c8df1836c06e9b85bece36'
restore_pinned 'tests/ui/keybindings-full-coverage.test.ts' '94f0a57db8f7adc21cb1f0d624549392b9744082'
restore_pinned 'tests/ui/vim-state-machine.test.ts' '7d408512e550d261ee7a9c3287fe7c8d29d84c02'
restore_pinned 'tests/workflow/sandbox.test.ts' '69247565076918856e8b9556fe21005afb4405da'
rm -f 'tests/ide/context-delta.test.ts'

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
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/ide/context-delta.test.ts' 'tests/memory/team/sync.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/ide/integration.test.ts' 'tests/memory/team/secret-scanner.test.ts' 'tests/memory/team/watcher.test.ts' 'tests/memory/team/paths.test.ts' 'tests/memory/team/store.test.ts' 'tests/memory/team/secret-guard.test.ts' 'tests/skill/code-review.test.ts' 'tests/permission/bash-security.test.ts' 'tests/trace/collector.test.ts' 'tests/llm/errors.test.ts' 'tests/tool/omission-detector.test.ts' 'tests/llm/effort.test.ts' 'tests/ui/keybindings-full-coverage.test.ts' 'tests/ui/history-adapter.test.ts' 'tests/agent/loop-detection.test.ts' 'tests/llm/fallback.test.ts' 'tests/skill/ci-self-heal.test.ts' 'tests/tool/read-tool.test.ts' 'tests/llm/openai-protocol-edge.test.ts' 'tests/permission/checker.test.ts' 'tests/tool/web-fetch.test.ts' 'tests/ui/vim-state-machine.test.ts' 'tests/skill/security-audit-scripts.test.ts' 'tests/permission/path-validator.test.ts' 'tests/context/manager.test.ts' 'tests/trace/builder.test.ts' 'tests/query/empty-param.test.ts' 'tests/trace/digest.test.ts' 'tests/config/system-prompt.test.ts' 'tests/workflow/sandbox.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
