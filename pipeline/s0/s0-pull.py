#!/usr/bin/env python3
"""
s0-pull.py — 从轨迹平台把会话拉进本仓分析湖（云端 → 本地）

每个会话落 3 个文件：session.traj、raw.jsonl、events.jsonl。
本文件只负责「平台 HTTP → 本地湖」。归一化仍是 s0-normalize.py。

落盘默认本仓 `data/pulled_sessions/`（已 gitignore，不入库）。
原始层只增不删：去重只看 `<sid>/.pulled`，不要靠移目录表达淘汰
（上一轮 `_trash/` 让 1722 条被当成未拉取重下）。

去重（指纹）：
- `.pulled` 记录拉取时云端指纹（end_time / total_steps / duration_ms / exit_status）
- 列表 API 元数据与指纹一致 → 跳过；不一致 → 覆盖重拉
- end_time 为空 → 进行中，每次必拉
- missing（云端确认不存在）视为已拉取，不重试

凭据与地址全走环境变量，仓内无默认端点：
    export TRAJ_PLATFORM_URL=...     # 必填，平台基地址
    export TRAJ_AUTH_PASS=...        # 必填，管理台口令
    export TRAJ_AUTH_USER=admin      # 可选
    export TRAJ_PULL_DIR=...         # 可选，覆盖落盘目录
    export SESSIONS_DIR=...          # 可选，TRAJ_PULL_DIR 未设时用（与清洗层对齐）

用法（从仓根）：
    python3 pipeline/s0/s0-pull.py
    python3 pipeline/s0/s0-pull.py --all
    python3 pipeline/s0/s0-pull.py --session <session_id>
    python3 pipeline/s0/s0-pull.py --limit 50
    python3 pipeline/s0/s0-pull.py --since 2026-04-01
    python3 pipeline/s0/s0-pull.py --until 2026-05-01
    python3 pipeline/s0/s0-pull.py --workers 2
    python3 pipeline/s0/s0-pull.py --list-only
"""

# 让类型注解延迟求值(PEP 563),使 dict | None 等 PEP 604 写法在 Python 3.9 上也能运行
from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlencode, urlparse

# pipeline/s0/s0-pull.py → 仓根。禁止 Path(__file__).parent（会写成 pipeline/s0/data/）
REPO_ROOT = Path(__file__).resolve().parents[2]


def _require_env(name: str) -> str:
    """读必填环境变量。缺失即退出 —— 仓内无默认端点、无内置口令。"""
    val = os.environ.get(name, "")
    if not val:
        raise SystemExit(f"缺少必需的环境变量 {name}（平台地址与口令不入库，须显式 export）")
    return val


def _default_sessions_dir() -> Path:
    """落盘目录：TRAJ_PULL_DIR > SESSIONS_DIR > 仓根 data/pulled_sessions。"""
    for key in ("TRAJ_PULL_DIR", "SESSIONS_DIR"):
        val = os.environ.get(key, "").strip()
        if val:
            return Path(val)
    return REPO_ROOT / "data" / "pulled_sessions"


PLATFORM_URL = _require_env("TRAJ_PLATFORM_URL")
AUTH_USER = os.environ.get("TRAJ_AUTH_USER", "admin")
AUTH_PASS = _require_env("TRAJ_AUTH_PASS")
LOCAL_SESSIONS_DIR = _default_sessions_dir()

# 会话文件清单 → (本地文件名, API 路径后缀, 内容形态)
# raw_bytes: 直接二进制写入(后端已经自动解压 .gz)
# json_items: 后端返回 {items: [...]},还原成 jsonl(每行一个 JSON)
SESSION_FILES = [
    ("session.traj", "raw", "raw_bytes"),
    ("raw.jsonl", "raw-data", "json_items"),
    ("events.jsonl", "events", "json_items"),
]

PAGE_SIZE = 100
# 默认并发 2（原为 5）。实测把后端压出 HTTP 502 的失败数随并发单调下降：
#   8 并发 → 653 条失败（占 74%）  3 并发 → 357  2 并发 → 219  串行 → 216 降到 47
# 失败全是 502/500、无一条 missing，逐条串行重试全部成功 —— 服务端承载问题，
# 不是数据损坏。会话文件平均 8.6MB × 3 个，8 并发相当于让后端同时从 OSS
# 拉 200MB 并解压。
# 并发在这里是负优化：失败的会话下一轮还要重拉，同一份数据下载多次，总时间更长。
DEFAULT_WORKERS = 2
HTTP_TIMEOUT = 60


def _auth_header() -> str:
    token = base64.b64encode(f"{AUTH_USER}:{AUTH_PASS}".encode()).decode()
    return f"Basic {token}"


