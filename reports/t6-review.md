# T6 — 人工过目 100%（六项检查逐条结论）

> 日期：2026-09-11｜输入：T5 三道门禁存活的 **40 条** + `meta/gate.jsonl` + `meta/resolved.jsonl`
> 脚本：`scripts/mvp/t6-leak-scan.py`（容器内泄漏扫描）、`scripts/mvp/t6-writeback.py`（回写 meta）
> 产物：本报告 + `meta.json` 的 `leakage.leak_scan_passed` / `solvability.gold_verified`
> 明细：`reports/t6-recheck/`（复跑判定、扫描产物、逐条分级、自证记录）

## 结论先说

| 项 | 结果 |
|---|---|
| 过目覆盖 | **40/40（100%，非抽样）** |
| 淘汰 | **1 条（T0005）** —— 题面与判分对象完全无关 + 含提示词模板残留 |
| 存活 | **39 条** —— 🔴 **已跌破方案「≥40」底线**，处置权交 T7（见 §6） |
| T5 遗留的 T0017/T0027 | 复跑 6/6 全红且失败集合三次一致 → **两条都淘汰**，非 flaky（不增加存活） |
| 最有价值的发现 | **35/40 的题面指向一个容器内不存在、且内容含标准答案的文档** —— 这不是剔除失误，是数据源的结构性问题（§3） |

---

## 一、T5 交接 #4 先做：T0017 / T0027 复跑定性

T5 把这两条列为「待复查」，并指出这是 T6 **唯一可能增加存活数**的动作。已做完，结论是不增加。

```
harbor run -p reports/t6-recheck/tasks -a oracle -n 1 -k 3 \
  -o reports/t6-recheck/oracle-k3 --verifier-timeout-multiplier 6
```

| task | 3 次结果 | 失败 P2P 集合 | 根因 | 判定 |
|---|---|---|---|---|
| `T0017` | 3/3 红 | 三次**完全一致**：`stream-interrupt-recovery` + `stream-level-error` | gold patch 引入时序回归，4 个用例 `timed out after 5000ms` | 淘汰 |
| `T0027` | 3/3 红 | 三次**完全一致**：`abort-graceful` + `turn-hard-timeout` | **gold patch 自身坏了**（见下） | 淘汰 |

**T0017 的归因用了对照，不是只看红**：同一批 P2P 在 `nop` 下 **524 pass / 0 fail**，在 `oracle` 下才 timeout —— 红只出现在打了 gold patch 之后，所以是补丁的问题，不是测试慢。

**T0027 是硬缺陷，一眼可判**：

```
ReferenceError: detectInvestigationContext is not defined
    at queryLoop (/repo/src/query/loop.ts:476:11)
```

补丁把 `detectInvestigationContext` 定义在 `src/query/hypothesis-guide.ts`，却**没给 `loop.ts` 加任何 import 行**（实测：该文件的新增行里 import 数为 0）。这是确定性错误，与 flaky 无关。

> 🔧 **纠正 T5 报告的一处归类**：T5 把这两条放在「oracle 基础设施问题（**修环境，不要动 task**）」下。复跑证明二者都是 task/参考解自身缺陷 —— 尤其 T0027 缺 import，改环境永远修不好。归类错会让下游误以为「补个环境就能救回 2 条」。

---

## 二、六项检查逐项结果

| # | 检查项 | 结果 | 判据来源 |
|---|---|---|---|
| ① | 单一任务 | 22/40 题面含「所有问题 / 全部 / 不要遗漏」类字样 —— **量出来但不淘汰**（见下） | 题面文本 |
| ② | 解法未泄漏 | 容器内扫描零违规；另发现 8 条**文件名点出根因**（§4） | `t6-leak-scan.py` + 题面 |
| ③ | 题面自足 | **A2 20 / A1 11 / B 4 / C 4 / X 1** —— 这是本轮核心发现（§3） | 逐条手读 40 份 |
| ④ | 判重 | 5 对 F2P 文件重叠，逐对核后**均非同一件事**，不淘汰（§5） | base + F2P 集合 + 题面 |
| ⑤ | 容器内无泄漏 | 见 §4（在容器里重扫，**没有复用 T4 清单**） | `t6-leak-scan.py` |
| ⑥ | F2P 有因果 | **40/40 成立**，三类机械证据（§5） | `nop` 侧 `f2p.log` + gold patch |

