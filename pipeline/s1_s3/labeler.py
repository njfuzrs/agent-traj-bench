#!/usr/bin/env python3
"""labeler.py — 分类与标注的判定逻辑（被 label-units.py 调用，也被单测直接引用）

出处：bench-curation-design.md §4.6「分类体系（taxonomy）」

**这一步是用户 2026-09-05 新提出的需求，方案原文把它排在 Phase 2。** 提前到 Phase 1
的理由：分类与源信息是「筛选查看」的前提，没有它，11591 个单元就是一堆无法检索的
jsonl 行；而 S4 分诊要按类别配平采样，也需要先有类别。

## 三组标注（正交，互不覆盖）

| 组 | 字段 | 用途 |
|---|---|---|
| 主类别 | `category` + `category_confidence` | 测什么能力（§4.6 单选） |
| 标签 | `tags[]` | 切片分析，不参与判定（§4.6 多选） |
| 难度 | `difficulty` + `difficulty_basis` | 分层采样（§4.6，绑客观量） |

源信息（`agent_source` / `model` / `vendor` / `repo` / `batch_version`）不在这里
生成 —— 它从 S0 一路带下来，见 common.py。

## 为什么用加权打分而不是「正则首命中」

方案 §2.7 的画像用的是首命中法，得到 bug_fix 54.5%。我按同法在 11591 个单元上
复现，得到 66.2%，并且发现**76.5% 的单元同时命中 ≥2 个类别** —— 首命中等于
「谁的正则写在前面谁赢」，这个数字没有判别力。

根因是长指令。实测 instruction 中位数 448 字符、47.9% 超过 500、20.3% 超过 2000，
里面粘贴了大量报错日志和代码。「问题」这个词在全体单元里出现 **42196 次**，绝大
多数在粘贴的日志里而不在真正的指令里。全文匹配等于让日志决定分类。

所以改成三条一起用：

1. **位置加权**。指令头部（前 120 字符）的命中权重 ×3 —— 用户的真实意图几乎总在
   开头。实测只看头部时多重命中从 65.9% 降到 28.5%，但无命中升到 35.9%，所以不
   只看头部，而是加权。
2. **客观信号加成**。`edit_ops == 0` 且有 Read/Grep → 更像 code_comprehension；
   `.md` 独占改动 → doc_authoring；测试文件改动 → test_authoring。这些来自轨迹
   实际发生了什么，比指令措辞可靠。
3. **置信度显式记录**。第一名与第二名的分差 <30% 记 `low`，交 Phase 2 的 LLM 复判
   （§4.6：「那 23.6% 的未分类…进 S6 前用 LLM 做一次分类」）。**不假装确定**。
"""

import re

HEAD_CHARS = 120
HEAD_WEIGHT = 3.0
BODY_WEIGHT = 1.0

# 单个类别在头部/正文各自的命中次数上限。
#
# 为什么要封顶：按命中次数线性计分时，**粘贴的日志靠重复词就能压倒真实意图**。
# 实测病理用例「请你重构这个模块的结构」+ 20 行含「问题/报错/修复」的日志：
# bug_fix 得 102 分而 refactor 只有 3 分，判成 bug_fix —— 而用户要的是重构。
# 封顶后一个词出现 1 次和 20 次等价，措辞的**种类**而非**频次**决定分类。
HIT_CAP = 2

# 主类别关键词（§4.6 的 7 类）。刻意收窄到「意图动词」，不含「问题」这类
# 在日志里高频出现的词 —— 它在全体单元里出现 42196 次，几乎全在粘贴的日志里。
CATEGORY_PATTERNS: dict[str, re.Pattern] = {
    "bug_fix": re.compile(
        r"(修复|修一下|修改一下|fix\b|bug|报错|异常|不生效|失效|崩溃|挂了|"
        r"排查|定位|复现|回归|不работ|没生效|错位|越界|死循环|内存泄漏|"
        r"debug|broken|crash|regression)", re.I),
    "feature_impl": re.compile(
        r"(实现|新增|添加|加上|加个|新加|支持|开发|接入|集成|做一个|做个|"
        r"implement|add\s|create\s|feature|新功能|新接口|新模块)", re.I),
    "refactor": re.compile(
        r"(重构|重写|拆分|抽取|提取|统一|规范化|简化|收敛|下沉|上提|解耦|"
        r"refactor|restructure|extract|简化实现|去重复)", re.I),
    "test_authoring": re.compile(
        r"(写.{0,4}测试|补.{0,4}测试|加.{0,4}测试|单测|测试用例|单元测试|"
        r"覆盖率|coverage|test\s?case|写个测试|补齐测试)", re.I),
    "doc_authoring": re.compile(
        r"(写文档|文档|方案|设计稿|readme|写一份|总结|报告|注释|说明书|"
        r"记录一下|整理成文|design\s?doc|changelog)", re.I),
    "code_comprehension": re.compile(
        r"(解释|讲讲|是什么|梳理|阅读|研究|评估|对比|讲一下|说明一下|"
        r"怎么实现|如何工作|原理|为什么这样|理解|explain|understand|"
        r"how does|what is)", re.I),
    "env_ops": re.compile(
        r"(部署|构建|打包|依赖|安装|配置|环境|docker|镜像|发布|上线|"
        r"commit|merge|分支|rebase|ci\b|流水线|pipeline|deploy|build\b)", re.I),
}

