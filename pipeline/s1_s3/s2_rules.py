#!/usr/bin/env python3
"""s2_rules.py — S2 脱敏的规则层（被 s2-desensitize.py 调用，也被单测直接引用）

出处：bench-curation-design.md §4.1 S2 + Phase 1 任务表「S2 脱敏（复用 v0.1
Layer1 正则 + LLM 复扫扩到全量入选）」，验收「抽样 100 条人工确认零漏检」

拆成独立模块的理由同 s3_segment.py：零漏检是验收项，规则必须能被单测逐条覆盖。

## 相对 v0.1 的三处改进（都是实测驱动，不是重写）

v0.1 的 7 类正则（`legacy_v01/desensitize-regex.py`）本身有效，全量跑过 2441 条，
命中 1617 条。但它的 LLM 复扫（138 条样本）暴露了正则层的漏检，按频次排序：

    personal_information 39 / 真实公司名 27 / real_person_name 25 / 真实个人信息 23
    real_product_name 22 / internal_project_structure 15 / internal_file_paths 14

**改进一：把 real_person_name 从 LLM 层收回正则层。** 这是漏检 #1 类，载体几乎
全是绝对路径里的登录名 —— 实测 120 条会话抽样中 **99% 含 `/Users/<name>` 或
`/home/<name>`**，出现 `zhourusheng` 53292 次、`yaobei` 1912 次、`ethan` 289 次。
这是确定性模式，交给 LLM 判断既贵又不可靠。v0.1 的 `_ABS_PATH` 只用于统计，
没做替换，所以这批姓名原样留在了产物里。

**改进二：sk- 类 API key 加熵判定。** v0.1 的 `sk-[a-zA-Z0-9]{32,}` 会误伤分支名
与任务标识。实测命中样本里 `sk-specific-scorer-registry`、`sk-user-question-bridge`、
`sk-omission-8fixes-implemented` 都不是密钥，而 `sk-REvAV2bcQ4aARmDhi0dqH35C7tJYJiPE…`
和 `sk-2ae4ff93debf4e9c9b212f5cb002184c` 是。两者的区别不在长度而在**字符分布**：
真密钥是随机串（高熵、无词典词、大小写数字混排），假阳性是连字符分隔的英文词。

**改进三：补 shell 内联凭据。** 实测抓到 `sshpass -p '18752006620@zRs' ssh …`
这类把口令写在命令行里的用法，v0.1 的 7 类模式覆盖不到（既不是 sk- 开头，也不
匹配 `password=` 赋值形态）。

## 严重度分级（沿用 v0.1 口径）

    high    真实密钥 / 身份证 / 内联凭据 → 单元标记 needs_review，不进公开 split
    medium  内网 IP / 内网域名 / 手机号 / 邮箱 / 路径姓名 → 替换后可用
    low     其他 → 替换后可用
"""

import math
import re

# ── 熵判定：区分真密钥与形似密钥的标识符 ──────────────────────────

_WORDISH = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$")


def shannon_entropy(s: str) -> float:
    """每字符香农熵（bit）。随机 base62 串约 5.5-6.0，英文词组约 3.0-4.0"""
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def looks_like_real_key(body: str) -> bool:
    """`sk-<body>` 里的 body 是否真密钥而非标识符

    三条判据，任一否决即判为标识符：
      1. 连字符分隔的小写词组（sk-specific-scorer-registry）→ 不是密钥
      2. 熵 < 3.5 → 字符分布太规律，不像随机串
      3. 无大写且无数字 → 真密钥几乎不会全小写纯字母
    """
    if not body or len(body) < 20:
        return False
    if _WORDISH.match(body):
        return False
    if shannon_entropy(body) < 3.5:
        return False
    has_upper = any(c.isupper() for c in body)
    has_digit = any(c.isdigit() for c in body)
    return has_upper or has_digit


# ── 路径登录名 ──────────────────────────────────────────────────────

# 这些不是登录名，是系统/工具目录，替换它们会破坏路径语义
PATH_NAME_ALLOWLIST = {
    "shared", "local", "opt", "usr", "var", "tmp", "root", "runner",
    "node", "python", "lib", "bin", "etc", "home", "users", "public",
    "administrator", "default", "linuxbrew",
}

