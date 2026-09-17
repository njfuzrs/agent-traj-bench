#!/usr/bin/env python3
"""Phase 1 清洗流水线的单元测试（S1 硬过滤 / S2 脱敏 / S3 切分 / 分类标注）

与 `verify-phase1.py` 的分工同 Phase 0：门禁验「产物合不合格」，本文件验
「逻辑对不对」—— 用构造输入固定住每条**实测得来**的判定规则，防止后续改动
悄悄把它们改回错的写法。

被固定的实测结论（每条都对应源码 docstring 里的一段标定）：

  S1  ① 中断态会话不淘汰（转 S3 只丢末尾单元），§4.2 R5
      ② 自指污染在 S1 就淘汰，不留到 S4（§9.4 坑③）
  S2  ③ sk- 密钥要过熵判定：真密钥脱敏，`sk-specific-scorer-registry` 这类
         分支名/任务标识不动（v0.1 会误伤）
      ④ 路径登录名必须替换，但 /home/runner 这类系统目录不动（漏检 #1 类）
      ⑤ 规则必须幂等：脱敏两次结果不变（否则幂等自检永远报红）
      ⑥ 回环地址与公开邮箱域名不脱敏
  S3  ⑦ harness 注入的提示词不是用户指令（805/476/211 条实测量级）
      ⑧ `<session>` 包裹的是真实用户内容，要拆包而非丢弃（634 条）
      ⑨ 「请继续」要剥客套前缀才能判成追问（251 条曾漏判成新任务）
      ⑩ 会话恢复时首行 messages 倒灌历史，只取最后一条 user 消息
      ⑪ 一行 raw 只产出一个轮次（402 条会话曾同 started_at 挂多单元）
      ⑫ 轮次必须按时间戳排序（18.2% 会话时间戳非单调）
      ⑬ enforce_partition 保证区间互不重叠（重叠率 49.8% → 0%）
  标注 ⑭ 零写单元 difficulty 记 unrated 而非 easy（否则 easy 偏斜到 77.9%）
      ⑮ 源信息块必须齐全

用法：
    python3 -m pytest tests/test_s1_s3.py -v
"""

import importlib.util
import sys
from pathlib import Path

import pytest

PHASE1 = Path(__file__).resolve().parent.parent / "s1_s3"
sys.path.insert(0, str(PHASE1))

# ⚠️ 不用裸 `import common` —— 两层各有一份同名的 common.py，而 sys.modules 是
# 进程级缓存：交叉收集时（pytest pipeline/tests scripts/tests）**谁先加载谁赢**，
# 且 conftest 全部先于测试模块导入 ⇒ 裸 import 拿到的是另一层那份（实测 §2.8）。
# 按绝对路径显式加载本层那份，并占住 sys.modules —— 后者是给下面 _load() 出来的
# 生产脚本用的，它们自己也写 `import common`。
def _load_own_common():
    spec = importlib.util.spec_from_file_location("common", PHASE1 / "common.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["common"] = mod          # 先占住，再 exec —— 生产脚本 import 时才拿得到
    spec.loader.exec_module(mod)
    return mod


common = _load_own_common()

import labeler  # noqa: E402
import s2_rules  # noqa: E402
import s3_segment as seg  # noqa: E402


def _load(filename: str, name: str):
    """带连字符的脚本不能 import，用 spec 加载"""
    spec = importlib.util.spec_from_file_location(name, PHASE1 / filename)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


s1 = _load("s1-filter.py", "s1_filter")
s3 = _load("s3-split.py", "s3_split")


# ── S1 硬过滤 ───────────────────────────────────────────────────────

def _rec(**kw):
    base = {
        "sid": "s" * 36, "steps": 20, "tool_call_count": 10,
        "total_tokens": 50000, "exit_status": "end_turn", "excluded_hit": False,
    }
    base.update(kw)
    return base


@pytest.mark.parametrize("kw,expect", [
    ({"steps": 0}, "R1_EMPTY"),
    ({"steps": 2}, "R2_TOO_SHORT"),
    ({"steps": 5, "tool_call_count": 0}, "R3_NO_ACTION"),
    ({"total_tokens": 999}, "R4_TOO_FEW_TOKENS"),
    ({"excluded_hit": True}, "E_SELF_REFERENTIAL"),
    ({}, None),
])
def test_s1_rules(kw, expect):
    assert s1.judge(_rec(**kw)) == expect


def test_s1_rule_priority_empty_before_short():
    """R1 优先于 R2：steps==0 必须记 R1_EMPTY 而不是 R2_TOO_SHORT

    顺序错了不影响保留集，但会让淘汰归因失真 —— 而归因分布是验收项。
    """
    assert s1.judge(_rec(steps=0)) == "R1_EMPTY"


@pytest.mark.parametrize("status", ["user_interrupt", "interrupted", "partial", "abort"])
def test_s1_interrupt_not_dropped(status):
    """① 中断态不淘汰（§4.2 R5）

    一条 200 步的会话在末尾被打断，前 180 步可能含完整成功的子任务。
    整条丢掉等于把这批素材白扔。
    """
    assert s1.judge(_rec(exit_status=status)) is None
    assert status in s1.INTERRUPT_STATUS


def test_s1_tool_use_is_not_failure():
    """exit_status=tool_use 是正常停止态（实测 2213 条），不是失败"""
    assert s1.judge(_rec(exit_status="tool_use")) is None
    assert s1.judge(_rec(exit_status="unknown")) is None


def test_s1_self_referential_dropped_at_s1():
    """② 自指污染在 S1 淘汰（§9.4 坑③：索引已标好，不要留到 S4 重扫）"""
    assert s1.judge(_rec(excluded_hit=True)) == "E_SELF_REFERENTIAL"
    assert "E_SELF_REFERENTIAL" in s1.DROP_REASONS


# ── S2 脱敏 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "sk-REvAV2bcQ4aARmDhi0dqH35C7tJYJiPE4gtPLWJMVuMeYkle",
    "sk-2ae4ff93debf4e9c9b212f5cb002184c",
])
def test_s2_real_key_redacted(text):
    """③ 真密钥必须脱敏（高熵、大小写数字混排）"""
    out, hits = s2_rules.desensitize(text)
    assert "sk-<REDACTED>" in out
    assert any(h["type"] == "generic_sk_key" for h in hits)


