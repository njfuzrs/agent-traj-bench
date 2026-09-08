# T3 — harbor task 目录生成 + P2P 采样 + 判分链路自证

> 日期：2026-09-08 ｜ 脚本：`scripts/mvp/t3-sample-p2p.py`（采 P2P）
> + `scripts/mvp/t3-build-harbor-tasks.py`（生成 task 目录）
> 输入：`meta/resolved.jsonl`（T2）+ `meta/snapshots.jsonl` / `tasks/T####/environment/`（T4）
> + `meta/candidates.jsonl`（T1，题面在这里）
> 产物：`tasks/T####/` 的九个文件 × 65 + `meta/p2p.jsonl` + `meta/tasks.stats.json`

## 一、结果

**65 条 task 目录全部产出，harbor 全认，五项验收过四项**（S 档不足是 T2 上游流失，见 §9.1）。

| 项 | 数 | 说明 |
|---|---|---|
| task 目录 | **65** | = T4 可建 env 的 65 条（`resolved.jsonl` 70 条 − 5 条无 env） |
| 每条文件数 | **12** | §4 的九个 + `meta.json` + `environment/` 两个（T4 产出，本 task 只核不写） |
| `Task.is_valid_dir()` | **65/65** | 用 harbor 自带解释器逐条校验，无一不认 |
| P2P 名单 | 每条 **30** 个文件，合计 1950 | 口径②：单位是文件；`filter_mode: "path"` |
| F2P 名单 | 1–11 个文件（中位 1），合计 154 | 按 task 独立算（口径①） |
| unique base | **50** | 8 个 base 被复用，去重省了 15 次全量跑 |
| 难度档 | S 5 ／ M 22 ／ L 38 | ⚠️ S 档 < 10，**不达验收**，根因在 T2（§9.1） |
| 类别 | `test_authoring` 37 ／ `bug_fix` 28 | 其中 4 条 `test_authoring` 判定为**非 F2P**（§5） |
| 采样耗时 | 全量 23–144s（中位 65s）／复跑 0.6–79s（中位 23s） | 冷构建 46 个，21.6–67.3s（中位 28s） |

验收逐项：

| 验收项 | 结果 |
|---|---|
| ≥50 条 task 目录 | ✅ 65 |
| 三个难度档各 ≥10 | 🔴 **S 档只有 5** —— 上游 T2 流失，非本 task 缺陷（§9.1） |
| `FAIL_TO_PASS` 全部非空 | ✅ 65/65，最少 1 个文件 |
| harbor 认全部目录 | ✅ 65/65 `Task.is_valid_dir()` |
| 文件齐全自查 | ✅ 65×12，缺失或零字节都报错（`--check-only`，§4.1） |
| `test.sh` 静态自查三条 | ✅ 无 grep 判分 ／ 逐路径还原 ／ 每条退出路径写 reward |
| 反向自证三条 | ✅ 全部实测通过（§6.1） |

## 二、🔴 四处实测纠正了方案的写法

四条都不是「方案写得不够细」，而是**照着方案写会得到一个静默失效的判分链路**。
共同形态与 §3.8-F 同源：**看着绿，实际坏，且不报错**。

| # | 纠正 | 照方案写的后果 | 谁抓出来的 |
|---|---|---|---|
| 2.1 | reward 文件名是 `reward.json`（单数） | 静默退回读 `reward.txt`，f2p/p2p 两键永不进 result.json | 核 harbor 源码 |
| 2.2 | junit XML 整份漏掉**加载失败**的文件 | 只读 failures → 满分；采样侧 → 误判为绿进名单后恒败 | 端到端实测 |
| 2.2' | bun 只按**文件名**收集测试 | 辅助文件混进 F2P → 静默跳过 → **oracle 也拿 0 分** | ← 2.2 的核对机制自己抓的 |
| 2.3 | `--3way` 前必须刷 git index | 容器里 100% apply 失败，而 test.sh 照样给分 | 第一次端到端实测 |

⚠️ 2.2' 值得单独记一笔：它是**2.2 的修复机制自己抓出来的第二类问题** ——
写文件覆盖核对时只想着「加载失败」，结果它顺带兜住了「根本没被收集」。
一个防御措施抓到设计时没想到的第二种故障，说明这层核对不是冗余。

