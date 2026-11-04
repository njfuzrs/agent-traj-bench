'/Users/<USER>/Code/person/sid-code/docs/bugfixes/todo/可选优化/G7-G9-G10单元测试补全.md' 这是之前排查问题的时候，顺便制定的一个可选的优化方案，也联网查询了一些资料，目的是弥补我们当前系统中的不足，提高性能，优化功能和用户体验，现在需要对这份方案进行二次评审，帮我检查一下，方案中哪些是真正值得做的地方？哪些是性价比高 / 无副作用 / 一次性根治的，我们需要筛选出来，而不是照单全收，我们要避免文档中宏大结论，技术自嗨，避免毫无实用价值的东西，请你结合现在代码和功能帮我分析一下

---

## 引用文档原文

### `/Users/<USER>/Code/person/sid-code/docs/bugfixes/todo/可选优化/G7-G9-G10单元测试补全.md`

> 以下为该文件正文（评测环境无法访问你本机路径，故内联附上；文中代码块已移除）。

```
# G7/G9/G10 单元测试补全

> 优先级：P0 | 预估工作量：0.5 天 | 依赖：无

## 1. 背景

LSP 缺口补全方案 G1–G10 已全部落地，但以下三项缺少单元测试覆盖：

| 缺口 | 实现位置 | 当前测试 |
|------|---------|---------|
| G7 capabilities 声明 | `src/lsp/server-instance.ts:86-104` | ❌ 无 |
| G9 gitignore 过滤 | `src/tool/lsp.ts:99-131` | ❌ 无 |
| G10 文件大小保护 | `src/tool/lsp.ts:238-252` | ❌ 无 |

现有测试文件（`tests/lsp/`）共 4 个、67 个用例，模式成熟可复用。

---

## 2. G7 Capabilities 测试

### 位置

在 `tests/lsp/server-instance.test.ts` 中追加 describe 块。

### 方案

扩展现有 mock LSP server 脚本（`writeMockLSP`），让 initialize handler 在返回 result 后，额外发送一条自定义通知 `test/echoCapabilities`，携带收到的 `msg.params.capabilities` 参数。测试端注册该通知 handler 接收并断言。

### Mock Server 改动

（此处原有一段代码块，评测题面已移除。）

### 测试用例

（此处原有一段代码块，评测题面已移除。）

### 复用设施

- `writeMockLSP(dir)` — 已有，需微改追加 echoCapabilities 通知
- `makeInstance(overrides)` — 已有
- afterEach cleanup — 已有

---

## 3. G9 Gitignore 过滤测试

### 前置改动

将 `src/tool/lsp.ts` 中的 `filterGitignored` 函数从 module-private 改为 `export`：

（此处原有一段代码块，评测题面已移除。）

### 位置

新建 `tests/lsp/lsp-tool-filters.test.ts`

### 测试用例

（此处原有一段代码块，评测题面已移除。）

### CI 注意

测试开头检测 git 可用性，不可用时 skip：

（此处原有一段代码块，评测题面已移除。）

---

## 4. G10 文件大小保护测试

### 位置

在同一文件 `tests/lsp/lsp-tool-filters.test.ts` 中追加 describe 块。

### 方案

利用 `manager.test.ts` 的模式：`initializeLSP("/nonexistent")` 让 LSP 进入 success 状态（无配置 = 无服务器 = 立即 success），然后实例化 LSPTool 调用 execute 触发文件大小检查。

### 测试用例

（此处原有一段代码块，评测题面已移除。）

---

## 5. 验证

（此处原有一段代码块，评测题面已移除。）

---

## 6. 文件变更清单

| 文件 | 操作 |
|------|------|
| `src/tool/lsp.ts` | 修改：`filterGitignored` 改为 export |
| `tests/lsp/server-instance.test.ts` | 修改：追加 G7 capabilities 测试 |
| `tests/lsp/lsp-tool-filters.test.ts` | **新建**：G9 + G10 测试 |
| mock LSP 脚本（test 内联） | 修改：追加 echoCapabilities 通知 |
```


---

## 验收标准

你的修复必须让以下测试文件**全部通过**（`bun test <路径>`）：

- `tests/lsp/lsp-tool-filters.test.ts`

> 这些测试文件当前**不在**工作区，验收时才会放入。
> ⚠️ 不要自己创建这些测试文件 —— 验收时会被覆盖。


---

## 环境事实

- 仓库已在 `/repo`，你的改动直接留在工作区即可（不需要 commit、不需要生成 patch）
- 跑测试：`bun test`
- 容器**离线运行**（`--network none`），依赖已装好，不要尝试联网安装
