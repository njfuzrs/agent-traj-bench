#!/usr/bin/env python3
"""s2-desensitize.py — S2 脱敏：给保留单元产出脱敏文本 + 审计台账

出处：bench-curation-design.md §4.1 S2 + Phase 1 任务表，验收「抽样 100 条零漏检」

规则层在 `s2_rules.py`（单测直接引用）；本脚本负责读单元、脱敏、落盘、出台账。

## 为什么脱敏 unit 而不是整条 session（与 v0.1 的关键差异）

v0.1 对 2441 条 session 逐条脱敏，把整个 `trajectory` + `history` 重写成
`desensitized/<sid>/trajectory.json`。这次不这么做，两个理由：

1. **量级不对**。S1 保留 4381 条会话的 `raw.jsonl` 合计 **47.6GB**，全量重写既慢
   又要占掉几乎同等磁盘，而 benchmark 真正会发布出去的只是**单元级的
   instruction 与文件路径**（§6.2 的 task.yaml 字段）。轨迹正文留在原始层按需读。
2. **粒度不对**。S3 已经把会话切成 11591 个单元，脱敏产物应该与下游消费单位对齐。
   按 session 存会让 S4/S6 每次都要重新定位「这个单元对应哪一段」。

所以产物是 `phase1/desensitized/units.jsonl`：每单元一条，含脱敏后的
`instruction_clean`、`files_clean`、`test_cmds`，以及命中台账。

## 原始层只读

`data/pulled_sessions/` 一个字节都不改（见 common.py 顶部）。本阶段甚至不读它 ——
输入是 S3 产物 `units-v2.jsonl`。

用法：
  python3 scripts/phase1/s2-desensitize.py
  python3 scripts/phase1/s2-desensitize.py --limit 500 --dry-run

验收：python3 scripts/phase1/verify-phase1.py --stage s2
"""

import argparse
import collections
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import s2_rules as rules  # noqa: E402

OUT_UNITS = os.path.join(common.DESENS_DIR, "units.jsonl")


def process(unit: dict) -> dict:
    """脱敏一个单元。返回新记录，不改入参"""
    instr = unit.get("instruction_raw") or ""
    instr_clean, hits = rules.desensitize(instr)

    files_clean = []
    file_hits: list[dict] = []
    for fp in unit.get("files_touched") or []:
        c, h = rules.desensitize(fp)
        files_clean.append(c)
        file_hits.extend(h)

    all_hits = hits + file_hits
    sev = rules.worst_severity(all_hits)
    type_dist = collections.Counter(h["type"] for h in all_hits)

    return {
        "unit_id": unit["unit_id"],
        "sid": unit["sid"],
        "seq": unit.get("seq"),
        # 脱敏产物
        "instruction_clean": instr_clean,
        "instruction_len": len(instr_clean),
        "files_clean": files_clean,
        "test_cmds": unit.get("test_cmds") or {},
        # 审计
        "secret_severity": sev,
        "secret_types": sorted(type_dist),
        "secret_hit_count": len(all_hits),
        # high 级命中的单元不进公开 split（§6.2 splits.public）
        "needs_review": sev == rules.SEVERITY_HIGH,
        # 下游要用的客观量，从 S3 单元原样带过来
        "step_range": unit.get("step_range"),
        "started_at": unit.get("started_at"),
        "ended_by": unit.get("ended_by"),
        "boundary_reason": unit.get("boundary_reason"),
        # 切分置信度必须带下去 —— 它是 S3 披露自身局限的载体，下游要靠它筛选。
        # 漏掉过一次：本函数按字段名逐个搬运，新增字段不会自动跟着走，
        # 结果 7094 条产物的 boundary_confidence 全是 None，而 S3 产物里是好的。
        "boundary_confidence": unit.get("boundary_confidence"),
        "session_steps": unit.get("session_steps") or 0,
        "edit_ops": unit.get("edit_ops") or 0,
        "error_ops": unit.get("error_ops") or 0,
        "n_test_cmds": unit.get("n_test_cmds") or 0,
        "unique_tools": unit.get("unique_tools") or [],
        # 源信息块必须一路带下去（见 common.py）
        **{k: unit.get(k) for k in common.PROVENANCE_FIELDS},
    }


def main(argv: list[str] | None = None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=OUT_UNITS)
    args = ap.parse_args(argv)

    if not os.path.exists(common.UNITS):
        raise SystemExit(f"S3 产物不存在：{common.UNITS}\n  先跑 s3-split.py")
    units = [u for u in common.read_jsonl(common.UNITS) if u.get("keep")]
    if args.limit:
        units = units[:args.limit]

    t0 = datetime.datetime.now()
    print(f"S2 脱敏 — 输入 {len(units)} 个保留单元（S3 产物）")

    out = [process(u) for u in units]

    sev_dist = collections.Counter(r["secret_severity"] for r in out)
    type_dist: collections.Counter = collections.Counter()
    for r in out:
        for t in r["secret_types"]:
            type_dist[t] += 1
    clean = sum(1 for r in out if not r["secret_types"])
    review = sum(1 for r in out if r["needs_review"])

    # 残留自检：脱敏后还能不能扫出敏感信息（本阶段的自证，不依赖外部验收）
    residual: collections.Counter = collections.Counter()
    for r in out:
        _, again = rules.desensitize(r["instruction_clean"])
        for h in again:
            residual[h["type"]] += 1

    stats = {
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input_units": len(units),
        "units_with_hits": len(out) - clean,
        "units_clean": clean,
        "hit_rate": round((len(out) - clean) / max(len(out), 1), 4),
        "severity_dist": {str(k): v for k, v in sev_dist.most_common()},
        "type_dist": dict(type_dist.most_common()),
        "needs_review": review,
        "residual_after_redaction": dict(residual),
        "elapsed_sec": round((datetime.datetime.now() - t0).total_seconds(), 1),
    }

    print(f"  命中敏感信息 {stats['units_with_hits']} = {stats['hit_rate']:.1%}，"
          f"无命中 {clean}")
    print(f"  严重度分布：{stats['severity_dist']}")
    print(f"  命中类型：{stats['type_dist']}")
    print(f"  needs_review（high 级，不进公开 split）：{review}")
    if residual:
        print(f"  ⚠ 二次扫描仍有残留：{dict(residual)} —— 规则不收敛，须排查")
    else:
        print("  ✓ 二次扫描零残留（脱敏收敛）")

    if args.dry_run:
        print("\n--dry-run，未写文件")
        return

    common.write_jsonl(args.out, out)
    # 审计台账：只记命中的单元，供人工抽查
    audit = [
        {"unit_id": r["unit_id"], "sid": r["sid"],
         "severity": r["secret_severity"], "types": r["secret_types"],
         "hit_count": r["secret_hit_count"], "needs_review": r["needs_review"],
         "agent_source": r["agent_source"], "repo": r["repo"]}
        for r in out if r["secret_types"]
    ]
    common.write_jsonl(common.DESENS_AUDIT, audit)
    stats_path = args.out.replace(".jsonl", ".stats.json")
    with open(stats_path, "w") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"\n产物 → {args.out}（{len(out)} 条）")
    print(f"台账 → {common.DESENS_AUDIT}（{len(audit)} 条命中）")
    print(f"统计 → {stats_path}")
    print("原始层未改动：data/pulled_sessions/ 只读")


if __name__ == "__main__":
    main()