### 2.1 reward 文件名是 `reward.json`（单数），方案写的 `rewards.json` harbor 不读

方案有十来处写 `rewards.json`（§3.8-D、§4 T3、§4 T5、§7 排查表…）。核 harbor 源码：

```python
# harbor/models/trial/paths.py:45-46
reward_text_path: PurePosixPath = verifier_dir / "reward.txt"
reward_json_path: PurePosixPath = verifier_dir / "reward.json"     # ← 单数
```

`verifier/verifier.py:226` 的取值顺序是「`reward.json` 存在就用它，否则退到
`reward.txt`，两个都没有才抛 `RewardFileNotFoundError`」。

**后果不是报错，而是静默降级**：写 `rewards.json` → harbor 找不到 → 退回读
`reward.txt`（只能装一个数）→ **`f2p` / `p2p` 两个键永远不进 `result.json`**。
形态是「门禁在跑、分也有，但 F2P 与 P2P 的分永远读不到」——
正是 §3.8-D 立规矩要避免的「退化成单值判定」，而它会以「规矩已遵守」的样子出现。

本轮实现写 **`reward.json`**，并同时写 `reward.txt`（双源，T5 交叉核对）。
实测两个源逐字一致。

### 2.2 junit XML 会**整份漏掉「加载失败」的文件**

这是本轮最重要的一条，方案与 T4 报告都没有。实测：

```
$ bun test --reporter=junit --reporter-outfile=x.xml good.test.ts loadfail.test.ts
XML root:  tests="6" assertions="16" failures="0"      ← 看着全绿
日志:      6 pass / 1 fail / 1 error                    ← 有个文件根本没跑起来
XML 内容:  只有 good.test.ts 一个 <testsuite>          ← loadfail 整个消失
```

`import` 失败的文件（`Cannot find package 'chalk'`、`Cannot find module '../../ink/...'`）
bun **不会为它生成 `<testsuite>` 节点**。只单跑一个这样的文件时更极端：
**XML 文件根本不写**（`cat: x.xml: No such file or directory`）。

全量跑也能看到这个缺口：root 报 `failures="6"`，日志报 `27 fail / 21 errors`——
差额 21 就是「加载失败、从 XML 消失」的那些文件。

**两侧都会中招，且方向相反：**

| 侧 | 只看 `failures` 的后果 | 形态 |
|---|---|---|
| 采样（`t3-sample-p2p.py`） | 加载失败的文件「没有 failures 记录」→ 误判为绿 → 进 P2P 名单 → 容器里恒败 | 像「task 太难」 |
| 判分（`tests/score.py`） | 名单里的文件没跑起来 → root `failures=0` → **判满分** | 像「agent 做对了」 |

所以两侧统一判据 —— **三条同时成立**才算绿：
① 文件出现在 XML 的直接子 `testsuite` 里（证明加载成功）② `failures == 0`
③ `tests > 0`（零用例不构成回归保护）。判分侧再加**文件覆盖核对**：
名单里每个文件都必须出现，少一个即该侧判 0。

### 2.2' 同一个缺口的第二次命中：bun 只按**文件名**收集测试

文件覆盖核对（§2.2）写完后不久，它抓到了第二类完全不同的问题 ——
T2 的 `is_test` 是**按用途**判的（在 `tests/` 下、随 test_patch 一起进来），
而 bun 是**按文件名**收集的（必须含 `.test.` / `.spec.` / `_test_` / `_spec_`）。

实测反例：T0010 的 `tests/preload-isolate-sid-home.ts` —— 一个 preload 辅助文件
（给同进程后续测试设 HOME 隔离兜底），`is_test=true` 但文件名没有 `.test.`：

```
单独跑它         → error: Tests need ".test", "_test_", ".spec" or "_spec_" in the filename
                   并且**连 XML 都不写**
与正常测试一起跑 → exit 0、日志只报正常那个文件、它从 XML 里整个消失
```

