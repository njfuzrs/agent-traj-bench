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
import os
import statistics
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402
import t7_report_lib as lib  # noqa: E402

#: 取数源目录。默认是第一轮（作废）的 `baseline/`；整改后那批用 `--runs t8-rerun`。
#:
#: 🔴 **为什么做成开关而不是直接改常量**：`baseline/` 那批 0/39 的数据要留着，
#: 否则「整改前 vs 整改后」的对照就没有可执行的基线侧（同 t8-rerun 不改 t7-baseline 的理由）。
#: ⚠️ 报告文件名跟着取数源走 —— 两批写同一个 .md 会**静默覆盖**，
#: 而覆盖后文件里每张表都有数、看不出少了一批。
RUNS = c.MVP_REPORTS / "baseline"
REPORT = c.MVP_REPORTS / "baseline-v0.2-mini.md"
SUMMARY = RUNS / "summary.json"
RECHECK = c.MVP_REPORTS / "t6-recheck"

#: dataset card。⚠️ **不随 `--runs` 切**：card 描述的是「这个数据集是什么」，
#: 只有一份；报告才是「某一批跑出了什么」，一批一份。
#: 🔴 所以 card 里凡是引用某批读数的地方都必须**写明是哪一批** —— 见 `build_card()`。
CARD = c.MVP_DIR / "DATASET_CARD.md"


def _retarget(runs_name: str) -> None:
    """把取数源与产物路径整组切到另一批。

    ⛔ 三个全局必须一起改：只改 RUNS 会让报告读新批的 trial、
    却把 summary 写进旧批的目录，两侧都不报错。
    """
    global RUNS, REPORT, SUMMARY
    RUNS = c.MVP_REPORTS / runs_name
    SUMMARY = RUNS / "summary.json"
    REPORT = c.MVP_REPORTS / (
        "baseline-v0.2-mini.md" if runs_name == "baseline"
        else f"baseline-v0.2-mini-{runs_name}.md"
    )


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
# 🔴 P0-4：漏斗前三行的取数源原本是 tp 的 `data/bench-staging/`（4.4G，**从未入库**）
# ⇒ 公开仓照原样跑会直接 FileNotFoundError。现改读入库的 ~3.6KB 派生统计
# `meta/batch-v0.2.summary.json`（只收 card 真正用到的 6 个标量）。
#
# ⛔ 不整份搬 `batch-v0.2.json`：它含 8562 个会话 ID 与 6 个内网仓库名（4 个题集里没有）。
# ⚠️ `fingerprint` 在 summary 里是**抄录值**，不可从本仓复算 —— 原始会话未迁出。
# 若 STAGING_DIR 指向真实的 bench-staging，则优先用它（源仓侧复算走这条，保证两侧同数）。
STAGING = Path(os.environ["STAGING_DIR"]) if os.environ.get("STAGING_DIR") else None
BATCH_SUMMARY = c.MVP_META / "batch-v0.2.summary.json"


def _funnel_sources() -> tuple[dict, dict, dict]:
    """漏斗前三行的三个取数源 ⇒ `(batch, filtered, units)`。

    两条路径必须算出**同样的数**（阶段 5.3 的判据是逐字节 diff 两侧 card）：
      - `STAGING_DIR` 指向 tp 的 `data/bench-staging/` ⇒ 读原始三个文件
      - 否则（公开仓的默认）⇒ 读入库的 summary，字段名与原始保持一致
    """
    if STAGING is not None:
        return (
            json.loads((STAGING / "meta/batch-v0.2.json").read_text(encoding="utf-8")),
            json.loads((STAGING / "phase1/meta/filtered-v2.stats.json").read_text(encoding="utf-8")),
            json.loads((STAGING / "phase1/meta/units-v2.stats.json").read_text(encoding="utf-8")),
        )
    if not BATCH_SUMMARY.exists():
        raise SystemExit(
            f"⛔ 缺 {BATCH_SUMMARY} —— 漏斗前三行无从取数。\n"
            f"   公开仓应有这个文件；在 tp 侧跑请 export STAGING_DIR=<…>/data/bench-staging"
        )
    d = json.loads(BATCH_SUMMARY.read_text(encoding="utf-8"))
    return d, d["filtered"], d["units"]

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
    # ⚠️ `{n_conc}` 由 `_limitations(n_conc)` 按 run 产物填 —— ⛔ 不许写死 `-n 1`。
    # 「并发失真」正是本条自己点名的六类静默失效之一，写错并发数等于这条局限
    # 在陈述一个与 §1/§5 相反的执行条件。
    "**继承 harbor 的六类静默失效**（verifier 恒返值、双层超时互掩、并发失真等）。"
    "已按其判据设门禁（`-n {n_conc}`、reward 双源核对），但**不能声称已全部排除**。",
    "**单一执行环境**：只在本机 colima + arm64 上验证过。换 x64 或换 Docker 后端须重跑门禁，"
    "结果不保证可比。",
    # 🔴 2026-09-14 新增。⚠️ 整条由 `_excluded_limitation()` 按 run 产物生成 ——
    # 条目文案、task 名、成因分类**全部随数据走**，⛔ 一个字都不许写死：
    # 写死的形态是「下一批换了别的题被排除，而这条还在讲 T0009」。
    # 没有任何排除时这条**整条消失**（⛔ 不留「本批无排除」的空话占位）。
    "{excluded}",
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


#: 排除类判定 → 给读者的「下一棒会不会再撞上」说明。
#:
#: 🔴 分类的意义在于**结构性 vs 偶发**：前者换个模型重跑必然复现（题面本身装不进
#: 命令行），后者是链路抖动。两者混报的形态是「读者以为重跑一次就能补回来」。
_EXCLUDED_KIND = {
    "infra_agent_not_launched": (
        "**结构性**：题面超 Linux `MAX_ARG_STRLEN`（131,072 B，容器内实测 131,000 过 / "
        "131,060 起 `Argument list too long`）⇒ `bash -c` 拒绝 exec，agent **一个字没跑**"
        "（退出码 255），而 verifier 照常打分 ⇒ 假 0。"
        "🔴 **换模型重跑必然复现** —— 与模型能力无关，是题面装不进命令行。"
        "本批成因：单份内联文档 130,285 B（第二大的 2.1 倍，孤立离群）"
    ),
    "infra_upstream_disconnect": (
        "**偶发但本批两次都中**：上游 LLM 链路断连（`socket connection was closed "
        "unexpectedly`），verifier 照常打分 ⇒ 假 0。首轮 61 轮时断、补跑 24 轮又断"
    ),
}


def _excluded_limitation(excluded_tasks: list[str], n_surv: int,
                         zd: dict | None) -> str | None:
    """infra 排除那条局限 —— **整条按数据生成**，没有排除就返回 None。

    🔴 为什么必须有这一条：§1 已经写了「排除的 task：[...]」，但那是「本批发生了什么」；
    局限清单回答的是「**下一棒会再撞上什么**」。T0009 是结构性的 —— 换模型重跑还会撞，
    而在加这条之前，报告里没有任何一处说明这件事。

    ⚠️ 同时点破**两个分母**：39 条是 benchmark 规模，37 条才是参与计分的。
    引用方只看到「39 条 benchmark」+「pass@1 37.8%」会以为分母是 39
    （那样算出来是 35.9%，差 1.9pp —— 小到看不出，正因如此才要写明）。
    """
    if not excluded_tasks:
        return None
    verdicts = {t.get("task"): t.get("verdict")
                for t in ((zd or {}).get("trials") or [])}
    by_kind: dict[str, list[str]] = {}
    for t in excluded_tasks:
        by_kind.setdefault(verdicts.get(t) or "unknown", []).append(t)

    n_scored = n_surv - len(excluded_tasks)
    head = (f"🔴 **{len(excluded_tasks)} 条按 infra 排除出分母 ⇒ 分母是 {n_scored}，不是 {n_surv}**"
            f"（{', '.join(f'`{t}`' for t in excluded_tasks)}）。"
            f"「{n_surv} 条 benchmark」与「{n_scored} 条参与计分」是**两个数** ——"
            f"⛔ 别拿 {n_surv} 当 pass@1 的分母（那会把仪器故障记成答错）。")
    bits = [head]
    for kind, tasks in sorted(by_kind.items()):
        why = _EXCLUDED_KIND.get(kind)
        bits.append(
            f"　· {', '.join(f'`{t}`' for t in tasks)}（`{kind}`）："
            + (why if why else
               "⚠️ 本脚本没有这一类的成因说明 —— 先去 `t7-zero-diag.py` 补，"
               "⛔ 别让读者自己猜"))
    return "".join(bits)


def _limitations(n_conc: int, excluded: str | None = None) -> list[str]:
    """局限清单，把占位符换成本轮实际值。

    🔴 2026-09-14 抓到：第 10 条写死「已按其判据设门禁（`-n 1`）」，
    而本批实测跑的是 `-n 6`（`config.json` 的 `n_concurrent_trials`）。
    §1 与 §5 都如实写了 `-n 6`，只有这条还是旧值 ——
    而「**并发失真**」正是这条自己点名的六类静默失效之一，
    写错并发数等于这条局限在陈述一个与主表相反的执行条件。

    ⚠️ `{excluded}` 那条**没有排除时整条剔除**，⛔ 不留空话占位：
    留一句「本批无 infra 排除」会让清单的条数虚增，而条数是读者判断
    「披露得够不够细」的第一眼指标。所以 §11 的标题条数也必须跟着这里的
    **返回长度**算，⛔ 不能用 `len(LIMITATIONS)`（那个恒为 16，会与正文差 1）。
    """
    out = []
    for x in LIMITATIONS:
        if x == "{excluded}":
            if excluded:
                out.append(excluded)
            continue                     # 无排除 ⇒ 整条不输出
        out.append(x.replace("{n_conc}", str(n_conc)))
    return out


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
    batch, filt, units = _funnel_sources()
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


