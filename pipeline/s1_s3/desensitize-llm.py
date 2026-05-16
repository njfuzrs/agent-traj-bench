#!/usr/bin/env python3
"""Phase 1 W2 Day 3: Layer 2 LLM 复扫 — 用 claude-haiku-4-5 做语义级敏感信息审核"""

import json
import os
import time
import sys
from pathlib import Path
from openai import OpenAI

OUT_DIR = Path("data/bench-staging/desensitized")
AUDIT_FILE = Path("data/bench-staging/audit/secrets-found-llm.jsonl")
META_FILE = Path("data/bench-staging/meta/all-sessions.jsonl")

# LLM 配置
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "http://127.0.0.1:4000") + "/v1"
MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 512

SYSTEM_PROMPT = """你是一个数据脱敏审核员。下面是某 coding agent 的 trajectory 片段（已经过基础正则脱敏）。
请检查是否还残留以下信息:
1. 真实公司名（国内一线/二线互联网公司、央企国企、知名外企）
2. 真实产品名（知名度 ≥ "国内 top 50 APP"水平）
3. 真实业务代码（疑似公司内部业务逻辑，而非通用框架代码）
4. 任何可能用于身份识别的细节（真实姓名、工号、内部系统名等）

判定原则：这条信息泄露是否会让作者被法务追究 / 让对应的真实用户感到被冒犯？是→标记；否→忽略。

不要标记以下内容：
- 开源项目名、公开框架名（React, Vue, Express 等）
- 公开的 GitHub 用户名
- 通用路径如 /Users/xxx/Code/project
- 已被替换为 <REDACTED>/<INTERNAL_DOMAIN>/<EMAIL> 等占位符的内容
- 通用 SQL schema、通用 API 设计

输出严格 JSON 格式（不要 markdown 代码块）:
{"has_residual_secrets": bool, "categories": [...], "evidence": [{"snippet": "...", "reason": "..."}], "severity": "low/medium/high"}

severity 判定:
- high: 真实 API key 残留 / 身份证号 / 明确的公司内部系统完整代码
- medium: 真实公司名 / 真实产品名 / 内部域名残留
- low: 可能的个人信息但不确定 / 模糊的业务逻辑"""


def extract_snippet(session_dir: Path, max_chars: int = 4000) -> str:
    """从脱敏后的 trajectory 提取片段送审"""
    traj_file = session_dir / "trajectory.json"
    if not traj_file.exists():
        return ""

    with open(traj_file) as f:
        data = json.load(f)

    # 提取 trajectory 中的文本内容（截断到 max_chars）
    parts = []
    total = 0
    for step in data.get("trajectory", []):
        if not isinstance(step, dict):
            continue
        content = step.get("content", "")
        if isinstance(content, str) and content:
            chunk = content[:1000]
            parts.append(chunk)
            total += len(chunk)
            if total >= max_chars:
                break

    # 也看 history 中的用户消息
    for msg in data.get("history", [])[:5]:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content", "")
        if isinstance(content, str) and content and total < max_chars:
            chunk = content[:500]
            parts.append(chunk)
            total += len(chunk)
        elif isinstance(content, list):
            for block in content[:3]:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")[:500]
                    if text and total < max_chars:
                        parts.append(text)
                        total += len(text)

    return "\n---\n".join(parts)[:max_chars]


def call_llm(snippet: str) -> dict | None:
    """调用 LLM 审核片段"""
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"请审核以下 trajectory 片段:\n\n{snippet}"},
            ],
            max_tokens=MAX_TOKENS,
            temperature=0,
        )
        text = resp.choices[0].message.content.strip()
        # 尝试解析 JSON
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except json.JSONDecodeError:
        return {"has_residual_secrets": False, "parse_error": True, "raw": text[:200]}
    except Exception as e:
        return {"has_residual_secrets": False, "error": str(e)}


def main():
    # 参数解析
    limit = None
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        limit = int(sys.argv[idx + 1])
        print(f"Running with limit={limit}")

    AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)

    # 获取所有已脱敏的 session 目录
    session_dirs = sorted([
        d for d in OUT_DIR.iterdir()
        if d.is_dir() and (d / "trajectory.json").exists()
    ])

    if limit:
        session_dirs = session_dirs[:limit]

    total = len(session_dirs)
    print(f"Total sessions to scan: {total}")

    findings = 0
    errors = 0
    t0 = time.time()

    with open(AUDIT_FILE, "w") as out:
        for idx, session_dir in enumerate(session_dirs):
            sid = session_dir.name
            snippet = extract_snippet(session_dir)

            if not snippet or len(snippet) < 50:
                continue

            result = call_llm(snippet)
            if result is None:
                errors += 1
                continue

            if result.get("error"):
                errors += 1
                if errors <= 5:
                    print(f"  ERROR {sid[:12]}: {result['error']}")
                continue

            if result.get("has_residual_secrets"):
                record = {
                    "sid": sid,
                    "severity": result.get("severity", "low"),
                    "categories": result.get("categories", []),
                    "evidence": result.get("evidence", []),
                    "layer": "llm",
                }
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                findings += 1

            if (idx + 1) % 50 == 0:
                elapsed = time.time() - t0
                rate = (idx + 1) / elapsed
                eta = (total - idx - 1) / rate if rate > 0 else 0
                print(f"  [{idx+1}/{total}] findings={findings}, errors={errors}, "
                      f"rate={rate:.1f}/s, ETA={eta/60:.0f}min")

    elapsed = time.time() - t0
    print(f"\nDone: {total} sessions scanned")
    print(f"Findings: {findings}")
    print(f"Errors: {errors}")
    print(f"Time: {elapsed:.1f}s ({elapsed/60:.1f}min)")

    # 打印 severity 分布
    if AUDIT_FILE.exists() and findings > 0:
        severities = {"high": 0, "medium": 0, "low": 0}
        with open(AUDIT_FILE) as f:
            for line in f:
                rec = json.loads(line)
                sev = rec.get("severity", "low")
                severities[sev] = severities.get(sev, 0) + 1
        print(f"Severity: high={severities['high']}, medium={severities['medium']}, low={severities['low']}")


if __name__ == "__main__":
    main()
