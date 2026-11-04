#!/usr/bin/env python3
"""T06：把 v0.2.1 计分集导出成 harbor 可直接跑的发布目录。

## 为什么要导出，而不是让人直接 `harbor run -p tasks`

harbor 0.22 的 `TaskPaths.instruction_path` 写死读 `instruction.md`，不可配置。
而按 T00 裁决，`tasks/*/instruction.md` 保留原句（provenance，T3「题面不加工」纪律），
评测题面在 `instruction.eval.md`。⛔ 不在 `tasks/` 里互换两份题面：那会让 provenance
与评测题面换名字、37.8% 那批的复现链断掉。

所以发布目录是**派生物**：

    dist/v0.2.1/tasks/T####/
      instruction.md        ← tasks/T####/instruction.eval.md（评测题面）
      task.toml / solution/ / tests/ / environment/Dockerfile   ← 原样复制
      environment/repo-snapshot.tar.gz   ← 不入库；--snapshots 指定时从 HF 快照目录复制并校验 sha256

只导出 `meta/scoring-set.json` 的 `scored` 组（32 题）。

## taskset_digest

对**发布目录**里每个文件（不含快照 tar，快照用 `meta/snapshots.jsonl` 的 `tar_sha256` 代入）
按相对路径排序后做 sha256：`sha256(path \\0 sha256(content) \\n ...)`。
⇒ 题面、判分脚本、计分集、快照任一变化 digest 都会变；目录位置、mtime 不影响。

用法：
    python3 scripts/export-release.py                         # 只导出题目定义（无快照）
    python3 scripts/export-release.py --snapshots DIR         # 同时铺快照（DIR = HF 仓的 snapshots/）
    python3 scripts/export-release.py --digest-only           # 只打印 digest，不写盘
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

VERSION = "v0.2.1"
DIST = c.MVP_DIR / "dist" / VERSION
SNAP_NAME = "repo-snapshot.tar.gz"
#: 发布目录里不出现的文件：评测题面已经改名成 instruction.md；meta.json 留在 tasks/ 作 provenance
SKIP = {"instruction.eval.md"}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def scored_tasks() -> list[str]:
    ss = json.loads((c.MVP_META / "scoring-set.json").read_text(encoding="utf-8"))
    return list(ss["groups"]["scored"])


def snapshot_shas() -> dict[str, str]:
    out = {}
    for line in (c.MVP_META / "snapshots.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("ok"):
                out[r["task_id"]] = r["tar_sha256"]
    return out


def plan(tasks: list[str]) -> dict[str, bytes | tuple[str, str]]:
    """发布目录的完整清单：{相对路径: 内容 | ("snapshot", sha256)}。"""
    snaps = snapshot_shas()
    files: dict[str, bytes | tuple[str, str]] = {}
    for t in tasks:
        src = c.MVP_TASKS / t
        ev = src / "instruction.eval.md"
        if not ev.exists():
            raise SystemExit(f"⛔ {t} 没有 instruction.eval.md —— 先跑 scripts/build-eval-instruction.py")
        files[f"tasks/{t}/instruction.md"] = ev.read_bytes()
        for p in sorted(src.rglob("*")):
            rel = p.relative_to(src)
            if not p.is_file() or rel.name in SKIP or rel.name == "instruction.md" \
                    or rel.name == "meta.json" or rel.name == SNAP_NAME or "__pycache__" in rel.parts:
                continue
            files[f"tasks/{t}/{rel.as_posix()}"] = p.read_bytes()
        if t not in snaps:
            raise SystemExit(f"⛔ {t} 在 meta/snapshots.jsonl 里没有 ok 的快照记录")
        files[f"tasks/{t}/environment/{SNAP_NAME}"] = ("snapshot", snaps[t])
    return files


def digest(files: dict[str, bytes | tuple[str, str]]) -> str:
    h = hashlib.sha256()
    for rel in sorted(files):
        v = files[rel]
        h.update(rel.encode() + b"\0" + (v[1] if isinstance(v, tuple) else _sha(v)).encode() + b"\n")
    return h.hexdigest()


def write(files: dict, snapshots: Path | None) -> int:
    if DIST.exists():
        shutil.rmtree(DIST)
    n_snap = 0
    for rel, v in sorted(files.items()):
        dst = DIST / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(v, tuple):
            if snapshots is None:
                continue
            task = rel.split("/")[1]
            src = snapshots / task / SNAP_NAME
            if not src.exists():
                src = snapshots / f"{task}.tar.gz"
            if not src.exists():
                raise SystemExit(f"⛔ 快照目录里找不到 {task} 的快照：{snapshots}")
            if _sha(src.read_bytes()) != v[1]:
                raise SystemExit(f"⛔ {task} 快照 sha256 与 meta/snapshots.jsonl 不符")
            shutil.copyfile(src, dst)
            n_snap += 1
        else:
            dst.write_bytes(v)
            if rel.endswith(".sh"):
                dst.chmod(0o755)
    return n_snap


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=f"导出 {VERSION} 发布目录")
    ap.add_argument("--snapshots", type=Path, help="HF 仓的 snapshots/ 目录；不给就不铺快照")
    ap.add_argument("--digest-only", action="store_true")
    args = ap.parse_args(argv)
    tasks = scored_tasks()
    files = plan(tasks)
    d = digest(files)
    if args.digest_only:
        print(d)
        return 0
    n_snap = write(files, args.snapshots)
    (DIST / "taskset_digest.txt").write_text(d + "\n", encoding="utf-8")
    print(f"导出 {len(tasks)} 题到 {DIST}（快照 {n_snap}/{len(tasks)}）")
    print(f"taskset_digest = {d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