@pytest.mark.parametrize("text", [
    "分支 sk-specific-scorer-registry 已合并",
    "任务 sk-user-question-bridge 完成",
    "sk-omission-8fixes-implemented",
])
def test_s2_identifier_not_redacted(text):
    """③ 形似密钥的标识符不能误伤 —— v0.1 的 sk-[a-zA-Z0-9]{32,} 会

    真假的区别不在长度而在字符分布：真密钥是随机串，假阳性是连字符分隔的英文词。
    """
    out, _ = s2_rules.desensitize(text)
    assert out == text


def test_s2_entropy_discriminates():
    assert s2_rules.looks_like_real_key("REvAV2bcQ4aARmDhi0dqH35C7tJYJiPE4gt")
    assert not s2_rules.looks_like_real_key("specific-scorer-registry")
    # 太短的不判为密钥
    assert not s2_rules.looks_like_real_key("abc123")


def test_s2_path_username_redacted():
    """④ 路径登录名是 v0.1 漏检 #1 类（实测 99% 会话命中）"""
    out, hits = s2_rules.desensitize("/Users/zhourusheng/Code/person/sid-code")
    assert out == "/Users/<USER>/Code/person/sid-code"
    assert any(h["type"] == "path_username" for h in hits)


def test_s2_path_keeps_repo_part():
    """④ 只替换登录名那一段，仓库名必须留着 —— S4 分诊靠它锚定仓库"""
    out, _ = s2_rules.desensitize("/Users/yaobei/Code/ruijie/iam-studio-fe/src/a.ts")
    assert "ruijie/iam-studio-fe/src/a.ts" in out
    assert "yaobei" not in out


@pytest.mark.parametrize("path", [
    "/home/runner/work/repo",     # CI
    "/Users/shared/tools",
    "/home/root/x",
])
def test_s2_system_dirs_not_redacted(path):
    """④ 系统/工具目录不是登录名，替换它们会破坏路径语义"""
    out, _ = s2_rules.desensitize(path)
    assert out == path


@pytest.mark.parametrize("text", [
    "sshpass -p 'secret123' ssh host",
    "sk-REvAV2bcQ4aARmDhi0dqH35C7tJYJiPE4gtPLWJMVuMeYkle",
    "password: hunter2hunter2hunter2",
    "curl -u admin:pass123 http://10.1.2.3/api",
    "/Users/zhourusheng/x 联系 li@acme.corp 电话 13510010001",
    "AKIA1234567890ABCDEF",
])
def test_s2_idempotent(text):
    """⑤ 幂等：脱敏两次结果必须一致

    不幂等的后果不是漏脱敏，而是**幂等自检永远报红** —— 分不清「还在漏」与
    「已脱敏」。实测 inline_credential 曾匹配自己的替换产物
    `sshpass -p <CREDENTIAL_REDACTED>`，因为 [^'"\\s]{6,} 把占位符也算作凭据。
    """
    once, _ = s2_rules.desensitize(text)
    twice, hits2 = s2_rules.desensitize(once)
    assert once == twice, f"不幂等：{once!r} → {twice!r}"
    assert not hits2, f"二次扫描仍有命中：{hits2}"


@pytest.mark.parametrize("text", [
    "http://127.0.0.1:8080/api",
    "连接 localhost:5432",
    "联系 zhang@gmail.com",
    "反馈到 someone@github.com",
])
def test_s2_safe_values_untouched(text):
    """⑥ 回环地址与公开邮箱域名不是敏感信息"""
    out, _ = s2_rules.desensitize(text)
    assert out == text


