#!/usr/bin/env python3
"""s3_segment.py — S3 会话切分的判定逻辑（被 s3-split.py 调用，也被单测直接引用）

出处：bench-curation-design.md §4.3「S3 会话切分」+ §9.4 坑①

拆成独立模块的理由：切分正确率 ≥90% 是 Phase 1 的关键验收项，判定逻辑必须能被
单测逐条覆盖，不能埋在读盘/并发代码里。

## 数据源为什么是 raw.jsonl 而不是 session.traj（§4.3 数据源修正）

方案初稿假定 trajectory 里能找到用户消息、`end_turn` 标记和逐步时间戳，实测三项
均不成立：`message_type` 只有 `action`/`observation`，user step 为 0；`stop_reason`
覆盖率 0.8%；`observation` 无 timestamp。用户指令实际在 `history` 里，但 history
条目只有 `{role, content, agent}`，**既无时间戳也无 step index**，无法定位切分点。

`raw.jsonl` 的增量结构天然带齐了所需信息：首行完整 `messages`，后续行
`new_messages` + `_messages_count`，且**每行都带 `index` 与 `timestamp`**。

本轮实测（400 条 steps>=3 抽样，冻结批次 v0.2）：

| 指标 | 本轮 | 方案 §4.3（6019 条时） |
|---|---|---|
| 有 raw.jsonl | 95.5% | 89.2% |
| 含 index+timestamp+messages 结构 | 100% | 85.5% |
| 能提取带时间戳的用户轮次 | 99.2% | 95.7% |
| 提取到 >=2 轮（实际可切分） | 62.3% | 52.9% |
| 平均轮次 | 4.21 | 2.78 |
| **覆盖上限** | **94.8%** | 85% |

覆盖率比方案预估高约 10 个点（§9.4 坑① 要求「本轮新数据要重新统计，别用旧数字」）。

## index → step_range 的映射依据

实测 40 条抽样中 35 条 raw 行时间戳与 trajectory 的 action step 时间戳**完全逐一
相等**（另 5 条部分对齐，无一条完全对不上）。所以映射不靠 index 算术推导，而是
**按时间戳对齐**：raw 行 timestamp → 同 timestamp 的 action step 下标。这比按
index 比例换算稳，因为 raw 行数与 trajectory 步数不是固定倍数（实测 action 步数
可达 raw 行数的 5 倍，如 0ce08c20 是 40 行 / 216 action）。
"""

import re

# ── 噪声识别 ────────────────────────────────────────────────────────

# 系统注入的标签。实测 user 消息 text 块里这类占比很高（3192 个 text 块中
# 1057 是真实用户输入，其余 2135 是各类系统标签）。
# v0.1 曾因未过滤，13/45 条 instruction 以 `<command-` 开头，spot-check 通过率
# 被拉到 71%（§4.3）。
NOISE_TAGS = (
    "system-reminder",
    "local-command-stdout",
    "local-command-caveat",
    "local-command-stderr",
    "command-name",
    "command-message",
    "command-args",
    "task-notification",
    "available-deferred-tools",
)

# 逐字前缀噪声（非 XML 标签形态）。前三条沿用 S0 口径，其余五条是本轮用独立
# 裁判（hook 通道的 metadata.user_prompts）对账时发现的 —— 它们全都是 **harness
# 自己注入的提示词**，被 API 层原样记成 role=user，但没有任何人类输入。
#
# 不滤掉的后果实测过：一条会话被切成 106 个单元而裁判只认 2 个真实指令，
# 其中 104 个是重复的 "Describe your most recent action…"。全库口径下精确率
# 只有 33.4%，远低于 ≥90% 的验收线。
#
# 各条的实测命中量（保留单元数）与性质：
#   805  "A session-scoped Stop hook is now active…"  hook 把用户目标回灌给模型
#   476  "Describe your most recent action in 3-5 words…"  生成状态行的内部提问
#   211  "Based on the conversation transcript above, has the following stopping…"
#                                                    停止条件自判，模型问模型
#    61  "Another Claude session sent a message:"     跨会话消息转发
#    57  "[SYSTEM NOTIFICATION - NOT USER INPUT]"     文本自己就写明了不是用户输入
NOISE_PREFIXES = (
    "[SUGGESTION MODE",
    "The user stepped away",
    "Caveat:",
    "A session-scoped Stop hook is now active",
    "Describe your most recent action",
    "Based on the conversation transcript above",
    "Another Claude session sent a message",
    "[SYSTEM NOTIFICATION",
)

