'/Users/<USER>/Code/person/sid-code/docs/bugfixes/todo/Dynamic Workflows' 帮我检查方案中所有需求是否全部落地到代码中，不要遗漏

---

## 验收标准

你的修复必须让以下测试文件**全部通过**（`bun test <路径>`）：

- `tests/workflow/runtime.test.ts`

> 这些测试文件当前**不在**工作区，验收时才会放入。
> ⚠️ 不要自己创建这些测试文件 —— 验收时会被覆盖。


---

## 环境事实

- 仓库已在 `/repo`，你的改动直接留在工作区即可（不需要 commit、不需要生成 patch）
- 跑测试：`bun test`
- 容器**离线运行**（`--network none`），依赖已装好，不要尝试联网安装
