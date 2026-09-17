# 评测过程证据（v0.2-mini）

本目录只有**指针**：`MANIFEST.tsv`、`SHA256SUMS`、`evidence.jsonl`。
字节在 Hugging Face dataset [`njfuzrs/agent-traj-bench`](https://huggingface.co/datasets/njfuzrs/agent-traj-bench)
的 `evidence/v0.2-mini/`（与 39 份 `snapshots/` 同仓）。

```bash
# 证据 + 快照一次拿齐
hf download njfuzrs/agent-traj-bench --repo-type dataset --local-dir ./atb-hf
# 或只要证据层
hf download njfuzrs/agent-traj-bench --repo-type dataset --include "evidence/**" --local-dir ./atb-hf
# 校验
cd atb-hf && shasum -a 256 -c <(awk '{print $1, $2}' ../agent-traj-bench/reports/evidence/SHA256SUMS | sed 's|evidence/v0.2-mini/||')
```

近线副本（同盘，**不算独立副本**）：环境变量或参数指向的本地 `*.tar.zst` 目录。
独立副本只有 HF 那一份。

## 归档了什么

22 个 `.tar.zst`（21 个 job + `_stage-prompts`）。归档单元是 **job**（`20*__*` 目录），
不是 trial。解开保留 job 目录层：`tar -tf` 第一行是 `<job_path>/...`。

`_stage-prompts.tar.zst` 是 `t8-fix/stage/` 与 `t8-rerun/tasks/` 的非 tar 文件
（`instruction.md` 经 batch_inlines 内联后与公开仓 `tasks/` 不同，是 t8-rerun
相对 baseline 归因的核心输入）。`repo-snapshot.tar.gz` 已在 `snapshots/`，不重复归档。

## 脱敏

门禁⑤ 盯的私有仓源码路径换成 `<REDACTED-PRIVATE-PATH>`。
实测作用面（Python 走目录树，**不经过 grep**）：

- 10 个文件 / 823 处命中
- 其中 1 个（`t8-fix/docs/` 下那份 T0063 报告）是入库文件，公开仓已有脱敏版，不在包内
- 其余 9 个文件 / 813 处全部在 `t8-rerun/2026-09-13__19-35-38` 一个包里
- 另外 21 个包一处未改

`MANIFEST.tsv` 的 `redacted` 列写明了哪个包被改过。
⛔ 不许说「证据层全部原样公开」，也不许说「证据层含隐私」——
真名与公开 API 端点在本项目已被裁决为已披露的历史证据，唯一处理的是门禁⑤ 盯的路径。

### 为什么不是「3 文件 / 95 处」

归档方案初稿用 `grep -rlIE` 量出 4 文件 / 95 处。那是一次**漏扫**：
本机 `grep` 是 ugrep，**默认读 `.gitignore`**；证据里的
`<trial>/agent/sid-home/.gitignore` 忽略 `sessions/`、`trajectories/`、`*.log`，
递归时静默跳过 6 个文件 / 728 处。逐个点名文件时 ugrep **能**命中 ——
漏扫只在递归时发生。`/usr/bin/grep` 与本仓 `redact-evidence.py` 都给出 10 / 823。
CI 是 GNU grep（不读 gitignore）⇒ 漏扫的方向是「本地假绿、CI 报红」。

## 26 条 T6 淘汰题的 repo-snapshot.tar.gz（161 MB）判弃归档（2026-09-17 裁决）。

判据：base_commit 26/26 在采集机 sid-code 仓与
`_archive/bench-mirrors/person_sid-code.git` 镜像中命中，题面与判分文件在私有仓
agent-traj-corpus 的 v02-eliminated/（每条 11 文件）⇒ 可用 t4-build-env.py 重建。

⚠️ 代价：重建出的 tar 与原 tar 未必字节一致（gzip 头含时间戳），故
meta/snapshots.jsonl 里这 26 条的 tar_sha256 ⛔ 不再可校。
⛔ 不许说"26 条淘汰题快照已归档" —— 是判弃 + 可重建，两回事。

`meta/snapshots.jsonl` 那 26 行的 `tar_sha256` 字段照留（历史事实），只是不再可校。

## 清单字段

全部从 `lock.json` / `result.json` 派生，⛔ 不手写数字。注意：

- `model` 只有跑真 agent 的 job 有值；`nop` / `oracle` 桩是空（正确值，不是缺失）
- `n_concurrent_trials` 按 job 存（有的是 1，有的是 6），⛔ 不许用一个值覆盖全部
- `dataset_source` 原样存（多种取值，含空），⛔ 不许归一成 `tasks`
- `n_planned` / `n_scored` / `n_total_trials` 三列都在，⛔ 不许只存一个
- `leak_hits` 是四类内网判据（真名 / 内网域名 / 内网仓名）的命中文件数，
  **披露事实**，不是「不能公开」的理由

## 以后再跑评测

差集闸（⛔ 不挂 CI —— CI runner 上没有 runs 目录，分子恒 0 会恒绿）：

```bash
EVIDENCE_RUNS_ROOT=<runs 根目录> python3 scripts/check-evidence-due.py
```

`EVIDENCE_RUNS_ROOT` 必须显式给，没给则 exit 2，⛔ 不是跳过。
可挂本机 `.git/hooks/pre-push`（不入仓，clone 不会带上）。

重新归档：

```bash
python3 scripts/redact-evidence.py --root <runs根> --dry-run
python3 scripts/t10-archive-evidence.py --root <runs根> --out <近线目录> --pack
python3 scripts/t10-archive-evidence.py --root <runs根> --out <近线目录> --scan-packed
python3 scripts/t10-archive-evidence.py --root <runs根> --out <近线目录> --push
```

`--scan-packed` 会把每个包解到临时目录再跑门禁⑤。⛔ 不许用 `grep -I` 扫 `.tar.zst`
本身（跳过二进制 ⇒ 恒绿）。
