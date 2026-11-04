#!/usr/bin/env python3
"""生成评测题面 `tasks/*/instruction.eval.md`（T04，按 T00 裁决①）。

## 题面 = 原句 + 内联文档（剥掉围栏代码块）+ F2P 路径清单 + 环境事实

与 `t8-rerun.py:build_instruction`（37.8% 那批）的差别只有两处，都是为了去掉泄漏：

  1. **内联文档里的 ``` 围栏代码块整块删掉**，原位留一行占位。
     依据（2026-11-04 实测）：t8 题面泄漏的 42 行 gold patch 里 41 行在围栏代码块内 ——
     方案文档的体裁是「问题分析 + 要写的代码」，泄漏源就是后者。
     ⛔ 不按「与 gold patch 重合」去剥：那是拿答案筛题面，尺子和被测对象同源。
  2. **删掉 F2P 段那句「文件名指示了实现应落在哪个模块」**：题面之外新加的解题引导。

另做一处与泄漏无关的对齐：内联文档里的本机登录名按 `instruction.md` 同一口径脱敏成
`/Users/<USER>`（复用 `pipeline/s1_s3/s2_rules.py:redact_home_paths`，⛔ 不另写一份正则）。

`instruction.md` 不动（原句 + 环境事实，provenance；T3「题面不加工」纪律）。
产物是否干净由 `check-prompt-leak.py` 判，本脚本不自证。

用法：`python3 scripts/build-eval-instruction.py [--check]`
  --check：只比对、不写；有任何一份与现拼结果不一致即退出 1（防手改 / 漂移）。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

FIX = c.MVP_REPORTS / "t8-fix"
OUT_NAME = "instruction.eval.md"
#: 占位行。⚠️ 不含任何原文，只告诉 agent「这里原来有代码块」，避免它把断裂的上下文误读成文档残缺。
FENCE_PLACEHOLDER = "（此处原有一段代码块，评测题面已移除。）"


def _visible_ctrl():
    """复用 t8 的控制字符转义（同一份文档、同一种传输约束，⛔ 不各写一份）。"""
    spec = importlib.util.spec_from_file_location(
        "_t8_rerun", Path(__file__).resolve().parent / "t8-rerun.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._visible_ctrl


def _redactor():
    """加载 pipeline 层的 `redact_home_paths`。⚠️ spec 加载：那层也有一个 common.py，裸 import 会撞。"""
    spec = importlib.util.spec_from_file_location(
        "_s2_rules", c.REPO_ROOT / "pipeline" / "s1_s3" / "s2_rules.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return lambda text: mod.redact_home_paths(text)[0]


def strip_fenced_blocks(text: str) -> str:
    """删掉 ``` 围栏代码块（含围栏行），每块原位留一行占位。

    未闭合的围栏：从它开始到文末都按代码块处理 —— 宁可多删，不漏删。
    """
    out: list[str] = []
    in_block = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            if not in_block:
                out.append(FENCE_PLACEHOLDER)
            in_block = not in_block
            continue
        if not in_block:
            out.append(line)
    return "\n".join(out)


def build(task: str, idx: dict, visible, redact) -> str:
    src = (c.MVP_TASKS / task / "instruction.md").read_text(encoding="utf-8")
    body, _, envfacts = src.partition("\n---\n")
    parts = [body.strip()]

    blocks = []
    for e in idx.get(task, {}).get("docs", []):
        if e.get("channel") not in ("lake", "mirror"):
            continue
        txt = (FIX / "docs" / e["file"]).read_text(encoding="utf-8", errors="replace")
        txt = redact(visible(strip_fenced_blocks(txt)))
        # 剥完后正文不含 ``` ⇒ 外层用围栏包住是安全的（不会被内文提前闭合）
        blocks.append(
            f"### `{e['ref']}`\n\n"
            "> 以下为该文件正文（评测环境无法访问你本机路径，故内联附上；文中代码块已移除）。\n\n"
            f"```\n{txt}\n```\n"
        )
    if blocks:
        parts.append("---\n\n## 引用文档原文\n\n" + "\n".join(blocks))

    f2p = json.loads((c.MVP_TASKS / task / "tests/f2p.json").read_text(encoding="utf-8"))
    parts.append(
        "---\n\n## 验收标准\n\n"
        "你的修复必须让以下测试文件**全部通过**（`bun test <路径>`）：\n\n"
        + "\n".join(f"- `{p}`" for p in f2p)
        + "\n\n> 这些测试文件当前**不在**工作区，验收时才会放入。\n"
          "> ⚠️ 不要自己创建这些测试文件 —— 验收时会被覆盖。\n"
    )
    return "\n\n".join(parts) + "\n\n---\n" + envfacts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成 tasks/*/instruction.eval.md")
    ap.add_argument("--check", action="store_true", help="只比对不写，不一致退出 1")
    args = ap.parse_args(argv)

    idx = json.loads((FIX / "docs-index.json").read_text(encoding="utf-8"))
    visible = _visible_ctrl()
    redact = _redactor()
    tasks = sorted(p.name for p in c.MVP_TASKS.iterdir() if p.is_dir())
    if not tasks:
        print(f"::error::{c.MVP_TASKS} 下没有题", file=sys.stderr)
        return 2

    drift = []
    for t in tasks:
        want = build(t, idx, visible, redact)
        dst = c.MVP_TASKS / t / OUT_NAME
        if args.check:
            if not dst.exists() or dst.read_text(encoding="utf-8") != want:
                drift.append(t)
        else:
            dst.write_text(want, encoding="utf-8")
    if args.check:
        if drift:
            print(f"::error::{len(drift)} 份 {OUT_NAME} 与现拼结果不一致：{', '.join(drift[:8])}"
                  " —— 跑 scripts/build-eval-instruction.py 重新生成，⛔ 不要手改")
            return 1
        print(f"✅ {len(tasks)} 份 {OUT_NAME} 与现拼结果一致")
        return 0
    print(f"写出 {len(tasks)} 份 {OUT_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
