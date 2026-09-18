# Phase 0 — 地基

对应 `docs-research/trajectory-platform/bench-curation-design.md` §9 Phase 0。
实施记录在该文档 §9.0（归档）、§9.1（S0 与反解）、§9.2（批次治理）。

**Phase 0 已全部完成**（含采集侧两个 P0，已于 2026-09-05 11:48 重启验证生效）。
这里是给下一棒（Phase 1 清洗）的入口说明；方案侧的完整交接见文档 §9.4。

## 先跑这一条

```bash
# 验收当前状态。全绿才说明地基完好，可以进 Phase 1
python3 s0/verify-s0.py --sample 150
./s0/verify-archive.sh
./s0/check-collector-live.sh   # 采集器跑的是不是最新代码
```

两个脚本都是**幂等的只读检查**，随时可跑。报红时按下面的对应关系处理。

## 文件

| 文件 | 作用 | 何时要跑 |
|---|---|---|
| `archive-repos.sh` | `git clone --mirror` 冻结全部仓库的完整 refs | 进入新阶段前重跑一次（幂等，只增量拉新 refs） |
| `verify-archive.sh` | 归档验收：抽样 commit 对象完整 + 逐 ref 比对 + worktree tip | 每次进入新阶段（当作入口门禁） |
| `repo_map.py` | 路径→仓库映射、`working_directory` 三路加权反解、会话目录枚举、两份清单加载 | 被下面几个脚本引用，不单独跑 |
| `s0-pull.py` | 平台 HTTP → `data/pulled_sessions/`（gitignore）。URL/口令走环境变量，仓内无默认端点 | 有凭据要填湖时 |
| `s0-normalize.py` | S0 归一化：`session.traj` → `sessions-v2.jsonl` + `instructions/<sid>.txt` | 每次 `s0-pull.py` 拉了新数据之后 |
| `verify-s0.py` | 七组验收门禁 + `--self-test` 反向自证 | S0 之后；改动 S0 逻辑后跑自证 |
| `freeze-batch.py` | 冻结批次：sid 清单 + 内容指纹 + 截止时间戳 | 决定「这一批就洗到这里」时 |
| `excluded-paths.txt` | 自指污染排除清单，S4 强制引用 | 数据文件，不跑 |
| `legacy-trashed-sids.txt` | 上一轮手工移入 `_trash/` 的 1722 条会话清单 | 数据文件，不跑 |
| `check-collector-live.sh` | 采集器部署自检：运行中的进程是否加载了最新二进制 + 端到端验证新会话真的带上了 git 状态 | 每次改完 claude-trace、以及怀疑新字段没生效时 |
| `_check_traj_git.py` | 上面第 ④ 项的实现（拆成独立文件避免嵌套 heredoc） | 被上面调用，不单独跑 |

## 报红怎么处置

| 报红 | 含义 | 处置 |
|---|---|---|
| 磁盘上有 N 条会话未进索引 | 拉了新数据，索引过期 | 重跑 `s0-normalize.py` |
| ref 未进镜像 | 仓库日更导致归档漂移（**正常现象**，已复现三次） | 重跑 `archive-repos.sh`，幂等增量 |
| 运行中的代码已过期 | proxy 未重启 | `claude-trace restart` |
| 含 git 状态 0 条 | 两个 P0 未生效 | 同上。注意前三项形式检查可能全绿 |
| 可裁判样本仅 N 条，少于下限 | `--sample` 给小了 | 加大到 150 |

## 标准流程：拉了新数据之后

```bash
# ① 拉取（地址和口令走环境变量，仓内无默认、不要写进命令历史）
#    ⚠️ 用 --workers 2：实测 8 并发会把服务端压出 HTTP 502
#    （8 并发 653 条失败 / 3 并发 357 / 2 并发 219，串行重试则全部成功）。
#    502 不是数据损坏（无一条 missing），纯粹是并发承载问题。
export TRAJ_PLATFORM_URL=...          # 必填
export TRAJ_AUTH_PASS=...             # 必填
export TRAJ_AUTH_USER=admin           # 可选
python3 s0/s0-pull.py --workers 2
# 若当前目录不是仓根：python3 pipeline/s0/s0-pull.py --workers 2

# ② 重跑 S0（全量幂等，8 进程约 20 秒）
python3 s0/s0-normalize.py --workers 8

# ③ 验收（必须全绿）
python3 s0/verify-s0.py --sample 150

# ④ 冻结批次，Phase 1 只洗这一批
python3 s0/freeze-batch.py --version v0.2
```

## 三条不要踩的坑

**① 不要靠移目录来表达「淘汰」。**

`s0-pull.py` 的 `should_skip` 去重只查 `data/pulled_sessions/<sid>/.pulled`。把会话目录移走，
标记跟着走，下次拉取就判为「未拉取」并重新下载 —— 上一轮的 `_trash/` 正是如此，
实测让 1722 条会话进了待拉取清单（占 2601 条的 66%）。

原则是**原始层只增不删，淘汰在元数据层表达**：用 S0 索引的 `legacy_trashed` /
`excluded_hit` 字段标注，让 Phase 1 的 S1 按规则判定。`verify-s0.py` 和单元测试
各有一道门禁盯着 `_trash/` 不许回来。

