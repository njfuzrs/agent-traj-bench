#!/usr/bin/env python3
"""差集闸 —— 守「以后再跑评测，证据不会再次只剩单点」。

出处：`docs-research/trajectory-platform/20260917-evidence-archive-plan.md` §6。

## 它不守什么

⛔ 不是守**本次**归档（本次由归档方案 §5.4 的九条判据守）。
本脚本守的是：**磁盘上新出现的 job，清单里还没有 sha256**。

## 判据：差集，不是时间戳

    分子：EVIDENCE_RUNS_ROOT 下名字匹配 `20*__*` 的目录（job，⛔ 不是 trial）
    分母：MANIFEST.tsv 里 sha256 非空、且 job_path 末段匹配 `20*__*` 的行
    差集（分子 − 分母）非空 ⇒ 红，并**逐个点名**未归档的 job_path

🔴 为什么不用时间戳闸（「最后归档时间晚于最后跑批时间」）：
只要你在跑批之后归档过**任意一个** job，时间戳就领先了，
「跑了但没归档」这种形态抓不到。差集闸抓得到。同 PR-A §A4。

## ⛔ 不挂 CI

公开仓的 CI runner 上**没有** runs 目录（它们从未入库）⇒ 分子恒为 0、
差集恒为空 ⇒ **闸恒绿**。挂上去等于关掉它。

运行位置是**有 runs 的机器**（跑批那台）：

    EVIDENCE_RUNS_ROOT=<runs 根目录> python3 scripts/check-evidence-due.py
    EVIDENCE_RUNS_ROOT=<runs> MANIFEST=<清单> python3 scripts/check-evidence-due.py

可挂本机 `.git/hooks/pre-push`（⛔ 不入仓 —— hook 不随 clone 走，写进
`reports/evidence/README.md` 让人自己装）。

## 必填环境变量

`EVIDENCE_RUNS_ROOT` **必须显式给，⛔ 不许有默认值**。
若默认成 `reports/`，在公开仓上就是「目录不存在 ⇒ 分子 0 ⇒ 恒绿」。
没给这个变量时脚本 **exit 2**，⛔ 不是「跳过检查」。

退出码：0 差集为空；2 缺变量 / 目录或清单不存在；4 差集非空（点名）。
⛔ 不用 1 —— 那和 argparse 的参数错混了。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402


def is_job_name(name: str) -> bool:
    """归档单元是 job：`20*__*`。⛔ 不是 `T0*`（会漏掉 M# / hash 哨兵）。"""
    return name.startswith("20") and "__" in name


def jobs_on_disk(root: Path) -> set[str]:
    """相对 `root` 的 job_path 集合。"""
    found = [p for p in root.rglob("*")
             if p.is_dir() and is_job_name(p.name)]
    jobs = []
    for p in found:
        if any(q in p.parents for q in found):
            continue
        jobs.append(str(p.relative_to(root)))
    return set(jobs)


def jobs_in_manifest(man: Path) -> set[str]:
    """sha256 非空、且末段是 job 名的行。`_stage-prompts` 不是 job，不进分母。"""
    lines = man.read_text(encoding="utf-8").splitlines()
    if not lines:
        return set()
    cols = lines[0].split("\t")
    try:
        i_path = cols.index("job_path")
        i_sha = cols.index("sha256")
    except ValueError as e:
        print(f"::error::MANIFEST 缺列: {e}", file=sys.stderr)
        raise SystemExit(2)
    out: set[str] = set()
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        path = parts[i_path] if i_path < len(parts) else ""
        sha = parts[i_sha] if i_sha < len(parts) else ""
        if not sha or not path:
            continue
        if is_job_name(Path(path).name):
            out.add(path)
    return out


def main() -> int:
    root_s = os.environ.get("EVIDENCE_RUNS_ROOT")
    if not root_s:
        print("::error::EVIDENCE_RUNS_ROOT 未设置。"
              "必须显式给跑批那台的 runs 根目录，"
              "⛔ 不许默认成 reports/（公开仓上会恒绿）", file=sys.stderr)
        return 2
    root = Path(root_s).expanduser()
    if not root.is_dir():
        print(f"::error::EVIDENCE_RUNS_ROOT 不是目录: {root}", file=sys.stderr)
        return 2

    man_s = os.environ.get("MANIFEST")
    man = Path(man_s).expanduser() if man_s else (c.MVP_REPORTS / "evidence" / "MANIFEST.tsv")
    if not man.is_file():
        print(f"::error::清单不存在: {man}", file=sys.stderr)
        return 2

    disk = jobs_on_disk(root)
    listed = jobs_in_manifest(man)
    missing = sorted(disk - listed)
    extra = sorted(listed - disk)  # 清单有、磁盘无：归档后源被移走是**预期**，只提示
    print(f"磁盘 job {len(disk)} / 清单（sha256 非空）{len(listed)}")
    if extra:
        print(f"（清单有、磁盘无 {len(extra)} 个 —— 源已移走则属预期，不报红）")
    if missing:
        print(f"::error::未归档 {len(missing)} 个 job：")
        for p in missing:
            print(f"    {p}")
        return 4
    print("✅ 差集为空（磁盘上的每个 job 清单里都有 sha256）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
