# Agent-Traj-Bench v0.2-mini — Dataset Card

> 生成于 2026-09-17 02:32 UTC，由 `scripts/t7-report.py --card` 从产物**纯复算**。⛔ 本文没有一个手写数字。

## 这是什么

从**真实 Claude Code / Codex 生产会话轨迹**反解出的 SWE-bench 形态 benchmark：每条 task 给一个 base 快照 + 开发者当时那句话，判分看指定测试从红转绿。

**定位是「真实生产交互衍生的补充 benchmark」，⛔ 不是通用 SWE 基准** ——单开发者、单仓库、两类任务（见 Limitations 第 2 / 4 条）。

## 规模与构成

| 项 | 值 |
|---|---|
| 交付 task 数 | **39** |
| 来源仓库 | `person/sid-code` 39 |
| 任务类型 | `test_authoring` 21 / `bug_fix` 18 |
| 难度分档（`edit_ops` 代理指标） | `M` 12 / `L` 27　⚠️ **S 档为 0** |
| 题面信息量分级 | `C` 4 / `B` 4 / `A1` 11 / `A2` 20 |
| 轨迹采集工具 | `claude_code` 39 |
| 轨迹里的原始模型 | `claude-opus-4-8` 22 / `claude-opus-5` 11 / `claude-opus-4-8[1m]` 6 |
| 冻结批次指纹 | `91be9a5d90d8` |

> **题面信息量分级**：`A2` 剥掉路径后只剩一句祈使句 ／ `A1` 点名交付物 ／ `B` 文件名点出症状 ／ `C` 散文自带可复现症状。信息量 C > B > A1 > A2。
> 🔴 这个维度与难度分档**不交叉**，两张表各看一个维度。

## 是怎么筛出来的（漏斗）

| 级 | 剩余 | 取数源 |
|---|---|---|
| 冻结批次**会话**（四通道：claude_code 7820 / codex 317 / short_id 248 / sid_code 177） | **8562** | `meta/batch-v0.2.json` |
| 清洗后保留的**会话**（去空/过短/自指等） | **4381** | `meta/phase1/filtered-v2.stats.json` |
| 切分出的**任务单元**（⚠️ 换单位，1.762 个/会话） | **7692** | `meta/phase1/units-v2.stats.json` |
| 其中两端边界均 high 置信的单元 | **2937** | `meta/candidates.stats.json` |
| T1 候选（八级筛选后） | **182** | `meta/candidates.stats.json` |
| T2 反解出 base+patch | **70** | `meta/resolved.stats.json` |
| T3 生成 harbor task | **65** | `meta/tasks.stats.json` |
| T5 三道门禁存活 | **40** | `meta/gate.jsonl` |
| **T6 人工过目后交付** | **39** | `reports/t6-recheck/survivors.json` |

> ⚠️ 第 3 行比第 2 行大不是笔误：单位从「会话」换成「任务单元」。

三道机械门禁（`oracle` / `nop` / `oracle -k 3`）后 **100% 人工过目**（非抽样）。淘汰归因合计 26 条：

- `src/ink/` 从未入库 → 不可复现（T5 门禁①）：**7** 条
- oracle reward=0，gold patch 打上后 F2P 仍红（T5 门禁①）：**12** 条
- 假 task：nop 下 f2p=1（T5 门禁②）：**4** 条
- 参考解自身缺陷 `gold_patch_regression` / `_broken`（T6 §1）：**2** 条
- 题面与判分对象无关 + 提示词模板残留（T6 §6.1）：**1** 条

## 基线读数

🔴 **以下数字是 `t8-rerun` 那一批的读数，⛔ 不是数据集的固有属性** ——pass@1 是「模型 × 题集 × 配置」的联合结果，换任一项都会变。

| 项 | 值 |
|---|---|
| 模型 | origin-deepseek-v4-1-flash |
| **pass@1** | **37.8%**（14 / 37） |
| 95% Wilson | [24.1%, 53.9%]，半宽 ±14.9pp |
| 分母 | `scored=37`，infra 排除 2 条（T0009, T0022） |
| k | 1（`-n 6`） |
| 实付 | $26.214353（38/39 个 trial 有成本值） |

> **分母是 37 而不是 39**：分母是 scored（参与计分的 task）。基础设施故障（抛异常 / verifier 未写分）排除出分母 —— 算进去等于把它记成答错。⛔ 不是 40（那是 T5 门禁的结论，含 T0005）。

完整报告（13 节，含真 0/假 0 逐条归因）：`reports/baseline-v0.2-mini-t8-rerun.md`　机器可读取数源：`reports/t8-rerun/summary.json`

