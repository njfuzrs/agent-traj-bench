#!/bin/bash
# T3 生成，勿手改。task=T0056
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
restore_pinned 'tests/preload-isolate-sid-home.ts' '541abfc175dc7e4804aefa3714fb889d87a60226'
restore_pinned 'tests/telemetry/cache-bench.test.ts' '7210cddfecc3b331e33ba011b81325544134ce4d'
restore_pinned 'tests/telemetry/cache-telemetry-rotation.test.ts' 'e2ec190c5040dba497119971f9b1c952d9de79c1'
restore_pinned 'tests/telemetry/cache-trust-probe.test.ts' 'bf553cc5dd7dcf725a793b4d8f83edd3b6503b81'
restore_pinned 'tests/telemetry/config-undefined-defaults.test.ts' 'c61aeda18c5e9d92fc41a1875e898696b7d6f57b'
restore_pinned 'tests/telemetry/content-tracing-wiring.test.ts' '764d627b32d67bc3bfda6d7bdc3b165319af2a92'
restore_pinned 'tests/telemetry/content-tracing.test.ts' '5d5a092db22ce73788994a69e794cce7750bdb96'
restore_pinned 'tests/telemetry/cost-attribution.test.ts' '91e9c418ce674f3d44532bff03e371ca46fce9bb'
restore_pinned 'tests/telemetry/hook-probe.test.ts' '1db88e26a59cccf6d4ab3b5423fb3fdc52f518e0'
restore_pinned 'tests/telemetry/no-real-path-writes.test.ts' '0b14ee4c8b2689e75357bbbfd49d8946fbd8782b'
restore_pinned 'tests/telemetry/otlp-exporter.test.ts' 'bc521f1ab89aa5e77b11a9db3eb681cd22c0eaf9'
restore_pinned 'tests/telemetry/otlp-wiring.test.ts' 'c966c10c5733676a7213edfee1bae048340ed57b'
restore_pinned 'tests/telemetry/provider-health.test.ts' '5516d8300ed1d8fcf8773d939b9d70f16449725c'
restore_pinned 'tests/telemetry/telemetry.test.ts' 'c88899fc2c999d3c5aa94c4490faddb869266b58'
restore_pinned 'tests/telemetry/usage-ledger.test.ts' 'c31b7f6ebe1daed9295abd2d65cda66de71d189c'
restore_pinned 'tests/trace/blank-session-prune.test.ts' '66a644374ff054bbcd25e88d339c2a5aaa794cbd'
restore_pinned 'tests/trace/builder.test.ts' 'c8ede8326abb1822def2846c6c3526db454c4f5b'
restore_pinned 'tests/trace/cache-report.test.ts' 'a425651a9eda9c3254dbebecfd4457e014b5fa09'
restore_pinned 'tests/trace/collector.test.ts' 'c9510574a5b678acd181c830009c43454469aace'
restore_pinned 'tests/trace/cost-recompute.test.ts' '16be9664887b0eb955850c2becabbf4436f518d5'
restore_pinned 'tests/trace/crash-marker.test.ts' '402128df896da84efa5ea7219d5358fc14b8f838'
restore_pinned 'tests/trace/digest.test.ts' 'f64ef22fac33d878defd60f06a75ec2516007ce8'
restore_pinned 'tests/trace/jit-digest.test.ts' 'b00578617980910544e07bd5f1179344bf580733'
restore_pinned 'tests/trace/jit-telemetry.test.ts' '413c0f2359667927947958f1bf4c4d6ce2aae3c6'
restore_pinned 'tests/trace/pid-manager.test.ts' 'a365b7ef1fa384975b618b8db92361853acf9b80'
restore_pinned 'tests/trace/prefix-break-probe.test.ts' 'cbb2a1d959074efcff8f99b2d12483633140732c'
restore_pinned 'tests/trace/side-call-observability.test.ts' '56ac952c3e0a6639958d52eeeed0059296f8a5d2'
restore_pinned 'tests/trace/stream-observer.test.ts' '24a415aaf17869fa7afb9456263b85f0fea5dc81'
restore_pinned 'tests/trace/todo-digest.test.ts' '987bc251b4f374d2c7c2c4a16bc7d3c48359a8d9'
restore_pinned 'tests/trace/ttft-lifecycle.test.ts' '7b1735ffb8975797ea040366e13a90a12f08664c'
restore_pinned 'tests/trace/uploader.test.ts' 'fa7369fac6333831785c144cd44cea6cf0e3fcca'
restore_pinned 'tests/trace/writer-redaction.test.ts' '8a268ceb41d1797d88c39ae89f86d30b7a224f04'
restore_pinned 'tests/trace/writer.test.ts' '615d634e0dda2f2c667005ef3ef0954b45d9916d'
rm -f 'tests/telemetry/usage-aggregator.test.ts'

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
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/telemetry/provider-health.test.ts' 'tests/telemetry/usage-aggregator.test.ts' 'tests/trace/prefix-break-probe.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/trace/collector.test.ts' 'tests/trace/digest.test.ts' 'tests/telemetry/content-tracing.test.ts' 'tests/trace/builder.test.ts' 'tests/telemetry/otlp-exporter.test.ts' 'tests/trace/uploader.test.ts' 'tests/telemetry/cache-bench.test.ts' 'tests/telemetry/usage-ledger.test.ts' 'tests/telemetry/hook-probe.test.ts' 'tests/telemetry/cache-trust-probe.test.ts' 'tests/telemetry/cost-attribution.test.ts' 'tests/trace/jit-digest.test.ts' 'tests/telemetry/cache-telemetry-rotation.test.ts' 'tests/trace/todo-digest.test.ts' 'tests/trace/ttft-lifecycle.test.ts' 'tests/telemetry/telemetry.test.ts' 'tests/trace/cache-report.test.ts' 'tests/trace/cost-recompute.test.ts' 'tests/trace/stream-observer.test.ts' 'tests/trace/side-call-observability.test.ts' 'tests/trace/writer.test.ts' 'tests/telemetry/otlp-wiring.test.ts' 'tests/trace/blank-session-prune.test.ts' 'tests/telemetry/config-undefined-defaults.test.ts' 'tests/trace/writer-redaction.test.ts' 'tests/trace/jit-telemetry.test.ts' 'tests/trace/pid-manager.test.ts' 'tests/telemetry/content-tracing-wiring.test.ts' 'tests/trace/crash-marker.test.ts' 'tests/telemetry/no-real-path-writes.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