def test_s2_timestamp_not_phone():
    """时间戳不能被手机号正则误报（1[3-9]\\d{9} 会撞上毫秒时间戳）"""
    out, _ = s2_rules.desensitize("提交于 2026-09-05T13:20:37 完成")
    assert out == "提交于 2026-09-05T13:20:37 完成"


def test_s2_severity_ranking():
    assert s2_rules.worst_severity(
        [{"severity": "medium"}, {"severity": "high"}]) == "high"
    assert s2_rules.worst_severity([{"severity": "medium"}]) == "medium"
    assert s2_rules.worst_severity([]) is None


# ── S3 切分：噪声识别 ───────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "<system-reminder>foo</system-reminder>",
    "<command-name>/model</command-name>",
    "<local-command-stdout>Set model</local-command-stdout>",
    "Caveat: The messages below were generated",
])
def test_s3_noise_tags(text):
    assert seg.is_noise(text)


@pytest.mark.parametrize("text", [
    "A session-scoped Stop hook is now active with condition: \"修文档\"",
    "Describe your most recent action in 3-5 words using present tense",
    "Based on the conversation transcript above, has the following stopping condition",
    "Another Claude session sent a message:\n<agent-message from=\"Explore\">",
    "[SYSTEM NOTIFICATION - NOT USER INPUT]\nThis is an automated event",
])
def test_s3_harness_injected_is_noise(text):
    """⑦ harness 自己注入的提示词不是用户指令

    实测量级：Stop hook 805 / Describe 476 / 停止条件裁判 211 / 跨会话 61 /
    系统通知 57（保留单元数）。不滤掉时一条会话被切成 106 个单元而独立裁判
    只认 2 个真实指令。
    """
    assert seg.is_noise(text)


@pytest.mark.parametrize("text", [
    "[Request interrupted by user]",
    "# JD 映射\n\n当用户调用 `/jd-map <路径>` 时，按以下流程执行。",
    "Agent (Explore): 读取 src/trace/collector.ts 的完整内容",
    "User: 这是 claude code 源码，请你结合源码分析",
    "The following is the user's CLAUDE.md configuration. Treat it as context",
    "Continue from where you left off.",
])
def test_s3_injected_prompt(text):
    """⑦ slash 命令定义正文与转录回放也不是本轮用户输入"""
    assert seg.is_injected_prompt(text)


def test_s3_markdown_paste_is_not_injected():
    """以 # 开头的 markdown 不能一律当噪声 —— 实测真实指令里也有 13 个这样

    这是刻意的取舍：宁可留下少量模板，不可误杀真实指令。那类走
    boundary_confidence 标注交 Phase 2 复判，而不是在这里丢掉。
    """
    assert not seg.is_injected_prompt("# 图谱组件样式更新计划\n\n## Context\n\n设计师更新了视觉设计")


def test_s3_session_tag_unwrapped():
    """⑧ `<session>` 裹的是真实用户内容（实测 634 个单元），要拆包不是丢弃"""
    text = "<session>\n'/path/doc.md' 请你核对文档是否有误\n</session>"
    assert not seg.is_noise(text)
    inner = seg.unwrap_user_text(text)
    assert "请你核对文档是否有误" in inner
    assert "<session>" not in inner


@pytest.mark.parametrize("text", [
    "<!--\n  提示词文件\n-->",
    '<select class="h-7 w-full rounded-md">',
    "<conversation>\n# 修复对话重播\n</conversation>",
])
def test_s3_angle_bracket_content_not_noise(text):
    """不能按 `<` 开头判噪声：用户粘贴的模板/HTML/注释都长这样"""
    assert not seg.is_noise(text)


def test_s3_user_text_blocks_skips_tool_result():
    """user 消息绝大多数是 tool_result（实测 25935 vs 3192 text），不是用户输入"""
    msg = {"role": "user", "content": [
        {"type": "tool_result", "content": "output"},
        {"type": "text", "text": "请修复这个 bug"},
    ]}
    assert seg.user_text_blocks(msg) == ["请修复这个 bug"]


# ── S3 切分：边界判定 ───────────────────────────────────────────────

def _turn(text, ts_epoch=1000.0, files=None):
    return {"text": text, "ts_epoch": ts_epoch, "files": files or []}


def test_s3_first_turn_is_boundary():
    is_bd, reason = seg.decide_boundary(_turn("随便什么"), None)
    assert is_bd and reason == "B_FIRST"


def test_s3_time_gap_boundary():
    prev = _turn("上一个任务", ts_epoch=0.0)
    cur = _turn("另一件事", ts_epoch=seg.GAP_SECONDS + 1)
    is_bd, reason = seg.decide_boundary(cur, prev)
    assert is_bd and reason == "B_TIME_GAP"


def test_s3_file_disjoint_boundary():
    prev = _turn("改 a.ts", files=["/x/a.ts"])
    cur = _turn("改另一批", files=["/x/b.ts"])
    is_bd, reason = seg.decide_boundary(cur, prev, prev_files={"/x/a.ts"})
    assert is_bd and reason == "B_FILE_DISJOINT"


