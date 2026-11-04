#!/bin/bash
# T3 生成，勿手改。task=T0064
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
restore_pinned 'tests/extension/loader.test.ts' 'e36e68e79b62c2c2708137a19eb0a833019fd717'
restore_pinned 'tests/extension/naming.test.ts' '95754fabaa481934ef88064b8770e5afb9fb70e3'
restore_pinned 'tests/extension/trust.test.ts' 'abe92677a6a964677bc1e181523ef64e69e18947'
restore_pinned 'tests/llm/errors.test.ts' '78adffa364f15aeb964a149095a43f1d03876377'
restore_pinned 'tests/permission/bash-security.test.ts' '8b8b9ef6ed466bab1da35f10c0e34f9b3c2b7be8'
restore_pinned 'tests/plugin/builtin.test.ts' '0017812f4dfbd65ca0fcc2c872d6d6a2b2d6346b'
restore_pinned 'tests/plugin/dependency.test.ts' '2d1475ce768c1300ff42a579dd810c5f4b9ee05f'
restore_pinned 'tests/plugin/identifier.test.ts' '453f722d342e7a1851b94da4ca0f6a53387018c3'
restore_pinned 'tests/plugin/loader-e2e.test.ts' '1db9bc0c404c5880dd0b6c4373fecd280ba2ef7e'
restore_pinned 'tests/plugin/manifest.test.ts' 'fca7ec7ef9ad08db8bd2690d197330e56425a938'
restore_pinned 'tests/plugin/memoize.test.ts' '7457c461b82d048facf718cd7d4892eb95915a77'
restore_pinned 'tests/plugin/scope.test.ts' 'fd55c7d831cc5c964543c5c7ad3803d099f87991'
restore_pinned 'tests/plugin/validate.test.ts' '7ae44558d740036c6bbe7555b8b2aa0718997ab6'
restore_pinned 'tests/skill/apply-migration.test.ts' 'b1970314a67b384b8fd46cbe12f7c05f579efdb6'
restore_pinned 'tests/skill/budget.test.ts' '3c17b34baeb56cf40eb2f5b21458d51d01869f95'
restore_pinned 'tests/skill/change-detector.test.ts' '94ffa59126442626f825d60ee7c7d825c39f4dd3'
restore_pinned 'tests/skill/ci-self-heal-chaos.test.ts' 'dcec6c8df0528c2b4db1c4cc5c68ee93785feaa0'
restore_pinned 'tests/skill/ci-self-heal.test.ts' 'b897c1904b3742a85854799441339c8cd4e6f18d'
restore_pinned 'tests/skill/code-governance.test.ts' '2b1bc4ce4e87f1b6db4e272ce296ce1bab74a17c'
restore_pinned 'tests/skill/code-review-chaos.test.ts' '50f0817ea3fddb72239d3582eb40e5ed7400fd67'
restore_pinned 'tests/skill/code-review.test.ts' '3c37b7dc506bde9442ff9c472aa08279ff9e230e'
restore_pinned 'tests/skill/dynamic-conditional.test.ts' '8a819361a1cdaec94a8382762566877d33b1304c'
restore_pinned 'tests/skill/enhancement.test.ts' 'df3a4ab08dc7aeecd7ad20faccffa384da36da6f'
restore_pinned 'tests/skill/hooks.test.ts' '8902a090198635fb63bac8aa6531f8ce3c8eadaf'
restore_pinned 'tests/skill/permission-mcp.test.ts' '4413e4d9ae8778c4d0db56f7a21960c6c881d92a'
restore_pinned 'tests/skill/prompt-processor.test.ts' '4e30b9a1f73eeca7406856f11418bd7249e343d6'
restore_pinned 'tests/skill/security-audit-scripts.test.ts' 'e78ca963643b6ad3875acbfd42205d3ea21cc991'
restore_pinned 'tests/skill/skill.test.ts' '703579a4766dded341190ff00c536f9cc6ca0585'
restore_pinned 'tests/tool/omission-detector.test.ts' 'b0fb5707410b8c4b404159cf09de4ad483f8e4b8'
restore_pinned 'tests/trace/collector.test.ts' 'c9510574a5b678acd181c830009c43454469aace'
rm -f 'tests/extension/managed-layer.test.ts'
rm -f 'tests/plugin/plugin-skills.test.ts'
rm -f 'tests/skill/activation-coordinator.test.ts'
rm -f 'tests/skill/executor.test.ts'
rm -f 'tests/skill/meta-tool.test.ts'

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
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml 'tests/extension/managed-layer.test.ts' 'tests/plugin/plugin-skills.test.ts' 'tests/skill/activation-coordinator.test.ts' 'tests/skill/executor.test.ts' 'tests/skill/meta-tool.test.ts' \
  > /logs/verifier/f2p.log 2>&1 || true
bun test --config=/tests/bunfig.verifier.toml --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml 'tests/skill/code-review.test.ts' 'tests/skill/ci-self-heal.test.ts' 'tests/skill/security-audit-scripts.test.ts' 'tests/skill/code-governance.test.ts' 'tests/skill/ci-self-heal-chaos.test.ts' 'tests/skill/code-review-chaos.test.ts' 'tests/skill/enhancement.test.ts' 'tests/extension/loader.test.ts' 'tests/plugin/validate.test.ts' 'tests/skill/prompt-processor.test.ts' 'tests/skill/skill.test.ts' 'tests/plugin/dependency.test.ts' 'tests/skill/permission-mcp.test.ts' 'tests/skill/budget.test.ts' 'tests/skill/dynamic-conditional.test.ts' 'tests/skill/apply-migration.test.ts' 'tests/skill/hooks.test.ts' 'tests/extension/naming.test.ts' 'tests/extension/trust.test.ts' 'tests/plugin/builtin.test.ts' 'tests/plugin/identifier.test.ts' 'tests/plugin/manifest.test.ts' 'tests/plugin/loader-e2e.test.ts' 'tests/plugin/scope.test.ts' 'tests/plugin/memoize.test.ts' 'tests/skill/change-detector.test.ts' 'tests/permission/bash-security.test.ts' 'tests/trace/collector.test.ts' 'tests/llm/errors.test.ts' 'tests/tool/omission-detector.test.ts' \
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
