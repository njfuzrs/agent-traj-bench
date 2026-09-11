#!/usr/bin/env python3
"""T6 — 容器内泄漏扫描（方案 §4 T6 第二项检查）

出处：docs-research/trajectory-platform/bench-mvp-plan.md v1.2 §4 T6

## 为什么必须在容器里扫，不能读 tar

方案原话：「**查产物，不查意图**」。T4 的剔除清单写对了 ≠ 执行对了 —— T4 那两处
漏剔（`lstrip('./')` 把 `.claude/` 啃成 `claude/`、4 个评测 workflow 散落在
`.github/workflows/`）都是**容器内 `ls` 抓出来的**，清单自己不自证完备。

而且容器里有两处 tar 根本看不到的地方：
  - `bun install` 装出来的 `node_modules/`（构建期才产生）
  - `/` 根下的 `/eval-framework` stub（Dockerfile 里 printf 出来的，不在快照内）

## 三类「看着像泄漏、其实是真实资产」（T4 已核，误淘汰会打断存活测试）

  1. `src/skill/builtin/*/evals/` —— skill 的 baseline case。
     `tests/skill/code-review.test.ts:54` 断言该目录存在、`:58` 断言至少 10 条
     yaml。剔了会让**存活测试**变红，等于自己造一个假的 P2P 失败。
     ⚠️ T4 报告记的是 `packages/*/skill/builtin/*/evals/`（monorepo 形态），
     本批 40 条全是 external 形态，落在 `src/` 下 —— **同一类，路径不同**。
  2. `packages/eval-framework/package.json` —— workspace 锚，判分本体
     `core/runner.ts` 已剔（本批 40 条无此形态，保留判据以防回归）。
  3. `/eval-framework`（容器根下，不在 /repo 里）—— external 分支的 stub，
     内容只有 name/version/private 三键，快照内零处 import。

## 用法

    python3 scripts/mvp/t6-leak-scan.py            # 全量 40 条
    python3 scripts/mvp/t6-leak-scan.py --only T0002
    python3 scripts/mvp/t6-leak-scan.py --keep-images   # 不删镜像（调试用）
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

OUT = c.MVP_REPORTS / "t6-recheck" / "leak-scan-container.jsonl"

#: 方案 §4 T6 的 find 判据，逐字照搬后补三个词（harbor / external-benchmarks / .claude）。
#: ⚠️ `-o` 的优先级已实测确认（三个表达式都生效，不是只对最后一个），但仍显式加括号。
FIND_EXPR = [
    "(",
    # 方案 §4 T6 原样的三条
    "-path", "*evals*",
    "-o", "-name", "*calibration*",
    "-o", "-path", "*bugfixes*",
    # 补的四条：判分本体 / harbor 自身 / 评测工作流 / agent 配置目录
    "-o", "-path", "*judge*",
    "-o", "-path", "*external-benchmark*",
    "-o", "-path", "*harbor*",
    "-o", "-path", "*.claude*",
    # ⚠️ 单列 `eval-framework`，**不能靠放宽成 `*eval*`**：
    # `*evals*` 匹配不到 `/eval-framework`（少个 s），而它正是方案点名的三类良性之一,
    # 等于扫描器对它失明（T6 实测发现）。但放宽成 `*eval*` 会把
    # `timeval`（perl 头文件）、`evaluator.ts`（仓库真实源码）全扫进来 ——
    # 噪声淹掉真违规，比漏看更危险。所以精确列出这一个词。
    "-o", "-path", "*eval-framework*",
    ")",
]

#: 排除掉噪声目录：/proc /sys /dev 是内核虚拟文件系统，扫它们只会拿到无关命中
PRUNE = ["-path", "/proc", "-prune", "-o", "-path", "/sys", "-prune", "-o",
         "-path", "/dev", "-prune", "-o"]

#: 三类已核良性（见 docstring）。命中这些不算违规，但要单独计数并报出来。
BENIGN = [
    (re.compile(r"^/repo/(src|packages)/[^/]*/?skill/builtin/[^/]+/evals(/|$)"),
     "skill baseline case（tests/skill/code-review.test.ts:54 断言其存在）"),
    (re.compile(r"^/repo/packages/eval-framework/package\.json$"),
     "workspace 锚（判分本体 core/runner.ts 已剔）"),
    (re.compile(r"^/eval-framework(/|$)"),
     "external 分支 stub（只有 name/version/private 三键，快照内零处 import）"),
    # `bun install` 会把上面那个 stub 链进 node_modules —— 同一个东西的第二处落点，
    # tar 里看不到（构建期产物），只有容器内扫描才会出现。
    (re.compile(r"^/repo/node_modules/eval-framework(/|$)"),
     "同上 stub 被 bun install 链入 node_modules（构建期产物）"),
    # 基础镜像 oven/bun 自带的系统文件。与 task 内容无关，不构成泄漏面。
    # 之所以仍扫 `/` 而不 prune：harbor/judge 若被误挂到根下，只有全盘扫才看得见。
    (re.compile(r"^/(usr|lib|bin|sbin|etc|opt|var/lib/(apt|dpkg))/"),
     "基础镜像自带系统文件（非 task 内容）"),
]


#: 单条构建上限。`bun install` 正常 2-3 分钟；宿主代理中途断开时它会**无限等待**
#: 一条死连接（实测 0.02% CPU 挂 8 分钟不退），而 `docker build` 自己没有超时。
#: 没有这个上限，一次代理抖动就会把整轮扫描永久卡住。
BUILD_TIMEOUT_SEC = 420


def build(task: Path, tag: str) -> tuple[bool, str]:
    """构建 task 的镜像。**用 task 自己的 environment/ 作构建上下文**，与 harbor 同源。

    返回 `(是否成功, 失败原因)`。原因要落盘 —— 「构建超时」和「Dockerfile 有错」
    是两回事：前者复跑能过（属基础设施），后者是 task 缺陷。混在一起会误判淘汰。
    """
    try:
        r = subprocess.run(
            ["docker", "build", "-q", "-t", tag, "-f", str(task / "environment" / "Dockerfile"),
             str(task / "environment")],
            capture_output=True, text=True, timeout=BUILD_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        print(f"  ⏱️  构建超时（>{BUILD_TIMEOUT_SEC}s，多半是宿主代理断开）", file=sys.stderr)
        return False, f"build_timeout_{BUILD_TIMEOUT_SEC}s"
    if r.returncode != 0:
        err = r.stderr.strip()[-400:]
        print(f"  🔴 构建失败：{err}", file=sys.stderr)
        return False, f"build_failed: {err[-200:]}"
    return True, ""


def scan(tag: str) -> list[str]:
    """在容器内跑 find。**不看退出码** —— find 撞到不可读目录会返非 0 但结果有效。"""
    r = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--entrypoint", "find", tag,
         "/", *PRUNE, *FIND_EXPR, "-print"],
        capture_output=True, text=True,
    )
    return [x for x in r.stdout.splitlines() if x.strip()]


def classify(hits: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    viol, benign = [], []
    for h in hits:
        why = next((w for p, w in BENIGN if p.match(h)), None)
        (benign.append((h, why)) if why else viol.append(h))
    return viol, benign


def load_done() -> dict[str, dict]:
    """读已有产物，供 `--resume` 跳过已扫条目。文件不存在或有坏行都当没扫过。"""
    done: dict[str, dict] = {}
    if not OUT.exists():
        return done
    for line in OUT.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if row.get("task_id"):
            done[row["task_id"]] = row
    return done


def main() -> int:
    ap = argparse.ArgumentParser(description="T6 容器内泄漏扫描")
    ap.add_argument("--only", nargs="*", help="只扫这几条")
    ap.add_argument("--keep-images", action="store_true", help="扫完不删镜像")
    ap.add_argument("--resume", action="store_true",
                    help="跳过已成功扫过的条目（构建失败/超时的会重试）")
    args = ap.parse_args()

    gate = c.MVP_META / "gate.jsonl"
    surv = [json.loads(l)["task_id"] for l in gate.open() if json.loads(l)["survives"]]
    todo = args.only or surv

    OUT.parent.mkdir(parents=True, exist_ok=True)
    # ⚠️ 逐条**追加**落盘，不在结尾一次性 write_jsonl。
    # 首版栽在这里：跑到第 13 条时宿主代理断开、进程被杀，40 条只留下 1 行 —— 前 12 条
    # 的容器全白建了。长跑任务的中间结果必须即时可见，否则一次抖动就毁掉整轮。
    done = load_done() if args.resume else {}
    # 只跳过**成功**的；构建失败/超时的要重试（那是基础设施抖动，不是结论）
    skip = {t for t, r in done.items() if r.get("built") and r.get("leak_scan_passed") is not None}
    rows = [done[t] for t in todo if t in skip]
    n_bad = sum(1 for r in rows if not r.get("leak_scan_passed"))
    if skip:
        print(f"--resume：跳过已扫完的 {len(skip)} 条\n")
    if not args.resume and OUT.exists():
        OUT.unlink()   # 全新跑：清掉旧产物，避免新旧混写

    def emit(row: dict) -> None:
        with OUT.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    pending = [t for t in todo if t not in skip]
    for i, t in enumerate(pending, 1):
        tag = f"t6scan:{t.lower()}"
        print(f"[{i}/{len(pending)}] {t} 构建…", flush=True)
        ok_build, why = build(c.MVP_TASKS / t, tag)
        if not ok_build:
            row = {"task_id": t, "built": False, "n_hits": None,
                   "violations": None, "benign_n": None,
                   "leak_scan_passed": None, "error": why}
            rows.append(row)
            emit(row)
            n_bad += 1
            continue
        hits = scan(tag)
        viol, benign = classify(hits)
        ok = not viol
        n_bad += 0 if ok else 1
        print(f"      命中 {len(hits)}（良性 {len(benign)} / 违规 {len(viol)}）"
              f" {'✅' if ok else '🔴 ' + str(viol[:5])}", flush=True)
        row = {"task_id": t, "built": True, "n_hits": len(hits),
               "violations": viol, "benign_n": len(benign),
               "benign_classes": sorted({w for _, w in benign}),
               "leak_scan_passed": ok}
        rows.append(row)
        emit(row)
        if not args.keep_images:
            subprocess.run(["docker", "rmi", "-f", tag], capture_output=True)

    n_unbuilt = sum(1 for r in rows if not r.get("built"))
    print(f"\n扫描 {len(rows)} 条：违规 {sum(1 for r in rows if r.get('leak_scan_passed') is False)} 条，"
          f"未建成 {n_unbuilt} 条 → {OUT}")
    if n_unbuilt:
        print(f"⚠️ 未建成的复跑：python3 scripts/mvp/t6-leak-scan.py --resume")
    return 1 if n_bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
