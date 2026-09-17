#!/usr/bin/env python3
"""Phase 0 的 S0 归一化与仓库反解单元测试

这里测的是 verify-s0.py 那道门禁验不到的东西：门禁验「产物合不合格」，
本文件验「逻辑对不对」—— 用构造输入固定住每条实测得来的判定规则，
防止后续改动悄悄把它们改回错的写法。

被固定的实测结论（每条都对应 repo_map.py docstring 里的一段标定）：
  ① 路径含中文与空格（docs-research/ai-agent-inter/02-工程（agent）/…）不能被截断
  ② worktree 副本必须归到宿主仓库
  ③ 只认 file_path 类字段，不扫 Bash command 自由文本
  ④ 轨迹证据权重 3，能压倒 wd + raw 的 1+1
  ⑤ 排除前缀按 / 分段匹配，evals-foo/ 不能被 evals/ 误命中

用法：
    backend/venv/bin/python -m pytest tests/test_phase0_s0.py -v
    python3 -m pytest tests/test_phase0_s0.py -v
"""

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

PHASE0 = Path(__file__).resolve().parent.parent / "scripts" / "phase0"
sys.path.insert(0, str(PHASE0))

import repo_map  # noqa: E402


def _load_s0():
    """s0-normalize.py 带连字符，不能 import，用 spec 加载"""
    spec = importlib.util.spec_from_file_location("s0_normalize", PHASE0 / "s0-normalize.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_mod(filename: str, name: str):
    """带连字符的脚本不能 import，用 spec 加载"""
    spec = importlib.util.spec_from_file_location(name, PHASE0 / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


s0 = _load_s0()
freeze = _load_mod("freeze-batch.py", "freeze_batch")
CODE = repo_map.CODE_ROOT


# ── ① to_repo：路径 → 仓库 ────────────────────────────────────────

@pytest.mark.parametrize(
    "path,expected",
    [
        (CODE + "person/sid-code", "person/sid-code"),
        (CODE + "person/sid-code/packages/core/src/agent/loop.ts", "person/sid-code"),
        # 中文目录名 + 全角括号：实测 §2.5 的真实 wd，早期用 \S+ 的正则会在此截断
        (CODE + "person/docs-research/ai-agent-inter/02-工程（agent）/03-向量数据库与Embedding",
         "person/docs-research"),
        # worktree 副本归宿主仓库（§2.6：11 个活跃 worktree，14 条会话落其中）
        (CODE + "person/sid-code/.claude/worktrees/feat-harbor-h1/packages/cli/index.ts",
         "person/sid-code"),
        (CODE + "ruijie/iam-studio-fe/anka-app/packages/ontology-studio", "ruijie/iam-studio-fe"),
        # 非 Code 根下的临时目录不归属任何仓库（实测 189 条 wd 落在 /private/tmp 等）
        ("/private/tmp/lspdemo", None),
        ("/Users/yaobei/Documents/code/iam-studio-fe", None),
        ("", None),
        # 前缀必须按段比对，不能裸字符串前缀
        (CODE + "person/sid-code-fork/src/a.ts", None),
    ],
)
def test_to_repo(path, expected):
    assert repo_map.to_repo(path) == expected


def test_to_repo_longest_prefix_wins():
    """长前缀优先：不能被同名短前缀抢走"""
    assert repo_map.to_repo(CODE + "person/claude-code-working/x.ts") == "person/claude-code-working"
    assert repo_map.to_repo(CODE + "person/claude-code/x.ts") == "person/claude-code"


def test_known_repos_matches_archive_manifest():
    """KNOWN_REPOS 必须与 mirror 归档清单一致

    反解出的仓库若不在归档内，base_commit 就无从定位 —— 这是 §9.0 归档存在的
    全部意义。归档不在本机时跳过（CI 环境无归档）。
    """
    manifest = Path(os.environ.get(
        "ARCHIVE_DIR", os.path.expanduser("~/Code/_archive/bench-mirrors")
    )) / "manifest.tsv"
    if not manifest.exists():
        pytest.skip(f"归档清单不存在：{manifest}")
    archived = set()
    for i, line in enumerate(manifest.read_text().splitlines()):
        if i == 0 or not line.strip():
            continue
        archived.add(line.split("\t")[0])
    missing = set(repo_map.KNOWN_REPOS) - archived
    assert not missing, f"这些仓库会被反解出来但没归档，base_commit 无从定位：{sorted(missing)}"


# ── ② 信号 C：轨迹路径众数 ───────────────────────────────────────

def test_repo_from_trajectory_counts_file_keys_only():
    """只认 file_path 类字段。实测把 Bash command 里的路径算进来会让正确率 97.3%→95.9%"""
    trajectory = [
        {"tool_name": "Edit", "tool_input": {"file_path": CODE + "person/sid-code/a.ts"}},
        {"tool_name": "Read", "tool_input": {"file_path": CODE + "person/sid-code/b.ts"}},
        # command 里提到别的仓库 5 次，也不能influence结果
        {"tool_name": "Bash", "tool_input": {
            "command": " ".join([CODE + "person/code-graph/x.yaml"] * 5)}},
    ]
    repo, hits = repo_map.repo_from_trajectory(trajectory)
    assert repo == "person/sid-code"
    assert hits == 2


def test_repo_from_trajectory_empty():
    assert repo_map.repo_from_trajectory([]) == (None, 0)
    assert repo_map.repo_from_trajectory([{"tool_name": "Bash", "tool_input": None}]) == (None, 0)


# ── ③ 三路加权投票 ──────────────────────────────────────────────

def _resolve(wd=None, raw_lines=None, traj=None):
    """跑一次 resolve_repo，raw_lines 写进临时 raw.jsonl"""
    trajectory = traj or []
    with tempfile.TemporaryDirectory() as d:
        raw_path = os.path.join(d, "raw.jsonl")
        if raw_lines:
            with open(raw_path, "w") as f:
                for line in raw_lines:
                    f.write(json.dumps(line, ensure_ascii=False) + "\n")
        return repo_map.resolve_repo({"working_directory": wd or ""}, trajectory, raw_path)


def _sysline(wd: str) -> dict:
    return {"request": {"system": [{"text": f"<env>\nWorking directory: {wd}\nIs a git repo: yes\n"}]}}


def _edits(repo: str, n: int) -> list:
    return [
        {"tool_name": "Edit", "tool_input": {"file_path": f"{CODE}{repo}/f{i}.ts"}}
        for i in range(n)
    ]


def test_resolve_three_way_agreement_is_direct():
    r = _resolve(
        wd=CODE + "person/sid-code",
        raw_lines=[_sysline(CODE + "person/sid-code")],
        traj=_edits("person/sid-code", 3),
    )
    assert r["repo"] == "person/sid-code"
    assert r["repo_resolution"] == "direct"


def test_resolve_trajectory_outweighs_wd_and_raw():
    """核心回归：轨迹权重 3 > wd 1 + raw 1

    这是实测得出的结论 —— 抽查 4 个冲突案例，metadata.wd 全部是错的
    （采集侧多实例串号），轨迹路径全部是对的。若哪天有人把权重改回等权，
    这条测试必须变红。
    """
    r = _resolve(
        wd=CODE + "ruijie/iam-studio-fe/anka-app",
        raw_lines=[_sysline(CODE + "ruijie/iam-studio-fe/anka-app")],
        traj=_edits("person/sid-code", 4),
    )
    assert r["repo"] == "person/sid-code", "轨迹证据没能压倒 wd+raw，权重被改坏了"
    assert r["repo_resolution"] == "conflict", "结论虽由权重裁决，也必须如实标为 conflict"


def test_resolve_single_signal_is_inferred():
    r = _resolve(traj=_edits("person/claude-trace", 2))
    assert r["repo"] == "person/claude-trace"
    assert r["repo_resolution"] == "inferred"


def test_resolve_two_way_agreement_is_voted():
    r = _resolve(
        wd=CODE + "person/docs-research",
        raw_lines=[_sysline(CODE + "person/docs-research")],
    )
    assert r["repo"] == "person/docs-research"
    assert r["repo_resolution"] == "voted"


def test_resolve_no_signal_is_unresolved():
    r = _resolve(wd="/private/tmp/lspdemo")
    assert r["repo"] is None
    assert r["repo_resolution"] == "unresolved"


def test_resolve_signals_recorded():
    """repo_signals 必须留痕，下游要靠 traj_hits 判断证据强度"""
    r = _resolve(wd=CODE + "person/sid-code", traj=_edits("person/sid-code", 7))
    assert r["repo_signals"]["wd"] == "person/sid-code"
    assert r["repo_signals"]["traj_hits"] == 7
    assert r["repo_signals"]["raw"] is None


# ── ④ raw.jsonl 反解 ────────────────────────────────────────────

def test_wd_from_raw_parses_system_field():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "raw.jsonl")
        with open(p, "w") as f:
            f.write(json.dumps(_sysline(CODE + "person/sid-code")) + "\n")
        assert repo_map.wd_from_raw(p) == CODE + "person/sid-code"


def test_wd_from_raw_ignores_message_body():
    """只解析 request.system，不在整行原文上搜

    实测：在整行上搜会命中消息正文里提到的其他仓库路径，
    使仓库级准确率从 91% 掉到 79%。
    """
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "raw.jsonl")
        rec = _sysline(CODE + "person/sid-code")
        rec["request"]["messages"] = [
            {"role": "user", "content": f"Working directory: {CODE}ruijie/iam-studio-fe 看下这个"}
        ]
        with open(p, "w") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        assert repo_map.wd_from_raw(p) == CODE + "person/sid-code"


