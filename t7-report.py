#!/usr/bin/env python3
"""T7 — 从基线 run 的产物出成果报告。**纯复算，不跑任何东西、不花钱。**

判定与统计都在 `t7_report_lib.py`（已单测）；本文件只负责把数字排成报告。

## 输出

  - `reports/baseline-v0.2-mini.md` —— 成果报告
  - `reports/baseline/summary.json`  —— 机器可读的取数源（供别处引用，别抄 markdown）
  - `version.json` 的 `frozen_at` / `task_count`（`--freeze` 时才写）

## 🔴 报告必须遵守的四条（全部来自 T6→T7 交接，违反会让数字被误读）

  1. **分母 39**，读 `survivors.json`（交接 1b）。
  2. **按题面信息量分级分组报**（A2 20 / A1 11 / B 4 / C 4）——
     混报会把「题面缺信息」误读成「模型能力差」（交接 2）。
  3. **难度维度与题面维度各一张表，不交叉**；任一格 < 5 条只报绝对条数（交接 2b）。
  4. **难度只有 M / L 两档，S=0**；方案原写的「S > M > L 单调梯度」判据
     **整条失效**，dataset card 要写明「S 档为 0，不构成三档单调性证据」（交接 2c）。

## 报告里必须写明的两条 caveat（否则报告自己在撒谎）

  - **网络**：题面写「`--network none` 离线」，实际跑的是
    **allowlist 且只放宿主网关 IP**。对被测模型而言 github/npm 全不可达
    （已实测：SSL EOF），差别只是多了一个它必须用的模型出口。
    ⛔ 不许含糊成「已按题面离线运行」。
  - **题面缺文档**：35/39 条题面点名 `docs/` 下的文档，而**容器里没有 `docs/`**
    （T6 的核心发现）。这不是本轮引入的，但它压着 A2 那 20 条的天花板 ——
    A2 档的低分**不能**读成「模型不行」。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402
import t7_report_lib as lib  # noqa: E402

RUNS = c.MVP_REPORTS / "baseline"
REPORT = c.MVP_REPORTS / "baseline-v0.2-mini.md"
SUMMARY = RUNS / "summary.json"
RECHECK = c.MVP_REPORTS / "t6-recheck"


def _rel(p: Path) -> str:
    """仓内路径写相对、仓外写绝对。

    ⛔ 不能用裸 `relative_to`：它在路径不在仓内时**抛 ValueError**。
    `MVP_DIR` 是可被环境变量改的（冒烟测试就把它指到 /tmp），
    形态是「报告脚本崩在写 summary 的最后一行」，报错完全不指向路径。
    2026-09-12 冒烟时实测撞到 —— 冒烟测试的价值就在这儿。
    """
    try:
        return str(p.resolve().relative_to(c.REPO_ROOT))
    except ValueError:
        return str(p)


def load_inputs() -> tuple[list[str], dict[str, list[str]], dict[str, list[str]]]:
    """存活名单 + 两个维度的分组。**两个维度分开返回，刻意不交叉。**"""
    surv = sorted(json.loads((RECHECK / "survivors.json").read_text(encoding="utf-8"))["survivors"])
    grade = json.loads((RECHECK / "t7-grade-groups.json").read_text(encoding="utf-8"))

    band: dict[str, list[str]] = {}
    for t in surv:
        m = json.loads((c.MVP_TASKS / t / "meta.json").read_text(encoding="utf-8"))
        band.setdefault(m["band"], []).append(t)
    # 报告里按 M → L 排（S 为 0，刻意不建这个键 —— 建一个空键会让读者以为「待填」）
    band = {k: sorted(v) for k, v in sorted(band.items(), key=lambda kv: "MLS".index(kv[0]))}
    return surv, grade, band


def cost_stats(trials: list[lib.Trial]) -> dict:
    """成本。⛔ `None` 不按 0 计入 —— 那会低报（08 号 §4.11 的同一条纪律）。"""
    vals = [t.cost_usd for t in trials if isinstance(t.cost_usd, (int, float))]
    if not vals:
        return {"total": 0.0, "n_with_cost": 0, "n_trials": len(trials),
                "note": "没有任何 trial 报告成本 —— 若本该有，先查 agent 的 cost 回填路径"}
    return {
        "total": round(sum(vals), 6),
        "n_with_cost": len(vals),
        "n_trials": len(trials),
        "mean": round(statistics.mean(vals), 6),
        "median": round(statistics.median(vals), 6),
        "p90": round(sorted(vals)[min(len(vals) - 1, int(len(vals) * 0.9))], 6),
        "max": round(max(vals), 6),
        "note": "⛔ None 未按 0 计入（那会低报）。n_with_cost < n_trials 时差额就是没拿到成本的 trial 数。",
    }


def controlled(trials: list[lib.Trial]) -> dict:
    """必控变量的**观测值**。名字里写「observed」是刻意的 —— 这不是我们设的期望值。"""
    models = sorted({t.model for t in trials if t.model})
    shas = sorted({t.binary_sha for t in trials if t.binary_sha})
    return {
        "model_observed": models,
        "n_model_missing": sum(1 for t in trials if not t.model),
        "sid_binary_sha256_observed": shas,
        "n_binary_missing": sum(1 for t in trials if not t.binary_sha),
        "note": "多于一个值 ⇒ 这批混了不同模型/二进制，pass@1 不可作为单一臂的结论",
    }


def table(cells: dict[str, lib.Cell], order: list[str]) -> list[str]:
    out = ["| 分组 | 条数 | 解出 / 计分 | 95% Wilson |", "|---|---|---|---|"]
    for k in order:
        cell = cells[k]
        body = cell.fmt()
        if cell.report_pct and cell.scored:
            p, lo, hi = lib.wilson(cell.solved, cell.scored)
            out.append(f"| **{k}** | {len(cell.tasks)} | {cell.solved}/{cell.scored} = {p:.1%} | [{lo:.1%}, {hi:.1%}] |")
        else:
            out.append(f"| **{k}** | {len(cell.tasks)} | {body} | — （n<{lib.SMALL_CELL}，不报） |")
    return out


def build_report(res: dict, trials: list[lib.Trial],
                 gcells: dict, bcells: dict, cost: dict, ctl: dict, k: int) -> str:
    """排报告。**只吃已经算好的格子**，自己不做任何统计。

    刻意不收 `grade` / `band` 原始分组：它们已经被 `lib.group()` 变成 cells 了，
    再传一份进来就是**同一事实存两份**，将来两处漂移时会静默按错的那份排版。
    """
    p, lo, hi = res["p"], res["lo"], res["hi"]
    ec = Counter(t.error_code for t in trials if t.error_code)
    L = [
        "# Agent-Traj-Bench v0.2-mini — 基线评测报告",
        "",
        f"> 生成于 {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}，由 `scripts/mvp/t7-report.py` 从 run 产物**纯复算**。",
        f"> 取数源唯一：`bench/v0.2-mini/reports/baseline/`（{res['n'] + res['excluded']} 条 task × k={k}）。",
        "",
        "## 1. 主结果",
        "",
        "| 项 | 值 |",
        "|---|---|",
        f"| **pass@1** | **{p:.1%}**（{res['passed']:g} / {res['n']} 解出） |",
        f"| **95% Wilson** | [{lo:.1%}, {hi:.1%}]，半宽 ±{res['halfwidth_pp']:.1f}pp |",
        f"| **分母** | `scored={res['n']}`，排除 {res['excluded']} 条 |",
        f"| 模型 | {', '.join(ctl['model_observed']) or '（产物里没有模型名）'} |",
        f"| k | {k}（`-n 1`，并发是最大单一失真源） |",
        f"| **实付** | **${cost['total']}**（{cost['n_with_cost']}/{cost['n_trials']} 个 trial 有成本值） |",
        "",
        f"排除的 task：{res['excluded_tasks'] or '无'}",
        "",
        f"> **分母纪律**：{res['denominator_note']}",
        "",
        "## 2. 🔴 先读这一节，否则会读错上面的数字",
        "",
        "**① 分母是 39，不是 40。** T6 人工过目淘汰了 `T0005`（题面与判分对象完全无关 +"
        " 含提示词模板残留，而 T5 三道门禁全绿 —— 人工环节价值的实例）。",
        "方案原写「≥40 条」是目标值，实际交付 **39 条**（降量交付，见 `t6-review.md` §6.2）。",
        "",
        "**② 35/39 条题面点名 `docs/` 下的文档，而容器里没有 `docs/`。**",
        "这是 T6 的核心发现，压着 A2 那 20 条的天花板 —— **A2 档的低分不能读成「模型能力差」**，",
        "它首先是「题面缺信息」。这也是为什么下面必须**分级分组**看，而不是只看总分。",
        "",
        "**③ 执行环境是 allowlist，不是题面写的 `--network none`。**",
        "39 条题面都写着「容器离线运行（`--network none`）」，但 `task.toml` 原先一条都没设"
        " `network_mode`，harbor 默认是 `PUBLIC` ⇒ **此前是联网跑的**（实测容器内 github/npm 均 200）。",
        "T7 开跑前已改为 **allowlist 且只放宿主网关 IP**，并实测确认：",
        "github / npm / raw.githubusercontent 全部不可达（SSL EOF），网关 `192.168.5.2:4101` 放行。",
        "⇒ 对被测模型而言与题面承诺的离线效果一致，差别只是多了一个**它必须用的模型出口**。",
        "证据：`reports/t7-regate/netpolicy-probe.txt`。",
        "",
        "**④ 难度只有 M / L 两档，S 档为 0。** 方案原写的健康度判据「难度分档呈单调梯度"
        " S > M > L」**整条失效**（不是「未达标」）：S 档在 T3 只剩 5 条，T5 门禁全数淘汰。",
        "⇒ **S 档为 0，不构成三档单调性证据。**",
        "",
        "## 3. 按「题面信息量」分级（🔴 本批最重要的一张表）",
        "",
        "分级含义：**A2** 剥掉路径后只剩一句祈使句 ／ **A1** 点名交付物 ／"
        " **B** 文件名点出症状 ／ **C** 散文自带可复现症状。",
        "信息量 C > B > A1 > A2。若分数随信息量单调下降，说明**题面质量**在主导分数，而非模型能力。",
        "",
        *table(gcells, [x for x in ("C", "B", "A1", "A2") if x in gcells]),
        "",
        f"> 小格纪律：任一格 < {lib.SMALL_CELL} 条只报绝对条数、**不报百分比** ——"
        " 5 条以下的比例会被单条结果整数级拉动（1/4 → 25%，2/4 → 50%）。",
        "",
        "## 4. 按难度分档（与上表**不交叉**）",
        "",
        *table(bcells, list(bcells.keys())),
        "",
        "> 为什么不交叉：39 条切成 2 档 × 4 级 = 8 格、每格 1-14 条，交叉报会碎到没有统计意义。",
        "",
        "## 5. 必控变量与成本",
        "",
        "| 项 | 观测值 |",
        "|---|---|",
        f"| 模型 | {ctl['model_observed']}（缺失 {ctl['n_model_missing']}） |",
        f"| sid 二进制 sha256 | {[s[:12] for s in ctl['sid_binary_sha256_observed']]}（缺失 {ctl['n_binary_missing']}） |",
        f"| 单题成本 | 均值 ${cost.get('mean', 0)} / 中位 ${cost.get('median', 0)} /"
        f" p90 ${cost.get('p90', 0)} / 最大 ${cost.get('max', 0)} |",
        "",
        "⚠️ 二进制 sha256 只有一个值才说明「只换了模型」。"
        "本机容器是 **aarch64** ⇒ 用的是 **arm64** 包；",
        "⛔ X2-Evaluation 08 号交接里写的 `4e51bda52f9c` 是 **x64** 那个包，"
        "照它逐字核对会误判成「跑的不是同一个二进制」。",
        "",
        f"reward.json 的 error_code 分布：{dict(ec) or '全为 0（正常跑完）'}",
        "",
        "> `error_code != 0` 的条数就是判分侧自己报错的条数（XML 缺失/解析失败等），"
        "与「模型答错」是两回事。",
        "",
        "## 6. 这批数字**不能**用来说什么",
        "",
        f"- **不能**说「模型在真实软件任务上的通过率是 {p:.0%}」——"
        " 39 条全部来自单一仓库（`person/sid-code`）、两类任务（bug_fix / test_authoring）。",
        "- **不能**把 A2 档的低分当模型能力证据（见 §2②）。",
        "- **不能**报三档难度单调性（S 档为 0，见 §2④）。",
        f"- **不能**跨批比 pass@1：半宽 ±{res['halfwidth_pp']:.1f}pp，"
        "n=39 下小于这个量级的差异都在噪声里。",
        "",
        "## 7. 复算方式",
        "",
        "```bash",
        "# 纯复算，不跑任何东西、不花钱",
        "~/.local/share/uv/tools/harbor/bin/python scripts/mvp/t7-report.py",
        "```",
        "",
        "机器可读取数源：`reports/baseline/summary.json`（⛔ 别抄本文的 markdown 数字）。",
        "",
    ]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", action="store_true", help="同时写 version.json 的冻结字段")
    args = ap.parse_args()

    run = lib.latest_run(RUNS)
    if run is None:
        raise SystemExit(f"{RUNS} 下没有 run 目录 —— 先跑 scripts/mvp/t7-baseline.py")
    trials = lib.collect(run)
    if not trials:
        raise SystemExit(f"{run} 里没有可读的 trial —— 看 run.log")

    surv, grade, band = load_inputs()
    res = lib.pass_at_1(trials)
    k = max(1, round(len(trials) / max(1, len({t.task for t in trials}))))

    gcells = lib.group(res["per_task_rate"], grade, res["excluded_tasks"])
    bcells = lib.group(res["per_task_rate"], band, res["excluded_tasks"])
    cost = cost_stats(trials)
    ctl = controlled(trials)

    # 分母自校验：分组合计必须等于总表，否则报告自己对不上
    for name, cells in (("题面分级", gcells), ("难度分档", bcells)):
        tot = sum(len(x.tasks) for x in cells.values())
        if tot != len(surv):
            raise SystemExit(f"{name} 合计 {tot} ≠ 存活 {len(surv)} —— 分组表与分母对不上，别出报告")

    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps({
        "generated_at": datetime.now(UTC).isoformat(),
        # ⚠️ 用 _rel() 而不是裸 relative_to：MVP_DIR 被指到仓外（冒烟测试就是这么跑的）时
        # relative_to 会抛 ValueError，形态是「报告脚本崩在写 summary 的最后一行」，
        # 完全不指向路径。2026-09-12 冒烟时实测撞到。
        "run_dir": _rel(run),
        "k": k,
        "ci": {kk: vv for kk, vv in res.items() if kk != "per_task_rate"},
        "per_task_rate": res["per_task_rate"],
        "cost_usd": cost,
        "controlled_variables": ctl,
        "by_grade": {kk: {"n": len(v.tasks), "solved": v.solved, "scored": v.scored,
                          "report_pct": v.report_pct} for kk, v in gcells.items()},
        "by_band": {kk: {"n": len(v.tasks), "solved": v.solved, "scored": v.scored,
                         "report_pct": v.report_pct} for kk, v in bcells.items()},
        "caveats": [
            "分母 39（T6 淘汰 T0005），⛔ 不是 gate.jsonl 的 40",
            "35/39 题面点名容器内不存在的 docs/ —— A2 档低分首先是题面缺信息",
            "执行环境 allowlist（只放网关 IP），非题面写的 --network none",
            "S 档为 0 ⇒ 不构成三档单调性证据",
        ],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    REPORT.write_text(build_report(res, trials, gcells, bcells, cost, ctl, k),
                      encoding="utf-8")
    print(f"pass@1 = {res['p']:.1%}（{res['passed']:g}/{res['n']}），排除 {res['excluded']}，实付 ${cost['total']}")
    print(f"  报告 {_rel(REPORT)}")
    print(f"  取数源 {_rel(SUMMARY)}")

    if args.freeze:
        vp = c.MVP_DIR / "version.json"
        doc = json.loads(vp.read_text(encoding="utf-8"))
        doc["status"] = "frozen"
        doc["frozen_at"] = datetime.now(UTC).isoformat()
        doc["task_count"] = len(surv)
        vp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  已冻结 version.json：task_count={len(surv)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