**①「一题多事」为什么只量不淘汰**：这 22 条的「所有问题」指的是**那份文档里列的问题**，而判分只认 `f2p.json` 里的具体测试文件 —— 范围由 F2P 名单收窄，不会因为题面说「全部」就要求 agent 改更多。真正的问题是文档不可见（§3），而不是「一题多事」。按 T5 交接 #1「只淘汰真有题面问题的」，不动。

---

## 三、🔴 核心发现：35/40 的题面指向一个容器内不存在、且含标准答案的文档

### 3.1 现象

40 条里 **35 条**的题面主体是「读某个文档 + 照做」，引用 37 个文档路径。**这 37 个在容器内全部不存在。**

```
T0002  《docs/bugfixes/todo/20260807-遥测落盘恒空-配置undefined覆盖默认值.md》 请按照方案执行代码修复
T0010  《docs/bugfixes/todo/20260803-单测污染用户遥测数据-隔离缺口根治方案.md》 请你完成文档中的所有任务和需求
T0050  《docs/bugfixes/todo/子代理委托机制-现状对照与缺口修复方案.md》 请修复文档中所有问题，不要遗漏
```

剥掉打不开的路径后，**20 条（A2 档）的题面只剩一句祈使句**，最短的 10 个字（`帮我排查文档中的问题`）。

### 3.2 这不是 T4 剔除失误 —— 根因在数据源

一开始我以为是 T4 剔泄漏面时把 `docs/` 剔掉了。查 mirror 推翻了这个假设：

```bash
git -C $MIRROR log --all --oneline -- 'docs/**'   # 输出为空
```

**`docs/` 从未进入过仓库的任何提交**。它是作者本地的工作目录，只存在于宿主机。所以：

- 与 T4 无关，T4 没有剔错任何东西
- **回填不可行，且会更糟**：这些文档在宿主机上找得到 31/37 份（在**另一个仓库** `docs-research/` 里），但它们含**标准答案**。实测 T0026 引用的文档里逐字写着：

  ```markdown
  将 src/tool/lsp.ts 中的 filterGitignored 函数从 module-private 改为 export：
  // 改后
  export async function filterGitignored(paths: string[], cwd: string): Promise<Set<string>>
  ```
  ```typescript
  // 文档里还直接给出了测试代码
  import { filterGitignored } from "../../src/tool/lsp.ts";
  describe("G9：filterGitignored", () => { ...
  ```

  而 `gold_patch` 新增的就是 `export function filterGitignored`。逐条比对：**31 份可找回的文档里，21 份含 gold_patch 新增的专有标识符**（判据：补丁新增行里定义的标识符，长度 ≥8 且排除 `result`/`text`/`base` 这类通用词；不收紧的话是 26 份，但那里面混着通用词，不足为证）。命中的都是专名，例如 `T0022` 的 `ACCEPT_EDITS_FS_COMMANDS`、`T0064` 的 `SkillPermissionRules`、`T0059` 的 `getBuiltInAgentDefinitions`。把这些文档放进容器，等于把答案和测试一起发给 agent。

### 3.3 为什么三道门禁一条都没抓到

因为 **`oracle` 和 `nop` 都不读 `instruction.md`**。已在全 40 条上核过：`solution/` 与 `tests/` 下**零处**引用该文件（`solve.sh` 只有一行 `git apply --3way /solution/gold_patch.diff`）。题面写什么都不影响 `oracle` 拿 1 分。

> 核这条时先撞了两次误报，值得记下来：先搜 `instruction` 命中 3 处，都是 gold_patch **注释**里提到「MCP server instructions」；收紧成 `/instruction` 后仍命中 1 处，是 `mcp/instructions-delta.ts` 这个文件名。**子串判据在这里天然不可靠**，要落到「是否真的读那个文件」才算数。

**这正是 T6 存在的理由**，也是「方案敢跳过 κ 校准」的那个人工环节唯一能抓到的东西 —— 机械门禁在这个维度上完全失明。

