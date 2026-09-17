# Phase 1 — 清洗

对应 `docs-research/trajectory-platform/bench-curation-design.md` §4.2（S1）、
§4.3（S3）、§4.6（分类体系）、§9 Phase 1 任务表。

**Phase 1 已全部完成并验收通过**（四组门禁全绿 + 反向自证 17/17 + 单测 111 项）。
这里是给下一棒（Phase 2 分诊与去重）的入口说明。

## 先跑这一条

```bash
# 验收当前状态。全绿才说明产物可用，可以进 Phase 2
python3 s1_s3/verify-phase1.py

# 改了任何判定逻辑之后，必须再跑一次反向自证（约 4 分钟，CPU 密集）
python3 s1_s3/verify-phase1.py --self-test
```

两条都是幂等只读检查。`--self-test` 慢是因为它把 S3 的独立信号对账（1313 条会话
逐条 difflib 比对）跑了 6 遍 —— 这是刻意的，不缓存才能保证每个注入 case 都真的
走完整条判定链。

## 数据流与产物

```
data/pulled_sessions/          只读数据湖，一个字节都不改
        │
        │  Phase 0 产物（只读）
        ├─ meta/sessions-v2.jsonl      S0 索引，8562 条
        └─ meta/batch-v0.2.json        冻结批次
        │
        ▼
   s1-filter.py     →  phase1/meta/filtered-v2.jsonl     8562 条（保留 4381）
        ▼
   s3-split.py      →  phase1/meta/units-v2.jsonl        7721 单元（保留 7692）
        ▼
   s2-desensitize.py→  phase1/desensitized/units.jsonl   7692 条脱敏单元
        ▼
   label-units.py   →  phase1/meta/labeled-v2.jsonl      ★ Phase 1 最终交付物
        │
        └─ query-units.py       按源信息 / 分类检索的入口
```

注意 **S2 排在 S3 之后**，与方案 §4.1 的编号顺序相反。理由见 `s2-desensitize.py`
顶部：S1 保留会话的 `raw.jsonl` 合计 47.6GB，按 session 全量重写既慢又占盘，而
真正会发布出去的只是单元级的 instruction 与文件路径。所以先切分，再对单元脱敏，
产物粒度与下游消费单位对齐。

## 文件

| 文件 | 作用 | 何时要跑 |
|---|---|---|
| `common.py` | 三阶段公共契约：目录布局、源信息块定义、批次加载 | 被下面引用，不单独跑 |
| `s1-filter.py` | S1 硬过滤：六条规则，命中即淘汰并记 `drop_reason` | 换批次时 |
| `s3_segment.py` | S3 切分的判定逻辑（噪声识别、边界信号、区间映射） | 被 s3-split 与单测引用 |
| `s3-split.py` | S3 会话切分：读 `raw.jsonl`，切成任务单元 | S1 之后（8 进程约 47 秒） |
| `s2_rules.py` | 脱敏规则层：正则、替换、严重度分级 | 被 s2-desensitize 与单测引用 |
| `s2-desensitize.py` | S2 脱敏：产出脱敏文本 + 命中台账 | S3 之后 |
| `labeler.py` | 分类与标注的判定逻辑（类别打分、标签、难度分档） | 被 label-units 与单测引用 |
| `label-units.py` | 给脱敏单元补 category / tags / difficulty | S2 之后 |
| `query-units.py` | **按源信息与分类检索的入口** | 随时 |
| `verify-phase1.py` | 四组验收门禁 + `--self-test` 反向自证 | 每个阶段之后；改判定逻辑后跑自证 |
| `legacy_v01/` | v0.1 的六个脚本，归档不再使用 | 不跑 |

判定逻辑一律拆成 `*_rules.py` / `*_segment.py` / `labeler.py`，脚本只负责读盘写盘。
这样单测能直接 import 判定函数，不必造文件。

## 完整重跑

```bash
python3 s1_s3/s1-filter.py --batch v0.2
python3 s1_s3/s3-split.py --batch v0.2 --workers 8   # 约 47 秒
python3 s1_s3/s2-desensitize.py
python3 s1_s3/label-units.py
python3 s1_s3/verify-phase1.py                       # 必须全绿
```

每个脚本都有 `--dry-run`（只打统计不写盘）和 `--limit N`（抽样试跑）。

## 本轮实测结果

