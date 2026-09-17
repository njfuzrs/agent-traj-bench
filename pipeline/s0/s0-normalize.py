#!/usr/bin/env python3
"""s0-normalize.py — S0 归一化：6019 条 session.traj → meta/sessions-v2.jsonl

出处：bench-curation-design.md §4.2「S0 归一化入库」+ §9 Phase 0

与 v0.1 的 extract-meta.py 的区别（这是本脚本存在的理由）：
  1. 拆两层。v0.1 的 all-sessions.jsonl 达 51MB，因为把 500 字符 user_query 和
     文件数组全塞进了索引。本脚本索引只留 instruction_len，正文落
     instructions/<sid>.txt 按需加载，目标索引 <10MB。
  2. 逐 step 扫 trajectory。v0.1 只读 metadata 层，这是它 must_modify_files_in
     覆盖率仅 1.5% 的根因 —— metadata.files_edited 常为空，但轨迹里的 Edit 调用
     带着完整 file_path。新增 n_edit_ops / n_error_ops / n_test_cmds /
     file_paths_hash 四个字段必须逐 step 才能得到。
  3. repo 三路反解（见 repo_map.py）。锚定率从 metadata.working_directory 的
     38.8% 提升到 90.6%（实测 600 条抽样，steps>=3）。
  4. provenance 标注。v1.3 §8.5 的边界：claude-trace v0.2.0 起才采集 git 状态，
     本批数据 git 状态永久缺失。用字段标注升级前/后，供使用者筛选。

批次口径：本脚本处理 `data/pulled_sessions/` 下的**全部**会话目录，包括上一轮
被手工移入 `_trash/` 的 1722 条（已移回，见 repo_map.load_legacy_trashed 的说明）。
「哪些该淘汰」由 Phase 1 的 S1 按规则判定，S0 只负责如实归一化并标注。

用法：
  python3 scripts/phase0/s0-normalize.py                  # 全量
  python3 scripts/phase0/s0-normalize.py --limit 200      # 抽样试跑
  python3 scripts/phase0/s0-normalize.py --workers 8      # 指定并行度

验收：python3 scripts/phase0/verify-s0.py
"""

import argparse
import collections
import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import repo_map  # noqa: E402

SESSIONS_DIR = os.environ.get("SESSIONS_DIR", "data/pulled_sessions")
OUT_DIR = os.environ.get("OUT_DIR", "data/bench-staging/meta")
OUT_FILE = os.path.join(OUT_DIR, "sessions-v2.jsonl")
INSTR_DIR = os.path.join(OUT_DIR, "instructions")
STATS_FILE = os.path.join(OUT_DIR, "sessions-v2.stats.json")