第二种是致命的：**bun 不报错、也不非零退出**。若判分只看失败计数，这条 task
会稳定满分；而有了文件覆盖核对，它被判 `missing` → f2p=0 → **连 oracle 都拿 0 分**，
形态是「参考解也做不出来」，极易被误诊成 T2 的 patch 反解错了。修前实测 T0010
的 oracle 正是 f2p=0；修后 oracle=1.0（`missing: []`）、nop=0.0。

**修法要拆成两份名单**，两边都不能省：

| 名单 | 过不过滤 | 理由 |
|---|---|---|
| F2P（`bun test` 的参数） | ✅ 过滤 | 混进去会从 XML 消失 → f2p 恒 0 |
| 保护名单（restore/remove） | ❌ **不过滤** | 辅助文件随 test_patch 落地、agent 同样能改。排除了却不保护，agent 改掉它就能影响同进程后续测试，且没有任何机制会还原 |

全库扫过：65 条里只有 T0010 这一条中招（1/161 个测试文件）。

### 2.3 `git apply --3way` 在容器里 100% 失败（`does not match index`）

T2/T4 都验过 `git apply --check` 全过（130/130），但那是在 mirror 里验的。
容器里第一次跑 `solve.sh` 就失败：

```
$ git apply --3way /solution/gold_patch.diff
error: src/app.ts: does not match index          ← 100% 复现
$ git apply /solution/gold_patch.diff            ← 同一个 patch
（成功）
```

根因：T4 的镜像用 `tar -xzf` 解包再 `git add -A` + `commit`，
解出来的文件 **mtime/ctime 与 index 记录不一致**。实测

```
git diff-files --name-only | wc -l   →  1215      ← 快照里每个文件都 stat-dirty
git update-index -q --refresh
git diff-files --name-only | wc -l   →  0
```

`--3way` 要读 index 做三方合并，一遇 stat-dirty 就拒绝动手；纯 `git apply`
只碰工作区，所以两层的 `apply --check` 全都发现不了。

**形态最危险的一条**：`solve.sh` 失败 → 代码没改 → 但 `test.sh` 照样跑完给分。
第一次端到端实测就撞上了：**`solve.sh` 报错，reward 却是 1.0**
（那条 task 的 F2P 恰好在 base 上也绿，见 §3）。两个独立缺陷叠在一起，
单看 reward 完全看不出参考解根本没打上。

修法：apply 前 `git update-index -q --refresh || true`
（`|| true` 是因为它在有真实改动时返回非零，而我们只要它刷 stat 缓存）。
`solve.sh` 与 `test.sh` 两处都要加。

## 三、🔴 抓到一批「F2P 名不副实」的 task，且判据已机械化

§2.3 那次实测顺带暴露了一件更要紧的事：**T0001 的 F2P 在 base 上就是绿的**。

```
# base 上只打 test_patch、不打 code_patch，跑它的 F2P：
14 pass / 0 fail          ← 按 F2P 的定义，这里必须是红的
```

它是 `test_authoring` 类：新写的测试测的是**已有行为**，所以不改代码也能过。
后果是 `nop`（空 patch）也能拿满分，**`oracle` 与 `nop` 的分无法区分** ——
这条 task 对基线没有鉴别力。

方案 §4 T3 的遗留问题里预告过这个形态（「`test_authoring` 的淘汰判断要在 T5 之后
复核」），本轮把它**提前到采样阶段并机械化**：`f2p_precheck()` 在 base 上打
test_patch、跑该 task 的 F2P，**必须红**，否则记 `is_f2p: false`。

**为什么必须在这里做，而不是留给 T5**：这个检查需要一个活容器。采 P2P 时容器
本来就起着，顺手多跑一次只多几秒；留给 T5 要**重建 50 个镜像**（实测冷构建
29-160 秒/个，约 40-130 分钟纯等待）。

⚠️ 本脚本**只标记、不淘汰** —— 淘汰判据属于 T5/T6（方案 §4 T3 遗留问题）。
名单见 §5。

## 四、九个文件，不是七个

方案 §4 T3（v1.2）说「五个文件实为七个」。本轮实际产出**九个**，多出的两个是
`tests/f2p.json` 与 `tests/p2p.json`：