def _http_get(path: str, query: dict | None = None) -> tuple[int, bytes]:
    """带重试的 HTTP GET,返回 (status, body_bytes)"""
    parsed = urlparse(PLATFORM_URL)
    host = parsed.hostname or ""
    if not host:
        raise RuntimeError(f"PLATFORM_URL 解析失败,缺少 host: {PLATFORM_URL}")
    is_https = parsed.scheme == "https"
    port = parsed.port or (443 if is_https else 80)
    base = (parsed.path or "").rstrip("/")
    full_path = base + path
    if query:
        full_path += "?" + urlencode({k: v for k, v in query.items() if v is not None})

    last_err: Exception | None = None
    for attempt in range(3):
        conn = None
        try:
            if is_https:
                conn = http.client.HTTPSConnection(host, port, timeout=HTTP_TIMEOUT)
            else:
                conn = http.client.HTTPConnection(host, port, timeout=HTTP_TIMEOUT)
            conn.request("GET", full_path, headers={
                "Authorization": _auth_header(),
                "Accept": "application/json, application/octet-stream",
            })
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, data
        except Exception as e:
            last_err = e
            if attempt < 2:
                time.sleep([2, 5][attempt])
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    raise RuntimeError(f"HTTP GET 失败: {path} ({last_err})")


def list_sessions(since: str | None, until: str | None, limit: int | None) -> list[dict]:
    """翻页拉取会话列表(按 start_time 降序),返回 list[dict]"""
    sessions: list[dict] = []
    page = 1
    while True:
        status, data = _http_get("/api/v1/trajectories", query={
            "page": page,
            "page_size": PAGE_SIZE,
            "sort": "-start_time",
            "start_date": since,
            "end_date": until,
        })
        if status != 200:
            raise RuntimeError(f"列表拉取失败 HTTP {status}: {data[:200].decode(errors='replace')}")

        payload = json.loads(data)
        items = payload.get("items", [])
        if not items:
            break
        sessions.extend(items)

        total = payload.get("total", 0)
        if len(sessions) >= total:
            break
        if limit and len(sessions) >= limit:
            break
        page += 1

    if limit:
        sessions = sessions[:limit]
    return sessions


def pull_one_file(
    session_id: str, basename: str, api_suffix: str, kind: str,
    target_dir: Path, force: bool,
) -> str:
    """拉取单个文件。返回 ok / skipped / missing / error:..."""
    target = target_dir / basename
    if target.exists() and not force:
        return "skipped"

    path = f"/api/v1/trajectories/{session_id}/detail/{api_suffix}"
    status, data = _http_get(path)
    if status == 404:
        return "missing"
    if status != 200:
        return f"error: HTTP {status}"

    target_dir.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")

    if kind == "raw_bytes":
        tmp.write_bytes(data)
    else:
        try:
            payload = json.loads(data)
        except json.JSONDecodeError as e:
            return f"error: parse json {e}"
        items = payload.get("items", []) if isinstance(payload, dict) else []
        with open(tmp, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False))
                f.write("\n")

    # 原子替换,避免半写文件
    tmp.replace(target)
    return "ok"


def pull_session(session_id: str, force: bool, fingerprint: dict | None = None) -> tuple[str, dict[str, str]]:
    """拉取单个会话所有文件,完成后落 .pulled 标记(含指纹)"""
    target_dir = LOCAL_SESSIONS_DIR / session_id
    results: dict[str, str] = {}
    for basename, api_suffix, kind in SESSION_FILES:
        try:
            results[basename] = pull_one_file(
                session_id, basename, api_suffix, kind, target_dir, force,
            )
        except Exception as e:
            results[basename] = f"error: {e}"

    # 没有 error 就落标记(missing 视为云端确认不存在,不再重试)
    if not any(v.startswith("error") for v in results.values()):
        target_dir.mkdir(parents=True, exist_ok=True)
        marker = target_dir / ".pulled"
        marker.write_text(json.dumps({
            "pulled_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "files": results,
            "fingerprint": fingerprint or {},
        }, ensure_ascii=False, indent=2))

    return session_id, results


def fingerprint_of(session: dict) -> dict:
    """从列表 API 返回的会话元数据提取指纹

    指纹包含:
    - end_time:    会话结束时间(空 = 进行中)
    - exit_status: 退出状态(空 = 进行中)
    - total_steps: 步骤数,会话追加内容必变
    - duration_ms: 持续时长,同上
    """
    return {
        "end_time": session.get("end_time") or "",
        "exit_status": session.get("exit_status") or "",
        "total_steps": session.get("total_steps") or 0,
        "duration_ms": session.get("duration_ms") or 0,
    }


def should_skip(session: dict) -> tuple[bool, str]:
    """判断会话是否可跳过。返回 (跳过?, 原因)"""
    sid = session["session_id"]
    marker = LOCAL_SESSIONS_DIR / sid / ".pulled"

    if not marker.exists():
        return False, "未拉取"

    # 进行中的会话(end_time 为空):每次都重拉,跟踪最新进度
    cur_fp = fingerprint_of(session)
    if not cur_fp["end_time"]:
        return False, "进行中"

    try:
        marker_data = json.loads(marker.read_text())
    except (json.JSONDecodeError, OSError):
        return False, "标记损坏"

    saved_fp = marker_data.get("fingerprint") or {}

    # 老格式标记(没有指纹)按"已结束 + 一致"处理,不重拉
    if not saved_fp:
        return True, "已拉取(老格式)"

    if saved_fp == cur_fp:
        return True, "指纹一致"

    return False, "指纹变化"