| 阶段 | 输入 | 保留 | 备注 |
|---|---|---|---|
| S1 硬过滤 | 8562 会话 | 4381（51.2%） | 淘汰 4181 条全部有归因 |
| S3 切分 | 4381 会话 | 7692 单元 | 7721 个单元，淘汰 29（中断 7 + 无边界 22） |
| S2 脱敏 | 7692 单元 | 7692 | 80.2% 命中，脱敏后二次扫描零残留 |
| 分类标注 | 7692 单元 | 7692 | 8 类别，最大类 34.3%；难度最大单档 43.4% |

淘汰原因分布（S1）：`R1_EMPTY` 2659 / `R2_TOO_SHORT` 1112 /
`E_SELF_REFERENTIAL` 272 / `R4_TOO_FEW_TOKENS` 120 / `R3_NO_ACTION` 18。

保留率 51.2% 与方案 §4.1 预算 70.8% 的差是**口径差不是数据变差**，逐层拆解见
`s1-filter.py` 顶部的对照表（预算是在 6019 条、且不含自指污染排除时算的）。

## 用户新增需求：源信息贯穿 + 检索入口

方案原文只把 `agent_source` 当成「要不要拆批」的判断依据。用户 2026-09-05 指出
不够 —— 数据来自四条采集通道，模型分布完全不同，混算得到的是三种工具的加权平均：

| 通道 | 保留会话 | 主要厂商 |
|---|---|---|
| `claude_code` | 3850 | anthropic 3833 / openai 17 |
| `codex` | 224 | deepseek 103 / zhipu 49 / openai 46 / xai 12 … |
| `short_id` | 186 | deepseek 75 / openai 47 / anthropic 39 / alibaba 25 |
| `sid_code` | 121 | unknown 63 / openai 24 / deepseek 21 … |

处置：把七个字段做成**贯穿字段**（`agent_source` / `model` / `vendor` / `repo` /
`repo_resolution` / `provenance` / `batch_version`），会话级、单元级都带，
每一层由 `verify-phase1.py` 加门禁 —— 任何一层丢字段即报红。定义在
`common.py:PROVENANCE_FIELDS`。

检索入口是 `query-units.py`：

```bash
# 按通道 × 边界置信度看分布
python3 s1_s3/query-units.py --group agent_source,boundary_confidence

# 只看 codex 通道里 deepseek 的 bug_fix，排除敏感与锚定矛盾的
python3 s1_s3/query-units.py --agent-source codex --vendor deepseek \
    --category bug_fix --exclude-review --exclude-conflict --list

# 筛出一批写文件，交给 Phase 2
python3 s1_s3/query-units.py --boundary-confidence high \
    --min-edit-ops 3 --out /tmp/candidates.jsonl
```

## 六条不要踩的坑

**① 淘汰不移目录，不删记录。**

与 Phase 0 同一条纪律，原因也一样（`pull.py:246` 的去重只看
`data/pulled_sessions/<sid>/.pulled`，移目录会让 1722 条重复下载）。S1 和 S3 的
产物都是**全量记录 + `keep` 字段 + `drop_reason`**，淘汰的条目留在文件里。
`common.py` 顶部与两处门禁盯着这件事。

**② S2 是按字段名逐个搬运的，新增字段不会自动跟着走。**

实测踩过：`boundary_confidence` 在 S3 产物里是 `high`/`low`，到 S2 产物全变
`None` —— 而当时四组门禁全绿，是靠 `query-units.py` 筛出「codex 通道 0 条高可信
单元」才暴露的。修法是给 `verify-phase1.py` 加了一道贯穿字段门禁（`CARRY_FIELDS`
全为 None 即报红），并进了自证 case。往 S3 加字段时，记得同时改 `s2-desensitize.py`
的搬运列表。

**③ 零写操作的单元记 `unrated`，不要判 easy。**

51.1% 的单元 `edit_ops == 0`（3927/7692，纯问答/探索会话，已核对不是 S3 漏算）。
判成 easy 会造出 easy 67.3% 的偏斜（实测反事实），与 v0.1 的 hard 87.4% 是同一个病：**用一个与难度无关的
量当难度锚点**。只对有写操作的单元评级，实测 hard 43.4% / easy 33.1% /
medium 23.5%（n=3765），通过「单档 ≤60%」的验收线。这批 3927 条的难度等 Phase 3 有了参考解
diff 再定（§4.6 要求绑 gold patch 的 hunk/行数）。

**④ 分类打分要封顶，不然粘贴的日志会压倒真实意图。**

