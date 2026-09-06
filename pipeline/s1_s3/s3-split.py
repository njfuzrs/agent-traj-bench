#!/usr/bin/env python3
"""s3-split.py — S3 会话切分：filtered-v2.jsonl 保留集 → units-v2.jsonl

出处：bench-curation-design.md §4.3「S3 会话切分」+ §9.4 坑① + Phase 1 任务表

判定逻辑在 `s3_segment.py`（单测直接引用它）；本脚本只负责读盘、映射、落盘。

## 为什么必须切分

实测 steps p90=204、最大 4284，`>100 steps` 的会话占 20.5%。一条 4284 步的会话
显然不是「一个任务」。v0.1 把整条会话当一个 task，产出了 `estimated_turns: 134`
配 `max_steps: 45` 这种自相矛盾的断言。

## 三种单元来源（ended_by 字段区分）

| ended_by | 含义 | 后续处置 |
|---|---|---|
| `next_task` | 后面还有新任务，本单元正常收尾 | 进 S4 |
| `session_end` | 会话最后一个单元且未中断 | 进 S4 |
| `interrupted` | 会话末尾被打断的单元 | **直接淘汰**（未完成，无从判定期望结果） |
| `no_raw_jsonl` | 无 raw.jsonl，整条会话作单个单元 | steps>100 一并淘汰（§4.3） |

淘汰同样不删记录 —— 写 `keep: false` + `drop_reason`，与 S1 一致。

## 原始层只读

只 open() 读 `data/pulled_sessions/`，产物全部写 `data/bench-staging/phase1/`。

用法：
  python3 scripts/phase1/s3-split.py --batch v0.2
  python3 scripts/phase1/s3-split.py --batch v0.2 --limit 200      # 抽样试跑
  python3 scripts/phase1/s3-split.py --batch v0.2 --workers 8

验收：python3 scripts/phase1/verify-phase1.py --stage s3
"""

import argparse
import collections
import datetime
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import s3_segment as seg  # noqa: E402

WRITE_TOOLS = {
    "edit", "write", "multiedit", "apply_patch", "notebookedit",
    "str_replace_editor", "create_file",
}
SHELL_TOOLS = {"bash", "exec_command", "shell", "run_command", "run_terminal_cmd"}

# 与 S0 同一份口径（scripts/phase0/s0-normalize.py:TEST_CMD_RE）
import re  # noqa: E402

TEST_CMD_RE = re.compile(
    r"\b(bun\s+test|vitest|jest|pytest|py\.test|go\s+test|cargo\s+test"
    r"|npm\s+(?:run\s+)?test|pnpm\s+(?:run\s+)?test|yarn\s+test"
    r"|make\s+(?:test|lint|build|check)"
    r"|oxlint|eslint|ruff\s+check|alembic\s+check"
    r"|format:check|lint:boundary|docs:lint|docs:index-check"
    r"|tsc\b)"
)

# §4.3：无 raw.jsonl 且步数过长 → 无法确定任务边界，淘汰
NO_RAW_MAX_STEPS = 100


def read_raw_lines(path: str) -> list[dict]:
    """读 raw.jsonl。容忍单行损坏（跳过并计数，不让一行坏掉整条会话）"""
    out = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                continue
    return out