# 厂商归一化（§4.2）。顺序敏感：先匹配到的先算，故把长前缀放前面。
VENDOR_RULES = [
    ("claude", "anthropic"),
    ("deepseek", "deepseek"),
    ("gpt", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("glm", "zhipu"),
    ("qwen", "alibaba"),
    ("kimi", "moonshot"),
    ("grok", "xai"),
    ("gemini", "google"),
    ("doubao", "bytedance"),
]

# 写操作工具（大小写混用是真实分布：Edit 1099 / edit 56 / Write 182 / write 22）
WRITE_TOOLS = {
    "edit", "write", "multiedit", "apply_patch", "notebookedit",
    "str_replace_editor", "create_file",
}

# 执行 shell 的工具
SHELL_TOOLS = {"bash", "exec_command", "shell", "run_command", "run_terminal_cmd"}

# 测试/门禁命令。绑定的是仓库真实存在的门禁（§2.3 修订：tsc 不是 sid-code 的门禁，
# 但仍统计，因为 <私有前端仓> 上它有意义）。
TEST_CMD_RE = re.compile(
    r"\b(bun\s+test|vitest|jest|pytest|py\.test|go\s+test|cargo\s+test"
    r"|npm\s+(?:run\s+)?test|pnpm\s+(?:run\s+)?test|yarn\s+test"
    r"|make\s+(?:test|lint|build|check)"
    r"|oxlint|eslint|ruff\s+check|alembic\s+check"
    r"|format:check|lint:boundary|docs:lint|docs:index-check"
    r"|tsc\b)"
)

# 用户指令抽取时要跳过的系统标签（沿用 v0.1 extract-meta.py 的口径）
SKIP_PREFIXES = (
    "<system-reminder>",
    "<local-command",
    "<command-name>",
    "[SUGGESTION MODE",
    "The user stepped away",
    "Caveat:",
)

_ABS_PATH = re.compile(r"/(?:Users|home|private|tmp|var)/[^\s\"'`,)\]}]+")


def normalize_vendor(model: str) -> str:
    m = (model or "").lower()
    for key, vendor in VENDOR_RULES:
        if key in m:
            return vendor
    return "unknown"


def extract_instruction(data: dict) -> str:
    """提取首条真实用户指令。优先 metadata.user_prompts，回落到 history 扫描"""
    prompts = (data.get("metadata") or {}).get("user_prompts") or []
    for p in prompts:
        text = p if isinstance(p, str) else (p.get("text", "") if isinstance(p, dict) else "")
        text = (text or "").strip()
        if text and not text.startswith(SKIP_PREFIXES) and len(text) > 10:
            return text

    for msg in data.get("history", []):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            text = (block.get("text") or "").strip()
            if text and not text.startswith(SKIP_PREFIXES) and len(text) > 10:
                return text
    return ""


def scan_trajectory(trajectory: list) -> dict:
    """逐 step 扫描。v0.1 缺的就是这一步。"""
    tool_calls = 0
    unique_tools: set = set()
    n_edit_ops = 0
    n_rebuildable_writes = 0
    n_error_ops = 0
    n_test_cmds = 0
    test_cmds: collections.Counter = collections.Counter()
    file_paths: set = set()
    n_parse_error = 0

    for step in trajectory:
        if not isinstance(step, dict):
            continue

        if step.get("message_type") == "observation":
            if step.get("is_error"):
                n_error_ops += 1
            continue

        tool = step.get("tool_name") or ""
        if tool:
            tool_calls += 1
            unique_tools.add(tool)
        tool_input = step.get("tool_input")
        if not isinstance(tool_input, dict):
            continue

        tool_l = tool.lower()

        # 写操作 + diff 可重建性（§2.3：按写调用 96.9% 可重建，
        # 不可重建的主因是采集时 JSON 截断 _parse_error）
        if tool_l in WRITE_TOOLS:
            n_edit_ops += 1
            if tool_input.get("_parse_error"):
                n_parse_error += 1
            elif (
                ("old_string" in tool_input and "new_string" in tool_input)
                or "content" in tool_input
                or "edits" in tool_input
                or "patch" in tool_input
            ):
                n_rebuildable_writes += 1

        # 测试/门禁命令
        if tool_l in SHELL_TOOLS:
            cmd = tool_input.get("command") or tool_input.get("cmd") or ""
            if isinstance(cmd, list):
                cmd = " ".join(str(c) for c in cmd)
            if isinstance(cmd, str) and cmd:
                for m in TEST_CMD_RE.finditer(cmd):
                    n_test_cmds += 1
                    test_cmds[m.group(1).split()[0]] += 1

        # 文件路径集合（供 file_paths_hash 与 S5 去重使用）
        for key in ("file_path", "path", "notebook_path", "filePath"):
            value = tool_input.get(key)
            if isinstance(value, str) and value.startswith("/"):
                file_paths.add(value)

    return {
        "tool_call_count": tool_calls,
        "unique_tools": sorted(unique_tools),
        "n_edit_ops": n_edit_ops,
        "n_rebuildable_writes": n_rebuildable_writes,
        "n_parse_error_writes": n_parse_error,
        "n_error_ops": n_error_ops,
        "n_test_cmds": n_test_cmds,
        "test_cmds": dict(test_cmds.most_common()),
        "n_file_paths": len(file_paths),
        "file_paths_hash": hashlib.sha256(
            "\n".join(sorted(file_paths)).encode()
        ).hexdigest()[:16] if file_paths else "",
        "_file_paths": sorted(file_paths),
    }


def detect_provenance(metadata: dict) -> str:
    """升级前/后 provenance（v1.3 §8.5 的强制要求）

    claude-trace v0.2.0（2026-09-04，commit e756e07）起采集 git 状态。有该字段
    的会话 base_commit 可直接锚定；无的只能靠时间反查 + mirror 快照。

    ⚠️ 只认 `git_state` / `git_head`，**不能把 `metadata.git` 算进来**。
    后者是另一条更早的采集路径留下的旧字段，结构完全不同
    （`{sha, branch, originUrl}`，无 dirty / upstream / worktree 信息），
    全库 19 条，且都不是升级后采的。初版把它一并当作 post_upgrade，
    导致统计出「post_upgrade 19 条」的假象 —— 实际升级后新采的会话
    一条都没带上 git 状态（根因见 §9.3：proxy 进程未重启，跑的是旧二进制）。
    """
    if metadata.get("git_state") or metadata.get("git_head"):
        return "post_upgrade"
    return "pre_upgrade"


def process_one(sid: str) -> dict | None:
    traj_path = os.path.join(SESSIONS_DIR, sid, "session.traj")
    raw_path = os.path.join(SESSIONS_DIR, sid, "raw.jsonl")
    events_path = os.path.join(SESSIONS_DIR, sid, "events.jsonl")
    if not os.path.exists(traj_path):
        return None
    try:
        with open(traj_path) as f:
            data = json.load(f)
    except Exception as e:
        return {"_error": f"{sid}: {type(e).__name__}: {e}"}

    metadata = data.get("metadata") or {}
    trajectory = data.get("trajectory") or []
    scan = scan_trajectory(trajectory)
    resolved = repo_map.resolve_repo(metadata, trajectory, raw_path)

    # 自指污染排除清单命中判定（S4 强制引用，这里只做标注不做淘汰）
    excluded_hit = False
    repo = resolved["repo"]
    if repo:
        repo_abs = os.path.join(repo_map.CODE_ROOT, repo) + "/"
        prefixes = repo_map.load_excluded_prefixes()
        for path in scan["_file_paths"]:
            # worktree 副本要先剥掉，否则相对路径算错
            idx = path.find("/.claude/worktrees/")
            if idx > 0:
                tail = path[idx + len("/.claude/worktrees/"):]
                path = repo_abs + tail.split("/", 1)[1] if "/" in tail else repo_abs
            if path.startswith(repo_abs) and repo_map.is_excluded_path(
                path[len(repo_abs):], prefixes
            ):
                excluded_hit = True
                break

    instruction = extract_instruction(data)
    model = metadata.get("model") or "unknown"

    record = {
        "sid": sid,
        "model": model,
        "vendor": normalize_vendor(model),
        "start_time": metadata.get("start_time"),
        "end_time": metadata.get("end_time"),
        "steps": metadata.get("total_steps") or 0,
        "total_api_calls": metadata.get("total_api_calls") or 0,
        "tokens_in": metadata.get("total_tokens_sent") or 0,
        "tokens_out": metadata.get("total_tokens_received") or 0,
        "tokens_cache_read": metadata.get("total_cache_read_tokens") or 0,
        "tokens_cache_creation": metadata.get("total_cache_creation_tokens") or 0,
        "total_tokens": metadata.get("total_tokens") or 0,
        "cost_usd": metadata.get("total_cost_usd") or 0,
        "exit_status": metadata.get("exit_status") or "",
        "working_directory": metadata.get("working_directory") or "",
        "repo": resolved["repo"],
        "repo_resolution": resolved["repo_resolution"],
        "repo_signals": resolved["repo_signals"],
        "has_thinking": bool(metadata.get("has_thinking")),
        "has_sub_agent": bool(metadata.get("has_sub_agent")),
        "instruction_len": len(instruction),
        "excluded_hit": excluded_hit,
        "provenance": detect_provenance(metadata),
        # 采集通道。线上 8591 条不是单一来源（Claude Code / Codex / sid-code），
        # 字段集与模型分布都不同，混在一起统计会得出错误结论。见 repo_map.detect_agent_source
        "agent_source": repo_map.detect_agent_source(sid, metadata),
        # 上一轮被手工移入 _trash/ 的会话。原始层只增不删，淘汰在元数据层表达 ——
        # 目录已移回主目录（否则 pull.py 会把这 1722 条全部重下）
        "legacy_trashed": sid in repo_map.load_legacy_trashed(),
        "has_raw": os.path.exists(raw_path),
        "has_events": os.path.exists(events_path),
        "trajectory_len": len(trajectory),
    }
    record.update({k: v for k, v in scan.items() if not k.startswith("_")})
    record["_instruction"] = instruction
    return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个会话（试跑）")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(INSTR_DIR, exist_ok=True)

    sids = repo_map.iter_session_dirs(SESSIONS_DIR)
    if args.limit:
        sids = sids[: args.limit]
    print(f"待处理 {len(sids)} 个会话目录，并行度 {args.workers}")

    t0 = time.time()
    written = 0
    errors: list[str] = []
    stats: collections.Counter = collections.Counter()
    repo_dist: collections.Counter = collections.Counter()
    res_dist: collections.Counter = collections.Counter()
    source_dist: collections.Counter = collections.Counter()

    with open(OUT_FILE, "w") as out, ProcessPoolExecutor(args.workers) as pool:
        for i, rec in enumerate(pool.map(process_one, sids, chunksize=32)):
            if rec is None:
                stats["no_traj"] += 1
                continue
            if "_error" in rec:
                errors.append(rec["_error"])
                continue

            instruction = rec.pop("_instruction", "")
            if instruction:
                with open(os.path.join(INSTR_DIR, f"{rec['sid']}.txt"), "w") as f:
                    f.write(instruction)

            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            written += 1

            stats["total"] += 1
            if rec["steps"] >= 3:
                stats["steps_ge3"] += 1
                if rec["repo"]:
                    stats["steps_ge3_anchored"] += 1
                res_dist[rec["repo_resolution"]] += 1
                repo_dist[rec["repo"] or "(unresolved)"] += 1
            if rec["excluded_hit"]:
                stats["excluded_hit"] += 1
            if rec["provenance"] == "post_upgrade":
                stats["post_upgrade"] += 1
            if rec["legacy_trashed"]:
                stats["legacy_trashed"] += 1
            source_dist[rec["agent_source"]] += 1

            if (i + 1) % 1000 == 0:
                print(f"  [{i+1}/{len(sids)}] {time.time()-t0:.0f}s")

    ge3 = stats["steps_ge3"]
    anchored = stats["steps_ge3_anchored"]
    summary = {
        "written": written,
        "no_traj": stats["no_traj"],
        "parse_errors": len(errors),
        "steps_ge3": ge3,
        "steps_ge3_anchored": anchored,
        "anchor_rate": round(anchored / ge3, 4) if ge3 else 0,
        "excluded_hit": stats["excluded_hit"],
        "post_upgrade": stats["post_upgrade"],
        "legacy_trashed": stats["legacy_trashed"],
        "agent_source_dist": dict(source_dist.most_common()),
        "resolution_dist": dict(res_dist.most_common()),
        "repo_dist": dict(repo_dist.most_common(25)),
        "elapsed_sec": round(time.time() - t0, 1),
        "index_bytes": os.path.getsize(OUT_FILE),
    }
    with open(STATS_FILE, "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n写入 {written} 条 → {OUT_FILE}")
    print(f"索引体积 {summary['index_bytes']/1024/1024:.1f} MB（目标 <10MB）")
    print(f"指令正文 → {INSTR_DIR}/")
    print(f"steps>=3: {ge3}，锚定 {anchored} = {summary['anchor_rate']:.1%}（验收线 ≥85%）")
    print(f"置信度分布: {summary['resolution_dist']}")
    print(f"命中自指污染前缀: {stats['excluded_hit']} 条")
    print(f"provenance=post_upgrade: {stats['post_upgrade']} 条")
    print(f"采集通道分布: {summary['agent_source_dist']}")
    print(f"上一轮已清洗标记(legacy_trashed): {stats['legacy_trashed']} 条")
    print(f"解析失败 {len(errors)}，缺主文件 {stats['no_traj']}，耗时 {summary['elapsed_sec']}s")
    for e in errors[:5]:
        print(f"  {e}")
    if len(errors) > 5:
        print(f"  ... 另 {len(errors)-5} 条")
    print(f"统计 → {STATS_FILE}")


if __name__ == "__main__":
    main()
