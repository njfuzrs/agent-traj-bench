# Agent-Traj-Bench v0.2-mini

**39 条从真实 agent 开发轨迹反解出来的 SWE 任务**，配可复算的判分链路与全部中间报告。

题目不是手写的：先采集真实编码会话（8562 条），再从里面把「改了哪些文件、跑了哪些测试」
反解成 base commit + gold patch + F2P/P2P 测试集，最后逐条人工复核。
所以每道题都有**它从哪来**的完整链条 —— `meta/` 与 `reports/` 里 T1→T7 每一步都在。

| | |
| --- | --- |
| 交付题数 | **39**（漏斗见下；65 条产出中 26 条在 T6 复核里被淘汰，留在私有仓归档） |
| 基线 pass@1 | **37.8%**（14/37，排除 2 条 infra；95% Wilson `[24.1%, 53.9%]`） |
| 基线模型 | `origin-deepseek-v4-1-flash`，k=1，实付 **$26.21** |
| 批次指纹 | `91be9a5d90d8`（冻结于 2026-09-05） |
| 快照 | 39 份 / **259.9MB**（1.2–13.1MB），走 HF LFS，**不在本仓** |

- 数据集卡：[`DATASET_CARD.md`](DATASET_CARD.md) —— ⛔ 里面**没有一个手写数字**，全部由 `scripts/t7-report.py --card` 从产物复算
- 完整报告：[`reports/baseline-v0.2-mini-t8-rerun.md`](reports/baseline-v0.2-mini-t8-rerun.md)（13 节，含真 0/假 0 逐条归因）
- 快照仓：<https://huggingface.co/datasets/njfuzrs/agent-traj-bench>
- 过程评测判据：[`docs/eval-criteria/`](docs/eval-criteria/) —— ⚠️ 判据词汇表，与本仓 `pass@1` 口径**不互比**（见「目录」）

## 🔴 两条复现路径不是一回事

这是本数据集**最容易踩的坑**，所以放在最前面。两条路径跑的**题面不同**，得到的数字也不同：

| 想复现什么 | 入口 | 题面形态 |
| --- | --- | --- |
| **题集本身**（39 条能不能跑起来） | `harbor run -p tasks -n 6` | 交付原句，**不含**下面两段 |
| **基线读数**（37.8% 这个数） | `scripts/t8-rerun.py` | 原句 **+ 两段现拼** |

`t8-rerun.py` 把 39 条复制到 stage 目录后，在题面原句之外拼了两段（都是修复实验的产物）：

1. **内联被点名文档的原文** —— 34/39 条题面点名了容器里不存在的 `docs/`，不内联的话
   模型只能去猜
2. **补一段环境约定** —— 说明测试怎么跑

⇒ **照第一行跑（`tasks/` 原句）等于关掉这两项修复**，而它们正是本批 pass@1 不是 0% 的原因：
第一轮 `baseline/` 没有这两段，实测 **0/39**。

⛔ 所以：拿 `tasks/` 直接跑出来的数字**不能**和 37.8% 比较。要比就用 `scripts/t8-rerun.py`。

## 快速开始

```bash
git clone https://github.com/njfuzrs/agent-traj-bench && cd agent-traj-bench

# ① 题集完整性自查（$0，不跑模型、不需要容器）
python3 scripts/t3-build-harbor-tasks.py --check-only
#    → ✅ 39 条 task 的 11 个入库文件全部齐备且非空
#    → ⚠️ 另有 39 条缺 environment/repo-snapshot.tar.gz（未入库，走 HF 快照仓）

# ② 取快照并重建 environment/（259.9MB，走 LFS）
git lfs install
git clone https://huggingface.co/datasets/njfuzrs/agent-traj-bench /tmp/atb-hf
python3 scripts/t4-build-env.py --from-snapshots /tmp/atb-hf/snapshots
#    🔴 它会逐份校验 sha256（基准是 meta/snapshots.jsonl 的 tar_sha256）
#    任一份不符即报红退出 4 —— ⛔ 不许跳过：铺进容器的内容与冻结时不是同一份，
#    判分结果就不可复算，而那种失败看起来只是"判分结果诡异"

# ③ 纯复算报告与 card（$0，不跑任何模型）
python3 scripts/t7-report.py --runs t8-rerun --card
```

