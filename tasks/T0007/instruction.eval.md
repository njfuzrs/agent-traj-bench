'/Users/<USER>/Code/person/sid-code/docs/_template/gpt参数校验失败.txt' 帮我排查文档中的问题

---

## 引用文档原文

### `/Users/<USER>/Code/person/sid-code/docs/_template/gpt参数校验失败.txt`

> 以下为该文件正文（评测环境无法访问你本机路径，故内联附上；文中代码块已移除）。

```
刚刚使用sid-code +  gpt-5.6-luna  模型执行任务，全程频繁遇到：参数校验失败报错

具体的报错信息包括：

⏺ read /Users/<USER>/Code/person/sid-code/docs/bugf… (行 1-2001)
  ⎿ 参数校验失败（工具 read）:
    - pages: 期望 string，实际收到 unknown（Invalid input: expected string, received null）

⏺ hypothesis_register
  ⎿ 参数校验失败（工具 hypothesis_register）:
    - supporting_evidence: 期望 array，实际收到 unknown（Invalid input: expected array, received null）
⏺ hypothesis_register
  ⎿ 参数校验失败（工具 hypothesis_register）:
    - supporting_evidence: 期望 array，实际收到 unknown（Invalid input: expected array, received null）
⏺ hypothesis_register
  ⎿ 参数校验失败（工具 hypothesis_register）:
    - supporting_evidence: 期望 array，实际收到 unknown（Invalid input: expected array, received null）
⏺ hypothesis_register
  ⎿ 参数校验失败（工具 hypothesis_register）:
    - supporting_evidence: 期望 array，实际收到 unknown（Invalid input: expected array, received null）
⏺ hypothesis_register
  ⎿ 参数校验失败（工具 hypothesis_register）:
    - supporting_evidence: 期望 array，实际收到 unknown（Invalid input: expected array, received null）

⏺ sub_agent explore "请在当前 sid-code 仓库中只读深入审计目标文档涉及…"
  ⎿ 参数校验失败（工具 sub_agent）:
    - model: 期望 string，实际收到 unknown（Invalid input: expected string, received null）

⏺ sub_agent explore "请在当前 sid-code 仓库中只读深入审计目标文档涉及…"
  ⎿ [子代理完成] 类型: explore, 轮次: 1
    Token 用量: input=0, output=0
    … 4 行已折叠 · ctrl+o 展开
⏺ sub_agent explore "请在当前 sid-code 仓库中只读深入审计 todo …"
  ⎿ [子代理完成] 类型: explore, 轮次: 1
    Token 用量: input=0, output=0
    … 4 行已折叠 · ctrl+o 展开
⏺ sub_agent explore "请在当前 sid-code 仓库中只读审计目标文档根因4/…"
  ⎿ [子代理完成] 类型: explore, 轮次: 1
    Token 用量: input=0, output=0
    … 4 行已折叠 · ctrl+o 展开
⏺ sub_agent explore "请在当前 sid-code 仓库中只读审计目标文档 §8 …"
  ⎿ [子代理完成] 类型: explore, 轮次: 1
    Token 用量: input=0, output=0
    … 4 行已折叠 · ctrl+o 展开


⏺ grep "isInternalUserMsg|_meta\?\.origin|origin"                            
  ⎿ 错误: 路径不存在 "/Users/<USER>/Code/person/sid-code/src/query/auto-compact.ts /Users/<USER>/Code/person/sid-code/src/query     
    /reactive-compact.ts /Users/<USER>/Code/person/sid-code/src/query/compact"。请确认路径正确，或使用默认当前目录（不传 path
    参数）。    

⏺ grep "buildIsolatedToolRegistry\(|TodoProgressAdvanced|events\.jsonl|readJsonl\("
  ⎿ 错误: 路径不存在 "/Users/<USER>/Code/person/sid-code/src/agent/sub-agent.ts /Users/<USER>/Code/person/sid-code/src/trace/di     
    gest.ts"。请确认路径正确，或使用默认当前目录（不传 path 参数）。

⏺ grep "TodoProgressAdvanced|todo_progress|todo|NoProgressNagInjected"
  ⎿ 错误: 路径不存在 "/Users/<USER>/Code/person/sid-code/scripts/trace-digest.ts /Users/<USER>/Code/person/sid-code/src/trace/d
    igest.ts"。请确认路径正确，或使用默认当前目录（不传 path 参数）。                                                                                                                             

⏺ grep "docs:gen-reference|make build|bun test|TodoProgressAdvanced|todo-realtime-integration|todo-reminder-scan"                             
  ⎿ 错误: 路径不存在 "/Users/<USER>/Code/person/sid-code/.github /Users/<USER>/Code/person/sid-code/scripts /Users/<USER>/
    Code/person/sid-code/docs"。请确认路径正确，或使用默认当前目录（不传 path 参数）。      

⏺ grep "TodoProgressAdvanced|writeVersion|NoProgressNagInjected|todo_gate_retry|prompt cache|cache hit|cacheRead"
  ⎿ 错误: 路径不存在 "/Users/<USER>/Code/person/sid-code/src/trace/digest.ts /Users/<USER>/Code/person/
    sid-code/scripts/trace-digest.ts"。请确认路径正确，或使用默认当前目录（不传 path 参数）。                                                  


 │ ✘ 模型不存在或不可用
 │   LLM 错误: OpenAI API 错误: 503 {"error":{"code":"model_not_found","message":"No available channel for model deepseek under group 个人
 │   (distributor) (request id: 202608010403493067678748268d9d6bDgnrEtL)","type":"new_api_error"}}
 │   → 请确认 settings.json 的 model 字段与网关实际可用模型一致（区分大小写）
 │

对应的轨迹文件是：/Users/<USER>/.sid-code/trajectories/sessions/20260801-120158-d91920a0

请你结合轨迹文件进行分析，找出证据，定位上面所有报错的原因，到底是sid-code 原因，还是大模型原因，还是网关层原因，我们要彻底修复这个问题，不要猜测
```


---

## 验收标准

你的修复必须让以下测试文件**全部通过**（`bun test <路径>`）：

- `tests/agent/sub-agent-model-whitelist.test.ts`
- `tests/llm/strict-wire-contract-reconciliation.test.ts`
- `tests/tool/nullish-normalize.test.ts`

> 这些测试文件当前**不在**工作区，验收时才会放入。
> ⚠️ 不要自己创建这些测试文件 —— 验收时会被覆盖。


---

## 环境事实

- 仓库已在 `/repo`，你的改动直接留在工作区即可（不需要 commit、不需要生成 patch）
- 跑测试：`bun test`
- 容器**离线运行**（`--network none`），依赖已装好，不要尝试联网安装
