#!/bin/bash
# T3 生成，勿手改。task=T0012
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
restore_pinned 'tests/query/backoff-abort.test.ts' '293e78b9741d9446479ca23441cc355dd0aba1a5'
restore_pinned 'tests/query/context-pressure.test.ts' '4900a9cdcb56b820f52e7ad4b6aa83c090fd2d4a'
restore_pinned 'tests/query/empty-param.test.ts' '6d276401b08799d53ccb8c7d5a2e3b28f0ada411'
restore_pinned 'tests/query/false-compaction-banner.test.ts' 'f07f22df439bae87a456a9d4c1105632963bdac3'
restore_pinned 'tests/query/hook-modified-notice.test.ts' 'd5f1b495bcfb51fa5425794b5d6dcbe9a6feffdb'
restore_pinned 'tests/query/human-input-gate.test.ts' '8f9b462ab8f2e3e6ae23a424ee5a40758e65e567'
restore_pinned 'tests/query/hypothesis-gaps.test.ts' '5b638f43c05954979df8dcdff27ed8de063afc1c'
restore_pinned 'tests/query/hypothesis-guide.test.ts' '16e9e968852c9865a68b0d1dd46f19e95b5bbfb5'
restore_pinned 'tests/query/hypothesis-ledger.test.ts' 'c88b37d1910a58ee809f88d3127ae6167e4b3b2b'
restore_pinned 'tests/query/message-queue-manager.test.ts' '71188e45997f6a35d95899fbffe4f5fed88ed653'
restore_pinned 'tests/query/negative-yield-defense-audit-fixes.test.ts' 'a82d8fe1f4f3496bf9c71f8288d579065c46ef10'
restore_pinned 'tests/query/output-stall.test.ts' 'c29476e7a4f59ef3ae236b13d5682b607abb6278'
restore_pinned 'tests/query/permission-reminder.test.ts' '024f98adb3d352aea27b7d245e71ce8a4f93bcfa'
restore_pinned 'tests/query/queue-priority-drain.test.ts' '72215979485317c90392ab0b3c0f2a6389f019e9'
restore_pinned 'tests/query/reactive-compact.test.ts' '6a711b1aac07c4256742be9839bdaa07718c96bd'
restore_pinned 'tests/query/reminder-inject-invariant.test.ts' '22ccf5fa3c9d7583cf1c0c61ea8ce3b7f317728f'
restore_pinned 'tests/query/reminder-inject.test.ts' 'ade5c6e5bc57485f2338c9ce703aa3469d69e2ef'
restore_pinned 'tests/query/reminder-throttle.test.ts' '864e2ff501c6c3495bffdd43abc91d3f7579db2f'
restore_pinned 'tests/query/repeated-readonly-guard.test.ts' '3ba6b597ca3b8879a4f0fe1423d4fd687f85d0b9'
restore_pinned 'tests/query/side-call-timeout.test.ts' 'edaee26aa1e8bcbe07e0b2bfdfc255f6960ab505'
restore_pinned 'tests/query/soft-turn-limit.test.ts' '3a8dcac60ed6fb71ec6f6399d732f07f32b86b1a'
restore_pinned 'tests/query/sparse-content-index.test.ts' 'bbd0f5dada1bb161bec41feb70f58b761bfab5c3'
restore_pinned 'tests/query/stream-processor-abort-isolation.test.ts' '2acae4c5f67fdbf94baaf9926b515af5b0cfd9a8'
restore_pinned 'tests/query/streaming-tool-executor.test.ts' '13d3115ff72c31f4c724894ba5ae7ea2a12d15ae'
restore_pinned 'tests/query/thinking-divergence.test.ts' 'fcf6892d0623d7028beb5d99c6ea648a1c4cc15c'
restore_pinned 'tests/query/todo-realtime-integration.test.ts' '74b8f2b4c4883b010238905cd80f25c490f45f22'
restore_pinned 'tests/query/todo-reminder-scan.test.ts' '0fdc41cbe30820dd5ab58f7c0d59c0b74b901120'
restore_pinned 'tests/query/todo-reminder.test.ts' '1415178e1edf8671f393a758ae33ccc9da8ed847'
restore_pinned 'tests/query/token-budget-continuation.test.ts' '62a3d7a2eae8583cc7b4d2479422031590efaf85'
restore_pinned 'tests/query/unanswered-end-turn.test.ts' 'd55d9841d4258960a9af2e1413b948c607da62fb'
rm -f 'tests/query/incremental-tool-settle.test.ts'

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
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/query/incremental-tool-settle.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/query/hypothesis-gaps.test.ts' 'tests/query/hypothesis-ledger.test.ts' 'tests/query/hypothesis-guide.test.ts' 'tests/query/empty-param.test.ts' 'tests/query/repeated-readonly-guard.test.ts' 'tests/query/message-queue-manager.test.ts' 'tests/query/reminder-inject.test.ts' 'tests/query/context-pressure.test.ts' 'tests/query/output-stall.test.ts' 'tests/query/negative-yield-defense-audit-fixes.test.ts' 'tests/query/permission-reminder.test.ts' 'tests/query/token-budget-continuation.test.ts' 'tests/query/todo-reminder-scan.test.ts' 'tests/query/hook-modified-notice.test.ts' 'tests/query/thinking-divergence.test.ts' 'tests/query/todo-reminder.test.ts' 'tests/query/queue-priority-drain.test.ts' 'tests/query/reactive-compact.test.ts' 'tests/query/todo-realtime-integration.test.ts' 'tests/query/reminder-throttle.test.ts' 'tests/query/unanswered-end-turn.test.ts' 'tests/query/soft-turn-limit.test.ts' 'tests/query/reminder-inject-invariant.test.ts' 'tests/query/side-call-timeout.test.ts' 'tests/query/stream-processor-abort-isolation.test.ts' 'tests/query/backoff-abort.test.ts' 'tests/query/human-input-gate.test.ts' 'tests/query/streaming-tool-executor.test.ts' 'tests/query/false-compaction-banner.test.ts' 'tests/query/sparse-content-index.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
