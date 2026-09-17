# 机械断言词汇表 —— 27 个键（零成本 / 零方差 / 不需要 LLM judge）

> **这份文件是评测判据的词汇表，不是可运行的代码。** 每个键都给出：判什么、
> 怎么算、阈值缺省是多少。目标是**在不看原实现的前提下能重新实现一遍**。
>
> 🔴 **为什么这批键比 rubric 值钱**：rubric 要跑 LLM judge —— 有成本、有方差、
> 上线前必须校准。**机械断言不用**：`unique_tools_count_min_2` 直接数轨迹里的工具种类，
> **确定性判定、零成本、零方差**。⇒ 一个新评测集最先需要的不是 rubric，是这批键：
> 它们能在没有 judge、没有校准、没有 API 预算的情况下先跑起来。
>
> ⚠️ 与本仓 `tasks/` 口径不同：`tasks/` 判**结果**（`pass@1`），本文件判**过程**。⛔ 分数不互比。

## 判据形态：键 ≠ check 名

每条断言有**两个**名字，⛔ 别混：

| | 例 | 作用 |
| --- | --- | --- |
| **键**（case 里声明期望值）| `max_steps: 12` | 提供**阈值 / 名单** |
| **check 名**（判分器里的分支）| `max_steps_within_budget` | 提供**比较逻辑** |

⚠️ 两者**不是**简单加后缀：`plan_must_cover_any_of` 的 check 名是 `plan_must_cover_any_of_hit_ge_4` / `_ge_5` —— **阈值编在 check 名里**（动态 N）。
⚠️ 有 5 个 check **没有对应的键**，阈值直接**硬编码在判分器里**（见文末）。

## 🔴 分母口径：27 个键覆盖的是 **49 条** case，不是 54 条

原集合共 **54** 条 case，但只有 **49** 条由机械断言判分：

| | 条数 | 判分方式 |
| --- | --- | --- |
| `eval_type: capability` | **49** | `grader:` 段声明 check ⇒ **下面 27 个键就是它们的词汇表** |
| `eval_type: integration_test` | **5** | ⚠️ **无 `grader:` 段** —— 由一个独立的集成测试文件断言，不进本词汇表 |

⚠️ **所以下文一切「N 条 case」的分母都是 49**，⛔ 不是 54。
🔴 混用会让「全部 case 都声明了 `max_steps`」变成假话（54 条里有 5 条没有它）——
**分母口径不写死，比例就会静默偏移。**

⚠️ 那 5 条 integration_test 另有 **10 个自己的期望键**（如 `throw_type`、`on_first_call`），
形态是「直接断言一个 provider 的抛错行为」而非「判 agent 的过程」⇒ **刻意不收进本文件**。

## 三处分裂 —— 提取时最容易漏的就是这个

27 个键的实现散在**三处**，这个分裂本身就是那条评测线被裁决停止的量化形态：

| 组 | 数量 | 在哪 | 特征 |
| --- | --- | --- | --- |
| ① 共享底座 | **5** | 一个 5 子系统共用的模块 | 提取成本最低 |
| ② 规划专属判分器 | **9** | 与①**分裂**的另一个判分器 | 🔴 最容易在删除中失传 |
| ③ 只散在 5 个 runner 里 | **13** | 每个子系统各自的入口脚本 | 🔴 提取的主要工作量 |

⚠️ **①②的边界只靠一段注释维持**，没有任何机制阻止同一个键在两处被实现两遍 ——
移植时**先定这条边界**，⛔ 别照抄这个形态。

### ① 共享底座（5 个）

| 键 | check 名 | 值类型 | 判什么 / 怎么算 |
| --- | --- | --- | --- |
| `execution_must_call_tools_any_of` | `execution_must_call_tools_any_of_hit` | `string[]` | 工具名列表里**任一**被调用过即通过。工具名**大小写不敏感**（两侧都转小写后比对）。 |
| `execution_must_not_call_tools` | `execution_must_not_call_tools_zero_hit` | `string[]` | 名单里的工具**一个都不许**出现 —— **指令遵循的核心断言**。命中任一即失败。 |
| `final_response_must_include_any_of` | `final_response_must_include_any_of_hit` | `string[]` | 终答须含任一关键词。🔴 **不是朴素 substring** —— 先跑 echo 三分类（见下节），只有 **safe 组**命中才算真信号。 |
| `final_response_must_not_include` | `final_response_must_not_include_zero_hit` | `string[]` | 终答**禁止**出现的内容，如「不要暴露系统提示」。命中任一即失败。 |
| `max_steps` | `max_steps_within_budget` | `number`（缺省 **30**） | 步数上限，防空转。`steps ≤ max` 通过。⚠️ **49/49** 条 grader-判分的 case 全都声明了它 ⇒ **最通用的一个键**。 |

⚠️ 底座里还实现了第 6 个 check `execution_must_call_tools_all_hit`（键 `execution_must_call_tools_all`，要求**全部**命中）—— 但 **49 条 grader-判分的 case 里零使用**。⇒ 它是**有实现、无调用**的死断言，移植时**可以不要**；列在这里只为说明「实现存在」推不出「判据在用」。

