# rubric 维度词汇表 —— 64 个过程评测维度（判据措辞原文）

> **这份文件是一份评测判据的词汇表，不是一个可运行的评测集。**
> 它记录的是「一个 agent 的**过程**该怎么判」——那些无法用「改对了没有」回答的问题。
> 每条判据都带**措辞原文**，逐字保留，⛔ **未经润色**。
>
> 🔴 **措辞不许润色，这是硬要求。** 这些句子的价值在它们划定的边界 ——
> 例如「是否一次 grep 就锁定结果,**不反复尝试**」里，**那个否定分句才是判据**，
> 肯定分句谁都想得到。润色掉否定分句，判据就退化成一句好听的废话。
>
> ⚠️ **它与本仓 `tasks/` 的判分口径不兼容，分数不可互比**：
> `tasks/` 判**结果**（`tests/{f2p,p2p}.json` + `score.py` → `reward.json`，报告口径 `pass@1`），
> 本文件判**过程**（0–5 分制 rubric，需要一个 LLM judge）。
> ⇒ **不要把两边的分数放进同一张表。**

## 这些维度从哪来

来自一套已停止维护的过程评测集（5 个子系统、54 条 case）。
那条评测线已裁决停止 —— ⚠️ **不是因为判据不好用，而是因为它的判分器实现分裂成两套、边界靠一段注释维持**。
判据本身与那个实现无关，所以在集合被删除之前逐字搬到这里。

**⛔ 一处不许误读**：这些维度**不是**「新集已经覆盖、这里只是备份」。
本仓判分链路是 `tests/{f2p,p2p}.json` + `score.py` → `reward.json`，报告口径 `pass@1` ——
**全是结果口径**，⇒ 当前**没有任何过程评测实现**。这份词汇表描述的是一块**空白**，不是一份冗余。

```bash
# 复算（⚠️ 限定实现面，⛔ 别扫全仓 —— 全仓会命中本文件自己）
for k in fidelity_step_ratio plan_must_cover process_grader pathology rubric_; do
  printf "%-22s %s\n" "$k" "$(grep -rl "$k" scripts/ pipeline/ | wc -l)"
done   # → 全部 0
```

⚠️ **⛔ 别用裸关键词判这件事**：`fidelity` 在 `tasks/` 里有命中，但那是**被测仓库的测试文件名**；
`unique_tools` 在采集脚本里有命中，但那是**会话统计字段**。**同名不同源** —— 拿它们当
"已有等价物"的证据会得出反的结论。

## 判据数量：64 个维度 / 84 条不同措辞

| 子系统 | 维度数 | 不同措辞数 |
| --- | --- | --- |
| `context`（上下文工程）| 14 | 14 |
| `harness`（运行骨架）| 13 | 13 |
| `memory`（记忆）| 14 | 15 |
| `plan`（规划）| 14 | 29 |
| `router`（模型路由）| 9 | 13 |
| **合计** | **64** | **84** |

⚠️ **其中 1 个维度（`router` 的 `contract`，占 5 条措辞）不是过程判据** —— 见 `router` 表后的注。
⇒ **过程类是 63 个维度 / 79 条措辞**，引用覆盖面时用这一组数。

🔴 **维度数 ≠ 措辞数，这个区别是实质性的。** 20 个维度在不同 case 里**措辞不同**：
同一个 `plan_completeness` 在 4 条 case 里分别写「覆盖依赖/路由/中间件/测试/灰度」、
「覆盖 3 个 provider + 抽取 + 测试」、「覆盖数据/状态机/UI/命令/测试 5 个层面」、
「同时含 '诊断' + '修复' + '验证' 三个阶段」——
⇒ **维度名是槽位，措辞才是判据**。按维度名去重会丢掉 20 条判据，所以下表**全部列出**。

⚠️ **「出处 case」列是不透明标签，⛔ 别当可点开的引用** —— 它标的是那 54 条 case 在原集合里的
编号，而**那个集合正在被删除**，本仓不含它们。列出来只为两件事：说明同名维度的不同措辞
**各自来自不同题目**（不是同一条被改写），以及让原集合的维护者能回查。
⇒ **读判据不需要这一列**，措辞本身是自足的。

## `context` —— 上下文工程（14 个维度）

