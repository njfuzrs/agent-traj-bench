#!/usr/bin/env python3
"""common.py — Phase 1 清洗流水线的公共契约

出处：bench-curation-design.md §4.2（S1）、§4.3（S3）、§9 Phase 1

本模块只放**三个阶段都要遵守的契约**，不放业务逻辑：

  1. 目录布局：产物一律写 data/bench-staging/phase1/，原始层只读
  2. 源信息块（provenance）：每层产物必带的筛选维度
  3. 批次加载：只洗冻结批次，不追新增

## 为什么产物要另建目录而不在原始层加工

`data/pulled_sessions/`（62GB、8562 条）是**只读数据湖**。这不是洁癖，是踩过的坑：
`s0-pull.py` 的 `should_skip` 去重只查 `data/pulled_sessions/<sid>/.pulled`，把会话目录移走、
改名或删除，标记就跟着走，下次同步判为「未拉取」并重新下载 —— 上一轮把 1722 条
移进 `_trash/` 正是如此（实测待拉取从 879 涨到 2601，多出来的 1722 条就是它们）。

纪律：**原始层只增不删，淘汰在元数据层用字段表达**（S1 的 `drop_reason`）。
`verify-s0.py` 与 `../tests/test_s0.py` 各有一道门禁盯着 `_trash/` 不许回来。

顺带一个量级理由：入选 4653 条的 `raw.jsonl` 合计 47.6GB，原地重写脱敏既危险
又无必要 —— 只脱敏真正要用的那部分文本。

## 为什么源信息必须每层都带（用户 2026-09-05 提出，方案原文未要求）

方案 §9.4 只把 `agent_source` 当成「要不要拆批」的判断依据。不够 —— 实测四条
采集通道的模型分布完全不同（steps>=3 口径）：

    claude_code  4241 条  清一色 claude-*（opus-4-8 / opus-5 / haiku-4-5 …）
    codex         226 条  ali-deepseek-v4-pro / glm-5.2 / gpt-5.6-luna
    short_id      201 条  deepseek-v4-pro / claude-opus-4-7 / gpt-5.4
    sid_code      123 条  harbor-gateway / gpt-5.6-luna / qwen-plus

混算得到的是三种工具的加权平均，任何按模型切片的结论都会失真（§2.4 那张分布表
就是这么算出来的，不能直接当任一工具的画像用）。所以把这组字段做成**贯穿字段**，
会话级、单元级都带，并由 `verify-phase1.py` 加门禁：任何一层丢字段即报红。
"""

import json
import os

# ── 目录布局 ────────────────────────────────────────────────────────

# 只读数据湖。本模块及下游脚本**只允许 open() 读**，不许写、不许移、不许删。
SESSIONS_DIR = os.environ.get("SESSIONS_DIR", "data/pulled_sessions")

# Phase 0 的产物（索引与批次清单），只读
PHASE0_META = os.environ.get("PHASE0_META", "data/bench-staging/meta")
S0_INDEX = os.path.join(PHASE0_META, "sessions-v2.jsonl")
INSTR_DIR = os.path.join(PHASE0_META, "instructions")

# Phase 1 的产物根目录。全部新增，不覆盖 Phase 0 或 v0.1 的任何文件
PHASE1_DIR = os.environ.get("PHASE1_DIR", "data/bench-staging/phase1")
P1_META = os.path.join(PHASE1_DIR, "meta")
FILTERED = os.path.join(P1_META, "filtered-v2.jsonl")       # S1 产物
UNITS = os.path.join(P1_META, "units-v2.jsonl")             # S3 产物
DESENS_DIR = os.path.join(PHASE1_DIR, "desensitized")       # S2 产物
DESENS_AUDIT = os.path.join(P1_META, "desensitize-audit.jsonl")


def batch_path(version: str) -> str:
    return os.path.join(PHASE0_META, f"batch-{version}.json")


# ── 源信息块（provenance）────────────────────────────────────────────

# 每层产物必带的源信息字段。verify-phase1.py 逐层检查，缺一个即报红。
PROVENANCE_FIELDS = (
    "agent_source",      # 采集通道：claude_code / codex / sid_code / short_id
    "model",             # 模型名（原样，不归一化）
    "vendor",            # 厂商（anthropic / deepseek / openai / …；unknown 是真实值）
    "repo",              # 反解出的仓库，可能为 None
    "repo_resolution",   # 锚定置信度：direct / voted / inferred / conflict / unresolved
    "provenance",        # 采集器升级前后：pre_upgrade / post_upgrade
    "batch_version",     # 批次版本号，如 v0.2
)

AGENT_SOURCES = ("claude_code", "codex", "sid_code", "short_id")


def provenance_of(rec: dict, batch_version: str) -> dict:
    """从 S0 索引记录抽出源信息块

    `repo` 允许为 None（490 条 unresolved 是真实情况），但键必须在 ——
    门禁查的是「键齐全」而不是「值非空」，否则会把数据事实误判成故障。
    """
    return {
        "agent_source": rec.get("agent_source"),
        "model": rec.get("model"),
        "vendor": rec.get("vendor"),
        "repo": rec.get("repo"),
        "repo_resolution": rec.get("repo_resolution"),
        "provenance": rec.get("provenance"),
        "batch_version": batch_version,
    }


def missing_provenance(rec: dict) -> list[str]:
    """返回缺失的源信息字段名。空列表 = 齐全"""
    return [f for f in PROVENANCE_FIELDS if f not in rec]


# ── 数据加载 ────────────────────────────────────────────────────────

def load_s0_index(path: str | None = None) -> dict[str, dict]:
    """加载 S0 索引，返回 sid → 记录"""
    path = path or S0_INDEX
    if not os.path.exists(path):
        raise SystemExit(f"S0 索引不存在：{path}\n  先跑 s0/s0-normalize.py")
    out = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            out[rec["sid"]] = rec
    return out


def load_batch(version: str) -> dict:
    """加载冻结批次。Phase 1 只洗批次内的会话，不追新增数据

    为什么不直接用 S0 索引：线上日增约 77 条，索引是「当下」，批次是「快照」。
    benchmark 的 pass@1 数字必须可复现，所以有版本边界（§3.1 门槛 4，
    也是 SWE-bench / REAP 的做法）。
    """
    path = batch_path(version)
    if not os.path.exists(path):
        raise SystemExit(
            f"批次不存在：{path}\n"
            f"  先跑 python3 s0/freeze-batch.py --version {version}"
        )
    with open(path) as f:
        return json.load(f)


def read_jsonl(path: str) -> list[dict]:
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def write_jsonl(path: str, records: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def session_file(sid: str, name: str) -> str:
    """数据湖里某条会话的文件路径。**只读**"""
    return os.path.join(SESSIONS_DIR, sid, name)