# 技术栈标签：按改动文件的扩展名判定（比指令措辞可靠）
EXT_TAGS = {
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".vue": "vue", ".py": "python", ".sh": "bash", ".bash": "bash",
    ".md": "markdown", ".yml": "yaml", ".yaml": "yaml",
    ".json": "json", ".css": "css", ".scss": "css", ".html": "html",
    ".go": "go", ".rs": "rust", ".java": "java", ".sql": "sql",
}

TEST_PATH_RE = re.compile(r"(^|/)(tests?|__tests__|spec)/|\.(test|spec)\.[a-z]+$", re.I)
DOC_PATH_RE = re.compile(r"\.(md|mdx|rst|txt)$", re.I)

# 能力维度标签的阈值（§4.6）
MULTI_FILE_MIN = 2
LONG_HORIZON_MIN_STEPS = 50
ERROR_RECOVERY_MIN = 3
AMBIGUOUS_SPEC_MAX_LEN = 20

# 难度客观锚点（§4.6，阈值取自 SWE-bench Verified 实测统计）
# 这里只有改动文件数与写操作次数可用（gold patch 的 hunk/行数要到 Phase 3 才有），
# 所以 difficulty_basis 记 `proxy_editops` 明示这是代理指标而非最终判定。
def classify_difficulty(n_files: int, edit_ops: int) -> tuple[str, str]:
    """按改动量估难度。返回 (difficulty, basis)

    **零写操作的单元记 `unrated` 而不是 `easy`**。这一条是实测逼出来的：
    51.1% 的单元 `edit_ops == 0`（3622/7094；会话级看，4381 条保留会话里 1818 条
    = 41.5% 整条都没有写操作，是纯问答/探索会话 —— 已核对不是 S3 漏算，单元
    edit_ops 合计对会话 n_edit_ops 的覆盖率为 100.9%）。

    把它们判成 easy 会造出 easy 67.9% 的偏斜（实测反事实：4817/7094），正是
    v0.1 失控的同一个错误
    （v0.1 是 hard 87.4%，方向相反、病理相同：**用一个与难度无关的量当难度锚点**）。
    没有改动量就是没有难度信息，`unrated` 是诚实的答案；这批单元的难度等
    Phase 3 有了参考解 diff 再定（§4.6 要求绑 gold patch 的 hunk/行数）。

    只对有写操作的单元评级后实测 hard 41.2% / easy 34.4% / medium 24.3%
    （n=3472），最大单档 41.2%，通过「不出现单档 >60%」的验收线。
    """
    if edit_ops == 0:
        return "unrated", "no_edit_ops"
    if n_files <= 1 and edit_ops <= 2:
        return "easy", "proxy_editops"
    if n_files <= 2 and edit_ops <= 6:
        return "medium", "proxy_editops"
    return "hard", "proxy_editops"


def instruction_head(text: str) -> str:
    """取指令头部：首行，最多 HEAD_CHARS 字符

    为什么是「首行」而不是固定切前 120 字符：用户粘贴的日志、代码、文档几乎总是
    从第二行起（第一行是他自己写的诉求）。实测「请你重构这个模块的结构，把
    collector 拆出来」只有 27 字符，固定切 120 会把后面粘贴的日志一起圈进「头部」，
    于是头部权重 ×3 反而放大了日志里的词 —— 头部加权形同虚设。
    """
    first = (text or "").split("\n", 1)[0]
    return first[:HEAD_CHARS] if first.strip() else (text or "")[:HEAD_CHARS]


def score_categories(text: str) -> dict[str, float]:
    """对每个类别打分：头部命中 ×3，正文命中 ×1，各自封顶 HIT_CAP 次"""
    head = instruction_head(text)
    body = (text or "")[len(head):]
    scores: dict[str, float] = {}
    for name, rx in CATEGORY_PATTERNS.items():
        h = min(len(rx.findall(head)), HIT_CAP)
        b = min(len(rx.findall(body)), HIT_CAP)
        s = HEAD_WEIGHT * h + BODY_WEIGHT * b
        if s:
            scores[name] = s
    return scores