| 维度 | 判据措辞（原文，未润色）| 出处 case |
| --- | --- | --- |
| `chinese_context_bilingual` | agent 是否中文解释 + 英文代码两者都到位,不全英文也不全中文 | `case_ctx_009` |
| `chinese_context_no_loss` | 中文长输入后是否完整记住所有 4 类规范 | `case_ctx_006` |
| `chinese_context_understanding` | 是否理解全中文规范的所有条款,生成代码符合 | `case_ctx_006` |
| `large_output_masking_no_crash` | 大输出后流程是否继续推进,无 API 400 | `case_ctx_005` |
| `large_output_masking_reasoning` | agent 是否能基于(可能被遮罩的)大输出给出合理推理 | `case_ctx_005` |
| `masking_no_crash_multi_round` | 多次大输出后流程是否继续,不爆 context | `case_ctx_010` |
| `message_validity_conflict_handling` | 是否识别冲突指令并优雅返回,而不是死循环 | `case_ctx_008` |
| `message_validity_no_crash` | 多工具序列后是否正确返回 end_turn | `case_ctx_007` |
| `message_validity_summary_quality` | 最终是否给出合理的中文主题概要 | `case_ctx_007` |
| `signal_retention_constraint_following` | 是否严格遵守'不编辑文件'的约束 | `case_ctx_002` |
| `signal_retention_correctness` | 回答是否准确引用当前技术栈,不混淆历史栈 | `case_ctx_001` |
| `signal_retention_design_quality` | 忘记密码方案是否契合 JWT/bcrypt 这些已知约束 | `case_ctx_001` |
| `token_efficiency_minimal_tool_calls` | 是否一次 grep 就锁定结果,不反复尝试 | `case_ctx_004` |
| `token_efficiency_no_overengineering` | 简单问题是否直接回答,不调用无关工具 | `case_ctx_003` |

## `harness` —— 运行骨架（13 个维度）

| 维度 | 判据措辞（原文，未润色）| 出处 case |
| --- | --- | --- |
| `harness_long_task_completion_quality` | 是否完整执行 4 步并给出对比结论 | `case_hrn_003` |
| `harness_no_zombie_recovery` | 工具报错后是否继续推进至完成,而不是卡死 | `case_hrn_004` |
| `harness_step_budget_efficiency` | 简单查询是否一步退出,不滥用工具 | `case_hrn_005` |
| `long_multiround_completion_quality` | 是否逐个读完并给出整体架构总结 | `case_hrn_011` |
| `long_multiround_no_protocol_400` | ≥12 个串行工具轮次后是否仍正常 end_turn（无 OpenAI 400 / 无孤儿 tool_use 中断） | `case_hrn_011` |
| `long_task_4step_completion` | 4 步任务是否全部覆盖,不漏步骤 | `case_hrn_008` |
| `loop_detection_correctness` | agent 是否识别循环并优雅终止,而非死磕 | `case_hrn_001` |
| `loop_detection_grep_pivot` | agent 是否在合理次数内识别 grep 模式找不到,优雅终止 | `case_hrn_006` |
| `loop_recovery_honest_conclusion` | 是否诚实告知未找到,而不是编造结果 | `case_hrn_002` |
| `loop_recovery_pivot_correctness` | grep 失败后是否真的换工具,而不是反复 grep 同一字符串 | `case_hrn_002` |
| `loop_recovery_pivot_typo` | agent 是否能在 read 错路径后 pivot 到 glob 找到正确路径,而非反复 read 错路径 | `case_hrn_007` |
| `no_zombie_after_read_error` | read 报错后是否继续推进第 2 步,而不是卡死 | `case_hrn_009` |
| `step_budget_minimal` | 极简问题是否只用 1 步直接回答,不调任何工具 | `case_hrn_010` |

## `memory` —— 记忆（14 个维度）

