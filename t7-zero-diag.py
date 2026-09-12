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

RUNS = c.MVP_REPORTS / "baseline"
RECHECK = c.MVP_REPORTS / "t6-recheck"
OUT = RUNS / "zero-diag.json"

#: sid-code 侧的写文件工具名。🔴 **全小写** —— 见模块 docstring ② 的实测。
WRITE_TOOLS = {"write", "edit", "multi_edit", "multiedit", "str_replace",
               "apply_patch", "notebook_edit"}

#: 「在容器里找那份不存在的文档」的动作特征：find/ls 且提到 docs 或带中文文件名。
#: ⚠️ 这是个**近似**指标，用来量级说明而非精确计数，报告里要标明「约」。
_FIND_DOC = re.compile(r"\b(find|ls)\b")
_CJK = re.compile(r"[一-鿿]")


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

    # ── 合判 ──
    fd = out["f2p_detail"]
    judged_all = (fd["n_missing"] == 0 and fd["n_no_tests"] == 0
                  and fd["n_seen"] == fd["n_required"] and out.get("error_code") == 0)
    if out.get("reward") == 1.0:
        out["verdict"], out["why"] = "solved", "解出"
    elif not judged_all:
        out["verdict"] = "grader_incomplete"
        out["why"] = (f"判分侧没看全 f2p（seen {fd['n_seen']}/{fd['n_required']}，"
                      f"missing {fd['n_missing']}，no_tests {fd['n_no_tests']}，"
                      f"error_code {out.get('error_code')}）⇒ ⛔ 这一条**不能**读作「模型答错」")
    elif out["n_write_tool_calls"] == 0:
        out["verdict"] = "true_zero_no_attempt"
        out["why"] = ("真 0，但模型**一次都没改文件**（写文件工具 0 次）⇒ "
                      "它没提交解法，不是解法不对")
    else:
        out["verdict"] = "true_zero_wrong_fix"
        out["why"] = (f"真 0：测试跑起来了（{fd['n_failed']} 个 fail）且模型改过文件"
                      f"（{out['n_write_tool_calls']} 次）⇒ 改动不对")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="只打印 JSON，不打人读表格")
    ap.add_argument("--max-turns", type=int, default=40,
                    help="agent 的 --max-turns（sid_code_agent 的 CLI_FLAGS 默认 40）")
    args = ap.parse_args()

    run = lib.latest_run(RUNS)
    if run is None:
        raise SystemExit(f"{RUNS} 下没有 run 目录 —— 先跑 scripts/mvp/t7-baseline.py")

    grade_groups = json.loads((RECHECK / "t7-grade-groups.json").read_text(encoding="utf-8"))
    grade = {t: g for g, ts in grade_groups.items() for t in ts}

    rows = [diagnose_one(d, args.max_turns) for d in sorted(run.glob("T0*/")) if d.is_dir()]
    done = [r for r in rows if r["verdict"] != "running"]
    for r in done:
        r["grade"] = grade.get(r["task"])
        ins = c.MVP_TASKS / r["task"] / "instruction.md"
        r["instruction_names_docs"] = ("docs/" in ins.read_text(encoding="utf-8")) if ins.exists() else None

    verdicts = Counter(r["verdict"] for r in done)
    n_bash = sum(r.get("n_bash", 0) for r in done)
    n_hunt = sum(r.get("n_bash_hunting_doc", 0) for r in done)
    summary = {
        "run_dir": str(run.relative_to(c.REPO_ROOT)) if run.is_relative_to(c.REPO_ROOT) else str(run),
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
        "conclusion_guard": (
            "⛔ pass@1=0 不等于「模型能力差」。verdict=grader_incomplete 的条数**不能**"
            "读作模型答错；verdict=true_zero_no_attempt 说明模型没提交解法（本批的成因是"
            "题面点名容器里不存在的 docs/ 文档 + 40 轮隐式上限），也不能读作「解法不对」。"),
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
    for r in done:
        att = (r.get("termination") or {}).get("attribution")
        if att:
            print(f"  {r['task']}: {att}")
            break
    print(f"\n{summary['conclusion_guard']}")
    print(f"\n已写 {OUT.relative_to(c.REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
