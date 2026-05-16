#!/usr/bin/env python3
"""Phase 1 W2 Day 5: 粗筛 — trivial 筛除 + 失败筛除"""

import json
import os
import time
from pathlib import Path
from collections import Counter

META_FILE = Path("data/bench-staging/meta/all-sessions.jsonl")
OUT_DIR = Path("data/bench-staging/meta")
SESSIONS_DIR = Path("data/pulled_sessions")

TRIVIAL_OUT = OUT_DIR / "trivial-filtered.jsonl"
FAILED_OUT = OUT_DIR / "failed-filtered.jsonl"
CANDIDATE_OUT = OUT_DIR / "candidate-pool.jsonl"


def is_trivial(record: dict) -> tuple[bool, str]:
    """判定是否为 trivial session"""
    steps = record.get("steps", 0)
    tool_call_count = record.get("tool_call_count", 0)
    tokens_in = record.get("tokens_in", 0)
    tokens_out = record.get("tokens_out", 0)
    user_query = record.get("user_query", "")
    trajectory_len = record.get("trajectory_len", 0)

    # 空 session（steps=0 且无 trajectory）
    if steps == 0 and trajectory_len == 0:
        return True, "empty_session"

    # 纯文本闲聊（steps < 3 且无工具调用）
    if steps < 3 and tool_call_count == 0:
        return True, "no_tool_short"

    # 一次工具调用就完事的太简单
    if steps < 3 and tool_call_count == 1:
        return True, "single_tool_short"

    # 过短（token 总量 < 1000）
    if tokens_in + tokens_out < 1000:
        return True, "too_few_tokens"

    # 测试性输入（query 太短且无工具）
    if len(user_query) < 20 and tool_call_count == 0:
        return True, "test_input"

    return False, ""


def is_failed(record: dict) -> tuple[bool, str]:
    """基于元数据判定是否为失败/中断 session（粗判，不开原始文件）"""
    exit_status = record.get("exit_status", "")
    steps = record.get("steps", 0)
    trajectory_len = record.get("trajectory_len", 0)
    tool_call_count = record.get("tool_call_count", 0)

    # 明确的用户中断
    if exit_status == "user_interrupt":
        return True, "user_interrupt"

    # partial（未完成）
    if exit_status == "partial":
        return True, "partial"

    # max_tokens（被截断）
    if exit_status == "max_tokens":
        return True, "max_tokens"

    # steps > 0 但 trajectory 为空（数据异常）
    if steps > 0 and trajectory_len == 0:
        return True, "data_anomaly"

    return False, ""


def check_trajectory_failure(sid: str) -> tuple[bool, str]:
    """深度检查：读 trajectory 末尾判断是否以错误结束"""
    traj_path = SESSIONS_DIR / sid / "session.traj"
    if not traj_path.exists():
        return False, ""

    try:
        with open(traj_path) as f:
            data = json.load(f)

        traj = data.get("trajectory", [])
        if not traj:
            return True, "empty_trajectory"

        # 检查最后一个 step
        last = traj[-1]
        if not isinstance(last, dict):
            return False, ""

        content = str(last.get("content", ""))

        # 末尾是错误消息
        if last.get("message_type") == "error":
            return True, "ended_with_error"

        # 末尾内容包含明显错误标志且是最后一步
        error_markers = [
            "Error:", "Traceback (most recent call last)",
            "command not found", "permission denied",
            "FATAL", "panic:", "segmentation fault",
        ]
        if any(marker in content for marker in error_markers):
            # 但如果 trajectory 很长（>10 steps），末尾一个错误不代表整体失败
            if len(traj) <= 3:
                return True, "ended_with_tool_error"

        return False, ""
    except Exception:
        return False, ""


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 加载所有元数据
    records = []
    with open(META_FILE) as f:
        for line in f:
            records.append(json.loads(line))

    print(f"Total records: {len(records)}")

    trivial_records = []
    failed_records = []
    candidate_records = []

    trivial_reasons = Counter()
    failed_reasons = Counter()

    t0 = time.time()
    deep_check_count = 0

    for record in records:
        # 先检查 trivial
        is_triv, reason = is_trivial(record)
        if is_triv:
            record["filter_reason"] = reason
            trivial_records.append(record)
            trivial_reasons[reason] += 1
            continue

        # 再检查失败（元数据级）
        is_fail, reason = is_failed(record)
        if is_fail:
            record["filter_reason"] = reason
            failed_records.append(record)
            failed_reasons[reason] += 1
            continue

        # 对 exit_status 异常的做深度检查（读原始文件）
        exit_status = record.get("exit_status", "")
        if exit_status in ("", "unknown"):
            deep_check_count += 1
            is_fail, reason = check_trajectory_failure(record["sid"])
            if is_fail:
                record["filter_reason"] = reason
                failed_records.append(record)
                failed_reasons[reason] += 1
                continue

        # 通过筛选，进入候选池
        candidate_records.append(record)

    elapsed = time.time() - t0

    # 写输出文件
    with open(TRIVIAL_OUT, "w") as f:
        for r in trivial_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with open(FAILED_OUT, "w") as f:
        for r in failed_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with open(CANDIDATE_OUT, "w") as f:
        for r in candidate_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 打印报告
    print(f"\n{'='*60}")
    print(f"粗筛结果 (耗时 {elapsed:.1f}s, 深度检查 {deep_check_count} 条)")
    print(f"{'='*60}")
    print(f"\n原始: {len(records)}")
    print(f"Trivial 筛掉: {len(trivial_records)} ({len(trivial_records)/len(records)*100:.1f}%)")
    for reason, count in trivial_reasons.most_common():
        print(f"  {reason}: {count}")
    print(f"\n失败/中断筛掉: {len(failed_records)} ({len(failed_records)/len(records)*100:.1f}%)")
    for reason, count in failed_reasons.most_common():
        print(f"  {reason}: {count}")
    print(f"\n候选池: {len(candidate_records)} ({len(candidate_records)/len(records)*100:.1f}%)")

    # 候选池模型分布
    model_dist = Counter(r.get("model", "unknown") for r in candidate_records)
    print(f"\n候选池模型分布:")
    for model, count in model_dist.most_common():
        print(f"  {model}: {count}")


if __name__ == "__main__":
    main()