def objective_boost(
    scores: dict[str, float],
    files: list[str],
    edit_ops: int,
    unique_tools: list[str],
    n_test_cmds: int,
) -> dict[str, float]:
    """用轨迹里实际发生的事修正打分

    比指令措辞可靠：用户说「看看这个 bug」但全程只 Read/Grep 没改一行，
    那它是 code_comprehension 不是 bug_fix。
    """
    out = dict(scores)
    tools_l = {t.lower() for t in unique_tools}

    # 零写操作 + 只读工具 → 理解类。
    #
    # 权重刻意压到 1.5（初版给 4.0）：4.0 会盖过指令本身的措辞，把 1623 个单元
    # 从别的类别改判成 code_comprehension —— 包括「任务被切在中途、还没开始改」
    # 这种本该按指令意图归类的单元。零写只是**弱证据**：它同样可能意味着任务
    # 未完成，而不是「用户想要一份解释」。
    #
    # 实测这个加成不是 code_comprehension 占比高的主因（W 从 4.0 降到 1.0，
    # 占比只从 32.1% 降到 24.0%），主因是指令措辞本身 —— 探索类会话在本数据集
    # 里确实很多（41.5% 的保留会话整条零写）。所以不再靠调这个权重去凑
    # §4.6 的 3.7%：那个数字是「会话首条指令 + 正则首命中」口径下的产物，
    # 与「单元级 + 加权打分」不可直接比。真实分布由抽样人工核对确认。
    if edit_ops == 0 and (tools_l & {"read", "grep", "glob", "search"}):
        out["code_comprehension"] = out.get("code_comprehension", 0) + 1.5

    # 改动全是文档 → 文档类
    if files and all(DOC_PATH_RE.search(f) for f in files):
        out["doc_authoring"] = out.get("doc_authoring", 0) + 5.0

    # 改动含测试文件 → 测试类。这是稀缺类别（实测 0.1%），§4.6 要求优先保留
    if any(TEST_PATH_RE.search(f) for f in files):
        out["test_authoring"] = out.get("test_authoring", 0) + 4.0

    # 跑了门禁命令但没改测试文件 → 更可能是 bug_fix / feature 的验证环节，不加成
    if n_test_cmds >= 3 and any(TEST_PATH_RE.search(f) for f in files):
        out["test_authoring"] = out.get("test_authoring", 0) + 2.0

    # 只改配置/构建文件 → 工程化
    if files and all(
        re.search(r"(package\.json|pyproject\.toml|Dockerfile|\.ya?ml|"
                  r"\.config\.[jt]s|Makefile|requirements\.txt)$", f, re.I)
        for f in files
    ):
        out["env_ops"] = out.get("env_ops", 0) + 4.0

    return out


def pick_category(scores: dict[str, float]) -> tuple[str, str, float]:
    """选主类别。返回 (category, confidence, margin)

    confidence 三档：
      high    第一名比第二名高 >=60%，或只有一个类别命中
      medium  高 30%-60%
      low     高 <30%，或没有任何命中 → 交 Phase 2 LLM 复判
    """
    if not scores:
        return "unclassified", "low", 0.0
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    top, top_s = ranked[0]
    if len(ranked) == 1:
        return top, "high", 1.0
    second_s = ranked[1][1]
    margin = (top_s - second_s) / top_s if top_s else 0.0
    if margin >= 0.6:
        conf = "high"
    elif margin >= 0.3:
        conf = "medium"
    else:
        conf = "low"
    return top, conf, round(margin, 3)


def build_tags(
    files: list[str],
    session_steps: int,
    error_ops: int,
    unique_tools: list[str],
    instruction: str,
    has_thinking: bool = False,
) -> list[str]:
    """构造标签（§4.6 多选，不参与判定）"""
    tags: set[str] = set()

    for f in files:
        i = f.rfind(".")
        if i >= 0:
            t = EXT_TAGS.get(f[i:].lower())
            if t:
                tags.add(t)

    if len({f for f in files}) >= MULTI_FILE_MIN:
        tags.add("multi_file")
    if session_steps >= LONG_HORIZON_MIN_STEPS:
        tags.add("long_horizon")
    # §4.6：撞墙过程是真实困难任务的天然标记，这批优先进 capability split
    if error_ops >= ERROR_RECOVERY_MIN:
        tags.add("error_recovery")
    if any(t.lower() in {"agent", "task", "subagent"} for t in unique_tools):
        tags.add("sub_agent")
    if has_thinking:
        tags.add("thinking")
    if len((instruction or "").strip()) < AMBIGUOUS_SPEC_MAX_LEN:
        tags.add("ambiguous_spec")

    return sorted(tags)


def label(unit: dict) -> dict:
    """给一个（已脱敏的）单元打全部标注"""
    instr = unit.get("instruction_clean") or ""
    files = unit.get("files_clean") or []
    edit_ops = unit.get("edit_ops") or 0
    tools = unit.get("unique_tools") or []

    scores = objective_boost(
        score_categories(instr), files, edit_ops, tools,
        unit.get("n_test_cmds") or 0,
    )
    category, conf, margin = pick_category(scores)
    difficulty, basis = classify_difficulty(len(set(files)), edit_ops)

    return {
        "category": category,
        "category_confidence": conf,
        "category_margin": margin,
        "category_scores": {k: round(v, 2) for k, v in sorted(scores.items())},
        "tags": build_tags(
            files, unit.get("session_steps") or 0, unit.get("error_ops") or 0,
            tools, instr,
        ),
        "difficulty": difficulty,
        "difficulty_basis": basis,
        "n_files": len(set(files)),
    }
