# T4 — env 镜像 + 仓库快照（剔除泄漏面）+ 步骤④交叉验收

> 日期：2026-09-08 ｜ 脚本：`scripts/mvp/t4-build-env.py`
> 输入：`meta/resolved.jsonl`（T2 的 70 条 ok）+ mirror（只读）
> 产物：`tasks/T####/environment/{Dockerfile,repo-snapshot.tar.gz}` × 65
>       + `meta/snapshots.jsonl`（剔除清单 + 校验和）

## 一、结果

| 指标 | 数字 | 验收线 | 结论 |
|---|---|---|---|
| 快照产出 | **65** / 70 | — | ✅ |
| **步骤④交叉 `apply --check`** | **65 / 65 全过**（test+code 双 patch = 130 次） | 全过 | ✅ |
| 容器内泄漏扫描 | 65 份快照 **零违规** | 零违规 | ✅ |
| 快照校验和 | 65 / 65 与 `snapshots.jsonl` 逐条相符 | 全对 | ✅ |
| 真实资产存活 | 65 / 65 保有嵌套 skill `evals/` + `package.json` + `bun.lock` | 不误剔 | ✅ |
| env 不可构建 | 5（全部 `ruijie/iam-studio-fe`） | — | ⚠️ 见 §4 |
| 06/07/08 三月份 + monorepo 分支 | 4 个代表镜像**全部构建成功** | 均可构建 | ✅ |
| `--network none` 下跑完整 test | 三月份均可执行（3003 / 4604 / 7864 tests） | 可执行 | ✅ |
| 同 commit 跑两次结果一致 | 4577 pass / 27 fail，两次**逐字相同** | 一致 | ✅ |
| 单测 | **89 passed / 0 skipped**（新增 5 条 T4 回归） | 全绿 | ✅ |

难度分布 S 5 / M 22 / L 38（T2 是 S 5 / M 25 / L 40，差额即被挡的 5 条 iam）。
快照体积：中位数 2.5MB，区间 0.8–14.7MB，合计 429MB。剔除量 706–773 文件/条。

**存活 65 条 ≥ 方案的 40 条底线**，T5 门禁的输入量充足。

## 二、🔴 实测推翻了方案的一个前提（本轮最重要的一条）

方案 §3.8-E 假定「剔除 `packages/eval-framework/` 会打断 `bun install`，打断就淘汰该
task」。**这个因果是错的。照方案的预案执行，会白淘汰 47 条 task（存活从 65 掉到 18）。**

怎么发现的：剔除后 `bun install --frozen-lockfile` 确实报
`ENOENT: failed opening cache/package/version dir for package eval-framework`。
形态完全符合方案的预言 —— 但我用**未剔除的对照镜像**跑了同一条命令，**报同一个错**。

根因：50 条 sid base 里有 **47 条**把它声明成 **`file:../eval-framework`** ——
指向**仓库外**的兄弟目录，**任何快照里都不可能有它**。这是既有问题，与剔除无关。

两个分支的机理必须分开处理（判据落在 `eval_framework_mode()`）：

| 形态 | 条数 | 剔除是否打断 | 处置 |
|---|---|---|---|
| `file:../eval-framework`（仓库外） | 62 | ❌ 无关 | 镜像内 `/eval-framework` 造最小 stub 闭合 resolver |
| `workspace:*`（仓库内） | 3 | ✅ 真打断 | 只保留 `packages/eval-framework/package.json` 这一个 manifest，其余全剔 |

两处残余泄漏面都已核过，都是**可证不参与判分**的死物：

- **stub**：在 `/repo` **之外**，不属于仓库内容；且快照内**零处 import 它**
  （`grep -rlE "(from|require\(|import\()\s*['\"]eval-framework"` 命中 0）。
- **保留的真 manifest**：只有 name/version/deps 与 `"eval:run": "bun run core/runner.ts"`
  一条指针，而 `core/runner.ts` 已被剔除 —— **判分逻辑本体不在里面**。
  （合成 stub manifest 试过，破 `--frozen-lockfile`：真 manifest 的 deps 在 bun.lock
  里有记录，所以必须留真的那份。）

**教训**：「剔除后坏了」≠「剔除导致坏了」。**必须先跑未剔除的对照**，
否则会把「本来就坏」记成自己的锅，反向淘汰掉一批本可用的 task。
与 §3.8-F「绿着坏掉」同源，只是方向相反 —— 这次是**红着其实没坏**。

## 三、容器内泄漏扫描抓到的两件事（都不是推演出来的）

§4.9 要求「泄漏扫描在容器内查」。实践证明这条不能省 —— 两个漏洞都是它抓出来的，
只看剔除计数发现不了。