instruction 中位数 448 字符、20.3% 超过 2000，「问题」一词在全体单元里出现 42196
次且绝大多数在粘贴的日志里。实测病理用例「请你重构这个模块的结构」+ 20 行含
「问题/报错/修复」的日志：封顶前 bug_fix 得 102 分而 refactor 仅 3 分，判成
bug_fix。两个修法都在 `labeler.py`：`HIT_CAP = 2`（同一类别命中次数封顶，
出现 1 次和 20 次等价），以及**头部取首行而非固定切 120 字符**（用户写的诉求
通常只占第一行，固定切会把日志一起圈进「头部」，头部权重 ×3 反而放大日志）。

**⑤ 「切分正确率 ≥90%」这条验收线本轮做不到，也无法用现有数据证明。**

不是没调权重，是**没有可信的裁判**：hook 通道 `user_prompts` 当裁判得精确 58.4% /
召回 58.9%，但按裁判完备度分层后两端走势相反（记 1 条时精确 38.7%/召回 77.5%，
记 ≥5 条时精确 50.0%/召回 38.7%）—— 说明双方都有错，裁判会漏记（56.1% 的会话
只记 1 条 prompt），我方也会多切。在这种情形下报「正确率 92%」只是选一个对自己
有利的分母。

替代门禁三条（全部机械可判，实现在 `verify-phase1.py:check_s3`）：

  ① 逐信号精确率必须与 `BOUNDARY_CONFIDENCE` 的分档一致（实测 high 75.0% >
     medium 52.3% > low 42.9%，单调递减）
  ② high 档精确率 ≥65%（实测 75.0%）
  ③ 单元 `step_range` 必须构成轨迹的划分（互不重叠、随 seq 递增）——
     **这条不依赖裁判**，重叠必然是 bug。实测它抓出三个真实缺陷，修掉后
     重叠率 49.8% → 0%

并把 `boundary_confidence` 写进产物：`high` 4302 / `medium` 452 / `low` 2938。
**Phase 2 必须对 low 档 2938 条做 LLM 复判**（`B_TASK_PATTERN` 实测精确率仅
37.4%）。这是对自身局限的披露，不是绕过验收。

> ⚠️ **2026-09-07 补充：上面这句「对 2938 条做 LLM 复判」照字面执行会做错。**
> 完整方案见 `docs-research/trajectory-platform/bench-curation-design.md` §9.6，
> 三处要点：
> **(a) `2938` 是边界数，不是调用数。** 判一个边界是否新任务必须看它前后的轮次，
> 送审单位只能是**会话** —— 2793 个 `B_TASK_PATTERN` 边界分布在 1222 个会话，
> 加 medium 档共 **1355 个会话**。
> **(b) 漏了「少切」，它比多切更危险。** 召回仅 58.8%，说明规则不只多切还漏切。
> 多切产生的碎片在 S4 会被自然淘汰（有一层免疫），少切产生的「一个 task 塞两件
> 不相关的事」能通过 S4 和 S5，到 Phase 3 才暴露成「不存在单一 gold patch」。
> 故 prompt 要写成「给出完整任务划分」而非「判断这些边界对不对」，做**双向 diff**，
> 送审范围扩到**全部 1400 条多轮会话**。
> **(c) 换一个裁判不等于有了裁判。** 坑⑤ 论证了 hook 裁判不可信；直接拿未校准的
> LLM 判定覆盖 `step_range`，等于把这段论证作废。**前置门槛：50-80 条人工校准集，
> 同时报规则与 LLM 两个 κ，κ≥0.6 才允许改写 `step_range`**；κ<0.6 则只落
> `boundary_disputed` 降权字段。

**⑥ 「提取不出轮次」不等于「不可能切错」—— 这两件事必须分开标。**

这是本轮最值得记住的一个缺陷，因为**它让门禁数字变得更好看**，所以三道门禁全绿
也没抓到它。

`B_NO_RAW` 走的是 `if not turns` 兜底分支，原先同时盖住两种情况：真没有
`raw.jsonl`（28 条），以及有 `raw.jsonl` 但轮次提取返回空（1232 条）。后者是
**该切没切**，却跟着前者一起拿了 high 置信度 —— 而 high 的理由是「整条会话一个
单元，不存在切错的可能」，这句话对后者根本不成立。