def test_s3_file_disjoint_needs_both_sides():
    """本轮还没碰文件时不能判新任务 —— 空集与任何集合交集都为空"""
    prev = _turn("改 a.ts", files=["/x/a.ts"])
    cur = _turn("嗯嗯继续看看这里", files=[])
    is_bd, _ = seg.decide_boundary(cur, prev, prev_files={"/x/a.ts"})
    assert not is_bd


def test_s3_task_pattern_needs_length():
    """强信号 3 要求长度 >= 40（TASK_START_MIN_LEN），短句不算完整指令"""
    assert not seg.looks_like_task_start("修复一下")
    # 刚好卡在门槛下：有动词但不够长 —— 这类多为追问而非新任务
    short = "请你修复 collector.ts 流式超时失效的问题"
    assert len(short) < seg.TASK_START_MIN_LEN
    assert not seg.looks_like_task_start(short)
    # 够长且含动词 + 对象
    full = "请你修复 collector.ts 里流式超时失效的问题，并补一个回归测试用例覆盖它"
    assert len(full) >= seg.TASK_START_MIN_LEN
    assert seg.looks_like_task_start(full)


def test_s3_task_pattern_needs_verb():
    """够长但没有动词的不算任务起始（避免把粘贴的段落当指令）"""
    assert not seg.looks_like_task_start("这个模块的结构大概是这样的，" * 5)


@pytest.mark.parametrize("text", [
    "继续", "接着来", "还有", "不对", "再改改", "ok", "hmm",
])
def test_s3_short_followup(text):
    assert seg.looks_like_followup(text)


@pytest.mark.parametrize("text", [
    "请继续完成任务",
    "请继续完成任务，文档还没写",
    "请接着上面的做",
    "Continue from where you left off",
])
def test_s3_polite_prefix_stripped(text):
    """⑨ 「请继续」必须剥掉客套前缀才能判成追问

    实测 251 个单元以「请继续」开头却被判成新任务边界 —— 因为 startswith 查的是
    「继续」而文本以「请继续」开头。这类漏判直接制造多切。
    """
    assert seg.looks_like_followup(text), f"{text!r} 应判为追问"


def test_s3_error_log_is_followup():
    """粘贴的报错日志是上个任务的反馈，不是新任务"""
    assert seg.looks_like_followup(
        "Traceback (most recent call last):\n  File \"a.py\", line 1")
    assert seg.looks_like_followup("Error: cannot find module 'foo'")


def test_s3_weak_signal_beats_strong():
    """弱信号优先于强信号（decide_boundary 的顺序是刻意的）

    一段粘贴的报错日志很可能同时匹配 TASK_START_RE（含「修复」等词）又超过
    40 字符。强信号先判就会把「上个任务的报错反馈」误切成新任务。
    """
    prev = _turn("上一个任务", ts_epoch=0.0)
    text = "Error: 修复失败了，实现的那个函数报错 TypeError: cannot read property of undefined"
    is_bd, reason = seg.decide_boundary(_turn(text, ts_epoch=10.0), prev)
    assert not is_bd and reason == "W_FOLLOWUP"


def test_s3_boundary_confidence_calibrated():
    """置信度分档必须与实测精确率一致（B_TASK_PATTERN 实测仅 37.4%）"""
    assert seg.boundary_confidence("B_FIRST") == "high"
    assert seg.boundary_confidence("B_TIME_GAP") == "high"
    assert seg.boundary_confidence("B_NO_RAW") == "high"
    assert seg.boundary_confidence("B_FILE_DISJOINT") == "medium"
    assert seg.boundary_confidence("B_TASK_PATTERN") == "low"
    assert seg.boundary_confidence("未知信号") == "low"
    # 提取失败 ≠ 不可能切错，必须是 low（2026-09-06 修的缺陷）
    assert seg.boundary_confidence("B_EXTRACT_FAILED") == "low"


def test_s3_extract_failed_not_confused_with_no_raw():
    """B_EXTRACT_FAILED 与 B_NO_RAW 必须分开，且只有后者配 high

    这两者原先共用 B_NO_RAW，理由是「整条会话一个单元，不存在切错的可能」——
    但这句话只对**真的没有 raw.jsonl** 成立。有 raw.jsonl 却提取不出轮次的是
    **该切没切**，切分信号缺失不代表会话里只有一个任务。

    实测代价：1282 个 B_NO_RAW 单元里 1232 个其实有 raw.jsonl，冒用 high 置信度
    并把 high 档精确率从 75% 抬高到 84%（不切分就不会切错）。缺陷让门禁数字更
    好看，所以三道门禁全绿也没抓到它。
    """
    assert seg.boundary_confidence("B_NO_RAW") == "high"
    assert seg.boundary_confidence("B_EXTRACT_FAILED") == "low"
    assert seg.BOUNDARY_CONFIDENCE["B_NO_RAW"] != seg.BOUNDARY_CONFIDENCE["B_EXTRACT_FAILED"]