def extract_turns(raw_lines: list[dict]) -> list[dict]:
    """从 raw.jsonl 提取用户轮次

    首行读 `messages`（完整上下文），后续行读 `new_messages`（增量）。同一指令在
    增量中会重复出现，按文本去重（§4.3「需按文本去重」）。

    ## 首行只取最后一条 user 消息（否则会造出大量幻影单元）

    会话恢复（`--resume`）或 proxy 中途接入时，**首行的 `messages` 是把之前
    整段对话history 全量倒进来的**。实测 c33a9523 这条会话首行有 716 条消息、
    其中 239 条 role=user，而整条 trajectory 只有 10 步 / 5 个 action step ——
    那 239 轮的动作**根本不在本轨迹里**，它们属于上一段会话。

    不处理的后果实测过：这条会话被切成 10 个单元，其中 9 个的 step_range 全是
    `[0, 0]`、`started_at` 全等于首行时间戳 —— 因为历史轮次没有各自的时间戳，
    全部落到首行那一刻。全库口径下 **49.8% 的多单元会话存在区间重叠**，正是
    这个原因。抽样 400 条会话中 **56.5% 的首行含 >1 条 user 消息**。

    首行真正「触发这次 API 调用」的是最后一条 user 消息，之前的都是上下文。
    对全新会话，首行本来就只有 1 条 user 消息，取最后一条等价于取它本身。
    """
    turns = []
    seen: set[str] = set()
    for line_no, obj in enumerate(raw_lines):
        req = obj.get("request") or {}
        incremental = req.get("new_messages")
        msgs = incremental if incremental else (req.get("messages") or [])
        if not isinstance(msgs, list):
            continue

        user_msgs = [m for m in msgs
                     if isinstance(m, dict) and m.get("role") == "user"]
        # 首行且是全量 messages：只认最后一条 user 消息，其余是上一段会话的历史
        if line_no == 0 and not incremental and len(user_msgs) > 1:
            user_msgs = user_msgs[-1:]

        # 一行 raw = 一次 API 调用 = 最多一个「触发它的用户轮次」。
        #
        # 所以每行只产出一个轮次，取最后一个非噪声 text 块作为触发文本。
        # 不这么做的后果实测过：一行里有 6 个 text 块（真实指令 + 若干
        # 「请继续完成任务」/「Continue from where you left off」），它们共享该行
        # 时间戳，于是映射出 6 个 step_range 完全相同的单元 —— 全库 39.3% 的
        # 多单元会话存在区间重叠，同一 started_at 挂 2-7 个单元的有 402 条会话。
        #
        # 单元区间必须是轨迹的**划分**而不是**覆盖**：区间重叠会让 S4 分诊把同一
        # 段动作反复计入，下游的 edit_ops / files_touched 全部失真。
        blocks: list[str] = []
        for msg in user_msgs:
            blocks.extend(seg.user_text_blocks(msg))
        if not blocks:
            continue
        text = blocks[-1].strip()
        key = text[:200]
        if key in seen:
            continue
        seen.add(key)
        turns.append({
            "raw_index": obj.get("index"),
            "ts": obj.get("timestamp"),
            "ts_epoch": seg.parse_ts(obj.get("timestamp")),
            "text": text,
        })

    # 按时间戳排序 —— **raw.jsonl 的行序不等于时间序**。
    #
    # 实测 400 条抽样中 18.2% 的会话时间戳非单调（最严重的 d6766405 在 405 行里
    # 有 112 处逆序），原因是子 agent 并发请求交错写入同一个文件。
    # 不排序的后果：切分点按文件顺序排列，映射出的 step_range 会倒退
    # （实测 ca8430d9 出现 seq4=[51,51] → seq5=[49,49] → seq6=[43,43]），
    # 「时间间隔 >30 分钟」这条强信号也会算出负数间隔而永不触发。
    turns.sort(key=lambda t: (t["ts"] or "", t["raw_index"] or 0))
    return turns


def action_timeline(traj: list) -> list[tuple[str, int]]:
    """trajectory 里 action step 的 (timestamp, step_index) 序列

    只有 action step 带 timestamp（observation 全部无，§4.3 实测），
    所以时间轴由 action 步构成。
    """
    out = []
    for i, step in enumerate(traj):
        if not isinstance(step, dict):
            continue
        if step.get("message_type") == "action" and step.get("timestamp"):
            out.append((step["timestamp"], i))
    return out


def map_step_range(
    start_ts: str | None,
    end_ts: str | None,
    timeline: list[tuple[str, int]],
) -> list[int] | None:
    """按时间戳把 raw 行区间映射回 trajectory 步区间

    为什么按时间戳而不按 index 算术推导：实测 40 条抽样中 35 条 raw 行时间戳与
    action step 时间戳**完全逐一相等**，而 raw 行数与 trajectory 步数不成固定
    倍数（0ce08c20 是 40 行 / 216 action，比例 5.4；14bdb107 是 13 行 / 21 action，
    比例 1.6）。按比例换算会系统性错位。

    时间戳是字符串比较 —— ISO 8601 同精度下字典序等于时间序，且实测同一会话内
    格式一致，无需解析成 datetime。
    """
    if not timeline or not start_ts:
        return None
    lo = None
    for ts, idx in timeline:
        if ts >= start_ts:
            lo = idx
            break
    if lo is None:
        # 起点晚于所有 action step：本轮次后面没有动作了
        return [timeline[-1][1], timeline[-1][1]]
    if end_ts is None:
        hi = timeline[-1][1]
    else:
        hi = lo
        for ts, idx in timeline:
            if ts < end_ts:
                hi = max(hi, idx)
            else:
                break
    return [lo, max(lo, hi)]


