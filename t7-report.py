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


#: Phase 0/1 的产物（漏斗前四级的取数源）。**只读**。
STAGING = c.REPO_ROOT / "data/bench-staging"

#: dataset card 的 Limitations —— 方案 §6 的 13 条（v1.3 起含 T4 新增的第 12/13 条）。
#: 🔴 第 2 / 4 / 5 条的措辞是 T4/T6 实测后**改过**的，不是方案原文，别回改：
#:   - 第 2 条：从「以某仓库为主」改成「**彻底**单仓库」（T4 之后 iam 5 条全被挡）
#:   - 第 4 条：写明「实测只有两类，另两类为 0」，⛔ 别写成「未过门禁」
#:     （门禁那层看到的 65 条里本就没有 feature_impl / refactor）
#:   - 第 5 条：写「S 档为 0」，⛔ 别写「锚点无效」（样本量为 0 ⇒ 锚点未被证伪也未被证实）
LIMITATIONS = [
    "**仅采用高置信切分单元**（2937/7692，38.2%）—— 低置信部分的切分债务**隔离未清**，"
    "是没用，不是修好了。",
    "🔴 **单一开发者、单一仓库**。原计划双仓库，T4 实测后 `ruijie/iam-studio-fe` 的 5 条"
    "**全部被挡**（见第 12 条），交付 39 条**全部**来自 `person/sid-code`。"
    "⛔ 这不是「以某仓库为主」，是**彻底**单仓库。"
    "定位是「真实生产交互衍生的补充 benchmark」，不是通用 SWE 基准。",
    "**自指污染**：sid-code 本身就是 coding agent，仓库含 SWE-bench 判分逻辑与 prompt 模板，"
    "约 14% commit 与 evals 相关。已用 `excluded-paths.txt` 强制排除四个前缀，但仍须披露。",
    "🔴 **任务类型覆盖窄**：交付 39 条实测**只有两类** —— `bug_fix` 18 / `test_authoring` 21。"
    "`feature_impl` 10 与 `refactor` 1 在 T1/T2 尚存，但 T3 生成的 65 条里已一条不剩"
    "（与另外 106 条一并未生成，未逐条归因）。⛔ 别写成「未过门禁」—— 门禁那层看到的 65 条里本就没有。"
    "且 `test_authoring` 占 21/39，须连带披露「测试自己测自己」的退化风险。",
    "🔴 **难度锚点是代理指标**：用 `edit_ops` 而非真实解题难度，**且 S 档实测为 0 条**，"
    "只剩 M 12 / L 27 两档 ⇒ **不构成三档单调性证据**。"
    "⛔ 不要写成「锚点无效」—— 样本量为 0 时锚点既未被证伪也未被证实，那是两回事。",
    "**样本量小、统计功效低**：n=39 的 pass@1 置信区间宽，模型间差异须谨慎解读 ——"
    "所以本报告每格都给 Wilson 区间，不只给点估计。",
    "**gold patch 来自轨迹反解，不是开发者真实 commit**。优点是自包含，"
    "缺点是可能不是最优解法。",
    "**无污染检测**：base_commit 早于多数模型训练截止，存在训练集污染可能。"
    "这一项**未做**，不假装做了。",
    "**base 快照不带 git 历史**：容器内是 `git init` 的单 commit，agent 看不到真实提交历史。"
    "副作用是消除了「翻 git log 找答案」的泄漏路径，但也偏离真实开发环境。",
    "**继承 harbor 的六类静默失效**（verifier 恒返值、双层超时互掩、并发失真等）。"
    "已按其判据设门禁（`-n 1`、reward 双源核对），但**不能声称已全部排除**。",
    "**单一执行环境**：只在本机 colima + arm64 上验证过。换 x64 或换 Docker 后端须重跑门禁，"
    "结果不保证可比。",
    "**5 条 task 因私有 registry 被排除**：`ruijie/iam-studio-fe` 的 `@ruijie/*` 依赖只存在于"
    "内网私服，公网 404，装它必须把 `_authToken` 烤进镜像 —— 违反「不在容器里配私钥」。"
    "🔴 这是**纪律决定而非技术障碍**（内网当时可达）。后果就是第 2 条的单仓库；"
    "将来有内网镜像或 vendored 方案时这 5 条可回归。",
    "**7 条 task 因 `src/ink/` 从未入库而不可复现**（T5 门禁① 淘汰）。"
    "这是**采集侧**问题：轨迹引用了从未提交进仓库的路径，反解出的 base 里自然没有它。"
    "v0.3 的动作是在 T1 筛选链里排除「引用未入库路径」的会话。",
    "🔴 **4 条题面的文件名点出了修法所需机制，这 4 条得分可能偏高**"
    "（`T0002` / `T0038` / `T0040` / `T0065`，取数 `meta.json` 的 "
    "`leakage.filename_specificity == \"mechanism\"`）。"
    "⛔ **不是 8 条** —— `reports/t6-recheck/filename-leak.json` 只做了"
    "「带信息 8 条 vs 仅主题 27 条」的粗二分，**没有 mechanism/symptom 这一层**；"
    "照它取会把 T6 明确判为「正常题面」的另 4 条 symptom 也算进来（T6 §4.2 的原话）。"
    "另有 4 条无文件名可判，回写为 `null`（**不是 `false`**）。",
    "**快照内有两处刻意保留的残余泄漏面**：① 62 条 external 分支在容器 `/eval-framework`"
    "（**`/repo` 之外**）放了 name/version/private 三键的 stub，用于闭合 "
    "`file:../eval-framework` 依赖；② 3 条 monorepo base 保留了 "
    "`packages/eval-framework/package.json`。"
    "**可证不参与判分**：两者都不含判分逻辑与测试代码，且容器内泄漏扫描零违规"
    "（扫描器另有 5/5 反向自证）。⛔ 不能只写「已剔除泄漏面」了事。",
]