_NOISE_TAG_RE = re.compile(r"^\s*<(" + "|".join(NOISE_TAGS) + r")\b", re.I)

# `<session>` 包裹的是**真实用户内容**（实测 634 个单元，正文是粘贴的文档路径与
# 真实诉求），不能当噪声丢掉 —— 要拆掉外层标签取里面的正文。
# 同理 `<conversation>`、`<select …>`、`<!-- … -->` 都是用户粘贴的素材。
_UNWRAP_TAGS = ("session", "conversation")
_UNWRAP_RE = re.compile(
    r"^\s*<(" + "|".join(_UNWRAP_TAGS) + r")>\s*(.*?)\s*(?:</\1>)?\s*$",
    re.I | re.S,
)


def unwrap_user_text(text: str) -> str:
    """拆掉 `<session>` 这类包裹标签，取出里面的用户正文"""
    m = _UNWRAP_RE.match(text or "")
    return m.group(2) if m else text

# 报错日志特征 → 是上个任务的反馈，不是新任务（§4.3 弱信号）
ERROR_LOG_RE = re.compile(
    r"(Traceback \(most recent call last\)|^\s*at .+:\d+:\d+|"
    r"\bError:|\bERR!|\bException\b|error TS\d+|"
    r"FAIL\s|✗|failed with exit code)",
    re.M,
)

# 追问词。命中且短 → 归入前一任务（§4.3 弱信号）
FOLLOWUP_WORDS = (
    "继续", "接着", "还有", "不对", "再改", "这个", "那个", "然后", "为什么",
    "为啥", "不行", "还是", "改一下", "再来", "重新", "试试", "好的", "嗯",
    "ok", "okay", "continue", "go on", "next", "again", "why", "hmm",
)

# 任务起始模式：含动词 + 对象的完整指令（§4.3 强信号 3）
TASK_START_RE = re.compile(
    r"(请你?|帮我|麻烦|需要|我要|我想|现在)?\s*"
    r"(实现|新增|添加|加上|修复|修改|改成|重构|优化|删除|移除|清理|"
    r"分析|排查|调查|检查|审查|评审|设计|规划|梳理|整理|写|编写|补全|"
    r"补充|生成|创建|新建|部署|发布|升级|迁移|测试|验证|跑一下|执行|"
    r"实施|开始|完成|处理|解决|支持|重命名|拆分|合并|替换|统一|对齐|"
    r"implement|add|create|fix|refactor|optimi[sz]e|remove|delete|"
    r"analy[sz]e|investigate|review|design|write|generate|deploy|"
    r"upgrade|migrate|test|verify|split|merge|rename|replace|support)"
)

# 强边界：时间间隔阈值（§4.3 强信号 1）
GAP_SECONDS = 30 * 60

# 追问判定的长度上限（§4.3 弱信号：以追问词开头且 <20 字符）
FOLLOWUP_MAX_LEN = 20

# 任务起始模式要求的最小长度（§4.3 强信号 3）
TASK_START_MIN_LEN = 40


def is_noise(text: str) -> bool:
    """是否系统注入的噪声文本

    注意**不能**简单按 `<` 开头判定：实测 `<session>`、`<conversation>`、
    `<select class=...>`、`<!--` 都是用户真实粘贴的内容（粘贴的文档、Vue 模板、
    提示词文件），误杀它们会丢掉真实指令。只按已知标签名匹配。
    """
    if not text or not text.strip():
        return True
    if _NOISE_TAG_RE.match(text):
        return True
    return text.lstrip().startswith(NOISE_PREFIXES)


