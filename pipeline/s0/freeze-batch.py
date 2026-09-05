#!/usr/bin/env python3
"""freeze-batch.py — 冻结一个数据批次，产出可复现的 sid 清单

为什么必须冻结：线上数据每天新增（实测日增约 77 条），而 benchmark 的
「pass@1 = 42%」这类数字必须可复现。这与 §9.0 归档面对的是同一个问题 ——
仓库在日更，所以我们 `--mirror` 冻结快照；数据同理，冻结一个批次只洗这个批次，
之后新增的进下一批，不回炉重洗。

行业依据（§3.1 门槛 4「无污染 + 可版本化」）：SWE-bench / REAP 都以固定
task 清单 + 版本号发布，没有版本边界的数据集不可引用。

产出 `meta/batch-<version>.json`：
  - sid 清单（排序后）与内容指纹，任何增删都会让指纹变化
  - 截止时间戳、各采集通道计数、provenance 分布
  - 每条 sid 的 steps 与文件存在性，供后续阶段对账

用法：
  python3 scripts/phase0/freeze-batch.py --version v0.2
  python3 scripts/phase0/freeze-batch.py --version v0.2 --dry-run
  python3 scripts/phase0/freeze-batch.py --verify v0.2   # 校验批次是否仍完整
"""

import argparse
import collections
import datetime
import hashlib
import json
import os
import sys

SESSIONS_DIR = os.environ.get("SESSIONS_DIR", "data/pulled_sessions")
META_DIR = os.environ.get("OUT_DIR", "data/bench-staging/meta")
INDEX = os.path.join(META_DIR, "sessions-v2.jsonl")


def batch_path(version: str) -> str:
    return os.path.join(META_DIR, f"batch-{version}.json")


def build(version: str) -> dict:
    """从 S0 索引构建批次清单。以索引为准而不是直接扫目录 ——
    索引是 S0 归一化的产物，只有进了索引的会话才是可用素材。"""
    if not os.path.exists(INDEX):
        raise SystemExit(f"索引不存在：{INDEX}，先跑 s0-normalize.py")

    entries = []
    source_dist: collections.Counter = collections.Counter()
    prov_dist: collections.Counter = collections.Counter()
    repo_dist: collections.Counter = collections.Counter()
    steps_ge3 = 0
    anchored = 0
    latest = ""

    with open(INDEX) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            entries.append({
                "sid": rec["sid"],
                "steps": rec.get("steps") or 0,
                "agent_source": rec.get("agent_source"),
                "provenance": rec.get("provenance"),
                "repo": rec.get("repo"),
                "repo_resolution": rec.get("repo_resolution"),
                "legacy_trashed": bool(rec.get("legacy_trashed")),
                "has_raw": bool(rec.get("has_raw")),
                "has_events": bool(rec.get("has_events")),
            })
            source_dist[rec.get("agent_source")] += 1
            prov_dist[rec.get("provenance")] += 1
            if (rec.get("steps") or 0) >= 3:
                steps_ge3 += 1
                repo_dist[rec.get("repo") or "(unresolved)"] += 1
                if rec.get("repo"):
                    anchored += 1
            st = rec.get("start_time") or ""
            if st > latest:
                latest = st

    entries.sort(key=lambda e: e["sid"])
    # 指纹只覆盖 sid + steps：sid 集合的增删、以及会话被追加内容（steps 变化）
    # 都会让指纹变化，但不受字段口径调整影响。
    payload = "\n".join(f"{e['sid']}:{e['steps']}" for e in entries)
    fingerprint = hashlib.sha256(payload.encode()).hexdigest()

    return {
        "version": version,
        "frozen_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session_count": len(entries),
        "fingerprint": fingerprint,
        "latest_session_start": latest,
        "steps_ge3": steps_ge3,
        "steps_ge3_anchored": anchored,
        "anchor_rate": round(anchored / steps_ge3, 4) if steps_ge3 else 0,
        "legacy_trashed": sum(1 for e in entries if e["legacy_trashed"]),
        "agent_source_dist": dict(source_dist.most_common()),
        "provenance_dist": dict(prov_dist.most_common()),
        "repo_dist": dict(repo_dist.most_common(25)),
        "sessions": entries,
    }