```
T0001/
├── instruction.md          题面（T1 的 instruction_clean 原文 + 环境事实）
├── task.toml               harbor 读；三个 timeout 都显式写
├── environment/            ← T4 的产物，本 task 只读不写
│   ├── Dockerfile
│   └── repo-snapshot.tar.gz
├── solution/
│   ├── solve.sh            OracleAgent 挂 /solution
│   └── gold_patch.diff
├── tests/
│   ├── test.sh             Evaluator 挂 /tests
│   ├── test_patch.diff
│   ├── score.py            解析 junit → 写 reward.json + reward.txt
│   ├── f2p.json            ← 多出来的
│   └── p2p.json            ← 多出来的
└── meta.json               我们的溯源，harbor 不读
```

为什么把名单单独落成 json：`test.sh` 与 `score.py` **必须读同一份名单**。
走 shell 变量导出给 python 会被容器环境影响，而两份各写一遍会漂移 ——
漂移的形态是「跑了 30 个文件、只核对了 28 个」，又是一个不报错的缺口。
落成文件后两边同源，规则5（名单字面写入）也仍然满足。

### 4.1 齐全自查必须有一条**不写盘**的路径（实测踩到才发现）

方案的验收项写「脚本自查每个 task 目录，缺一个即报错」，反向自证②要求
「删掉某条的 `tests/score.py` → 自查必须报错」。最初把自查放在**生成之后**，
结果反向自证**做不出来**：

```
rm bench/v0.2-mini/tasks/T0002/tests/score.py
python3 scripts/mvp/t3-build-harbor-tasks.py   → rc=0   ← 期望非 0
```

原因是生成是**幂等重写** —— 跑一遍就把删掉的文件补回来了，末尾那次核对
永远看不到「产物被破坏」的状态。这样的自查只能抓「生成器自己漏写」，
抓不到交付物在盘上被改坏，而后者才是验收项想防的。

所以加了 `--check-only`（只核对、不写盘）：

```
$ python3 scripts/mvp/t3-build-harbor-tasks.py --check-only
✅ 65 条 task 的 12 个文件全部齐备且非空

$ rm .../T0002/tests/score.py && truncate -s0 .../T0003/solution/gold_patch.diff
$ python3 scripts/mvp/t3-build-harbor-tasks.py --check-only ; echo rc=$?
🔴 2/65 条 task 的产物不齐：
   T0002: ['tests/score.py']
   T0003: ['solution/gold_patch.diff']
rc=2
```

两个细节：

- **零字节文件与缺失同罪**，且更隐蔽 —— 空的 `gold_patch.diff` 在容器里是
  「`git apply` 成功但什么都没改」，即 **oracle 静默拿 0 分**，形态是
  「参考解做不出来」，会被误诊成 T2 反解错了（与 §2.2' 同一个坑）。
- **`environment/` 两个文件本脚本不写但必须核**（所以是 12 个而不是 10 个）：
  快照不入 git，换机器后缺它的 task 要在**生成阶段**就炸，而不是等 T5 建镜像时才失败。

## 五、F2P 自检的结果

65 条全部跑过 `f2p_precheck()`（在 base 上打 test_patch、不打 code_patch，跑该条 F2P，
必须红）。**4 条判定为非 F2P**，全部是同一形态 `f2p_passes_at_base`：

| task | band | category | base 上跑 F2P 的结果 | 改动规模 |
|---|---|---|---|---|
| T0001 | S | `test_authoring` | 14 pass / 0 fail（1 文件） | 1 code + 1 test |
| T0006 | M | `bug_fix` | 12 pass / 0 fail（1 文件） | 4 code + 1 test |
| T0015 | S | `bug_fix` | 22 pass / 0 fail（1 文件） | 1 code + 1 test |
| T0037 | M | `test_authoring` | 7 pass / 0 fail（3 文件） | 1 code + 3 test |

⚠️ **两条是 `bug_fix`，不是只有 `test_authoring` 会中招** —— 这一点方案没预料到。
方案把这个形态归因于 `test_authoring`（「测试自己测自己」），但 T0006/T0015 是
修 bug 的单元，新测试照样在 base 上全绿。合理的解释是**测试与代码改动不同因**：
同一个会话里既修了 bug 又补了一批与该 bug 无关的测试，T2 按会话边界把它们
收进同一个单元，于是「这批测试」并不检验「这次代码改动」。