_HOME_PATH = re.compile(r"(/(?:Users|home))/([A-Za-z0-9._\-]+)")


def redact_home_paths(text: str) -> tuple[str, int]:
    """把 `/Users/zhourusheng` → `/Users/<USER>`，返回 (结果, 替换次数)

    只替换紧跟 /Users 或 /home 的那一段，路径其余部分保留 —— 下游 S4 分诊要靠
    路径里的仓库名做锚定（`repo_map.py` 的三路反解就依赖它），全路径打码会毁掉
    这条信号。
    """
    count = 0

    def sub(m: re.Match) -> str:
        nonlocal count
        prefix, name = m.group(1), m.group(2)
        if name.lower() in PATH_NAME_ALLOWLIST:
            return m.group(0)
        # 带扩展名的是文件不是用户名（如 /tmp/fix.patch 误入的情况）
        if "." in name and not name.startswith("."):
            return m.group(0)
        count += 1
        return f"{prefix}/<USER>"

    return _HOME_PATH.sub(sub, text), count


# ── 规则表 ──────────────────────────────────────────────────────────

PUBLIC_EMAIL_DOMAINS = {
    "gmail.com", "qq.com", "163.com", "126.com", "outlook.com", "hotmail.com",
    "yahoo.com", "foxmail.com", "icloud.com", "protonmail.com", "github.com",
    "example.com", "test.com", "localhost", "anthropic.com", "openai.com",
}

SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"

# (类型, 正则, 替换串或 None 表示自定义处理, 严重度)
RULES: list[tuple[str, re.Pattern, str | None, str]] = [
    ("anthropic_key", re.compile(r"sk-ant-[a-zA-Z0-9_\-]{20,}"),
     "sk-ant-<REDACTED>", SEVERITY_HIGH),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
     "<AWS_KEY_REDACTED>", SEVERITY_HIGH),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
     "<GH_TOKEN_REDACTED>", SEVERITY_HIGH),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
     "<JWT_REDACTED>", SEVERITY_HIGH),
    # sk- 泛型密钥：命中后再过熵判定（见 apply 的特判）
    ("generic_sk_key", re.compile(r"\bsk-([A-Za-z0-9_\-]{20,})"),
     None, SEVERITY_HIGH),
    # shell 内联凭据：sshpass -p 'xxx' / mysql -pxxx / --password xxx
    #
    # `(?!<[A-Z_]+>)` 是必须的：没有它，本规则会匹配自己的替换产物
    # `sshpass -p <CREDENTIAL_REDACTED>` —— 因为 `[^'"\s]{6,}` 把占位符本身也
    # 算作凭据。后果不是漏脱敏（密钥已经没了），而是**幂等自检永远报红**，
    # 分不清「还在漏」与「已脱敏」。一个不收敛的自检等于没有自检。
    ("inline_credential", re.compile(
        r"(?i)\b(sshpass\s+-p|--password[=\s]+|mysql\s+-p|curl\s+-u)\s*"
        r"['\"]?(?!<[A-Z_]+>)([^'\"\s]{6,})['\"]?"), None, SEVERITY_HIGH),
    ("id_number", re.compile(r"\b\d{17}[\dxX]\b"),
     "<ID_NUMBER>", SEVERITY_HIGH),
    # 通用赋值形态：保留 key 名，只换值
    ("generic_secret", re.compile(
        r"(?i)\b(token|secret|password|passwd|api_key|apikey|auth_token|"
        r"access_token|private_key|client_secret)"
        r"([\"'\s:=]+)([a-zA-Z0-9_\-\.]{16,})"), None, SEVERITY_HIGH),
    ("private_ip", re.compile(
        r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
        r"|192\.168\.\d{1,3}\.\d{1,3})\b"), "<INTERNAL_IP>", SEVERITY_MEDIUM),
    ("internal_domain", re.compile(
        r"\b[a-zA-Z0-9\-]+\.(?:internal|local|corp|intranet|alibaba-inc|"
        r"bytedance|meituan)(?:\.[a-zA-Z]{2,})?\b"),
     "<INTERNAL_DOMAIN>", SEVERITY_MEDIUM),
    ("phone_cn", re.compile(r"(?<![\d.])1[3-9]\d{9}(?![\d.])"),
     "<PHONE>", SEVERITY_MEDIUM),
    ("email", re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b"),
     None, SEVERITY_MEDIUM),
]

