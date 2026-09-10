# T5 反向自证（方案 §4 T5 的四条 + 一个对照）

> 生成：`python3 scripts/mvp/t5-gate.py --selftest`
> 机制：**故意破坏一处，然后要求门禁报红** —— 并核「红的理由对不对」，
> 不只看红没红。理由错的红是假绿的一种（T4 交接 #6 的教训）。

| 变异体 | 门禁 | 期望 | 结果 | 说明 |
|---|---|---|---|---|
| `M0-control` | oracle | 过 | ✅ 符合 | 未变异对照 —— 它若不过，说明整批环境有问题，四条自证的红都不算数 |
| `M1-testsh-always-1` | nop | 报红 | ✅ 符合 | test.sh 无条件报 1 → 门禁②（nop）必须判「假 task」 |
| `M2-empty-solution` | oracle | 报红 | ✅ 符合 | 参考解为空 → 门禁①（oracle）必须报红，且判成 task 问题而非环境问题 |
| `M3-conflicting-test-patch` | oracle | 报红 | ✅ 符合 | test_patch 打不上 → reward=0 且 error_code=2，且 **trial 状态不是 error**（要 reward=0，不要 trial error） |
| `M4-agent-tampers-tests` | oracle | 过 | ✅ 符合 | agent 往 `tests/telemetry/config-undefined-defaults.test.ts` 写垃圾 → 测试保护必须清掉它，门禁① 仍为 1 |
| `M5-tamper-unprotected` | oracle | 报红 | ✅ 符合 | M4 的配对反证：同样注入垃圾但**拿掉测试保护** → 必须报红。缺这条，M4 的绿分不清是「清理生效」还是「垃圾没写进去」 |

**6/6 通过**