所以 §3 的判据（`f2p_precheck`）比方案的分类启发式**更该被信任**：
它按行为判，不按 category 猜。若照方案只审 `test_authoring`，
T0006/T0015 这两条会带着「nop 也满分」进 T5。

⚠️ 本脚本**只标记、不淘汰** —— `meta.json` 里不写 `is_f2p`（已核，65 条都没这个键），
判据留在 `meta/p2p.jsonl` 的 `f2p_check` 字段。淘汰属于 T5/T6 的职责。
**淘汰后 61 条**，高于验收下限 50，但 **S 档会从 5 掉到 3**（见 §9.1）。

**中招率远低于方案预期**：方案担心 `test_authoring` 会「大量淘汰」
（占可 F2P 池 112/163），实际 37 条里只有 2 条中招。原因是 T2 的
`not_two_sided` 已先筛掉 37 个「只有测试、没有代码改动」的单元（见 §9.1 漏斗）——
两道筛子叠起来，剩下的 `test_authoring` 多数确有因果关联。

## 六、四条作弊路径的实测封堵

在 T0002（`bug_fix`，F2P 合格）上逐条实测，四条全部封住：

| # | 作弊方式 | 结果 | 关键机制 |
|---|---|---|---|
| 1 | 正常 oracle（打 gold patch） | `reward=1.0` f2p=1 p2p=1 | 基准正例 |
| 2 | nop（不改任何代码） | `reward=0.0` **f2p=0** p2p=1 | F2P 红、P2P 绿 —— 分开报分的价值 |
| 3 | agent 把 F2P 测试覆写成 `expect(1).toBe(1)` | `reward=0.0` f2p=0 | 规则4 逐路径还原后重打 test_patch |
| 4 | agent 预先伪造 `reward.json` = 1.0 与 `reward.txt` = 1 | 两个文件都被改回 **0.0** | 规则1+2 无条件先覆盖为 0 |

第 2 条的 `f2p_detail.failed` 里逐字列出了失败文件名，第 3 条的伪造测试
被 `git checkout` 还原后仍然判红 —— 说明还原真的生效，不是「碰巧也红」。

这四条合起来即**T5 门禁的核心已经在 T3 阶段自证过一遍**：
`oracle=1 / nop=0` 可区分，且区分不来自任何可被 agent 篡改的中间产物。

### 6.1 三条反向自证（「验收项本身会不会恒真」）

上面四条验的是「判分链路挡不挡作弊」。反向自证验的是另一件事：
**这些检查自己会不会永远通过** —— 一个恒真的门禁比没有门禁更糟，
因为它会在报告里留下「已验证」的字样。三条全部实测：

| # | 破坏方式 | 期望 | 实测结果 |
|---|---|---|---|
| ① | 把 `test.sh` 换成「无条件写满分」，跑 nop | nop 拿到 1.0 → T5 的 nop 门禁必须报红 | ✅ `{"reward":1.0,"f2p":1.0,"p2p":1.0}`，与 §6 第 2 行真实 nop 的 `0.0` 形成对照 |
| ② | 删掉 `T0002/tests/score.py`，跑齐全自查 | 非零退出并指名缺哪个文件 | ✅ `rc=2`，`T0002: ['tests/score.py']`（**但第一版做不出来**，见 §4.1） |
| ③ | 造一个必然冲突的 `test_patch`（声称改的三行在真实文件里不存在） | `reward=0`、`error=test_patch_apply_failed`、**`exit 0` 而非 trial error** | ✅ 三项全中 |

③ 的实测输出（`t4:T0002` 镜像内跑，`--network none`）：

```
test.sh rc=0                                   ← exit 0，不是 trial error
reward.json: {"reward":0.0,"f2p":0.0,"p2p":0.0,"error":"test_patch_apply_failed"}
reward.txt:  0                                 ← 双源一致
apply.log:   error: repository lacks the necessary blob to perform 3-way merge.
             Falling back to direct application...
             error: patch failed: tests/telemetry/telemetry.test.ts:1
             TEST_PATCH_APPLY_FAILED
```