### 3.4 分级明细（逐条手读 40 份）

| 分级 | 含义 | 条数 | task |
|---|---|---|---|
| **C** | 散文自带可复现症状，不依赖文档也能理解 | 4 | `T0011` `T0018` `T0036` `T0051` |
| **B** | 文件名点出具体症状（挂死/不显示/缺少选项） | 4 | `T0002` `T0040` `T0054` `T0063` |
| **A1** | 点名了具体交付物，缺验收细节 | 11 | `T0003` `T0009` `T0013` `T0020` `T0024` `T0026` `T0031` `T0033` `T0045` `T0047` `T0049` |
| **A2** | 只剩祈使句 + 主题级文件名，**要做什么未定** | 20 | `T0007` `T0008` `T0010` `T0012` `T0014` `T0022` `T0028` `T0029` `T0034` `T0038` `T0039` `T0042` `T0050` `T0052` `T0055` `T0056` `T0059` `T0062` `T0064` `T0065` |
| **X** | 题面与判分对象无关 → **淘汰** | 1 | `T0005` |

**每组的分布（T7 分组报基线时直接用，`reports/t6-recheck/t7-grade-groups.json` 可机读）**：

| 分级 | 条数 | band | category | F2P 中位数 |
|---|---|---|---|---|
| C | 4 | M 2 / L 2 | test_authoring 3 / bug_fix 1 | 1.5 |
| B | 4 | M 2 / L 2 | bug_fix 3 / test_authoring 1 | 1.0 |
| A1 | 11 | M 2 / L 9 | test_authoring 10 / bug_fix 1 | 2.0 |
| A2 | 20 | M 6 / L 14 | bug_fix 13 / test_authoring 7 | 2.0 |

（共 39 条，已剔除 `T0005`。P2P 一律 30 条。）

⚠️ **A2 组占一半（20/39），且以 `bug_fix` 为主（13 条）** —— 如果基线出现「bug_fix 显著低于
test_authoring」，先排除这个混淆因素再下结论：A2 的题面信息量最低，而它恰好集中在 bug_fix。

A1 档点名的交付物（agent 至少知道要造什么）：

| task | 题面点名的交付物 |
|---|---|
| `T0013` | MCP OAuth 全链路 |
| `T0020` | AskUserQuestionTool |
| `T0031` | ToolSearchTool |
| `T0047` | Bash 注入防护深化 |
| `T0024` | 批次 D：内容级 tracing flag 灰度 + 录制回放能力 |
| `T0003` / `T0009` | 第 2 批：功能等同未上线（第 17、22、19 条）／第 5 批：消息保真（第 5、8、6 条） |

### 3.5 为什么 A2 的 20 条不淘汰

三个理由，按 T5 交接 #1（只淘汰真有题面问题的，别顺手清理）：

1. **淘汰它们等于交付 19 条**，远低于底线，这一版就没有基线可谈
2. **题面不自足不等于不可解**：A2 的判分对象是明确的（F2P 测试文件），一个强 agent 在 `/repo` 里搜索仍可能定位到缺陷。**它们测的是「低信息量指令下的自主定位能力」** —— 这个能力本身有意义，只是与 SWE-bench 的题面范式不同
3. **方案明令不许改题面**（§4 T6 已知坑一：改写题面 = 引入人工润色，尺度不可机械复现）。所以此处只能「量出来」，交 T7 决定怎么标注

⚠️ **但 T7 必须在 dataset card 里写明这一条**，且**基线数字必须按分级分组报**。否则读者会把「A2 档得分低」误读成模型能力差，而真实原因是题面缺信息。

---

## 四、检查②⑤：泄漏扫描（容器内重扫，未复用 T4 清单）

按 T4 交接 #5 与方案 §4 T6 的要求，**在容器里扫产物，不查打包脚本的意图**：

```bash
docker run --rm --network none --entrypoint find <task-image> / \
  -path /proc -prune -o -path /sys -prune -o -path /dev -prune -o \
  \( -path '*evals*' -o -name '*calibration*' -o -path '*bugfixes*' \
     -o -path '*judge*' -o -path '*external-benchmark*' -o -path '*harbor*' \
     -o -path '*.claude*' -o -path '*eval-framework*' \) -print
```