def load_gate_rows() -> tuple[list[tuple[str, str, int, int, int]], dict[str, int]]:
    """门禁记录：三道门禁各拦下多少，以及淘汰归因分布。

    归因分布来自 `t6-review.md` §6.3 的表（**含 T5 的 26 条一并归类**）——
    那张表是人工归因的结论，无法从 JSON 机械重算，所以这里写常量但**注明出处**，
    并对总数做闭合自检：归因合计必须等于 65 - 39 = 26。
    """
    gate = [json.loads(x) for x in (c.MVP_META / "gate.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    n_oracle_ok = sum(1 for r in gate if r["oracle"]["ok"])
    n_nop_ok = sum(1 for r in gate if r["nop"]["ok"])
    k3 = [r for r in gate if r.get("oracle-k3")]
    # 🔴 每行**带自己的分母**，⛔ 不许让渲染侧写死 `/65`。
    #
    # 2026-09-14 抓到：模板原本写死 `{ok}/65`，而门禁③（`oracle -k 3`）只在
    # 过了①②的那 40 条上跑 ⇒ 渲染成「过 40/65、淘汰 0」，读起来像
    # **25 条被③拦下却没进归因表**（归因表合计 26 条，且一条 flaky 都没有）。
    # 真相是 40/40 全过：③ 一条都没淘汰。分母混用让一张自证可信度的表自相矛盾。
    rows = [
        ("① `oracle`（参考解必须能解出）", "gold patch 打上后 F2P 仍红 ⇒ 反解或测试选取有偏差",
         n_oracle_ok, len(gate), len(gate) - n_oracle_ok),
        ("② `nop`（什么都不改必须解不出）", "nop 下 f2p=1 ⇒ 假 task，测试不改代码就绿",
         n_nop_ok, len(gate), len(gate) - n_nop_ok),
        ("③ `oracle -k 3`（三次必须一致，**只在过了①②的那些上跑**）",
         "三次结果不一致 ⇒ flaky，不可作为判分依据",
         sum(1 for r in k3 if r["oracle-k3"]["ok"]), len(k3),
         sum(1 for r in k3 if not r["oracle-k3"]["ok"])),
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


def fp_split(trials: list[lib.Trial]) -> dict:
    """F2P / P2P 两个分量分开统计（方案 §4 T7 第 2 项要求）。

    🔴 **为什么必须分开报**：`reward` 把两件事压成一个 0/1，而它们含义完全不同：

      - **F2P 红** = 没修好目标缺陷（该做的没做到）
      - **P2P 红** = **改出了回归**（把原本好的测试弄坏了）—— 这是**更严重**的信号，
        压进单个 reward 就彻底丢了

    ⚠️ P2P 只统计**参与计分**的 trial：infra 故障那些 `p2p` 可能是 None，
    按 0 计入会虚报「改出回归」（同 `cost_stats` 那条 None 不按 0 算的纪律）。
    """
    scored = [t for t in trials if not t.infra_failure]
    f2p_vals = [t.f2p for t in scored if isinstance(t.f2p, (int, float))]
    p2p_vals = [t.p2p for t in scored if isinstance(t.p2p, (int, float))]

    # 🔴 P2P < 1.0 有**两种完全不同的成因**，⛔ 不许都算成「改出回归」：
    #
    #   ① score-detail 的 p2p.error 为空 ⇒ 测试真跑了、真红了 ⇒ **改出了回归**
    #   ② p2p.error 是 `xml_missing` / `xml_parse_error` / `empty_file_list`
    #      ⇒ **判分侧没产出可读 XML**，那是仪器问题
    #
    # `score.py` 两种都返回 0.0。只看 `p2p < 1.0` 会把②报成①，
    # 而①是本报告标记的**最严重**信号（把本来绿的测试改红）——
    # 拿判分故障去指控模型改出回归，是同 §10 `grader_incomplete` 那条纪律
    # 在分量表这侧漏掉了一次（2026-09-14 追 T0036 时发现）。
    #
    # ⚠️ T0036 经逐条核实**确是真回归**：`truncateNotificationBody` 在 base 快照 0 次、
    # gold patch 0 次、模型工具调用 102 次 —— 模型自造符号并导出，
    # 导致 4 个 import 它的 p2p 文件加载失败。所以本条修复不改变它的判定。
    low_p2p = [t for t in scored if isinstance(t.p2p, (int, float)) and t.p2p < 1.0]
    regressed = sorted(t.task for t in low_p2p if not t.p2p_error)
    grader_p2p = sorted(f"{t.task}({t.p2p_error})" for t in low_p2p if t.p2p_error)
    return {
        "n_scored": len(scored),
        "f2p": {"n": len(f2p_vals), "n_full": sum(1 for v in f2p_vals if v >= 1.0),
                "mean": round(statistics.mean(f2p_vals), 4) if f2p_vals else None},
        "p2p": {"n": len(p2p_vals), "n_full": sum(1 for v in p2p_vals if v >= 1.0),
                "mean": round(statistics.mean(p2p_vals), 4) if p2p_vals else None},
        "regressed_tasks": regressed,
        # 判分侧故障导致的 p2p=0 单列 —— ⛔ 不混进 regressed_tasks
        "grader_p2p_failures": grader_p2p,
        "note": ("F2P 红 = 没修好目标缺陷；P2P 红 = **改出了回归**（更严重）。"
                 "⛔ 压进单个 reward 就丢了这个区分。"
                 "None 不按 0 计入 —— 那会虚报「改出回归」。"
                 "p2p=0 但 score-detail 有 error 码（xml_missing 等）的单列 "
                 "grader_p2p_failures —— 那是判分侧没产出 XML，⛔ 不是回归。"),
    }


def _error_code_note(ec, zd: dict | None) -> list[str]:
    """§5 `error_code` 分布下面那句注释 —— ⛔ 不许无条件说「与模型答错是两回事」。

    🔴 2026-09-14 抓到的**跨节矛盾**：这句原文写死「`error_code != 0` 就是判分侧
    自己报错，与『模型答错』是两回事」。而本批那 2 条（T0039 / T0049，都是
    `error_code=4` = `xml_missing`）经 §10 逐条核实是 `true_zero_missing_symbol`：

      测试**跑起来了**，但 import 的 src 符号正是 gold patch 要创建的、
      模型没写出来 ⇒ 文件加载失败 ⇒ bun 不写 XML ⇒ error_code=4。

    也就是说 `xml_missing` 的成因可以是**模型没写出符号**（真 0、能力信号），
    ⛔ 不能一律读成判分缺陷。§10 判「是能力信号」而 §5 说「与答错是两回事」，
    同一份报告对同一批 task 给出两个相反的判定。

    所以这句改为：先说 error_code 的字面含义，再交叉引用 §10 的**实际判定**。
    """
    if not ec:
        return ["> 全部 `error_code = 0` ⇒ 判分侧没有自报错误。"]

    lines = [
        "> `error_code != 0` 表示**判分侧没产出可读的 XML**"
        "（4=`xml_missing` / 5=`xml_parse_error` / 3=`empty_file_list`）。",
        "> ⛔ 但这**不等于**「判分缺陷、与模型答错无关」——"
        "`xml_missing` 的成因也可能是**模型没写出被 import 的 src 符号**"
        "（文件加载失败 ⇒ bun 不写 XML），那是**真 0**。",
    ]
    v = (zd or {}).get("verdicts") or {}
    n_ms = v.get("true_zero_missing_symbol", 0)
    n_gi = v.get("grader_incomplete", 0)
    if zd is None:
        lines.append("> → 本批未做真 0/假 0 归因 ⇒ **无法判定**这些条属于哪一类，见 §10。")
    else:
        lines.append(
            f"> → 本批 §10 已逐条核实：`true_zero_missing_symbol` {n_ms} 条"
            f"（**真 0**，模型没写出 gold patch 创建的符号）、"
            f"`grader_incomplete` {n_gi} 条（**判分侧没看全**，⛔ 不可读作答错）。"
            + ("" if n_gi else " ⇒ 本批没有一条是判分缺陷。"))
    return lines


def _fp_section(fp: dict | None) -> list[str]:
    """§6 F2P / P2P 分量表。"""
    if not fp:
        return ["## 6. F2P / P2P 两个分量（⛔ 不压成单个 reward）", "",
                "🔴 **未算出分量** —— `fp_split()` 没拿到数据，先查 reward 取值路径。", ""]
    f, p = fp["f2p"], fp["p2p"]
    n = fp["n_scored"]
    reg = fp["regressed_tasks"]
    lines = [
        "## 6. F2P / P2P 两个分量（⛔ 不压成单个 reward）",
        "",
        "`reward` 把两件事压成一个 0/1，而它们含义完全不同 ——"
        "**F2P 红 = 没修好目标缺陷；P2P 红 = 改出了回归**（更严重的信号）。",
        "",
        "| 分量 | 含义 | 满分条数 | 均值 |",
        "|---|---|---|---|",
        f"| **F2P** | 目标缺陷的测试（要从红转绿） | {f['n_full']}/{f['n']} | "
        f"{f['mean'] if f['mean'] is not None else '—'} |",
        f"| **P2P** | base 时点本来全绿的测试（不许弄坏） | {p['n_full']}/{p['n']} | "
        f"{p['mean'] if p['mean'] is not None else '—'} |",
        "",
        f"分母是参与计分的 {n} 条（infra 故障不计入 —— `None` 按 0 算会**虚报**「改出回归」）。",
        "",
    ]
    if reg:
        lines += [
            f"🔴 **{len(reg)} 条 P2P 未满分且判分正常 ⇒ 模型改出了回归**：{', '.join(reg)}。",
            "> 这比 F2P 红更值得看：说明改动破坏了原本通过的测试。",
        ]
    else:
        lines += [
            "✅ **没有任何一条判分正常的 P2P 未满分 ⇒ 未观测到回归。**",
        ]
        # ⛔ 不许写死「结合 F2P 全红 ⇒ 模型压根没改文件」——
        # 那是 baseline 批的形态。本批 F2P 有满分条目，那句话会与 §4 主表打架。
        if f["n_full"] == 0:
            lines += [
                "> 结合 F2P 全红，形态是「模型没能修好，但也没弄坏别的」——"
                "与 §10 归因的「模型压根没改文件」一致（没改自然不会有回归）。",
            ]
        else:
            lines += [
                f"> 注意 F2P 有 {f['n_full']}/{f['n']} 条满分 ⇒ ⛔ **不可**读作"
                "「模型没动手」：它改了、改对了一部分，且没弄坏原本通过的测试。",
            ]

    # 判分侧故障导致的 p2p=0 单独说 —— ⛔ 混进「改出回归」是拿仪器问题指控模型
    gp = fp.get("grader_p2p_failures") or []
    if gp:
        lines += [
            "",
            f"⚠️ 另有 **{len(gp)} 条 P2P = 0 源于判分侧故障，⛔ 不是回归**：{', '.join(gp)}。",
            "> `score.py` 在 `xml_missing` / `xml_parse_error` / `empty_file_list` 时"
            "同样返回 0.0（那是**没产出可读 XML**，不是「测试被改红」）。"
            "把它算成回归等于拿仪器问题指控模型 —— 同 §10 `grader_incomplete` 的纪律。",
        ]
    return lines + [""]


_INLINE_MARK = "## 引用文档原文"


def _run_meta() -> dict:
    """该批 run 的元数据 —— run 目录未入库时的唯一来源（见 `reports/<批次>/trials.json`）。

    🔴 这三件事**都是批次特异的**，⛔ 不许写死、也不许回落到「看着合理」的默认值：
      - `n_concurrent_trials`：baseline 是 1、t8-rerun 是 6。回落 1 等于**谎报必控变量**。
      - `batch_inlines`：baseline 跑在修复① 之前，题面 0 条内联；t8-rerun 的 stage 内联 34/39。
      - `dataset_dir_rel`：baseline 指 `reports/baseline/survivors`、t8-rerun 指 `reports/t8-rerun/tasks`。
    """
    p = RUNS / "trials.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8")).get("run_meta") or {}


#: 本仓的脚本目录与题集目录（相对仓库根）。
#
# 🔴 ⛔ 不许把 `scripts/mvp/` 或 `bench/v0.2-mini/tasks` 写进报告字符串 ——
# 那是 trajectory-platform 的布局。公开仓拆出来后脚本在 `scripts/`、题集在仓库根，
# 写死的形态是**报告里每条命令都指向一个不存在的路径**，而报告本身看着完全正常。
# 从实际布局现推 ⇒ 两个仓各自生成各自正确的路径（§5.5）。
SCRIPTS_REL = _rel(Path(__file__).resolve().parent)
TASKS_REL = _rel(c.MVP_TASKS)


def _rel_run(run_dir: Path | None) -> str:
    """报告/summary 里的 run 目录字段。

    ⚠️ 公开仓的 run 目录未入库（run_dir 为 None）⇒ **照实写取数源是 trials.json**，
    ⛔ 不许编一个看着像真的 run 路径出来：那会让读者以为 clone 下来就有 harbor 产物，
    照它去核对只会得到「目录不存在」，而 card 顶行还写着「纯复算」。
    """
    if run_dir is not None:
        return _rel(run_dir)
    meta = _run_meta()
    dirs = meta.get("run_dirs") or []
    src = _rel(RUNS / "trials.json")
    return f"{src}（派生自未入库的 run 目录 {', '.join(dirs) or '未记录'}）" if dirs else src


def _dataset_dirs() -> list[Path]:
    """本批各 run 实际用的题源目录（从 run 的 `config.json` 现读）。

    ⚠️ 这是**批次特异**的：baseline 批指向 `reports/baseline/survivors`，
    整改后那批指向 `reports/t8-rerun/tasks`。⛔ 不许写死任何一个。
    """
    out: list[Path] = []
    if not RUNS.exists():
        return out
    runs = sorted(q for q in RUNS.iterdir() if q.is_dir() and q.name[:2] == "20")
    if not runs:
        # 公开仓：run 目录未入库 ⇒ 用 trials.json 记下的 stage 路径。
        # ⚠️ 该目录本身也未入库（stage 是跑批时复制出来的）⇒ 通常不存在，
        # 于是 `_batch_inlines()` 的判据① 命中不了，改走那边的 run_meta 回落。
        rel = _run_meta().get("dataset_dir_rel")
        return [c.REPO_ROOT / rel] if rel else out
    for run in runs:
        cfg = run / "config.json"
        if not cfg.exists():
            continue
        try:
            doc = json.loads(cfg.read_text(encoding="utf-8"))
        except Exception:
            continue
        for ds in doc.get("datasets") or []:
            d = Path(ds.get("path") or "")
            if d.is_dir() and d not in out:
                out.append(d)
    return out


def _batch_inlines() -> bool:
    """这一批的题面到底有没有内联文档原文 —— 从**该批自己的产物**判定。

    🔴 2026-09-14 自查抓到我引入的回归：内联**条数**改从 `docs-index.json` 取
    （见 `_n_inlined`）之后，那个文件不随 `--runs` 变 ⇒ `--runs baseline`
    也会报「34/39 条已内联」，而 baseline 批跑在修复① **之前**，
    题面实测 **0 条**内联。那份报告会声称与事实完全相反的结论。

    判据两路，任一命中即算内联：
      ① 该批 run 的 dataset 目录里现存的题面含内联段（便宜、直接）
      ② 兜底扫 trial 的 agent 日志 —— `--resume` 会把 stage 重建成只剩待跑的
         几条，万一那几条恰好都不内联，①会误判成「整批没内联」。
         agent 日志是**每条 trial 各自的**，补跑不动已跑那些。
    """
    # ⓿ 公开仓：run 产物（stage 题面 + agent 日志）都未入库 ⇒ 两条判据都命中不了，
    # 会把 t8-rerun 误报成「整批没内联」⇒ card 的内联条数塌成 0/39。
    # 改读 trials.json 里记下的该批事实（⛔ 它是**批次特异**的，不是全局常量）。
    meta = _run_meta()
    if "batch_inlines" in meta and not RUNS.exists():
        return bool(meta["batch_inlines"])
    if "batch_inlines" in meta and not any(
            q.is_dir() and q.name[:2] == "20" for q in RUNS.iterdir()):
        return bool(meta["batch_inlines"])

    for d in _dataset_dirs():
        if not d.exists():
            continue
        for ins in sorted(d.glob("*/instruction.md")):
            if _INLINE_MARK in ins.read_text(encoding="utf-8", errors="replace"):
                return True

    # ② 兜底：trial 的 agent 日志里找题面回显（逐行扫，命中即停）
    if RUNS.exists():
        for run in sorted(q for q in RUNS.iterdir() if q.is_dir() and q.name[:2] == "20"):
            for jl in sorted(run.glob("T0*/agent/sid-code.jsonl")):
                try:
                    with jl.open(encoding="utf-8", errors="replace") as fh:
                        for line in fh:
                            if _INLINE_MARK in line:
                                return True
                except OSError:
                    continue
    return False


def _n_inlined() -> tuple[int, int]:
    """本批有多少条题面内联了被点名文档的原文 ⇒ `(内联数, 存活数)`。

    🔴 两个来源各管一半，⛔ 不许只用其中一个：

      - **是否内联** → `_batch_inlines()`，从该批自己的 run 产物判定。
        只看 `docs-index.json` 会让 baseline 批（跑在修复① 之前、题面 0 条内联）
        也被报成「34/39 已内联」—— 那个文件不随 `--runs` 变。
      - **内联条数** → `docs-index.json`（修复① 的输入）。
        ⛔ 不数 `RUNS/tasks` 下的题面：`t8-rerun.py --resume` 会把 stage
        **重建成只剩待跑的那几条**，补跑 T0009 + T0022 之后 stage 只有 2 个目录
        ⇒ 会说「本批 **2/2** 条题面内联」，而真实是 34/39。
        形态是**终版报告带着一个凭空缩小的分母**，且它看着完全正常。

    已逐条核对：`docs-index.json` 判定可内联的 34 条与 stage 实际内联的 34 条完全一致。

    ⚠️ 与 `t8-rerun.build_instruction()` 同口径：只认 `channel in ("lake", "mirror")`
    的条目（那才是真取到了正文）。
    """
    surv = json.loads(
        (RECHECK / "survivors.json").read_text(encoding="utf-8"))["survivors"]
    if not _batch_inlines():
        return 0, len(surv)
    idx_p = c.MVP_REPORTS / "t8-fix/docs-index.json"
    if not idx_p.exists():
        return 0, len(surv)
    idx = json.loads(idx_p.read_text(encoding="utf-8"))
    n = sum(1 for t in surv
            if any(e.get("channel") in ("lake", "mirror")
                   for e in ((idx.get(t) or {}).get("docs") or [])))
    return n, len(surv)


def _n_no_attempt(zd: dict) -> int:
    """`true_zero_no_attempt` 的条数。**键缺失 ⇒ 0，⛔ 不是「未判定」**。

    🔴 2026-09-14 抓到（我自己引入的）：`verdicts` 是 `dict(Counter(...))` ——
    **计数为 0 的判定键根本不存在**。用 `.get(key)` 拿到 `None` 后当成
    「缺 zero-diag.json」，报告就会写「无法断言 A2 低分是能力还是题面」，
    而真相恰恰相反：该项为 0 正是「0 分的题全都改过文件」⇒ **A2 低分是真能力信号**
    这条结论的关键证据。两个读法的结论完全相反。

    `t7-zero-diag.py` 的 `_guard_text` 用的就是 `.get(..., 0)`，两侧必须同口径。
    """
    return (zd.get("verdicts") or {}).get("true_zero_no_attempt", 0)


def _a2_dont_say(zd: dict | None) -> str:
    """§12「这批数字不能用来说什么」里关于 A2 的那条 —— 与 §2② 同源。

    🔴 修复① 内联文档后这条**方向反转**：原本「不能当能力证据」，
    现在归因实测 `true_zero_no_attempt = 0` ⇒ 它就是能力读数，
    反而「不能再用题面缺信息解释掉」。写死会让 §12 与 §2② 自相矛盾。
    """
    n_inl, _ = _n_inlined()
    if not n_inl:
        return "**不能**把 A2 档的低分当模型能力证据"
    if zd is None:                       # ⚠️ 判据是**文件不存在**，⛔ 不是某个键缺失
        return "**不能**断言 A2 档低分的性质（缺 `zero-diag.json`，判据是 true_zero_no_attempt）"
    na = _n_no_attempt(zd)
    if na == 0:
        return ("**不能**再用「题面缺 `docs/`」解释 A2 档的低分 —— "
                "本批已内联文档且 0 分的题全都改过文件")
    return f"**不能**把 A2 档的低分全当能力证据（{na} 条是零仓库写 = 拒绝瞎改）"


def _docs_gap_caveat(zd: dict | None) -> str:
    """summary.json 里「题面缺 docs/」那条 caveat —— 与 §2② 同一判据，⛔ 不写死。

    两处必须同源：markdown 说「已消除」而 summary.json 说「首先是题面缺信息」，
    引用 summary.json 的下游就会拿到与报告相反的结论，且没人会发现。
    """
    n_inl, n_tasks = _n_inlined()
    if not n_inl:
        return "35/39 题面点名容器内不存在的 docs/ —— A2 档低分首先是题面缺信息"
    if zd is None:                       # ⚠️ 只有**文件不存在**才算未判定
        tail = "；缺 zero-diag.json ⇒ A2 低分性质未判定"
    else:
        na = _n_no_attempt(zd)
        tail = ("；true_zero_no_attempt=0 ⇒ A2 低分是真能力信号" if na == 0
                else f"；true_zero_no_attempt={na} ⇒ A2 低分仍混有题面因素")
    return (f"修复①已内联文档：{n_inl}/{n_tasks} 条题面含被点名文档原文，"
            f"「题面缺 docs/」不再是低分解释{tail}")


def _docs_gap_para(zd: dict | None) -> list[str]:
    """§2② 「题面缺 docs/」这条 caveat —— ⛔ **不许写死**，按本批实际形态生成。

    🔴 2026-09-14 抓到：这段原文写死「35/39 条题面点名 `docs/`，而容器里没有 `docs/`
    ⇒ A2 档的低分不能读成模型能力差」。但**修复① 已把文档原文内联进题面**
    （本批 33/39 条题面带「## 引用文档原文」段），那条 docs 不再缺失；
    且归因实测 `true_zero_no_attempt = 0`（0 分的题全都改过文件），
    ⇒ A2 的低分是**真能力信号**，不是题面缺信息。

    写死的形态是「数据变了、结论没变」，与 `t7-zero-diag.py` 的 `conclusion_guard`
    要拦的东西完全同类：报告看着完整，只有结论在撒谎。
    ⛔ 尤其不能在内联生效的批次里还说「不可读作模型能力」——
    那会把一个真实的能力读数解释掉。
    """
    # 本批题面是否内联了文档原文（stage 出来的题面现读，⛔ 不写死）
    n_inl, n_tasks = _n_inlined()

    if not n_inl:
        # 未内联（原 baseline 批）：T6 的核心发现仍然成立
        return [
            "**② 35/39 条题面点名 `docs/` 下的文档，而容器里没有 `docs/`。**",
            "这是 T6 的核心发现，压着 A2 那 20 条的天花板 —— "
            "**A2 档的低分不能读成「模型能力差」**，",
            "它首先是「题面缺信息」。这也是为什么下面必须**分级分组**看，而不是只看总分。",
        ]

    # ⚠️ `zd is None` 才是「没做归因」；⛔ 键缺失 ≠ 没做 —— 见 _n_no_attempt
    n_noattempt = None if zd is None else _n_no_attempt(zd)
    lines = [
        f"**② 题面缺 `docs/` 这条已被修复① 消除：本批 {n_inl}/{n_tasks} 条题面"
        "内联了被点名文档的原文。**",
        "原 baseline 批的核心 caveat 是「35/39 条题面点名 `docs/`，而容器里没有 `docs/`」，"
        "它压着 A2 档的天花板。本批已把那些文档原文附在题面里 ⇒ **这条不再是低分的解释**。",
    ]
    if n_noattempt is not None:
        lines += [
            f"归因侧的判据也指向同一结论：`true_zero_no_attempt = {n_noattempt}` —— "
            + ("0 分的题**全都改过文件**（读懂了题、动手改了、改错了），"
               if n_noattempt == 0 else
               f"其中 {n_noattempt} 条是「判断信息不足、拒绝瞎改」，仍需按题面缺信息读，"),
            "⇒ " + ("A2 档的低分在本批是**真能力信号**，⛔ 不可再用「题面缺信息」解释掉。"
                    if n_noattempt == 0 else
                    "A2 档的低分仍混有题面因素，分级分组看。"),
        ]
    else:
        lines += [
            "⚠️ 但本批缺 `zero-diag.json` ⇒ **无法断言** A2 的低分是能力还是题面："
            "判据是 `true_zero_no_attempt`（零仓库写 = 判断信息不足而拒绝瞎改）。",
            f"→ 跑 `{SCRIPTS_REL}/t7-zero-diag.py`（$0）后重新生成本报告。",
        ]
    lines.append("无论哪种读法，下面都必须**分级分组**看，而不是只看总分。")
    return lines


def _zero_diag_section(zd: dict | None, p: float | None = None) -> list[str]:
    """§10 真 0 / 假 0 归因。**pass@1 低时这一节是预案要求的必答项。**

    没有 zero-diag.json 时刻意输出一行「未做」而不是静默跳过 ——
    跳过会让报告看起来完整，而预案要求的那一步其实没做。
    """
    if not zd:
        # ⛔ 路径与阈值都不许写死：
        #  - 取数源随 `--runs` 变（本批在 `reports/t8-rerun/`），
        #    写死 `reports/baseline/` 会让读者照它去查**另一批**的目录。
        #  - 阈值这里原写「< 10%」，而实际触发判据是 `res["p"] < 0.20`
        #    （健康度①「pass@1 ∈ [20%, 80%]」的下限），同一份报告两个数字打架。
        # ⚠️ pass@1 达标（≥ 20%）时这一节**不是**预案的必答项 ——
        # 仍然建议做（0 分的成因值得分辨），但标 🔴「未做」会谎报一条未完成的要求。
        low = p is not None and p < 0.20
        return [
            "## 10. 真 0 / 假 0 归因",
            "",
            (f"🔴 **未做**：pass@1 = {p:.1%} 低于健康度下限（20%）⇒ "
             "预案表要求先分辨真 0 假 0，" if low else
             (f"ℹ️ **未做**（非必答）：pass@1 = {p:.1%} 已达健康度下限（20%），"
              "预案未被触发；仍建议归因 0 分的成因，"
              if p is not None else
              "ℹ️ **未做**：预案表要求 pass@1 低于 20% 时先分辨真 0 假 0，"))
            + f"而 `{_rel(RUNS / 'zero-diag.json')}` 不存在。",
            f"→ 跑 `{SCRIPTS_REL}/t7-zero-diag.py --runs {RUNS.name}`"
            "（纯读产物，$0）后重新生成本报告。",
            "",
        ]
    v = zd.get("verdicts", {})
    hd = zd.get("bash_hunting_doc", {})
    term = zd.get("termination_subtypes", {})
    n = zd.get("n_diagnosed", 0)
    # 🔴 标题与首句都随实际 pass@1 变，⛔ 不许写死「低于 20% / 预案要求的必答项」。
    #
    # 2026-09-14 抓到：整节无条件断言「pass@1 低于 20% ⇒ 预案表写死优先怀疑 grader」，
    # 而本批实测 36%（健康度① **达标**）⇒ 报告在陈述一条与自己主表相反的事实，
    # 且把一节「本不该触发的预案」讲成了必答项。
    low = p is not None and p < 0.20
    lines = [
        "## 10. 真 0 / 假 0 归因"
        + ("（🔴 预案要求的必答项）" if low or p is None else "（ℹ️ 预案未触发，主动归因）"),
        "",
    ]
    if zd.get("stale"):
        st = zd["stale"]
        who = st.get("unseen_tasks") or []
        # 🔴 必须点名「哪几条没归因」，⛔ 不能只说条数差 ——
        # 补跑重跑同一条题时条数一个不变（39 vs 39），只有 trial 目录换了。
        # 光说条数的文案在那个形态下读起来像「没差」，而本节的判定其实是旧的。
        lines += [
            f"> ⚠️ **本节数据比主表旧**：归因跑的是 {st['n_diagnosed']} 条，"
            f"主表 {st['n_with_trial']} 条。"
            + (f"其中 **{len(who)} 条未被本节归因**："
               f"{'、'.join(f'`{t}`' for t in who[:12])}"
               f"{' …' if len(who) > 12 else ''}"
               "（新跑出的、或补跑换了 trial 目录的）。"
               if who else "")
            + "⛔ 本节判定**不可**与主表并读。"
            f"重跑 `{SCRIPTS_REL}/t7-zero-diag.py`（$0）即可对齐。",
            "",
        ]
    lines += [
        (f"pass@1 = {p:.1%} 低于 20% ⇒ 预案表写死「**优先怀疑 grader**，先分辨真 0 假 0」。"
         if low else
         (f"pass@1 = {p:.1%} 已达健康度下限（20%）⇒ 预案「优先怀疑 grader」**未被触发**；"
          "本节是主动归因，用来分辨 0 分里哪些是能力信号、哪些是判分或环境问题。"
          if p is not None else
          "预案表写死：pass@1 低于 20% ⇒「**优先怀疑 grader**，先分辨真 0 假 0」。"))
        + f"已逐条归因 {n} 条（`{SCRIPTS_REL}/t7-zero-diag.py`，纯读产物 $0，"
        # ⛔ 产物路径随 `--runs` 变，不写死 reports/baseline/
        f"产物 `{_rel(RUNS / 'zero-diag.json')}`）。",
        "",
        "| 判定 | 条数 | 含义 |",
        "|---|---|---|",
        f"| `grader_incomplete` | {v.get('grader_incomplete', 0)} | "
        "判分侧没看全 f2p（missing / no_tests / error_code≠0）⇒ "
        "⛔ **不能**读作「模型答错」 |",
        f"| `true_zero_no_attempt` | {v.get('true_zero_no_attempt', 0)} | "
        "真 0，但模型**一次都没改文件** ⇒ 它没提交解法，不是解法不对 |",
        f"| `true_zero_wrong_fix` | {v.get('true_zero_wrong_fix', 0)} | "
        # ⛔ 不许写「**这才是**能力信号」—— 排他措辞会与 conclusion_guard 的
        # 「能力信号共 N 条」打架（后者含 true_zero_missing_symbol）。
        "真 0：测试跑起来了且模型改过文件 ⇒ 改动不对（**能力信号**） |",
        # 🔴 这一行原本**整行缺失** —— 2026-09-14 抓到：本批有 5 条
        # `true_zero_missing_symbol`，conclusion_guard 与 §5 都在讲它，
        # 而 §10 的判定表里没有它，读者对不上「5 条从哪来的」。
        f"| `true_zero_missing_symbol` | {v.get('true_zero_missing_symbol', 0)} | "
        "真 0：测试跑到了，但模型没写出被 import 的 src 符号"
        "（那些正是 gold patch 要创建的）⇒ **也是能力信号**，⛔ 不是判分缺陷 |",
        f"| `infra_upstream_disconnect` | {v.get('infra_upstream_disconnect', 0)} | "
        "**假 0**：上游 LLM 链路断连，verifier 照常打了分 ⇒ 已按 infra 排除出分母 |",
        # 🔴 2026-09-14 抓到的第二类假 0：agent **一次都没启动**（题面超
        # Linux MAX_ARG_STRLEN，`bash -c` 拒绝 exec）。判分侧读数与「改错」
        # 一模一样（reward=0 + f2p 加载失败）⇒ 旧口径把它判成
        # `true_zero_missing_symbol`，即**能力信号**。⛔ 一次工程故障不许
        # 记成模型没写出符号。
        f"| `infra_agent_not_launched` | {v.get('infra_agent_not_launched', 0)} | "
        "**假 0**：agent 进程一次都没启动（题面超 `MAX_ARG_STRLEN`，exec 被拒，"
        "退出码 255），verifier 照常打了分 ⇒ 已按 infra 排除出分母 |",
        f"| `solved` | {v.get('solved', 0)} | 解出 |",
        "",
        f"**写文件工具调用合计：{zd.get('n_write_tool_calls_total')} 次**"
        f"（{n} 条 trial 加起来）。",
        "",
    ]
    if term:
        lines += [f"终止类型：`{term}`。"]
    # 轮次归因：取第一条有 attribution 的
    att = next((t["termination"]["attribution"] for t in zd.get("trials", [])
                if (t.get("termination") or {}).get("attribution")), None)
    if att:
        lines += [
            "",
            f"轮次归因：{att}",
            "",
            "> 判据出处：`sid_code_agent.py` 的 `sid_num_turns_without_model_interaction` "
            "注释 —— `error_max_turns` 有**两类成因、不可混算**："
            "「轮次真不够用」要抬 `--max-turns`，"
            "「轮次没换来模型交互」是网络/重试问题，抬轮数治不了。",
        ]
    if hd.get("share") is not None:
        # 🔴 措辞随批次变，⛔ 不许写死 baseline 的框架。
        #
        # 2026-09-14 抓到：原文把这些 bash 调用当作低分归因
        # （「模型把预算花在找那份题面点名、而实际不存在的文档上」），
        # 而修复① 已把文档原文内联进题面（§2②）⇒ 本批那份文档**就在题面里**，
        # 这些 find/ls 是白费功夫，⛔ 不是「信息拿不到」。
        # 两句并读会让读者以为本批仍有文档缺口。
        #
        # ⚠️ 占比本身是修复① 生效的证据：baseline 批 154/405 = 38%，
        # 本批 400/2774 = 14%（同一判据、同一脚本）。
        inlined, _ = _n_inlined()
        lines += [
            "",
            f"**约 {hd['n_hunting']}/{hd['n_bash']}（{hd['share']:.0%}）的 bash 调用"
            + ("花在容器里找题面点名的文档上** —— 但本批那些文档的**原文已内联在题面里**"
               "（§2②）⇒ 这是**白费功夫**，⛔ 不是「信息拿不到」。"
               if inlined else
               "花在容器里找那份题面点名、而实际不存在的文档上**")
            + f"（{hd.get('note', '')}）。",
        ]
    ctrl = zd.get("control_group") or {}
    if ctrl:
        lines += [
            "",
            "### 对照组：能反证上面这个归因的 4 条",
            "",
            f"存活 39 条里有 **{ctrl.get('n_control')} 条题面不点名 `docs/`**"
            f"（{', '.join(ctrl.get('control_tasks', []))}）—— 天然对照组。"
            f"已跑 {ctrl.get('n_control_done')} 条。",
            "",
            f"判读：{ctrl.get('reading')}",
            "",
            f"> {ctrl.get('prereg_note', '')}",
            "> 归因**可被这组数据推翻**：若对照组也全是「零改动 + 轮次耗尽」，"
            # ⛔ 轮次上限从 zero-diag 现读 —— baseline 批是 40（agent 默认值），
            # 整改后这批显式传了 120，写死会让读者拿错的阈值理解「撞上限」。
            f"就说明 {zd.get('max_turns', '?')} 轮上限本身不够用，"
            "⛔ 那时不许只把责任推给题面缺陷。",
        ]
    # ⚠️ 结论强度必须跟证据强度对齐：对照组没跑完时只能说「已判的这些条不是能力信号」，
    # ⛔ 不许提前写成「本批的 0% 不是模型能力问题」—— 那是反证做完之后才成立的话。
    ctrl_done = bool(ctrl.get("n_control_done"))
    # 🔴 读结构化字段，⛔ 不许 `"成立" in reading` ——
    # 2026-09-14 实测：判读加了否定句「不许用部分样本宣布归因**成立**」后，
    # 子串匹配把「判读暂缓」读成了「对照组支持归因」，
    # 于是 1/4 条样本解锁了 §10 最强的那句结论。
    # 旧快照没有 supports 字段时**保守取 False**（宁可少下结论）。
    ctrl_supports = bool(ctrl.get("supports"))
    lines += [
        "",
        # ⛔ 不许再套一层 `**` —— guard 文案**自己带**加粗标记（「**假 0**」
        # 「**真 0**」…），外面再包一对会让 markdown 的强调配对错位：
        # 渲染出来是「假 0」那几个字变回正常体、而周围本该正常的文字变粗。
        # 形态是**只在渲染后才看得见**，读源码时一切正常。
        # 2026-09-14 抓到（新增 infra_agent_not_launched 使 guard 里的 `**`
        # 由偶数变奇数，把后半段整句都染粗了）。
        f"> 🔴 {zd.get('conclusion_guard', '')}",
        "",
    ]
    if ctrl_done and ctrl_supports:
        # 🔴 这一支**只在终版触发**（对照组跑完且判读支持归因），
        # 中途 `--partial` 永远走不到 ⇒ 写死的数字在这里最难被发现。
        # 2026-09-14 抓到：原文写死「本批的 0%」+「40 轮隐式上限」，
        # 而本批实测 pass@1 ≈ 33%、显式跑的是 120 轮。
        #
        # ⚠️ 还有一处**逻辑**过期：这句把低分整体归给「题面缺陷（点名容器内
        # 不存在的 docs/）」，但修复① 已把文档原文内联进题面（见 §2②）——
        # 本批那个缺陷已消除，⛔ 不能再作为归因。
        n_wrong = (zd.get("verdicts") or {}).get("true_zero_wrong_fix", 0)
        if n_wrong:
            lines += [
                f"⇒ 对照组支持归因，但本批仍有 **{n_wrong} 条 `true_zero_wrong_fix`**"
                "（改了代码但改错）—— 那些条的 0 分**是能力信号**。"
                "⛔ 不许把本批的低分整体归给题面缺陷：题面缺 `docs/` 已被修复① 消除（见 §2②），"
                f"而 `--max-turns` 本批显式跑的是 {zd.get('max_turns', '?')} 轮。",
            ]
        else:
            lines += [
                f"⇒ 本批的 pass@1 **不是**「模型解不动真实软件任务」，而是"
                "**题面缺陷叠加轮次上限**："
                "模型把预算花在找那份文档上，从未进入「改代码」阶段"
                f"（`--max-turns` = {zd.get('max_turns', '?')}）。"
                "对照组已给出反向支持（见上）。"
                "⛔ 这个数字不可作为模型能力的证据。",
            ]
    else:
        # 🔴 ⛔ 不许写死「`true_zero_wrong_fix` = 0 ⇒ 0 分不是能力信号」。
        #
        # 2026-09-14 抓到：这段原文是 baseline 批（wrong_fix 确实为 0）的文案，
        # 而本批实测 **7 条** wrong_fix。写死的形态是**同一份报告自相矛盾**：
        # §10 表格写「wrong_fix 7 —— 这才是能力信号」、conclusion_guard 也写
        # 「✅ 只有那 7 条是能力信号」，紧接着下一行却说「没有一条…= 0 ⇒ 不是能力信号」。
        # 三处并排，读者无从判断哪个是真的。
        n_wrong = (zd.get("verdicts") or {}).get("true_zero_wrong_fix", 0)
        if n_wrong:
            lines += [
                f"⇒ 已判的 {n} 条里有 **{n_wrong} 条**是「改了代码但改错」"
                f"（`true_zero_wrong_fix` = {n_wrong}）—— 这些条的 0 分**是能力信号**："
                "测试跑起来了、模型改过文件、仍红。",
            ]
        else:
            lines += [
                f"⇒ 已判的 {n} 条里**没有一条**是「改了代码但改错」（`true_zero_wrong_fix` = 0）"
                "—— 就这些条而言，0 分**不是**能力信号：模型从未进入「改代码」阶段。",
            ]
        lines += [
            "",
            "⚠️ **但「整批的分数都由题面缺陷解释」这句话现在还不能说**："
            "对照组（题面无此缺陷的 4 条）"
            + ("的判读尚未支持归因" if ctrl_done else "还没跑到")
            + "，反证未完成。⛔ 不许把整批的低分归给题面缺陷。",
        ]
    lines += [
        "",
        "**v0.3 的两个动作**（本轮无法自救，如实记下）："
        "① T1 筛选链排除「题面主体是引用本地不可见文档」的会话，或引入指令重写；"
        "② `--max-turns` 显式写进跑批命令而不是用 agent 默认值 —— "
        "方案原就要求「`task.toml` 与 CLI 的 timeout 都显式写」，轮次上限是同一类隐式约束。",
        "",
    ]
    return lines


def load_zero_diag(trials: list) -> dict | None:
    """真 0 / 假 0 归因（`t7-zero-diag.py` 的产物）。没有就返回 None。

    🔴 方案预案表写死：pass@1 < 10% ⇒ **优先怀疑 grader，先分辨真 0 假 0**。
    所以 pass@1 低时报告**必须**带上这一节，否则等于跳过了预案要求的那一步。

    ⚠️ **新鲜度校验按 trial 身份，⛔ 不按条数**。
    `zero-diag.json` 是另一个脚本在**另一个时刻**跑出的快照，
    跑批还在前进时它会比 run 产物旧 —— 实测撞到过 §9 写「已判 5 条」而主表已是 6 条。

    🔴 为什么不能数条数：补跑（`t8-rerun.py --resume`）**重跑同一条题**，
    条数一个不变（39 vs 39），但那条的 trial 目录换成了新随机后缀、判定也换了。
    2026-09-14 的 T0022 就是这个形态：旧快照判 `infra_upstream_disconnect`，
    补跑后是真实读数 —— 条数判据完全不响，报告带着**旧归因**发布，
    §10 说「1 条上游断连」而主表已把它算进有效分母。两个数字并排且口径不同，
    正是这道守卫要拦的东西。

    所以拿 `trial_dir` 目录名（含随机后缀，重跑必变）做集合比对：
    只要主表里有任何一条不在快照里，就是过期。
    """
    p = RUNS / "zero-diag.json"
    if not p.exists():
        return None
    zd = json.loads(p.read_text(encoding="utf-8"))

    # 主表这一轮实际用的 trial 目录名。
    #
    # ⚠️ 只算**已判分**的：`t7-zero-diag.py` 把没有 `verifier/reward.json` 的
    # 判成 `running` 并**刻意排除**出 `n_diagnosed`。拿全部 trial 去比对，
    # 一条还没判分的题（本批 T0009）就会让守卫**永久报过期** ——
    # 重跑 zero-diag 也消不掉，因为它本来就不该归因那条。
    # 假阳性守卫比没有守卫更糟：它会训练读者忽略这行告警。
    now = {t.trial_dir.name for t in trials
           if getattr(t, "trial_dir", None) and isinstance(t.reward, (int, float))}
    # 快照归因过的 trial 目录名
    diagnosed = {r.get("trial_dir") for r in (zd.get("trials") or []) if r.get("trial_dir")}
    unseen = sorted(now - diagnosed)
    if unseen:
        zd["stale"] = {
            "n_diagnosed": zd.get("n_diagnosed", 0),
            "n_with_trial": len(now),
            "unseen_trials": unseen,
            "unseen_tasks": sorted({d.split("__")[0] for d in unseen}),
            "note": "zero-diag.json 未覆盖主表的全部**已判分** trial"
                    "（含补跑换目录的那些），需重跑 t7-zero-diag.py",
        }
    return zd


def health_checks(res: dict, bcells: dict, zd: dict | None = None) -> list[tuple[str, str, str]]:
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
        "低于 20% ⇒ 触发预案「优先怀疑 grader，先分辨真 0 假 0」。"
        "**已逐条归因，见 §10** —— 结论不是「模型能力差」。"),
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