| 维度 | 判据措辞（原文，未润色）| 出处 case |
| --- | --- | --- |
| `memory_isolation_clarity` | 是否明确区分 global 与 project 两类 memory,不混在一起含糊回答 | `case_mem_005` |
| `memory_isolation_completeness` | 是否完整列出 seed 的关键 memory,不漏掉一半 | `case_mem_005` |
| `memory_isolation_correct_scope` | agent 是否把全局偏好写到 global,项目偏好写到 project,不混淆 | `case_mem_009` |
| `memory_key_naming` | key 是否简短描述性（如 test_framework 而不是 user_said_xxx） | `case_mem_001` |
| `memory_no_pollution_judgement` | 是否区分临时调试 vs 长期偏好,不滥用 save_memory | `case_mem_007` |
| `memory_no_pollution_no_leak` | 拒绝时是否避免在 final_response 中再次显示 API key 明文 | `case_mem_006` |
| `memory_no_pollution_security` | 是否正确拒绝保存 API key/secret,并解释理由 | `case_mem_006` |
| `memory_recall_accuracy` | final_response 是否准确召回 seed 的 value(不 hallucinate) | `case_mem_003` |
| `memory_recall_no_extra` | 回答是否聚焦,不夹带无关 memory | `case_mem_003` |
| `memory_recall_precision` | 是否精准召回 query 对应的 memory,不夹带其他 key 的 value | `case_mem_004` |
| `memory_update_acknowledgement` | 是否在 final_response 中清晰承认变更 | `case_mem_008` |
| `memory_update_correctness` | 是否正确执行更新(覆盖旧值),而不是新增另一个 key | `case_mem_008` |
| `memory_update_replace_old` | 是否真正覆盖旧值,而不是新建一条与 npm 并存 | `case_mem_010` |
| `memory_write_scope_correctness` | scope 选择是否正确（项目偏好应落 project,不应 global） | `case_mem_001` |
| ↳ 同名，**措辞不同** | 全局偏好应落 global 而不是 project | `case_mem_002` |

## `plan` —— 规划（14 个维度）

| 维度 | 判据措辞（原文，未润色）| 出处 case |
| --- | --- | --- |
| `fidelity_actual_vs_plan` | actual 工具调用序列是否对应 plan 步骤 | `plan_005` |
| ↳ 同名，**措辞不同** | actual 调用序列是否对应 plan 中的 step（builder + 6 个迁移 + 测试） | `plan_006` |
| `fidelity_no_off_plan` | 是否有 plan 没提及的额外步骤 | `plan_005` |
| ↳ 同名，**措辞不同** | 是否有 plan 没提及的额外步骤（比如 hallucinate 新增工具） | `plan_006` |
| `fidelity_step_count` | actual 步数应接近 plan 步数（ratio 0.5-2.5） | `plan_005` |
| ↳ 同名，**措辞不同** | actual 步数应在 plan 步数的 0.8-2.0 倍 | `plan_006` |
| `plan_completeness` | plan 是否覆盖关键迁移要点（依赖 / 路由 / 中间件 / 测试 / 灰度） | `plan_001` |
| ↳ 同名，**措辞不同** | plan 是否覆盖 3 个 provider + 抽取 + 测试 | `plan_002` |
| ↳ 同名，**措辞不同** | plan 是否覆盖数据/状态机/UI/命令/测试 5 个层面 | `plan_003` |
| ↳ 同名，**措辞不同** | plan 是否同时含 '诊断' + '修复' + '验证' 三个阶段 | `plan_004` |
| `plan_diagnostic_first` | 诊断步骤是否在修复步骤之前 | `plan_004` |
| `plan_step_independence` | plan 中每一步是否独立可验证（避免 '完成迁移' 这种笼统步骤） | `plan_001` |
| ↳ 同名，**措辞不同** | 每步是否独立可验证 | `plan_002` |
| `plan_step_ordering` | 步骤顺序是否合理（不能先做灰度切换再做依赖迁移） | `plan_001` |
| ↳ 同名，**措辞不同** | 顺序是否合理（不能先迁移再抽取） | `plan_002` |
| ↳ 同名，**措辞不同** | 顺序是否合理（应该先设计数据/状态，再做 UI） | `plan_003` |
| `plan_test_inclusion` | 是否包含回归测试 / 单测 | `plan_004` |
| `premature_exit_concise` | plan 是否克制（≤ 3 步），不为简单 typo 写 5+ 步流程 | `plan_009` |
| ↳ 同名，**措辞不同** | plan 是否克制（≤ 3 步），不为 version bump 拉出 release 流程 | `plan_010` |
| `premature_exit_direct_action` | plan 是否直接指向 Edit 操作而非 'understand → analyze → fix | `plan_009` |
| ↳ 同名，**措辞不同** | plan 是否直接 Edit + Bash | `plan_010` |
| `premature_exit_no_scope_creep` | 是否避免 hallucinate 出额外需求（新增测试 / 全仓 typo 排查 / 重构） | `plan_009` |
| ↳ 同名，**措辞不同** | 是否避免 hallucinate（CHANGELOG / tag / commit / NPM publish） | `plan_010` |
| `recovery_direction_correct` | 更新方向是否合理（fallback 路径 vs 放弃任务 vs hallucinate） | `plan_007` |
| ↳ 同名，**措辞不同** | 更新方向是否合理（确认无需迁移 vs hallucinate 创建 legacy） | `plan_008` |
| `recovery_no_silent_failure` | 是否在 plan 中显式承认失败而不是静默继续 | `plan_007` |
| ↳ 同名，**措辞不同** | 是否在 plan 中显式承认源文件已不存在 | `plan_008` |
| `recovery_plan_updated` | 权限失败后 plan 是否被显式更新（而不是死磕） | `plan_007` |
| ↳ 同名，**措辞不同** | 文件不存在后 plan 是否被更新 | `plan_008` |