def test_wd_from_raw_handles_chinese_path():
    wd = CODE + "person/docs-research/ai-agent-inter/02-工程（agent）/19-前沿趋势与未来思考"
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "raw.jsonl")
        with open(p, "w") as f:
            f.write(json.dumps(_sysline(wd), ensure_ascii=False) + "\n")
        assert repo_map.wd_from_raw(p) == wd, "含中文与全角括号的路径被截断了"


def test_wd_from_raw_tolerates_broken_json():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "raw.jsonl")
        with open(p, "w") as f:
            f.write("{ 这不是合法 JSON\n")
            f.write(json.dumps(_sysline(CODE + "person/code-graph")) + "\n")
        assert repo_map.wd_from_raw(p) == CODE + "person/code-graph"


def test_wd_from_raw_missing_file():
    assert repo_map.wd_from_raw("/nonexistent/raw.jsonl") is None


# ── ⑤ 自指污染排除清单 ─────────────────────────────────────────

def test_excluded_prefixes_complete():
    """§2.5 点名的四个前缀必须都在"""
    prefixes = set(repo_map.load_excluded_prefixes())
    assert {"evals", "packages/eval-framework", "scripts/eval", "tests/eval"} <= prefixes


@pytest.mark.parametrize(
    "rel,hit",
    [
        ("evals/grade.ts", True),
        ("evals", True),
        ("packages/eval-framework/runner.ts", True),
        ("scripts/eval/run.sh", True),
        ("tests/eval/case_001.yaml", True),
        # 按段匹配，不是裸字符串前缀
        ("evals-foo/bar.ts", False),
        ("packages/eval-frameworkx/a.ts", False),
        ("packages/core/src/agent.ts", False),
        ("docs/evals/readme.md", False),
    ],
)
def test_is_excluded_path(rel, hit):
    assert repo_map.is_excluded_path(rel) is hit


