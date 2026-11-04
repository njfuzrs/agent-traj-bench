#!/bin/bash
# T3 生成，勿手改。task=T0010
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
restore_pinned 'tests/api/cache-detection.test.ts' 'c930e93d7fd692279b27288ab6f73fa5a6adaa40'
restore_pinned 'tests/api/cache-strategy.test.ts' '2bd8400b392c1ad46b92969498e959327fbc6db7'
restore_pinned 'tests/api/cost-tracker.test.ts' '374bd533e1a1064f35dd483e3a052b85eaa5580d'
restore_pinned 'tests/api/error-utils.test.ts' 'b6b9900cff55ae39c1287f3365b2d3b3b04cf258'
restore_pinned 'tests/api/errors.test.ts' '08ea5de410d864635a8659b0b1b4015670d82994'
restore_pinned 'tests/api/rate-limit.test.ts' 'e9ccf71f64d99276c9d1a2cda6bc8f85ff362157'
restore_pinned 'tests/command/clear-resets-cache-state.test.ts' '80a849b8559bde44235d5a2f6ab2facb4d807cb6'
restore_pinned 'tests/command/custom.test.ts' '187ff2964f91ad7401de4a81bc5bf2869eed8885'
restore_pinned 'tests/command/registry.test.ts' '8a0f2956c4f8781d3efdb3ba2c184c1b7036459a'
restore_pinned 'tests/config/config.test.ts' '771410ae5a0d376f95b23473fe6a9603498d23aa'
restore_pinned 'tests/config/language-preference.test.ts' 'cb98c05c628f392e8f43209422380e63533662f2'
restore_pinned 'tests/config/network-profile.test.ts' 'c17a69fa06dae2809627fe405093dd0eb93bbb10'
restore_pinned 'tests/config/patch-settings.test.ts' '51adc648b760de30380077f064466abfc66b8ec2'
restore_pinned 'tests/config/rules-layered.test.ts' '865b3783b0d45305658d03bfbb98ca13410e466a'
restore_pinned 'tests/config/rules.test.ts' 'b97e2d0b0068009be15e96a79146b4e772b67e89'
restore_pinned 'tests/config/schema.test.ts' '4149d39bce6bae4105c8fa322fe64bffe595d86a'
restore_pinned 'tests/config/settings.test.ts' '75287efe4f16687b35cbded1ba0581097158de74'
restore_pinned 'tests/config/system-prompt-cache-key.test.ts' '9e6cb306bb42ebeabfb1d27759b166ee98516abf'
restore_pinned 'tests/config/system-prompt.test.ts' '6927b42f0b369f9207638f97a9b2d78321ce51a4'
restore_pinned 'tests/config/token-utils.test.ts' '82a184c67621948cd7013fdd6e60ab2805b57339'
restore_pinned 'tests/edit-failure-tracker.test.ts' '3f9898a018e78b506a94a9fc510d1b716d6a13ef'
restore_pinned 'tests/guard/test-isolation-guard.test.ts' 'c035595b48fb276ef383818c12b8d2d94b88e6ed'
restore_pinned 'tests/migrations/backfill-team-defaults.test.ts' '09744d2ac2e847f3df5119d11a2770c9840499a3'
restore_pinned 'tests/migrations/relocate-lossy-project-key.test.ts' '7031c6746344364883e7b4a26a2be07775dd72c4'
restore_pinned 'tests/migrations/runner-fs-failure.test.ts' '84f9c7a13ed2228b8a0bb0f8657f44f581610a3d'
restore_pinned 'tests/release-flow-contract.test.ts' 'b992863a19fbe8c7add1ce077683c0970ee7cbb0'
restore_pinned 'tests/telemetry/cache-telemetry-rotation.test.ts' 'c24e0bb5581d1c4b3b2d8219fcb706c02bdba363'
restore_pinned 'tests/telemetry/cost-attribution.test.ts' '91e9c418ce674f3d44532bff03e371ca46fce9bb'
restore_pinned 'tests/telemetry/hook-probe.test.ts' '1db88e26a59cccf6d4ab3b5423fb3fdc52f518e0'
restore_pinned 'tests/telemetry/telemetry.test.ts' 'c88899fc2c999d3c5aa94c4490faddb869266b58'
restore_pinned 'tests/telemetry/usage-ledger.test.ts' '552f5031b21dafc76989a8df070cd84773ef428b'
restore_pinned 'tests/trace/builder.test.ts' 'c8ede8326abb1822def2846c6c3526db454c4f5b'
restore_pinned 'tests/trace/collector.test.ts' 'c9510574a5b678acd181c830009c43454469aace'
restore_pinned 'tests/trace/crash-marker.test.ts' '10cb90e03d229f06570ee582536e921b7111c3c4'
restore_pinned 'tests/trace/digest.test.ts' '4fb6632a34e7ce9d0e50da8da01f3a74bb35f34d'
restore_pinned 'tests/trace/jit-digest.test.ts' 'b00578617980910544e07bd5f1179344bf580733'
restore_pinned 'tests/trace/pid-manager.test.ts' '403c60863de44b5069e7650646e01e91c8d4e3c7'
restore_pinned 'tests/trace/stream-observer.test.ts' '24a415aaf17869fa7afb9456263b85f0fea5dc81'
restore_pinned 'tests/trace/todo-digest.test.ts' '987bc251b4f374d2c7c2c4a16bc7d3c48359a8d9'
restore_pinned 'tests/trace/uploader.test.ts' 'fa7369fac6333831785c144cd44cea6cf0e3fcca'
rm -f 'tests/preload-isolate-sid-home.ts'
rm -f 'tests/telemetry/no-real-path-writes.test.ts'

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
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/api/cache-detection.test.ts' 'tests/command/clear-resets-cache-state.test.ts' 'tests/config/patch-settings.test.ts' 'tests/guard/test-isolation-guard.test.ts' 'tests/migrations/backfill-team-defaults.test.ts' 'tests/migrations/relocate-lossy-project-key.test.ts' 'tests/migrations/runner-fs-failure.test.ts' 'tests/telemetry/cache-telemetry-rotation.test.ts' 'tests/telemetry/no-real-path-writes.test.ts' 'tests/trace/crash-marker.test.ts' 'tests/trace/pid-manager.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/trace/collector.test.ts' 'tests/config/language-preference.test.ts' 'tests/trace/builder.test.ts' 'tests/trace/digest.test.ts' 'tests/config/schema.test.ts' 'tests/config/system-prompt.test.ts' 'tests/api/errors.test.ts' 'tests/api/cache-strategy.test.ts' 'tests/config/system-prompt-cache-key.test.ts' 'tests/trace/uploader.test.ts' 'tests/command/custom.test.ts' 'tests/config/network-profile.test.ts' 'tests/config/settings.test.ts' 'tests/release-flow-contract.test.ts' 'tests/telemetry/usage-ledger.test.ts' 'tests/api/cost-tracker.test.ts' 'tests/api/error-utils.test.ts' 'tests/config/rules-layered.test.ts' 'tests/telemetry/hook-probe.test.ts' 'tests/config/rules.test.ts' 'tests/telemetry/cost-attribution.test.ts' 'tests/trace/jit-digest.test.ts' 'tests/api/rate-limit.test.ts' 'tests/edit-failure-tracker.test.ts' 'tests/trace/todo-digest.test.ts' 'tests/command/registry.test.ts' 'tests/config/config.test.ts' 'tests/telemetry/telemetry.test.ts' 'tests/trace/stream-observer.test.ts' 'tests/config/token-utils.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