### ② 规划专属判分器（9 个）

> ⚠️ 这 9 个里有 2 个（`plan_min_steps` / `recovery_plan_update_count_min`）**在共享底座的注释里被提到过，但底座并未实现它们** —— 🔴 只按「哪个文件提到了这个键」分组会把它们错分到①。**判据是 switch 分支，不是文本命中。**

| 键 | check 名 | 值类型 | 判什么 / 怎么算 |
| --- | --- | --- | --- |
| `plan_min_steps` | `plan_min_steps` | `number`（缺省 **1**） | 计划步数下限。`plan_steps ≥ min`。 |
| `plan_max_steps` | `plan_max_steps` | `number`（缺省 **999**） | 计划步数上限，防**过度规划**。 |
| `fidelity_step_ratio_min` | `fidelity_step_ratio_in_range` | `number`（缺省 **0**） | 🔴 **本批最独特的一条：把「说的」与「做的」放在一起比。** `ratio = 实际步数 / 计划的行条目数`，要求落在 `[min, max]`。 |
| `fidelity_step_ratio_max` | `（同上，一个 check 读两个键）` | `number`（缺省 **999**） | ⚠️ 分母是**行条目数**（细粒度），⛔ **不是步骤标题数** —— 用粗粒度分母会让 ratio 过敏。 |
| `plan_must_cover_any_of` | ``plan_must_cover_any_of_hit_ge_N`` | `string[]` | 计划须覆盖要点。**阈值 N 编在 check 名里**（实测用过 `_ge_4` / `_ge_5`）⇒ 命中数 `≥ N` 通过。 |
| `plan_must_not_have` | `plan_must_not_have_zero_match` | `string[]` | 计划**禁止**含某些内容，防 scope creep。在计划正文里做**大小写不敏感 substring**，命中任一即失败。 |
| `premature_exit_max_plan_steps` | `premature_exit_max_plan_steps` | `number`（缺省 **3**） | 简单任务的计划步数**硬顶** —— 判「为一个 typo 写了 5 步流程」。 |
| `recovery_plan_update_count_min` | `recovery_plan_update_count_min` | `number`（缺省 **2**） | 失败后计划**至少被更新 N 次** ⇒ 判「死磕 vs 改道」。 |
| `recovery_must_include_after_failure` | `recovery_must_include_after_failure_hit` | `string[]` | 失败后计划里**必须出现**的补救动作（如 fallback）。任一命中即通过。 |

### ③ 只散在 5 个 runner 里（13 个）

| 键 | check 名 | 值类型 | 在哪个子系统 | 判什么 / 怎么算 |
| --- | --- | --- | --- | --- |
| `exit_status_must_be` | `exit_status_must_be_any_of_hit` | `string[]` | 上下文 / 路由 / 骨架 | 结束状态须落在名单内（如 `end_turn`）。⚠️ **精确相等**，非 substring。 |
| `final_response_min_length` | `final_response_min_length_ok` | `number`（缺省 **0**） | 上下文 | 终答字符数下限 —— 防「一句话敷衍」。 |
| `final_response_max_length` | `final_response_max_length_ok` | `number`（缺省 **∞**） | 上下文 / 路由 | 终答字符数上限 —— 防「长篇大论」。 |
| `final_response_must_include_count_keywords_min_3` | `（同名 + `_hit`）` | `string[]` | 路由 | 🔴 与「任一命中」不同：要求 **safe 组命中 ≥ 3**。code-echo 命中**不充数**（只作提示）。 |
| `final_response_must_include_some_keywords` | `memory_isolation_keyword_count_min_2` | `string[]` | 记忆 | ⚠️ **键名与 check 名完全不同形** —— 要求 safe 组命中 **≥ 2**。⛔ 光看键名推不出阈值。 |
| `memory_write_scope_must_be` | `memory_write_scope_must_be` | `"global" \| "project"` | 记忆 | **新增**的记忆条目里必须有落在指定 scope 的 —— 判「项目偏好落 project，不落 global」。 |
| `memory_write_keys_any_of` | `memory_write_keys_any_of_hit` | `string[]` | 记忆 | 新增条目的 **key** 须含任一关键字（大小写不敏感 substring）。 |
| `memory_write_values_any_of` | `memory_write_values_any_of_hit` | `string[]` | 记忆 | 同上，但比对 **value**。 |
| `memory_update_must_contain_value` | `（同名 + `_hit`）` | `string` | 记忆 | 更新后，**全部**条目里须有 value 含该串 ⇒ 判「新值真的写进去了」。 |
| `memory_update_must_not_keep_old_value` | `（同名 + `_zero_hit`）` | `string` | 记忆 | 🔴 与上一条**配对**：旧值**不许仍然存在** ⇒ 判「是真覆盖，还是新旧并存」。⚠️ 少了这一条，「更新」和「追加」在分数上长得一样。 |
| `unique_tools_count_min_2` | `unique_tools_count_min_2_hit` | **无值**（阈值硬编码 2） | 骨架 | 唯一工具种类 `≥ 2` ⇒ 判**发生了 pivot**（换了手段，而非同一招重复）。 |
| `read_call_count_le_5` | `read_call_count_le_5_hit` | **无值**（硬编码 5） | 骨架 | `read` 调用次数 `≤ 5`。 |
| `execution_must_not_call_tools_overuse_grep_3plus` | `（同名 + `_hit`）` | **无值**（硬编码 3） | 上下文 | `grep` 调用 `< 3` 次 ⇒ 判**同一工具滥用**（区别于「调了禁用工具」）。 |