🔴 **只跑了 1 个模型 × k=1** ⇒ ⛔ **不能**用本数据集比较模型强弱（方案要求 ≥2 模型 × k=3 才谈模型间差异），也**不能**把这个点估计当作「模型在真实任务上的能力」—— 半宽 ±14.9pp 的区间比多数模型间差距还宽。

## 怎么跑

**⛔ 这两件事不是一回事**，混了就会跑出另一个数字：

| 你想复现什么 | 入口 | 题面形态 |
|---|---|---|
| **题集本身**（39 条能不能跑起来） | `harbor run -p tasks -n 6` | 交付原句，**不含**下面两段 |
| **基线读数**（t8-rerun 那批的 pass@1） | `~/.local/share/uv/tools/harbor/bin/python scripts/t8-rerun.py` | 原句 **+ 两段现拼** |

🔴 **基线跑的题面不在 `tasks/` 里**。`t8-rerun.py` 把 39 条复制到 stage（`reports/t8-rerun/tasks/`，已 gitignore）并在原句之外拼了两段：

- **`## 引用文档原文`**（修复①，本批 `inline_docs=True`）—— 把题面点名的那份文档原文内联进去。取数 `reports/t8-fix/docs/`（37 份原文已入库）+ `docs-index.json`。⚠️ 本批 **34/39** 条题面真的拼上了这段（其余的没点名任何可取到的文档）—— ⛔ 与「文档份数」是两个数。
- **`## 验收标准`**（修复③，本批 `f2p_list=True`）—— 只给 F2P 测试的**路径清单**，⛔ 不给测试内容（给内容就能从断言反推实现）。取数各 task 的 `tests/f2p.json`。

⇒ 照第一行跑（`tasks/` 原句）等于**关掉这两项修复**，而它们正是本批 pass@1 不是 0% 的原因（第一轮 `baseline/` 无此两段，实测 0/39）。

其余必控参数（本批实测）：`max_turns=120`、`max_budget_usd=1.8`、`-n 6`、`--agent-timeout-multiplier 3.0`。

⚠️ **`environment/repo-snapshot.tar.gz` 不在 git 里**（65 份，每份 0.8–14.0MB，见 `.gitignore`）⇒ 新克隆的仓库**跑不起来**，须先重建 —— 两条路径：
> - **有快照在手**（HF 仓的 `snapshots/`）：`scripts/t4-build-env.py --from-snapshots <dir>`，逐份校验 `tar_sha256`，任一条不符即报红退出 4。
> - **有 mirror 在手**（仅采集机）：`scripts/t4-build-env.py` 从 mirror 重建。
> `meta/snapshots.jsonl` 存了每份的 `tar_sha256` 与 `tar_bytes`，可逐条校验重建结果。

## Limitations（主动披露）

🔴 **16 条，与报告 §11 同源**（`_limitations()`，⛔ 两处不各写一份）。不读这一节就引用上面的数字，会把已知缺陷当成结论。

