#!/usr/bin/env python3
"""label-units.py — 分类与标注：给脱敏单元补 category / tags / difficulty

出处：bench-curation-design.md §4.6「分类体系」（方案原排在 Phase 2，用户
2026-09-05 要求提前到 Phase 1，理由见 labeler.py 顶部）

判定逻辑在 `labeler.py`（单测直接引用）；本脚本负责读写与出分布统计。

产物 `phase1/meta/labeled-v2.jsonl` 是 Phase 1 的**最终交付物**：一条一单元，
带齐三组信息 —— 源信息（哪个工具/模型/仓库采的）、分类（测什么能力）、
客观量（改了几个文件、报错几次）。这就是「筛选查看」的检索面。

用法：
  python3 scripts/phase1/label-units.py
  python3 scripts/phase1/label-units.py --dry-run

验收：python3 scripts/phase1/verify-phase1.py --stage label
"""

import argparse
import collections
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import labeler  # noqa: E402

IN_UNITS = os.path.join(common.DESENS_DIR, "units.jsonl")
OUT = os.path.join(common.P1_META, "labeled-v2.jsonl")


def main(argv: list[str] | None = None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args(argv)

    if not os.path.exists(IN_UNITS):
        raise SystemExit(f"S2 产物不存在：{IN_UNITS}\n  先跑 s2-desensitize.py")
    units = common.read_jsonl(IN_UNITS)

    t0 = datetime.datetime.now()
    print(f"分类与标注 — 输入 {len(units)} 个脱敏单元")

    out = []
    for u in units:
        out.append({**u, **labeler.label(u)})

    n = len(out)
    cat = collections.Counter(r["category"] for r in out)
    conf = collections.Counter(r["category_confidence"] for r in out)
    dif = collections.Counter(r["difficulty"] for r in out)
    tags: collections.Counter = collections.Counter()
    for r in out:
        for t in r["tags"]:
            tags[t] += 1

    rated = [r for r in out if r["difficulty"] != "unrated"]
    dif_rated = collections.Counter(r["difficulty"] for r in rated)
    max_share = (max(dif_rated.values()) / len(rated)) if rated else 0

    # 按采集通道 × 类别交叉 —— 这是「按源信息筛选」的核心视图
    by_source = {
        src: dict(collections.Counter(
            r["category"] for r in out if r["agent_source"] == src
        ).most_common())
        for src in common.AGENT_SOURCES
    }

    stats = {
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input_units": n,
        "category_dist": dict(cat.most_common()),
        "category_share": {k: round(v / n, 4) for k, v in cat.most_common()},
        "confidence_dist": dict(conf.most_common()),
        "low_confidence_share": round(conf["low"] / max(n, 1), 4),
        "difficulty_dist": dict(dif.most_common()),
        "difficulty_dist_rated_only": dict(dif_rated.most_common()),
        "difficulty_max_share_rated": round(max_share, 4),
        "tag_dist": dict(tags.most_common()),
        "category_by_agent_source": by_source,
        "elapsed_sec": round((datetime.datetime.now() - t0).total_seconds(), 1),
    }

    print("\n  category（单元级，加权打分；不与 §4.6 的会话级首命中口径直接可比）:")
    for k, v in cat.most_common():
        print(f"    {k:20s} {v:>6} {v / n:>6.1%}")
    print(f"\n  置信度：{stats['confidence_dist']}")
    print(f"    low {stats['low_confidence_share']:.1%} —— 交 Phase 2 LLM 复判")
    print(f"\n  difficulty（全体）：{stats['difficulty_dist']}")
    print(f"  difficulty（仅有写操作的 {len(rated)} 个）：{stats['difficulty_dist_rated_only']}")
    gate = "✓" if max_share <= 0.6 else "✗ 偏斜，回查客观锚点阈值"
    print(f"    最大单档 {max_share:.1%}（验收线 ≤60%）{gate}")
    print(f"\n  tags top10：{dict(tags.most_common(10))}")
    print("\n  按采集通道 × 类别（源信息筛选视图）:")
    for src, d in by_source.items():
        if not d:
            continue
        top = ", ".join(f"{k} {v}" for k, v in list(d.items())[:4])
        print(f"    {src:<14} {sum(d.values()):>6}   {top}")

    if args.dry_run:
        print("\n--dry-run，未写文件")
        return

    common.write_jsonl(args.out, out)
    stats_path = args.out.replace(".jsonl", ".stats.json")
    with open(stats_path, "w") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"\n产物 → {args.out}（{n} 条，Phase 1 最终交付物）")
    print(f"统计 → {stats_path}")


if __name__ == "__main__":
    main()