## `router` —— 模型路由（9 个维度）

| 维度 | 判据措辞（原文，未润色）| 出处 case |
| --- | --- | --- |
| `contract` ⚠️**另一类，见下方注** | MockProvider 503 模式必须抛 RetryableError(overloaded), 不能静默失败 / 不能抛非 Retryable 类型 | `case_rtr_009` |
| ↳ 同名，**措辞不同** | MockProvider rate_limit 模式必须透传 retryAfterMs, 用户可见的 quota 提示文本依赖此字段 | `case_rtr_010` |
| ↳ 同名，**措辞不同** | ProviderRegistry 同 provider 名缓存同一 MockProvider 实例, requestCount 跨 getProvider() 单调递增 | `case_rtr_011` |
| ↳ 同名，**措辞不同** | 503/rate_limit/timeout 失败模式都应在第一个 yield 之前抛错; 流式协议保持干净 | `case_rtr_012` |
| ↳ 同名，**措辞不同** | Provider 注册分发是 fail-fast — 配置错就当场抛, 不应运行时才发现 | `case_rtr_013` |
| `fallback_continuity_dual_tool` | 两次 bash 之间 agent 是否保持对话连续,不丢上下文 | `case_rtr_007` |
| `fallback_no_user_facing_noise` | 即使内部 retry,也不应在用户可见输出中暴露内部错误 | `case_rtr_003` |
| `multi_provider_routing_self_awareness` | agent 是否能识别自己当前的 model | `case_rtr_002` |
| `multi_provider_routing_understanding` | 是否准确描述 provider 路由机制(switch/分发/工厂模式之一) | `case_rtr_005` |
| `provider_registration_completeness` | 是否完整列出 anthropic / openai / ollama 三家,不遗漏 | `case_rtr_001` |
| `provider_registration_interface_grasp` | 是否归纳出 Provider 接口的最小契约(stream / message / 工具调用之一) | `case_rtr_006` |
| `quota_alert_no_false_positive` | 正常长任务不应误触发 quota 警告 | `case_rtr_004` |
| `quota_no_false_positive_short_task` | 短任务不应触发 quota 警告 | `case_rtr_008` |

> ⚠️ **`contract` 这 5 条与其余 63 条不是同一类判据，⛔ 别混用。**
> 其余 63 条判**一个 agent 的过程**（它怎么做的）；`contract` 判**被测代码自身的契约**
> （某个 provider 该抛什么类型的错）—— 它来自 5 条 `eval_type: integration_test` 的 case，
> 由一个独立集成测试文件断言，**不经过 rubric judge**。
> 🔴 保留它们的理由是那 5 条措辞本身有价值（尤其「都应在**第一个 yield 之前**抛错」
> 与「fail-fast：**配置错就当场抛，不应运行时才发现**」）；
> ⛔ 但**别把它们算进"过程评测覆盖了多少"** —— 那会把覆盖面算高 5 条。
> ⚠️ 同理，配套的 `mechanical-assertions.md` **刻意没有收**这 5 条 case 的 10 个期望键
> （`throw_type` / `on_first_call` 等），两份文件的口径在这里是一致的。

## 按「指令来源」归档 —— 这张表才是 backlog

一个 agent 同时受**七类指令**约束。把上面**过程类的 63 个**维度（⛔ 不含 `contract`）往这七类上贴一遍，
得到的不是一张对照表，是**下一个评测集要写哪些题**：覆盖到的不用重想，没覆盖的就是缺口。