# ── S3 切分：slash command 参数里的真实指令 ──────────────────────────

def test_s3_extract_command_args_recovers_instruction():
    """slash command 的参数里藏着真实指令，不能随整块噪声丢掉

    `<command-name>` 整块判噪声是对的（/model、/clear 不是任务），但用户常把
    任务写在参数里。实测 332 条会话整条提取不出轮次，其中 194 条（58%）的指令
    就在 `<command-args>` 里；命令分布 /goal 614、/add-question 187。
    """
    text = (
        "<command-name>/goal</command-name>\n"
        "<command-message>goal</command-message>\n"
        "<command-args>请审查 evals/eval-judge.ts 以及相关的评分计算代码</command-args>\n"
    )
    got = seg.extract_command_args(text)
    assert len(got) == 1
    assert got[0].startswith("请审查")


def test_s3_command_args_ignores_switch_values():
    """开关型命令的参数值不是任务：/model opus-5 不能被当成指令

    两条限制各挡一类：长度 <15 挡掉短值，TASK_START_RE 挡掉不含动词+对象的值。
    """
    assert seg.extract_command_args(
        "<command-name>/model</command-name><command-args>opus-5</command-args>") == []
    # 够长但不含任务动词，同样不认
    assert seg.extract_command_args(
        "<command-name>/effort</command-name>"
        "<command-args>maximum effort setting value here</command-args>") == []


def test_s3_command_args_reached_through_noise_block():
    """user_text_blocks 要能穿过噪声块拿到 command-args（端到端）"""
    msg = {"role": "user", "content": [{"type": "text", "text": (
        "<command-name>/goal</command-name>"
        "<command-args>请你重构 auth 模块，把 token 校验抽成独立函数</command-args>")}]}
    blocks = seg.user_text_blocks(msg)
    assert len(blocks) == 1 and "重构" in blocks[0]


# ── S3 切分：轮次提取与区间映射 ─────────────────────────────────────

def test_s3_resumed_session_takes_last_user_msg():
    """⑩ 会话恢复时首行 messages 倒灌历史，只认最后一条 user 消息

    实测 c33a9523 首行有 716 条消息 / 239 条 user，而整条 trajectory 只有 10 步
    —— 那 239 轮的动作不在本轨迹里。不处理会造出 9 个 step_range 全为 [0,0] 的
    幻影单元；抽样 400 条会话中 56.5% 的首行含 >1 条 user 消息。
    """
    raw = [{
        "index": 1, "timestamp": "2026-08-19T13:05:36",
        "request": {"messages": [
            {"role": "user", "content": [{"type": "text", "text": "历史轮次一，很久以前问的"}]},
            {"role": "assistant", "content": []},
            {"role": "user", "content": [{"type": "text", "text": "历史轮次二"}]},
            {"role": "user", "content": [{"type": "text", "text": "这才是本次真正的指令"}]},
        ]},
    }]
    turns = s3.extract_turns(raw)
    assert len(turns) == 1
    assert turns[0]["text"] == "这才是本次真正的指令"


def test_s3_new_session_first_line_kept():
    """全新会话首行本来只有 1 条 user 消息，取最后一条等价于取它本身"""
    raw = [{
        "index": 1, "timestamp": "2026-08-19T13:05:36",
        "request": {"messages": [
            {"role": "user", "content": [{"type": "text", "text": "请实现一个功能"}]},
        ]},
    }]
    turns = s3.extract_turns(raw)
    assert len(turns) == 1 and turns[0]["text"] == "请实现一个功能"


def test_s3_first_line_skips_trailing_noise_to_find_instruction():
    """⑩b 首行末尾是 tool_result / 注入噪声时，要往前找到真实指令

    这条锁的是一个真实缺陷（2026-09-06 修）：上一条测试的「只取最后一条 user
    消息」若写成无条件 `user_msgs[-1:]`，实测让 **1086 个单元（15.3%）**退化成
    「整条会话一个单元」—— 这类会话首行的最后一条 user 消息是 tool_result 或
    `<system-reminder>` / `<command-name>` 这类注入噪声，取出来是空块，turns
    为空，于是被标成 B_NO_RAW。

    症状隐蔽之处：这些会话**有** raw.jsonl，却和真的没有 raw.jsonl 的会话混在
    同一个 reason 里，还共享 high 置信度（理由是「整条一个单元，不存在切错的
    可能」）—— 而它们其实是**该切没切**。修掉后保留单元 7094 → 7385，
    step_range 映射率 83.5% → 94.4%。

    防幻影单元的不变量不许因此松动：首行仍然最多产出一个轮次。
    """
    raw = [{
        "index": 1, "timestamp": "2026-08-19T13:05:36",
        "request": {"messages": [
            {"role": "user", "content": [{"type": "text", "text": "历史轮次，很久以前问的"}]},
            {"role": "assistant", "content": []},
            {"role": "user", "content": [{"type": "text", "text": "请你修复登录接口的超时问题"}]},
            # 真实指令之后跟着的全是噪声，无条件取 [-1:] 会取到空
            {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]},
            {"role": "user", "content": [{"type": "text", "text": "<system-reminder>ctx</system-reminder>"}]},
        ]},
    }]
    turns = s3.extract_turns(raw)
    assert len(turns) == 1, "首行仍然只能产出一个轮次（防幻影单元）"
    assert turns[0]["text"] == "请你修复登录接口的超时问题"


