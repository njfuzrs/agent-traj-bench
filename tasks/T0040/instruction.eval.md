'/Users/<USER>/Code/person/sid-code/docs/bugfixes/todo/Anthropic代理流式挂死-三层超时失效根因分析.md' 请按照文档中的来执行代码修复，直到所有问题都修复落地

---

## 引用文档原文

### `/Users/<USER>/Code/person/sid-code/docs/bugfixes/todo/Anthropic代理流式挂死-三层超时失效根因分析.md`

> 以下为该文件正文（评测环境无法访问你本机路径，故内联附上；文中代码块已移除）。

```
---
status: draft
era: ts
last_verified: 2026-08-15
---
# Anthropic 代理 content_block index 空洞导致 TypeError 崩溃

> **Session ID**: 9bc92c2c  
> **发现日期**: 2026-06-25  
> **严重等级**: P0 (任务立即失败，无法执行复杂任务)  
> **状态**: 待修复  
> **首次触发场景**: sid-code 第一次使用 Claude 模型（通过第三方代理 `code.ppchat.vip`）执行复杂任务

---

## 1. 现象描述

用户切换到 `claude-sonnet-4-6` 模型后，简单对话（"你好"）正常，但发送复杂代码检查任务时看似无响应。实际上请求 7 秒就返回了，但处理响应时立即崩溃（TypeError），TUI 显示 fatal_error 后恢复等待输入状态。

由于 AfterModel 事件在崩溃点之后触发，events.jsonl 中缺失 AfterModel 记录，表面看起来像"请求发出后永远没响应"。

---

## 2. 根因

### 2.1 直接原因：`response.content` 数组存在空洞（sparse array）

**崩溃位置**: `src/query/loop.ts:737-738`

（此处原有一段代码块，评测题面已移除。）

**错误信息**:
（此处原有一段代码块，评测题面已移除。）

### 2.2 根本原因：第三方代理 SSE 流中 content_block index 不从 0 开始

通过实际抓包和 SDK 测试复现，代理返回的 SSE 事件流：

（此处原有一段代码块，评测题面已移除。）

模型在决定直接调用工具（不输出文本前缀）时，代理返回的 `content_block_start` 的 `index` 从 1 开始，跳过了 0。

### 2.3 stream-processor 用 index 做数组下标赋值

**文件**: `src/query/stream-processor.ts:105-117`

（此处原有一段代码块，评测题面已移除。）

结果：`response.content = [undefined, {type:"tool_use",...}]`（稀疏数组）

### 2.4 queryLoop 遍历 content 时未做 null/undefined 防御

`loop.ts` 中多处直接 `.filter(b => b.type === ...)` 遍历 content，均假设数组元素非空：

| 行号 | 代码 | 触发条件 |
| --- | --- | --- |
| 627 | `response.content.filter(b => b.type === "tool_use")` | abort 后 |
| 737 | `response.content.filter(b => b.type === "text")` | **每次响应后（首先命中）** |
| 808 | `detectEmptyParamToolUses(response.content, ...)` | 处理空参数 |
| 912 | `response.content.some(b => b.type === "tool_use")` | 判断是否有工具调用 |
| 1049 | `response.content.filter(b => b.type === "tool_use")` | 工具执行 |

---

## 3. 时间线（修正后）

| 时间 (CST) | 事件 | 说明 |
| --- | --- | --- |
| 00:42:37 | /model claude-sonnet-4-6 | 用户切换模型 |
| 00:42:50 | BeforeModel#1 | 简单问候 |
| 00:42:55 | AfterModel#1 ✅ | 5秒完成，纯文本 index=0 |
| 00:44:03 | BeforeModel#2 | 复杂代码检查任务 |
| 00:44:03 | FALLBACK: 连接阶段尝试 1/4 | — |
| 00:44:03 | LLM:ANTHROPIC: 发送请求 | — |
| 00:44:10 | 首 token 延迟: 6959ms | 代理正常返回 |
| 00:44:10 | 流结束: tool_use×1, stop=tool_use | **processStream 成功返回** |
| 00:44:10 | **TypeError: undefined is not an object** | loop.ts:737 崩溃 |
| 00:44:10 | ENGINE: fatal_error | engine catch 住异常 |
| 00:44:10 | TUI: isLoading → false | 恢复输入状态 |

**关键**：请求并没有 hang。7 秒就结束了，只是结果是一个 TypeError 崩溃。

---

## 4. 为什么第一次请求成功？

| 对比 | 第一次（"你好"） | 第二次（代码检查） |
| --- | --- | --- |
| 模型行为 | 直接输出文本 | 直接调用工具（read） |
| SSE index | index=0 (text) | index=1 (tool_use)，跳过 0 |
| content 数组 | `[{type:"text",...}]` | `[undefined, {type:"tool_use",...}]` |
| 结果 | ✅ 正常 | ❌ TypeError |

## 5. 为什么 Claude Code 没问题？

可能原因（需验证）：
1. Claude Code 的 stream processor 对 content 数组做了 `.filter(Boolean)` 去除空洞
2. Claude Code 使用官方 API（非代理），官方 API 可能保证 index 从 0 连续开始
3. Claude Code 的 SDK 版本或 stream 处理逻辑不同

---

## 6. 修复方案

### P0-1：stream-processor 输出时过滤空洞

**文件**: `src/query/stream-processor.ts`

在 `processStream` 返回前过滤掉 undefined 元素：

（此处原有一段代码块，评测题面已移除。）

### P0-2：queryLoop 所有遍历 content 的位置加防御

**文件**: `src/query/loop.ts`

所有 `response.content.filter/some/map` 调用前加 `.filter(Boolean)`：

（此处原有一段代码块，评测题面已移除。）

或更简洁地在 processStream 出口做一次清理（P0-1），所有下游自动安全。

### P1：stream-processor 的 index 赋值逻辑改为 push（不信任 index 连续性）

当前用 `response.content[event.index] = ...` 做随机赋值，信任 index 是连续且从 0 开始的。改为：

（此处原有一段代码块，评测题面已移除。）

### P2：AfterModel 事件应在 processStream 返回后立即触发

当前 AfterModel hook 在 line 745（`responseText` 提取之后）才触发。如果在 processStream 返回后、任何 content 处理之前就记录 AfterModel 事件，就不会出现"有 BeforeModel 无 AfterModel"的诊断盲区。

（此处原有一段代码块，评测题面已移除。）

### P3：loop.ts 硬超时 timer 去掉 unref（防御性加固）

**文件**: `src/query/loop.ts:555-558`

当前 `turnTimer` 被 `unref()` 了，这与 `fallback.ts:266-269` 中已修复的 fdb47f30 教训是同一模式：Bun 中 unref 的 timer 在事件循环被底层 IO 占满时不保证按时触发。虽然本次故障未触发该路径（请求 7 秒就返回了），但如果将来真遇到代理 TCP 半开/上游 hang 住的场景，这个 timer 就是最后的兜底，必须保证按时 fire。

（此处原有一段代码块，评测题面已移除。）

---

## 7. 证据链

| 证据 | 来源 | 结论 |
| --- | --- | --- |
| `[00:44:10] LLM:ANTHROPIC 首 token 延迟: 6959ms` | audit.log | 代理 7 秒返回，没有 hang |
| `[00:44:10] STREAM 流结束: 工具调用1个, stop=tool_use` | audit.log | processStream 成功解析 |
| `[00:44:10] TypeError: undefined is not an object (evaluating 'block.type')` | audit.log | **直接崩溃证据** |
| `content_block_start index=1`（跳过 0） | SDK 实测抓包 | 代理行为确认 |
| `response.content[event.index] =` 赋值逻辑 | stream-processor.ts:110 | 空洞产生机制 |
| `.filter(b => b.type === "text")` 无 null check | loop.ts:738 | 崩溃触发点 |
| AfterModel 在 line 745（崩溃点之后） | loop.ts:745 | 为何 events.jsonl 缺 AfterModel |

---

## 8. 附录：之前误判的"超时失效"问题

初始分析中误以为是"三层超时保护全部失效导致进程 hang 22 分钟"。实际上进程在 7 秒后就报错结束了当前任务，TUI 恢复了输入等待状态。heartbeat 17:06:50 只是 TUI 进程正常运行的心跳。

超时相关的 `unref()` 问题已在第 6 节 P3 中作为正式修复项列出。

---

## 9. 验证清单

- [ ] P0-1：processStream 返回时 `response.content = response.content.filter(Boolean)`
- [ ] P0-2：确认所有遍历 `response.content` 的位置都安全
- [ ] 回归测试：构造 index 不连续的 mock stream event，验证不崩溃
- [ ] 回归测试：正常 index=0 开始的 stream 不受影响
- [ ] P1：stream-processor index→position 映射改造
- [ ] P2：AfterModel 事件前移到 content 处理之前
- [ ] P3：loop.ts turnTimer 去掉 unref
```


---

## 验收标准

你的修复必须让以下测试文件**全部通过**（`bun test <路径>`）：

- `tests/query/sparse-content-index.test.ts`

> 这些测试文件当前**不在**工作区，验收时才会放入。
> ⚠️ 不要自己创建这些测试文件 —— 验收时会被覆盖。


---

## 环境事实

- 仓库已在 `/repo`，你的改动直接留在工作区即可（不需要 commit、不需要生成 patch）
- 跑测试：`bun test`
- 容器**离线运行**（`--network none`），依赖已装好，不要尝试联网安装