def verify(version: str) -> int:
    """校验已冻结的批次：清单里的会话是否都还在、指纹是否仍一致"""
    path = batch_path(version)
    if not os.path.exists(path):
        print(f"✗ 批次不存在：{path}")
        return 1
    with open(path) as f:
        batch = json.load(f)

    print(f"批次 {batch['version']}（冻结于 {batch['frozen_at']}）")
    print(f"  会话 {batch['session_count']} 条，指纹 {batch['fingerprint'][:16]}…")

    missing = [e["sid"] for e in batch["sessions"]
               if not os.path.exists(os.path.join(SESSIONS_DIR, e["sid"], "session.traj"))]
    if missing:
        print(f"  ✗ {len(missing)} 条会话的 session.traj 已不在磁盘：{missing[:5]}")
        return 1
    print(f"  ✓ {batch['session_count']} 条会话全部在磁盘")

    current = build(batch["version"])
    if current["fingerprint"] != batch["fingerprint"]:
        added = {e["sid"] for e in current["sessions"]} - {e["sid"] for e in batch["sessions"]}
        removed = {e["sid"] for e in batch["sessions"]} - {e["sid"] for e in current["sessions"]}
        print(f"  ! 当前索引与批次不一致：新增 {len(added)}、移除 {len(removed)}")
        print("    这是预期的 —— 数据每天在增。批次是快照，索引是当下。")
        print(f"    要洗的是批次里那 {batch['session_count']} 条，新增的进下一批。")
    else:
        print("  ✓ 当前索引与批次指纹一致（尚无新数据）")
    return 0


def main_with_args(argv: list[str] | None = None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", help="批次版本号，如 v0.2")
    ap.add_argument("--verify", metavar="VERSION", help="校验已冻结的批次")
    ap.add_argument("--dry-run", action="store_true", help="只打印统计，不写文件")
    args = ap.parse_args(argv)

    if args.verify:
        sys.exit(verify(args.verify))
    if not args.version:
        ap.error("需要 --version 或 --verify")

    batch = build(args.version)
    path = batch_path(args.version)

    print(f"批次 {batch['version']}")
    print(f"  会话数        {batch['session_count']}")
    print(f"  指纹          {batch['fingerprint'][:16]}…")
    print(f"  最新会话      {batch['latest_session_start']}")
    print(f"  steps>=3      {batch['steps_ge3']}，锚定 {batch['steps_ge3_anchored']}"
          f" = {batch['anchor_rate']:.1%}")
    print(f"  采集通道      {batch['agent_source_dist']}")
    print(f"  provenance    {batch['provenance_dist']}")
    print(f"  上轮已清洗标记 {batch['legacy_trashed']}")

    if args.dry_run:
        print("\n--dry-run，未写文件")
        return
    if os.path.exists(path):
        with open(path) as f:
            old = json.load(f)
        if old["fingerprint"] != batch["fingerprint"]:
            raise SystemExit(
                f"\n✗ {path} 已存在且指纹不同（{old['fingerprint'][:12]}… → "
                f"{batch['fingerprint'][:12]}…，{old['session_count']} → "
                f"{batch['session_count']} 条）。\n"
                f"  冻结过的批次不可改写 —— 那会让已发布的结果不可复现。\n"
                f"  新数据请冻结为新版本号。"
            )
        print(f"\n{path} 已存在且指纹一致，无需重写")
        return

    os.makedirs(META_DIR, exist_ok=True)
    with open(path, "w") as f:
        json.dump(batch, f, ensure_ascii=False, indent=2)
    print(f"\n已冻结 → {path}")
    print(f"Phase 1 只洗这 {batch['session_count']} 条；之后新增的冻结为下一版本。")


def main():
    main_with_args(None)


if __name__ == "__main__":
    main()