跑真评测需要 [harbor](https://pypi.org/project/harbor/) 与 Docker：

```bash
harbor run -p tasks -n 6 -a <your-agent>
```

## 目录

```text
tasks/T####/              39 条题目
├── instruction.md        题面（真实开发者原句，⛔ 改它就改了题目）
├── task.toml  meta.json  harbor 元数据 + 溯源（unit_id / repo / base_commit / band / grade）
├── tests/                f2p.json  p2p.json  test.sh  test_patch.diff  score.py
├── solution/             gold_patch.diff  solve.sh（oracle，用于验题目可解）
└── environment/          Dockerfile（⚠️ repo-snapshot.tar.gz 见上文 ②）

meta/                     漏斗取数源：candidates / resolved / p2p / gate / snapshots
                          + batch-v0.2.summary.json（漏斗前三行的标量）
reports/                  T1–T7 全部报告 + trials.json（trial 级取数源）
scripts/                  生成与复算脚本（T1→T8），含单测 tests/test_mvp.py
docs/eval-criteria/       ⚠️ 过程评测判据词汇表 —— 判据文档，不是可运行的评测集
                          mechanical-assertions.md  27 个机械断言键（零成本 / 不需要 judge）
                          rubric-dimensions.md      64 个 rubric 维度 / 84 条措辞原文
```

⚠️ **`docs/eval-criteria/` 与本仓 `tasks/` 的判分口径不兼容，分数不可互比**：
`tasks/` 判**结果**（「改对了吗」→ `pass@1`），那两份文档记的是判**过程**的判据
（「过程病态吗」→ 0–5 分制 rubric + 机械断言）。⛔ 别把两边的分数放进同一张表。
🔴 它们描述的是本仓**当前没有**的能力，是**待接入的判据**，⛔ 不是「已经支持过程评测」：

```bash
# 判据要限定在实现面（scripts/ pipeline/），⛔ 别扫全仓
for k in fidelity_step_ratio plan_must_cover process_grader pathology rubric_; do
  printf "%-22s %s\n" "$k" "$(grep -rl "$k" scripts/ pipeline/ | wc -l)"
done   # → 全部 0
```

⚠️ **⛔ 别用裸关键词扫全仓**：`grep -rli rubric .` 现在会命中**这两份新文档本身**（自我推翻），
而 `grep -rli fidelity` 的命中是 `tasks/` 里被测仓库的**测试文件名**、
`unique_tools` 的命中是采集侧的**会话统计字段** —— 三者都是**同名不同源**，不是过程评测实现。

## 漏斗（从 8562 条会话到 39 道题）

| 步骤 | 剩余 | 取数源 |
| --- | --- | --- |
| 冻结批次**会话**（claude_code 7820 / codex 317 / short_id 248 / sid_code 177） | **8562** | `meta/batch-v0.2.summary.json` |
| 清洗后保留的**会话**（去空/过短/自指等） | **4381** | 同上 `filtered` |
| 切分出的**任务单元**（⚠️ 换单位，1.762 个/会话） | **7692** | 同上 `units` |
| …（T1 筛选 → T2 反解 → T4 建环境 → T5 门禁 → T6 复核） | | `meta/` + `reports/` |
| **交付** | **39** | `reports/t6-recheck/survivors.json` |

⚠️ 第 3 行**比第 2 行大**：单位在那里从「会话」变成「任务单元」，一个会话可切多个单元。
完整逐级数字见 [`DATASET_CARD.md`](DATASET_CARD.md)。

## 基线读数

| 分档 | 解出 / 计分 |
| --- | --- |
| A1 | 6/10 |
| A2 | 4/19 |
| B | 3/4 |
| C | 1/4 |

🔴 **这些是「模型 × 题集 × 配置」的联合结果，⛔ 不是数据集的固有属性** —— 换任一项都会变。
排除的 2 条（`T0009` / `T0022`）是 infra 故障（上游断连），**不记为答错**：
把一次网络抖动记成模型能力不足，与「模型改了但改错」在产物上逐字节一样，
判据写在 `scripts/t7_report_lib.py` 的 `infra_failure` / `upstream_failure`。

## 已知局限

1. **快照不在 git 里**（259.9MB）⇒ fresh clone 跑不起来，须走上文 ② 重建。
2. **`mirror` 只在采集机**：`scripts/t4-build-env.py` 的默认模式从 19 个 bare 仓重建，
   那些仓没有分发 ⇒ **别人只能用 `--from-snapshots`**。
3. **原始轨迹不入库**（66G，gitignore 的 `data/pulled_sessions/`）⇒
   T1/T2（从轨迹反解题面）在 fresh clone 上跑不了，相关自证会如实报
   「跑不起来」（退出码 5）而**不是**假装守卫失效。
   有平台凭据时用 `python3 pipeline/s0/s0-pull.py` 拉到本仓 `data/`；
   已有湖则 `export SESSIONS_DIR=` 指过去。
4. **`tasks/T0011/instruction.md` 含一句带真实用户名与主机名的 shell 提示符**
   （`zhourusheng@zhourushengdeMacBook-Pro sid-code % sc`）。它是开发者当时那句话的原文；
   两个字符串在公开的 sid-code 仓里已经存在（用户名是其 MIT LICENSE 的署名人）。
   ⛔ 不清理的理由是**改题面会影响判分口径**。
5. **S 档为 0** ⇒ 三档单调性无从谈起，⛔ 不能据此说「edit_ops 不是好锚点」——
   样本量为 0 时锚点既未证伪也未证实，那是两回事。
6. **两项看着像大面积泄漏的扫描结果已被证伪**，⛔ 别照它们返工：
   - 39/39 快照命中 `sk-` / `AKIA` / `ghp_` ⇒ **全是误报**：命中的是 sid-code 自己的
     密钥检测器代码与测试 fixture（`AKIAIOSFODNN7EXAMPLE`），`sk-` 更是子串误匹配
   - 39/39 命中 `/Users/` ⇒ 实际值是 `/Users/runner`（GitHub Actions）等**占位符**

   ⇒ **快照必须逐字节保持原样**，它的 sha256 是校验基准（见 [`LICENSE`](LICENSE) ③）。

## 许可

三层，见 [`LICENSE`](LICENSE)：数据内容 **CC BY 4.0** / 代码 **MIT** /
39 份快照是 [sid-code](https://github.com/njfuzrs/sid-code) 的源码，
**MIT，Copyright (c) 2026 zhourusheng and sid-code contributors**。
