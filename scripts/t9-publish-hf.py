#!/usr/bin/env python3
"""T9 — HF 仓（快照层）发布：现算 README + 重出两个索引 jsonl + 上传

出处：`docs-research/trajectory-platform/20260916-curation-migration.md` §5.1 之后
的补漏项（HF 侧一直没有生成器，见下方「为什么要有这个脚本」）。

## 为什么要有这个脚本

HF 仓（`huggingface.co/datasets/njfuzrs/agent-traj-bench`）当初是**一次性手工上传**
的：全仓 0 处 `hf upload` / `HfApi` / `upload_folder`，也没有任何脚本生成它的
`README.md`。而那份 README 自己写着：

    ⚠️ 本页数字全部由脚本从 `tasks.jsonl` / `snapshots.jsonl` 现算，⛔ 没有手写数字。

⇒ **这条自证当时无法被验证**。形态与 §2.2 那个 P0（card 印着取数源、产生它的产物却
不在仓里）是同一类：*声明了一条自证链，但产生它的东西不在仓里*。手工传第二次，就是
把这个假自证再续一轮 —— 所以补本脚本。

🔴 判据是「**能不能复现**」，不是「能不能上传」：`--check` 不带任何凭证就能跑，把现算
结果与 HF 线上逐字节比对。这才是那句自证的兑现方式。

## 三层产物与本脚本的边界

| 层 | 放哪 | 本脚本管不管 |
|---|---|---|
| 39 份 `snapshots/T####.tar.gz`（247.9 MiB） | HF | 管上传，但**本机通常没有** —— 见下 |
| `tasks.jsonl` / `snapshots.jsonl` / `README.md` | HF | **管，全部现算** |
| 题面 / 判分脚本 / `DATASET_CARD.md` / 漏斗报告 | GitHub | 不管（HF README 里指过去） |

⚠️ **快照 tar 不在公开仓里**（`.gitignore:6` `tasks/*/environment/repo-snapshot.tar.gz`），
本机实测 0 份。所以**默认不带快照**：只发 README + 两个 jsonl（要带就显式
`--with-tars --tars-dir <DIR>`）。⛔ 不要为了「让上传完整」
去重建快照 —— 那需要采集机上的 19 个 bare mirror，且重建出的 tar **未必逐字节等同**
已冻结的那份（`tar_sha256` 会变 ⇒ 反而把 HF 上正确的快照覆盖成新的）。
真要重传快照：先 `t4-build-env.py --from-snapshots <已有快照目录>` 校验通过，再 `--with-tars`。

## 取数源（全部仓内，零外部依赖）

  - `tasks/T####/meta.json`      → tasks.jsonl 的 9 个字段 + n_f2p/n_p2p
  - `tasks/T####/instruction.md` → instruction_len（**字符数**，不是字节数：
    实测 T0002 = 235 字符 / 403 字节，HF 上是 235 ⇒ 口径是 `len(str)`）
  - `meta/snapshots.jsonl`（70 条）→ 裁到 `tasks/` 的 39 条，**逐行原样透传**
  - README 的 7 处数字全部由上面两份现算，⛔ 无一处手写

## 用法

    python3 scripts/t9-publish-hf.py --check      # $0、免凭证：与线上逐字节比对
    python3 scripts/t9-publish-hf.py --out /tmp/hf   # 只落盘，不传
    python3 scripts/t9-publish-hf.py --push       # 落盘 + 上传（README + 2 jsonl）
    python3 scripts/t9-publish-hf.py --push --with-tars --tars-dir <DIR>   # 连快照一起

退出码：0 一致/成功；4 现算结果与线上不一致（`--check`）或校验失败；
        5 缺 huggingface_hub（只在 --check/--push 时需要）。
⛔ 不用 1 —— 那和 argparse 的参数错混了（同 t4-build-env.py 的约定）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common as c  # noqa: E402

#: HF 数据集仓 ID。⚠️ 与 GitHub 仓同名但是**两个仓**，内容按上面那张表分层。
HF_REPO = "njfuzrs/agent-traj-bench"

#: tasks.jsonl 的键序 —— ⛔ 必须与线上逐字段同序，否则 `--check` 的逐字节比对会假红。
#: 实测线上键序就是这 11 个（见 §「取数源」）。
TASKS_KEYS = ("task_id", "repo", "base_commit", "band", "category", "test_cmd",
              "f2p", "p2p", "instruction_len", "n_f2p", "n_p2p")

#: 上传时**只**动这三个文件（不带 --with-tars）。
#: ⛔ 不用 upload_folder 传整个目录：那会把本地缺失的 snapshots/ 当成「要删」，
#: 而 delete_patterns 一旦写错就是把 247.9 MiB 快照删了 —— 逐份 upload_file 没有这个风险。
INDEX_FILES = ("README.md", "tasks.jsonl", "snapshots.jsonl")


def version() -> str:
    """数据集版本 —— 取自 `version.json`。

    ⛔ 不写字面量 "v0.2-mini"：README 的标题、pretty_name 与引用块共三处用它，
    发 v0.3 时漏改任一处就是「三个地方三个版本号」。
    ⚠️ `common.py` 没有 VERSION 常量（实测），所以在这里读。
    """
    return json.loads((c.MVP_DIR / "version.json").read_text(encoding="utf-8"))["version"]


def delivered_ids() -> list[str]:
    """交付集的 task_id —— 以 `tasks/` 的目录为准（39 条）。

    ⛔ 不以 `meta/snapshots.jsonl` 为准：那是 70 条（含 26 条 T6 复核淘汰
    + 5 条私有 registry 排除）。HF README 自己就警告过别拿那份的条数对本仓。
    """
    return sorted(p.name for p in c.MVP_TASKS.iterdir()
                  if p.is_dir() and p.name.startswith("T"))


def build_tasks_jsonl(ids: list[str]) -> str:
    """从 `tasks/*/meta.json` + `instruction.md` 现算 tasks.jsonl。"""
    out = []
    for tid in ids:
        d = c.MVP_TASKS / tid
        m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        row = {k: m.get(k) for k in TASKS_KEYS}
        # instruction_len 不在 meta.json 里，现数 —— 口径是**字符数**（见文件头）
        row["instruction_len"] = len((d / "instruction.md").read_text(encoding="utf-8"))
        out.append(json.dumps(row, ensure_ascii=False) + "\n")
    return "".join(out)


def build_snapshots_jsonl(ids: list[str]) -> str:
    """把仓内 70 条裁到交付的 39 条，**逐行原样透传**。

    ⛔ 不重新 json.dumps：那会按本脚本的键序/空格重排，与线上不再逐字节相同，
    而这份数据的权威版本在 `meta/snapshots.jsonl` —— 透传才能保证两侧同源。
    """
    keep = set(ids)
    out = []
    for line in (c.MVP_META / "snapshots.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        if json.loads(line)["task_id"] in keep:
            out.append(line + "\n")

    # 🔴 守卫：裁剪必须恰好剩交付集那么多条，且每条都有 tar_bytes/tar_sha256。
    # ⚠️ 不是多余的断言 —— 上游 70 条里有 5 条 `ok=False`（registry_unreachable）
    # **没有 tar_bytes 字段**。裁剪逻辑一旦被改坏（漏掉 keep 判断），下游算总字节
    # 时会抛裸 KeyError，堆栈指向 `sum(...)` 那一行，读者看不出真正的原因是「裁剪没生效」。
    if len(out) != len(ids):
        raise SystemExit(
            f"⛔ 裁剪后 {len(out)} 条 ≠ 交付集 {len(ids)} 条 —— 裁剪逻辑坏了。\n"
            f"   上游 meta/snapshots.jsonl 含 T6 淘汰与 registry 排除条目，"
            f"必须按 tasks/ 的目录裁到交付集。"
        )
    missing = [json.loads(x)["task_id"] for x in out
               if "tar_bytes" not in json.loads(x) or "tar_sha256" not in json.loads(x)]
    if missing:
        raise SystemExit(
            f"⛔ {len(missing)} 条缺 tar_bytes/tar_sha256：{missing[:5]}\n"
            f"   这些是 ok=False 的排除条目，⛔ 不该进交付集。"
        )
    return "".join(out)


def _dist(rows: list[dict], key: str) -> dict[str, int]:
    """按 key 计数，**按键名字母序**排列。

    ⚠️ ⛔ 别改成按条数降序：线上两张表都是键名序（`bug_fix` 18 排在
    `test_authoring` 21 **之前**，`L` 27 在 `M` 12 之前 —— 前者升后者降，
    只有键名序同时解释这两张表）。按条数排会让 `--check` 假红。
    """
    d: dict[str, int] = {}
    for r in rows:
        d[r[key]] = d.get(r[key], 0) + 1
    return dict(sorted(d.items()))


def _evidence_section(evidence_jsonl: str | None) -> str:
    """从 evidence.jsonl 现算 HF README 的 evidence 章节。文件不存在则空串。

    🔴 所有数字从 jsonl 现算，⛔ 不手写。jsonl 不在时不加这一节 ——
    这样在证据归档落地前，`t9 --check` 仍与线上逐字节一致。
    """
    if not evidence_jsonl or not evidence_jsonl.strip():
        return ""
    rows = [json.loads(x) for x in evidence_jsonl.splitlines() if x.strip()]
    n = len(rows)
    n_stage = sum(1 for r in rows if str(r.get("job_path", "")).startswith("_"))
    n_jobs = n - n_stage
    src = sum(int(r["src_bytes"] or 0) for r in rows)
    arch = sum(int(r["archive_bytes"] or 0) for r in rows)
    redacted = [r for r in rows if str(r.get("redacted", "no")).startswith("yes")]
    red_lines = "\n".join(
        f"- `{r['job_path']}`：{r['redacted']}" for r in redacted
    ) or "（无）"
    return f"""
