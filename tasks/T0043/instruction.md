https://github.com/rushengzhou/sid-code/pull/66 现在ci 有个报错：Run if command -v rg >/dev/null 2>&1; then
Error: The operation was canceled.  请你帮我解决一下
</session>

Write the title in the predominant language of the session — a stray word or code token in another language doesn't change it, and neither does the English of these instructions.

---

## 环境事实

- 仓库已在 `/repo`，你的改动直接留在工作区即可（不需要 commit、不需要生成 patch）
- 跑测试：`bun test --test-name-pattern '^(?!.*\[slow\])'`
- 容器**离线运行**（`--network none`），依赖已装好，不要尝试联网安装