def user_text_blocks(msg: dict) -> list[str]:
    """从一条 user 消息里取出非噪声 text 块

    user 消息的 content 绝大多数是 tool_result（实测 25935 个 tool_result
    vs 3192 个 text），tool_result 不是用户输入，必须跳过。
    """
    content = msg.get("content")
    if isinstance(content, str):
        blocks = [content]
    elif isinstance(content, list):
        blocks = [
            b.get("text") or ""
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
    else:
        return []
    out = []
    for t in blocks:
        if is_noise(t):
            continue
        t = unwrap_user_text(t)
        # 拆包后再查一次：`<session>` 里也可能裹着 harness 注入的提示词
        if not t.strip() or is_noise(t):
            continue
        if is_injected_prompt(t):
            continue
        out.append(t)
    return out


# ── 边界判定 ────────────────────────────────────────────────────────

# 客套前缀。判定追问前必须先剥掉 —— 实测 251 个单元以「请继续」开头却被判成
# 新任务边界，因为 startswith 查的是「继续」而文本以「请继续」开头。
# 这类漏判会把「让 agent 接着干」误当成新任务，直接制造多切。
_POLITE_PREFIX = re.compile(r"^\s*(请你?|帮我|麻烦你?|你|能不能|可以)\s*")


def strip_polite(text: str) -> str:
    return _POLITE_PREFIX.sub("", text or "", count=1).strip()


def looks_like_followup(text: str) -> bool:
    """是否追问（归入前一任务）"""
    t = strip_polite(text)
    low = t.lower()
    if len(t) < FOLLOWUP_MAX_LEN and low.startswith(FOLLOWUP_WORDS):
        return True
    # 「继续/接着」类无论多长都算追问：它明确指向「上一个任务还没做完」，
    # 而长度只反映用户补充了多少上下文。实测「请继续完成任务，文档还没写」
    # 这类 13 字符的句子，语义上就是追问。
    if low.startswith(("继续", "接着", "重新", "continue", "go on")):
        return True
    # 粘贴的报错日志 = 上个任务的反馈
    return bool(ERROR_LOG_RE.search(t))


# slash 命令的**定义正文**（不是用户调用它时说的话）。Claude Code 把
# `.claude/commands/*.md` 的全文当 user 消息注入，形如
# 「# JD 映射：… 当用户调用 `/jd-map <路径>` 时，按以下流程执行。」
# 用独立裁判对账：伪块中命中 111 个，真实块中仅 2 个 —— 判别力足够。
SLASH_COMMAND_BODY_RE = re.compile(r"当用户调用\s*`?/[a-zA-Z0-9_\-]")

# 中断标记：采集侧插入的占位文本，不是用户输入。伪块 92 个 / 真实块 0 个。
INTERRUPT_MARKER = "[Request interrupted"


# 转录回放：会话恢复时，harness 把之前的对话（含子 agent 的往来）以
# 「Agent (Explore): …」「User: …」的带说话人前缀形式重新注入成一条 user 消息。
# 这些是**上一段会话的转录**，不是本轮的人类输入。
TRANSCRIPT_REPLAY_RE = re.compile(
    r"^\s*(?:Agent\s*\([^)]{1,40}\)|User|Assistant|Human)\s*:\s")

# CLAUDE.md / 项目配置注入
CONFIG_INJECTION_MARKERS = (
    "user's CLAUDE.md configuration",
    "Contents of /",
    "Continue from where you left off",
)


def is_injected_prompt(text: str) -> bool:
    """是否 harness 注入的提示词正文（而非人类输入）

    只放**已用独立裁判验证过判别力**的两类。其余形似模板的文本（如以 `#` 开头
    的 markdown 正文）不在这里拦 —— 实测真实块里也有 13 个以 `#` 开头（用户粘贴
    文档很常见），拦掉会误杀真实指令。那类走 `boundary_confidence` 标注而不是丢弃。
    """
    head = (text or "")[:400]
    if INTERRUPT_MARKER in head[:60]:
        return True
    if TRANSCRIPT_REPLAY_RE.match(head):
        return True
    if any(m in head[:150] for m in CONFIG_INJECTION_MARKERS):
        return True
    return bool(SLASH_COMMAND_BODY_RE.search(head))


def looks_like_task_start(text: str) -> bool:
    """是否任务起始模式且够长（§4.3 强信号 3）"""
    t = text.strip()
    return len(t) >= TASK_START_MIN_LEN and bool(TASK_START_RE.search(t))


def parse_ts(ts: str | None) -> float | None:
    """解析 ISO 时间戳为秒。容忍缺失与格式异常"""
    if not ts or not isinstance(ts, str):
        return None
    import datetime
    s = ts.strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.UTC).replace(tzinfo=None)
    return dt.timestamp()