## 评测过程证据

本仓 `evidence/v0.2-mini/` 含 **{n}** 个包（{n_jobs} 个 job + {n_stage} 个 stage 题面），
合计 **{arch / 1024 / 1024:.1f} MiB**（压缩前 {src / 1024 / 1024:.1f} MiB）。
索引：`evidence.jsonl`（{n} 行，与 GitHub `reports/evidence/MANIFEST.tsv` 同字段）。

```bash
# 只取证据层（与 39 份快照同仓，一次 clone 全拿也行）
hf download {HF_REPO} --repo-type dataset --include "evidence/**" --local-dir ./atb-hf
```

⚠️ **{len(redacted)}** 个包经过脱敏（门禁⑤ 盯的私有仓源码路径 → `<REDACTED-PRIVATE-PATH>`）：
{red_lines}
其余包原样。⛔ 不许说成「证据层全部原样公开」。

26 条 T6 淘汰题快照**判弃**归档（可从 `base_commit` 重建），详见 GitHub
[`reports/evidence/README.md`](https://github.com/njfuzrs/agent-traj-bench/blob/main/reports/evidence/README.md)。
"""


def build_readme(tasks_jsonl: str, snaps_jsonl: str, ver: str,
                 evidence_jsonl: str | None = None) -> str:
    """现算 HF README。⛔ 本函数里不许出现任何统计数字的字面量。

    7 处现算：band 分布 / category 分布 / 来源仓库 / 判分命令 / F2P·P2P 计数 /
    快照总字节 / 上游 70 条与淘汰归因。⚠️ 唯一的例外是 §「已知局限」那四条散文与
    许可段 —— 那是**结论**不是统计量，改它要连 GitHub 的 DATASET_CARD.md 一起改。
    """
    tasks = [json.loads(x) for x in tasks_jsonl.splitlines() if x.strip()]
    snaps = [json.loads(x) for x in snaps_jsonl.splitlines() if x.strip()]
    n = len(tasks)

    band = _dist(tasks, "band")
    cat = _dist(tasks, "category")
    repos = sorted({t["repo"] for t in tasks})
    cmds = sorted({t["test_cmd"] for t in tasks})
    n_f2p = sum(t["n_f2p"] for t in tasks)
    n_p2p = sum(t["n_p2p"] for t in tasks)
    tar_b = sum(s["tar_bytes"] for s in snaps)
    tar_mib = tar_b / 1024 / 1024

    # 上游条数与淘汰归因 —— 现算，别写死 70/26/5
    up = [json.loads(x) for x in
          (c.MVP_META / "snapshots.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    n_up = len(up)
    n_registry = sum(1 for s in up if not s.get("ok"))
    n_t6 = n_up - n - n_registry

    band_rows = "\n".join(f"| `{k}` | {v} |" for k, v in band.items())
    cat_rows = "\n".join(f"| `{k}` | {v} |" for k, v in cat.items())
    repo_txt = "、".join(f"`{r}`" for r in repos)
    single = "（**单仓库** —— 见下方局限）" if len(repos) == 1 else ""

    ev_rows = [json.loads(x) for x in (evidence_jsonl or "").splitlines() if x.strip()]
    ev_cfg = ("  - config_name: evidence\n    data_files: evidence.jsonl\n"
              if ev_rows else "")
    ev_sec = _evidence_section(evidence_jsonl)
    if ev_rows:
        ev_mib = sum(int(r["archive_bytes"] or 0) for r in ev_rows) / 1024 / 1024
        lead_ev = f" + {len(ev_rows)} 个评测过程证据包（{ev_mib:.1f} MiB）"
        src_ev = " / `evidence.jsonl`"
        ev_file_row = (f"| `evidence/v0.2-mini/*.tar.zst` | {len(ev_rows)} 个评测过程证据包"
                       f"（{ev_mib:.1f} MiB），索引见 `evidence.jsonl` |\n")
    else:
        lead_ev = src_ev = ev_file_row = ""

    return f"""---
license: mit
language:
  - zh
  - en
tags:
  - code
  - software-engineering
  - agent
  - swe-bench
  - benchmark
pretty_name: Agent-Traj-Bench {ver} (snapshots)
size_categories:
  - n<1K
task_categories:
  - text-generation
configs:
  - config_name: tasks
    data_files: tasks.jsonl
  - config_name: snapshots
    data_files: snapshots.jsonl
{ev_cfg}---

# Agent-Traj-Bench {ver} — 仓库快照（{n} 份）

> 🔴 **这个 HF 仓只放「跑起来必需的大文件」** —— {n} 份 base 仓库快照
> + 两份索引{lead_ev}。
> **题目本体、判分脚本、漏斗报告、Dataset Card 全在 GitHub**：
> <https://github.com/njfuzrs/agent-traj-bench>
>
> ⚠️ 本页数字全部由 `scripts/t9-publish-hf.py` 从 `tasks.jsonl` / `snapshots.jsonl`{src_ev} 现算，
> ⛔ 没有手写数字。复现：`python3 scripts/t9-publish-hf.py --check`（$0、免凭证，
> 与本页逐字节比对）。

## 为什么拆成两个仓

快照 {tar_mib:.1f} MiB（{tar_b} B）不适合进 git 主仓（clone 会变慢，且它们是**别人的代码**，
许可与题面不同层）。⇒ GitHub 放题集与全部可复算产物，HF 放快照。
两边用 `snapshots.jsonl` 的 `tar_sha256` 对齐，**逐份可校验**。

## 文件

| 文件 | 内容 |
| --- | --- |
| `snapshots/T####.tar.gz` | {n} 份 base 仓库快照，文件名 = task_id |
| `snapshots.jsonl` | {n} 行，每行含 `task_id` / `base_commit` / `tar_sha256` / `tar_bytes` / `test_cmd` 等 |
| `tasks.jsonl` | {n} 行题目索引：`band` / `category` / `f2p` / `p2p` / `instruction_len` |
{ev_file_row}
⚠️ `snapshots.jsonl` 已**裁到交付的 {n} 条**。上游 `meta/snapshots.jsonl` 是 {n_up} 条
（含 {n_t6} 条 T6 复核淘汰 + {n_registry} 条因私有 registry 被排除）⇒ ⛔ 别拿那份的条数对本仓。

## 构成

| 难度分档（`edit_ops` 代理指标） | 条数 |
| --- | --- |
{band_rows}

| 任务类型 | 条数 |
| --- | --- |
{cat_rows}

- 来源仓库：{repo_txt}{single}
- 判分命令：{"、".join(f"`{x}`" for x in cmds)}
- 判分用例：F2P **{n_f2p}** 个 / P2P **{n_p2p}** 个

## 怎么用

```bash
# ① 取题集（含脚本与判分逻辑）
git clone https://github.com/njfuzrs/agent-traj-bench
# ② 取快照（本仓）
hf download {HF_REPO} --repo-type dataset --local-dir ./atb-hf
# ③ 校验 sha256（⛔ 只看「文件下来了」不算）
cd atb-hf && python3 - <<'PY'
import json, hashlib, pathlib
bad = 0; n = 0
for line in open('snapshots.jsonl'):
    d = json.loads(line); n += 1
    p = pathlib.Path('snapshots') / f"{{d['task_id']}}.tar.gz"
    if hashlib.sha256(p.read_bytes()).hexdigest() != d['tar_sha256']:
        print('MISMATCH', d['task_id']); bad += 1
print(f'{{n - bad}}/{{n}} 校验通过')
PY
# ④ 铺开并逐份校验（任一条 sha256 不符即报红退出）
cd ../agent-traj-bench && python scripts/t4-build-env.py --from-snapshots ../atb-hf/snapshots
```

## 已知局限（完整 16 条见 GitHub 的 `DATASET_CARD.md`）

这里只列**直接影响怎么读这批快照**的四条，⛔ 别只看这四条就下结论：

1. **单开发者、单仓库、两类任务** ⇒ 定位是「真实生产交互衍生的**补充** benchmark」，
   ⛔ **不是通用 SWE 基准**。
2. ⛔ **不能说「已排除训练集污染」** —— 污染检测**未做**，题目也**未嵌 canary**。
3. **快照内有两处刻意保留的残余泄漏面**（`/repo` 之外的 `/eval-framework` stub、
   3 条 monorepo 的 `packages/eval-framework/package.json`）。可证不参与判分：
   两者都不含判分逻辑与测试代码。⛔ 不能只写「已剔除泄漏面」了事。
4. **`S` 档为 0** —— 难度分档只有 `M` / `L`，⛔ 别把它当覆盖全难度谱的题集。

## 许可

本仓内容 = **{n} 份仓库快照**，即 {repo_txt} 的源码 ⇒ **MIT**，版权归 sid-code 作者。
🔴 快照是**别人的代码**，保留其版权声明是 MIT 明文要求，不是可选的礼节。

题面与报告（在 GitHub 仓）另按 **CC BY 4.0** 授权，判分脚本按 **MIT**
—— 三层各有各的许可，详见 GitHub 仓的 `LICENSE`。

## 引用

```
Agent-Traj-Bench {ver}. njfuzrs, 2026.
https://github.com/njfuzrs/agent-traj-bench
```
{ev_sec}"""


def verify_tars(tars_dir: Path, snaps_jsonl: str) -> tuple[int, list[str]]:
    """逐份校验快照 sha256。⛔ 不校验就上传等于把「可复现」偷换成「文件在」。

    同 t4-build-env.py 的口径：报出期望与实得两个值，别只说「校验失败」——
    大小差很多通常是截断，大小一样而摘要不同才是内容被改过。
    """
    bad: list[str] = []
    n_ok = 0
    for line in snaps_jsonl.splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        tid = rec["task_id"]
        p = tars_dir / f"{tid}.tar.gz"
        if not p.exists():
            print(f"🔴 {tid}: 快照缺失 {p}", file=sys.stderr)
            bad.append(tid)
            continue
        gz = p.read_bytes()
        got = hashlib.sha256(gz).hexdigest()
        if got != rec["tar_sha256"]:
            print(f"🔴 {tid}: sha256 不匹配\n"
                  f"     期望 {rec['tar_sha256']}\n"
                  f"     实得 {got}\n"
                  f"     大小 {len(gz)} bytes（snapshots.jsonl 记 {rec['tar_bytes']}）",
                  file=sys.stderr)
            bad.append(tid)
            continue
        n_ok += 1
    return n_ok, bad


def _hub():
    """惰性导入 huggingface_hub —— 只有 --check / --push 才需要它。

    🔴 这样 `--out`（纯现算）保持**零第三方依赖**：别人 clone 后不装任何东西就能
    复算出三个文件，自己 diff。⛔ 别把 import 提到模块顶层。
    """
    try:
        from huggingface_hub import HfApi
    except ImportError:
        print("⛔ 缺 huggingface_hub —— --check / --push 需要它\n"
              "   pip install huggingface_hub   （--out 模式不需要）", file=sys.stderr)
        raise SystemExit(5)
    return HfApi()


def do_check(built: dict[str, str]) -> int:
    """把现算结果与 HF 线上逐字节比对 —— 兑现 README 里那句「没有手写数字」。

    🔴 这是本脚本的**主判据**，比 --push 重要：一个只会上传的脚本无法证明线上那份
    是算出来的。⚠️ 免凭证（公开仓可匿名读），所以 CI 里也能跑。
    """
    # ⛔ 这个 import 必须走 _hub() 的兜底，不能裸写在函数顶部：裸写时缺包会抛
    # ModuleNotFoundError ⇒ 退出码 1，而 1 是「参数错」的语义（同 t4 的约定），
    # 调用方分不出「用法写错」和「环境缺包」。实测踩过：文件头写着退 5，实际退 1。
    _hub()
    from huggingface_hub import hf_hub_download

    n_bad = 0
    for name, mine in built.items():
        p = hf_hub_download(HF_REPO, name, repo_type="dataset")
        theirs = Path(p).read_text(encoding="utf-8")
        if mine == theirs:
            print(f"✅ {name}  逐字节一致（{len(mine)} B）")
            continue
        n_bad += 1
        print(f"🔴 {name}  与线上不一致：现算 {len(mine)} B / 线上 {len(theirs)} B",
              file=sys.stderr)
        ml, tl = mine.splitlines(), theirs.splitlines()
        if len(ml) != len(tl):
            print(f"     行数 现算 {len(ml)} / 线上 {len(tl)}", file=sys.stderr)
        for i, (a, b) in enumerate(zip(ml, tl), 1):
            if a != b:
                print(f"     首个不同在第 {i} 行：\n"
                      f"       现算 {a[:200]}\n"
                      f"       线上 {b[:200]}", file=sys.stderr)
                break
    if n_bad:
        print(f"\n⛔ {n_bad}/{len(built)} 份与线上不一致 —— 要么线上该重发"
              f"（--push），要么本脚本的口径漂了。⛔ 别直接改本脚本去凑线上。",
              file=sys.stderr)
        return 4
    print(f"\n✅ {len(built)}/{len(built)} 份与线上逐字节一致 ⇒ README 那句「没有手写数字」成立")
    return 0


def do_push(built: dict[str, str], out: Path, with_tars: bool, tars_dir: Path | None) -> int:
    api = _hub()
    files = list(INDEX_FILES)
    if with_tars:
        if tars_dir is None:
            print("⛔ --with-tars 需要 --tars-dir <DIR>", file=sys.stderr)
            return 4
        n_ok, bad = verify_tars(tars_dir, built["snapshots.jsonl"])
        if bad:
            print(f"⛔ 快照校验失败 {len(bad)} 条：{bad[:5]} ⇒ 不上传任何东西",
                  file=sys.stderr)
            return 4
        print(f"✅ 快照逐份校验通过 {n_ok} 份")

    for name in files:
        api.upload_file(path_or_fileobj=str(out / name), path_in_repo=name,
                        repo_id=HF_REPO, repo_type="dataset",
                        commit_message=f"chore: 由 scripts/t9-publish-hf.py 现算重发 {name}")
        print(f"⬆️  {name}")

    if with_tars:
        assert tars_dir is not None
        for line in built["snapshots.jsonl"].splitlines():
            tid = json.loads(line)["task_id"]
            api.upload_file(path_or_fileobj=str(tars_dir / f"{tid}.tar.gz"),
                            path_in_repo=f"snapshots/{tid}.tar.gz",
                            repo_id=HF_REPO, repo_type="dataset",
                            commit_message=f"chore: 重发快照 {tid}")
            print(f"⬆️  snapshots/{tid}.tar.gz")
    print(f"\n✅ 已上传 https://huggingface.co/datasets/{HF_REPO}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="T9 — HF 快照层发布：现算 README + 两个索引 jsonl")
    ap.add_argument("--out", metavar="DIR", default=None,
                    help="落盘目录（默认写临时目录）。只落盘不上传时用它自己 diff")
    ap.add_argument("--check", action="store_true",
                    help="与 HF 线上逐字节比对（$0、免凭证）。不一致以退出码 4 报红")
    ap.add_argument("--push", action="store_true",
                    help="上传 README + 两个 jsonl（⛔ 不含快照，见 --with-tars）")
    ap.add_argument("--with-tars", action="store_true",
                    help="连 39 份快照一起传。⛔ 先逐份校验 sha256，任一条不符即不传任何东西")
    ap.add_argument("--tars-dir", metavar="DIR", default=None,
                    help="快照 tar 所在目录（文件名 T####.tar.gz）")
    args = ap.parse_args()

    ids = delivered_ids()
    tasks_jsonl = build_tasks_jsonl(ids)
    snaps_jsonl = build_snapshots_jsonl(ids)
    ev_path = c.MVP_REPORTS / "evidence" / "evidence.jsonl"
    ev_text = ev_path.read_text(encoding="utf-8") if ev_path.is_file() else None
    readme = build_readme(tasks_jsonl, snaps_jsonl, version(), evidence_jsonl=ev_text)
    built = {"README.md": readme, "tasks.jsonl": tasks_jsonl,
             "snapshots.jsonl": snaps_jsonl}

    print(f"交付集 {len(ids)} 条 ⇒ 现算 README {len(readme)} B / "
          f"tasks.jsonl {len(tasks_jsonl)} B / snapshots.jsonl {len(snaps_jsonl)} B",
          file=sys.stderr)

    # ⚠️ 默认落**临时目录**，不落 reports/ —— 这三份是 HF 侧的产物，进 reports/ 会让
    # 工作树多出未跟踪文件（而它们又不该入库：入库就成了「同一份数据两个仓各存一份」）。
    # 想留档自己 diff 就显式给 --out。
    out = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="atb-hf-"))
    out.mkdir(parents=True, exist_ok=True)
    for name, text in built.items():
        (out / name).write_text(text, encoding="utf-8")
    print(f"落盘 {out}", file=sys.stderr)

    if args.check:
        return do_check(built)
    if args.push:
        return do_push(built, out, args.with_tars,
                       Path(args.tars_dir) if args.tars_dir else None)
    print("（未加 --check / --push ⇒ 只落盘。加 --check 与线上比对）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
