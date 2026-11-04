'/Users/<USER>/Code/person/sid-code/docs/_template/language命令缺少选项.txt' 请帮我修复文档中的问题

---

## 引用文档原文

### `/Users/<USER>/Code/person/sid-code/docs/_template/language命令缺少选项.txt`

> 以下为该文件正文（评测环境无法访问你本机路径，故内联附上；文中代码块已移除）。

```
现在我们sid-code 执行 /language 之后tui界面的输出是这样的：

> /language


  当前输出语言: zh — 中文优先

  可用值:
    zh     — 中文优先
    en     — 英文优先
    auto   — 跟随用户输入语言（每轮按用户所用语言应答）
    unset  — 清除偏好，回落缺省（中文优先）

  用法: /language <zh|en|auto|unset> [-p]（-p 持久化到 settings.json）
  也可用 --language 启动参数或 SID_LANGUAGE 环境变量（优先级：参数 > 环境变量 > settings.json）


缺少选项和键盘交互，我们应该做成类似于 /model 命令这样的，带边框的，有选项，用户可以用键盘快速选择与切换的形式

/model 命令输出是这样：

╭───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ 选择模型 · 14 个可用                                                                                                          │
│ 当前: glm-5.2 (openai)                                                                                                        │
│ 推理强度: █ max · ←/→ 调整                                                                                                    │
│                                                                                                                               │
│   gpt-5.4                openai — openai (https://uniapi.ruijie.com.cn/v1)                                                    │
│   ali-deepseek-v4-pro    openai — openai (https://uniapi.ruijie.com.cn/v1)                                                    │
│   ali-deepseek-v4-flash  openai — openai (https://uniapi.ruijie.com.cn/v1)                                                    │
│   claude-sonnet-4-6      anthropic — anthropic (https://uniapi.ruijie.com.cn)                                                 │
│   claude-sonnet-5        anthropic — anthropic (https://uniapi.ruijie.com.cn)                                                 │
│   claude-opus-4-8        anthropic — anthropic (https://code.ppchat.vip)                                                      │
│   claude-opus-5          anthropic — anthropic (https://code.ppchat.vip)                                                      │
│   claude-sonnet-5        anthropic — anthropic (https://code.ppchat.vip)                                                      │
│ › glm-5.2                openai ● 当前 — openai (https://uniapi.ruijie.com.cn/v1)                                             │
│   gpt-5.6-luna           openai — openai (https://uniapi.ruijie.com.cn/v1)                                                    │
│   gemini-3.5-flash       openai — openai (https://uniapi.ruijie.com.cn/v1)                                                    │
│   kimi-k2.6              openai — openai (https://uniapi.ruijie.com.cn/v1)                                                    │
│                                                                                                                               │
│ ↑↓ 导航 · Enter 切换 · ←/→ 调 effort · Esc 取消                                                                               │
╰───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
 glm-5.2 · ✻ · max
                                                                                                sid-code ⎇ master · ⚠ skip-perms
```


---

## 验收标准

你的修复必须让以下测试文件**全部通过**（`bun test <路径>`）：

- `tests/command/language-dialog.test.ts`

> 这些测试文件当前**不在**工作区，验收时才会放入。
> ⚠️ 不要自己创建这些测试文件 —— 验收时会被覆盖。


---

## 环境事实

- 仓库已在 `/repo`，你的改动直接留在工作区即可（不需要 commit、不需要生成 patch）
- 跑测试：`bun test`
- 容器**离线运行**（`--network none`），依赖已装好，不要尝试联网安装