def decide_boundary(
    turn: dict,
    prev_turn: dict | None,
    prev_files: set[str] | None = None,
) -> tuple[bool, str]:
    """判定一个用户轮次是否新任务起点

    返回 (是否切分, 理由)。理由取值固定，供验收脚本统计各信号贡献度。

    首轮永远是边界（B_FIRST）。其余按方案 §4.3：先查弱信号（追问 → 不切），
    再查三条强信号（任一命中即切）。

    **弱信号优先于强信号**是刻意的：一段粘贴的报错日志很可能同时匹配
    TASK_START_RE（含「修复」等词）又超过 40 字符，若强信号先判就会把
    「上个任务的报错反馈」误切成新任务。实测报错日志粘贴很常见。
    """
    if prev_turn is None:
        return True, "B_FIRST"

    text = turn["text"]

    # 弱信号：追问或报错反馈 → 不切
    if looks_like_followup(text):
        return False, "W_FOLLOWUP"

    # 强信号 1：时间间隔 > 30 分钟（人离开又回来）
    t_now, t_prev = turn.get("ts_epoch"), prev_turn.get("ts_epoch")
    if t_now is not None and t_prev is not None and (t_now - t_prev) > GAP_SECONDS:
        return True, "B_TIME_GAP"

    # 强信号 2：与前一任务的文件集合交集为空（改的完全是另一批文件）
    # 只在两边都有文件时判定 —— 空集与任何集合交集都为空，
    # 若不设这个前提，「本轮还没碰文件」会被误判成新任务。
    if prev_files and turn.get("files"):
        if not (prev_files & set(turn["files"])):
            return True, "B_FILE_DISJOINT"

    # 强信号 3：任务起始模式 + 长度 >= 40
    if looks_like_task_start(text):
        return True, "B_TASK_PATTERN"

    return False, "W_SAME_TASK"


# ── 边界置信度 ──────────────────────────────────────────────────────

# 各边界信号的置信度。分档依据是用独立裁判（hook 通道 metadata.user_prompts）
# 逐信号对账的结果 —— 见 verify-phase1.py 的 s3 门禁。
#
# **为什么要有这个字段，而不是把切分正确率做到 90% 再交付**：
# 用两条独立信号交叉验证后确认，「切分正确率」这个指标本身没有可信的裁判：
#   · hook 侧裁判（user_prompts / UserPromptSubmit，两者一致率 99.8%）在
#     56.1% 的会话里只记录 1 条 prompt，而这些会话的召回率高达 77.5% ——
#     说明裁判自己漏记；
#   · 按裁判完备度分层后，裁判记 >=5 条的会话精确率 50.0%、召回 38.7%，
#     裁判记 1 条的会话精确率 38.7%、召回 77.5%。两端相反的走势说明
#     **双方都有错**，不能把任一方当真值。
# 在这种情况下报一个「正确率 92%」是自欺。诚实的做法是：把每个边界的判据
# 记下来，让 S4/S6 能按置信度筛选，并在 Phase 2 用 LLM 对 low 档做复判
# （与 §4.6 对未分类样本的处置方式一致）。
# 分档取自逐信号实测（裁判 >=2 条的会话口径，n 为该信号的单元数）：
#
#   B_NO_RAW          100.0%  (n=26)    整条会话一个单元，不存在切错的可能
#   B_FIRST            74.8%  (n=552)   会话第一条指令
#   B_TIME_GAP         73.0%  (n=37)    间隔 >30 分钟
#   B_FILE_DISJOINT    57.1%  (n=119)   文件集合无交集
#   B_TASK_PATTERN     37.4%  (n=995)   措辞判定 —— 多切的主要来源
#
# 只用「裁判 >=2 条」的会话计算：裁判只记 1 条时，我方首单元必然匹配，
# 会把 B_FIRST 的精确率虚高成无判别力的数字。
BOUNDARY_CONFIDENCE = {
    "B_NO_RAW": "high",         # 实测 100%：没有切分动作，就没有切错的可能
    "B_FIRST": "high",          # 实测 74.8%
    "B_TIME_GAP": "high",       # 实测 73.0%
    "B_FILE_DISJOINT": "medium",  # 实测 57.1%
    "B_TASK_PATTERN": "low",    # 实测 37.4% —— 必须交 Phase 2 LLM 复判
}


def boundary_confidence(reason: str) -> str:
    return BOUNDARY_CONFIDENCE.get(reason, "low")
