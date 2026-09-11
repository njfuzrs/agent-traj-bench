#!/usr/bin/env python3
"""T6 — 回写 meta.json 的 leakage / solvability 两个字段

出处：docs-research/trajectory-platform/bench-mvp-plan.md v1.2 §4 T6「输出」与「验收」

## 写哪两个字段，源是什么

| 字段 | 源 | 交接依据 |
|---|---|---|
| `solvability.gold_verified` | `meta/gate.jsonl` 的 `survives` | T5 交接 #6：**以 gate.jsonl 为源，别解析报告 markdown** |
| `leakage.leak_scan_passed` | `reports/t6-recheck/leak-scan-container.jsonl` | 方案 §4 T6「验收」 |

## 两条纪律

1. **只写这两个字段**，其余键原样保留 —— meta.json 是 T3/T4 的产物，
   T6 没有资格改 f2p/p2p/snapshot 等判分输入。
2. **扫描没跑成功的条目写 `null`，不写 `true`**。构建超时属基础设施问题，
   「没验」和「验过没问题」必须可区分 —— 否则就是方法论第一条
   （验收脚本自己会骗人）：一个永远返 true 的字段等于没有这个字段。

## 用法

    python3 scripts/mvp/t6-writeback.py --dry-run   # 只看会改什么
    python3 scripts/mvp/t6-writeback.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

SCAN = c.MVP_REPORTS / "t6-recheck" / "leak-scan-container.jsonl"


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
        m["leakage"]["scanned_by"] = "scripts/mvp/t6-leak-scan.py（容器内，非读 tar）"

        if not args.dry_run:
            mp.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        n_changed += 1

    verb = "将写" if args.dry_run else "已写"
    print(f"{verb} {n_changed} 份 meta.json")
    if missing_scan:
        print(f"⚠️ 存活但泄漏扫描未覆盖/未建成的 {len(missing_scan)} 条，"
              f"leak_scan_passed 写 null（不是 true）：{' '.join(missing_scan)}")
        print("   补跑：python3 scripts/mvp/t6-leak-scan.py --resume")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