**结果：见 `reports/t6-recheck/leak-scan-container.jsonl`（逐条 `n_hits` / `violations` / `benign_n`）。已扫条目零违规**，命中项全部落在三类已核良性里：

| 良性类 | 每条命中数 | 为什么不是泄漏 |
|---|---|---|
| `src/skill/builtin/*/evals/` | 65 | skill baseline case，`tests/skill/code-review.test.ts:54` 断言该目录存在、`:58` 断言 ≥10 条 yaml。**剔了会打断存活测试** |
| `/eval-framework` | 2 | external 分支 stub，内容只有 name/version/private 三键，快照内零处 import |
| `/repo/node_modules/eval-framework` | 2 | 同一个 stub 被 `bun install` 链入，**构建期产物，读 tar 看不到** |

> ⚠️ T4 报告把第一类记作 `packages/*/skill/builtin/*/evals/`（monorepo 形态）。本批 40 条全是 external 形态，落在 `src/` 下 —— **同一类，路径不同**。照 T4 的路径去核会以为「没命中」。

> ⚠️ **`T0002` 那一行是加宽判据前扫的，命中数 65 而非 69** —— 差的 4 项正是
> `/eval-framework` 与 `node_modules/eval-framework`（判据补入前扫描器看不见它们）。
> 结论同为零违规，但**分母不同不能并排采信** —— 已按新判据复扫对齐，
> 见 `leak-scan-container.jsonl` 里 `T0002` 的 `n_hits`（应为 69，与其余 39 条一致）。

### 4.0 前提核验：我扫的容器 == harbor 实跑的容器

「容器内零违规」只有在**扫描容器与实跑容器看到同一份文件树**时才作数。若 harbor 会往容器里挂宿主目录，挂进来的泄漏面我这边根本扫不到 —— 整个检查⑤就成了空转。已核三点（产物 `reports/t6-recheck/scan-validity.json`）：

| 项 | 判据 | 结论 |
|---|---|---|
| 镜像同源 | 扫描用 task 自己的 `environment/Dockerfile` + `environment/` 作构建上下文，与 harbor 读的是同两个 | 同一份镜像 |
| 无额外挂载 | 实跑 trial 的 `config.json` 只有 `task.path`/`trial_name`/`trials_dir`/`verifier_timeout_multiplier`/`job_id`，**零挂载配置**；`trial.log` 里零处 volume/mount/bind；判分产物靠「Collecting main service artifacts」拷出来，不靠挂载。harbor 源码的 volumes/mount 逻辑全在 ack/gke/islo 云后端，本地 docker 后端不走 | harbor 不挂宿主目录 → 不存在「挂进来的泄漏面扫不到」 |
| 网络不影响文件树 | 扫描与实跑都是 `--network none`；文件树在构建期就定了，运行期网络与它无关 | 无影响 |

**两处刻意的差异及其安全性**：① `--entrypoint find` 覆盖入口 —— 只读文件不跑 `test.sh`，不改容器状态；② prune 掉 `/proc /sys /dev` —— 内核虚拟文件系统，不属于 task 内容，`/` 下其余全扫（harbor/judge 若被误放到根下仍能发现）。

### 4.1 扫描器自己也被扫描（T4 交接 #6 的教训）

T4 的自证阈值是拍的，导致它自称检查却永远返绿。所以这次先注入必然泄漏的文件，要求扫描器报红且**违规路径指向注入点**：

| 变异体 | 注入 | 期望 | 结果 |
|---|---|---|---|
| `L0-control` | 未注入 | 0 违规 | ✅ 命中 69 全良性 |
| `L1` | `/repo/docs/bugfixes/leak.md` | 报红 | ✅ 违规 2，首项 `/repo/docs/bugfixes` |
| `L2` | `/repo/evals/_judge/calibration-set/` | 报红 | ✅ 违规 4，首项 `/repo/evals` |
| `L3` | `/repo/.claude/settings.json` | 报红 | ✅ 违规 2，首项 `/repo/.claude` |
| `L4` | `/repo/external-benchmarks/harbor/` | 报红 | ✅ 违规 3，首项 `/repo/external-benchmarks` |