def test_s3_first_line_all_noise_still_degrades():
    """首行确实全是噪声时，取不到轮次是正确行为（不许硬造一个）

    与上一条配对：修法只是「往前找」，不是「无论如何都要产出轮次」。
    全噪声的首行应当仍然提取不到 —— 该走 B_NO_RAW 兜底的就该走。
    """
    raw = [{
        "index": 1, "timestamp": "2026-08-19T13:05:36",
        "request": {"messages": [
            {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]},
            {"role": "user", "content": [{"type": "text", "text": "<system-reminder>ctx</system-reminder>"}]},
        ]},
    }]
    assert s3.extract_turns(raw) == []


def test_s3_one_raw_line_one_turn():
    """⑪ 一行 raw = 一次 API 调用 = 最多一个触发轮次

    实测一行里有 6 个 text 块（真实指令 + 若干「请继续完成任务」），共享该行
    时间戳，于是映射出 6 个 step_range 完全相同的单元。全库 402 条会话曾出现
    同一 started_at 挂 2-7 个单元。
    """
    raw = [{
        "index": 5, "timestamp": "2026-07-02T19:07:26",
        "request": {"new_messages": [
            {"role": "user", "content": [
                {"type": "text", "text": "第一段说明"},
                {"type": "text", "text": "最后这段才是触发文本"},
            ]},
        ]},
    }]
    turns = s3.extract_turns(raw)
    assert len(turns) == 1
    assert turns[0]["text"] == "最后这段才是触发文本"


def test_s3_turns_sorted_by_timestamp():
    """⑫ raw.jsonl 的行序不等于时间序（18.2% 会话非单调，子 agent 并发写入）

    不排序会让 step_range 倒退，且「间隔 >30 分钟」算出负数间隔永不触发。
    """
    raw = [
        {"index": 1, "timestamp": "2026-07-02T19:30:00",
         "request": {"new_messages": [{"role": "user", "content": [
             {"type": "text", "text": "后发生的"}]}]}},
        {"index": 2, "timestamp": "2026-07-02T19:00:00",
         "request": {"new_messages": [{"role": "user", "content": [
             {"type": "text", "text": "先发生的"}]}]}},
    ]
    turns = s3.extract_turns(raw)
    assert [t["text"] for t in turns] == ["先发生的", "后发生的"]


def test_s3_dedup_repeated_instruction():
    """同一指令在增量里重复出现要去重（§4.3）"""
    msg = {"role": "user", "content": [{"type": "text", "text": "请修复这个问题"}]}
    raw = [
        {"index": 1, "timestamp": "2026-07-02T19:00:00",
         "request": {"new_messages": [msg]}},
        {"index": 2, "timestamp": "2026-07-02T19:00:01",
         "request": {"new_messages": [msg]}},
    ]
    assert len(s3.extract_turns(raw)) == 1


@pytest.mark.parametrize("ranges,expect", [
    # 已经是划分 → 原样
    ([[0, 5], [6, 10]], [[0, 5], [6, 10]]),
    # 重叠 → 抬起点
    ([[0, 8], [3, 12]], [[0, 8], [9, 12]]),
    # 完全被前一区间吞掉 → None（无独占区间）
    ([[0, 20], [5, 10]], [[0, 20], None]),
    # 同区间重复（幻影单元的症状）
    ([[8, 8], [8, 8], [8, 12]], [[8, 8], None, [9, 12]]),
    # None 原样透传
    ([None, [3, 7]], [None, [3, 7]]),
])
def test_s3_enforce_partition(ranges, expect):
    """⑬ 单元区间必须是轨迹的划分而非覆盖

    重叠会让 S4 把同一段动作反复计入，edit_ops / files_touched 全部虚高。
    实测这条修复把重叠率从 49.8% 降到 0%。
    """
    assert s3.enforce_partition(ranges) == expect


def test_s3_map_step_range_by_timestamp():
    """区间映射按时间戳对齐，不按 index 比例换算

    实测 raw 行数与 trajectory 步数不成固定倍数（0ce08c20 是 40 行 / 216 action，
    比例 5.4；14bdb107 是 13 行 / 21 action，比例 1.6）。
    """
    timeline = [("T1", 0), ("T2", 4), ("T3", 8), ("T4", 12)]
    assert s3.map_step_range("T1", "T3", timeline) == [0, 4]
    assert s3.map_step_range("T3", None, timeline) == [8, 12]


