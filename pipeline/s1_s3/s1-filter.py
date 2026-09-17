#!/usr/bin/env python3
"""s1-filter.py — S1 硬过滤：冻结批次 8562 条 → filtered-v2.jsonl

出处：bench-curation-design.md §4.2「S1 硬过滤规则」+ §9 Phase 1 任务表

只做规则判定，不读会话文件（S0 索引里的字段已够）。判定顺序即优先级，
命中即淘汰并记 `drop_reason` —— 每条淘汰都有归因，这是验收项。

## 淘汰不移目录

产物是一份新的 jsonl，`data/pulled_sessions/` 一个字节都不动。「这条不要」用
`keep: false` + `drop_reason` 表达。原因见 common.py 顶部注释（移目录会让
pull.py 重复下载 1722 条）。

## 六条规则

| 规则 | 判定 | 依据 |
|---|---|---|
| R1_EMPTY | steps == 0 | §4.2 |
| R2_TOO_SHORT | steps < 3 | §4.2 |
| R3_NO_ACTION | steps < 6 且 tool_call_count == 0 | §4.2 |
| R4_TOO_FEW_TOKENS | total_tokens < 1000 | §4.2 |
| E_SELF_REFERENTIAL | excluded_hit == true | §9.4 坑③（强制） |
| —— | exit_status 异常**不淘汰**，转 S3 | §4.2 R5 |

**R5 刻意不是淘汰规则**。方案原文说得很明确：一条 200 步的会话在末尾被用户
打断，前 180 步可能包含一个完整且成功的子任务。所以中断态会话打
`forced_split: true` 标记强制进 S3，只淘汰其最后一个未完成单元。实测批次内
29 条（interrupted 22 / user_interrupt 5 / partial 1 / abort 1 量级）。

`exit_status: tool_use`（2213 条）是 agent 调工具后的正常停止态，不是失败；
`unknown` + 空串（2569 条）也不作淘汰依据 —— 两者都交后续阶段按内容判定。

## 保留率 51.2% 与方案 §4.1 预算 70.8% 的偏差（是口径差，不是数据变差）

实测保留 4381/8562 = 51.2%，看着比预算低近 20 个点。逐层拆开后完全可解释：

| 口径 | 输入 | 保留 | 保留率 |
|---|---|---|---|
| 方案 §4.1（6019 条时） | 6019 | 4262 | 70.8% |
| 本次全量 | 8562 | 4381 | 51.2% |
| 扣掉 `legacy_trashed` | 6841 | 4381 | 64.0% |
| 再把 E_SELF_REFERENTIAL 还给 S4 | 6841 | 4653 | **68.0%** |

两个差异来源：

1. **分母含了上一轮移走的 1721 条**。它们的判据正是 `steps == 0`（实测 1721 条
   全部 steps==0），6019 那次统计不含它们，本轮移回主目录后进了索引 —— 于是
   `steps==0` 占比从 12.8% 涨到 31.1%，全部被 R1 挡掉。这批本来就该淘汰，
   把它们算进分母只是让百分比变小，可用素材数没少。
2. **E_SELF_REFERENTIAL 被提前到 S1**（见下一节）。方案把这 272 条算在 S4。

同口径下 68.0% vs 预算 70.8%，剩下 2.8 个点来自新数据的自然分布差异。
**结论：可用素材 4381 条，比 6019 条时代的 4262 条还多 119 条。**

## 为什么 E_SELF_REFERENTIAL 在这里而不在 S4

方案 §4.4 把它放在 S4 分诊。但 §9.4 坑③ 要求「不要在 S4 重新扫路径，索引里
已经标好了」—— 既然判定已完成，越早淘汰越省下游算力（S2 脱敏和 S3 切分都要
读会话文件，让 281 条自指污染会话白跑一遍没有意义）。产物里保留
`drop_reason: E_SELF_REFERENTIAL`，S4 可据此对账。

用法：
  python3 s1_s3/s1-filter.py --batch v0.2
  python3 s1_s3/s1-filter.py --batch v0.2 --dry-run

验收：python3 s1_s3/verify-phase1.py --stage s1
"""

import argparse
import collections
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

# 明确中断态（§4.2 R5）。这些**不淘汰**，转 S3 切分后只丢末尾未完成单元。
INTERRUPT_STATUS = {"user_interrupt", "interrupted", "partial", "abort"}

# 淘汰原因。取值固定，验收脚本按这份清单校验，防止下游出现拼写变体
DROP_REASONS = (
    "R1_EMPTY",
    "R2_TOO_SHORT",
    "R3_NO_ACTION",
    "R4_TOO_FEW_TOKENS",
    "E_SELF_REFERENTIAL",
)

MIN_STEPS = 3
MIN_STEPS_FOR_NO_TOOL = 6
MIN_TOKENS = 1000


def judge(rec: dict) -> str | None:
    """返回淘汰原因，None 表示保留。顺序即优先级"""
    steps = rec.get("steps") or 0
    tool_calls = rec.get("tool_call_count") or 0
    tokens = rec.get("total_tokens") or 0

    if steps == 0:
        return "R1_EMPTY"
    if steps < MIN_STEPS:
        return "R2_TOO_SHORT"
    if steps < MIN_STEPS_FOR_NO_TOOL and tool_calls == 0:
        return "R3_NO_ACTION"
    if tokens < MIN_TOKENS:
        return "R4_TOO_FEW_TOKENS"
    # §9.4 坑③：索引里已标好，不重新扫路径
    if rec.get("excluded_hit"):
        return "E_SELF_REFERENTIAL"
    return None