def enforce_partition(ranges: list[list[int] | None]) -> list[list[int] | None]:
    """把一组 step_range 强制成互不重叠且递增的划分

    规则：逐个往后扫，把每个区间的起点抬到「前一个区间末步 + 1」；若抬过了自己的
    末步，说明这个单元在轨迹上没有独占的动作，记 None（下游据此知道它无动作可归）。

    为什么不是「重叠就报错」：重叠是数据本身的性质（时间戳等值、并发子 agent），
    不是代码 bug，报错只会让 27.5% 的多单元会话全部无法处理。划分是可判定的
    修正方式，且信息损失可见 —— None 明确表示「这个单元没有独占区间」。
    """
    out: list[list[int] | None] = []
    prev_hi: int | None = None
    for rng in ranges:
        if rng is None:
            out.append(None)
            continue
        lo, hi = rng
        if prev_hi is not None and lo <= prev_hi:
            lo = prev_hi + 1
        if lo > hi:
            out.append(None)
            continue
        out.append([lo, hi])
        prev_hi = hi
    return out


def scan_step_range(traj: list, rng: list[int] | None, whole: bool = False) -> dict:
    """统计一个步区间内的写操作、报错、测试命令、涉及文件

    与 S0 的 scan_trajectory 同口径，但作用在**区间**而非整条会话上 ——
    单元级的客观量必须只算本单元的，否则 S4 分诊会按整条会话的数字判断。
    """
    files: set[str] = set()
    tools: set[str] = set()
    edit_ops = error_ops = n_test = 0
    test_cmds: collections.Counter = collections.Counter()

    # `rng is None` 有两种含义，必须由调用方用 whole 参数区分，不能在这里猜：
    #   · 无 raw.jsonl 的会话 → 整条轨迹就是这一个单元（whole=True）
    #   · enforce_partition 判定「本单元无独占区间」→ 不能算任何动作（whole=False）
    # 混同两者会让后者继承整条会话的 edit_ops，客观量直接虚高。
    if rng is None:
        if not whole:
            return {
                "files_touched": [], "unique_tools": [], "edit_ops": 0,
                "error_ops": 0, "n_test_cmds": 0, "test_cmds": {},
            }
        lo, hi = 0, len(traj) - 1
    else:
        lo, hi = rng[0], rng[1]

    for step in traj[lo:hi + 1]:
        if not isinstance(step, dict):
            continue
        if step.get("message_type") == "observation":
            if step.get("is_error"):
                error_ops += 1
            continue
        tool = (step.get("tool_name") or "")
        if tool:
            tools.add(tool)
        tool_input = step.get("tool_input")
        if not isinstance(tool_input, dict):
            continue
        tool_l = tool.lower()
        if tool_l in WRITE_TOOLS:
            edit_ops += 1
            fp = tool_input.get("file_path") or tool_input.get("path")
            if isinstance(fp, str) and fp:
                files.add(fp)
        if tool_l in SHELL_TOOLS:
            cmd = tool_input.get("command") or tool_input.get("cmd") or ""
            if isinstance(cmd, list):
                cmd = " ".join(str(c) for c in cmd)
            if isinstance(cmd, str) and cmd:
                for m in TEST_CMD_RE.finditer(cmd):
                    n_test += 1
                    test_cmds[m.group(1).strip()] += 1

    return {
        "files_touched": sorted(files),
        "unique_tools": sorted(tools),
        "edit_ops": edit_ops,
        "error_ops": error_ops,
        "n_test_cmds": n_test,
        "test_cmds": dict(test_cmds),
    }


