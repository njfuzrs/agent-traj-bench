#!/bin/bash
# T3 生成，勿手改。task=T0033
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
restore_pinned 'tests/api/errors.test.ts' '08ea5de410d864635a8659b0b1b4015670d82994'
restore_pinned 'tests/llm/effort.test.ts' 'ab5bfc47682d5a810e647c154fb85a2a1bec8af4'
restore_pinned 'tests/llm/errors.test.ts' 'd49a413d6c544d724a47a673a592186f3a14d065'
restore_pinned 'tests/llm/fallback.test.ts' 'f95d46f91bbe22b167df6fd769ca493c7f54bc5e'
restore_pinned 'tests/llm/openai-protocol-edge.test.ts' 'c2019424270a7879022a20784fef3568634d86cc'
restore_pinned 'tests/permission/bash-security.test.ts' '0bee2f56752ebcfecd9312d82bf5272159477d72'
restore_pinned 'tests/permission/path-validator.test.ts' '3780c447557369a58762b782f444472b91f49b8f'
restore_pinned 'tests/query/empty-param.test.ts' '2ddb8cd12a23358ab8355b798dc2cfe418e868df'
restore_pinned 'tests/query/hypothesis-guide.test.ts' '549842d08158406a60d5d33cb537d45714b0cf92'
restore_pinned 'tests/skill/ci-self-heal.test.ts' 'b897c1904b3742a85854799441339c8cd4e6f18d'
restore_pinned 'tests/skill/code-review.test.ts' '3c37b7dc506bde9442ff9c472aa08279ff9e230e'
restore_pinned 'tests/skill/security-audit-scripts.test.ts' 'e78ca963643b6ad3875acbfd42205d3ea21cc991'
restore_pinned 'tests/telemetry/cost-attribution.test.ts' '91e9c418ce674f3d44532bff03e371ca46fce9bb'
restore_pinned 'tests/telemetry/hook-probe.test.ts' '577379bbb32e1585ec75ce1a1d20521a3a1b76a8'
restore_pinned 'tests/telemetry/telemetry.test.ts' 'c88899fc2c999d3c5aa94c4490faddb869266b58'
restore_pinned 'tests/telemetry/tracing-enhanced.test.ts' '288e2a90d57c9598387ca50177bb964c2eca23d3'
restore_pinned 'tests/telemetry/usage-ledger.test.ts' '77a4a7a91eeafc68ed9e6ed7e89c35b6f8b15381'
restore_pinned 'tests/tool/omission-detector.test.ts' '906829dd226926ef57e3c9ceb614cb93c9bd4ccb'
restore_pinned 'tests/trace/builder.test.ts' '51c9b9f5904b9615b728d30acac57e0c7384f996'
restore_pinned 'tests/trace/collector.test.ts' '6036ad33e48ed9183e5fdb5446448767ca75563c'
restore_pinned 'tests/trace/cost-recompute.test.ts' '9f18993bd81b5da850dbd8b1736f22a6a251b065'
restore_pinned 'tests/trace/crash-marker.test.ts' '10cb90e03d229f06570ee582536e921b7111c3c4'
restore_pinned 'tests/trace/digest.test.ts' 'ff753cb3911301fb7be0f6200354b54fa374a371'
restore_pinned 'tests/trace/pid-manager.test.ts' '403c60863de44b5069e7650646e01e91c8d4e3c7'
restore_pinned 'tests/trace/stream-observer.test.ts' '361b98781c130784a735ee75839ce2d214d5cdd7'
restore_pinned 'tests/trace/uploader.test.ts' '6ee4d1a791437c2793d0d123905ddcf363fa9367'
restore_pinned 'tests/trace/writer.test.ts' '615d634e0dda2f2c667005ef3ef0954b45d9916d'
restore_pinned 'tests/ui/history-adapter.test.ts' '39410da0bad3d160ba31c5019c87a9eb4cb30489'
restore_pinned 'tests/workflow/sandbox.test.ts' '69247565076918856e8b9556fe21005afb4405da'
rm -f 'tests/telemetry/provider-health.test.ts'
rm -f 'tests/trace/retry-telemetry-sink.test.ts'

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
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/telemetry/provider-health.test.ts' 'tests/trace/retry-telemetry-sink.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/trace/collector.test.ts' 'tests/trace/builder.test.ts' 'tests/trace/uploader.test.ts' 'tests/trace/digest.test.ts' 'tests/telemetry/cost-attribution.test.ts' 'tests/telemetry/hook-probe.test.ts' 'tests/telemetry/telemetry.test.ts' 'tests/telemetry/usage-ledger.test.ts' 'tests/trace/writer.test.ts' 'tests/telemetry/tracing-enhanced.test.ts' 'tests/trace/cost-recompute.test.ts' 'tests/trace/pid-manager.test.ts' 'tests/trace/crash-marker.test.ts' 'tests/trace/stream-observer.test.ts' 'tests/skill/code-review.test.ts' 'tests/permission/bash-security.test.ts' 'tests/tool/omission-detector.test.ts' 'tests/skill/ci-self-heal.test.ts' 'tests/ui/history-adapter.test.ts' 'tests/agent/loop-detection.test.ts' 'tests/llm/errors.test.ts' 'tests/llm/effort.test.ts' 'tests/skill/security-audit-scripts.test.ts' 'tests/permission/path-validator.test.ts' 'tests/llm/openai-protocol-edge.test.ts' 'tests/query/empty-param.test.ts' 'tests/workflow/sandbox.test.ts' 'tests/query/hypothesis-guide.test.ts' 'tests/api/errors.test.ts' 'tests/llm/fallback.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