def _n_concurrent(run_dir: Path | None) -> int:
    """从 run 产物读实际并发数（`config.json` 的 `n_concurrent_trials`）。

    ⛔ 不写死：第一轮是 `-n 1`、整改后那批是 `-n 6`，硬编码等于**谎报必控变量**。
    读不到时回落 1 并在报告里照实写 —— ⛔ 不编一个 6 出来。
    """
    # 公开仓：run 目录未入库（run_dir 为 None）⇒ 读 trials.json 的 run_meta。
    # ⛔ 不许直接回落 1 —— t8-rerun 实为 6，回落等于谎报必控变量。
    if run_dir is None:
        n = _run_meta().get("n_concurrent_trials")
        return int(n) if n else 1
    p = run_dir / "config.json"
    if not p.exists():
        return 1
    try:
        return int(json.loads(p.read_text(encoding="utf-8")).get("n_concurrent_trials") or 1)
    except (json.JSONDecodeError, TypeError, ValueError):
        return 1


def _compose() -> dict:
    """基线那一批实跑的**题面构成** —— card 的「怎么用」必须照它写。

    🔴 2026-09-14 抓到，这是 card 最容易发布出去的一条假话：
    交付的题面（`tasks/`）**不是基线实跑的题面**。
    基线跑的是 `t8-rerun.py` 现拼的 stage（`reports/t8-rerun/tasks/`，已 gitignore）——
    在原句之外加了两段：修复①「## 引用文档原文」与修复③「## 验收标准」。
    实测交付真身 **0/39** 带这两段，stage **34/39 + 39/39** 带。

    ⇒ 照 `harbor run -p <题集目录>` 跑复现的是**题集**，⛔ 不是基线读数的条件；
    那样跑等于关掉了两项修复，而这两项修复正是 pass@1 从 0% 变成 37.8% 的原因
    （见 remediation §8.2：T0011/T0047 就是靠修复③ 才拿到 1.0）。
    形态是「读者照 card 跑出个更低的数字，以为是模型差」，而 card 每个字都对得上产物。

    取数走 `summary-raw.json` 的 `config`（`t8-rerun.py` 自己落的盘），
    ⛔ 不数 stage 目录：`--resume` 会把 stage 重建成只剩待跑的那几条
    （本批补跑后只剩 2 个目录），照它数会说「本批 2 条」。同 `_n_inlined()` 那个坑。
    """
    raw = RUNS / "summary-raw.json"
    if not raw.exists():
        return {}
    try:
        return json.loads(raw.read_text(encoding="utf-8")).get("config") or {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _snapshot_stats() -> tuple[int, float, float] | None:
    """未入库的仓库快照：`(份数, 最小 MB, 最大 MB)`，从 `snapshots.jsonl` 的 `tar_bytes` 现算。

    🔴 2026-09-14 抓到：这段原本手写「每份 1–3MB」，实测是 **0.8–14.0MB**（均值 6.3）。
    一份开头就写着「⛔ 本文没有一个手写数字」的 card 里，唯一的手写数字是错的 ——
    而读者拿它估算「重建要多少磁盘」时会差 4 倍。
    """
    p = c.MVP_META / "snapshots.jsonl"
    if not p.exists():
        return None
    sizes = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            b = json.loads(line).get("tar_bytes")
        except json.JSONDecodeError:
            continue
        if isinstance(b, int) and b > 0:
            sizes.append(b)
    if not sizes:
        return None
    return len(sizes), min(sizes) / 1048576, max(sizes) / 1048576


def _n_docs_inlined() -> int:
    """修复① 内联用的**文档原文**份数（`reports/t8-fix/docs/` 下的 .md）。

    ⚠️ 与 `_n_inlined()` 的 34 是**两个数**：34 是「有内联的 task 条数」，
    这里是「文档份数」（一条 task 可点名多份）。card 里两个都出现，⛔ 别混。
    """
    d = c.MVP_REPORTS / "t8-fix/docs"
    return len(list(d.glob("*.md"))) if d.is_dir() else 0


def _card_usage(cfg: dict) -> list[str]:
    """card 的「怎么复现基线」段。**按实跑 config 现写**，⛔ 不写死命令。

    ⚠️ 两条命令刻意分开列，且**先说差别**：
      - 复现**题集**（跑交付的 tasks/ 原句题面）
      - 复现**基线读数**（必须走 t8-rerun.py，它才会拼那两段）
    只给一条会让读者以为二者等价 —— 见 `_compose()` 的论证。
    """
    inl, f2p = cfg.get("inline_docs"), cfg.get("f2p_list")
    n_conc = cfg.get("n_concurrent")
    turns, budget = cfg.get("max_turns"), cfg.get("max_budget_usd")
    if not cfg:
        # ⛔ 没有 config 就照实说「读不到」，不编一条命令出来 ——
        # card 是对外引用的第一入口，编出来的复现命令比没有更糟。
        return ["> ⚠️ 读不到本批实跑配置（缺 `summary-raw.json` 的 `config`）⇒"
                " **无法给出可复现基线的命令**，⛔ 别照 `tasks/` 直接跑就当复现了基线。", ""]
    return [
        "**⛔ 这两件事不是一回事**，混了就会跑出另一个数字：",
        "",
        f"| 你想复现什么 | 入口 | 题面形态 |",
        "|---|---|---|",
        f"| **题集本身**（39 条能不能跑起来） | `harbor run -p {TASKS_REL} "
        f"-n {n_conc}` | 交付原句，**不含**下面两段 |",
        f"| **基线读数**（{RUNS.name} 那批的 pass@1） | "
        f"`~/.local/share/uv/tools/harbor/bin/python {SCRIPTS_REL}/t8-rerun.py` | "
        f"原句 **+ 两段现拼** |",
        "",
        "🔴 **基线跑的题面不在 `tasks/` 里**。`t8-rerun.py` 把 39 条复制到 stage"
        f"（`reports/{RUNS.name}/tasks/`，已 gitignore）并在原句之外拼了两段：",
        "",
        f"- **`## 引用文档原文`**（修复①，本批 `inline_docs={inl}`）——"
        " 把题面点名的那份文档原文内联进去。"
        f"取数 `reports/t8-fix/docs/`（{_n_docs_inlined()} 份原文已入库）+ `docs-index.json`。"
        f"⚠️ 本批 **{_n_inlined()[0]}/{_n_inlined()[1]}** 条题面真的拼上了这段"
        "（其余的没点名任何可取到的文档）—— ⛔ 与「文档份数」是两个数。",
        f"- **`## 验收标准`**（修复③，本批 `f2p_list={f2p}`）——"
        " 只给 F2P 测试的**路径清单**，⛔ 不给测试内容（给内容就能从断言反推实现）。"
        "取数各 task 的 `tests/f2p.json`。",
        "",
        f"⇒ 照第一行跑（`tasks/` 原句）等于**关掉这两项修复**，"
        f"而它们正是本批 pass@1 不是 0% 的原因（第一轮 `baseline/` 无此两段，实测 0/39）。",
        "",
        f"其余必控参数（本批实测）：`max_turns={turns}`、`max_budget_usd={budget}`、"
        f"`-n {n_conc}`、`--agent-timeout-multiplier "
        f"{cfg.get('agent_timeout_multiplier')}`。",
        "",
        "⚠️ **`environment/repo-snapshot.tar.gz` 不在 git 里**"
        + (f"（{_snap[0]} 份，每份 {_snap[1]:.1f}–{_snap[2]:.1f}MB，"
           if (_snap := _snapshot_stats()) else "（")
        + "见 `.gitignore`）⇒ 新克隆的仓库**跑不起来**，须先重建 —— 两条路径：\n"
        f"> - **有快照在手**（HF 仓的 `snapshots/`）：`{SCRIPTS_REL}/t4-build-env.py --from-snapshots <dir>`，逐份校验 `tar_sha256`，任一条不符即报红退出 4。\n"
        f"> - **有 mirror 在手**（仅采集机）：`{SCRIPTS_REL}/t4-build-env.py` 从 mirror 重建。\n"
        "> `meta/snapshots.jsonl` 存了每份的 `tar_sha256` 与 `tar_bytes`，可逐条校验重建结果。",
        "",
    ]


def build_report(res: dict, trials: list[lib.Trial],
                 gcells: dict, bcells: dict, cost: dict, ctl: dict, k: int,
                 missing: list[str], n_surv: int,
                 funnel: list, gate_rows: list, attrib: dict, health: list,
                 fingerprint: str, zd: dict | None = None,
                 fp: dict | None = None, n_conc: int = 1) -> str:
    """排报告。**只吃已经算好的格子**，自己不做任何统计。

    刻意不收 `grade` / `band` 原始分组：它们已经被 `lib.group()` 变成 cells 了，
    再传一份进来就是**同一事实存两份**，将来两处漂移时会静默按错的那份排版。

    `missing` / `n_surv` 只用来在首屏标红「未跑齐」—— 不参与任何统计。
    """
    p, lo, hi = res["p"], res["lo"], res["hi"]
    ec = Counter(t.error_code for t in trials if t.error_code)
    # 🔴 局限清单先算出来 —— §11 的**标题条数**与**正文**必须用同一份，
    # 否则「标题说 16 条、正文 15 条」（`{excluded}` 无排除时整条剔除）。
    _lims = _limitations(
        n_conc, _excluded_limitation(res.get("excluded_tasks") or [], n_surv, zd))
    L = [
        "# Agent-Traj-Bench v0.2-mini — 基线评测报告",
        "",
        f"> 生成于 {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}，由 `{SCRIPTS_REL}/t7-report.py` 从 run 产物**纯复算**。",
        # ⛔ 取数源路径必须从 RUNS 现取，不能写死 `reports/baseline/` ——
        # `--runs t8-rerun` 时报告会自称数据来自第一轮那批（已作废），
        # 而报告里每个数字其实都是新批的。冒烟实测撞到（2026-09-13）。
        f"> 取数源唯一：`{_rel(RUNS)}/`（{res['n'] + res['excluded']} 条 task × k={k}）。",
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
        # ⛔ 并发数从 run 产物的 config.json 现读，不写死「-n 1」——
        # 整改后这批跑的是 `-n 6`（E1 实测判分零损伤），报告自称 `-n 1` 等于
        # 谎报必控变量，而读者无从发现。冒烟实测撞到（2026-09-13）。
        f"| k | {k}（`-n {n_conc}`"
        f"{'，并发是最大单一失真源' if n_conc == 1 else '，E1 实测 39/39 oracle 判分零损伤'}） |",
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
        *_docs_gap_para(zd),
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
        *_error_code_note(ec, zd),
        "",
        *_fp_section(fp),
        "## 7. 数据集是怎么来的（漏斗）",
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
        "## 8. 这批 task 凭什么可信（三道门禁）",
        "",
        "**每一条 task 都过了三道机械门禁**，然后 **40 条 100% 人工过目**（非抽样）。",
        "",
        "| 门禁 | 拦的是什么 | 过 | 淘汰 |",
        "|---|---|---|---|",
        # ⛔ 分母用各行自己的（门禁③ 的分母是 40，不是 65）—— 见 load_gate_rows
        *[f"| {name} | {why} | {ok}/{tot} | {bad} |" for name, why, ok, tot, bad in gate_rows],
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
        "## 9. 健康度判据逐条对账",
        "",
        "方案 §9 的三条（MVP 已放宽口径）。**达标与否都如实写，不达标不改判据。**",
        "",
        "| 判据 | 结论 | 依据 |",
        "|---|---|---|",
        *[f"| {name} | {verdict} | {why} |" for name, verdict, why in health],
        "",
        *_zero_diag_section(zd, p),
        # 🔴 条数取**实际渲染出的那份**，⛔ 不用 len(LIMITATIONS)：
        # `{excluded}` 那条在无排除时整条剔除 ⇒ 两者会差 1，
        # 形态是「标题说 16 条、正文只有 15 条」，而这一节正是讲诚实披露的。
        f"## 11. 局限（{len(_lims)} 条，主动披露）",
        "",
        "> 不写这一节，前面所有数字都会被一句「你怎么证明」问倒。",
        "",
        # ⛔ 不许直接渲染 LIMITATIONS：其中一条含 `{n_conc}` 占位符，
        # 直接输出会把花括号原样印进报告（且并发数仍是错的）。
        *[f"{i}. {x}" for i, x in enumerate(_lims, 1)],
        "",
        "## 12. 这批数字**不能**用来说什么",
        "",
        f"- **不能**说「模型在真实软件任务上的通过率是 {p:.0%}」——"
        " 39 条全部来自单一仓库（`person/sid-code`）、两类任务（bug_fix / test_authoring）。",
        # 🔴 与 §2② 同源 —— 修复① 内联文档后这条反过来了：⛔ 不许写死
        f"- {_a2_dont_say(zd)}（见 §2②）。",
        "- **不能**报三档难度单调性（S 档为 0，见 §2④）。",
        # ⛔ 分母写实际计分数，不写死 39 —— 半宽是按 scored 算的，
        # 两个数字并排（±16.7pp 与 n=39）会让读者以为区间是 39 条上的，
        # 而中途/有 infra 排除时 scored 一定小于 39。
        f"- **不能**跨批比 pass@1：半宽 ±{res['halfwidth_pp']:.1f}pp"
        f"（按参与计分的 {res['n']} 条算），小于这个量级的差异都在噪声里。",
        "- **不能**说「已按题面承诺离线运行」—— 实际是 allowlist（见 §2③）。",
        "",
        "## 13. 复算方式",
        "",
        "```bash",
        "# 纯复算，不跑任何东西、不花钱",
        # 🔴 命令必须带 `--runs`，⛔ 不许写死默认值。
        # 2026-09-14 抓到：这行原本是裸 `t7-report.py`，而默认取数源是
        # `baseline`（第一轮，已作废）⇒ 照本报告的复算命令跑，读的是**另一批**，
        # 复算出来的数字与本文对不上。而 §13 是本报告自称「可复算」的唯一入口，
        # 它指错批次等于这份报告不可复算。
        f"~/.local/share/uv/tools/harbor/bin/python {SCRIPTS_REL}/t7-report.py"
        + (f" --runs {RUNS.name}" if RUNS.name != "baseline" else ""),
        "```",
        "",
        # ⛔ 取数源路径同样随 `--runs` 变
        f"机器可读取数源：`{_rel(SUMMARY)}`（⛔ 别抄本文的 markdown 数字）。",
        "",
    ]
    return "\n".join(L)


def build_card(res: dict, gcells: dict, bcells: dict, cost: dict, ctl: dict, k: int,
               funnel: list, attrib: dict, n_surv: int, zd: dict | None,
               n_conc: int, fingerprint: str) -> str:
    """dataset card —— 方案 §6 点名要的那份「这个数据集是什么」。

    🔴 **与报告的分工**（写错这一条，两份文件就会互相打架）：

      - **报告** = 「**某一批**跑出了什么」，一批一份，文件名带批次名。
      - **card** = 「**这个数据集**是什么」，只有一份，不随 `--runs` 切。
        所以 card 引用读数时**必须点明是哪一批**，⛔ 不许写成数据集的固有属性 ——
        pass@1 是「模型 × 题集 × 配置」的联合读数，换任一项都会变。

    ⛔ **Limitations 不许在这里另写一份**：与报告 §11 共用 `_limitations()`。
    两处各写一份的形态是「报告 16 条、card 13 条」，而对外引用的人只看 card ——
    少的那几条正好是最该披露的（infra 排除、私有 registry、残余泄漏面都是后补的）。

    ⚠️ 分类/分档/仓库分布从 `meta.json` 现算，⛔ 不写死：
    局限第 2/4/5 条的措辞都依赖这几个分布，写死会在上游重跑后与局限自相矛盾。
    """
    surv = json.loads((RECHECK / "survivors.json").read_text(encoding="utf-8"))["survivors"]
    cat: Counter[str] = Counter()
    repo: Counter[str] = Counter()
    src: Counter[str] = Counter()
    model: Counter[str] = Counter()
    for t in surv:
        m = json.loads((c.MVP_TASKS / t / "meta.json").read_text(encoding="utf-8"))
        cat[m.get("category") or "?"] += 1
        repo[m.get("repo") or "?"] += 1
        src[m.get("agent_source") or "?"] += 1
        model[m.get("model") or "?"] += 1

    cfg = _compose()
    p, lo, hi = res["p"], res["lo"], res["hi"]
    _lims = _limitations(
        n_conc, _excluded_limitation(res.get("excluded_tasks") or [], n_surv, zd))

    def _dist(ctr: Counter[str]) -> str:
        return " / ".join(f"`{k}` {v}" for k, v in ctr.most_common())

    L = [
        "# Agent-Traj-Bench v0.2-mini — Dataset Card",
        "",
        f"> 生成于 {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}，"
        f"由 `{SCRIPTS_REL}/t7-report.py --card` 从产物**纯复算**。⛔ 本文没有一个手写数字。",
        "",
        "## 这是什么",
        "",
        "从**真实 Claude Code / Codex 生产会话轨迹**反解出的 SWE-bench 形态 benchmark："
        "每条 task 给一个 base 快照 + 开发者当时那句话，判分看指定测试从红转绿。",
        "",
        "**定位是「真实生产交互衍生的补充 benchmark」，⛔ 不是通用 SWE 基准** ——"
        "单开发者、单仓库、两类任务（见 Limitations 第 2 / 4 条）。",
        "",
        "## 规模与构成",
        "",
        "| 项 | 值 |",
        "|---|---|",
        f"| 交付 task 数 | **{len(surv)}** |",
        f"| 来源仓库 | {_dist(repo)} |",
        f"| 任务类型 | {_dist(cat)} |",
        f"| 难度分档（`edit_ops` 代理指标） | "
        f"{' / '.join(f'`{kk}` {len(v.tasks)}' for kk, v in bcells.items())}"
        "　⚠️ **S 档为 0** |",
        f"| 题面信息量分级 | "
        f"{' / '.join(f'`{kk}` {len(gcells[kk].tasks)}' for kk in ('C', 'B', 'A1', 'A2') if kk in gcells)} |",
        f"| 轨迹采集工具 | {_dist(src)} |",
        f"| 轨迹里的原始模型 | {_dist(model)} |",
        f"| 冻结批次指纹 | `{fingerprint}` |",
        "",
        "> **题面信息量分级**：`A2` 剥掉路径后只剩一句祈使句 ／ `A1` 点名交付物 ／"
        " `B` 文件名点出症状 ／ `C` 散文自带可复现症状。信息量 C > B > A1 > A2。",
        "> 🔴 这个维度与难度分档**不交叉**，两张表各看一个维度。",
        "",
        "## 是怎么筛出来的（漏斗）",
        "",
        "| 级 | 剩余 | 取数源 |",
        "|---|---|---|",
        *[f"| {label} | **{n}** | `{srcf}` |" for label, n, srcf in funnel],
        "",
        "> ⚠️ 第 3 行比第 2 行大不是笔误：单位从「会话」换成「任务单元」。",
        "",
        "三道机械门禁（`oracle` / `nop` / `oracle -k 3`）后 **100% 人工过目**（非抽样）。"
        f"淘汰归因合计 {sum(attrib.values())} 条：",
        "",
        *[f"- {kk}：**{vv}** 条" for kk, vv in attrib.items()],
        "",
        "## 基线读数",
        "",
        f"🔴 **以下数字是 `{RUNS.name}` 那一批的读数，⛔ 不是数据集的固有属性** ——"
        "pass@1 是「模型 × 题集 × 配置」的联合结果，换任一项都会变。",
        "",
        "| 项 | 值 |",
        "|---|---|",
        f"| 模型 | {', '.join(ctl['model_observed']) or '（产物里没有模型名）'} |",
        f"| **pass@1** | **{p:.1%}**（{res['passed']:g} / {res['n']}） |",
        f"| 95% Wilson | [{lo:.1%}, {hi:.1%}]，半宽 ±{res['halfwidth_pp']:.1f}pp |",
        f"| 分母 | `scored={res['n']}`，infra 排除 {res['excluded']} 条"
        f"{'（' + ', '.join(res['excluded_tasks']) + '）' if res['excluded_tasks'] else ''} |",
        f"| k | {k}（`-n {n_conc}`） |",
        f"| 实付 | ${cost['total']}（{cost['n_with_cost']}/{cost['n_trials']} 个 trial 有成本值） |",
        "",
        f"> **分母是 {res['n']} 而不是 {len(surv)}**：{res['denominator_note']}",
        "",
        f"完整报告（13 节，含真 0/假 0 逐条归因）：`{_rel(REPORT)}`　"
        f"机器可读取数源：`{_rel(SUMMARY)}`",
        "",
        # ⛔ 单模型 ⇒ 必须当场说清「不能拿它比较模型」，不能只在 Limitations 里提一句。
        # card 是对外引用的第一入口，读者最想干的就是拿这个数字比模型。
        *(["🔴 **只跑了 1 个模型 × k=1** ⇒ ⛔ **不能**用本数据集比较模型强弱"
           "（方案要求 ≥2 模型 × k=3 才谈模型间差异），也**不能**把这个点估计"
           "当作「模型在真实任务上的能力」—— 半宽 ±"
           f"{res['halfwidth_pp']:.1f}pp 的区间比多数模型间差距还宽。", ""]
          if len(ctl["model_observed"]) < 2 or k < 3 else []),
        "## 怎么跑",
        "",
        *_card_usage(cfg),
        "## Limitations（主动披露）",
        "",
        f"🔴 **{len(_lims)} 条，与报告 §11 同源**（`_limitations()`，⛔ 两处不各写一份）。"
        "不读这一节就引用上面的数字，会把已知缺陷当成结论。",
        "",
        *[f"{i}. {x}" for i, x in enumerate(_lims, 1)],
        "",
        "## 这批数字不能用来说什么",
        "",
        f"- ⛔ **不能**说「模型在真实开发任务上只能解 {p:.0%}」——"
        f"单模型、k={k}、n={res['n']}，且题面信息量分级实测主导了分数（报告 §3）。",
        f"- ⛔ **不能**拿它与 SWE-bench 等公开基准比数字：题集构造、判分口径、"
        "题面信息量都不同源。",
        "- ⛔ **不能**说「已排除训练集污染」—— 污染检测**未做**（Limitations 第 8 条）。",
        f"- ⛔ **不能**拿 {len(surv)} 当 pass@1 的分母（那会把 {res['excluded']} 条"
        "仪器故障记成答错）。",
        "",
        "## 复算",
        "",
        "```bash",
        "PY=~/.local/share/uv/tools/harbor/bin/python   # ⛔ 系统 python3 没有 harbor 包",
        f"$PY {SCRIPTS_REL}/t7-report.py --runs {RUNS.name} --card   # $0，不跑任何模型",
        "```",
        "",
    ]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", action="store_true", help="同时写 version.json 的冻结字段")
    ap.add_argument("--partial", action="store_true",
                    help="允许用跑批**中途**的产物出报告（会在报告首屏标红「未跑齐」）。"
                         "⛔ 不加这个开关时，跑批没跑齐就直接拒绝出报告")
    ap.add_argument("--runs", default="baseline", metavar="DIR",
                    help="取数源目录名（reports/ 下）。默认 baseline（第一轮，已作废）；"
                         "整改后那批传 t8-rerun。产物文件名跟着一起切，"
                         "⛔ 两批不共用同一个 .md（会静默覆盖）")
    ap.add_argument("--card", action="store_true",
                    help="同时写 DATASET_CARD.md（方案 §6 点名要的那份）。"
                         "⚠️ card 只有一份、不随 --runs 切，里面引用读数处会写明是哪一批")
    args = ap.parse_args()

    if args.runs != "baseline":
        _retarget(args.runs)

    # ⚠️ 公开仓没有 run 目录（那些 harbor 产物 2.5G，从未入库）⇒ 回落到入库的
    # `trials.json`。此时 `run` 为 None，只影响 `_n_concurrent(run)` 这类读 run 元数据的地方。
    run = lib.latest_run(RUNS)
    if run is None and not (RUNS / "trials.json").exists():
        raise SystemExit(
            f"{RUNS} 下既没有 run 目录、也没有 trials.json —— "
            f"先跑 scripts/t8-rerun.py（或 t7-baseline.py）"
        )
    # 🔴 跨所有 run 目录收 —— `t8-rerun.py --resume` 会新建一个 run 目录，
    # 只读最后那个会**静默漏掉**第一轮跑出的 trial（分母悄悄变小，每张表照样有数）。
    # 单 run 目录时 collect_all 等价于 collect。
    trials = lib.collect_all(RUNS)
    if not trials:
        raise SystemExit(f"{run or RUNS} 里没有可读的 trial —— 看 run.log / trials.json")

    surv, grade, band = load_inputs()
    res = lib.pass_at_1(trials)
    k = max(1, round(len(trials) / max(1, len({t.task for t in trials}))))

    gcells = lib.group(res["per_task_rate"], grade, res["excluded_tasks"])
    bcells = lib.group(res["per_task_rate"], band, res["excluded_tasks"])
    cost = cost_stats(trials)
    ctl = controlled(trials)
    fp = fp_split(trials)

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
            f"   run={_rel_run(run)}\n"
            "   → 等跑批跑完再出报告；确实要看中途结果就加 --partial（报告会标红「未跑齐」）。"
        )
    if missing:
        print(f"⚠️ --partial：{len(missing)}/{len(surv)} 条未跑，报告首屏已标红，⛔ 不可作为终版结论")

    funnel = load_funnel()
    gate_rows, attrib = load_gate_rows()
    # ⚠️ 传 trials 本身（不是条数）—— 过期判据按 trial 身份比对，见 load_zero_diag
    zd = load_zero_diag(trials)

    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps({
        "generated_at": datetime.now(UTC).isoformat(),
        # ⚠️ 用 _rel() 而不是裸 relative_to：MVP_DIR 被指到仓外（冒烟测试就是这么跑的）时
        # relative_to 会抛 ValueError，形态是「报告脚本崩在写 summary 的最后一行」，
        # 完全不指向路径。2026-09-12 冒烟时实测撞到。
        "run_dir": _rel_run(run),
        "k": k,
        # 🔴 完整性状态必须进机器可读取数源，不能只在 markdown 里标红 ——
        # 别处引用 summary.json 时看不到 markdown 的那行字。
        "complete": not missing,
        "coverage": {"n_survivors": len(surv), "n_with_trial": len(res["per_task_rate"]),
                     "n_missing": len(missing), "missing_tasks": missing},
        "ci": {kk: vv for kk, vv in res.items() if kk != "per_task_rate"},
        "per_task_rate": res["per_task_rate"],
        "cost_usd": cost,
        # F2P/P2P 分量：reward 把「没修好」与「改出回归」压成一个 0/1，分开存才留得住区分
        "f2p_p2p": fp,
        "controlled_variables": ctl,
        "by_grade": {kk: {"n": len(v.tasks), "solved": v.solved, "scored": v.scored,
                          "missing": v.missing, "excluded": v.excluded,
                          "report_pct": v.report_pct} for kk, v in gcells.items()},
        "by_band": {kk: {"n": len(v.tasks), "solved": v.solved, "scored": v.scored,
                         "missing": v.missing, "excluded": v.excluded,
                         "report_pct": v.report_pct} for kk, v in bcells.items()},
        "caveats": [
            "分母 39（T6 淘汰 T0005），⛔ 不是 gate.jsonl 的 40",
            # 🔴 这条**按本批实测生成**，⛔ 不写死 —— 修复① 内联文档后
            # 「题面缺 docs/」不再成立，写死会让机器可读取数源与报告 §2② 打架。
            _docs_gap_caveat(zd),
            "执行环境 allowlist（只放网关 IP），非题面写的 --network none",
            "S 档为 0 ⇒ 不构成三档单调性证据",
        ],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    if zd and zd.get("stale"):
        st = zd["stale"]
        who = st.get("unseen_tasks") or []
        print(f"⚠️ zero-diag.json 已过期（判了 {st['n_diagnosed']} 条，主表 "
              f"{st['n_with_trial']} 条；未覆盖 {len(who)} 条："
              f"{', '.join(who[:8])}{' …' if len(who) > 8 else ''}）"
              f" —— 报告 §10 会标注；重跑 {SCRIPTS_REL}/t7-zero-diag.py（$0）")
    health = health_checks(res, bcells, zd)
    # ⚠️ 与漏斗前三行走同一个取数源（公开仓是入库的 summary，抄录值）
    fingerprint = _funnel_sources()[0]["fingerprint"][:12]

    # 🔴 pass@1 低于健康度下限却没做真 0/假 0 归因 ⇒ 预案要求的那一步没做。
    # 不拦住的话报告会「看起来完整」地把 0% 摊出来，读者只能读成「模型不行」。
    if res["p"] < 0.20 and zd is None:
        print("⚠️ pass@1 低于 20% 但缺 zero-diag.json —— 报告 §10 会标「未做」；"
              f"建议先跑 {SCRIPTS_REL}/t7-zero-diag.py（$0）")

    REPORT.write_text(build_report(res, trials, gcells, bcells, cost, ctl, k, missing, len(surv),
                                   funnel, gate_rows, attrib, health, fingerprint, zd, fp,
                                   n_conc=_n_concurrent(run)),
                      encoding="utf-8")
    print(f"pass@1 = {res['p']:.1%}（{res['passed']:g}/{res['n']}），排除 {res['excluded']}，实付 ${cost['total']}")
    print(f"  报告 {_rel(REPORT)}")
    print(f"  取数源 {_rel(SUMMARY)}")

    if args.card:
        # 🔴 与冻结同一条纪律：中途产物不许写 card。
        # card 是**对外引用的第一入口**，它比报告更容易被单独传播 ——
        # 报告首屏有「未跑齐」红字，card 一旦发出去就没人回来看那行字了。
        if missing:
            raise SystemExit(
                f"⛔ 拒绝写 dataset card：{len(missing)}/{len(surv)} 条还没跑"
                "（--partial 只放行报告，不放行 card）。\n"
                "   → card 是对外引用入口，中途读数写进去等于把它当定稿发布。"
            )
        CARD.write_text(build_card(res, gcells, bcells, cost, ctl, k, funnel, attrib,
                                   len(surv), zd, _n_concurrent(run), fingerprint),
                        encoding="utf-8")
        print(f"  dataset card {_rel(CARD)}")

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
            # ⛔ 路径不许写死 baseline —— `--runs t8-rerun` 时报告叫
            # `baseline-v0.2-mini-t8-rerun.md`、summary 在 `reports/t8-rerun/` 下。
            # 写死会把**另一批**的产物路径永久冻进 version.json，
            # 而日后照它去复现只会读到 baseline 那批（或根本不存在的文件）。
            "artifacts": [_rel(REPORT), _rel(SUMMARY), _rel_run(run)],
            # 🔴 2026-09-14 抓到（就在真冻结那一刻）：这里原写
            #   f"...（{passed}/{n}），分母 {len(surv)} 条，排除 {excluded} 条"
            # ⇒ 渲染成「pass@1=37.8%（14/**37**），分母 **39** 条」——
            # **同一句话里两个分母**，而它要被**永久冻进** version.json。
            # 37 是 pass@1 的分母（scored），39 是题集条数（task_count，本文档另有其字段）。
            # 这正是 remediation §七-8 记的那个坑（40 / 39 / 37 三个数各有用途）的复发，
            # 且冻结后不可改 —— 日后回看只会看到一句自相矛盾的验收结论。
            # ⇒ 分母只写 scored，题集条数交给 task_count，⛔ 不在同一句里塞两个。
            "gate": (f"pass@1={res['p']:.1%}（{res['passed']:g}/{res['n']}），"
                     f"分母 scored={res['n']}（题集 {len(surv)} 条，"
                     f"infra 排除 {res['excluded']} 条不计分），"
                     f"实付 ${cost['total']}"),
            "model": ctl["model_observed"],
            "k": k,
            # 🔴 两条必须随冻结一起留档的 caveat，否则日后无法复现这批数字的条件
            "network_policy": ("allowlist（只放宿主网关 IP），**非题面写的 --network none**；"
                               "对被测模型而言 github/npm 全不可达（实测 SSL EOF），"
                               "证据 reports/t7-regate/netpolicy-probe.json"),
            # 🔴 与 §2② / summary.caveats 同源现读，⛔ 不写死 ——
            # 修复① 内联文档后「题面缺 docs/」已不成立，而 version.json 是
            # **永久冻结**的元数据：写死会让日后回看时拿到一个与报告相反的结论。
            "known_caveat": _docs_gap_caveat(zd),
        }
        vp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  已冻结 version.json：task_count={len(surv)}，progress.T7 已记录")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