def split_session(rec: dict) -> list[dict]:
    """切分一条会话，返回单元列表。rec 来自 filtered-v2.jsonl（keep=true）"""
    sid = rec["sid"]
    prov = {k: rec.get(k) for k in common.PROVENANCE_FIELDS}
    forced = bool(rec.get("forced_split"))

    traj_path = common.session_file(sid, "session.traj")
    traj: list = []
    try:
        with open(traj_path, encoding="utf-8", errors="replace") as f:
            traj = (json.load(f) or {}).get("trajectory") or []
    except (OSError, json.JSONDecodeError, ValueError):
        traj = []

    raw_path = common.session_file(sid, "raw.jsonl")
    turns: list[dict] = []
    if os.path.exists(raw_path):
        turns = extract_turns(read_raw_lines(raw_path))

    def unit(n: int, ended_by: str, rng, started_at, instr, reason_extra=None):
        scan = scan_step_range(traj, rng, whole=(ended_by == "no_raw_jsonl"))
        keep = True
        drop = None
        # §4.3：中断的单元与无边界的超长会话淘汰
        if ended_by == "interrupted":
            keep, drop = False, "U_INTERRUPTED"
        elif ended_by == "no_raw_jsonl" and (rec.get("steps") or 0) > NO_RAW_MAX_STEPS:
            keep, drop = False, "U_NO_BOUNDARY"
        elif reason_extra:
            keep, drop = False, reason_extra
        return {
            "unit_id": f"{sid}#{n:02d}",
            "sid": sid,
            "seq": n,
            "keep": keep,
            "drop_reason": drop,
            "ended_by": ended_by,
            "raw_index_range": None,
            "step_range": rng,
            "started_at": started_at,
            "instruction_raw": (instr or "")[:4000],
            "instruction_len": len(instr or ""),
            **scan,
            "session_steps": rec.get("steps") or 0,
            "has_raw": bool(rec.get("has_raw")),
            **prov,
        }

    # 无 raw.jsonl 或提取不到轮次 → 整条会话作单个单元（§4.3）
    if not turns:
        instr = ""
        instr_path = os.path.join(common.INSTR_DIR, f"{sid}.txt")
        if os.path.exists(instr_path):
            try:
                with open(instr_path, encoding="utf-8", errors="replace") as f:
                    instr = f.read()
            except OSError:
                instr = ""
        u = unit(1, "no_raw_jsonl", None, rec.get("start_time"), instr)
        u["boundary_reason"] = "B_NO_RAW"
        u["boundary_confidence"] = seg.boundary_confidence("B_NO_RAW")
        u["raw_index_range"] = None
        return [u]

    # 先给每个轮次算出「本轮次内改了哪些文件」，强信号 2 才有判据。
    #
    # 这一步不能省：decide_boundary 的 B_FILE_DISJOINT 要比对「本轮次文件集」与
    # 「前一任务文件集」。若轮次上不带 files，该信号永远不触发 —— 三条强信号里
    # 静默少一条，切分退化成「只看时间间隔 + 起始词」。实测漏掉它时
    # B_FILE_DISJOINT 计数为 0，正是这个症状。
    timeline = action_timeline(traj)
    for i, t in enumerate(turns):
        nxt_ts = turns[i + 1]["ts"] if i + 1 < len(turns) else None
        rng = map_step_range(t["ts"], nxt_ts, timeline)
        t["files"] = scan_step_range(traj, rng)["files_touched"] if rng else []

    # 逐轮次判定边界。prev_files 累积「上一个边界以来所有轮次」碰过的文件 ——
    # 一个任务往往跨多轮追问才改完文件，只取相邻轮次会让交集判定过于敏感。
    boundaries: list[dict] = []
    prev_turn = None
    prev_files: set[str] = set()
    for t in turns:
        is_bd, reason = seg.decide_boundary(t, prev_turn, prev_files)
        if is_bd:
            boundaries.append({**t, "boundary_reason": reason})
            prev_files = set(t.get("files") or [])
        else:
            prev_files |= set(t.get("files") or [])
        prev_turn = t

    if not boundaries:
        boundaries = [{**turns[0], "boundary_reason": "B_FIRST"}]

    # 先算出全部区间，再强制成「划分」：单元区间必须互不重叠、按 seq 递增。
    #
    # 排序已经消除了大部分乱序，但仍有残余重叠 —— 时间戳精度到微秒也可能相等，
    # 且 action step 的时间轴与 raw 行时间轴不是一一对应。区间重叠会让 S4 把
    # 同一段动作反复计入多个单元，edit_ops / files_touched 全部虚高。
    ranges: list[list[int] | None] = []
    for i, b in enumerate(boundaries):
        nxt = boundaries[i + 1] if i + 1 < len(boundaries) else None
        ranges.append(map_step_range(b["ts"], nxt["ts"] if nxt else None, timeline))
    ranges = enforce_partition(ranges)

    units = []
    for i, b in enumerate(boundaries):
        nxt = boundaries[i + 1] if i + 1 < len(boundaries) else None
        rng = ranges[i]
        is_last = nxt is None
        if is_last:
            ended_by = "interrupted" if forced else "session_end"
        else:
            ended_by = "next_task"
        u = unit(i + 1, ended_by, rng, b["ts"], b["text"])
        u["boundary_reason"] = b["boundary_reason"]
        u["boundary_confidence"] = seg.boundary_confidence(b["boundary_reason"])
        u["raw_index_range"] = [
            b.get("raw_index"),
            (nxt.get("raw_index") if nxt else None),
        ]
        units.append(u)

    # 文件集合交集判定需要「前一单元的文件」，逐单元回填后重算一次弱信号
    # 不再做：boundaries 已定，回填只会让 unit 数变化，破坏 unit_id 稳定性。
    return units