def test_excluded_cache_not_poisoned_by_explicit_path():
    """传显式 path 不能污染默认清单的缓存"""
    default = repo_map.load_excluded_prefixes()
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "empty.txt")
        Path(p).write_text("# 空清单\n")
        assert repo_map.load_excluded_prefixes(p) == []
    assert repo_map.load_excluded_prefixes() == default


# ── ⑥ S0 逐 step 扫描 ──────────────────────────────────────────

def test_scan_trajectory_counts():
    """四个新字段必须逐 step 才能得到 —— v0.1 只读 metadata，覆盖率仅 1.5%"""
    trajectory = [
        {"message_type": "action", "tool_name": "Edit", "tool_input": {
            "file_path": CODE + "person/sid-code/a.ts",
            "old_string": "x", "new_string": "y"}},
        {"message_type": "observation", "is_error": False},
        {"message_type": "action", "tool_name": "Write", "tool_input": {
            "file_path": CODE + "person/sid-code/b.ts", "content": "hello"}},
        {"message_type": "observation", "is_error": True},
        {"message_type": "action", "tool_name": "Bash", "tool_input": {
            "command": "cd /x && bun test packages/core"}},
        {"message_type": "observation", "is_error": True},
        {"message_type": "action", "tool_name": "Bash", "tool_input": {
            "command": "make lint && oxlint packages"}},
    ]
    r = s0.scan_trajectory(trajectory)
    assert r["n_edit_ops"] == 2
    assert r["n_rebuildable_writes"] == 2
    assert r["n_error_ops"] == 2
    assert r["n_test_cmds"] == 3          # bun test / make lint / oxlint
    assert r["n_file_paths"] == 2
    assert len(r["file_paths_hash"]) == 16
    assert r["tool_call_count"] == 4