def build(batch_version: str) -> tuple[list[dict], dict]:
    batch = common.load_batch(batch_version)
    index = common.load_s0_index()

    batch_sids = [e["sid"] for e in batch["sessions"]]
    missing = [s for s in batch_sids if s not in index]
    if missing:
        raise SystemExit(
            f"批次里有 {len(missing)} 条会话不在 S0 索引中：{missing[:3]}\n"
            f"  索引可能被重建过。重跑 s0-normalize.py，或用与批次匹配的索引"
        )

    records = []
    drop_dist: collections.Counter = collections.Counter()
    keep_by_source: collections.Counter = collections.Counter()
    drop_by_source: collections.Counter = collections.Counter()
    forced = 0

    for sid in batch_sids:
        rec = index[sid]
        reason = judge(rec)
        prov = common.provenance_of(rec, batch_version)

        # 中断态：不淘汰，转 S3（§4.2 R5）
        is_interrupt = (rec.get("exit_status") or "").lower() in INTERRUPT_STATUS
        forced_split = bool(reason is None and is_interrupt)
        if forced_split:
            forced += 1

        out = {
            "sid": sid,
            "keep": reason is None,
            "drop_reason": reason,
            # 强制进 S3：中断态会话只淘汰末尾未完成单元，不整条丢
            "forced_split": forced_split,
            # 下游筛选与分诊要用的客观量，从索引搬过来避免二次读盘
            "steps": rec.get("steps") or 0,
            "tool_call_count": rec.get("tool_call_count") or 0,
            "total_tokens": rec.get("total_tokens") or 0,
            "exit_status": rec.get("exit_status") or "",
            "start_time": rec.get("start_time"),
            "n_edit_ops": rec.get("n_edit_ops") or 0,
            "n_error_ops": rec.get("n_error_ops") or 0,
            "n_test_cmds": rec.get("n_test_cmds") or 0,
            "instruction_len": rec.get("instruction_len") or 0,
            "has_raw": bool(rec.get("has_raw")),
            "has_events": bool(rec.get("has_events")),
            "has_thinking": bool(rec.get("has_thinking")),
            "has_sub_agent": bool(rec.get("has_sub_agent")),
            "unique_tools": rec.get("unique_tools") or [],
            # 标注类字段：不参与本阶段判定，但下游要据此降权/对账
            "excluded_hit": bool(rec.get("excluded_hit")),
            "legacy_trashed": bool(rec.get("legacy_trashed")),
            **prov,
        }
        records.append(out)

        if reason:
            drop_dist[reason] += 1
            drop_by_source[rec.get("agent_source")] += 1
        else:
            keep_by_source[rec.get("agent_source")] += 1

    kept = [r for r in records if r["keep"]]
    stats = {
        "batch_version": batch_version,
        "batch_fingerprint": batch["fingerprint"],
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input_count": len(records),
        "kept": len(kept),
        "dropped": len(records) - len(kept),
        "keep_rate": round(len(kept) / len(records), 4) if records else 0,
        "drop_reason_dist": dict(drop_dist.most_common()),
        "forced_split": forced,
        "keep_by_agent_source": dict(keep_by_source.most_common()),
        "drop_by_agent_source": dict(drop_by_source.most_common()),
        # 按通道×厂商交叉，供 §2.4 的分布表按通道拆分口径
        "kept_vendor_by_source": {
            src: dict(collections.Counter(
                r["vendor"] for r in kept if r["agent_source"] == src
            ).most_common())
            for src in common.AGENT_SOURCES
        },
        "kept_repo_resolution": dict(collections.Counter(
            r["repo_resolution"] for r in kept
        ).most_common()),
        "kept_anchored": sum(1 for r in kept if r["repo"]),
        "kept_conflict": sum(1 for r in kept if r["repo_resolution"] == "conflict"),
        "kept_has_raw": sum(1 for r in kept if r["has_raw"]),
    }
    return records, stats


def main(argv: list[str] | None = None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", default="v0.2", help="冻结批次版本号")
    ap.add_argument("--dry-run", action="store_true", help="只打印统计，不写文件")
    ap.add_argument("--out", default=common.FILTERED)
    args = ap.parse_args(argv)

    records, stats = build(args.batch)

    print(f"S1 硬过滤 — 批次 {stats['batch_version']}"
          f"（指纹 {stats['batch_fingerprint'][:16]}…）")
    print(f"  输入 {stats['input_count']} 条")
    for reason, n in stats["drop_reason_dist"].items():
        print(f"    淘汰 {reason:<20} {n}")
    print(f"  保留 {stats['kept']} = {stats['keep_rate']:.1%}"
          f"（方案 §4.1 预算 70.8%，见下方偏差说明）")
    print(f"  其中中断态强制进 S3：{stats['forced_split']} 条")
    print(f"  锚定 {stats['kept_anchored']}"
          f"（conflict {stats['kept_conflict']} 条，S4 须降权）")
    print(f"  有 raw.jsonl {stats['kept_has_raw']} = "
          f"{stats['kept_has_raw'] / max(stats['kept'], 1):.1%}（S3 切分素材）")
    print("  按采集通道保留：")
    for src, n in stats["keep_by_agent_source"].items():
        vend = stats["kept_vendor_by_source"].get(src) or {}
        top = ", ".join(f"{k}:{v}" for k, v in list(vend.items())[:3])
        print(f"    {src:<14} {n:>5}   厂商 {top}")

    if args.dry_run:
        print("\n--dry-run，未写文件")
        return

    common.write_jsonl(args.out, records)
    stats_path = args.out.replace(".jsonl", ".stats.json")
    with open(stats_path, "w") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"\n产物 → {args.out}（{len(records)} 条，含淘汰记录与归因）")
    print(f"统计 → {stats_path}")
    print("原始层未改动：data/pulled_sessions/ 只读")


if __name__ == "__main__":
    main()