def _worker(rec: dict) -> list[dict]:
    try:
        return split_session(rec)
    except Exception as exc:  # noqa: BLE001
        return [{
            "unit_id": f"{rec['sid']}#error",
            "sid": rec["sid"],
            "seq": 0,
            "keep": False,
            "drop_reason": "U_SPLIT_ERROR",
            "error": f"{type(exc).__name__}: {exc}"[:200],
            **{k: rec.get(k) for k in common.PROVENANCE_FIELDS},
        }]


def main(argv: list[str] | None = None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", default="v0.2")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条（试跑）")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default=common.UNITS)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if not os.path.exists(common.FILTERED):
        raise SystemExit(f"S1 产物不存在：{common.FILTERED}\n  先跑 s1-filter.py")
    filtered = common.read_jsonl(common.FILTERED)
    kept = [r for r in filtered if r.get("keep")]
    bad_batch = [r for r in kept if r.get("batch_version") != args.batch]
    if bad_batch:
        raise SystemExit(
            f"S1 产物的 batch_version 与 --batch {args.batch} 不符"
            f"（如 {bad_batch[0].get('batch_version')}）。重跑 s1-filter.py --batch {args.batch}"
        )
    if args.limit:
        kept = kept[:args.limit]

    t0 = datetime.datetime.now()
    print(f"S3 会话切分 — 输入 {len(kept)} 条会话（S1 保留集），并行度 {args.workers}")

    units: list[dict] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for i, res in enumerate(pool.map(_worker, kept, chunksize=16), 1):
            units.extend(res)
            if i % 1000 == 0:
                el = (datetime.datetime.now() - t0).total_seconds()
                print(f"  [{i}/{len(kept)}] {el:.0f}s，累计 {len(units)} 单元")

    kept_units = [u for u in units if u.get("keep")]
    per_session = collections.Counter(u["sid"] for u in units)
    multi = sum(1 for n in per_session.values() if n >= 2)
    bd_dist = collections.Counter(u.get("boundary_reason") for u in units)
    end_dist = collections.Counter(u.get("ended_by") for u in units)
    drop_dist = collections.Counter(
        u.get("drop_reason") for u in units if not u.get("keep")
    )
    src_dist = collections.Counter(u.get("agent_source") for u in kept_units)
    mapped = sum(1 for u in units if u.get("step_range"))

    stats = {
        "batch_version": args.batch,
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input_sessions": len(kept),
        "total_units": len(units),
        "kept_units": len(kept_units),
        "dropped_units": len(units) - len(kept_units),
        "units_per_session": round(len(units) / max(len(kept), 1), 3),
        "sessions_with_multi_units": multi,
        "multi_unit_rate": round(multi / max(len(kept), 1), 4),
        "step_range_mapped": mapped,
        "step_range_mapped_rate": round(mapped / max(len(units), 1), 4),
        "boundary_reason_dist": dict(bd_dist.most_common()),
        "ended_by_dist": dict(end_dist.most_common()),
        "drop_reason_dist": dict(drop_dist.most_common()),
        "kept_by_agent_source": dict(src_dist.most_common()),
        "elapsed_sec": round((datetime.datetime.now() - t0).total_seconds(), 1),
    }

    print(f"\n  产出 {stats['total_units']} 单元，保留 {stats['kept_units']}")
    print(f"  平均 {stats['units_per_session']} 单元/会话，"
          f"多单元会话 {multi} = {stats['multi_unit_rate']:.1%}")
    print(f"  step_range 映射成功 {mapped} = {stats['step_range_mapped_rate']:.1%}")
    print(f"  边界信号：{stats['boundary_reason_dist']}")
    print(f"  收尾方式：{stats['ended_by_dist']}")
    print(f"  淘汰归因：{stats['drop_reason_dist']}")
    print(f"  保留单元按通道：{stats['kept_by_agent_source']}")

    if args.dry_run:
        print("\n--dry-run，未写文件")
        return

    common.write_jsonl(args.out, units)
    stats_path = args.out.replace(".jsonl", ".stats.json")
    with open(stats_path, "w") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"\n产物 → {args.out}")
    print(f"统计 → {stats_path}")
    print("原始层未改动：data/pulled_sessions/ 只读")


if __name__ == "__main__":
    main()