**5/5 通过。自证过程中修掉扫描器两处缺陷**（不修就是假绿）：

1. 🔴 **方案给的 `-path '*evals*'` 匹配不到 `/eval-framework`（少个 s）** —— 而它正是方案自己点名的三类良性之一，等于扫描器对它**完全失明**
2. 但放宽成 `*eval*` 会把 `timeval`（perl 头文件）、`evaluator.ts`（仓库真实源码）扫成违规 —— **噪声淹掉真违规比漏看更危险**。改为精确单列 `eval-framework`

### 4.2 另一类泄漏：题面文件名本身点出根因

文档打不开，但**路径文本留在 `instruction.md` 里，agent 读得到**。8 条的文件名点出了根因：

| task | 文件名 | 泄漏程度 |
|---|---|---|
| `T0002` | `遥测落盘恒空-配置undefined覆盖默认值` | 🔴 **最重**：直接说出机制，而 gold_patch 干的就是「只在有值时才写入，避免 undefined 覆盖默认值」 |
| `T0040` | `Anthropic代理流式挂死-三层超时失效根因分析` | 点出「三层超时」这个机制 |
| `T0038` | `重复注入根因-system附件与user-reminder双通道` | 点出双通道 |
| `T0065` | `builtin-skill附属文件不释放+delegate读不到references` | 点出两处症状 |
| `T0010` `T0014` `T0054` `T0063` | 污染 / 误伤 / 缺少选项 / 不显示 | 仅症状，属正常题面 |

**不淘汰**：这些是 bug 标题的自然形态，症状描述本就该给 agent。只有 `T0002` 接近「把修法写在题面上」。

**口径要分三级，不是「8 条 vs 其余」**（已回写为 `meta.json` 的 `leakage.filename_specificity`）：

| 级 | 条数 | 是谁 | T7 怎么用 |
|---|---|---|---|
| `mechanism` | **4** | `T0002` `T0040` `T0038` `T0065` | 🔴 **文件名点出修法所需的机制**，得分可能偏高 —— dataset card 要标注的是这 4 条 |
| `symptom` | 4 | `T0010` `T0014` `T0054` `T0063` | 仅症状词（污染/误伤/缺少选项/不显示），**属正常题面**，不必打折扣 |
| `topic_only` | 27 | 其余 | 文件名只点主题 |

⚠️ `reports/t6-recheck/filename-leak.json` 只做了「带信息 8 条 vs 仅主题 27 条」的二分，**没有 mechanism/symptom 这一层** —— 照它的二分给 8 条一律打折扣，会把上表明确判为「正常题面」的 4 条也算进去。分级依据是本节表格，回写脚本里的名单与它由单测绑定（`test_t6_filename_mechanism_set_matches_report`）。

---

## 五、检查④判重 与 ⑥F2P 因果

### 5.1 判重：5 对 F2P 重叠，均非同一件事

四个维度查重（共享 base / 共享 sid / F2P 文件重叠 / 题面全文相同）。**sid 零重叠、题面零重复**；F2P 文件重叠 5 对，逐对核后都不是同一件事：

| 重叠的 F2P 文件 | 两条 task | 同 base? | F2P 集合相同? | 代码文件交集 | 判定 |
|---|---|---|---|---|---|
| `tests/api/cache-detection.test.ts` | `T0010` / `T0055` | 否 | 否（11 vs 1） | 空 | 非重复 |
| `tests/config/patch-settings.test.ts` | `T0010` / `T0011` | 否 | 否 | — | 非重复 |
| `tests/goal/goal-gate.test.ts` | `T0014` / `T0052` | 否 | 否 | — | 非重复 |
| `tests/telemetry/provider-health.test.ts` | `T0033` / `T0056` | 否 | 否 | — | 非重复 |
| `tests/config/system-prompt.test.ts` | `T0038` / `T0042` | 否 | 否 | — | 非重复 |

同 base 的 4 组（`b1fd8f8b` ×4、`76b60150` ×2、`3b916830` ×2、`56ff080f` ×2）只是同一时点切了多条任务，F2P 与题面均不同，不构成重复。