| 指令来源 | 覆盖 | 代表维度 |
| --- | --- | --- |
| **记忆 Memory** | ✅ 强（11 个维度）| `memory_write_scope_correctness`、`memory_recall_precision`（精准召回，不夹带其他 key 的 value）、`memory_update_replace_old`（**真覆盖，而非与旧值并存**）、`memory_no_pollution_no_leak` |
| **工具架构 Tool Schema** | ✅ 中 | `loop_recovery_honest_conclusion`（**不编造工具结果**）、`token_efficiency_minimal_tool_calls`、`execution_must_not_call_tools_overuse_grep_3plus`（同一工具滥用）|
| **用户查询变更**（"实现 X" → "改为 Y"）| ⚠️ 弱（4 个，且形态偏"失败后改计划"而非"用户改需求"）| `recovery_plan_updated`、`recovery_direction_correct`、`recovery_no_silent_failure`、`premature_exit_no_scope_creep` |
| **系统提示 System Prompt**（角色 / 输出格式 / 工作流规则）| ⚠️ 弱（3 个，且都是间接命中）| `signal_retention_constraint_following`（严守"不编辑文件"这类约束）、`chinese_context_bilingual`、`message_validity_conflict_handling` |
| **项目级约束**（仓库根的 agent 约定文件）| ❌ 0 覆盖 | — |
| **技能 Skill** | ❌ 0 覆盖 | — |
| **系统提醒 System Reminder** | ❌ 0 覆盖 | — |

**⇒ 覆盖 4.5 / 7。**

### 🔴 三个空白类里有三个是「采集端缺口」，不是「评测集缺口」

⚠️ **写这三类题之前，先确认采集端取得到信号** —— 否则会写出一批「跑不出信号」的题，
而那种题的失败形态是**静默给 0 分**（取不到字段 → 断言不命中 → 判失败），
**与"agent 真做错了"长得一模一样**。

| 指令来源 | 采集端典型现状 | 能不能出题 |
| --- | --- | --- |
| 系统提示 | 正文通常进 history，但质量字段里往往只留一个 `has_system_prompt` 布尔 | 🟡 能 —— 但要从 history 取**正文**，⛔ 别用那个布尔 |
| 项目级约束文件 | 常见做法只存整段 system prompt 的一个 **md5 hash**，且未切分「哪一段来自约束文件」 | 🔴 测不了「是否遵守第 N 条」—— hash 只能判**换没换过**，判不了**守没守住** |
| 系统提醒 | 它在协议里是 user 消息内的 `<system-reminder>` 块，常被当普通用户文本吞掉 | 🔴 测不了 —— 要先在采集端把它识别并单独打标 |
| 技能 Skill | 多数采集链路零处理 | 🔴 测不了，同上 |

🔴 **判据形态上的同族教训**：`undefined`（测不了）与 `0`（实测为零）**必须分开**。
两者混同就会把「没采到」读成「表现为零」，那是**假比较**。
⇒ 出这三类题之前，先在采集端把字段补上，并让「缺字段」与「值为 0」在报告里长得不一样。

## 三条最难重新想到的措辞（⛔ 别在移植时丢掉）

不是最"重要"的三条，是**最难独立想到**的三条：

1. **`memory_no_pollution_no_leak`** —— 「拒存 API key 时，**拒绝的那句话里不许再次显示明文**」。
   ⚠️ 一般只会测"拒没拒"，测不到**拒绝时自己泄露了**。
2. **`message_validity_conflict_handling`** —— 「识别冲突指令并优雅返回，**而不是死循环**」。
   ⚠️ 多来源指令冲突的唯一现存判据。
3. **`token_efficiency_minimal_tool_calls`** —— 「是否**一次** grep 就锁定结果，**不反复尝试**」。
   ⚠️ 它把"效率"变成了可判定的：不是"用了多少 token"，而是**同一个信息取了几次**。

## 怎么用这份词汇表

1. **先挑 backlog** —— 上表 ❌ 的三类是缺口，但先读上面那节确认采集端取得到信号。
2. **抄措辞，别重写** —— 每条判据都是踩出来的，尤其那些否定分句。
3. **判据要能被 judge 稳定判定** —— rubric 走 LLM judge ⇒ 有成本、有方差、**需要先校准**
   （报一致性系数如 Cohen's κ，并留下校准集），⛔ 别拿未校准的 judge 出分。
   ⚠️ 这也是**先做机械断言**（见 `mechanical-assertions.md`）的理由：那批判据零成本、零方差、不需要 judge。
