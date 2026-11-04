#!/usr/bin/env python3
"""题面泄漏扫描 —— 实跑题面里不许逐字出现 gold patch 的代码行（traj 缺陷 1 / 6，T03）。

## 为什么要有这一道

现有三道泄漏防线的作用域都不是「模型真正看到的那段文字」：

  - T4 `LEAK_PREFIXES` 从**容器**里剔掉 `docs/bugfixes/`（注释：「直接写着解法」）
  - T6 `t6-leak-scan.py` 在**容器**里复扫一遍
  - gate12 `check-contamination.py` 扫 **`tasks/`** 下的 5 个污染字段

而 T8 修复① 把同一批 `docs/bugfixes/` 原文内联进了**题面**（`t8-rerun.py:build_instruction`），
8/34 条题面逐字含 gold patch 代码（T0008 泄 26 行）。三道防线全绿，
因为没有一道扫题面。本脚本只扫题面，判据只看产物、不看题面是怎么生成的。

## 判据（与缺陷 1 的实测命令同口径）

gold patch 的新增行（`+` 开头、非 `+++`），去首尾空白后：

  - 长度 ≥ `MIN_LEN`（25）：短行（`}`、`return x;`）在任何文档里都会自然出现，是噪声
  - 不以 `*` `//` `/*` 开头：注释行不是实现

任一候选行作为子串出现在题面里 ⇒ 该题泄漏。⛔ 阈值是 1 行，不是比例：
T0014 / T0026 / T0065 都只泄 1 行，按比例算会被放过，而缺陷 1 要求 8/34 全部命中。

## 扫哪份题面（`--source`）

  - `eval`（默认，CI 跑这个）：`tasks/*/instruction.eval.md` —— v0.2.1 起复现基线用的题面
  - `t8`：用 `t8-rerun.py` 的 `build_instruction` **现拼** 37.8% 那批的题面。⚠️ 预期红，
    它是本门禁的阳性对照（缺陷 1 的 8 条必须全部报出来，否则判据失效）
  - `raw`：`tasks/*/instruction.md`（原句 + 环境事实，provenance）

## 豁免（`meta/prompt-leak-allowlist.json`）

只收「命中行在 base 里已存在、文档在描述现状」的情形（T0014 就是这样：缺陷 1 原先的
8/34 里它那 1 行是误报）。每条必须带可复跑的证据。⚠️ 豁免项**不再命中**时也报红 ——
否则题面一改，清单就成了没人知道还管不管用的旧账。

退出码：0 扫到题面且零泄漏；1 有泄漏或豁免过期；2 作用域为空。
⛔ 空集不当通过（同 `check-contamination.py`）：`instruction.eval.md` 还没生成时
默认模式必须红，而不是「0 个文件 0 命中」的假绿。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

MIN_LEN = 25
ALLOWLIST = c.MVP_META / "prompt-leak-allowlist.json"
COMMENT_PREFIXES = ("*", "//", "/*")


def gold_candidates(diff_text: str) -> set[str]:
    """gold patch 里够得上「实现代码」的新增行。"""
    out: set[str] = set()
    for raw in diff_text.splitlines():
        if not raw.startswith("+") or raw.startswith("+++"):
            continue
        line = raw[1:].strip()
        if len(line) >= MIN_LEN and not line.startswith(COMMENT_PREFIXES):
            out.add(line)
    return out


def leaked_lines(prompt: str, candidates: set[str]) -> list[str]:
    return sorted(line for line in candidates if line in prompt)


def _t8_builder():
    """加载 `t8-rerun.py` 的 `build_instruction`。脚本名带连字符，只能 spec 加载。

    ⚠️ 只读：`build_instruction` 只读 tasks/ 与 reports/t8-fix/，不写任何文件。
    """
    spec = importlib.util.spec_from_file_location(
        "_t8_rerun", Path(__file__).resolve().parent / "t8-rerun.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return lambda t: mod.build_instruction(t, inline_docs=True, f2p_list=True)


def load_prompts(source: str, tasks_dir: Path) -> dict[str, str]:
    tasks = sorted(p.name for p in tasks_dir.iterdir() if p.is_dir()) if tasks_dir.is_dir() else []
    if source == "t8":
        build = _t8_builder()
        return {t: build(t) for t in tasks}
    name = {"eval": "instruction.eval.md", "raw": "instruction.md"}[source]
    return {t: (tasks_dir / t / name).read_text(encoding="utf-8", errors="replace")
            for t in tasks if (tasks_dir / t / name).exists()}


def load_allowlist(path: Path) -> dict[str, set[str]]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for t, items in raw.items():
        if t.startswith("_"):
            continue
        for it in items:
            if not (it.get("reason") and it.get("evidence")):
                raise SystemExit(f"⛔ 豁免 {t} 缺 reason / evidence：{it.get('line')!r}")
            out.setdefault(t, set()).add(it["line"])
    return out


def scan(prompts: dict[str, str], tasks_dir: Path,
         allow: dict[str, set[str]] | None = None) -> dict[str, dict]:
    """返回 {task: {n_candidates, leaked, allowed, stale_allow}}，只含有 gold patch 的题。"""
    allow = allow or {}
    out: dict[str, dict] = {}
    for t, prompt in sorted(prompts.items()):
        gp = tasks_dir / t / "solution" / "gold_patch.diff"
        if not gp.exists():
            continue
        cand = gold_candidates(gp.read_text(encoding="utf-8", errors="replace"))
        hits = leaked_lines(prompt, cand)
        ok = allow.get(t, set())
        out[t] = {"n_candidates": len(cand),
                  "leaked": [h for h in hits if h not in ok],
                  "allowed": [h for h in hits if h in ok],
                  "stale_allow": sorted(ok - set(hits))}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="题面泄漏扫描：实跑题面不许逐字含 gold patch 代码行")
    ap.add_argument("--source", choices=("eval", "t8", "raw"), default="eval")
    ap.add_argument("--tasks", type=Path, default=c.MVP_TASKS, help="tasks 根目录（测试用）")
    ap.add_argument("--json", action="store_true", help="输出逐题 JSON")
    ap.add_argument("--allowlist", type=Path, default=ALLOWLIST)
    ap.add_argument("--no-allowlist", action="store_true", help="不读豁免（看原始命中）")
    args = ap.parse_args(argv)

    prompts = load_prompts(args.source, args.tasks)
    allow = {} if args.no_allowlist else load_allowlist(args.allowlist)
    res = scan(prompts, args.tasks, allow)
    if not res:
        print(f"::error::--source {args.source} 下没扫到任何题面（{args.tasks}）"
              " ⇒ 作用域为空，⛔ 不当通过", file=sys.stderr)
        return 2

    bad = {t: r for t, r in res.items() if r["leaked"]}
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    for t, r in bad.items():
        print(f"::error::{t}: {len(r['leaked'])}/{r['n_candidates']} 行 gold patch 逐字出现在题面")
        for line in r["leaked"][:3]:
            print(f"    {line[:120]}")
    # 豁免过期只在默认（eval）题面上判：t8 / raw 是别的题面，命中集本来就不同
    stale = {t: r["stale_allow"] for t, r in res.items()
             if r["stale_allow"] and args.source == "eval"}
    for t, lines in stale.items():
        print(f"::error::{t}: 豁免项已不再命中，从 {_rel(args.allowlist)} 删掉：{lines[0][:80]}")
    n_allowed = sum(len(r["allowed"]) for r in res.values())
    print(f"--source {args.source}：扫描 {len(res)} 份题面，泄漏 {len(bad)} 份"
          f"{'：' + ', '.join(bad) if bad else ''}"
          f"{f'（豁免 {n_allowed} 行）' if n_allowed else ''}")
    return 1 if bad or stale else 0


def _rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(c.REPO_ROOT))
    except ValueError:
        return str(p)


if __name__ == "__main__":
    raise SystemExit(main())