这条同时证明了 `exit 0` 的设计是对的：harbor 拿到的是「这条 task 得 0 分」，
而不是「这个 trial 崩了」—— 后者会被误读成基础设施问题，反而掩盖
「patch 与快照对不上」这个真实缺陷。

⚠️ **② 是本轮唯一一条「第一版实现让反向自证恒真」的**，它的价值全在于此：
若不做这条反向验，齐全自查会以「已实现」的身份留在报告里，
而它实际上抓不到交付物被改坏。详见 §4.1。

## 七、其它实测细节

- **两条特殊路径都单独验过**：
  - `workspace` 模式（3 条 monorepo base）：T0043 的 F2P 自检正常报红
    （base 上 22 pass / 6 fail），带引号的正则 `test_cmd` 原样透传没有被 shell 吃掉。
  - **含引号/空格的路径**：注入 `tests/it's-here.test.ts`、`tests/say-"hi".test.ts`、
    `tests/a b.test.ts` 三种，生成的 `test.sh` 仍过 `bash -n`（`sh_single_quote()`
    做 POSIX 转义）。实测仓库里没有这种路径，但生成器不该假定输入干净 ——
    语法错的形态是 `test.sh` 一进容器就崩、reward 只剩开头那个 0、**全批 0 分**。
- **P2P 单位是文件**（口径②），`meta.json` 记 `filter_mode: "path"`。
  实测同目录优先的排序确实生效：T0002（telemetry 改动）选出的 30 个里
  前 6 个全是 `tests/telemetry/`，T0024（llm 改动）前 6 个全是 `tests/llm/`。
- **复跑耗时取决于「采到哪些文件」，不取决于文件个数。** 同样是 40 个候选文件，
  全批 42 个这样的 base 实测从 **0.6 秒到 37.1 秒**都有（见 §8）。所以 T4 §9.3 的
  「40 文件 × 2 次 = 7 秒」并不是错的 —— 它测的那批恰好是快文件；
  但把它当**通用估算**会低估，中位数是 23 秒。口径③的结论不变。
- **flaky 真的抓到了一个**：`tests/tool/bash-stability.test.ts` 在全量跑里是绿的，
  复跑时红（`is_background（旧通道）也返回 task_id` 失败）。这条要是进了 P2P 名单，
  T5 的「nop 的 p2p=1」会随机失败，形态像 task 坏了而不像名单里混了 flaky。
  **口径③用一次真实拦截证明了自己的必要性** —— 而 T4 §8 的「同 commit 两次逐字相同」
  是**全量**层面的一致，掩盖了单文件层面的抖动（全量跑里它绿，所以那次一致性没露出来）。
- **`P2P_MARGIN = 10`**：多取 10 个送复跑。若只取 30 个去复跑，flaky 掉几个就
  跌破 30 的下限，补选又要再起一轮复跑。
- **agent 超时按难度分档**：S 900s / M 1800s / L 2700s。方案示例统一 900s，
  但 L 档占 38/65，给同样墙钟时间会系统性超时 —— 而超时在 harbor 里是
  **error 而不是低分**，会把「没做完」和「做不出来」混成一类。
- **`build_timeout_sec` 从 600 提到 1800**：实测冷构建 29-160 秒，但那是基础镜像
  已在本地的情况；换机器首次要拉 335MB 的 `oven/bun:1.3.14`，600 秒会压线。

## 八、耗时实测：复跑成本由「采到哪些文件」决定，不由文件个数决定

T4 §9.3 用「40 文件 × 2 次 = 7 秒」把口径③定了档。这个数**不能当通用估算**，
但它也不是测错了 —— 逐 base 实测（下表列前 12 个 base，全批 50 个的汇总见表下）：

