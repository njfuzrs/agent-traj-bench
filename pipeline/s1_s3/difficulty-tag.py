#!/usr/bin/env python3
"""Phase 1 W3 Day 4: 难度初打标 — 基于 trajectory 特征做三档粗分"""

import json
from pathlib import Path
from collections import Counter

DEDUP_FILE = Path("data/bench-staging/meta/duplicate-groups.jsonl")
OUT_FILE = Path("data/bench-staging/meta/difficulty-tagged.jsonl")


def classify_difficulty(task: dict) -> str:
    """基于 group 内成员的 trajectory 特征判定难度"""
    members = task.get("members", [])
    if not members:
        return "easy"

    # 取 group 内所有成员的最大值（代表任务复杂度上限）
    max_steps = max(m.get("steps", 0) for m in members)
    max_tools = max(m.get("tool_call_count", 0) for m in members)

    # 计算平均值
    avg_steps = sum(m.get("steps", 0) for m in members) / len(members)
    avg_tools = sum(m.get("tool_call_count", 0) for m in members) / len(members)

    # 三档判定（参考 01-phase-1 §4.6.1）
    # easy: trajectory_len ≤ 5 且 tool_call ≤ 3
    # medium: 5 < trajectory_len ≤ 15 或 tool_call ≤ 8
    # hard: trajectory_len > 15 或 tool_call > 8

    if avg_steps <= 5 and avg_tools <= 3:
        return "easy"
    elif avg_steps > 15 or avg_tools > 8:
        return "hard"
    else:
        return "medium"


def main():
    tasks = []
    with open(DEDUP_FILE) as f:
        for line in f:
            tasks.append(json.loads(line))

    print(f"Total tasks: {len(tasks)}")

    difficulty_counts = Counter()
    priority_difficulty = {}  # priority -> {difficulty -> count}

    with open(OUT_FILE, "w") as out:
        for task in tasks:
            difficulty = classify_difficulty(task)
            task["difficulty"] = difficulty
            out.write(json.dumps(task, ensure_ascii=False) + "\n")

            difficulty_counts[difficulty] += 1
            key = task["priority"]
            if key not in priority_difficulty:
                priority_difficulty[key] = Counter()
            priority_difficulty[key][difficulty] += 1

    total = len(tasks)
    print(f"\n{'='*50}")
    print(f"难度初打标结果")
    print(f"{'='*50}")
    print(f"\n总体分布:")
    for d in ["easy", "medium", "hard"]:
        c = difficulty_counts[d]
        print(f"  {d}: {c} ({c/total*100:.1f}%)")

    print(f"\n按优先级 × 难度交叉表:")
    print(f"  {'priority':<20} {'easy':>6} {'medium':>8} {'hard':>6} {'total':>6}")
    print(f"  {'-'*46}")
    for p in ["P0_multi_model", "P1_repeated", "P2_solo"]:
        pd = priority_difficulty.get(p, Counter())
        row_total = sum(pd.values())
        print(f"  {p:<20} {pd['easy']:>6} {pd['medium']:>8} {pd['hard']:>6} {row_total:>6}")

    # 打印 hard task 示例
    hard_tasks = [t for t in tasks if t["difficulty"] == "hard"]
    print(f"\nHard task 示例 (前 5):")
    for t in hard_tasks[:5]:
        avg_steps = sum(m["steps"] for m in t["members"]) / len(t["members"])
        avg_tools = sum(m["tool_call_count"] for m in t["members"]) / len(t["members"])
        print(f"  {t['task_id']}: members={t['member_count']}, avg_steps={avg_steps:.0f}, avg_tools={avg_tools:.0f}")
        print(f"    query: {t['representative_query'][:80]}")


if __name__ == "__main__":
    main()