def load_funnel() -> list[tuple[str, int | str, str]]:
    """漏斗表：从 8562 条冻结会话到 39 条可执行 task，每级都注明取数文件。

    ⛔ **不许写死数字**。每一级都从产物 JSON 现读 —— 写死会在上游重跑后静默过期，
    而漏斗表是报告的第一张表，读者拿它判断整批数据的可信度。

    ⚠️ 首级用 `batch-v0.2.json` 的 `session_count`（**8562**，冻结批次口径），
    ⛔ 不用 `repo_map.py` docstring 里的「8591 / CC 7132 / Codex 492 / sid-code 296」——
    那是**线上全量**的早期统计，三个分通道数合计 7920 ≠ 8591（不闭合），
    且与冻结批次不同口径。冻结批次的四通道
    （claude_code 7820 / codex 317 / short_id 248 / sid_code 177）合计精确等于 8562。
    照 8591 写会让报告第一行就对不上，且无法复算。
    """
    batch = json.loads((STAGING / "meta/batch-v0.2.json").read_text(encoding="utf-8"))
    filt = json.loads((STAGING / "phase1/meta/filtered-v2.stats.json").read_text(encoding="utf-8"))
    units = json.loads((STAGING / "phase1/meta/units-v2.stats.json").read_text(encoding="utf-8"))
    cand = json.loads(c.CANDIDATES_STATS.read_text(encoding="utf-8"))
    resolved = json.loads((c.MVP_META / "resolved.stats.json").read_text(encoding="utf-8"))
    tasks = json.loads((c.MVP_META / "tasks.stats.json").read_text(encoding="utf-8"))
    gate = [json.loads(x) for x in (c.MVP_META / "gate.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    surv = json.loads((RECHECK / "survivors.json").read_text(encoding="utf-8"))["survivors"]

    dist = batch["agent_source_dist"]
    chan = " / ".join(f"{k} {v}" for k, v in sorted(dist.items(), key=lambda kv: -kv[1]))
    # 合计闭合自检：不闭合就是取数源换了口径，别让它静默进报告
    if sum(dist.values()) != batch["session_count"]:
        raise SystemExit(f"⛔ 通道分布合计 {sum(dist.values())} ≠ session_count "
                         f"{batch['session_count']} —— 口径对不上，别出报告")

    # ① 两端 high 是方案写明的锚点（2937），从 T1 的 funnel 里现取而不是写死
    step1 = next((s["remaining"] for s in cand["funnel"] if s["step"].startswith("①")), "?")

    # ⚠️ 第 3 行数字**比第 2 行大**（4381 → 7692）：单位在这里从「会话」变成
    # 「任务单元」，一个会话可切多个单元（实测 1.762 个/会话，31.96% 的会话切出多段）。
    # 不标单位会让读者以为漏斗算错了 —— 漏斗表是报告第一张表，读者拿它判整批可信度。
    return [
        (f"冻结批次**会话**（四通道：{chan}）", batch["session_count"], "meta/batch-v0.2.json"),
        ("清洗后保留的**会话**（去空/过短/自指等）", filt["kept"], "phase1/meta/filtered-v2.stats.json"),
        (f"切分出的**任务单元**（⚠️ 换单位，{units['units_per_session']} 个/会话）",
         units["kept_units"], "phase1/meta/units-v2.stats.json"),
        ("其中两端边界均 high 置信的单元", step1, "meta/candidates.stats.json"),
        ("T1 候选（八级筛选后）", cand["n_candidates"], "meta/candidates.stats.json"),
        ("T2 反解出 base+patch", resolved["n_ok"], "meta/resolved.stats.json"),
        ("T3 生成 harbor task", tasks["n_tasks"], "meta/tasks.stats.json"),
        ("T5 三道门禁存活", sum(1 for r in gate if r["survives"]), "meta/gate.jsonl"),
        ("**T6 人工过目后交付**", len(surv), "reports/t6-recheck/survivors.json"),
    ]


def load_gate_rows() -> tuple[list[tuple[str, str, int, int]], dict[str, int]]:
    """门禁记录：三道门禁各拦下多少，以及淘汰归因分布。

    归因分布来自 `t6-review.md` §6.3 的表（**含 T5 的 26 条一并归类**）——
    那张表是人工归因的结论，无法从 JSON 机械重算，所以这里写常量但**注明出处**，
    并对总数做闭合自检：归因合计必须等于 65 - 39 = 26。
    """
    gate = [json.loads(x) for x in (c.MVP_META / "gate.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    n_oracle_ok = sum(1 for r in gate if r["oracle"]["ok"])
    n_nop_ok = sum(1 for r in gate if r["nop"]["ok"])
    k3 = [r for r in gate if r.get("oracle-k3")]
    rows = [
        ("① `oracle`（参考解必须能解出）", "gold patch 打上后 F2P 仍红 ⇒ 反解或测试选取有偏差",
         n_oracle_ok, len(gate) - n_oracle_ok),
        ("② `nop`（什么都不改必须解不出）", "nop 下 f2p=1 ⇒ 假 task，测试不改代码就绿",
         n_nop_ok, len(gate) - n_nop_ok),
        ("③ `oracle -k 3`（三次必须一致）", "三次结果不一致 ⇒ flaky，不可作为判分依据",
         sum(1 for r in k3 if r["oracle-k3"]["ok"]), sum(1 for r in k3 if not r["oracle-k3"]["ok"])),
    ]
    # 淘汰归因（出处：t6-review.md §6.3）
    attrib = {
        "`src/ink/` 从未入库 → 不可复现（T5 门禁①）": 7,
        "oracle reward=0，gold patch 打上后 F2P 仍红（T5 门禁①）": 12,
        "假 task：nop 下 f2p=1（T5 门禁②）": 4,
        "参考解自身缺陷 `gold_patch_regression` / `_broken`（T6 §1）": 2,
        "题面与判分对象无关 + 提示词模板残留（T6 §6.1）": 1,
    }
    n_elim = len(gate) - len(json.loads((RECHECK / "survivors.json").read_text(encoding="utf-8"))["survivors"])
    if sum(attrib.values()) != n_elim:
        raise SystemExit(f"⛔ 淘汰归因合计 {sum(attrib.values())} ≠ 实际淘汰 {n_elim} 条"
                         f"（{len(gate)} - 存活）—— 归因表已过期，先对回 t6-review.md §6.3")
    return rows, attrib


def health_checks(res: dict, bcells: dict) -> list[tuple[str, str, str]]:
    """健康度判据的逐条判定（方案 §9 三条，MVP 放宽后的口径）。

    🔴 第三条**整条失效**，不是「未达标」：S 档为 0 ⇒ 三档单调性无从谈起。
    ⛔ 不许走预案表「分档无梯度 ⇒ edit_ops 不是好锚点」那一行 ——
    样本量为 0 时锚点既未证伪也未证实，那是两回事（交接 2c）。
    """
    p = res["p"]
    out = []

    # ① 最强模型 pass@1 落在 20-80%（MVP 放宽自原方案 30-70%）
    ok1 = 0.20 <= p <= 0.80
    out.append((
        "① 最强模型 pass@1 ∈ [20%, 80%]",
        "✅ 达标" if ok1 else "🔴 **未达标**",
        f"实测 {p:.1%}。" + ("" if ok1 else
        "低于 20% ⇒ 按预案查「task 过难 or grader 有 bug」。"
        "本批已排除 grader 侧：T5 门禁① 44/65 条 oracle 能解出、"
        "T6 oracle 复检 reward=1.0，判分链路本身是好的 ⇒ 指向题面质量（§2②）而非 grader。"),
    ))

    # ② 最强与最弱模型差距 ≥10pp —— 单模型跑不出来，如实写「无法判定」
    out.append((
        "② 最强与最弱模型差距 ≥ 10pp",
        "⬜ **无法判定**",
        "本轮只跑了 1 个模型（deepseek-v4-1-flash），"
        "⛔ 这条判据**需要 ≥2 个模型**才能算。不是「达标」也不是「未达标」。",
    ))

    # ③ 难度三档单调梯度 —— 整条失效
    bands = {k: len(v.tasks) for k, v in bcells.items()}
    out.append((
        "③ ~~难度分档呈单调梯度 S > M > L~~",
        "🔴 **判据整条失效**",
        f"存活分布 {bands}，**S 档为 0** ⇒ 三档单调性无从谈起。"
        "⛔ 这不是「锚点无效」—— 样本量为 0 时 `edit_ops` 既未被证伪也未被证实。"
        "改报 M vs L 两档（§4）。",
    ))
    return out


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
    """排一张分组表。

    ⚠️ 多一列「覆盖」：格内有没跑 / 被排除的 task 时必须**当场看得见**，
    否则 `0/11` 读起来像「11 条全答错」而实际可能只跑了 1 条
    （2026-09-13 用中途产物实测撞到，见 `t7_report_lib.Cell` 的 docstring）。
    """
    out = ["| 分组 | 条数 | 解出 / 计分 | 95% Wilson | 覆盖 |", "|---|---|---|---|---|"]
    for k in order:
        cell = cells[k]
        cov = cell.coverage_note or "全跑齐"
        if cell.report_pct and cell.scored:
            p, lo, hi = lib.wilson(cell.solved, cell.scored)
            out.append(f"| **{k}** | {len(cell.tasks)} | {cell.solved}/{cell.scored} = {p:.1%} "
                       f"| [{lo:.1%}, {hi:.1%}] | {cov} |")
        else:
            out.append(f"| **{k}** | {len(cell.tasks)} | {cell.fmt()} "
                       f"| — （n<{lib.SMALL_CELL}，不报） | {cov} |")
    return out


def build_report(res: dict, trials: list[lib.Trial],
                 gcells: dict, bcells: dict, cost: dict, ctl: dict, k: int,
                 missing: list[str], n_surv: int,
                 funnel: list, gate_rows: list, attrib: dict, health: list,
                 fingerprint: str) -> str:
    """排报告。**只吃已经算好的格子**，自己不做任何统计。

    刻意不收 `grade` / `band` 原始分组：它们已经被 `lib.group()` 变成 cells 了，
    再传一份进来就是**同一事实存两份**，将来两处漂移时会静默按错的那份排版。

    `missing` / `n_surv` 只用来在首屏标红「未跑齐」—— 不参与任何统计。
    """
    p, lo, hi = res["p"], res["lo"], res["hi"]
    ec = Counter(t.error_code for t in trials if t.error_code)
    L = [
        "# Agent-Traj-Bench v0.2-mini — 基线评测报告",
        "",
        f"> 生成于 {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}，由 `scripts/mvp/t7-report.py` 从 run 产物**纯复算**。",
        f"> 取数源唯一：`bench/v0.2-mini/reports/baseline/`（{res['n'] + res['excluded']} 条 task × k={k}）。",
        "",
    ]
    if missing:
        L += [
            f"> 🔴🔴 **这不是终版报告：存活 {n_surv} 条里只跑了 {n_surv - len(missing)} 条，"
            f"{len(missing)} 条未跑。**",
            "> 下面每一个数字都只覆盖已跑的那部分，**不可引用、不可写进简历**。"
            "跑齐后重新生成（去掉 `--partial`）。",
            f"> 未跑：{', '.join(missing)}",
            "",
        ]
    L += [
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
        "## 6. 数据集是怎么来的（漏斗）",
        "",
        "每一级都注明取数文件，**可逐级复算**。⛔ 报告里所有数字都不是手写的。",
        "",
        "| 级 | 剩余 | 取数源 |",
        "|---|---|---|",
        *[f"| {name} | **{n}** | `{src}` |" for name, n, src in funnel],
        "",
        "> ⚠️ **第 3 行数字比第 2 行大不是笔误**：单位从「会话」变成「任务单元」，"
        "一个会话可切多个单元。",
        "> ⛔ 首级用冻结批次的 **8562**（`batch-v0.2.json`，指纹 "
        f"`{fingerprint}`）。"
        "早期文档里的「8591 / CC 7132 / Codex 492 / sid-code 296」是**线上全量**的另一口径，"
        "三个分通道合计 7920 ≠ 8591（不闭合），⛔ 不要引用。",
        "",
        "## 7. 这批 task 凭什么可信（三道门禁）",
        "",
        "**每一条 task 都过了三道机械门禁**，然后 **40 条 100% 人工过目**（非抽样）。",
        "",
        "| 门禁 | 拦的是什么 | 过 | 淘汰 |",
        "|---|---|---|---|",
        *[f"| {name} | {why} | {ok}/65 | {bad} |" for name, why, ok, bad in gate_rows],
        "",
        "淘汰归因（**含 T5 的 26 条一并归类**，出处 `t6-review.md` §6.3；"
        "合计已自检 = 65 − 39）：",
        "",
        "| 归类 | 条数 |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in attrib.items()],
        "",
        "> 🔴 **最后那 1 条是人工环节的价值实例**：`T0005` 三道机械门禁**全绿**，"
        "人工过目才发现它题面与判分对象完全无关且含提示词模板残留。"
        "⇒ 机械门禁不能替代人工过目。",
        "",
        "## 8. 健康度判据逐条对账",
        "",
        "方案 §9 的三条（MVP 已放宽口径）。**达标与否都如实写，不达标不改判据。**",
        "",
        "| 判据 | 结论 | 依据 |",
        "|---|---|---|",
        *[f"| {name} | {verdict} | {why} |" for name, verdict, why in health],
        "",
        f"## 9. 局限（{len(LIMITATIONS)} 条，主动披露）",
        "",
        "> 不写这一节，前面所有数字都会被一句「你怎么证明」问倒。",
        "",
        *[f"{i}. {x}" for i, x in enumerate(LIMITATIONS, 1)],
        "",
        "## 10. 这批数字**不能**用来说什么",
        "",
        f"- **不能**说「模型在真实软件任务上的通过率是 {p:.0%}」——"
        " 39 条全部来自单一仓库（`person/sid-code`）、两类任务（bug_fix / test_authoring）。",
        "- **不能**把 A2 档的低分当模型能力证据（见 §2②）。",
        "- **不能**报三档难度单调性（S 档为 0，见 §2④）。",
        f"- **不能**跨批比 pass@1：半宽 ±{res['halfwidth_pp']:.1f}pp，"
        "n=39 下小于这个量级的差异都在噪声里。",
        "- **不能**说「已按题面承诺离线运行」—— 实际是 allowlist（见 §2③）。",
        "",
        "## 11. 复算方式",
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
    ap.add_argument("--partial", action="store_true",
                    help="允许用跑批**中途**的产物出报告（会在报告首屏标红「未跑齐」）。"
                         "⛔ 不加这个开关时，跑批没跑齐就直接拒绝出报告")
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

    # 🔴 跑批完整性守卫：中途产物不许悄悄出终版报告。
    # 形态是「报告看起来完整、每张表都有数、pass@1 也算得出来」，
    # 只有分母悄悄小了一圈 —— 没有这道守卫谁都发现不了（2026-09-13 实测撞到）。
    missing = sorted(set(surv) - set(res["per_task_rate"]) - set(res["excluded_tasks"]))
    if missing and not args.partial:
        raise SystemExit(
            f"⛔ 跑批没跑齐：存活 {len(surv)} 条里有 {len(missing)} 条在这一轮产物里没有 trial。\n"
            f"   缺：{', '.join(missing[:8])}{' …' if len(missing) > 8 else ''}\n"
            f"   run={_rel(run)}\n"
            "   → 等跑批跑完再出报告；确实要看中途结果就加 --partial（报告会标红「未跑齐」）。"
        )
    if missing:
        print(f"⚠️ --partial：{len(missing)}/{len(surv)} 条未跑，报告首屏已标红，⛔ 不可作为终版结论")

    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps({
        "generated_at": datetime.now(UTC).isoformat(),
        # ⚠️ 用 _rel() 而不是裸 relative_to：MVP_DIR 被指到仓外（冒烟测试就是这么跑的）时
        # relative_to 会抛 ValueError，形态是「报告脚本崩在写 summary 的最后一行」，
        # 完全不指向路径。2026-09-12 冒烟时实测撞到。
        "run_dir": _rel(run),
        "k": k,
        # 🔴 完整性状态必须进机器可读取数源，不能只在 markdown 里标红 ——
        # 别处引用 summary.json 时看不到 markdown 的那行字。
        "complete": not missing,
        "coverage": {"n_survivors": len(surv), "n_with_trial": len(res["per_task_rate"]),
                     "n_missing": len(missing), "missing_tasks": missing},
        "ci": {kk: vv for kk, vv in res.items() if kk != "per_task_rate"},
        "per_task_rate": res["per_task_rate"],
        "cost_usd": cost,
        "controlled_variables": ctl,
        "by_grade": {kk: {"n": len(v.tasks), "solved": v.solved, "scored": v.scored,
                          "missing": v.missing, "excluded": v.excluded,
                          "report_pct": v.report_pct} for kk, v in gcells.items()},
        "by_band": {kk: {"n": len(v.tasks), "solved": v.solved, "scored": v.scored,
                         "missing": v.missing, "excluded": v.excluded,
                         "report_pct": v.report_pct} for kk, v in bcells.items()},
        "caveats": [
            "分母 39（T6 淘汰 T0005），⛔ 不是 gate.jsonl 的 40",
            "35/39 题面点名容器内不存在的 docs/ —— A2 档低分首先是题面缺信息",
            "执行环境 allowlist（只放网关 IP），非题面写的 --network none",
            "S 档为 0 ⇒ 不构成三档单调性证据",
        ],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    funnel = load_funnel()
    gate_rows, attrib = load_gate_rows()
    health = health_checks(res, bcells)
    fingerprint = json.loads(
        (STAGING / "meta/batch-v0.2.json").read_text(encoding="utf-8"))["fingerprint"][:12]

    REPORT.write_text(build_report(res, trials, gcells, bcells, cost, ctl, k, missing, len(surv),
                                   funnel, gate_rows, attrib, health, fingerprint),
                      encoding="utf-8")
    print(f"pass@1 = {res['p']:.1%}（{res['passed']:g}/{res['n']}），排除 {res['excluded']}，实付 ${cost['total']}")
    print(f"  报告 {_rel(REPORT)}")
    print(f"  取数源 {_rel(SUMMARY)}")

    if args.freeze:
        # 🔴 冻结是**不可逆的记录动作**：`frozen_at` 一写，这批就对外声称「定稿」。
        # ⛔ 中途产物绝不许冻结 —— 那等于把「跑了 5 条」的结论盖章成 39 条的定稿。
        # `--partial` 能绕过报告守卫，但**绕不过这里**，两道闸刻意分开。
        if missing:
            raise SystemExit(
                f"⛔ 拒绝冻结：{len(missing)}/{len(surv)} 条还没跑（--partial 只放行报告，不放行冻结）。\n"
                "   → 等跑批跑完、报告不带 --partial 生成成功后再冻结。"
            )
        vp = c.MVP_DIR / "version.json"
        doc = json.loads(vp.read_text(encoding="utf-8"))
        doc["status"] = "frozen"
        doc["frozen_at"] = datetime.now(UTC).isoformat()
        doc["task_count"] = len(surv)
        # T7 自己的进展也要落进 progress —— 前面 TZ/T0-T6 每一步都记了，
        # 少了 T7 这一格，version.json 就无法回答「基线是在什么条件下跑的」。
        doc.setdefault("progress", {})["T7"] = {
            "state": "done",
            "date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "artifacts": [
                "bench/v0.2-mini/reports/baseline-v0.2-mini.md",
                "bench/v0.2-mini/reports/baseline/summary.json",
                _rel(run),
            ],
            "gate": (f"pass@1={res['p']:.1%}（{res['passed']:g}/{res['n']}），"
                     f"分母 {len(surv)} 条，排除 {res['excluded']} 条，"
                     f"实付 ${cost['total']}"),
            "model": ctl["model_observed"],
            "k": k,
            # 🔴 两条必须随冻结一起留档的 caveat，否则日后无法复现这批数字的条件
            "network_policy": ("allowlist（只放宿主网关 IP），**非题面写的 --network none**；"
                               "对被测模型而言 github/npm 全不可达（实测 SSL EOF），"
                               "证据 reports/t7-regate/netpolicy-probe.json"),
            "known_caveat": ("35/39 条题面点名容器内不存在的 docs/（T6 核心发现）⇒ "
                             "A2 档 20 条的低分首先是题面缺信息，不可读作模型能力"),
        }
        vp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  已冻结 version.json：task_count={len(surv)}，progress.T7 已记录")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