> ✅ **顺带结掉 T3 交接 #2**：T3 判定「F2P 名不副实」的 4 条（`meta/p2p.jsonl` 的
> `f2p_check.is_f2p=false`，原因均为 `f2p_passes_at_base`）分别是
> `T0001` `T0006` `T0015` `T0037` —— **全部已被门禁②自动淘汰**，一条都没进存活集。
> T3 建议的「淘汰后 61 条」已由门禁机械完成，T6 无需再处置。

### 5.2 F2P 因果：40/40 成立

方案说这项「大部分已被门禁②机械化，人工只需复核门禁放过的那些」。复核方式是读 `nop` 侧的 `f2p.log`（比看聚合分硬得多），三类证据：

| 证据类 | 条数 | 形态 |
|---|---|---|
| **模块尚不存在** | 7 | `nop` 下 `Cannot find module '../../src/telemetry/content-tracing.ts'` —— 该文件由 gold_patch 新建。**最硬的因果证据** |
| **命名导出尚不存在** | 3 | `Export named 'filterGitignored' not found` —— 该 export 由 gold_patch 新增（逐条核对新增行确认） |
| **import/同目录/同名模块可链接** | 30 | F2P 测试 import 的模块 ∩ gold_patch 改的文件 非空 |

> 🔧 **中途纠正一处误判**：我最初把 10 条 `error_code=4`（F2P 的 junit XML 缺失）算成「无法判定」，还据此推出「16 个凑数 F2P」。读 `f2p.log` 后发现相反 —— XML 缺失的原因是**测试连加载都失败**（模块/导出尚不存在），这是最强的因果证据，不是缺口。**聚合分看不出这个区别，必须读日志。**

---

## 六、淘汰名单与 🔴 底线告警

### 6.1 淘汰 1 条：T0005

| 项 | 内容 |
|---|---|
| 题面 | `走流程发布一个新版本sid-code 记得更新官网更新日志` |
| 判分对象 | F2P = `tests/debug/logger-level-gate.test.ts`；gold_patch 只改 `src/debug/logger.ts` |
| 测的行为 | 「审计模式下 `AUDIT:*` 豁免级别门控（INFO 级也必须落盘）」 |
| 问题一 | **题面与判分对象完全无关** —— 要求「发版 + 更新官网日志」，判的是日志级别门控 |
| 问题二 | **含提示词模板残留**：`</session>` 闭合标签 + `Write the title in the predominant language of the session…`。这是 claude-trace 生成会话标题的 meta 指令，会直接指挥 agent「去写标题」 |
| 归类 | `instruction_unrelated_to_reward` + `prompt_template_contamination` |

全批扫过同类模板残留（12 个标记词），**只有 T0005 一条**，属个例。

### 6.2 🔴 已跌破 ≥40 底线

T5 交接 #1 明确：存活 40 条正好压线，T6 再淘汰任何一条就跌破，且要在报告里写明让 T7 决策。**现在跌破了：40 − 1 = 39 条。**

| 选项 | 代价 | 我的建议 |
|---|---|---|
| **A. 降量交付 39 条** | 差 1 条，但 39 条对 v0.2-mini 的基线统计没有实质影响 | ✅ **推荐** |
| B. 回补候选 | 要回 T2/T3/T4/T5 全链路跑 1 条新 task，且 T3 已知 S 档凑不出 —— 新条目大概率还是 M/L，改善不了分档 | 不值得 |
| C. 留下 T0005 凑 40 | 🔴 **不可接受**：它的题面与判分无关，基线会凭空多一条「谁都做不对但原因不明」的题，且污染源在题面 | 否 |

保留 T0017/T0027 也不是选项 —— §1 已证明二者是确定性缺陷。

### 6.3 淘汰率分布（v0.3 的输入）

方案要求「淘汰要记原因并归类，因为分布是 v0.3 的输入」。**含 T5 的 26 条一并归类**：

