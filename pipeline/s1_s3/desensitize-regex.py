#!/usr/bin/env python3
"""Phase 1 W2 Day 2: Layer 1 正则脱敏 — 确定性、零成本、快速"""

import json
import os
import re
import time
from pathlib import Path
from dataclasses import dataclass, field

SESSIONS_DIR = Path("data/pulled_sessions")
OUT_DIR = Path("data/bench-staging/desensitized")
AUDIT_FILE = Path("data/bench-staging/audit/secrets-found.jsonl")

# 公开邮箱域名白名单（不脱敏）
PUBLIC_EMAIL_DOMAINS = {
    "gmail.com", "qq.com", "163.com", "126.com", "outlook.com",
    "hotmail.com", "yahoo.com", "foxmail.com", "icloud.com",
    "protonmail.com", "github.com", "example.com", "test.com",
}

# 正则模式定义
PATTERNS = [
    # Anthropic API key
    ("anthropic_key", re.compile(r"sk-ant-[a-zA-Z0-9_\-]{20,}"), "sk-ant-REDACTED"),
    # OpenAI API key
    ("openai_key", re.compile(r"sk-[a-zA-Z0-9]{32,}"), "sk-REDACTED"),
    # AWS Access Key
    ("aws_key", re.compile(r"AKIA[0-9A-Z]{16}"), "AKIA-REDACTED"),
    # 通用 token/secret/password 赋值
    ("generic_secret", re.compile(
        r'(?i)(token|secret|password|api_key|apikey|auth_token|access_token|private_key)'
        r'[\"\s:=]+["\']?([a-zA-Z0-9_\-\.]{16,})["\']?'
    ), None),  # 特殊处理：保留 key 名，替换值
    # 私有 IP
    ("private_ip", re.compile(
        r"\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
        r"172\.(1[6-9]|2[0-9]|3[0-1])\.\d{1,3}\.\d{1,3}|"
        r"192\.168\.\d{1,3}\.\d{1,3})\b"
    ), "<INTERNAL_IP>"),
    # 内网域名
    ("internal_domain", re.compile(
        r"\b[a-zA-Z0-9\-]+\.(internal|local|corp|intranet|inc|alibaba-inc|bytedance|meituan)"
        r"(\.[a-zA-Z]{2,})?\b"
    ), "<INTERNAL_DOMAIN>"),
    # 手机号（国内）
    ("phone_cn", re.compile(r"\b1[3-9]\d{9}\b"), "<PHONE>"),
    # 身份证号
    ("id_number", re.compile(r"\b\d{17}[\dxX]\b"), "<ID_NUMBER>"),
    # 邮箱（排除公开域名）
    ("email", re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b"), None),  # 特殊处理
]

# 不脱敏的路径模式（避免过度脱敏）
SAFE_IP_PATTERNS = re.compile(r"\b(127\.0\.0\.1|0\.0\.0\.0|localhost)\b")


@dataclass
class DesensitizeResult:
    replacements: list = field(default_factory=list)
    has_secrets: bool = False


def desensitize_text(text: str, result: DesensitizeResult) -> str:
    """对一段文本执行正则脱敏"""
    if not text or not isinstance(text, str):
        return text

    for pattern_name, regex, replacement in PATTERNS:
        if pattern_name == "private_ip":
            # 排除安全 IP
            for match in regex.finditer(text):
                ip = match.group(0)
                if SAFE_IP_PATTERNS.match(ip):
                    continue
                result.replacements.append({
                    "type": pattern_name,
                    "before": ip,
                    "after": "<INTERNAL_IP>",
                    "layer": "regex",
                })
                result.has_secrets = True
            text = regex.sub(
                lambda m: m.group(0) if SAFE_IP_PATTERNS.match(m.group(0)) else "<INTERNAL_IP>",
                text
            )
        elif pattern_name == "generic_secret":
            def replace_secret(m):
                key_name = m.group(1)
                value = m.group(2)
                # 跳过明显的占位符
                if value.lower() in ("your_key_here", "xxx", "placeholder", "changeme"):
                    return m.group(0)
                result.replacements.append({
                    "type": pattern_name,
                    "before": f"{key_name}=***",
                    "after": f"{key_name}=REDACTED",
                    "layer": "regex",
                })
                result.has_secrets = True
                return m.group(0).replace(value, "REDACTED")
            text = regex.sub(replace_secret, text)
        elif pattern_name == "email":
            def replace_email(m):
                email = m.group(0)
                domain = email.split("@")[1].lower()
                if domain in PUBLIC_EMAIL_DOMAINS:
                    return email
                result.replacements.append({
                    "type": "email",
                    "before": email[:3] + "***@" + domain,
                    "after": "<EMAIL>",
                    "layer": "regex",
                })
                result.has_secrets = True
                return "<EMAIL>"
            text = regex.sub(replace_email, text)
        else:
            matches = regex.findall(text)
            if matches:
                for match_val in matches:
                    if isinstance(match_val, tuple):
                        match_val = match_val[0]
                    result.replacements.append({
                        "type": pattern_name,
                        "before": match_val[:20] + "..." if len(str(match_val)) > 20 else str(match_val),
                        "after": replacement,
                        "layer": "regex",
                    })
                result.has_secrets = True
                text = regex.sub(replacement, text)

    return text


def desensitize_obj(obj, result: DesensitizeResult):
    """递归脱敏 JSON 对象中的所有字符串"""
    if isinstance(obj, str):
        return desensitize_text(obj, result)
    elif isinstance(obj, list):
        return [desensitize_obj(item, result) for item in obj]
    elif isinstance(obj, dict):
        return {k: desensitize_obj(v, result) for k, v in obj.items()}
    return obj


def process_session(sid_dir: str) -> dict | None:
    """处理单条 session，返回审计记录（如有敏感信息）"""
    traj_path = SESSIONS_DIR / sid_dir / "session.traj"
    if not traj_path.exists():
        return None

    out_session_dir = OUT_DIR / sid_dir
    out_session_dir.mkdir(parents=True, exist_ok=True)

    with open(traj_path) as f:
        data = json.load(f)

    result = DesensitizeResult()

    # 脱敏 trajectory 和 history
    desensitized_data = {
        "trajectory": desensitize_obj(data.get("trajectory", []), result),
        "history": desensitize_obj(data.get("history", []), result),
        "info": data.get("info", {}),
        "metadata": desensitize_obj(data.get("metadata", {}), result),
    }

    # 写脱敏后的 trajectory
    with open(out_session_dir / "trajectory.json", "w") as f:
        json.dump(desensitized_data, f, ensure_ascii=False)

    # 写脱敏日志
    with open(out_session_dir / "desensitization.log", "w") as f:
        for r in result.replacements:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 写 manifest
    manifest = {
        "sid": sid_dir,
        "model": data.get("metadata", {}).get("model", "unknown"),
        "replacement_count": len(result.replacements),
        "has_secrets": result.has_secrets,
        "layer": "regex",
    }
    with open(out_session_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # 返回审计记录
    if result.has_secrets:
        types_found = list({r["type"] for r in result.replacements})
        return {
            "sid": sid_dir,
            "replacement_count": len(result.replacements),
            "types": types_found,
            "severity": classify_severity(result.replacements),
        }
    return None


def classify_severity(replacements: list) -> str:
    """根据命中类型判定严重程度"""
    types = {r["type"] for r in replacements}
    # high: 真实 API key 或身份证
    if types & {"anthropic_key", "openai_key", "aws_key", "id_number"}:
        return "high"
    # medium: 内网域名 + 通用 secret
    if types & {"internal_domain", "generic_secret"}:
        return "medium"
    # low: 邮箱、手机、私有 IP
    return "low"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)

    session_dirs = sorted(os.listdir(SESSIONS_DIR))
    total = len(session_dirs)
    secrets_count = 0
    processed = 0

    t0 = time.time()
    with open(AUDIT_FILE, "w") as audit_out:
        for idx, sid_dir in enumerate(session_dirs):
            traj_path = SESSIONS_DIR / sid_dir / "session.traj"
            if not traj_path.exists():
                continue

            audit_record = process_session(sid_dir)
            if audit_record:
                audit_out.write(json.dumps(audit_record, ensure_ascii=False) + "\n")
                secrets_count += 1
            processed += 1

            if (idx + 1) % 500 == 0:
                elapsed = time.time() - t0
                print(f"  [{idx+1}/{total}] processed={processed}, secrets={secrets_count}, time={elapsed:.0f}s")

    elapsed = time.time() - t0
    print(f"\nDone: {processed} sessions processed")
    print(f"Secrets found: {secrets_count} sessions")
    print(f"Time: {elapsed:.1f}s")

    # 打印 severity 分布
    if AUDIT_FILE.exists():
        severities = {"high": 0, "medium": 0, "low": 0}
        with open(AUDIT_FILE) as f:
            for line in f:
                rec = json.loads(line)
                severities[rec["severity"]] = severities.get(rec["severity"], 0) + 1
        print(f"Severity: high={severities['high']}, medium={severities['medium']}, low={severities['low']}")


if __name__ == "__main__":
    main()