# 明确不脱敏（本机回环地址不是内网资产）
SAFE_HOSTS = re.compile(r"\b(?:127\.0\.0\.1|0\.0\.0\.0|localhost)\b")


def _sub_generic_sk(text: str, hits: list[dict]) -> str:
    """sk- 泛型密钥：只替换过了熵判定的"""
    rule = next(r for r in RULES if r[0] == "generic_sk_key")

    def sub(m: re.Match) -> str:
        body = m.group(1)
        if not looks_like_real_key(body):
            return m.group(0)      # 标识符，不动
        hits.append({"type": "generic_sk_key", "severity": rule[3],
                     "sample": m.group(0)[:12] + "…"})
        return "sk-<REDACTED>"

    return rule[1].sub(sub, text)


def _sub_inline_credential(text: str, hits: list[dict]) -> str:
    def sub(m: re.Match) -> str:
        hits.append({"type": "inline_credential", "severity": SEVERITY_HIGH,
                     "sample": m.group(1)})
        return f"{m.group(1)} <CREDENTIAL_REDACTED>"
    return next(r for r in RULES if r[0] == "inline_credential")[1].sub(sub, text)


def _sub_generic_secret(text: str, hits: list[dict]) -> str:
    def sub(m: re.Match) -> str:
        hits.append({"type": "generic_secret", "severity": SEVERITY_HIGH,
                     "sample": m.group(1)})
        return f"{m.group(1)}{m.group(2)}<REDACTED>"
    return next(r for r in RULES if r[0] == "generic_secret")[1].sub(sub, text)


def _sub_email(text: str, hits: list[dict]) -> str:
    def sub(m: re.Match) -> str:
        addr = m.group(0)
        domain = addr.rsplit("@", 1)[-1].lower()
        if domain in PUBLIC_EMAIL_DOMAINS:
            return addr
        hits.append({"type": "email", "severity": SEVERITY_MEDIUM,
                     "sample": "…@" + domain})
        return "<EMAIL>"
    return next(r for r in RULES if r[0] == "email")[1].sub(sub, text)


CUSTOM = {
    "generic_sk_key": _sub_generic_sk,
    "inline_credential": _sub_inline_credential,
    "generic_secret": _sub_generic_secret,
    "email": _sub_email,
}


def desensitize(text: str) -> tuple[str, list[dict]]:
    """对一段文本做全部规则脱敏，返回 (脱敏后文本, 命中列表)

    顺序敏感：先跑高严重度的密钥类，再跑路径姓名 —— 反过来会让
    `/Users/foo/.aws/credentials` 里的 key 先被路径规则改写掉一部分。
    """
    if not text:
        return text, []
    hits: list[dict] = []

    for name, pattern, repl, severity in RULES:
        if name in CUSTOM:
            text = CUSTOM[name](text, hits)
            continue
        found = pattern.findall(text)
        if not found:
            continue
        # 回环地址不算内网资产
        if name == "private_ip":
            text_wo_safe = SAFE_HOSTS.sub("", text)
            if not pattern.search(text_wo_safe):
                continue
        hits.append({"type": name, "severity": severity,
                     "count": len(found)})
        text = pattern.sub(repl or "<REDACTED>", text)

    text, n_home = redact_home_paths(text)
    if n_home:
        hits.append({"type": "path_username", "severity": SEVERITY_MEDIUM,
                     "count": n_home})
    return text, hits


def worst_severity(hits: list[dict]) -> str | None:
    """命中集合的最高严重度"""
    sevs = {h.get("severity") for h in hits}
    for s in (SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW):
        if s in sevs:
            return s
    return None