| 归类 | 条数 | 阶段 | v0.3 的含义 |
|---|---|---|---|
| `src/ink/` 从未入库 → 不可复现 | 7 | T5 门禁① | 采集侧问题，T1 筛选链应排除引用未入库路径的会话 |
| oracle reward=0（gold patch 打上后 F2P 仍红） | 12 | T5 门禁① | 反解或测试选取有偏差 |
| 假 task（nop 下 f2p=1） | 4 | T5 门禁② | 门禁②已机械封堵，无需人工 |
| `gold_patch_regression` / `gold_patch_broken` | 2 | **T6 §1** | 参考解自身质量 —— 建议 v0.3 给 gold patch 加**编译/类型检查**前置门禁（T0027 缺 import，`tsc` 一步就能抓） |
| `instruction_unrelated_to_reward` + 模板污染 | 1 | **T6 §6.1** | 采集侧要过滤提示词模板残留 |

**最重要的分布信号**：方案预设「若『题面不自足』占淘汰的多数，说明需要引入指令重写」。本轮**题面不自足没有淘汰任何一条**（因为底线不允许），但它影响 **20/40 条（A2 档）**，是本批最大的质量缺口。**结论对 v0.3 依然成立：必须引入指令重写，或在 T1 筛选链里排除「题面主体是引用本地不可见文档」的会话**。后者更省 —— 这类会话在 T1 阶段就能用「题面是否引用仓库外路径」机械识别。

---

## 七、给 T7 的交接清单

| # | 事项 | 严重度 |
|---|---|---|
| 1 | **存活 39 条，已跌破 ≥40**。建议按 §6.2 选项 A 降量交付，dataset card 写明 | 🔴 |
| 1b | ⚠️ **存活集读 `reports/t6-recheck/survivors.json`，不要读 `meta/gate.jsonl` 的 `survives`** —— 后者是 T5 三道门禁的结论（**40 条**），不含 T6 的人工淘汰。照它取会把 `T0005` 算进基线，而那条的题面与判分对象完全无关。`meta.json` 已补 `review.eliminated` 供逐条判别 | 🔴 |
| 2 | **基线数字必须按 §3.4 分级分组报**（A2 20 / A1 11 / B 4 / C 4）。混在一起报会把「题面缺信息」误读成「模型能力差」 | 🔴 |
| 2b | ⚠️ **难度维度与题面维度分开各一张表，不交叉** —— 方案 §4 T7 第 2 项要求按 S/M/L 报，本报告 §3.4 要求按 A2/A1/B/C 报，二者**正交**。39 条切成 2 档 × 4 级 = 8 格、每格 1-14 条，交叉报会碎到没有统计意义。任一格 < 5 条只报绝对条数、不报百分比 | 🔴 |
| 2c | ⚠️ **方案的健康度判据「难度分档呈单调梯度 S > M > L」已整条失效**，不是「可能不达标」：存活 39 条为 **L 27 / M 12 / S 0**（见下表）。改报 **M vs L 两档**，dataset card 写明「S 档为 0，不构成三档单调性证据」。**别走方案预案表「分档无梯度」那行** —— 那行判读是「`edit_ops` 不是好锚点」，真实原因是样本量为 0，锚点既未证伪也未证实 | 🔴 |
| 3 | **dataset card 的 Limitations 至少写四条**：① 7 条因 `src/ink/` 从未入库不可复现（T5 交接 #2）② 5 条 iam 被内网 registry 挡（T5 交接 #2）③ **35/40 题面指向容器内不存在的文档，20 条题面信息量极低**（§3）④ **8 条文件名点出根因，得分可能偏高**（§4.2） | 🔴 |
| 4 | 泄漏扫描结论读 `reports/t6-recheck/leak-scan-container.jsonl`，**不要读本报告的 markdown**；`meta.json` 的 `leak_scan_passed` 已按它回写，未验的写 `null` 而非 `true` | 中 |
| 5 | **不要回填那些文档**（§3.2）：31/37 份在 `docs-research/` 里找得到，但 21 份含 gold_patch 的专有标识符与测试代码，放进容器等于发答案 | 🔴 |
| 6 | 跑批仍遵 T5 的三条硬约束：`-o` 与 `-p` 都在 `$HOME` 下、`HARBOR_TELEMETRY=0`、`-n 1`、**不看退出码** | 中 |
| 7 | ⚠️ **宿主代理断开会让 `bun install` 无限等待**（0.02% CPU 挂 8 分钟，`docker build` 自己没超时）。T6 的扫描脚本已加 420s 上限 + `--resume`；**T7 跑批前先确认 7881 通**，长跑要能续跑 | 中 |
| 8 | S 档仍为 0 条（T3 交接 #1 的结构性冲突，T6 无法解决）。**淘汰 T0005 后 39 条的分布见下表** —— 「各档 ≥10」只有 M/L 达标 | 中 |

