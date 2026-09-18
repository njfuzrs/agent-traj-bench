#!/usr/bin/env python3
"""T11 — 只用 HF 上的证据包做一次归因分析，验「归档够不够用」。

出处：`docs-research/trajectory-platform/20260917-evidence-archive-plan.md` §5.6
的第二条判据「至少一次归因分析从 HF 取过包并跑通」。那条判据是
`rm -rf _archive/bench-evidence-raw/`（本方案唯一不可逆的一步）的前置。

## 判据形态：复现已发表的数字，⛔ 不是「跑完没报错」

本脚本把公开仓两份报告里**已经写死的数字**当成基准，只用 HF 下回来的字节复算：

| 批次 | 报告 | 已发表 |
|---|---|---|
| `baseline/2026-09-12__23-46-37` | `reports/baseline-v0.2-mini.md` | pass@1 = 0 / 39 |
| `t8-rerun/2026-09-13__19-35-38` | `reports/baseline-v0.2-mini-t8-rerun.md` | 解出 14，scored 37（排除 T0009 / T0022） |

复算不上就是红 —— 那说明归档缺了东西，⛔ 此时不许删原件。

## 🔴 分母纪律：排除表是**已发表的结论**，⛔ 不许现推

报告把 `T0009`（agent 未启动）与 `T0022`（上游链路断连）按 infra 排除出分母。
两者**都写了 `verifier/reward.json`**（reward 0.0）⇒ 光看分数分不出「答错」与「仪器坏了」。
⇒ 本脚本按报告的排除表算分母，另外**逐条验证那两条的 infra 特征在归档证据里找得到**
（这才是「证据够用」的真判据）。

实测两条的特征都在包内：
- `T0022`：`socket connection was closed unexpectedly` 命中 6 个文件
  （`result.json` / `agent/sid-code.jsonl` / `sid-home/debug.log` / 该 session 的
  `warn.log` `events.jsonl` `errors.jsonl`）
- `T0009`：`exception.txt` 结尾是 `ValueError: embedded null byte`，且 `agent/` 下
  **没有** `sid-code.jsonl` ⇒ agent 一个字没跑
  ⚠️ 报告散文写的是 `Argument list too long`（容器内的成因），而**归档证据里的
  特征是 harbor 侧那个 ValueError** —— 实测 `Argument list too long` 在包内命中 0。
  ⛔ 别拿报告的散文当 grep 模式：成因与特征是两件事。

## 用法

    python3 scripts/t11-attribute-from-hf.py            # 从 HF 取包并复算
    python3 scripts/t11-attribute-from-hf.py --keep DIR # 解压产物留在 DIR 便于人看

⚠️ 取数源只有 `hf_hub_download`，⛔ 不读任何本地 `_archive/`：
读了近线副本就等于没验 HF 那份，而 §5.6 要删的恰恰是本地原件。

退出码：0 全部复现；4 有一项对不上；5 缺 huggingface_hub。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HF_REPO = "njfuzrs/agent-traj-bench"
PREFIX = "evidence/v0.2-mini"

#: 已发表的基准（取自公开仓两份报告的首表）。⛔ 不是本脚本算出来的。
EXPECTED = {
    "baseline/2026-09-12__23-46-37": dict(solved=0, scored=39, excluded=()),
    "t8-rerun/2026-09-13__19-35-38": dict(solved=14, scored=37,
                                          excluded=("T0009", "T0022")),
}

#: infra 故障在**归档证据**里的特征。⛔ 不是报告散文里的成因描述。
INFRA_SIGNS = {
    "T0022": ("socket connection was closed unexpectedly", 1),
    "T0009": ("ValueError: embedded null byte", 1),
}


def die(msg: str, code: int) -> int:
    print(f"::error::{msg}", file=sys.stderr)
    return code


def fetch_unpack(job: str, work: Path) -> Path:
    """只从 HF 取，解到 work 下。⛔ 不碰本地 _archive。"""
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("⛔ 缺 huggingface_hub", file=sys.stderr)
        raise SystemExit(5)
    blob = hf_hub_download(HF_REPO, f"{PREFIX}/{job}.tar.zst", repo_type="dataset")
    # HF cache 里是 symlink，zstd 默认不跟随 ⇒ 取 realpath（实测踩过）
    real = Path(os.path.realpath(blob))
    dest = work / job.replace("/", "__")
    if (dest / job).exists():
        return dest / job
    dest.mkdir(parents=True, exist_ok=True)
    raw = subprocess.run(["zstd", "-d", "-c", str(real)],
                         check=True, stdout=subprocess.PIPE).stdout
    subprocess.run(["tar", "-xf", "-", "-C", str(dest)], input=raw, check=True)
    return dest / job


def best_reward(job_dir: Path) -> dict[str, float | None]:
    """task_id → 最好的 reward（同题多 trial 取 max）。取 verifier/reward.json。"""
    out: dict[str, float | None] = {}
    for t in sorted(job_dir.iterdir()):
        if not t.is_dir() or t.name == "_digests":
            continue
        tid = t.name.split("__")[0]
        rj = t / "verifier" / "reward.json"
        r: float | None = None
        if rj.is_file():
            try:
                r = float(json.loads(rj.read_text(encoding="utf-8"))["reward"])
            except (ValueError, KeyError, json.JSONDecodeError):
                r = None
        prev = out.get(tid)
        if prev is None or (r is not None and (prev is None or r > prev)):
            out[tid] = r
    return out


def grep_count(root: Path, needle: str) -> int:
    """含该串的文件数。Python 走目录树，⛔ 不调 grep（ugrep 会读 .gitignore 漏扫）。"""
    pat = needle.encode("utf-8")
    n = 0
    for p in root.rglob("*"):
        if p.is_symlink() or not p.is_file():
            continue
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        if pat in raw:
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="T11 — 从 HF 取证据包做归因，验归档够用")
    ap.add_argument("--keep", type=Path, default=None,
                    help="解压产物保留目录（默认用临时目录，跑完即删）")
    args = ap.parse_args()

    work = args.keep.expanduser() if args.keep else Path(tempfile.mkdtemp(prefix="atb-attr-"))
    work.mkdir(parents=True, exist_ok=True)
    print(f"工作目录 {work}（取数源只有 HF，⛔ 不读本地 _archive）\n")

    fail = 0
    for job, exp in EXPECTED.items():
        print(f"↓ {job}", flush=True)
        d = fetch_unpack(job, work)
        lock = json.loads((d / "lock.json").read_text(encoding="utf-8"))
        rewards = best_reward(d)
        excluded = set(exp["excluded"])
        scored = {k: v for k, v in rewards.items() if k not in excluded}
        solved = [k for k, v in scored.items() if v is not None and v >= 1.0]
        n_conc = lock.get("n_concurrent_trials")
        pass1 = len(solved) / len(scored) * 100 if scored else 0.0
        print(f"  题目 {len(rewards)} / scored {len(scored)} / 解出 {len(solved)}"
              f" ⇒ pass@1 {pass1:.1f}%   (n_concurrent_trials={n_conc})")

        if len(solved) != exp["solved"]:
            print(f"::error::{job} 解出 {len(solved)}，报告是 {exp['solved']}", file=sys.stderr)
            fail += 1
        if len(scored) != exp["scored"]:
            print(f"::error::{job} scored {len(scored)}，报告是 {exp['scored']}", file=sys.stderr)
            fail += 1
        if len(solved) == exp["solved"] and len(scored) == exp["scored"]:
            print(f"  ✅ 与报告一致（解出 {exp['solved']} / scored {exp['scored']}）")

        # infra 排除项：特征必须在归档证据里找得到，否则「证据不够用」
        for tid in sorted(excluded):
            tdirs = [x for x in d.iterdir() if x.is_dir() and x.name.startswith(tid + "__")]
            if not tdirs:
                print(f"::error::{job} 缺 {tid} 的 trial 目录", file=sys.stderr)
                fail += 1
                continue
            needle, least = INFRA_SIGNS[tid]
            n = grep_count(tdirs[0], needle)
            ok = n >= least
            print(f"  {'✅' if ok else '❌'} {tid} infra 特征 {needle!r} 命中 {n} 个文件")
            if not ok:
                print(f"::error::{job} {tid} 的 infra 特征在归档证据里找不到 ⇒ 归档不够用",
                      file=sys.stderr)
                fail += 1
            if tid == "T0009":
                has = (tdirs[0] / "agent" / "sid-code.jsonl").exists()
                print(f"  {'✅' if not has else '❌'} T0009 agent/sid-code.jsonl 不存在"
                      f"（报告：agent 一个字没跑）")
                if has:
                    fail += 1
        print()

    print("=== 必控变量 ===")
    print("  baseline n_conc=1 / t8-rerun n_conc=6 ⇒ ⛔ 不许把并发效应算进模型差异")
    print("  （这正是 MANIFEST.tsv 存 n_concurrent_trials 这一列的理由）\n")

    if fail:
        return die(f"{fail} 项对不上 ⇒ ⛔ 不许删 _archive/bench-evidence-raw/", 4)
    print("✅ 两批 pass@1 与 infra 排除项全部从 HF 的证据包复现"
          " ⇒ §5.6 第二条判据成立")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