def test_scan_trajectory_parse_error_not_rebuildable():
    """采集时 JSON 截断的写调用不算可重建（§2.3：3.1% 的写调用属此类）"""
    r = s0.scan_trajectory([
        {"message_type": "action", "tool_name": "Edit", "tool_input": {
            "file_path": "/x/a.ts", "_parse_error": "truncated", "_raw_partial": "{"}},
    ])
    assert r["n_edit_ops"] == 1
    assert r["n_rebuildable_writes"] == 0
    assert r["n_parse_error_writes"] == 1


def test_scan_trajectory_lowercase_tool_names():
    """工具名大小写混用是真实分布（Edit 1099 / edit 56 / Write 182 / write 22）"""
    r = s0.scan_trajectory([
        {"message_type": "action", "tool_name": "edit", "tool_input": {
            "file_path": "/x/a.ts", "old_string": "a", "new_string": "b"}},
        {"message_type": "action", "tool_name": "write", "tool_input": {
            "file_path": "/x/b.ts", "content": "c"}},
        {"message_type": "action", "tool_name": "bash", "tool_input": {"command": "pytest -q"}},
    ])
    assert r["n_edit_ops"] == 2
    assert r["n_test_cmds"] == 1


def test_scan_trajectory_file_paths_hash_order_independent():
    """hash 基于排序后的路径集，与出现顺序无关（S5 去重要靠它）"""
    a = s0.scan_trajectory([
        {"message_type": "action", "tool_name": "Read", "tool_input": {"file_path": "/x/a.ts"}},
        {"message_type": "action", "tool_name": "Read", "tool_input": {"file_path": "/x/b.ts"}},
    ])
    b = s0.scan_trajectory([
        {"message_type": "action", "tool_name": "Read", "tool_input": {"file_path": "/x/b.ts"}},
        {"message_type": "action", "tool_name": "Read", "tool_input": {"file_path": "/x/a.ts"}},
    ])
    assert a["file_paths_hash"] == b["file_paths_hash"]


def test_scan_trajectory_empty():
    r = s0.scan_trajectory([])
    assert r["n_edit_ops"] == 0
    assert r["file_paths_hash"] == ""


# ── ⑦ 厂商归一化与 provenance ─────────────────────────────────

@pytest.mark.parametrize(
    "model,vendor",
    [
        ("claude-opus-4-6[1m]", "anthropic"),
        ("claude-opus-5", "anthropic"),
        ("deepseek-v3", "deepseek"),
        ("gpt-4o", "openai"),
        ("glm-4.6", "zhipu"),
        ("qwen3-max", "alibaba"),
        ("kimi-k2", "moonshot"),
        ("grok-4", "xai"),
        ("gemini-2.5-pro", "google"),
        ("some-unknown-model", "unknown"),
        ("", "unknown"),
    ],
)
def test_normalize_vendor(model, vendor):
    assert s0.normalize_vendor(model) == vendor


def test_detect_provenance():
    """v1.3 §8.5：升级前/后两种 provenance 必须能区分"""
    assert s0.detect_provenance({}) == "pre_upgrade"
    assert s0.detect_provenance({"working_directory": "/x"}) == "pre_upgrade"
    assert s0.detect_provenance({"git_state": {"head": "abc"}}) == "post_upgrade"
    assert s0.detect_provenance({"git_head": "abc"}) == "post_upgrade"