**① `lstrip('./')` 是字符集剥离，不是前缀剥离。**
`'.claude/x'.lstrip('./')` → `'claude/x'`，于是 `.claude/` 前缀**整个漏剔**，
泄漏面静默存活。我自己的探针就中了这一枪，容器内 `ls .claude` 一下就露出来。
必须用 `removeprefix('./')`。已固定为单测 ⑰。

**② 4 个评测工作流散落在 `.github/workflows/`，前缀清单抓不到。**
`judge-calibration.yml` / `eval-weekly.yml` / `eval-pr-smoke.yml` / `northstar-weekly.yml`
点名 `evals/**`、`scripts/eval/**`、`evals/_judge/calibration-set/`，
且 `judge-calibration.yml` 把校准集路径与 pairwise 判分方法写在注释里 ——
正是 §3.8-E 列的泄漏面。

处置按**文件粒度**、不整剔 `.github/`：同目录的 `ci.yml` / `docs-lint.yml` 是无关资产。
剔除安全性已核：存活测试引用的 `.github` 是 `tests/tool/glob.test.ts:19`
在**临时目录**里 `mkdirSync` 自建的，不读仓库这份。已固定为单测 ⑲。

## 四、剔除必须顶层锚定（差点打断存活测试）

`packages/core/src/skill/builtin/*/evals/` 下 61 个文件是 **skill 的 baseline case，
属于真实仓库资产**，且 `tests/skill/code-review.test.ts:66` 明确断言该目录存在。
按子串剔 `evals` 会打断这些**存活测试**。

所以判据是 `n == p or n.startswith(p)`（p 自带尾 `/`），只锚顶层；
尾 `/` 也是契约的一部分 —— 少了它 `evals` 会误命中 `evals-foo/`。

剔除对测试的净影响已用对照量化（同一 base，剔除 vs 未剔除，均 `--network none`）：

| | 未剔除 | 剔除后 | 差 |
|---|---|---|---|
| pass | 4809 | 4549 | 移除了 23 个测试文件 |
| fail | 59 | 55 | **新增失败 2 条** |

新增的 2 条是 `tests/skill/{incident-rca,security-audit}.test.ts` 断言
`scripts/eval/run-*-skill.ts` **落盘存在** —— 它们直接指向被剔的 runner，
属于「测试评测机制本身」，本就不该进 P2P 名单。
**T3 采 P2P 时必须在剔除后的快照上采**（§4.9 衔接①），这 2 条会自然落选。

## 五、⚠️ 5 条 `ruijie/iam-studio-fe` 没有可构建的 env

`anka-app/packages/{tag-studio,risk-query-studio}` 依赖
`@ruijie/{utils,eslint-config,typescript-config,crypto-interceptor}`，
它们**只存在于内网私有 registry**（地址见 base 时点的 `anka-app/.npmrc`，本报告
刻意不记具体 IP:端口 —— 判读只需要「私有 registry + 需凭据」这个事实），公网 registry 404
（实测 `ERR_PNPM_FETCH_404`）。拉它必须带 `anka-app/.npmrc` 里的 `_authToken`。

运行期 `--network none` 要求依赖在**构建期**装好，而装它就得把凭据烤进镜像 ——
**违反 §T4「不在容器里配私钥」**。所以这 5 条记 `drop_reason=registry_unreachable`，
不产快照。这是纪律决定，不是技术障碍：内网当前可达（`nc` 通），
但把凭据写进 task 镜像会让产物无法对外分发。

影响可接受：存活 65 条全是 `person/sid-code`，仍远超 40 条底线。
代价是**benchmark 退化为单仓库**，这条要写进 T7 的 dataset card Limitations。

## 六、步骤④为什么不能省，以及它非空转的证据

T2 在 **mirror 真实 commit** 上验 `apply --check`；T4 的快照**剔除过泄漏路径**。
patch 若触及被剔的路径，**两处验收都通过、容器里必然失败** —— 单看 T2 或单看 T4
都发现不了（§4.9 衔接②）。

65 条全过。但「全过」本身可疑，所以两层守卫各做了反向对照：

| 对照 | 注入 | 结果 |
|---|---|---|
| 路径守卫 | 把 `src/` `tests/` 也当泄漏面（必中 patch 路径） | **6/6 报红**，逐条列出被剔路径 |
| `apply --check` 层 | 往 hunk 上下文塞一行 base 里不存在的内容 | **4/4 报红** |
| 顶层锚定退化成子串匹配 | `--selftest-substring-leak` | **6/6 报红**，退出码 3 |

## 七、⚠️ 我的反向自证自己坏过一次（形态值得记）

第一版 `--selftest-substring-leak` 写成「剔除量 > 900 就算报红」。
实测最大只有 829 —— **阈值是拍的**，于是这个自证**自称检查却永远返回绿**，
正是它要防的那类「绿着坏掉」。

