1. run-statusline.test.ts 是目前最不稳的测试文件。今天连撞两次：PR #91 在 ubuntu 红 同指纹+窗口内，PR #93 在 macOS 红 stdout
     透传。两次都是 spawn 路径，重跑即绿，本地连跑 5 次 40/40 全过。根因是被测模块 STATUSLINE_TIMEOUT_MS = 1000 对满载 CI runner 太紧
     。真要治的方向是把超时在测试里做成可注入值，而不是放宽断言（放宽会让这个超时保护本身失去覆盖）——我没动它，因为那超出本次范围。
  2. 上一条我提过的流程冲突仍未解：CLAUDE.md 的发布流程最后那步 git push 会被 protect-main 以 GH013 拒绝，bump 提交只能走 PR。这次两个
     PR 都是这么绕的。要么改文档、要么给 release.sh 开 ruleset 例外，属于你的决策。
 这两件事请你帮我裁决并修复，看看怎么修复比较合适，我们现在不要残留，不然对话结束就丢失上下文，以后这些问题又会犯第二次

---

## 环境事实

- 仓库已在 `/repo`，你的改动直接留在工作区即可（不需要 commit、不需要生成 patch）
- 跑测试：`bun test --test-name-pattern '^(?!.*\[slow\])'`
- 容器**离线运行**（`--network none`），依赖已装好，不要尝试联网安装
