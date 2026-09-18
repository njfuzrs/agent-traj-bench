# pipeline — 轨迹清洗链路（S0 → S3）

把原始 Agent 轨迹洗成可发题的任务单元。`tasks/` 里那 39 道题的上游就是这一层。

对标 [SWE-bench](https://github.com/princeton-nlp/SWE-bench) 的 `collect/`：
**采集与清洗的代码入库，原始语料不入库。**

```
   s0/  s0-pull.py           平台 HTTP → 本地湖（URL/口令走环境变量）
        ▼
data/pulled_sessions/        原始轨迹数据湖（gitignore，不入库）
        │
        ├─ s0-normalize.py   归一化 + working_directory 三路反解
        ▼
   s1_s3/  s1-filter.py      S1 硬过滤（六条规则）
           s3-split.py       S3 会话切分成任务单元
           s2-desensitize.py S2 单元级脱敏
           label-units.py    分类 / 标签 / 难度
        ▼
   phase1/meta/labeled-v2.jsonl   ★ 本层终点，也是与 scripts/ 的唯一接口
        │
        ▼
   scripts/t1-select-candidates.py  题集链路从这里接手
```

## ⚠️ 先读这五条（前三条是 clone 下来一定会撞上的）

### 1. 本层在公开仓里跑不起来 —— 这是预期的

原始轨迹 **不入库**（只有清洗代码入库，语料不入库）。
`SESSIONS_DIR` 默认值 `data/pulled_sessions` 在 fresh clone 里不存在，所有读盘脚本都会空跑。

要真跑（有平台凭据 + 磁盘）：

```bash
export TRAJ_PLATFORM_URL=...          # 必填，仓内无默认
export TRAJ_AUTH_PASS=...             # 必填
export TRAJ_AUTH_USER=admin           # 可选
python3 pipeline/s0/s0-pull.py --workers 2
export SESSIONS_DIR="$PWD/data/pulled_sessions"
```

已经有一份湖时，只 `export SESSIONS_DIR=` 指过去即可，不必重拉。

单测不受影响 —— 构造输入默认跑；依赖真湖的那 2 条会 **skip 并说明原因**。

### 2. 真实仓库清单要自己提供

`s0/` 的 `base_commit` 反解要一份「已知仓库清单」。仓内
`config/repos.example.json` 只含**已公开披露的 10 个仓**，真实清单是 18 个
（另外 8 个是未披露的内网仓，不入库）。

```bash
export REPO_MAP_CONFIG=<你的 repos.json>     # 格式见 config/repos.example.json
```

`repo_map.py` 与 `s0/archive-repos.sh` **读同一个文件** —— 原先两处各写一份数组、
靠注释保持同源，改一处忘另一处的代价是不可逆的：反解出的仓库不在归档内，
那些会话的 `base_commit` 从此无从定位。

清单不全不会算错，只是少反解出几个仓（对应会话记 `unresolved`）。

### 3. mirror 只在采集机上

`s0/archive-repos.sh` 需要 **18 个 bare 仓**（`git clone --mirror` 冻结，
实测 1.8G，落在 `~/Code/_archive/bench-mirrors`）。**未分发**。

它存在的理由：轨迹里的 `base_commit` 可能已被 force-push 或分支删除覆盖掉，
不冻结就永久失去锚点。没有 mirror 时 `verify-archive.sh` 与依赖归档的那条单测
会 skip。

### 4. 本层与 `scripts/` 的边界

**唯一数据接口是 `labeled-v2.jsonl`**：本层 `label-units.py` 产出它，
`scripts/t1-select-candidates.py` 通过 `c.LABELED_V2` 消费它。除此之外两层不互相
import、不共享目录。

⚠️ 两层各有一个 **`common.py`，同名不同物**（本层是三阶段清洗契约，`scripts/`
那份是题集契约，常量表不兼容）。两层从不在同一进程里跑生产代码，唯一会撞的场合是
`pytest pipeline/tests scripts/tests` 一次收集两个目录 —— 那时 `sys.modules`
进程级缓存会让**谁先加载谁赢**。判据落在 pytest 层：两层各有一个 `conftest.py`
按绝对路径钉住本层那份，外加两条对称的隔离断言。

⛔ **不许把两份 `common.py` 合并成一份「公共层」。**

### 5. 本层零第三方依赖

只用标准库。跑单测只需 `pytest`：

```bash
cd pipeline && python -m pytest tests -q      # 构造输入全绿；真湖缺失时 2 条 skip
```

⚠️ 这条性质是本层的卖点之一，**加依赖前先想清楚**。CI 门禁⑩ 用 ast 遍历盯着它
（判据是「import 的顶层模块名 ∈ 标准库 ∪ 本层自己的模块」，不是「pip list
里有没有」—— 后者在装了全套依赖的机器上永远绿）。

## 各阶段产物与验收

| 阶段 | 脚本 | 产物 | 实测保留 |
|---|---|---|---|
| S0 归一化 | `s0/s0-normalize.py` | `meta/sessions-v2.jsonl` | 8562 会话 |
| S0 冻结批次 | `s0/freeze-batch.py` | `meta/batch-v0.2.json` | — |
| S1 硬过滤 | `s1_s3/s1-filter.py` | `phase1/meta/filtered-v2.jsonl` | 4381 / 8562（51.2%） |
| S3 切分 | `s1_s3/s3-split.py` | `phase1/meta/units-v2.jsonl` | 7692 单元 / 7721 |
| S2 脱敏 | `s1_s3/s2-desensitize.py` | `phase1/desensitized/units.jsonl` | 7692（80.2% 命中，二次扫描零残留） |
| 分类标注 | `s1_s3/label-units.py` | `phase1/meta/labeled-v2.jsonl` ★ | 7692 |
| 检索入口 | `s1_s3/query-units.py` | — | 随时可跑 |

⚠️ **S2 排在 S3 之后**（与编号顺序相反）：S1 保留会话的 `raw.jsonl` 合计 47.6GB，
按 session 全量重写既慢又占盘，而真正会发布出去的只是单元级的 instruction 与
文件路径。所以先切分，再对单元脱敏。

S1 淘汰归因：`R1_EMPTY` 2659 / `R2_TOO_SHORT` 1112 / `E_SELF_REFERENTIAL` 272 /
`R4_TOO_FEW_TOKENS` 120 / `R3_NO_ACTION` 18 —— 4181 条全部有归因。

### 验收命令

```bash
# S0（幂等只读）
python3 s0/verify-s0.py --sample 150
./s0/verify-archive.sh                # 需要 mirror

# S1→S3（幂等只读）
python3 s1_s3/verify-phase1.py

# 改了任何判定逻辑之后，必须跑反向自证
python3 s0/verify-s0.py --self-test
python3 s1_s3/verify-phase1.py --self-test    # 约 4 分钟，CPU 密集
```

`--self-test` 慢是刻意的：它把 S3 的独立信号对账（1313 条会话逐条 difflib 比对）
跑 6 遍，不缓存才能保证每个注入 case 都真的走完整条判定链。

### 完整重跑

```bash
export SESSIONS_DIR="$PWD/data/pulled_sessions"   # 先 s0-pull.py，或指已有湖
export REPO_MAP_CONFIG=<你的 repos.json>          # 完整清单仓外，见 config/repos.example.json

python3 s0/s0-normalize.py --workers 8            # 约 20 秒
python3 s0/verify-s0.py --sample 150              # 必须全绿
python3 s0/freeze-batch.py --version v0.2

python3 s1_s3/s1-filter.py --batch v0.2
python3 s1_s3/s3-split.py --batch v0.2 --workers 8   # 约 47 秒
python3 s1_s3/s2-desensitize.py
python3 s1_s3/label-units.py
python3 s1_s3/verify-phase1.py                    # 必须全绿
```

写盘的脚本都有 `--dry-run`（只打统计不写盘）；`s0-normalize.py` /
`s3-split.py` / `s2-desensitize.py` 另有 `--limit N`（抽样试跑）。
两个 `verify-*.py` 是只读的，没有这两个开关。

## 目录

| 路径 | 内容 |
|---|---|
| `s0/` | 入湖、归一化、仓库反解、mirror 归档、批次冻结（12 文件） |
| `s1_s3/` | S1 过滤、S3 切分、S2 脱敏、分类标注（11 文件） |
| `config/repos.example.json` | 仓库清单示例，真实清单靠 `REPO_MAP_CONFIG` 外置 |
| `tests/` | `test_s0.py` + `test_s0_pull.py` + `test_s1_s3.py`；真湖缺失时 2 条 skip |

各层细节见 `s0/README.md` 与 `s1_s3/README.md`。

判定逻辑一律拆成 `*_rules.py` / `*_segment.py` / `labeler.py`，脚本只负责读盘写盘
—— 单测能直接 import 判定函数，不必造文件。

## 设计取向

**原始层只增不删，淘汰在元数据层表达。** 不靠移目录来表达「淘汰」：拉取脚本的
去重只查 `<sid>/.pulled` 标记，把会话目录移走标记跟着走，下次就判为「未拉取」
重新下载 —— 实测让 1722 条会话进了待拉取清单（占 2601 条的 66%）。

**冻结批次，不等数据稳定。** 线上日增约 77 条，等不到静止。冻结过的批次不可改写
（`freeze-batch.py` 拒绝覆盖不同指纹），新数据冻结为新版本号，不回炉重洗。

**贯穿字段。** 七个字段（`agent_source` / `model` / `vendor` / `repo` /
`repo_resolution` / `provenance` / `batch_version`）会话级、单元级都带，每层由
`verify-phase1.py` 加门禁 —— 任何一层丢字段即报红。四条采集通道的模型分布完全不同，
混算得到的是三种工具的加权平均。