修法：不比绝对值，比**同一个 base 上严格版与退化版的差分**。
判据变成不变式而非魔法数 —— 退化后必然多剔到真实资产，所以「多剔量 > 0」
就是充分条件。修完后 6/6 报红，多剔 57 个/条。

**教训**：门禁自己也要被门禁验。写完自证要问「它在什么情况下会报红」，
并真的让它报一次 —— 我这次就是靠「它该红却是绿的」发现阈值是拍的。

## 八、其它实测细节

- **`git add -A` 会漏掉「被 gitignore 但已入库」的文件**。iam 的
  `anka-app/pnpm-lock.yaml` 正是这种，漏了它 `--frozen-lockfile` 直接失败。
  必须 `git add -A -f`。
- **`git archive` 而不是 `git bundle`**（沿用方案结论）。另外不落中间 tar 到磁盘 ——
  边流边剔，54 个 base 各 23MB，没必要在工作区堆一遍。
- **容器内 `git init` 单 commit**，历史深度实测 = 1：`test.sh` 需要 `git apply` 打
  test_patch、`git checkout -- tests/` 还原被 agent 动过的测试；且不带历史顺带
  消除「agent 翻 git log 找答案」这条泄漏路径。
- **429MB 快照已加进 `.gitignore`**：它含私有仓库源码，且是可复现产物
  （脚本 + mirror + `resolved.jsonl` 可重建），校验和记在 `snapshots.jsonl` 里。
- **`bun test` 命令从 base 时点的 `package.json` 读**（§3.5）：62 条是 `bun test`，
  3 条 monorepo base 是 `bun test --test-name-pattern '^(?!.*\[slow\])'`。
  已写进 `snapshots.jsonl` 的 `test_cmd`，供 T3 生成 `test.sh` 时引用。
- 镜像装了 `ripgrep`（实测 `/usr/bin/rg`，14.1.1）：`tests/tool/ripgrep.test.ts`
  有 17 处引用 `hasRipgrep` / `ripGrep`，不装它们在容器内必败（会污染 P2P 名单）。
  ⚠️ **这解释了本报告里两组不同的基线数**：§4 的对照表用的是**探针镜像**（未装
  ripgrep，4549 pass / 55 fail），§1 的一致性用的是**正式产物**（已装，4577 / 27）。
  差值主要就是那 13 个 ripgrep 用例。**比对基线时必须同镜像同条件** —— 跨镜像比数字
  会把「工具缺失」误读成「剔除打断了测试」。

## 九、交接给 T3

### 9.1 输入已就绪

| 交接物 | 路径 | 用途 |
|---|---|---|
| 剔除后快照 × 65 | `tasks/T####/environment/repo-snapshot.tar.gz` | **采 P2P 的唯一合法输入**（衔接①） |
| Dockerfile × 65 | `tasks/T####/environment/Dockerfile` | 已含 `git init` 单 commit + `bun install` |
| 快照元数据 | `meta/snapshots.jsonl`（70 行 = 65 ok + 5 blocked） | 回写 `meta.json` 的 `snapshot` 字段 |

`snapshots.jsonl` 可直接取用的字段：`tar_sha256` / `tar_bytes` / `n_files_kept` /
`n_files_stripped` / `stripped_top_dirs` / `eval_framework_mode` / `test_cmd` /
`cross_apply_check`。

⚠️ **快照本体不在 git 里**（429MB，`du` 看到 409MB 是块对齐差异，含私有仓库源码，
见 §8）。换机器或清过工作区后，
先 `python3 scripts/mvp/t4-build-env.py` 重建，再开 T3 —— 校验和会与
`snapshots.jsonl` 逐条比对，不一致说明 mirror 或 `resolved.jsonl` 变了。

### 9.2 🔴 P2P 必须采在剔除后的快照上（衔接①，采错了整批归零）

在 mirror 原始 commit 上采，会采到**已被剔除的测试** → 容器内那些文件不存在 →
**P2P 恒败 → 全部 reward=0**，形态像「task 太难」而不是「名单采错了」。

**现成的例子**（§4 已量化）：`tests/skill/{incident-rca,security-audit}.test.ts`
断言 `scripts/eval/run-*-skill.ts` 落盘存在，指向被剔的 runner。
在剔除后的快照上采样会自然排除它们，**不需要特殊处理** —— 但如果发现它们进了
P2P 名单，说明采样跑在了错误的文件树上。

### 9.3 ⚠️ T3 开工前需要定的三个决定（会改变实现，不是风格问题）

