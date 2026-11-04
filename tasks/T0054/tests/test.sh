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
restore_pinned 'tests/command/adapter.test.ts' 'b723e23dcf11638c7062c670a39967eba88a5e35'
restore_pinned 'tests/command/alias-collision.test.ts' '86fe3f4af67cc1745b72c836acc8f36e1bef02f3'
restore_pinned 'tests/command/args.test.ts' '0f023ad148f3639360f59a4534199b3cb3496fe3'
restore_pinned 'tests/command/batch.test.ts' '823f1af69b063b690939d76bf38d231a8ce1539d'
restore_pinned 'tests/command/btw.test.ts' '4be9f14543c22e7789c75dcd35bd31f6af1c0695'
restore_pinned 'tests/command/clear-resets-cache-state.test.ts' '80a849b8559bde44235d5a2f6ab2facb4d807cb6'
restore_pinned 'tests/command/color.test.ts' '13280351619201ce0ff659e97d84dbfd5875a9e4'
restore_pinned 'tests/command/compact-focus.test.ts' 'a218ec238aaef51c4efad958c8684536b6e97a17'
restore_pinned 'tests/command/custom.test.ts' '187ff2964f91ad7401de4a81bc5bf2869eed8885'
restore_pinned 'tests/command/keybindings.test.ts' 'db556ad270fed1b36a9a87bdbde95eb262fbb59c'
restore_pinned 'tests/command/mid-input.test.ts' '4691069195ccf945ea61f58a1ba1c3909e03d681'
restore_pinned 'tests/command/model.test.ts' '8da34d58750539f2c4b7d919d965816c0a28123f'
restore_pinned 'tests/command/parser.test.ts' '36fd12628e091520a23e7d40429e7f7221b59115'
restore_pinned 'tests/command/plugin-commands.test.ts' '28e8326228d2edecfb8ffa295c631cdcff7017cc'
restore_pinned 'tests/command/queue.test.ts' 'a3da0daa6c91b11354f47e7511f92be7e99fba2b'
restore_pinned 'tests/command/registry.test.ts' '8a0f2956c4f8781d3efdb3ba2c184c1b7036459a'
restore_pinned 'tests/command/review.test.ts' 'fe6ff822a25ca460a10071d812f3c7106089990e'
restore_pinned 'tests/command/self-check.test.ts' '67cea67deb7a7a9a2db282a158bf1191fa07351d'
restore_pinned 'tests/command/skill-command-adapter.test.ts' 'f34a514ff74493aadb60e63b9e9e5b1a73ccc47e'
restore_pinned 'tests/command/status.test.ts' 'bc442812ddbfc82dcc67c62bfb19be79768723b1'
restore_pinned 'tests/command/statusline.test.ts' '5add0b0f01b42e3c0bf3b252912b39caa8eac83f'
restore_pinned 'tests/command/suggestions.test.ts' '73051bca3db1ca0356073fb8874f51324005f23d'
restore_pinned 'tests/command/terminal-setup.test.ts' '252913853d5d205d1ec00f9cc4c0173b830cea64'
restore_pinned 'tests/command/todos.test.ts' '260fe7a0380dbb743eafca46f4573b0df965b9f5'
restore_pinned 'tests/command/tui-fast.test.ts' 'df3646b6458de7afe9ef4d41e257598312d9993a'
restore_pinned 'tests/command/unified-registry.test.ts' '167b1f3c3238a7ed6a38f287bb2f3619bde3f132'
restore_pinned 'tests/command/update.test.ts' 'fcbb0e7c98a8bcb54cb9913cae6526edbfd23eeb'
restore_pinned 'tests/command/usage-tracking.test.ts' '041eb442cd60215f54fb18ff067daea9f4d45ffd'
restore_pinned 'tests/command/vim.test.ts' 'a4a7eeb5bcb64148d6e3accd02af72ff0fa2d442'
restore_pinned 'tests/command/workflows.test.ts' 'b238a85c993e278295b2e737907b5748cc54e02e'
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
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/command/language-dialog.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/command/custom.test.ts' 'tests/command/registry.test.ts' 'tests/command/args.test.ts' 'tests/command/compact-focus.test.ts' 'tests/command/review.test.ts' 'tests/command/terminal-setup.test.ts' 'tests/command/model.test.ts' 'tests/command/parser.test.ts' 'tests/command/statusline.test.ts' 'tests/command/suggestions.test.ts' 'tests/command/adapter.test.ts' 'tests/command/queue.test.ts' 'tests/command/skill-command-adapter.test.ts' 'tests/command/unified-registry.test.ts' 'tests/command/update.test.ts' 'tests/command/clear-resets-cache-state.test.ts' 'tests/command/color.test.ts' 'tests/command/mid-input.test.ts' 'tests/command/tui-fast.test.ts' 'tests/command/btw.test.ts' 'tests/command/plugin-commands.test.ts' 'tests/command/self-check.test.ts' 'tests/command/usage-tracking.test.ts' 'tests/command/vim.test.ts' 'tests/command/workflows.test.ts' 'tests/command/todos.test.ts' 'tests/command/keybindings.test.ts' 'tests/command/status.test.ts' 'tests/command/alias-collision.test.ts' 'tests/command/batch.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