**② 不要等数据稳定，要冻结批次。**

线上日增约 77 条，等不到静止。这与归档面对的是同一个问题：仓库在日更，所以我们
`--mirror` 冻结快照；数据同理。冻结过的批次不可改写（`freeze-batch.py` 会拒绝
覆盖不同指纹），新数据冻结为新版本号，**不回炉重洗**。

**③ 改完采集器，别忘了它跑的是二进制。**

`~/.claude-trace/bin/claude-trace-proxy` 是 PyInstaller onefile，**启动时就把代码
加载进内存**。改磁盘上的 `.py` 不影响已运行的进程，重新构建二进制也不影响 ——
必须 `claude-trace restart`。

`watch-reload.sh` 兜不住这个：它监的是仓库里的 `.py` 源文件，而生产跑的是二进制。
源文件变了二进制没变、二进制重建了 watch 又不监它，两边都没覆盖到。

实测代价：§8.5 记录的两个 P0 写完后，**11 天里新采的会话一条都没带上 git 状态**
（详见方案 §9.3）。进程活着、端口通着、健康检查也绿 —— 唯一症状是产出数据缺字段。
所以有了 `check-collector-live.sh`：前三项查形式（进程新旧、文件一致性），
**第 ④ 项直接看产出数据**，因为形式检查全绿也不代表字段真的写进去了。

hook 侧不受此影响：每次事件由 Claude Code 新起 `python3` 进程，天然加载最新代码。

**④ 改了门禁就要跑自证。**

```bash
python3 s0/verify-s0.py --self-test
```

七个 case：一个健康基线必须保持绿，六类注入缺陷必须变红**且变红原因对得上号**。
只看退出码是不够的 —— 加入磁盘对账后，任何被裁剪的索引都会因「索引过期」变红，
自证会看着全绿却什么都没验到。§9.0 记录过这类假绿的代价：三个 bug 叠起来做到
「18 个仓库全绿，其中 4 个根本没验」，外表与真绿完全一致。

自证要求索引与磁盘同步。若提示「索引与磁盘差 N 条」，先重跑 `s0-normalize.py`。

## 对账要看 `.pulled` 标记，不是目录数

502 失败时会话目录已建但文件可能不全，且 `.pulled` 标记不会写 —— 所以重跑会自动
重试（不会漏），但**「主目录条数」不等于「完整会话数」**。

`.pulled` 里 `files` 字段的四种取值，本轮实测分布：

| 取值 | 条数 | 含义 |
|---|---|---|
| `ok` | 8507 | 本轮成功下载 |
| `skipped` | 38 | **本地已有且未变，不是缺失** —— 实测这 38 条文件全部存在且非空 |
| `missing` | 9 | 云端确实没有 |
| 无标记 | 5 | 早期遗留，但都有 `session.traj`，可用 |

`skipped` 最容易误读成失败。它的语义是「指纹未变，跳过下载」。判断完整性要落到
「本地文件是否存在且非空」，别看标记字面值。

最省事的办法是跑 `verify-s0.py` —— 它的磁盘对账会把差额逐条列出来。

## 索引字段速查

`data/bench-staging/meta/sessions-v2.jsonl`，一行一条会话。

| 字段 | 说明 |
|---|---|
| `repo` / `repo_resolution` | 反解出的仓库与置信度：`direct`（三路一致）、`voted`、`inferred`（单路）、`conflict`（多路矛盾，**下游应降权**）、`unresolved` |
| `repo_signals` | 三路信号的原始结论 + `traj_hits`（轨迹命中次数，用于判断证据强度） |
| `agent_source` | 采集通道：`claude_code` / `codex` / `sid_code` / `short_id`。**线上非单一来源，模型分布与字段集都不同，混算会得出错误结论** |
| `provenance` | `pre_upgrade` / `post_upgrade`。后者才有 git 状态（claude-trace v0.2.0 起） |
| `n_edit_ops` / `n_error_ops` / `n_test_cmds` / `file_paths_hash` | §4.2 点名必须逐 step 扫 trajectory 才能得到的四个字段 |
| `n_rebuildable_writes` / `n_parse_error_writes` | diff 可重建性。后者是采集时 JSON 截断，约占写调用 3% |
| `excluded_hit` | 命中自指污染前缀，S4 淘汰（原因记 `E_SELF_REFERENTIAL`） |
| `legacy_trashed` | 上一轮被手工移入 `_trash/` 过 |
| `instruction_len` | 指令长度。**正文在 `instructions/<sid>.txt`**，不在索引里（v0.1 把正文塞进索引导致 51MB） |

## 单元测试

```bash
python3 -m pytest ../tests/test_s0.py -v
```

固定住每条实测标定的结论（三路权重、路径口径、正则边界、排除清单按段匹配、
批次指纹语义）。若哪天有人把权重改回等权或把路径口径放宽到自由文本，测试会变红 ——
这些结论都是拿 mirror 客观裁判在数百条样本上测出来的，不是拍脑袋定的。