def test_detect_provenance_ignores_legacy_git_field():
    """旧版 `metadata.git` 不算 post_upgrade

    它来自另一条更早的采集路径，结构完全不同（{sha, branch, originUrl}，
    无 dirty / upstream / worktree 信息），全库 19 条且都不是升级后采的。
    初版把它一并算进去，得出「post_upgrade 19 条」的假象 —— 掩盖了
    「升级后新采会话一条都没带 git 状态」这个真实故障（见 §9.3）。
    """
    legacy = {"git": {"sha": "abc123", "branch": "main",
                      "originUrl": "http://example.com/x.git"}}
    assert s0.detect_provenance(legacy) == "pre_upgrade"
    # 新旧字段同时存在时，以新字段为准
    assert s0.detect_provenance({**legacy, "git_head": "def"}) == "post_upgrade"


# ── ⑧ 指令抽取 ────────────────────────────────────────────────

def test_extract_instruction_prefers_user_prompts():
    data = {"metadata": {"user_prompts": ["帮我把这个函数改成异步的，顺便加上超时处理"]}}
    assert s0.extract_instruction(data).startswith("帮我把这个函数")


def test_extract_instruction_skips_system_tags():
    data = {"metadata": {"user_prompts": [
        "<system-reminder>忽略这条系统提醒的内容不算用户指令</system-reminder>",
        "<command-name>/model</command-name> 这条也不算",
        "真正的用户指令：把测试跑一遍看看有没有问题",
    ]}}
    assert s0.extract_instruction(data) == "真正的用户指令：把测试跑一遍看看有没有问题"


def test_extract_instruction_falls_back_to_history():
    data = {"metadata": {"user_prompts": []}, "history": [
        {"role": "assistant", "content": "先看下代码"},
        {"role": "user", "content": [{"type": "text", "text": "把这个 bug 修掉，测试要过"}]},
    ]}
    assert s0.extract_instruction(data) == "把这个 bug 修掉，测试要过"


def test_extract_instruction_empty():
    assert s0.extract_instruction({"metadata": {}, "history": []}) == ""
    # 太短的不算指令（沿用 v0.1 的 >10 字符口径）
    assert s0.extract_instruction({"metadata": {"user_prompts": ["ok"]}}) == ""


# ── ⑨ 采集通道判定 ────────────────────────────────────────────

@pytest.mark.parametrize(
    "sid,metadata,expected",
    [
        # UUID 形态 = Claude Code 主通道（线上 7132 条）
        ("000bf70b-8796-4bf0-9e88-1a4ca0cb15ea", {}, "claude_code"),
        # 日期戳形态 = Codex 通道（492 条，模型以 glm/deepseek/gpt 为主）
        ("20260629-141829-dbc812b6", {}, "codex"),
        ("20260901-004200-5cd2edcf", {}, "codex"),
        # 8 位短 id（296 条）
        ("fea43918", {}, "short_id"),
        # tool_source 优先于 id 形态
        ("fea43918", {"tool_source": "sid-code"}, "sid_code"),
        ("20260629-141829-dbc812b6", {"tool_source": "sid-code"}, "sid_code"),
    ],
)
def test_detect_agent_source(sid, metadata, expected):
    assert repo_map.detect_agent_source(sid, metadata) == expected


def test_agent_source_never_empty():
    """任何 sid 都必须归到某个通道，不能返回空 —— 下游按通道分组统计"""
    for sid in ("", "x", "not-a-uuid-at-all", "20261301-999999-zzz"):
        assert repo_map.detect_agent_source(sid, {})


# ── ⑩ 历史清洗清单 ────────────────────────────────────────────

def test_legacy_trashed_list_loaded():
    """清单必须真的有内容 —— 上一轮手工移入 _trash/ 的 1722 条"""
    sids = repo_map.load_legacy_trashed()
    assert len(sids) == 1722, f"清单条数变了：{len(sids)}，应为 1722"
    # 抽查几条已知的
    assert "002f66db-095a-4b69-a75a-de875ae8884f" in sids


def test_legacy_trashed_missing_file_is_empty_not_crash():
    """清单缺失时返回空集而不是抛错 —— 别的环境可能没有这份历史"""
    with tempfile.TemporaryDirectory() as d:
        assert repo_map.load_legacy_trashed(os.path.join(d, "nope.txt")) == set()


