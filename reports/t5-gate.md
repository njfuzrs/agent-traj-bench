# T5 — 门禁：oracle / nop 双向验证

> 生成：`scripts/mvp/t5-gate.py`；判定逻辑 `scripts/mvp/t5_gate_lib.py`
> 逐 task 结论：`meta/gate.jsonl`

## 结论

| 门禁 | agent | 过 | 淘汰 | 基础设施问题 |
|---|---|---|---|---|
| oracle | `oracle` | 44/65 | 19 | 2 |
| nop | `nop` | 61/65 | 4 | 0 |
| oracle-k3 | `oracle -k 3` | 40/40 | 0 | 0 |

**已跑门禁：oracle、nop、oracle-k3**（三道齐全）

**三道门禁后存活：40/65 条**

### oracle 淘汰（task 自身问题）

- `T0004` —— oracle reward=0.0（f2p=0.0；正常跑完）
- `T0016` —— oracle reward=0.0（f2p=0.0；正常跑完）
- `T0019` —— oracle reward=0.0（f2p=0.0；正常跑完）
- `T0021` —— oracle reward=0.0（f2p=0.0；junit XML 缺失（测试文件没加载起来））
- `T0023` —— oracle reward=0.0（f2p=0.0；junit XML 缺失（测试文件没加载起来））
- `T0032` —— oracle reward=0.0（f2p=0.0；正常跑完）
- `T0035` —— oracle reward=0.0（f2p=0.0；正常跑完）
- `T0041` —— oracle reward=0.0（f2p=0.0；正常跑完）
- `T0043` —— oracle reward=0.0（f2p=0.0；正常跑完）
- `T0044` —— oracle reward=0.0（f2p=0.0；正常跑完）
- `T0046` —— oracle reward=0.0（f2p=0.0；junit XML 缺失（测试文件没加载起来））
- `T0048` —— oracle reward=0.0（f2p=0.0；正常跑完）
- `T0057` —— oracle reward=0.0（f2p=0.0；正常跑完）
- `T0058` —— oracle reward=0.0（f2p=0.0；正常跑完）
- `T0061` —— oracle reward=0.0（f2p=0.0；junit XML 缺失（测试文件没加载起来））
- `T0066` —— oracle reward=0.0（f2p=0.0；正常跑完）
- `T0067` —— oracle reward=0.0（f2p=0.0；junit XML 缺失（测试文件没加载起来））
- `T0069` —— oracle reward=0.0（f2p=0.0；正常跑完）
- `T0070` —— oracle reward=0.0（f2p=0.0；正常跑完）

### oracle 基础设施问题（**修环境，不要动 task**）

- `T0017` —— ⚠️ 参考解砸了 P2P（f2p=1 但 p2p=0.0）—— 须复跑分辨「gold patch 真引入回归」vs「P2P 是 flaky」，先不淘汰
- `T0027` —— ⚠️ 参考解砸了 P2P（f2p=1 但 p2p=0.0）—— 须复跑分辨「gold patch 真引入回归」vs「P2P 是 flaky」，先不淘汰

### nop 淘汰（task 自身问题）

- `T0001` —— 🔴 假 task：nop 下 f2p=1，测试不改代码就绿
- `T0006` —— 🔴 假 task：nop 下 f2p=1，测试不改代码就绿
- `T0015` —— 🔴 假 task：nop 下 f2p=1，测试不改代码就绿
- `T0037` —— 🔴 假 task：nop 下 f2p=1，测试不改代码就绿

