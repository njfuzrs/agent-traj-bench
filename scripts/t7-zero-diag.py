#!/usr/bin/env python3
"""T7 — 真 0 / 假 0 归因。**纯读产物，不跑任何东西、不花钱。**

## 为什么必须有这个脚本

方案预案表写死了一条：**「全部模型 pass@1 < 10% ⇒ 优先怀疑 grader，
先用 verifier_health 分辨真 0 假 0」**。本批 pass@1 = 0%，这条直接触发。

⛔ 不许只看 `reward=0` 就下「模型能力差」的结论 —— TZ 的 R-4 实测过反例：
oracle 拿 0 分、Exceptions=0，真因是 github 间歇不可达导致 uv 装不上，
那是**假 0 分**。形态是「数字齐全、看不出任何错误」。

## 三层判据（缺一层就会误判）

**① 判分侧有没有拿到测试节点**（真 0 的前提）
   `error_code` / `score-detail.json` 的 `missing` / `no_tests`。
   f2p 声明了 N 个文件却只 seen 到 M 个 ⇒ 判分没看全，**不能算模型答错**。

**② 模型有没有真的动过工作区**
   数 `tool_use` 里的写文件工具（write/edit/...）。
   ⚠️ 工具名在 sid-code 侧是**小写**（`write` 不是 `Write`）——
   2026-09-13 实测踩过：按首字母大写的正则查，5/5 条全报 0 次改动，
   而那是**仪器坏了**，不是模型没改。

**③ 这一轮是怎么终止的**
   `metadata.sid_subtype`。`error_max_turns` 有**两类成因、不可混算**
   （出处：`sid_code_agent.py` 那段注释）：

     - `num_turns + num_turns_without_model_interaction == max_turns + 1`
       ⇒ 轮次**真的用尽**，每一轮都换来了模型交互 ⇒ 抬 `--max-turns` 才有意义
     - `without_model_interaction > 0`
       ⇒ 有几格轮次**没换来模型交互**（超时/watchdog 杀在零产出上）
       ⇒ 是网络/重试问题，抬轮数**治不了**

   两种成因的修法完全相反，所以必须分开报。

## 用法

    ~/.local/share/uv/tools/harbor/bin/python scripts/mvp/t7-zero-diag.py
    ~/.local/share/uv/tools/harbor/bin/python scripts/mvp/t7-zero-diag.py --json

输出 `reports/baseline/zero-diag.json`（机器可读，供报告引用）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402
import t7_report_lib as lib  # noqa: E402

#: 取数源目录。默认第一轮 `baseline/`；整改后那批传 `--runs t8-rerun`。
#: 🔴 必须与 `t7-report.py --runs` **同时切**：报告去 `RUNS/zero-diag.json` 取归因，
#: 两边不一致的形态是**报告静默引用另一批的归因数据** —— §9 的结论对应的是
#: 另一轮的 trial，而两侧都不报错。
RUNS = c.MVP_REPORTS / "baseline"
RECHECK = c.MVP_REPORTS / "t6-recheck"
OUT = RUNS / "zero-diag.json"


def _retarget(runs_name: str) -> None:
    """把取数源与产物路径一起切到另一批（⛔ 只改 RUNS 会把结果写进旧批目录）。"""
    global RUNS, OUT
    RUNS = c.MVP_REPORTS / runs_name
    OUT = RUNS / "zero-diag.json"


def _rel(p: Path) -> str:
    """仓内路径写相对、仓外写绝对。

    ⛔ 不能用裸 `relative_to`：路径不在仓内时它**抛 ValueError**。
    `MVP_DIR` 是可被环境变量改的（冒烟测试就把它指到 /tmp），
    形态是「脚本干完所有活、崩在打印路径的最后一行」，报错完全不指向路径。

    ⚠️ **这是同一个坑的第二次**：`t7-report.py` 早有同名函数、docstring 写着
    2026-09-12 冒烟时撞到过，我写这个新脚本时没沿用 —— 2026-09-13 冒烟又抓到。
    新脚本里凡是要打印路径，一律走这个函数。
    """
    try:
        return str(p.resolve().relative_to(c.REPO_ROOT))
    except ValueError:
        return str(p)

#: sid-code 侧的写文件工具名。🔴 **全小写** —— 见模块 docstring ② 的实测。
WRITE_TOOLS = {"write", "edit", "multi_edit", "multiedit", "str_replace",
               "apply_patch", "notebook_edit"}

#: 「在容器里找那份不存在的文档」的动作特征：find/ls 且提到 docs 或带中文文件名。
#: ⚠️ 这是个**近似**指标，用来量级说明而非精确计数，报告里要标明「约」。
_FIND_DOC = re.compile(r"\b(find|ls)\b")
_CJK = re.compile(r"[一-鿿]")

#: 🔴 f2p 日志里的「整份测试文件加载失败」签名。命中 ⇒ 测试**跑到了**，
#: 是被 import 的 src 符号不存在（而那正是 gold patch 要创建的）⇒ 模型没做到，**真 0**。
#: ⛔ 没有这个判据，`missing` 会被一律误判成「判分侧没看全」，方向偏袒模型。
_LOAD_FAIL = re.compile(r"Cannot find module|SyntaxError: Export named")


def _is_upstream_failure(md: dict) -> bool:
    """上游 LLM 链路断了 ⇒ 假 0 分。

    🔴 判据与签名表**复用 `t7_report_lib`**，⛔ 不在这里另抄一份 ——
    两处各存一份的形态是「报告说仪器故障、归因说模型没做到」，
    而读者无从判断哪个是真的（口径打架比判错更难查）。
    """
    return lib.Trial(
        task="", reward=0.0, f2p=None, p2p=None, error_code=0, exception=None,
        subtype=md.get("sid_subtype"),
        errors=tuple(str(e) for e in (md.get("sid_errors") or [])),
    ).upstream_failure
def _agent_started(trial_dir: Path) -> bool:
    """agent 进程**真的跑起来了吗** —— 判据刻意不依赖 metadata。

    🔴 2026-09-14 抓到（T0009，本批唯一）：题面 131,498 B 超过 Linux
    `MAX_ARG_STRLEN`（实测 131,000 过 / 131,060 起 `Argument list too long`），
    `bash -c` **拒绝 exec** ⇒ agent 一个字都没跑，退出码 255。
    而 verifier 照常跑测试、照常打分 ⇒ `reward=0.0`。

    形态之所以危险：它与「模型改了但改错」在判分侧**读数一样**（都是 reward=0、
    f2p 有加载失败），于是被判成 `true_zero_missing_symbol` —— 那是**能力信号**。
    ⇒ 一次「题面装不进命令行」的工程故障，被记成「模型没写出 gold patch 的符号」。

    ⛔ **判据不能读 `result.json` 的 metadata**：agent 没跑 ⇒ 那份 metadata
    整体缺失（`sid_subtype` / `sid_num_turns` 全 None），拿缺失去判「有没有跑」
    是循环论证 —— 这正是 `agent-started-fourth-form-of-fake-zero` 那条教训：
    **判据必须取一个不依赖被怀疑那条链路的源**。

    所以判据取 agent 侧的**落盘产物**：`agent/sid-code.jsonl` 非空
    （agent 一启动就往它写事件流）。全批 39 条实测：启动 38 / 未启动 1，
    唯一那条正是 T0009。
    """
    j = trial_dir / "agent/sid-code.jsonl"
    try:
        return j.stat().st_size > 0
    except OSError:
        return False


_RAN_LINE = re.compile(r"Ran \d+ tests? across \d+ files?")


def iter_tool_uses(jsonl: Path):
    """逐个 yield `(tool_name, input_dict)`。

    ⛔ 不能用 grep `"name":"X"` 数工具调用 —— 那会把 **工具目录**（system 行里
    列出的可用工具清单，每个名字恰好出现一次）当成调用。2026-09-13 实测：
    grep 数出 66 次 `bash`、1 次 `write`，而真实 `tool_use` 是 65 次 bash、
    **0 次 write** —— 那个 1 次 write 是目录里的定义。
    """
    if not jsonl.exists():
        return
    for line in jsonl.open(encoding="utf-8", errors="ignore"):
        line = line.strip()
        if not line:
            continue
        try:
            j = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(j, dict):
            continue
        msg = j.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for blk in content:
            if isinstance(blk, dict) and blk.get("type") == "tool_use":
                yield blk.get("name"), (blk.get("input") or {})


def diagnose_one(trial_dir: Path, max_turns: int) -> dict:
    """一条 trial 的三层判定。"""
    task = trial_dir.name.split("__")[0]
    out: dict = {"task": task, "trial_dir": trial_dir.name}

    # ── ① 判分侧 ──
    rj = trial_dir / "verifier/reward.json"
    if not rj.exists():
        out["verdict"] = "running"
        out["why"] = "还没跑完（无 reward.json）"
        return out
    rw = json.loads(rj.read_text(encoding="utf-8"))
    out.update({k: rw.get(k) for k in ("reward", "f2p", "p2p", "error_code")})

    sd_p = trial_dir / "verifier/score-detail.json"
    sd = json.loads(sd_p.read_text(encoding="utf-8")) if sd_p.exists() else {}
    f = sd.get("f2p") or {}
    out["f2p_detail"] = {"n_required": f.get("n_required"), "n_seen": f.get("n_seen"),
                         "n_failed": len(f.get("failed") or []),
                         "n_missing": len(f.get("missing") or []),
                         "n_no_tests": len(f.get("no_tests") or [])}

    # ── ② 模型动过工作区吗 ──
    tools = Counter()
    n_find_doc = 0
    for name, inp in iter_tool_uses(trial_dir / "agent/sid-code.jsonl"):
        tools[name] += 1
        if name == "bash":
            cmd = str(inp.get("command") or "")
            if _FIND_DOC.search(cmd) and ("docs" in cmd or _CJK.search(cmd)):
                n_find_doc += 1
    out["tool_calls"] = dict(tools.most_common())
    out["n_write_tool_calls"] = sum(v for k, v in tools.items() if k in WRITE_TOOLS)
    out["n_bash"] = tools.get("bash", 0)
    out["n_bash_hunting_doc"] = n_find_doc

    # ── ③ 怎么终止的 ──
    res_p = trial_dir / "result.json"
    md = {}
    if res_p.exists():
        md = ((json.loads(res_p.read_text(encoding="utf-8")).get("agent_result") or {})
              .get("metadata") or {})
    nt = md.get("sid_num_turns")
    nowmi = md.get("sid_num_turns_without_model_interaction")
    out["termination"] = {"subtype": md.get("sid_subtype"), "num_turns": nt,
                          "num_turns_without_model_interaction": nowmi}
    if md.get("sid_subtype") == "error_max_turns":
        if isinstance(nt, int) and isinstance(nowmi, int) and nt + nowmi == max_turns + 1:
            out["termination"]["attribution"] = (
                f"轮次真的用尽（{nt} + {nowmi} = max_turns {max_turns} + 1，"
                "每轮都换来了模型交互）⇒ 抬 --max-turns 才有意义")
        elif isinstance(nowmi, int) and nowmi > 0:
            out["termination"]["attribution"] = (
                f"{nowmi} 格轮次没换来模型交互（超时/watchdog 杀在零产出上）"
                "⇒ 是网络/重试问题，抬轮数治不了")
        else:
            out["termination"]["attribution"] = "⚠️ 判据字段缺失，无法归因（先查 metadata 回填路径）"

    # ── ①b missing 的两种成因必须分开（2026-09-13 实测纠正）──
    #
    # 🔴 「f2p 文件在 XML 里没有节点」有**两个完全相反**的成因：
    #
    #   (a) 判分链路自己的问题（verifier 没跑、XML 没生成…）⇒ 真的不能算模型答错
    #   (b) **测试跑了，但 import 的 src 符号不存在** —— bun 报
    #       `Cannot find module '../../src/x.ts'` 或
    #       `SyntaxError: Export named 'foo' not found`，
    #       整份文件加载失败 ⇒ XML 里自然没有节点。
    #       而那些 src 文件/导出**正是 gold patch 创建的**（已逐条核对 T0031/T0039/T0064）
    #       ⇒ **模型没写出来**，这是**真 0**。
    #
    # ⚠️ 最初只看 `missing` 就判 `grader_incomplete`，把 (b) 误判成 (a) ——
    # 方向恰好**偏袒模型**（把「模型没做到」记成「判分有问题」），
    # 3/7 条被误判。判据是 f2p 日志里的加载失败签名。
    log = trial_dir / "verifier/f2p.log"
    load_fail = 0
    if log.exists():
        txt = log.read_text(encoding="utf-8", errors="ignore")
        load_fail = len(_LOAD_FAIL.findall(txt))
        out["f2p_ran_line"] = (_RAN_LINE.findall(txt) or [None])[-1]
    out["n_f2p_load_failures"] = load_fail

    # ── 合判 ──
    fd = out["f2p_detail"]
    judged_all = (fd["n_missing"] == 0 and fd["n_no_tests"] == 0
                  and fd["n_seen"] == fd["n_required"] and out.get("error_code") == 0)
    if out.get("reward") == 1.0:
        out["verdict"], out["why"] = "solved", "解出"
    elif _is_upstream_failure(md):
        # 🔴 上游 LLM 断连 ⇒ **假 0 分**，这一条根本没跑完，⛔ 不是任何能力信号。
        #
        # 2026-09-14 实测（T0022）：61 轮 / 73 分钟时上游断连，agent 以
        # `error_during_execution` 收尾，verifier 照常打分 ⇒ reward=0.0。
        # 最初这里把它判成 `true_zero_missing_symbol`（真 0），而报告侧
        # `Trial.upstream_failure` 已按 infra 排除 ⇒ **两套口径打架**：
        # 归因表说「模型没写出符号」，主表说「仪器故障」，读者无从判断哪个真。
        #
        # ⚠️ 这个分支必须排在 `load_fail` 前面：断连的题往往也有加载失败
        # （模型没来得及写完），照顺序会先命中那条，把假 0 说成真 0。
        out["verdict"] = "infra_upstream_disconnect"
        out["why"] = ("🔴 **假 0 分**：上游 LLM 链路断开（"
                      f"{(md.get('sid_errors') or ['?'])[0][:80]}…）⇒ "
                      f"agent 在第 {md.get('sid_num_turns')} 轮被打断、题**没跑完**，"
                      "而 verifier 照常打了分 ⇒ ⛔ 不计入分母，不是能力信号，需重跑")
    elif not _agent_started(trial_dir):
        # 🔴 **假 0 分**：agent 进程根本没启动起来（题面超 MAX_ARG_STRLEN，exec 被拒）。
        #
        # ⚠️ 这个分支必须排在 `load_fail` 前面 —— 没启动的题 f2p 必然有加载失败
        # （源码一个字没改，import 的符号当然不存在），照顺序会先命中那条，
        # 把一次工程故障说成「模型没写出 gold patch 的符号」（= 能力信号）。
        # 与 `infra_upstream_disconnect` 同理：先排除没跑完的，再谈能力。
        out["verdict"] = "infra_agent_not_launched"
        out["why"] = ("🔴 **假 0 分**：agent 进程**一次都没启动**"
                      "（`agent/sid-code.jsonl` 缺失或为空）⇒ 题**根本没跑**，"
                      "而 verifier 照常打了分 ⇒ ⛔ 不计入分母，不是能力信号。"
                      "本批实测成因：题面超 Linux `MAX_ARG_STRLEN`（131,072 B），"
                      "`bash -c` 拒绝 exec（`Argument list too long`，退出码 255）")
    elif not judged_all and load_fail:
        # (b)：测试跑到了，是模型没写出被 import 的符号
        out["verdict"] = "true_zero_missing_symbol"
        out["why"] = (f"真 0：测试跑起来了（{out.get('f2p_ran_line') or '见 f2p.log'}）但有 "
                      f"{load_fail} 处加载失败（`Cannot find module` / `Export named ... not found`）"
                      "—— 被 import 的 src 符号**正是 gold patch 创建的**，模型没写出来 ⇒ "
                      "⛔ 这**不是**判分缺陷")
    elif not judged_all:
        out["verdict"] = "grader_incomplete"
        out["why"] = (f"判分侧没看全 f2p（seen {fd['n_seen']}/{fd['n_required']}，"
                      f"missing {fd['n_missing']}，no_tests {fd['n_no_tests']}，"
                      f"error_code {out.get('error_code')}）**且 f2p 日志无加载失败签名** ⇒ "
                      "⛔ 这一条**不能**读作「模型答错」")
    elif out["n_write_tool_calls"] == 0:
        out["verdict"] = "true_zero_no_attempt"
        out["why"] = ("真 0，但模型**一次都没改文件**（写文件工具 0 次）⇒ "
                      "它没提交解法，不是解法不对")
    else:
        out["verdict"] = "true_zero_wrong_fix"
        out["why"] = (f"真 0：测试跑起来了（{fd['n_failed']} 个 fail）且模型改过文件"
                      f"（{out['n_write_tool_calls']} 次）⇒ 改动不对")
    return out


def _guard_text(v: Counter, n_done: int) -> str:
    """结论护栏文案 —— **按实际判定生成，不写死**。

    每一句都必须对应真实存在的条数：说「模型没提交解法」的前提是
    `true_zero_no_attempt > 0`；说「不能读作答错」的前提是
    `grader_incomplete > 0`。否则报告会在数据变化后继续讲上一轮的故事。
    """
    n_wrong = v.get("true_zero_wrong_fix", 0)
    n_no_attempt = v.get("true_zero_no_attempt", 0)
    n_missing_sym = v.get("true_zero_missing_symbol", 0)
    n_grader = v.get("grader_incomplete", 0)
    n_solved = v.get("solved", 0)
    # 🔴 两类**假 0**（题没跑完 / 没跑起来）必须在句子里出现，否则条数加不平：
    # 读者拿「解出 + 改错 + 未提交 + 缺符号 + 判分未看全」去凑 n_done 会差几条，
    # 而差掉的恰好是不该算进能力分母的那几条。
    n_disc = v.get("infra_upstream_disconnect", 0)
    n_nolaunch = v.get("infra_agent_not_launched", 0)

    bits = [f"已判 {n_done} 条：解出 {n_solved}、改了但改错 {n_wrong}、"
            f"未提交解法 {n_no_attempt}、缺 src 符号 {n_missing_sym}、判分未看全 {n_grader}"
            + (f"、上游断连 {n_disc}" if n_disc else "")
            + (f"、agent 未启动 {n_nolaunch}" if n_nolaunch else "")
            + "。"]
    if n_nolaunch:
        bits.append(f"🔴 那 {n_nolaunch} 条 `infra_agent_not_launched` 是**假 0**："
                    "agent 进程一次都没启动（题面超 `MAX_ARG_STRLEN`，exec 被拒），"
                    "verifier 却照常打了分 ⇒ ⛔ 已排除出分母，**不是**能力信号。")
    if n_grader:
        bits.append(f"⛔ 那 {n_grader} 条 `grader_incomplete` **不能**读作模型答错"
                    "（判分侧没拿全测试节点，且 f2p 日志无加载失败签名）。")
    if n_missing_sym:
        bits.append(f"那 {n_missing_sym} 条 `true_zero_missing_symbol` 是**真 0**："
                    "测试跑到了，但模型没写出被 import 的 src 符号"
                    "（那些正是 gold patch 创建的）⇒ ⛔ **不是**判分缺陷。")
    if n_no_attempt:
        bits.append(f"⛔ 那 {n_no_attempt} 条 `true_zero_no_attempt` 是**模型没提交解法**，"
                    "不是解法不对 —— 它一次都没改文件。")
    # 🔴 能力信号 = `true_zero_wrong_fix` + `true_zero_missing_symbol`，⛔ 不止前者。
    #
    # 2026-09-14 抓到**本段自相矛盾**：上面刚说那 N 条 `true_zero_missing_symbol`
    # 是「**真 0** ⇒ ⛔ 不是判分缺陷」（即模型没做到），紧接着却说
    # 「✅ **只有**那 M 条 `true_zero_wrong_fix` 是能力信号」——
    # 「只有」把自己刚认定的真 0 又排除在能力信号之外。
    # 那个「只有」是为 baseline 批写死的（那批 missing_symbol 为 0，措辞才成立）。
    #
    # 这段会被**逐字嵌进报告 §10**，且 §5 的 error_code 注释也引用它的判定
    # ⇒ 一处措辞错会同时污染三节。
    n_cap = n_wrong + n_missing_sym
    if n_cap:
        parts = []
        if n_wrong:
            parts.append(f"{n_wrong} 条 `true_zero_wrong_fix`（改了但改错）")
        if n_missing_sym:
            parts.append(f"{n_missing_sym} 条 `true_zero_missing_symbol`"
                         "（没写出 gold patch 创建的符号）")
        bits.append(f"✅ 能力信号共 {n_cap} 条：" + " + ".join(parts) + "。"
                    + ("⛔ 注意**不含** `true_zero_no_attempt`（一次都没改文件，"
                       "那是没提交解法，不是解法不对）。" if n_no_attempt else ""))
    else:
        bits.append("🔴 **`true_zero_wrong_fix` 与 `true_zero_missing_symbol` 均为 0"
                    " ⇒ 这批里没有任何一条能作为「模型做了但没做到」的能力证据。**")
    return "".join(bits)


def control_group(done: list[dict]) -> dict:
    """🔴 **对照组：题面不点名 `docs/` 的那 4 条**（T0011/T0012/T0018/T0028）。

    这是能**反证本脚本归因**的天然对照。归因说「0 分的成因是题面点名容器里
    不存在的文档，模型把轮次花在找文档上」，那么题面**没有**这个缺陷的 4 条
    就该表现不同 —— 至少不该是同一条「零改动 + 轮次耗尽」的路径。

    预注册的判读（2026-09-13 写下时这 4 条**都还没跑**，不是事后挑的）：

      - 对照组出现 `true_zero_wrong_fix` 或 `solved`
        ⇒ 归因**成立**：题面缺陷确实是主因，去掉它模型就能进到「改代码」阶段
      - 对照组也全是 `true_zero_no_attempt` + `error_max_turns`
        ⇒ 归因**不完整**：40 轮上限本身就不够，或另有系统性障碍
           （那时 §9 的措辞必须改，⛔ 不许只留「题面缺陷」这一个成因）

    ⚠️ n=4 < 5，**只报绝对条数不报比例**（同交接 2b 的小格纪律）。
    """
    # 🔴 只在**存活 39 条**里找，⛔ 不许扫 MVP_TASKS 下的全部 65 个目录 ——
    # 那会把门禁淘汰的（T0001/T0005/T0021…）也算进对照组，实测从 4 条虚报成 13 条。
    # 这就是交接 1b 那条分母纪律，换个地方又能踩一次（2026-09-13 实测）。
    surv = set(json.loads((RECHECK / "survivors.json").read_text(encoding="utf-8"))["survivors"])
    ctrl_ids = []
    for tid in sorted(surv):
        ins = c.MVP_TASKS / tid / "instruction.md"
        if ins.exists() and "docs/" not in ins.read_text(encoding="utf-8"):
            ctrl_ids.append(tid)
    rows = [r for r in done if r["task"] in set(ctrl_ids)]
    v = Counter(r["verdict"] for r in rows)
    n_attempted = sum(1 for r in rows if r.get("n_write_tool_calls", 0) > 0)

    # 🔴 `supports` 是给下游的**结构化判据**，⛔ 下游不许再靠子串匹配
    # （报告侧原来用 `"成立" in reading` ⇒ 新增的否定句「不许用部分样本宣布归因
    # **成立**」也含这两个字，把「暂缓」读成了「支持」。2026-09-14 实测撞到。）
    supports = False
    if not rows:
        read = "⏳ 对照组还没跑到 —— 跑到后本节自动给出判读"
    elif len(rows) < len(ctrl_ids):
        # 🔴 **跑齐才判读**，⛔ 不许用部分样本宣布归因成立。
        #
        # 2026-09-14 抓到：跑到 1/4 条时就输出「✅ 归因成立」，
        # 而这个字符串是报告里 `ctrl_supports` 的判据 ⇒ **一条样本解锁了最强结论**
        # （§10 那句「本批的 pass@1 不是模型解不动，而是题面缺陷叠加轮次上限」）。
        # 对照组的全部价值在于「能推翻归因」，用它的第一条就宣布支持，
        # 等于把反证做成了单向确认 —— 剩下 3 条无论什么结果都不会再改变结论。
        #
        # ⚠️ 且 n=4 < 5，本函数 docstring 的预注册纪律写死「只报绝对条数不报比例」。
        read = (f"⏳ 对照组只跑了 {len(rows)}/{len(ctrl_ids)} 条 —— **判读暂缓**。"
                f"已跑的形态：{dict(v)}（wrong_fix 进入了改代码阶段 / no_attempt 未提交解法）。"
                "⛔ 不许用部分样本宣布归因成立：对照组的价值在于**能推翻**归因，"
                "拿第一条就确认等于把反证做成单向确认。")
    elif v.get("true_zero_wrong_fix", 0) or v.get("solved", 0):
        supports = True
        read = ("✅ 归因**成立**：对照组里有条目进入了「改代码」阶段"
                f"（wrong_fix {v.get('true_zero_wrong_fix', 0)} / solved {v.get('solved', 0)}）"
                " ⇒ 题面缺陷（点名容器内不存在的文档）确实压着分数")
    elif n_attempted == 0 and all(
            (r.get("termination") or {}).get("subtype") == "error_max_turns" for r in rows):
        read = ("🔴 归因**不完整**：对照组也全是「零改动 + 轮次耗尽」 ⇒ "
                "40 轮上限本身不够用，或另有系统性障碍。"
                "⛔ §9 不许只留「题面缺陷」一个成因")
    else:
        read = "⚠️ 混合形态，需人工看逐条"

    return {
        "definition": "题面不含 `docs/` 引用的存活 task（天然对照组）",
        # 🔴 报告侧必须读这个字段判断「对照组是否支持归因」，⛔ 不许 grep `reading`
        "supports": supports,
        "control_tasks": ctrl_ids,
        "n_control": len(ctrl_ids),
        "n_control_done": len(rows),
        "verdicts": dict(v),
        "n_with_write_calls": n_attempted,
        "prereg_note": ("预注册：写下判读时这 4 条都还没跑（2026-09-13），"
                        "不是事后挑的。n=4 < 5 ⇒ 只报绝对条数不报比例"),
        "reading": read,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="只打印 JSON，不打人读表格")
    ap.add_argument("--max-turns", type=int, default=40,
                    help="agent 的 --max-turns（sid_code_agent 的 CLI_FLAGS 默认 40）。"
                         "⚠️ 整改后那批显式传了 120，判读时必须跟着传 --max-turns 120，"
                         "否则「撞上限」判据会用错的阈值比对")
    ap.add_argument("--runs", default="baseline", metavar="DIR",
                    help="取数源目录名（reports/ 下）。默认 baseline；整改后那批传 t8-rerun。"
                         "🔴 必须与 t7-report.py --runs 取同一个值")
    args = ap.parse_args()

    if args.runs != "baseline":
        _retarget(args.runs)

    run = lib.latest_run(RUNS)
    if run is None:
        raise SystemExit(f"{RUNS} 下没有 run 目录 —— 先跑 scripts/mvp/t8-rerun.py（或 t7-baseline.py）")

    grade_groups = json.loads((RECHECK / "t7-grade-groups.json").read_text(encoding="utf-8"))
    grade = {t: g for g, ts in grade_groups.items() for t in ts}

    # 🔴 跨所有 run 目录扫 —— 续跑（`t8-rerun.py --resume`）会新建 run 目录，
    # 只扫最后那个会漏掉第一轮的 trial，而归因表看着完整（只是条数少了）。
    # 同一 task 出现在多个目录时取**最新**那个（续跑结果比被中断的旧结果可信）。
    trial_dirs: dict[str, Path] = {}
    for r in sorted(p for p in RUNS.iterdir() if p.is_dir() and p.name[:2] == "20"):
        for d in sorted(r.glob("T0*/")):
            if d.is_dir():
                trial_dirs[d.name.split("__")[0]] = d
    rows = [diagnose_one(d, args.max_turns) for _, d in sorted(trial_dirs.items())]
    done = [r for r in rows if r["verdict"] != "running"]
    for r in done:
        r["grade"] = grade.get(r["task"])
        ins = c.MVP_TASKS / r["task"] / "instruction.md"
        r["instruction_names_docs"] = ("docs/" in ins.read_text(encoding="utf-8")) if ins.exists() else None

    control = control_group(done)
    verdicts = Counter(r["verdict"] for r in done)
    n_bash = sum(r.get("n_bash", 0) for r in done)
    n_hunt = sum(r.get("n_bash_hunting_doc", 0) for r in done)
    summary = {
        # ⚠️ 归因本身**跨所有 run 目录**扫（见上面 trial_dirs 那段），
        # 这里的 run_dir 只是**最新**那个 ⇒ 必须同时记 run_dirs，
        # 否则补跑后读者会以为归因只覆盖了一个目录（同 t8-rerun.summarize 的处理）。
        "run_dir": _rel(run),
        "run_dirs": [r.name for r in sorted(
            q for q in RUNS.iterdir() if q.is_dir() and q.name[:2] == "20")],
        "max_turns": args.max_turns,
        "n_diagnosed": len(done),
        "verdicts": dict(verdicts),
        "n_write_tool_calls_total": sum(r.get("n_write_tool_calls", 0) for r in done),
        "bash_hunting_doc": {"n_hunting": n_hunt, "n_bash": n_bash,
                             "share": round(n_hunt / n_bash, 4) if n_bash else None,
                             "note": "近似指标（find/ls 且提到 docs 或带中文名），"
                                     "用于量级说明，报告里须写「约」"},
        "termination_subtypes": dict(Counter(
            (r.get("termination") or {}).get("subtype") for r in done)),
        # ⛔ 这段话**必须按实际判定生成**，不能写死。
        # 2026-09-13 冒烟抓到：固定文案在「9 条解出、终止类型含 success」时还在说
        # 「本批的成因是题面点名不存在的 docs/ + 40 轮上限」—— 数据变了，结论没变，
        # 那就是报告在撒谎。同一类形态与「没跑的题算成答错」一样：输出看着完整。
        "conclusion_guard": _guard_text(verdicts, len(done)),
        "control_group": control,
        "trials": done,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        return 0

    print(f"真 0 / 假 0 归因（{len(done)} 条已判，max_turns={args.max_turns}）\n")
    print(f"{'task':7s} {'grade':5s} {'判定':22s} {'写文件':>5s} {'bash':>5s} {'找文档':>6s} 终止")
    for r in done:
        term = (r.get("termination") or {}).get("subtype") or "-"
        print(f"{r['task']:7s} {str(r.get('grade')):5s} {r['verdict']:22s} "
              f"{r.get('n_write_tool_calls', 0):5d} {r.get('n_bash', 0):5d} "
              f"{r.get('n_bash_hunting_doc', 0):6d} {term}")
    print(f"\n判定汇总：{dict(verdicts)}")
    print(f"写文件工具调用合计：{summary['n_write_tool_calls_total']} 次")
    if n_bash:
        print(f"bash 里约 {n_hunt}/{n_bash}（{n_hunt / n_bash:.0%}）花在找那份不存在的文档上")
    print(f"终止类型：{summary['termination_subtypes']}")
    print(f"\n对照组（题面**不**点名 docs/，{control['n_control']} 条，"
          f"已跑 {control['n_control_done']}）：{control['control_tasks']}")
    print(f"  {control['reading']}")
    for r in done:
        att = (r.get("termination") or {}).get("attribution")
        if att:
            print(f"  {r['task']}: {att}")
            break
    print(f"\n{summary['conclusion_guard']}")
    print(f"\n已写 {_rel(OUT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