def test_s3_scan_none_range_means_no_action():
    """rng=None 且 whole=False 时必须返回零，不能继承整条会话

    两种 None 语义混同会让「无独占区间」的单元继承整条会话的 edit_ops，
    客观量直接虚高。
    """
    traj = [
        {"message_type": "action", "tool_name": "Edit",
         "tool_input": {"file_path": "/x/a.ts", "old_string": "a", "new_string": "b"}},
        {"message_type": "observation", "is_error": True},
    ]
    empty = s3.scan_step_range(traj, None, whole=False)
    assert empty["edit_ops"] == 0 and empty["error_ops"] == 0
    assert empty["files_touched"] == []
    whole = s3.scan_step_range(traj, None, whole=True)
    assert whole["edit_ops"] == 1 and whole["error_ops"] == 1


def test_s3_scan_counts_within_range_only():
    """单元级客观量只算本区间的，否则 S4 会按整条会话的数字判断"""
    def edit(path):
        return {"message_type": "action", "tool_name": "Edit",
                "tool_input": {"file_path": path, "old_string": "a", "new_string": "b"}}
    traj = [edit("/x/a.ts"), edit("/x/b.ts"), edit("/x/c.ts")]
    got = s3.scan_step_range(traj, [0, 1])
    assert got["edit_ops"] == 2
    assert got["files_touched"] == ["/x/a.ts", "/x/b.ts"]


# ── 分类与标注 ──────────────────────────────────────────────────────

def test_label_zero_edit_is_unrated():
    """⑭ 零写单元记 unrated 而非 easy

    实测 59.3% 的单元 edit_ops==0（41.5% 的保留会话整条没有写操作，已核对不是
    S3 漏算：单元 edit_ops 合计对会话 n_edit_ops 覆盖率 100.9%）。判成 easy 会
    造出 easy 77.9% 的偏斜 —— 与 v0.1 的 hard 87.4% 是同一个病理：
    **用一个与难度无关的量当难度锚点**。
    """
    d, basis = labeler.classify_difficulty(0, 0)
    assert d == "unrated" and basis == "no_edit_ops"


@pytest.mark.parametrize("n_files,edits,expect", [
    (1, 2, "easy"),
    (2, 6, "medium"),
    (3, 20, "hard"),
    (1, 30, "hard"),
])
def test_label_difficulty_anchors(n_files, edits, expect):
    """难度锚点取自 SWE-bench Verified 实测统计的区间化处理（§4.6）"""
    assert labeler.classify_difficulty(n_files, edits)[0] == expect


def test_label_head_weighted_scoring():
    """指令头部权重 ×3：用户意图几乎总在开头

    实测 instruction 中位数 448 字符、20.3% 超过 2000，「问题」一词在全体单元里
    出现 42196 次且绝大多数在粘贴的日志里。全文等权会让日志决定分类。
    """
    text = "请你重构这个模块的结构\n" + "另外修复一下\n" * 3
    scores = labeler.score_categories(text)
    assert scores["refactor"] > scores.get("bug_fix", 0)


def test_label_head_is_first_line():
    """头部取首行而非固定切 120 字符

    实测「请你重构这个模块的结构，把 collector 拆出来」只有 27 字符，固定切 120
    会把后面粘贴的日志一起圈进「头部」，头部权重 ×3 反而放大日志里的词。
    """
    head = labeler.instruction_head("请你重构这个模块\n出现问题：Error 报错")
    assert head == "请你重构这个模块"
    assert "Error" not in head


def test_label_pasted_log_cannot_outvote_intent():
    """粘贴的日志不能靠重复词压倒真实意图（HIT_CAP 封顶）

    实测病理：「请你重构这个模块的结构」+ 20 行含「问题/报错/修复」的日志，
    封顶前 bug_fix 得 102 分而 refactor 仅 3 分，判成 bug_fix —— 用户要的是重构。
    """
    text = ("请你重构这个模块的结构，把 collector 拆出来"
            + "\n出现问题：Error 报错，问题定位失败，无法修复这个 bug。" * 20)
    assert labeler.pick_category(labeler.score_categories(text))[0] == "refactor"


def test_label_hit_cap_applied():
    """同一类别命中次数封顶，出现 1 次与 20 次等价"""
    once = labeler.score_categories("请你修复这个 bug")
    many = labeler.score_categories("请你修复 bug 修复 bug 修复 bug 修复 bug")
    assert once["bug_fix"] <= labeler.HEAD_WEIGHT * labeler.HIT_CAP
    assert many["bug_fix"] <= labeler.HEAD_WEIGHT * labeler.HIT_CAP


def test_label_zero_edit_readonly_boosts_comprehension():
    """零写 + 只读工具 → 理解类，但权重只 1.5（4.0 会盖过指令措辞）"""
    scores = labeler.objective_boost(
        {}, files=[], edit_ops=0, unique_tools=["Read", "Grep"], n_test_cmds=0)
    assert scores["code_comprehension"] == 1.5


def test_label_all_docs_boosts_doc_authoring():
    scores = labeler.objective_boost(
        {}, files=["a.md", "b.md"], edit_ops=3, unique_tools=["Edit"], n_test_cmds=0)
    assert scores["doc_authoring"] >= 5.0