1. **仅采用高置信切分单元**（2937/7692，38.2%）—— 低置信部分的切分债务**隔离未清**，是没用，不是修好了。
2. 🔴 **单一开发者、单一仓库**。原计划双仓库，T4 实测后 `ruijie/iam-studio-fe` 的 5 条**全部被挡**（见第 12 条），交付 39 条**全部**来自 `person/sid-code`。⛔ 这不是「以某仓库为主」，是**彻底**单仓库。定位是「真实生产交互衍生的补充 benchmark」，不是通用 SWE 基准。
3. **自指污染**：sid-code 本身就是 coding agent，仓库含 SWE-bench 判分逻辑与 prompt 模板，约 14% commit 与 evals 相关。已用 `excluded-paths.txt` 强制排除四个前缀，但仍须披露。
4. 🔴 **任务类型覆盖窄**：交付 39 条实测**只有两类** —— `bug_fix` 18 / `test_authoring` 21。`feature_impl` 10 与 `refactor` 1 在 T1/T2 尚存，但 T3 生成的 65 条里已一条不剩（与另外 106 条一并未生成，未逐条归因）。⛔ 别写成「未过门禁」—— 门禁那层看到的 65 条里本就没有。且 `test_authoring` 占 21/39，须连带披露「测试自己测自己」的退化风险。
5. 🔴 **难度锚点是代理指标**：用 `edit_ops` 而非真实解题难度，**且 S 档实测为 0 条**，只剩 M 12 / L 27 两档 ⇒ **不构成三档单调性证据**。⛔ 不要写成「锚点无效」—— 样本量为 0 时锚点既未被证伪也未被证实，那是两回事。
6. **样本量小、统计功效低**：n=39 的 pass@1 置信区间宽，模型间差异须谨慎解读 ——所以本报告每格都给 Wilson 区间，不只给点估计。
7. **gold patch 来自轨迹反解，不是开发者真实 commit**。优点是自包含，缺点是可能不是最优解法。
8. **无污染检测**：base_commit 早于多数模型训练截止，存在训练集污染可能。这一项**未做**，不假装做了。
9. **base 快照不带 git 历史**：容器内是 `git init` 的单 commit，agent 看不到真实提交历史。副作用是消除了「翻 git log 找答案」的泄漏路径，但也偏离真实开发环境。
10. **继承 harbor 的六类静默失效**（verifier 恒返值、双层超时互掩、并发失真等）。已按其判据设门禁（`-n 6`、reward 双源核对），但**不能声称已全部排除**。
11. **单一执行环境**：只在本机 colima + arm64 上验证过。换 x64 或换 Docker 后端须重跑门禁，结果不保证可比。
12. 🔴 **2 条按 infra 排除出分母 ⇒ 分母是 37，不是 39**（`T0009`, `T0022`）。「39 条 benchmark」与「37 条参与计分」是**两个数** ——⛔ 别拿 39 当 pass@1 的分母（那会把仪器故障记成答错）。　· `T0009`（`infra_agent_not_launched`）：**结构性**：题面超 Linux `MAX_ARG_STRLEN`（131,072 B，容器内实测 131,000 过 / 131,060 起 `Argument list too long`）⇒ `bash -c` 拒绝 exec，agent **一个字没跑**（退出码 255），而 verifier 照常打分 ⇒ 假 0。🔴 **换模型重跑必然复现** —— 与模型能力无关，是题面装不进命令行。本批成因：单份内联文档 130,285 B（第二大的 2.1 倍，孤立离群）　· `T0022`（`infra_upstream_disconnect`）：**偶发但本批两次都中**：上游 LLM 链路断连（`socket connection was closed unexpectedly`），verifier 照常打分 ⇒ 假 0。首轮 61 轮时断、补跑 24 轮又断
13. **5 条 task 因私有 registry 被排除**：`ruijie/iam-studio-fe` 的 `@ruijie/*` 依赖只存在于内网私服，公网 404，装它必须把 `_authToken` 烤进镜像 —— 违反「不在容器里配私钥」。🔴 这是**纪律决定而非技术障碍**（内网当时可达）。后果就是第 2 条的单仓库；将来有内网镜像或 vendored 方案时这 5 条可回归。
14. **7 条 task 因 `src/ink/` 从未入库而不可复现**（T5 门禁① 淘汰）。这是**采集侧**问题：轨迹引用了从未提交进仓库的路径，反解出的 base 里自然没有它。v0.3 的动作是在 T1 筛选链里排除「引用未入库路径」的会话。
15. 🔴 **4 条题面的文件名点出了修法所需机制，这 4 条得分可能偏高**（`T0002` / `T0038` / `T0040` / `T0065`，取数 `meta.json` 的 `leakage.filename_specificity == "mechanism"`）。⛔ **不是 8 条** —— `reports/t6-recheck/filename-leak.json` 只做了「带信息 8 条 vs 仅主题 27 条」的粗二分，**没有 mechanism/symptom 这一层**；照它取会把 T6 明确判为「正常题面」的另 4 条 symptom 也算进来（T6 §4.2 的原话）。另有 4 条无文件名可判，回写为 `null`（**不是 `false`**）。
16. **快照内有两处刻意保留的残余泄漏面**：① 62 条 external 分支在容器 `/eval-framework`（**`/repo` 之外**）放了 name/version/private 三键的 stub，用于闭合 `file:../eval-framework` 依赖；② 3 条 monorepo base 保留了 `packages/eval-framework/package.json`。**可证不参与判分**：两者都不含判分逻辑与测试代码，且容器内泄漏扫描零违规（扫描器另有 5/5 反向自证）。⛔ 不能只写「已剔除泄漏面」了事。

## 这批数字不能用来说什么

- ⛔ **不能**说「模型在真实开发任务上只能解 38%」——单模型、k=1、n=37，且题面信息量分级实测主导了分数（报告 §3）。
- ⛔ **不能**拿它与 SWE-bench 等公开基准比数字：题集构造、判分口径、题面信息量都不同源。
- ⛔ **不能**说「已排除训练集污染」—— 污染检测**未做**（Limitations 第 8 条）。
- ⛔ **不能**拿 39 当 pass@1 的分母（那会把 2 条仪器故障记成答错）。

## 复算

```bash
PY=~/.local/share/uv/tools/harbor/bin/python   # ⛔ 系统 python3 没有 harbor 包
$PY scripts/t7-report.py --runs t8-rerun --card   # $0，不跑任何模型
```
