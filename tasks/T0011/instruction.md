> /effort


  当前推理强度: auto
  实际档位(auto 解析): high（跟随模型默认）
  模型支持 max: 是

  可切换: low / medium / high / max / auto
  用 /effort <档位> 切换，加 -p 持久化到 settings.json；/effort help 查看用法


> /effort -p max


  推理强度已切换为: max，并已保存到 settings.json 我刚刚把sid-code effort 设置 max 并且之久化之后：'/Users/<USER>/.sid-code/settings.json' 但是我通过sc命令打开报错：zhourusheng@zhourushengdeMacBook-Pro sid-code % sc
错误: 未设置 OPENAI_API_KEY 环境变量 请你排查一下，我们这个设置的逻辑，有问题

---

## 环境事实

- 仓库已在 `/repo`，你的改动直接留在工作区即可（不需要 commit、不需要生成 patch）
- 跑测试：`bun test`
- 容器**离线运行**（`--network none`），依赖已装好，不要尝试联网安装