1. **P2P 采样是否按 base 去重**。65 条 task 覆盖 **50 个 unique base**，每个 base
   跑一次全量 `bun test` 实测 45–145 秒，串行约 40–90 分钟。按 base 去重可省 15 次
   （50 而非 65 次）再摊回 task。建议去重，但要接受这个耗时量级。
2. **「采样 20-30 个 P2P」的单位是文件还是用例**。方案 §T3 原文写「采样 20-30 个」，
   但同时要求**用文件路径而非 `--test-name-pattern` 选择**（因为测试名含中文与空格，
   实测样例 `切换权限模式`）。所以口径必须先定：20-30 个**文件**（推荐，与路径选择
   方式自洽）还是 20-30 个**用例**（则需把用例映射回文件，且同文件多用例时要做
   regex 转义并在 `meta.json` 标 `filter_mode: "name"`）。
3. **候选 P2P 是否跑两次取交集**。T4 只验了**全量** `bun test` 同 commit 两次一致
   （4577/27 逐字相同），**没有逐文件验 flaky**。P2P 名单一旦选进 flaky 测试，
   T5 门禁的判据「nop 的 p2p=1」会随机失败，且形态像 task 坏了。
   建议采样后对候选 P2P 文件跑两次取交集，多一轮时间换稳定。

### 9.4 ⚠️ 比对 `bun test` 基线必须同镜像同条件

本报告里出现过两组基线数，**它们不可互相比较**：

| 来源 | 镜像 | 结果 |
|---|---|---|
| §4 剔除影响对照表 | **探针镜像**（未装 ripgrep） | 4549 pass / 55 fail |
| §1 一致性验收 | **正式产物**（已装 ripgrep 14.1.1） | 4577 pass / 27 fail |

差值主要就是 `tests/tool/ripgrep.test.ts` 的 13 个用例。
**跨镜像比数字会把「工具缺失」误读成「剔除打断了测试」** ——
这与 §2 那个「红着其实没坏」是同一类错误，只是换了一层。
T3 若要重做剔除影响评估，请用正式产物镜像重跑双侧，不要引用 §4 的绝对值。

### 9.5 可复用的本地镜像（非必需，可随时删）

T4 验收时建了 4 个代表镜像，覆盖 06/07/08 三个月份 + monorepo 分支，T5 跑门禁可复用：

| 镜像 | base | 分支 | 大小 |
|---|---|---|---|
| `t4:T0006` | `5a092172`（2026-06） | external | 705MB |
| `t4:T0001` | `9b5706c0`（2026-07） | external | 716MB |
| `t4:T0002` | `76b60150`（2026-08） | external | 807MB |
| `t4:T0043` | `16cb1472`（monorepo） | workspace | 932MB |

不需要时：`docker rmi t4:T0001 t4:T0002 t4:T0006 t4:T0043`（共约 3.1GB）。
注意 colima profile 是 **swebench**，`colima status` 不带 `-p swebench` 会误报未运行。

## 十、遗留问题（不属于 T4 范围，但必须有人接）

| # | 遗留项 | 归属 | 不做的后果 |
|---|---|---|---|
| 1 | dataset card 的 Limitations 要写**单仓库**：5 条 iam 因私有 registry 需凭据被挡（§5），存活 65 条全是 `person/sid-code` | **T7** | 对外发布时隐瞒了覆盖面局限，属于数据集披露缺陷 |
| 2 | dataset card 要写**两处残余泄漏面**及其论证：`/eval-framework` stub（在 `/repo` 外、零处 import）与保留的真 manifest（判分本体已剔）（§2） | **T7** | 同上；且这两处是主动决策，不写等于隐藏 |
| 3 | **iam 的 5 条能否救回**：内网 registry 当前可达，技术上可装依赖，但需把 `_authToken` 烤进镜像。若将来有内网私服镜像或 vendored 依赖方案，这 5 条可回归、benchmark 恢复双仓库 | v0.3 | 无损失，但 benchmark 长期停留在单仓库 |
| 4 | **快照按 base 去重**：65 份快照对应 50 个 unique base，有 15 份是重复内容（tar 合计 429MB → 去重后 324MB） | v0.3 | 磁盘冗余，当前规模下不是问题（方案 §T4「已知坑」也主张先用笨办法） |
| 5 | **T6 的泄漏扫描要在容器内查**，不能只复用 T4 的剔除清单 —— T4 的两处漏剔都是容器内 `ls` 抓出来的，清单本身不自证完备（§3） | **T6** | 漏剔的泄漏面静默存活，agent 可直接读到答案 |
| 6 | **T5/T6 的门禁要自己验一次会不会报红**。T4 的反向自证阈值是拍的，导致它自称检查却永远返绿（§7） | **T5 / T6** | 门禁空转，「全绿」不代表真的通过 |
