#!/usr/bin/env python3
"""T1 — 候选池定档

出处：`docs-research/trajectory-platform/bench-mvp-plan.md` v1.2 §4 T1

输入：`data/bench-staging/phase1/meta/labeled-v2.jsonl`（7692 个已标注单元）
输出：`bench/v0.2-mini/meta/candidates.jsonl` + `candidates.stats.json`

## 八条筛选链（顺序固定，每步记录剩余条数供对账）

    ① 切分安全：起点与终点边界均为 high
    ② repo ∈ {person/sid-code, ruijie/iam-studio-fe} 且 repo_resolution 已锚定
    ③ edit_ops >= 1
    ④ n_test_cmds > 0
    ⑤ secret_severity != 'high'
    ⑥ started_at >= '2026-06'
    ⑦ category ∈ {bug_fix, feature_impl, refactor, test_authoring}
    ⑧ 60 <= instruction_len <= 1200

**顺序不能随便调**：stats 里的逐条剩余数是与方案 §3.1 实测值对账的依据
（①→2937 是方案写明的锚点）。调顺序会让这个数字失去可比性。

## ⚠️ 条件⑤是个陷阱（§3.1）

`secret_severity` 的分布是 `medium` 6136 / `None` 1524 / `high` 32。
`medium` 覆盖 80% 单元，它是**脱敏后的残留标记**而非真实泄漏。
所以必须写 `!= 'high'` —— 写成 `in ('none','low')` 会把候选池筛成 **0**。

`--selftest-strict-secret` 就是这条的**反向自证**：故意用错写法跑一遍，
候选池必须归零并以非零码退出。方案 §4 T1 与 §4.9 都把它列为验收项。

## ⚠️ 「终点 high」的定义（§4 T1）

终点边界不是单元自己的字段 —— 单元只有起点的 `boundary_confidence`。
终点 high 的判据是：**该单元是会话最后一个单元，或下一个单元的
`boundary_confidence == 'high'`**。所以要按 `sid` 分组、按 `seq` 排序后看后继。
只看自己那一个字段会把「起点 high 但被 low 边界切断尾巴」的单元也放进来 ——
它们的 step_range 终点不可信，patch 会反解出多余改动。

## 难度分档

用 `common.band(edit_ops)` 现算，**不用 Phase 1 的 `difficulty`**（§3.7 坑二）。

用法：
    python3 scripts/mvp/t1-select-candidates.py
    python3 scripts/mvp/t1-select-candidates.py --selftest-strict-secret   # 反向自证
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common as c  # noqa: E402

# 条件②：只做这两个仓库（mirror 归档可用且 commit 密度足够，§3.3）
TARGET_REPOS = set(c.REPO_MIRRORS)
# 条件②：`unresolved` / `conflict` 表示仓库没锚定，反查 base_commit 无从下手
BAD_REPO_RESOLUTION = {"unresolved", "conflict"}
# 条件⑦：只要有明确代码产出的四类（doc_authoring 这类没有可判分的代码改动）
TARGET_CATEGORIES = {"bug_fix", "feature_impl", "refactor", "test_authoring"}
# 条件⑧：太短无信息量，太长含多任务
INSTR_LEN_MIN, INSTR_LEN_MAX = 60, 1200
# 条件⑥：工具链与仓库结构接近，checkout 可用性高（§3.5 工具链在漂移）
STARTED_AT_MIN = "2026-06"


def endpoint_is_high(units_by_sid: dict[str, list[dict]], unit: dict) -> bool:
    """终点边界是否 high 置信（§4 T1 的定义）。

    判据：该单元是会话最后一个单元，或**下一个单元**的
    `boundary_confidence == 'high'`。下一个单元的起点就是本单元的终点。
    """
    siblings = units_by_sid[unit["sid"]]
    seq = unit.get("seq")
    nxt = None
    for u in siblings:
        u_seq = u.get("seq")
        if u_seq is None or seq is None or u_seq <= seq:
            continue
        if nxt is None or u_seq < nxt.get("seq", 1 << 30):
            nxt = u
    if nxt is None:
        return True  # 会话最后一个单元，终点就是会话结束
    return nxt.get("boundary_confidence") == "high"


def select(units: list[dict], *, strict_secret: bool = False):
    """跑八条筛选链，返回 (候选列表, 逐条剩余数)。

    `strict_secret=True` 是**反向自证**用的错写法（条件⑤写成 `in ('none','low')`），
    正常路径永远不要传它。
    """
    units_by_sid: dict[str, list[dict]] = collections.defaultdict(list)
    for u in units:
        units_by_sid[u["sid"]].append(u)

    funnel: list[tuple[str, int]] = [("全量单元", len(units))]
    cur = units

    # ① 切分安全：起点与终点边界均为 high
    cur = [u for u in cur if u.get("boundary_confidence") == "high" and endpoint_is_high(units_by_sid, u)]
    funnel.append(("① 两端边界均 high", len(cur)))

    # ② 仓库在名单内且已锚定
    cur = [u for u in cur if u.get("repo") in TARGET_REPOS and u.get("repo_resolution") not in BAD_REPO_RESOLUTION]
    funnel.append(("② 目标仓库且已锚定", len(cur)))

    # ③ 有代码改动
    cur = [u for u in cur if (u.get("edit_ops") or 0) >= 1]
    funnel.append(("③ edit_ops >= 1", len(cur)))

    # ④ 有测试命令（F2P 的前提）
    cur = [u for u in cur if (u.get("n_test_cmds") or 0) > 0]
    funnel.append(("④ n_test_cmds > 0", len(cur)))

    # ⑤ 排除真实泄漏。⚠️ 陷阱见模块 docstring
    if strict_secret:
        cur = [u for u in cur if (u.get("secret_severity") or "none") in ("none", "low")]
        funnel.append(("⑤ secret_severity ∈ (none,low)【错写法】", len(cur)))
    else:
        cur = [u for u in cur if u.get("secret_severity") != "high"]
        funnel.append(("⑤ secret_severity != high", len(cur)))

    # ⑥ 时间窗
    cur = [u for u in cur if (u.get("started_at") or "") >= STARTED_AT_MIN]
    funnel.append(("⑥ started_at >= 2026-06", len(cur)))

    # ⑦ 类别
    cur = [u for u in cur if u.get("category") in TARGET_CATEGORIES]
    funnel.append(("⑦ category 四类", len(cur)))

    # ⑧ 指令长度
    cur = [u for u in cur if INSTR_LEN_MIN <= (u.get("instruction_len") or 0) <= INSTR_LEN_MAX]
    funnel.append((f"⑧ {INSTR_LEN_MIN} <= instruction_len <= {INSTR_LEN_MAX}", len(cur)))

    return cur, funnel


def build_rows(candidates: list[dict]) -> list[dict]:
    """裁出候选池要留档的字段，并补 `band`。

    只留 T2 反解与 T6 人工过目要用的字段 —— 不整行照搬，`labeled-v2` 的行含
    `files_clean` / `category_scores` 等大字段，候选池带着它们会让文件虚胖。
    """
    rows = []
    for u in candidates:
        rows.append(
            {
                "unit_id": u["unit_id"],
                "sid": u["sid"],
                "seq": u.get("seq"),
                "repo": u.get("repo"),
                "repo_resolution": u.get("repo_resolution"),
                "instruction_clean": u.get("instruction_clean"),
                "instruction_len": u.get("instruction_len"),
                "step_range": u.get("step_range"),
                "started_at": u.get("started_at"),
                "category": u.get("category"),
                "category_confidence": u.get("category_confidence"),
                "edit_ops": u.get("edit_ops") or 0,
                "band": c.band(u.get("edit_ops") or 0),
                "n_test_cmds": u.get("n_test_cmds") or 0,
                "test_cmds": u.get("test_cmds") or {},
                "files_clean": u.get("files_clean") or [],
                "secret_severity": u.get("secret_severity"),
                "boundary_confidence": u.get("boundary_confidence"),
                "agent_source": u.get("agent_source"),
                "model": u.get("model"),
                "vendor": u.get("vendor"),
                "provenance": u.get("provenance"),
                "batch_version": u.get("batch_version"),
            }
        )
    return rows


def distributions(rows: list[dict]) -> dict:
    """四张分布表（方案 §4 T1 验收项）：仓库 / 类别 / 月份 / 难度。"""

    def count(key_fn):
        return dict(sorted(collections.Counter(key_fn(r) for r in rows).items()))

    return {
        "by_repo": count(lambda r: r["repo"]),
        "by_category": count(lambda r: r["category"]),
        "by_month": count(lambda r: (r["started_at"] or "")[:7]),
        "by_band": count(lambda r: r["band"]),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="T1 候选池定档")
    ap.add_argument(
        "--selftest-strict-secret",
        action="store_true",
        help="反向自证：把条件⑤写成 in ('none','low')，候选池必须归零并非零退出",
    )
    ap.add_argument("--out", type=Path, default=c.CANDIDATES)
    ap.add_argument("--stats", type=Path, default=c.CANDIDATES_STATS)
    args = ap.parse_args()

    units = list(c.read_jsonl(c.LABELED_V2))

    # ── 反向自证（§4 T1 / §4.9） ─────────────────────────────────
    # 方案的判据是「脚本必须报『候选池为 0』**并退出非零**」。所以这里不另写一套
    # 判定，而是**让主路径带着错写法跑一遍**，观测它的退出码 —— 自证的对象是
    # 主路径的空池守卫本身，而不是一段只在自证模式下存在的代码。
    # 产物写到 reports/ 下的自证文件，**不碰真正的 candidates.jsonl**。
    if args.selftest_strict_secret:
        probe_out = c.MVP_REPORTS / "t1-selftest-strict-secret.jsonl"
        probe_stats = c.MVP_REPORTS / "t1-selftest-strict-secret.stats.json"
        code = run(units, strict_secret=True, out=probe_out, stats_path=probe_stats)
        print()
        if code != 0:
            print(
                f"✅ 反向自证通过：条件⑤写成 in ('none','low') 后主路径以非零码"
                f"（{code}）退出并报「候选池为 0」—— 证明 §3.1 的陷阱真实存在，"
                f"正式路径必须写 != 'high'"
            )
            return 0
        print(
            "✘ 反向自证失败：用错写法竟然正常退出（码 0）。说明空池守卫失效，"
            "或 secret_severity 的分布已变（§3.1 实测 medium 占 80%），需重新标定。"
        )
        return 1

    return run(units, strict_secret=False, out=args.out, stats_path=args.stats)


def run(
    units: list[dict],
    *,
    strict_secret: bool,
    out: Path,
    stats_path: Path,
) -> int:
    """跑一次完整选择并落盘，返回退出码。自证与正式路径共用这一条实现。"""
    candidates, funnel = select(units, strict_secret=strict_secret)

    print("筛选链逐条剩余：")
    for label, n in funnel:
        print(f"  {label:44s} {n:6d}")

    rows = build_rows(candidates)
    dist = distributions(rows)

    n = c.write_jsonl(out, rows)
    stats = {
        "task": "T1",
        "source": str(c.LABELED_V2.relative_to(c.REPO_ROOT)),
        "n_input_units": len(units),
        "n_candidates": n,
        "funnel": [{"step": label, "remaining": cnt} for label, cnt in funnel],
        "distributions": dist,
        "thresholds": {
            "instruction_len": [INSTR_LEN_MIN, INSTR_LEN_MAX],
            "started_at_min": STARTED_AT_MIN,
            "categories": sorted(TARGET_CATEGORIES),
            "repos": sorted(TARGET_REPOS),
            "band_rule": "S: edit_ops<=3 / M: <=10 / L: >10",
        },
    }
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print()
    for name, table in dist.items():
        print(f"{name}: {table}")
    print()
    print(f"候选池 {n} 条 → {out}")
    print(f"stats → {stats_path}")

    # ── 空池守卫（§4 T1 反向自证的对象就是这一段） ────────────────
    # 候选池为 0 一定是筛选条件写错了，不是数据没了。必须**报错并非零退出**，
    # 否则 T2 会拿着空文件跑完并「成功」产出 0 条 resolved —— 那是 R1 式的假绿。
    if n == 0:
        print(
            "✘ 候选池为 0。最可能的成因是条件⑤写成了 in ('none','low') —— "
            "§3.1 实测 secret_severity 的 medium 覆盖 80% 单元（脱敏残留标记，"
            "非真实泄漏），正确写法是 != 'high'。"
        )
        return 3

    # ── 验收（方案 §4 T1 / §4.9） ───────────────────────────────
    ok = True
    if n < 120:
        print(f"⚠️ 候选池 {n} 条 < 120（目标交付 50，需 ≥2 倍余量）")
        ok = False
    thin = {b: cnt for b, cnt in dist["by_band"].items() if cnt < 15}
    missing = [b for b in ("S", "M", "L") if b not in dist["by_band"]]
    if thin or missing:
        print(f"⚠️ 难度档不足 15 条：{thin}；完全缺档：{missing}")
        ok = False
    if ok:
        print("✅ 验收通过：≥120 条且三档各 ≥15 条（检查点 A）")
    else:
        print("→ 未达验收线。按 §7.2 检查点 A 放宽第⑧条或⑥条，**但不放宽①「两端 high」**（那是切分安全的地基）")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
