#!/usr/bin/env python3
"""T6 — 回写 meta.json 的 solvability / leakage / review 三段

出处：docs-research/trajectory-platform/bench-mvp-plan.md v1.2 §4 T6「输出」与「验收」

## 写哪几个字段，源是什么

| 字段 | 源 | 交接依据 |
|---|---|---|
| `solvability.gold_verified` | `meta/gate.jsonl` 的 `survives` | T5 交接 #6：**以 gate.jsonl 为源，别解析报告 markdown** |
| `leakage.leak_scan_passed` | `reports/t6-recheck/leak-scan-container.jsonl` | 方案 §4 T6「验收」 |
| `review.grade` / `review.eliminated` | `reports/t6-recheck/grade.json` | 方案 §4 T6「淘汰要记原因并归类」 |
| `leakage.filename_specificity` | `reports/t6-recheck/filename-leak.json` + §4.2 表格 | 本报告 §4.2：题面文件名的具体程度，`mechanism` 的 4 条得分可能偏高 |

⚠️ **为什么必须写 `review.eliminated`**：`gate.jsonl` 的 `survives` 是 T5 三道门禁的结论
（40 条），**不含 T6 的人工淘汰**。只写 `gold_verified` 的话，被淘汰的 `T0005` 在
meta.json 里长得和存活条目一模一样（三道门禁全绿），下游照 `gold_verified` 取集合会把
它算进基线 —— 而它的题面与判分对象完全无关。存活名单另见
`reports/t6-recheck/survivors.json`。

## 两条纪律

1. **只写上表这三段**，其余键原样保留 —— meta.json 是 T3/T4 的产物，
   T6 没有资格改 f2p/p2p/snapshot 等判分输入。
2. **没验成的写 `null`，不写 `true`**（扫描未建成、未过目同理）。构建超时属基础设施问题，
   「没验」和「验过没问题」必须可区分 —— 否则就是方法论第一条
   （验收脚本自己会骗人）：一个永远返 true 的字段等于没有这个字段。

## 用法

    python3 scripts/t6-writeback.py --dry-run   # 只看会改什么
    python3 scripts/t6-writeback.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

SCAN = c.MVP_REPORTS / "t6-recheck" / "leak-scan-container.jsonl"
GRADE = c.MVP_REPORTS / "t6-recheck" / "grade.json"
FNLEAK = c.MVP_REPORTS / "t6-recheck" / "filename-leak.json"


def load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="T6 回写 meta.json")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不落盘")
    args = ap.parse_args()

    gate = {r["task_id"]: r for r in load_jsonl(c.MVP_META / "gate.jsonl")}
    scan = {r["task_id"]: r for r in load_jsonl(SCAN)}
    grade = json.loads(GRADE.read_text(encoding="utf-8")) if GRADE.exists() else {}
    fnl = json.loads(FNLEAK.read_text(encoding="utf-8")) if FNLEAK.exists() else {}
    fn_root = set(fnl.get("rootcause_in_filename", []))
    fn_topic = set(fnl.get("topic_only", []))
    # ⚠️ filename-leak.json 只做了「文件名含具体信息 vs 仅主题」的二分，
    # 但报告 §4.2 的表格把前者再分两级 —— 只有这 4 条的文件名点出**机制**
    # （T0002 的「配置 undefined 覆盖默认值」正是 gold_patch 干的事），
    # 其余 4 条只是症状词（污染 / 误伤 / 缺少选项 / 不显示），§4.2 原文判为
    # 「仅症状，属正常题面」。一律写 True 会把正常题面也标成根因泄漏，
    # 让 T7 按 8 条的口径去打折扣 —— 报告说的是 4 条。
    FN_MECHANISM = {"T0002", "T0040", "T0038", "T0065"}
    if not grade:
        print("⚠️ grade.json 读不到 —— review 字段将全部写 null（不假装过目过）",
              file=sys.stderr)
    if not gate:
        print("🔴 meta/gate.jsonl 读不到 —— T5 门禁产物缺失", file=sys.stderr)
        return 1

    surv = [t for t, r in gate.items() if r["survives"]]
    print(f"gate.jsonl：{len(gate)} 条，其中存活 {len(surv)} 条")
    print(f"泄漏扫描产物：{len(scan)} 条"
          f"（扫过且无违规 {sum(1 for r in scan.values() if r.get('leak_scan_passed') is True)}）\n")

    n_changed = 0
    missing_scan = []
    for t in sorted(gate):
        mp = c.MVP_TASKS / t / "meta.json"
        if not mp.exists():
            print(f"  ⚠️ {t}：meta.json 不存在，跳过")
            continue
        m = json.loads(mp.read_text(encoding="utf-8"))

        # ① 可解性：以 gate.jsonl 为唯一源
        g = gate[t]
        m.setdefault("solvability", {})
        m["solvability"]["gold_verified"] = bool(g["survives"])
        m["solvability"]["gate_oracle"] = None if g.get("oracle") is None else g["oracle"]["ok"]
        m["solvability"]["gate_nop"] = None if g.get("nop") is None else g["nop"]["ok"]
        m["solvability"]["gate_oracle_k3"] = (
            None if g.get("oracle-k3") is None else g["oracle-k3"]["ok"]
        )
        m["solvability"]["verified_by"] = "T5 三道门禁（oracle / nop / oracle-k3）"

        # ② 泄漏：只有存活条目才扫了；没扫成功写 null，不写 true
        s = scan.get(t)
        m.setdefault("leakage", {})
        if s is None:
            m["leakage"]["leak_scan_passed"] = None
            m["leakage"]["leak_scan_note"] = "未扫（非存活集，或扫描未覆盖）"
            if g["survives"]:
                missing_scan.append(t)
        elif not s.get("built"):
            m["leakage"]["leak_scan_passed"] = None
            m["leakage"]["leak_scan_note"] = f"镜像未建成，未验：{s.get('error', '')}"
            missing_scan.append(t)
        else:
            m["leakage"]["leak_scan_passed"] = bool(s["leak_scan_passed"])
            m["leakage"]["leak_scan_note"] = (
                f"容器内 find 全盘扫描：命中 {s['n_hits']}，"
                f"违规 {len(s['violations'])}，已核良性 {s['benign_n']}"
            )
            m["leakage"]["leak_scan_violations"] = s["violations"]
        # ⛔ 同 t3 的 generated_by：目录名从 c.SCRIPTS_REL 现推，不写死（源仓 scripts/mvp/）。
        m["leakage"]["scanned_by"] = f"{c.SCRIPTS_REL}/t6-leak-scan.py（容器内，非读 tar）"

        # 另一类泄漏：题面文件名本身带信息（容器内扫描抓不到 —— 泄漏在题面文本里）。
        # 三级，与 §4.2 表格逐条对齐；一律不淘汰（bug 标题的自然形态）。
        if t in FN_MECHANISM:
            m["leakage"]["filename_specificity"] = "mechanism"
        elif t in fn_root:
            m["leakage"]["filename_specificity"] = "symptom"
        elif t in fn_topic:
            m["leakage"]["filename_specificity"] = "topic_only"
        else:
            m["leakage"]["filename_specificity"] = None  # 未核（题面无文档引用等）
        m["leakage"]["filename_note"] = (
            "mechanism=文件名点出修法所需机制，得分可能偏高（4 条，T7 要标注）；"
            "symptom=仅症状词，§4.2 判为正常题面；topic_only=仅主题"
        )

        # ③ 人工过目：分级 + 是否淘汰。没过目的写 null，不写「已过目且没问题」
        g6 = grade.get(t)
        m.setdefault("review", {})
        m["review"]["grade"] = g6
        m["review"]["eliminated"] = None if g6 is None else (g6 == "X")
        m["review"]["grade_meaning"] = (
            "A2 只剩祈使句 / A1 点名交付物 / B 文件名点出症状 / C 散文自带可复现症状 / X 淘汰"
        )
        m["review"]["reviewed_by"] = "T6 人工过目 100%（reports/t6-review.md §3.4）"
        if g6 == "X":
            m["review"]["eliminated_reason"] = (
                "instruction_unrelated_to_reward + prompt_template_contamination"
            )

        if not args.dry_run:
            mp.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        n_changed += 1

    verb = "将写" if args.dry_run else "已写"
    print(f"{verb} {n_changed} 份 meta.json")
    n_elim = sum(1 for v in grade.values() if v == "X")
    n_surv = sum(1 for t in surv if grade.get(t) != "X")
    print(f"人工过目：分级 {len(grade)} 条，淘汰 {n_elim} 条 → "
          f"T6 存活 {n_surv} 条（gate 存活 {len(surv)} − 淘汰 {n_elim}）")
    print(f"题面文件名带信息：{len(fn_root)} 条，其中点出**机制**的 {len(FN_MECHANISM)} 条（§4.2，T7 的 dataset card 要标注这 4 条）")
    if n_surv < 40:
        print(f"🔴 存活 {n_surv} < 方案底线 40 —— 处置权在 T7（t6-review.md §6.2）")
    if missing_scan:
        print(f"⚠️ 存活但泄漏扫描未覆盖/未建成的 {len(missing_scan)} 条，"
              f"leak_scan_passed 写 null（不是 true）：{' '.join(missing_scan)}")
        print("   补跑：python3 scripts/t6-leak-scan.py --resume")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
