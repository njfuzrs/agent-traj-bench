#!/usr/bin/env python3
"""污染字段扫描 —— 防上一轮 agent 输出进入题面。

5 个黑名单字段来自 sid-code `scripts/eval/check-real-tasks-pollution.ts`
（B6-10）。它们在 trajectory-platform 上游 task.yaml 里携带「上一轮 agent
的输出」，进了题面等于让被测 agent 看到答案。

本仓没有 yaml case，题面是 `tasks/T####/` 下的 instruction.md / task.toml /
meta.json / tests / solution / Dockerfile。同等扫描 = 对这些文件做这 5 个
字段的子串命中（与原扫描器 `line.includes(kw)` 同口径）。

作用域只扫 `tasks/`：那是被测 agent 面对的题。scripts/ 与 reports/ 里出现
字段名是在讨论这条防线本身，不算污染。

退出码：
  0 扫到文件且 0 命中
  1 有命中
  2 作用域为空 / 目录不存在
    ⛔ 不许当通过 —— sid-code PR3d 删掉 real-tasks 后，原扫描器对空集
    仍返回 0（「no real-tasks yaml to scan, ok」）。那是已知中间态，
    不是「防线在工作」。本脚本把空集收成错误，避免同一形态复发。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

KEYWORDS = (
    "tool_result_content",
    "response_content",
    "patch_content",
    "observation_content",
    "completion_text",
)

SKIP_DIR_NAMES = {".git", "__pycache__", ".pytest_cache", ".ruff_cache"}

REPO = Path(__file__).resolve().parents[1]


def iter_task_files(tasks_dir: Path) -> list[Path]:
    """`tasks/` 下全部普通文件。目录不存在 → 空列表，由 main 收成 exit 2。"""
    if not tasks_dir.is_dir():
        return []
    out: list[Path] = []
    for p in tasks_dir.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in p.parts):
            continue
        out.append(p)
    return sorted(out)


def scan_file(path: Path) -> list[str]:
    """返回 `keyword@line:N` 列表。读字节，按 UTF-8 宽松拆行，避免编码把扫描打哑。"""
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    hits: list[str] = []
    for i, line in enumerate(text.splitlines(), start=1):
        for kw in KEYWORDS:
            if kw in line:
                hits.append(f"{kw}@line:{i}")
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="扫 tasks/ 是否含 5 个污染字段")
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO,
        help="仓库根（测试用）。默认本仓。扫描的是 <root>/tasks/",
    )
    args = parser.parse_args(argv)

    tasks_dir = args.root / "tasks"
    files = iter_task_files(tasks_dir)
    if not files:
        print(
            "::error::tasks/ 下 0 个文件。"
            "空集不许当通过（那是「防线全在、调用全 0」）",
            file=sys.stderr,
        )
        print(f"作用域: {tasks_dir}", file=sys.stderr)
        return 2

    offenders: list[tuple[Path, list[str]]] = []
    for f in files:
        hits = scan_file(f)
        if hits:
            offenders.append((f, hits))

    n_files = len(files)
    if not offenders:
        print(f"[contamination-scan] ✅ scanned {n_files} file(s), 0 hits")
        return 0

    n_hits = sum(len(h) for _, h in offenders)
    print(
        f"[contamination-scan] ❌ {n_hits} hit(s) in {len(offenders)} file(s):",
        file=sys.stderr,
    )
    print(
        "5 个字段是上一轮 agent 输出；进了 tasks/ 等于让被测 agent 看到答案。",
        file=sys.stderr,
    )
    for f, hits in offenders:
        try:
            rel = f.relative_to(args.root)
        except ValueError:
            rel = f
        print(f"  {rel}", file=sys.stderr)
        for h in hits:
            print(f"    - {h}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
