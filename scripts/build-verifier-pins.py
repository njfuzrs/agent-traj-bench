#!/usr/bin/env python3
"""T02 / traj 缺陷 2：判分方自带 bun 配置 + 被保护文件按 base blob 还原。

## 每题写出三份文件（都在 `tests/`，verifier 阶段才上传，agent 阶段看不见）

  - `bunfig.verifier.toml`：`bun test --config=` 用的配置。内容 = base 的 `bunfig.toml`；
    gold patch 改了 `bunfig.toml` 的题（只有 T0010）取打完 gold patch 之后的版本，
    否则 oracle 拿不到满分。
    ⚠️ T0010 的代价：gold patch 里 bunfig 那一半由判分方提供，agent 改不改都一样。
    它 preload 的 `tests/preload-isolate-sid-home.ts` 本来就由 test_patch 注入（判分方所有），
    所以这一行属于判分环境而不是解答本体，记在 `protected.json` 的 `note` 里。
  - `protected.json`：{路径: base blob sha}。= 原还原名单 + base 上存在的 preload 目标文件。
  - `test.sh`：由 `t3-build-harbor-tasks.py:test_sh(pinned=…, verifier_config=True)` 重新生成。

## 为什么这样能堵住

容器实测（2026-11-04，T0064，`t7probe-t0064:local`）：

  | 动作 | reward |
  |---|---|
  | nop | 0 |
  | 改 `/repo/bunfig.toml` 的 `[test] preload` → 插件把每个 `*.test.ts` 换成恒绿 | **1**（一行 src 不改） |
  | 同上，但 `bun test --config=<判分方配置>` | `/repo/bunfig.toml` 被整个忽略 |
  | 改 P2P 测试 + `git add && git commit` | `git checkout --` 还原出的是 agent 的版本 |

blob sha 取自 sid-code mirror 的 base commit，与容器内 `git init` 重建出来的 base 逐个一致
（T0064 30/30 实测）。

用法：`python3 scripts/build-verifier-pins.py`（需要 mirror：`$MIRRORS_DIR`）
     `python3 scripts/build-verifier-pins.py --check`（离线：只核 test.sh 与三份产物自洽，CI 用）
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402


def _t3():
    spec = importlib.util.spec_from_file_location(
        "_t3", Path(__file__).resolve().parent / "t3-build-harbor-tasks.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(repo: str, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, GIT_DIR=str(c.mirror_path(repo)))
    return subprocess.run(["git", *args], capture_output=True, text=True, env=env)


def _preload_targets(cfg: str) -> list[str]:
    lines = [ln for ln in cfg.splitlines() if re.match(r"\s*preload\s*=", ln)]
    return [p.removeprefix("./") for ln in lines for p in re.findall(r'"([^"]+)"', ln)]


def verifier_bunfig(meta: dict, task_dir: Path) -> tuple[str, str | None]:
    """返回 (判分方配置内容, 说明)。"""
    r = _git(meta["repo"], "show", f"{meta['base_commit']}:bunfig.toml")
    base = r.stdout if r.returncode == 0 else ""
    gold = (task_dir / "solution" / "gold_patch.diff").read_text(encoding="utf-8")
    if "diff --git a/bunfig.toml " not in gold:
        return base, None
    with tempfile.TemporaryDirectory() as t:
        Path(t, "bunfig.toml").write_text(base, encoding="utf-8")
        p = subprocess.run(["git", "apply", "--include=bunfig.toml", "-"], cwd=t,
                           input=gold, capture_output=True, text=True)
        if p.returncode != 0:
            raise SystemExit(f"⛔ {task_dir.name}: gold patch 的 bunfig 部分打不上：{p.stderr[:200]}")
        return (Path(t, "bunfig.toml").read_text(encoding="utf-8"),
                "gold patch 改了 bunfig.toml ⇒ 判分方配置取打完 gold 的版本；"
                "其 preload 目标由 test_patch 注入（判分方所有），agent 对 bunfig 的改动不参与判分")


def build_one(task_dir: Path, t3) -> dict:
    meta = json.loads((task_dir / "meta.json").read_text(encoding="utf-8"))
    cfg, note = verifier_bunfig(meta, task_dir)
    restore, remove = meta["protection"]["restore"], meta["protection"]["remove"]
    paths = list(restore) + [p for p in _preload_targets(cfg) if p not in remove and p not in restore]
    blobs: dict[str, str] = {}
    for p in paths:
        r = _git(meta["repo"], "rev-parse", f"{meta['base_commit']}:{p}")
        if r.returncode == 0:
            blobs[p] = r.stdout.strip()
        elif p in restore:
            raise SystemExit(f"⛔ {task_dir.name}: 还原名单里的 {p} 在 base 上取不到 blob")
        # preload 目标在 base 上不存在 ⇒ 由 test_patch 新增，不需要还原
    doc = {"_note": "T02：test.sh 按这里的 base blob 还原被保护文件。由 scripts/build-verifier-pins.py 生成，⛔ 不要手改。",
           "base_commit": meta["base_commit"], "blobs": dict(sorted(blobs.items()))}
    if note:
        doc["note"] = note
    tests = task_dir / "tests"
    (tests / "bunfig.verifier.toml").write_text(cfg, encoding="utf-8")
    (tests / t3.PROTECTED_JSON).write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    sh = render_test_sh(task_dir, t3)
    (tests / "test.sh").write_text(sh, encoding="utf-8")
    return {"n_blobs": len(blobs), "note": bool(note)}


def render_test_sh(task_dir: Path, t3) -> str:
    meta = json.loads((task_dir / "meta.json").read_text(encoding="utf-8"))
    pinned, vcfg = t3.load_protection(task_dir)
    return t3.test_sh(task_dir.name, meta["f2p"], meta["p2p"], meta["protection"]["restore"],
                      meta["protection"]["remove"], meta["test_cmd"], pinned=pinned, verifier_config=vcfg)


def check(tasks: list[Path], t3) -> int:
    """离线核：三份产物都在、还原名单全被 pin 住、test.sh 等于现拼结果。"""
    bad = []
    for d in tasks:
        tests = d / "tests"
        if not (tests / t3.PROTECTED_JSON).exists() or not (tests / "bunfig.verifier.toml").exists():
            bad.append(f"{d.name}: 缺 T02 产物")
            continue
        try:
            want = render_test_sh(d, t3)
        except ValueError as e:
            bad.append(str(e))
            continue
        if (tests / "test.sh").read_text(encoding="utf-8") != want:
            bad.append(f"{d.name}: test.sh 与现拼结果不一致")
    for b in bad[:10]:
        print(f"::error::{b}")
    print(f"{'⛔' if bad else '✅'} T02 判分加固：{len(tasks) - len(bad)}/{len(tasks)} 题自洽")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="T02：判分方自带 bun 配置 + 按 base blob 还原")
    ap.add_argument("--check", action="store_true", help="离线自洽检查（不需要 mirror）")
    args = ap.parse_args(argv)
    t3 = _t3()
    tasks = sorted(p for p in c.MVP_TASKS.iterdir() if p.is_dir())
    if not tasks:
        print(f"::error::{c.MVP_TASKS} 下没有题", file=sys.stderr)
        return 2
    if args.check:
        return check(tasks, t3)
    stats = {d.name: build_one(d, t3) for d in tasks}
    print(f"写出 {len(stats)} 题；pin 住 {sum(s['n_blobs'] for s in stats.values())} 个文件；"
          f"判分方配置取 gold 版本的：{[t for t, s in stats.items() if s['note']]}")
    return check(tasks, t3)


if __name__ == "__main__":
    raise SystemExit(main())