def test_legacy_trashed_cache_not_poisoned():
    default = repo_map.load_legacy_trashed()
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "empty.txt")
        Path(p).write_text("# 空\n")
        assert repo_map.load_legacy_trashed(p) == set()
    assert repo_map.load_legacy_trashed() == default


def test_legacy_trashed_all_still_on_disk():
    """清单里的会话必须都在主目录 —— 这是「移回主目录」这个修复的核心断言

    若哪天有人又把它们移走，pull.py 会再次把 1722 条全部重下（去重只查
    data/pulled_sessions/<sid>/.pulled）。这条测试就是防这个回归。
    """
    sessions_dir = Path(os.environ.get("SESSIONS_DIR", "data/pulled_sessions"))
    if not sessions_dir.is_dir():
        pytest.skip(f"数据目录不存在：{sessions_dir}")
    sids = repo_map.load_legacy_trashed()
    missing = [s for s in sids if not (sessions_dir / s).is_dir()]
    assert not missing, (
        f"{len(missing)} 条已不在主目录，pull.py 会把它们重新下载一遍："
        f"{missing[:5]}"
    )


def test_no_trash_dir_reintroduced():
    """_trash/ 目录不应再出现 —— 淘汰要在元数据层表达，不靠移目录"""
    sessions_dir = Path(os.environ.get("SESSIONS_DIR", "data/pulled_sessions"))
    if not sessions_dir.is_dir():
        pytest.skip(f"数据目录不存在：{sessions_dir}")
    trash = sessions_dir / "_trash"
    assert not trash.exists(), (
        "_trash/ 又出现了。移目录会让 pull.py 的 .pulled 去重失效并重复下载；"
        "淘汰请用 S0 索引的字段标注（legacy_trashed / excluded_hit）表达。"
    )


# ── ⑩b 会话目录枚举口径 ──────────────────────────────────────

def test_iter_session_dirs_excludes_system_and_legacy():
    """S0 与验收必须用同一口径枚举会话目录

    原先 S0 用 `s != "_trash"`、验收用 `not startswith("_")` —— 口径不同，
    对账就有系统性偏差。实测 data/pulled_sessions/ 下有个 2.2MB 的 .DS_Store，
    S0 会把它当会话 open() 然后计入 no_traj，掩盖真正缺主文件的会话。
    """
    with tempfile.TemporaryDirectory() as d:
        for name in ("aaa", "bbb", "_trash", "_old", ".DS_Store", ".hidden"):
            os.makedirs(os.path.join(d, name), exist_ok=True)
        Path(os.path.join(d, "loose-file.txt")).write_text("x")
        Path(os.path.join(d, ".DS_Store_file")).write_text("x")
        assert repo_map.iter_session_dirs(d) == ["aaa", "bbb"]


def test_iter_session_dirs_sorted():
    with tempfile.TemporaryDirectory() as d:
        for name in ("ccc", "aaa", "bbb"):
            os.makedirs(os.path.join(d, name))
        assert repo_map.iter_session_dirs(d) == ["aaa", "bbb", "ccc"]


def test_iter_session_dirs_empty():
    with tempfile.TemporaryDirectory() as d:
        assert repo_map.iter_session_dirs(d) == []


# ── ⑪ 批次冻结 ────────────────────────────────────────────────

def _write_index(tmpdir: str, recs: list[dict]) -> str:
    meta = os.path.join(tmpdir, "meta")
    os.makedirs(meta, exist_ok=True)
    path = os.path.join(meta, "sessions-v2.jsonl")
    with open(path, "w") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def _rec(sid: str, steps: int = 10, **kw) -> dict:
    base = {
        "sid": sid, "steps": steps, "agent_source": "claude_code",
        "provenance": "pre_upgrade", "repo": "person/sid-code",
        "repo_resolution": "voted", "legacy_trashed": False,
        "has_raw": True, "has_events": False,
        "start_time": "2026-08-01T00:00:00",
    }
    base.update(kw)
    return base