它躲过了全部现有门禁：区间不重叠（只有一个单元，天然不重叠）、单调递增（同上）、
high 档精确率**反而被它抬高**（不切分就不会切错，那 36 个可裁判样本 100% 命中，
把 high 档从 75% 拉到 84%）。发现它靠的是写交接文档时核对「98.9% 的会话有
raw.jsonl，为什么 1282 个单元标着 B_NO_RAW」这个对不上的数。

两处根因，都在轮次提取：

| 根因 | 表现 | 修法 | 救回 |
|---|---|---|---|
| 首行无条件取最后一条 user 消息 | 末尾是 `tool_result` 或 `<system-reminder>` 时取到空 | 改取「最后一条**含真实文本**的」，往前找 | 900 条 |
| slash command 整块判噪声 | 任务写在 `/goal <参数>` 里被一起丢掉 | 从 `<command-args>` 取，要求长度 ≥15 且含任务动词 | 194 条 |

剩下 138 条确实一个非噪声文本块都没有，改记 `B_EXTRACT_FAILED` + **low**，
交 Phase 2 复判。修完的净效果：

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 保留单元 | 7094 | **7692**（+598） |
| `step_range` 映射率 | 83.5% | **97.0%** |
| high 档精确率 | 84.2% | 75.0%（仍 ≥65%） |

**high 档精确率降 9 个点是修复的结果，不是退化** —— 原先那批「整条一个单元」白占
了 100% 精确率的便宜，切开后露出的是真实难度。新增两道门禁盯着它不许回来：
`B_NO_RAW` 不许盖 `has_raw` 的会话、`B_EXTRACT_FAILED` 必须是 low。

## 单元测试

```bash
python3 -m pytest ../tests/test_s1_s3.py -q     # 117 项
```

固定住每条实测标定的结论：S1 的 R5「中断不淘汰而是转 S3」、脱敏正则的边界与
幂等性、S3 的噪声识别与区间映射、难度分档的 `unrated` 语义、分类打分的封顶与
头部取法、以及贯穿字段与数据湖只读纪律。若哪天有人把这些改回错的写法，测试会变红。

`verify-phase1.py` 与本文件的分工：门禁验「产物合不合格」（跑在真实 7692 条上），
单测验「判定逻辑对不对」（跑在构造样例上，0.04 秒）。两者都要绿。

## 交接 Phase 2

最终交付物 `data/bench-staging/phase1/meta/labeled-v2.jsonl`，7692 行，每行一个
任务单元，含四组信息：

| 组 | 字段 |
|---|---|
| 身份与切分 | `unit_id` / `sid` / `seq` / `step_range` / `started_at` / `ended_by` / `boundary_reason` / `boundary_confidence` |
| 脱敏文本 | `instruction_clean` / `files_clean` / `test_cmds` / `secret_severity` / `secret_types` / `needs_review` |
| 源信息 | `agent_source` / `model` / `vendor` / `repo` / `repo_resolution` / `provenance` / `batch_version` |
| 分类与客观量 | `category` / `category_confidence` / `tags` / `difficulty` / `difficulty_basis` / `edit_ops` / `error_ops` / `n_test_cmds` / `n_files` / `session_steps` / `unique_tools` |

进 Phase 2（S3.5 切分复判 + S4 分诊 + S5 去重）之前要注意的四件事：

1. **切分复判要排在 S4 之前**（见坑⑤及其 2026-09-07 补充）。否则切错的单元会被当成
   合法 task 进 L1/L2。**注意口径**：判定单位是**会话不是边界** —— 送审 **1400 条
   多轮会话**（不是 2938 个边界），双向查多切与少切；且**必须先建 50-80 条人工校准集
   并量 κ**，κ≥0.6 才允许改写 `step_range`。主判用 `claude-opus-5`，交叉裁判用另一
   厂商模型。成本约 $13-26。完整方案见方案文档 §9.6。
   `B_NO_RAW` 那 28 条**判不了**（没有 `raw.jsonl` 就没有轮次序列），按 steps 过长
   淘汰处置。
2. **`needs_review` 32 条不进公开 split**。它们含 high 级敏感命中（`sk-` 密钥、
   身份证、内联凭据等），已在产物里标好。
3. **`repo_resolution == conflict` 的单元要降权**（573 个单元，来自 269 条会话）。
   多路信号矛盾，Phase 0 抽样实测这一档就是错判的集中区。
4. **`E_SELF_REFERENTIAL` 已在 S1 淘汰 272 条**，但 `excluded_hit` 是路径级判定。
   方案 §11 未决项 3（自指污染是否可接受）仍未定，S4 构造 task 时要复查。