def _summarize(results: dict[str, str]) -> tuple[bool, bool]:
    """返回 (有错误, 有新增)"""
    has_error = any(v.startswith("error") for v in results.values())
    has_new = any(v == "ok" for v in results.values())
    return has_error, has_new


def main():
    parser = argparse.ArgumentParser(description="从轨迹平台拉取会话到本仓分析湖")
    parser.add_argument("--all", action="store_true", help="全量拉取(覆盖本地已有文件)")
    parser.add_argument("--session", help="只拉单个会话(session_id)")
    parser.add_argument("--limit", type=int, help="最多拉取 N 条(按 start_time 倒序)")
    parser.add_argument("--since", help="起始日期 YYYY-MM-DD")
    parser.add_argument("--until", help="截止日期 YYYY-MM-DD")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help=f"并发数(默认 {DEFAULT_WORKERS})")
    parser.add_argument("--list-only", action="store_true", help="只列出待拉取的会话")
    args = parser.parse_args()

    print(f"平台地址: {PLATFORM_URL}")
    print(f"本地目录: {LOCAL_SESSIONS_DIR}")
    print()

    force = args.all

    # 模式 1:单会话
    if args.session:
        print(f"拉取单会话: {args.session}")
        # 单会话路径不查列表,无指纹;走 force 覆盖
        _, results = pull_session(args.session, force=True, fingerprint=None)
        for fn, st in results.items():
            mark = "✅" if st in ("ok", "skipped") else "❌"
            print(f"  {mark} {fn}: {st}")
        sys.exit(0 if not any(v.startswith("error") for v in results.values()) else 1)

    # 模式 2:批量
    print("拉取会话列表...")
    sessions = list_sessions(since=args.since, until=args.until, limit=args.limit)
    if not sessions:
        print("云端无符合条件的会话")
        return
    print(f"  云端共 {len(sessions)} 条会话")

    # 区分:全新 / 进行中 / 指纹变化 / 已完成无变更
    pending: list[tuple[dict, str]] = []   # (session, 原因)
    skipped_count = 0
    for s in sessions:
        if force:
            pending.append((s, "强制全量"))
            continue
        skip, reason = should_skip(s)
        if skip:
            skipped_count += 1
        else:
            pending.append((s, reason))

    print(f"  本地完整: {skipped_count},待拉取: {len(pending)}")

    # 待拉取的明细按"原因"分组打印,方便用户看出哪些是因为变更而重拉
    if pending and not args.list_only:
        from collections import Counter
        reason_stats = Counter(r for _, r in pending)
        for reason, cnt in reason_stats.most_common():
            print(f"    └─ {reason}: {cnt}")

    if not pending:
        print("\n无新会话需要拉取")
        return

    if args.list_only:
        print()
        for s, reason in pending:
            sid = s["session_id"]
            ts = (s.get("start_time") or "")[:19]
            prompt = (s.get("first_prompt") or "").replace("\n", " ").replace("\r", " ")[:60]
            print(f"  [{reason}]  {sid}  [{ts}]  {prompt}")
        return

    print(f"\n开始拉取(并发 {args.workers})...\n")

    total = len(pending)
    ok_count = 0
    err_count = 0
    nochange_count = 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        # 进行中或指纹变化的会话需要 force=True 覆盖旧文件;全新的不需要
        def _submit(s_reason: tuple[dict, str]):
            s, reason = s_reason
            need_force = force or reason in ("进行中", "指纹变化", "标记损坏")
            return pool.submit(
                pull_session, s["session_id"], need_force, fingerprint_of(s),
            )

        futures = {_submit(p): p for p in pending}
        for i, fut in enumerate(as_completed(futures), 1):
            s, reason = futures[fut]
            sid = s["session_id"]
            ts = (s.get("start_time") or "")[:19]

            try:
                _, results = fut.result()
            except Exception as e:
                err_count += 1
                print(f"[{i}/{total}] ❌ {sid[:12]} 异常: {e}")
                continue

            has_error, has_new = _summarize(results)
            summary = " ".join(f"{fn}={st}" for fn, st in results.items())

            if has_error:
                err_count += 1
                print(f"[{i}/{total}] ❌ {sid[:12]} [{ts}] [{reason}] {summary}")
            elif has_new:
                ok_count += 1
                print(f"[{i}/{total}] ✅ {sid[:12]} [{ts}] [{reason}] {summary}")
            else:
                nochange_count += 1

    print(f"\n拉取完成: 新增/更新 {ok_count},无变更 {nochange_count},失败 {err_count}")
    sys.exit(0 if err_count == 0 else 1)


if __name__ == "__main__":
    main()