def _with_index(recs: list[dict]):
    """把 freeze 模块的 INDEX/META_DIR 指到临时目录"""
    import contextlib

    @contextlib.contextmanager
    def ctx():
        with tempfile.TemporaryDirectory() as d:
            path = _write_index(d, recs)
            old_index, old_meta = freeze.INDEX, freeze.META_DIR
            freeze.INDEX = path
            freeze.META_DIR = os.path.join(d, "meta")
            try:
                yield d
            finally:
                freeze.INDEX, freeze.META_DIR = old_index, old_meta

    return ctx()


def test_freeze_fingerprint_is_order_independent():
    """指纹必须与 sid 出现顺序无关 —— 否则索引重排就让批次「变了」"""
    a = [_rec("bbb"), _rec("aaa"), _rec("ccc")]
    b = [_rec("ccc"), _rec("aaa"), _rec("bbb")]
    with _with_index(a):
        f1 = freeze.build("v0.2")["fingerprint"]
    with _with_index(b):
        f2 = freeze.build("v0.2")["fingerprint"]
    assert f1 == f2


def test_freeze_fingerprint_changes_on_added_session():
    """新增会话必须让指纹变化 —— 这是批次边界的全部意义"""
    with _with_index([_rec("aaa"), _rec("bbb")]):
        f1 = freeze.build("v0.2")["fingerprint"]
    with _with_index([_rec("aaa"), _rec("bbb"), _rec("ccc")]):
        f2 = freeze.build("v0.2")["fingerprint"]
    assert f1 != f2


def test_freeze_fingerprint_changes_on_steps_change():
    """会话被追加内容（steps 变化）也必须让指纹变化"""
    with _with_index([_rec("aaa", steps=10)]):
        f1 = freeze.build("v0.2")["fingerprint"]
    with _with_index([_rec("aaa", steps=25)]):
        f2 = freeze.build("v0.2")["fingerprint"]
    assert f1 != f2


def test_freeze_fingerprint_stable_across_field_changes():
    """字段口径调整不应让指纹变化 —— 指纹只覆盖 sid + steps

    否则每次给 S0 加字段，所有已冻结批次都会「失效」。
    """
    with _with_index([_rec("aaa", repo="person/sid-code", repo_resolution="voted")]):
        f1 = freeze.build("v0.2")["fingerprint"]
    with _with_index([_rec("aaa", repo="person/docs-research", repo_resolution="direct")]):
        f2 = freeze.build("v0.2")["fingerprint"]
    assert f1 == f2


def test_freeze_stats():
    recs = [
        _rec("a", steps=1, agent_source="claude_code"),
        _rec("b", steps=10, agent_source="codex", provenance="post_upgrade"),
        _rec("c", steps=50, agent_source="codex", repo=None, repo_resolution="unresolved"),
        _rec("d", steps=5, legacy_trashed=True),
    ]
    with _with_index(recs):
        b = freeze.build("v0.2")
    assert b["session_count"] == 4
    assert b["steps_ge3"] == 3                 # steps=1 的不算
    assert b["steps_ge3_anchored"] == 2        # c 未锚定
    assert b["legacy_trashed"] == 1
    assert b["agent_source_dist"]["codex"] == 2
    assert b["provenance_dist"]["post_upgrade"] == 1


def test_freeze_refuses_to_overwrite_different_fingerprint():
    """已冻结的批次不可改写 —— 那会让已发布的结果不可复现"""
    with _with_index([_rec("aaa")]) as d:
        os.makedirs(freeze.META_DIR, exist_ok=True)
        batch = freeze.build("v0.2")
        with open(freeze.batch_path("v0.2"), "w") as f:
            json.dump(batch, f)
        # 换一份内容不同的索引，再冻同一个版本号
        _write_index(d, [_rec("aaa"), _rec("bbb")])
        with pytest.raises(SystemExit) as e:
            freeze.main_with_args(["--version", "v0.2"])
        assert "不可改写" in str(e.value) or "指纹不同" in str(e.value)


def test_freeze_missing_index_fails_loudly():
    old = freeze.INDEX
    freeze.INDEX = "/nonexistent/sessions-v2.jsonl"
    try:
        with pytest.raises(SystemExit):
            freeze.build("v0.2")
    finally:
        freeze.INDEX = old


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
