#!/usr/bin/env python3
"""T5 — 门禁：oracle / nop 双向验证（跑批 + 判定 + 报告）

出处：docs-research/trajectory-platform/bench-mvp-plan.md v1.2 §4 T5

判定逻辑在 `t5_gate_lib.py`（可单测、可纯复算）；本文件负责调 harbor 跑批、
落 `meta/gate.jsonl` 与 `reports/t5-gate.md`。

## 三道门禁

    | 门禁     | agent       | 期望              | 不符合说明什么                |
    |----------|-------------|-------------------|-------------------------------|
    | ① 可解性 | oracle      | reward = 1        | gold patch 打不上 / 测试坏了  |
    | ② 有效性 | nop         | f2p=0 **且** p2p=1| f2p=1 假 task；p2p=0 坏环境   |
    | ③ 稳定性 | oracle -k 3 | 三次一致          | 测试有随机性 / 依赖外部状态   |

门禁③只在**过了①②的存活集**上跑 —— 对已经淘汰的 task 测稳定性没有意义，
而它是三道里最贵的一道（trial 数 ×3）。

## 🔴 T5 首次实跑抓到的 schema 缺陷（2026-09-10，已修 t3 生成器）

`harbor/models/verifier/result.py:5` 是 `rewards: dict[str, float | int] | None`。
原先 `score.py` 往 `reward.json` 里写了嵌套 dict（`f2p_detail`/`p2p_detail`）、
`test.sh` 的兜底 printf 写了字符串（`"error": "..."`）—— pydantic 全部拒收，
形态是 **`Trials=0 / Exceptions=N` 全 ValidationError**：整条 trial 判错，
连 reward=0 都拿不到。

**这个坑 T3 与 TZ 都发现不了**：TZ 跑的 hello-world 用 harbor 自带的单键
reward.json；T3 是 `docker run` 直跑 bun，**没有经过 harbor 的结果解析层**。
只有 T5 会撞上 —— 这正是「门禁要在真链路上跑」的理由。

修法：`reward.json` 只放标量（详情移到 `score-detail.json`，错误降级成
`error_code` 数值键）。见 t3-build-harbor-tasks.py 的 score_py() / test_sh()。

## 硬约束（TZ 实测，别靠记性）

  - **`-o` 必须落在 `$HOME` 之下**（R-3）。colima `mounts: []`，VM 内只挂 `$HOME`
    一个 virtiofs。用 /tmp 的形态是 `RewardFileNotFoundError` —— 而它指向
    「reward 没写」这个**错误方向**（实际写了，只是宿主读不到）。
    ⚠️ 同样约束**也适用于 `-p` 的 task 目录**：docker 构建上下文由 VM 内的
    dockerd 读取，放 /tmp 会让构建拿不到 repo-snapshot.tar.gz。
  - **`HARBOR_TELEMETRY=0` 写进命令本身**（R-2）。遥测默认开（发往 PostHog），
    我们的 instruction.md 含私有仓库信息。
  - **`-n 1` 是硬要求**。README ⑤ 实测并发是「最大的单一失真源，且伪装成能力差」。
  - **不能看退出码**。harbor 失败时退出码仍是 0（TZ 四次失败全复现）。

## 用法

    # 完整跑（三道门禁）
    python3 scripts/t5-gate.py

    # 只跑某一道（分批时用）
    python3 scripts/t5-gate.py --only nop

    # 在既有产物上纯复算，不重跑（$0）
    python3 scripts/t5-gate.py --from-runs
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common as c  # noqa: E402
import t5_gate_lib as lib  # noqa: E402

TASKS = c.MVP_DIR / "tasks"
GATE_DIR = c.MVP_REPORTS / "t5-gate"
GATE_JSONL = c.MVP_META / "gate.jsonl"
REPORT = c.MVP_REPORTS / "t5-gate.md"

#: 门禁③的存活集副本放这 —— harbor 的 `-p` 收「装着一堆 task 目录的目录」，
#: 要只跑存活集就得单独建一个目录。**必须在 $HOME 下**（见 docstring 硬约束）。
SURVIVOR_DIR = GATE_DIR / "survivors"


def run_harbor(agent: str, task_path: Path, out: Path, *, k: int | None = None) -> float:
    """跑一次 harbor，返回墙钟秒数。

    **刻意不检查退出码** —— harbor 失败时也返 0（TZ 实测）。判据是产物里的
    逐 task reward，由 lib 那边读。这里只负责把批跑完并把日志留下。
    """
    out.mkdir(parents=True, exist_ok=True)
    c.assert_jobs_dir_ok(out)
    cmd = [
        "harbor", "run",
        "-p", str(task_path),
        "-a", agent,
        "-n", "1",                          # 硬要求，见 docstring
        "-o", str(out),
        "--verifier-timeout-multiplier", "6",
        "-y",
    ]
    if k:
        cmd += ["-k", str(k)]

    env = {**os.environ, "HARBOR_TELEMETRY": "0"}   # R-2：写进命令本身
    log = out / "run.log"
    t0 = time.time()
    with open(log, "w", encoding="utf-8") as f:
        subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env=env, check=False)
    elapsed = time.time() - t0
    print(f"  {agent}{f' -k {k}' if k else ''} 跑完，{elapsed / 60:.1f} 分钟，日志 {log}")
    return elapsed


def load(name: str) -> list[lib.TrialRow]:
    """读某道门禁最近一次 run 的全部 trial。"""
    run = lib.latest_run(GATE_DIR / name)
    if run is None:
        return []
    return lib.collect_run(run)


def summarize(name: str, rows, judge) -> lib.GateSummary:
    s = lib.GateSummary(name=name, verdicts=judge(rows))
    print(f"  {s.line()}")
    return s


def build_survivor_dir(tasks: list[str]) -> Path:
    """给门禁③建存活集目录。用符号链接而不是复制 —— 快照有 409MB。"""
    if SURVIVOR_DIR.exists():
        for p in SURVIVOR_DIR.iterdir():
            p.unlink() if p.is_symlink() else None
    SURVIVOR_DIR.mkdir(parents=True, exist_ok=True)
    for t in tasks:
        link = SURVIVOR_DIR / t
        if not link.exists():
            link.symlink_to((TASKS / t).resolve())
    return SURVIVOR_DIR


def write_outputs(summaries: dict[str, lib.GateSummary]) -> list[str]:
    """落 gate.jsonl + t5-gate.md，返回最终存活名单。"""
    all_tasks = sorted(p.name for p in TASKS.iterdir() if p.is_dir())

    # 逐 task 汇总三道门禁
    rows: list[dict[str, object]] = []
    for t in all_tasks:
        row: dict[str, object] = {"task_id": t}
        for name, s in summaries.items():
            v = next((x for x in s.verdicts if x.task == t), None)
            row[name] = None if v is None else {
                "ok": v.ok,
                "reason": v.reason,
                "infra": v.infra,
            }
        judged = [v for n in summaries if isinstance(v := row.get(n), dict)]
        row["survives"] = bool(judged) and all(x["ok"] for x in judged)
        rows.append(row)

    c.write_jsonl(GATE_JSONL, rows)
    survivors = [str(r["task_id"]) for r in rows if r["survives"]]

    lines = [
        "# T5 — 门禁：oracle / nop 双向验证",
        "",
        "> 生成：`scripts/t5-gate.py`；判定逻辑 `scripts/t5_gate_lib.py`",
        "> 逐 task 结论：`meta/gate.jsonl`",
        "",
        "## 结论",
        "",
        "| 门禁 | agent | 过 | 淘汰 | 基础设施问题 |",
        "|---|---|---|---|---|",
    ]
    agent_of = {"oracle": "oracle", "nop": "nop", "oracle-k3": "oracle -k 3"}
    for name, s in summaries.items():
        lines.append(
            f"| {name} | `{agent_of.get(name, name)}` | {len(s.survivors)}/{len(s.verdicts)} "
            f"| {len(s.failures)} | {len(s.infra_issues)} |"
        )
    # ⚠️ 措辞必须反映**实际跑了几道**。`--only nop` 时写「三道门禁后存活」
    # 会让读者以为 61 条是终值，而 oracle/k3 还没跑 —— 这正是「报告自己说谎」。
    ran = "、".join(summaries)
    complete = len(summaries) == 3
    lines += [
        "",
        f"**已跑门禁：{ran}**（{'三道齐全' if complete else f'共 {len(summaries)}/3 道，其余未跑'}）",
        "",
        f"**{'三道门禁后存活' if complete else '当前存活（仅以上门禁）'}：{len(survivors)}/{len(all_tasks)} 条**",
        "",
    ]
    if not complete:
        lines += [
            "> ⚠️ **这不是终值** —— 未跑的门禁还会继续淘汰。补跑："
            + "、".join(f"`--only {g}`" for g in ("oracle", "nop", "oracle-k3") if g not in summaries),
            "",
        ]

    for name, s in summaries.items():
        if s.failures:
            lines += [f"### {name} 淘汰（task 自身问题）", ""]
            lines += [f"- `{v.task}` —— {v.reason}" for v in s.failures] + [""]
        if s.infra_issues:
            lines += [
                f"### {name} 基础设施问题（**修环境，不要动 task**）",
                "",
            ]
            lines += [f"- `{v.task}` —— {v.reason}" for v in s.infra_issues] + [""]

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n报告 → {REPORT}\n逐条 → {GATE_JSONL}")
    return survivors



# ── 反向自证（方案 §4 T5 的四条，`--selftest` 跑）──────────────────────

#: 变异体放这。**必须在 $HOME 下**（同 `-o` 的约束）。
SELFTEST_DIR = GATE_DIR / "selftest"

#: 基线 task —— 必须挑一条**三道门禁全过**的，否则红了分不清是变异还是它本来就坏。
SELFTEST_BASE = "T0002"


def _mutants(base: Path, work: Path) -> list[lib.SelftestCase]:
    """按方案 §4 T5 造四个变异体 + 一个未变异对照，返回它们的期望。

    🔴 **只动 `tests/` 与 `solution/`，`environment/` 原样硬链接** ——
    `environment_content_hash()` 只哈希 `environment/` 下的真实文件（且跳过
    symlink），所以五个副本共享同一个 `environment_id`，**镜像只构建一次**。
    改 `environment/` 会让每个变异体各建一次镜像（约 30 秒 + 数百 MB）。
    """
    import json
    import shutil

    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    f2p_path = json.loads((base / "tests" / "f2p.json").read_text())[0]

    def copy(name: str) -> Path:
        d = work / name
        (d / "tests").mkdir(parents=True)
        (d / "solution").mkdir(parents=True)
        (d / "environment").mkdir(parents=True)
        for f in ("task.toml", "instruction.md", "meta.json"):
            shutil.copy2(base / f, d / f)
        for f in base.glob("tests/*"):
            shutil.copy2(f, d / "tests" / f.name)
        for f in base.glob("solution/*"):
            shutil.copy2(f, d / "solution" / f.name)
        for f in base.glob("environment/*"):
            # 硬链接：12MB 的快照不复制 5 份，且保证内容逐字节相同 → 同一个 environment_id
            try:
                os.link(f, d / "environment" / f.name)
            except OSError:
                shutil.copy2(f, d / "environment" / f.name)
        return d

    cases: list[lib.SelftestCase] = []

    # ── M0 对照：不变异，必须过 ──────────────────────────────────────
    # 🔴 没有它，「整批因构建失败而全红」会被当成「四条自证全部通过」。
    copy("M0-control")
    cases.append(
        lib.SelftestCase(
            "M0-control", "oracle", True,
            "未变异对照 —— 它若不过，说明整批环境有问题，四条自证的红都不算数",
        )
    )

    # ── M1：test.sh 无条件报 1 → 门禁② 必须判「假 task」 ─────────────
    # ⚠️ reward.json 与 reward.txt **都写 1**，否则红会来自「双源不一致」
    #    （infra=True）而不是「假 task」（infra=False）—— 那是假绿的一种。
    m1 = copy("M1-testsh-always-1")
    (m1 / "tests" / "test.sh").write_text(
        "#!/bin/bash\n"
        "# 反向自证①（方案 §4 T5）：无条件报满分。门禁② 必须抓到 f2p=1。\n"
        "mkdir -p /logs/verifier\n"
        "printf '{\"reward\":1.0,\"f2p\":1.0,\"p2p\":1.0,\"error_code\":0}\\n'"
        " > /logs/verifier/reward.json\n"
        "echo 1 > /logs/verifier/reward.txt\n",
        encoding="utf-8",
    )
    cases.append(
        lib.SelftestCase(
            "M1-testsh-always-1", "nop", False,
            "test.sh 无条件报 1 → 门禁②（nop）必须判「假 task」",
            expect_infra=False, expect_reason_has="假 task",
        )
    )

    # ── M2：solve.sh 空 → 门禁① 必须报红 ───────────────────────────
    m2 = copy("M2-empty-solution")
    (m2 / "solution" / "solve.sh").write_text(
        "#!/bin/bash\n"
        "# 反向自证②（方案 §4 T5）：空参考解。门禁① 必须报红。\n"
        "exit 0\n",
        encoding="utf-8",
    )
    cases.append(
        lib.SelftestCase(
            "M2-empty-solution", "oracle", False,
            "参考解为空 → 门禁①（oracle）必须报红，且判成 task 问题而非环境问题",
            expect_infra=False, expect_reason_has="f2p=0.0",
        )
    )

    # ── M3：test_patch 故意冲突 → reward=0 且 error_code=2，**不是 trial error** ──
    m3 = copy("M3-conflicting-test-patch")
    (m3 / "tests" / "test_patch.diff").write_text(
        # 无 `index` 行 → `--3way` 无 blob 可用，退回普通 apply，必在 context 上失败。
        # 刻意打在 package.json（一定存在）上，确保失败原因是 context 不匹配而非文件缺失。
        "diff --git a/package.json b/package.json\n"
        "--- a/package.json\n"
        "+++ b/package.json\n"
        "@@ -1,3 +1,3 @@\n"
        "-THIS-LINE-DOES-NOT-EXIST-IN-PACKAGE-JSON\n"
        "+replacement-line\n"
        " neither-does-this-context-line\n"
        " nor-this-one\n",
        encoding="utf-8",
    )
    cases.append(
        lib.SelftestCase(
            "M3-conflicting-test-patch", "oracle", False,
            "test_patch 打不上 → reward=0 且 error_code=2，"
            "且 **trial 状态不是 error**（要 reward=0，不要 trial error）",
            expect_infra=False, expect_reason_has="test_patch 打不上",
            expect_error_code=2,
        )
    )

    # ── M4：模拟 agent 改测试 → 测试保护必须清掉，门禁① 仍为 1 ──────
    # 注入点选 solve.sh：OracleAgent 跑的就是它，等于「agent 在 agent 阶段动了测试」。
    m4 = copy("M4-agent-tampers-tests")
    (m4 / "solution" / "solve.sh").write_text(
        "#!/bin/bash\n"
        "# 反向自证④（方案 §4 T5）：agent 在自己阶段往 F2P 测试文件里写垃圾。\n"
        "# test.sh 的 `rm -f` + `git checkout` 必须把它清掉，门禁① 仍为 1。\n"
        "set -euo pipefail\n"
        "cd /repo\n"
        "git update-index -q --refresh || true\n"
        "git apply --3way /solution/gold_patch.diff\n"
        f"mkdir -p \"$(dirname '{f2p_path}')\"\n"
        f"printf 'test(\"tampered\", () => {{ throw new Error(\"agent wrote this\"); }});\\n'"
        f" > '{f2p_path}'\n",
        encoding="utf-8",
    )
    cases.append(
        lib.SelftestCase(
            "M4-agent-tampers-tests", "oracle", True,
            f"agent 往 `{f2p_path}` 写垃圾 → 测试保护必须清掉它，门禁① 仍为 1",
        )
    )

    # ── M5：M4 的配对反证 —— 拿掉保护，同样的注入必须报红 ─────────────
    # 🔴 **没有 M5，M4 的绿是不可信的**：「垃圾被清掉了所以绿」与「垃圾根本没写
    # 进去所以绿」在产物里长得一模一样。M4 绿 + M5 红成对出现，才排除了后者 ——
    # 这正是 T4 那条恒绿自检（阈值拍错导致永远返绿）骗过自己的同一个机制。
    #
    # 拿掉的是 test.sh 里针对该 F2P 文件的 `rm -f`。于是 agent 写的垃圾留在原地，
    # `git apply --3way` 要新建这个文件时撞上「已存在且内容不同」→ 打不上 →
    # error_code=2。红的**形态**与 M3 相同，但成因不同（M3 是 patch 本身坏，
    # 这条是保护缺失），所以两条都要有。
    m5 = copy("M5-tamper-unprotected")
    (m5 / "solution" / "solve.sh").write_text(
        (m4 / "solution" / "solve.sh").read_text(encoding="utf-8"), encoding="utf-8"
    )
    base_sh = (base / "tests" / "test.sh").read_text(encoding="utf-8")
    guard = f"rm -f '{f2p_path}'"
    assert guard in base_sh, f"基线 test.sh 里找不到保护行：{guard}"
    (m5 / "tests" / "test.sh").write_text(
        base_sh.replace(
            guard,
            f"# 反向自证⑤：**故意拿掉**这行保护（原为 {guard}）—— 必须因此报红",
        ),
        encoding="utf-8",
    )
    cases.append(
        lib.SelftestCase(
            "M5-tamper-unprotected", "oracle", False,
            "M4 的配对反证：同样注入垃圾但**拿掉测试保护** → 必须报红。"
            "缺这条，M4 的绿分不清是「清理生效」还是「垃圾没写进去」",
            expect_infra=False, expect_reason_has="test_patch 打不上",
            expect_error_code=2,
        )
    )

    return cases


def run_selftest(*, from_runs: bool = False) -> int:
    """跑四条反向自证。**镜像共享，成本 = 一次构建 + 5 个 trial，$0**。"""
    base = TASKS / SELFTEST_BASE
    if not base.exists():
        print(f"基线 task 不存在：{base}", file=sys.stderr)
        return 1

    print(f"T5 反向自证（基线 {SELFTEST_BASE}，四条变异 + 一个对照）\n")
    cases = _mutants(base, SELFTEST_DIR / "tasks")

    # 按门禁分批：同一个 agent 的变异体一次跑完
    by_gate: dict[str, list[lib.SelftestCase]] = {}
    for cs in cases:
        by_gate.setdefault(cs.gate, []).append(cs)

    verdicts: dict[str, list[lib.Verdict]] = {}
    rows: dict[str, list[lib.TrialRow]] = {}
    judges = {"oracle": lib.gate_oracle, "nop": lib.gate_nop}

    for gate, group in by_gate.items():
        out = SELFTEST_DIR / gate
        sub = SELFTEST_DIR / f"tasks-{gate}"
        if not from_runs:
            # harbor 的 `-p` 收「装着一堆 task 目录的目录」，所以按门禁建子目录
            import shutil

            if sub.exists():
                shutil.rmtree(sub)
            sub.mkdir(parents=True)
            for cs in group:
                (sub / cs.name).symlink_to((SELFTEST_DIR / "tasks" / cs.name).resolve())
            print(f"门禁 {gate}：{len(group)} 个变异体")
            run_harbor(gate, sub, out)
        r = load_dir(out)
        rows[gate] = r
        verdicts[gate] = judges[gate](r)

    outcomes = lib.check_selftest(cases, verdicts, rows)
    write_selftest_report(outcomes)

    bad = [o for o in outcomes if not o.ok]
    for o in outcomes:
        print(f"  {'✅' if o.ok else '🔴'} {o.case.name}：{o.detail}")
    print(f"\n反向自证：{len(outcomes) - len(bad)}/{len(outcomes)} 通过")
    return 1 if bad else 0


def load_dir(jobs_dir: Path) -> list[lib.TrialRow]:
    """读某个 jobs 目录最近一次 run（与 `load()` 同，但直接给路径）。"""
    run = lib.latest_run(jobs_dir)
    return [] if run is None else lib.collect_run(run)


def write_selftest_report(outcomes: list[lib.SelftestOutcome]) -> None:
    lines = [
        "# T5 反向自证（方案 §4 T5 的四条 + 一个对照）",
        "",
        "> 生成：`python3 scripts/t5-gate.py --selftest`",
        "> 机制：**故意破坏一处，然后要求门禁报红** —— 并核「红的理由对不对」，",
        "> 不只看红没红。理由错的红是假绿的一种（T4 交接 #6 的教训）。",
        "",
        "| 变异体 | 门禁 | 期望 | 结果 | 说明 |",
        "|---|---|---|---|---|",
    ]
    for o in outcomes:
        exp = "过" if o.case.must_pass else "报红"
        lines.append(
            f"| `{o.case.name}` | {o.case.gate} | {exp} | "
            f"{'✅ 符合' if o.ok else '🔴 不符合'} | {o.case.why} |"
        )
    bad = [o for o in outcomes if not o.ok]
    lines += ["", f"**{len(outcomes) - len(bad)}/{len(outcomes)} 通过**", ""]
    if bad:
        lines += ["## 不符合预期的", ""]
        lines += [f"- `{o.case.name}` —— {o.detail}" for o in bad] + [""]
    rp = c.MVP_REPORTS / "t5-selftest.md"
    rp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n报告 → {rp}")

def main() -> int:
    ap = argparse.ArgumentParser(description="T5 门禁")
    ap.add_argument(
        "--only",
        choices=["oracle", "nop", "oracle-k3"],
        help="只跑某一道门禁（分批时用）；不传则依次跑三道",
    )
    ap.add_argument(
        "--from-runs",
        action="store_true",
        help="不跑 harbor，只在既有产物上复算（$0）",
    )
    ap.add_argument(
        "--selftest",
        action="store_true",
        help="跑四条反向自证（方案 §4 T5）：故意破坏一处，要求门禁报红。"
        "与 --from-runs 可叠加（在既有变异体产物上复算）",
    )
    args = ap.parse_args()

    if args.selftest:
        return run_selftest(from_runs=args.from_runs)

    if not TASKS.exists():
        print(f"task 目录不存在：{TASKS}", file=sys.stderr)
        return 1
    n_tasks = len([p for p in TASKS.iterdir() if p.is_dir()])
    print(f"T5 门禁：{n_tasks} 条 task\n")

    todo = [args.only] if args.only else ["oracle", "nop", "oracle-k3"]
    summaries: dict[str, lib.GateSummary] = {}

    if "oracle" in todo:
        print("门禁① oracle（参考解必须全绿）")
        if not args.from_runs:
            run_harbor("oracle", TASKS, GATE_DIR / "oracle")
        summaries["oracle"] = summarize("oracle", load("oracle"), lib.gate_oracle)

    if "nop" in todo:
        print("\n门禁② nop（f2p 必须全红、p2p 必须全绿）")
        if not args.from_runs:
            run_harbor("nop", TASKS, GATE_DIR / "nop")
        summaries["nop"] = summarize("nop", load("nop"), lib.gate_nop)

    if "oracle-k3" in todo:
        print("\n门禁③ oracle -k 3（三次必须一致）")
        # 只在过了①②的存活集上跑 —— 见模块 docstring
        prior = {}
        for name, judge in (("oracle", lib.gate_oracle), ("nop", lib.gate_nop)):
            if name in summaries:
                prior[name] = summaries[name]
            else:
                rows = load(name)
                if rows:
                    prior[name] = lib.GateSummary(name=name, verdicts=judge(rows))
        if prior:
            alive = set.intersection(*(set(s.survivors) for s in prior.values()))
        else:
            alive = {p.name for p in TASKS.iterdir() if p.is_dir()}
        alive = sorted(alive)
        print(f"  存活集 {len(alive)} 条（①②的交集）")
        if not args.from_runs:
            if not alive:
                print("  存活集为空，跳过")
            else:
                run_harbor("oracle", build_survivor_dir(alive), GATE_DIR / "oracle-k3", k=3)
        summaries["oracle-k3"] = summarize("oracle-k3", load("oracle-k3"), lib.gate_consistency)

    if summaries:
        # 🔴 落盘前把**没在本次跑**但已有产物的门禁一并读进来（2026-09-10 修）。
        # 否则 `--only oracle-k3` 收尾时 summaries 只有 k3 一项，
        # `gate.jsonl` 会被覆盖成只剩 k3 的结论 —— 把前两道跑了 67 分钟的
        # 结果**静默抹掉**，报告还会写成「共 1/3 道」。
        # 形态是「命令报成功、产物悄悄不对」，与 T3 采样脚本的 ㊳㊴ 同源。
        for name, judge in (
            ("oracle", lib.gate_oracle),
            ("nop", lib.gate_nop),
            ("oracle-k3", lib.gate_consistency),
        ):
            if name in summaries:
                continue
            rows = load(name)
            if rows:
                summaries[name] = lib.GateSummary(name=name, verdicts=judge(rows))
                print(f"  （并入已有产物）{summaries[name].line()}")
        # 报告按门禁固定顺序呈现，不按跑的先后
        summaries = {
            k: summaries[k] for k in ("oracle", "nop", "oracle-k3") if k in summaries
        }
        write_outputs(summaries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