| base | 候选文件数 | 复跑耗时 | 复跑用例数 | 全量耗时 | 全量绿文件 |
|---|---|---|---|---|---|
| 9b5706c0 | 40 | 26.0s | 1305 | 76.1s | 347 |
| 76b60150 | 66 | 62.8s | 2263 | 142.8s | 558 |
| 484bb688 | 40 | 22.7s | 1518 | 72.8s | 471 |
| 6b09d717 | 108 | 79.3s | 2467 | 133.3s | 529 |
| 50a69824 | 40 | 22.8s | 1565 | 77.3s | 488 |
| 5a092172 | 40 | 18.5s | 1038 | 45.5s | 220 |
| 3b916830 | 80 | 30.1s | 1805 | 79.8s | 506 |
| c8d8fb42 | 40 | 22.4s | 1556 | 68.8s | 419 |
| d05cc2bc | 40 | 28.5s | 937 | 73.6s | 474 |
| **133e0cfa** | **40** | **1.1s** | 858 | 134.2s | 535 |
| **c279ae8b** | **40** | **1.3s** | 1128 | 54.4s | 304 |
| **5dba89fe** | **40** | **3.4s** | 525 | 78.3s | 515 |

**全批 50 个 base 跑完后，这个结论比上表更强**：候选恰好 40 个文件的有 42 个 base，
复跑耗时 **0.6 秒到 37.1 秒**（差 **62 倍**），而用例数只差 3.4 倍。

主项不是文件数也不是用例数，而是**这批文件里有没有慢测试**（起子进程、跑真 shell、
等超时的那些）。全批汇总：

| | min | 中位 | max |
|---|---|---|---|
| 复跑（候选文件） | 0.6s | **23.2s** | 79.3s |
| 全量（全部文件） | 23.2s | **65.0s** | 144.0s |

所以：

- T4 那 7 秒**大概是采到了一批快文件**，不是测量方法错。
- 但**写进文档当估算就会低估** —— 中位数 23 秒，最坏 79 秒。
- 复跑相对全量（中位 65 秒、最坏 144 秒）确实便宜，**口径③的结论完全站得住**。

另外两笔开销 T4 §9.3 没算进去，它们比复跑大得多：

| 项 | 实测 | 说明 |
|---|---|---|
| **冷构建镜像** | 21.6–67.3 秒/个（中位 28.4，共 46 个） | 50 个 base 只有 4 个有现成 `t4:*` 可复用 |
| **F2P 自检** | 每条 task 一次 `docker run` | 本轮新增（§3），65 条各一次 |

**教训与 T4 §9.4 同源：性能数字必须标明测的是哪一段、以及那一段的方差。**
「复跑 40 个文件」听起来是个确定的量，实际取决于采到了谁 —— 而采到谁是随机的。

## 九、遗留问题（交给 T5 / T6）

### 9.1 🔴 S 档只有 5 条，不达「各档 ≥10」—— 根因在 T2，T3 无法自救

这是本轮**唯一一项验收未过**，且**不是 T3 的缺陷**：T3 只能生成 T2 反解成功、
T4 又能建出 env 的那些 task。逐层漏斗：

| 层 | S | M | L | 合计 |
|---|---|---|---|---|
| T1 候选池 | 41 | 52 | 89 | 182 |
| T2 反解 ok | **5** | 25 | 40 | 70 |
| T4 env 可建 | **5** | 22 | 38 | 65 |
| 扣掉非 F2P（§5） | **3** | 20 | 38 | 61 |

S 档在 **T2 那一层就掉了 88%**（41 → 5），逐条原因：

| 丢弃原因 | S | M | L | S 档占比 |
|---|---|---|---|---|
| `not_two_sided`（只有测试或只有代码，凑不成两侧） | **17** | 9 | 11 | **41%** |
| `rebuild_failed`（patch 反解不出来） | 12 | 17 | 26 | 29% |
| `gitignored_paths` | 4 | 1 | 7 | 10% |
| `no_code_ops` | 2 | 0 | 3 | 5% |
| `incomplete_paths` | 1 | 0 | 2 | 2% |

**`not_two_sided` 在 S 档的占比（41%）远高于 M（17%）与 L（12%）**，这有其内在原因：
S 档按 `edit_ops` 定义就是「改动最少」的那批，改动少 → 更可能只碰了代码、
或只碰了测试 → 凑不出 F2P 需要的两侧。**S 档的稀缺是难度分档定义与 SWE-bench
范式的结构性冲突，不是筛子调松就能解决的。**

给 T5/T6 的三个选项（按代价从低到高）：