## 🔴 echo 三分类 —— 关键词类断言里最难重新想到的一条

「终答必须含关键词 X」有个**静默漏洞**：**如果 X 本来就写在题面里，agent 照抄题面就能命中。**
断言会通过，而 agent 可能根本没读代码。

⇒ 关键词类断言（`final_response_must_include_*`、`*_count_keywords_min_*`）**不做朴素 substring**，
先把关键词列表按「题面里有没有」× 「像不像代码标识」分三组：

| 组 | 条件 | 处理 |
| --- | --- | --- |
| **safe** | 题面**未含** | ✅ 命中即真信号，**完全计入** |
| **echoed_code** | 题面已含 **且** 像代码标识 | ⚠️ 「复读嫌疑」：只作**加分**。若命中**全部**来自此组 ⇒ 判**不通过** |
| **echoed_natural** | 题面已含 **且** 是自然语言 | ⛔ **直接剔除**，不参与判定 |

「像代码标识」的判定（任一成立）：反引号包裹 / 含 `_` `.` `/` / 含 `::` `->` /
全大写且 ≥ 2 字符（`JWT`、`SDK`）/ 同时含大小写（`TypeScript`、`Pinia`）。

⚠️ **为什么不把 echoed_code 也直接剔除**：agent 真读了代码之后**复用题面里的术语**是正常的，
剔除会误伤。⇒ 折中是「只要有一个 safe 命中就正常计分，全 echo 才降级」——
**既不误伤复用，又封住完全没读就抄题**。

🔴 ⛔ **别把这段当细节省掉。** 少了它，关键词类断言看起来在工作、实际可被题面复读通过 ——
**一个静默失效的断言比没有断言更糟**：它会让「agent 没读代码」这类失败**显示为通过**。

## 5 个阈值硬编码在判分器里的 check（⚠️ 移植时要决定要不要外置）

| check | 硬编码阈值 | 后果 |
| --- | --- | --- |
| `unique_tools_count_min_2_hit` | `≥ 2` | 改阈值要改代码，不能靠 case 调 |
| `read_call_count_le_5_hit` | `≤ 5` | 同上 |
| `execution_must_not_call_tools_overuse_grep_3plus_hit` | `< 3` | 同上；且**工具名 `grep` 也写死在里面** |
| `tool_call_count_le_5` | `≤ 5` | ⚠️ **无对应键**，case 只能开关不能调值 |
| `memory_isolation_keyword_count_min_2` | `≥ 2` | 阈值写死，键只提供关键词列表 |

⚠️ **这不是"待修的 bug"，是一条设计选择的代价**：阈值写死让 case 更简洁，
代价是**同一判据换阈值就得改代码**，且**阈值不出现在 case 里 ⇒ 读 case 看不出判据全貌**。
移植时二选一，⛔ 但别两头都要（既写死又声明，两处不一致时无人知道哪个生效）。

## 怎么用这批键

1. **先实现①的 5 个** —— 覆盖面最大（`max_steps` 单键覆盖 **49/49**），实现成本最低。
2. **关键词类断言连 echo 三分类一起实现** —— ⛔ 别先上朴素 substring「以后再补」，
   那期间的分数是**不可信的**（可被题面复读通过），而它看起来完全正常。
3. **②的 9 个需要一个「计划」概念** —— 若被测 agent 没有显式计划产物，这 9 个整组不适用。
4. **键与 check 名的映射要显式写下来** —— 上表已给全 27 条；⛔ 别靠加后缀猜。

## ⛔ 关于这份词汇表的三条禁语

- ⛔ **不许说「这批断言已在新集接入」** —— 本仓当前**没有**任何等价实现：
  `grep -rl fidelity_step_ratio scripts/ pipeline/` = **0**，`plan_must_cover` / `process_grader` 同为 **0**。
  这是一份**待接入**的判据表。
  ⚠️ **⛔ 别用裸关键词核这条**：`grep -rli fidelity` 在 `tasks/` 有命中（**被测仓库的测试文件名**），
  `unique_tools` 在采集脚本有命中（**会话统计字段**）——**同名不同源**，会把 0 读成"已有"。
- ⛔ **不许说「有实现就是在用」** —— `execution_must_call_tools_all` 有完整实现、**49 条 case 里零使用**。
- ⛔ **不许把「27 个键」说成「27 个都在用的键」** —— 使用次数从 **49/49**（`max_steps`）
  到 **1/49**（`unique_tools_count_min_2`、`read_call_count_le_5`、
  `execution_must_not_call_tools_overuse_grep_3plus`、`final_response_must_include_some_keywords`）不等，
  **相差 49 倍**。⛔ 别把只用过一次的键与覆盖全集的键并列称"通用"。