def test_label_test_files_boost_test_authoring():
    """test_authoring 是稀缺类别（实测 0.1%），§4.6 要求优先保留"""
    scores = labeler.objective_boost(
        {}, files=["src/__tests__/a.test.ts"], edit_ops=2,
        unique_tools=["Edit"], n_test_cmds=0)
    assert scores["test_authoring"] >= 4.0


def test_label_confidence_from_margin():
    assert labeler.pick_category({"bug_fix": 10.0})[1] == "high"
    assert labeler.pick_category({"bug_fix": 10.0, "refactor": 1.0})[1] == "high"
    assert labeler.pick_category({"bug_fix": 10.0, "refactor": 6.0})[1] == "medium"
    assert labeler.pick_category({"bug_fix": 10.0, "refactor": 9.0})[1] == "low"
    assert labeler.pick_category({}) == ("unclassified", "low", 0.0)


def test_label_pick_category_is_deterministic():
    """同分时按名字排序取第一个 —— 不能依赖 dict 顺序，否则重跑结果会变"""
    a = labeler.pick_category({"refactor": 5.0, "bug_fix": 5.0})[0]
    b = labeler.pick_category({"bug_fix": 5.0, "refactor": 5.0})[0]
    assert a == b == "bug_fix"


def test_label_tags():
    tags = labeler.build_tags(
        files=["a.ts", "b.vue"], session_steps=60, error_ops=5,
        unique_tools=["Agent"], instruction="改一下")
    assert {"typescript", "vue", "multi_file", "long_horizon",
            "error_recovery", "sub_agent", "ambiguous_spec"} <= set(tags)


def test_label_error_recovery_threshold():
    """error_recovery 是真实困难任务的天然标记（§4.6），阈值 >=3"""
    assert "error_recovery" not in labeler.build_tags([], 0, 2, [], "x" * 50)
    assert "error_recovery" in labeler.build_tags([], 0, 3, [], "x" * 50)


# ── 贯穿：源信息与数据湖只读 ────────────────────────────────────────

def test_provenance_fields_complete():
    """⑮ 源信息块必须齐全（用户 2026-09-05 要求贯穿每层产物）"""
    rec = {
        "agent_source": "claude_code", "model": "claude-opus-5",
        "vendor": "anthropic", "repo": "person/sid-code",
        "repo_resolution": "voted", "provenance": "pre_upgrade",
    }
    prov = common.provenance_of(rec, "v0.2")
    assert not common.missing_provenance(prov)
    assert prov["batch_version"] == "v0.2"


def test_provenance_allows_null_repo():
    """repo 允许为 None（实测 490 条 unresolved），但键必须在

    门禁查「键齐全」而非「值非空」—— 否则会把数据事实误判成故障。
    """
    prov = common.provenance_of({"agent_source": "codex"}, "v0.2")
    assert not common.missing_provenance(prov)
    assert prov["repo"] is None


def test_provenance_detects_missing():
    assert "agent_source" in common.missing_provenance({"model": "x"})


def test_all_agent_sources_covered():
    """四条采集通道的模型分布完全不同，混算会得出错误结论"""
    assert set(common.AGENT_SOURCES) == {
        "claude_code", "codex", "sid_code", "short_id"}


def test_output_paths_outside_data_lake():
    """产物目录必须在数据湖之外 —— 移动/改写原始层会让 pull.py 重复下载

    上一轮把 1722 条移进 _trash/，实测让待拉取从 879 涨到 2601 条。
    """
    lake = Path(common.SESSIONS_DIR).resolve()
    for out in (common.FILTERED, common.UNITS, common.DESENS_DIR, common.P1_META):
        p = Path(out).resolve()
        assert lake not in p.parents and p != lake, f"{out} 落在数据湖内"


def test_common_module_is_not_shared_with_scripts_layer():
    """两层各有一个 common.py，同名不同物 —— 撞上时 sys.modules 会静默返回先加载的那份

    实测形态（迁移方案 §2.8）：先 import pipeline 那份、再 import scripts 那份，
    第二次拿到的 __file__ 仍是第一份，且 `MVP_TASKS` 整个不存在。
    最坏情况不是 AttributeError（那还算显眼），是两份都有的 `read_jsonl`
    被静默换掉：scripts 那份返回生成器，本层调用方写 len() ⇒ TypeError，
    或 for 遍历两次时第二次拿到空 —— 不报错，只是少处理一批数据。

    ⛔ 所以不许把两份 common.py 合并成一份「公共层」：常量表不兼容
    （本层 FILTERED/UNITS 是 str，scripts 层 MVP_TASKS 是 Path）。
    """
    import common
    here = Path(__file__).resolve().parent.parent      # pipeline/
    assert Path(common.__file__).resolve().is_relative_to(here), \
        f"import common 拿到了 {common.__file__} —— 不是本层那份，说明与 scripts/ 层撞了"