1. **接受 S 档 3–5 条，在报告里显式标注**。基线仍可算，但 S 档的置信区间会很宽
   （n=3 时单条抖动就是 ±33%）。**推荐**：MVP 阶段的验收目的是「链路能跑通」，
   而链路已经在 65 条上验证过了。
2. **放宽 S 档的 band 边界**（当前按 `edit_ops` 分档，见 `common.py` ③）。
   代价：要重跑 T1 之后的全链路，且分档口径一改，与 T4/T3 已落盘的
   `band` 字段全部不一致，`meta.json` 要重生成。
3. **回到 T1 扩候选池**（当前 182 条来自更大的会话池）。代价最高：T2 的
   `rebuild_failed` 率是 30%，要多拿 5 条 S 就得多筛约 40 条 S 候选。

⚠️ 无论选哪个，**都不要靠「把非 F2P 的 T0001/T0015 留下」来凑 S 档到 5** ——
那两条 `nop` 也能拿满分，凑进去等于用没有鉴别力的题充数，
基线数字会**偏高**且偏得看不出来。

### 9.2 4 条非 F2P 的淘汰决策（§5）

`meta/p2p.jsonl` 的 `f2p_check` 已给出机械判据，**T3 只标记不淘汰**。
T5 要决定的是「淘汰」还是「保留但排除出基线统计」。建议淘汰 ——
`oracle` 与 `nop` 同分的题对基线没有信息量。

淘汰后 61 条（S 3 / M 20 / L 38），仍高于「≥50 条」的验收下限。

### 9.3 T0029 的 base 曾因宿主网络失败一次，已重采

`d70d8380` 首轮 `docker build` 失败（`deb.debian.org` 取包超时），
**不是 task 缺陷**。已用 `--resume` 重采成功，现 50/50 全绿。

顺带修掉一个会**静默销毁数小时产物**的缺陷（见 §9.4）。

### 9.4 🔴 修掉采样脚本两处会静默毁产物 / 空转的缺陷

为了重采 T0029 而读代码时发现的，两处都不报错：

**① `--only-base` / `--limit` 会把 `p2p.jsonl` 从 50 行截断成 1 行。**
落盘那步是「已有记录 + 本轮结果」的合并覆写，但「已有记录」原先**只在
`--resume` 分支里读**。于是 `--only-base xxx` 重采单个 base 时，
合并的左半边是空字典 → 覆写后只剩这一个 base。
形态：命令成功退出、打印「采样完成」，而 49 个 base 的数小时产物没了。
修法：已有产物**无条件读入**，只有 `--overwrite` 才丢弃。

**② `--resume` 会把「采失败」的 base 也当成「已采过」跳过。**
`done` 集合原先不看 `ok` 字段，于是 T0029 这种失败记录会被永久跳过 ——
`--resume` 打印「50/50 完成」，而那条始终是 `ok:false`。
修法：跳过名单只收 `ok=true`，并在启动时打印「N 个失败的会重采」。

①、以及「不带 `--resume`/`--overwrite` 重跑必须拒绝执行」都加了回归
（`test_mvp.py` 的 ㉟），因为它们的共同形态是
**「命令报成功 + 产物悄悄不对」**，正是 R1 那一类。

### 9.5 T5 建镜像前必须先重建快照

`tasks/T####/environment/repo-snapshot.tar.gz`（65 份，429MB）**不入 git**。
换机器或清过工作区后先跑：

```bash
python3 scripts/mvp/t4-build-env.py          # 重建 65 份快照，校验和逐条比对
python3 scripts/mvp/t3-build-harbor-tasks.py --check-only   # 确认 65×12 齐备
```

第二条是本轮新加的（§4.1），**T5 应把它作为门禁的第一步** ——
它是唯一能发现「交付物在盘上被改坏」的检查，且不写盘、秒级完成。

### 9.6 flaky 只拦了一层：单文件级抖动

口径③（跑两次取交集）实测拦下 1 个 flaky（`tests/tool/bash-stability.test.ts`）。
但两次都在**同一台机器、同一时刻附近**跑，拦不住「换机器才复现」
或「低频抖动」的那类。T5 跑 oracle/nop 双向门禁时若出现 `p2p<1`，
**先怀疑 flaky，再怀疑 task 坏了** —— 判据是「同一条重跑两次结果是否一致」。
