#!/usr/bin/env python3
"""Phase 1 W2 Day 1: 从 2441 条 session.traj 提取扁平化元数据到 all-sessions.jsonl"""

import json
import os
import hashlib
import time
from pathlib import Path

SESSIONS_DIR = Path("data/pulled_sessions")
OUT_DIR = Path("data/bench-staging/meta")
OUT_FILE = OUT_DIR / "all-sessions.jsonl"

SKIP_PREFIXES = (
    "<system-reminder>",
    "<local-command",
    "<command-name>",
    "[SUGGESTION MODE",
    "The user stepped away",
)


def extract_user_query(data: dict) -> str:
    """从 history 中提取第一条真实用户输入（跳过系统标签）"""
    for m in data.get("history", []):
        if m.get("role") != "user":
            continue
        content = m.get("content", "")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "").strip()
                    if any(text.startswith(p) for p in SKIP_PREFIXES):
                        continue
                    if len(text) > 10:
                        return text[:500]
        elif isinstance(content, str):
            text = content.strip()
            if any(text.startswith(p) for p in SKIP_PREFIXES):
                continue
            if len(text) > 10:
                return text[:500]
    return ""


def extract_tool_stats(traj: list) -> tuple[int, list[str]]:
    """统计工具调用次数和去重工具名列表"""
    tool_names = set()
    count = 0
    for step in traj:
        if not isinstance(step, dict):
            continue
        action = step.get("action")
        if step.get("message_type") == "action" and action:
            if isinstance(action, dict):
                tool = action.get("tool", "")
                if tool:
                    tool_names.add(tool)
                    count += 1
            elif isinstance(action, str) and action not in ("final_answer",):
                tool_names.add(action)
                count += 1
        elif step.get("tool_name"):
            count += 1
            tool_names.add(step["tool_name"])
    return count, sorted(tool_names)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    session_dirs = sorted(os.listdir(SESSIONS_DIR))
    total = len(session_dirs)
    errors = []
    written = 0

    t0 = time.time()
    with open(OUT_FILE, "w") as out:
        for idx, sid_dir in enumerate(session_dirs):
            traj_path = SESSIONS_DIR / sid_dir / "session.traj"
            if not traj_path.exists():
                continue

            try:
                with open(traj_path) as f:
                    data = json.load(f)

                traj = data.get("trajectory", [])
                metadata = data.get("metadata", {})

                user_query = extract_user_query(data)
                query_hash = hashlib.sha256(user_query.encode()).hexdigest()[:16]
                tool_call_count, unique_tools = extract_tool_stats(traj)

                record = {
                    "sid": sid_dir,
                    "model": metadata.get("model") or "unknown",
                    "exit_status": metadata.get("exit_status", ""),
                    "steps": metadata.get("total_steps", 0),
                    "tokens_in": metadata.get("total_tokens_sent", 0),
                    "tokens_out": metadata.get("total_tokens_received", 0),
                    "total_cost_usd": metadata.get("total_cost_usd", 0),
                    "trajectory_len": len(traj),
                    "history_len": len(data.get("history", [])),
                    "tool_call_count": tool_call_count,
                    "unique_tools": unique_tools,
                    "user_query": user_query,
                    "query_hash": query_hash,
                    "has_thinking": metadata.get("has_thinking", False),
                    "has_sub_agent": metadata.get("has_sub_agent", False),
                    "start_time": metadata.get("start_time"),
                    "end_time": metadata.get("end_time"),
                    "file_size": traj_path.stat().st_size,
                    "files_edited": metadata.get("files_edited", []),
                    "tools_used": metadata.get("tools_used", []),
                }
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                written += 1
            except Exception as e:
                errors.append(f"{sid_dir}: {e}")

            if (idx + 1) % 500 == 0:
                print(f"  [{idx+1}/{total}] processed...")

    elapsed = time.time() - t0
    print(f"\nDone: {written} records written to {OUT_FILE}")
    print(f"Time: {elapsed:.1f}s")
    print(f"Errors: {len(errors)}")
    if errors:
        for e in errors[:10]:
            print(f"  {e}")
        if len(errors) > 10:
            print(f"  ... and {len(errors)-10} more")


if __name__ == "__main__":
    main()