### 7.1 存活 39 条的分布（2c / 第 8 条引用的表）

取数：`reports/t6-recheck/survivors.json` × 各 `meta.json` 的 `band` / `category`。

| 难度档 | 条数 | 说明 |
|---|---|---|
| S | **0** | 🔴 **实测为零，不是待填**。T3 时只剩 5 条（T2 结构性冲突：S 档按 `edit_ops` 定义就是改动最少的那批，改动少 → 更可能只碰代码或只碰测试 → 凑不出 F2P 两侧），T5 门禁把这 5 条全数淘汰 |
| M | 12 | |
| L | 27 | |

| 类别 | 条数 |
|---|---|
| `bug_fix` | 18 |
| `test_authoring` | 21 |

| 题面信息量（§3.4） | 条数 |
|---|---|
| A2 只剩祈使句 | 20 |
| A1 点名交付物 | 11 |
| B 文件名点出症状 | 4 |
| C 散文自带可复现症状 | 4 |

⚠️ **这三张表是三个正交维度，T7 分开各报一张，不做交叉**（见 2b）。难度维度只有
M/L 两档可报；`test_authoring` 占 21/39 也要在 dataset card 里写明（这类 task 的
F2P 有「测试自己测自己」的退化风险，方案 §5.2 ④ 已列为可讲的取舍案例）。

---

## 八、产物清单

> 🔴 **T7 开工只需三个入口**（其余是支撑证据，按需查）：
> ① 存活名单 `reports/t6-recheck/survivors.json`（**39 条**，不要读 `meta/gate.jsonl`）
> ② 分组名单 `reports/t6-recheck/t7-grade-groups.json` + 本报告 §7.1 三张分布表
> ③ 交接清单 §7（**11 条**，其中 1b / 2b / 2c 直接改判据，别跳过）

| 文件 | 内容 |
|---|---|
| `reports/t6-review.md` | 本报告 |
| `reports/t6-recheck/recheck-verdict.json` | T0017/T0027 复跑定性（含 nop 对照与 ReferenceError 证据） |
| `reports/t6-recheck/oracle-k3/` | 复跑的 6 个 trial 原始产物，供复算 |
| `reports/t6-recheck/leak-scan-container.jsonl` | 逐条容器内扫描结论（**权威源**） |
| `reports/t6-recheck/leak-scan-selftest.json` | 扫描器的 5/5 反向自证 + 修掉的两处缺陷 |
| `reports/t6-recheck/grade.json` | 逐条题面分级（A2/A1/B/C/X） |
| `reports/t6-recheck/survivors.json` | **存活名单（T7 取存活集读这里）** —— gate 存活 40 − T6 淘汰 1 = 39 |
| `reports/t6-recheck/t7-grade-groups.json` | 分级分组名单，T7 分组报基线用 |
| `reports/t6-recheck/scan-validity.json` | 扫描容器与 harbor 实跑容器条件一致性核验（§4.0） |
| `reports/t6-recheck/filename-leak.json` | 题面文件名是否点出根因的二分（8 条点出 / 27 条仅症状，§4.2），已回写为 `meta.json` 的 `leakage.rootcause_in_filename` |
| `reports/t6-recheck/doc-refs.json` | 题面引用的 37 个文档路径与容器内缺失情况 |
| `reports/t6-recheck/doc-recoverable.json` | 宿主机上能找回哪些（31/37）及其位置 |
| `reports/t6-recheck/testpatch-applies.json` | 40/40 `git apply --check` 通过 → 快照都是 base 版 |
| `scripts/mvp/t6-leak-scan.py` | 容器内泄漏扫描（含 420s 超时、逐条落盘、`--resume`） |
| `scripts/mvp/t6-writeback.py` | 回写 meta.json 的 `solvability`／`leakage`／`review` 三段（未验、未过目一律写 `null`，不写 `true`／`false`） |
