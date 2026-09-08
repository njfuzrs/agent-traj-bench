'/Users/<USER>/Code/person/docs-research/sid-code/summary/Evaluation/01-coding-agent评测集全景与sid-code接入方案.md' 请你阅读一下：ZZZZ.9 smoke-8 结果 ZZZZ.10 🔴 更正 ZZZZ.9 的归因 作为任务背景，然后现在需要你执行任务：ZZZZ.11 下一棒（按优先级排，P0 那条不在评测里，在主循环里） ZZZZ.12 PR4 算不算完结？什么时候能开 PR6？ ，注意先判断根因定位准不准确，修复方案对不对，不要一上来就跑测评，结果发现又通过不了，又有问题，结果白跑了，另外已经通过的题目能不能就不要再跑了，就跑没通过的题目，这样做行不行？我看了跑完好像也没有分数，只有通过与不通过是吧？
</session>

Write the title in the predominant language of the session — a stray word or code token in another language doesn't change it, and neither does the English of these instructions.

---

## 环境事实

- 仓库已在 `/repo`，你的改动直接留在工作区即可（不需要 commit、不需要生成 patch）
- 跑测试：`bun test --test-name-pattern '^(?!.*\[slow\])'`
- 容器**离线运行**（`--network none`），依赖已装好，不要尝试联网安装
