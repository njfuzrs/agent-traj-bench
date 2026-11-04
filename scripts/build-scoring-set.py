#!/usr/bin/env python3
"""生成 v0.2.1 计分集 `meta/scoring-set.json`（T05，按 T00 裁决②③）。

## 为什么是新文件，而不是改 `survivors.json` / `meta.json`

  - `reports/t6-recheck/survivors.json` 是 **37.8% 那批的分母**（T6 人工过目后的存活集）。
    改它会让 `t7-report.py --runs t8-rerun --card` 不再能复现已发布的 card（T01 刚修好的那条）。
    ⇒ 交付集仍是 39 条；计分集是**另一个**、更窄的集合，二者并存。
  - `meta.json` 的 `category` 是上游会话分类器（`pipeline/s1_s3/labeler.py`）的原始标签，
    `t3` / `t9` / pipeline 都在读。缺陷 8 指出它的语义在反解成 task 后翻转了
    （`test_authoring` 21 条里没有一条要 agent 写测试），但**标签本身是一份 provenance**，
    ⛔ 不覆盖。本文件为每题另记一个 `task_kind`，从 gold patch **实算**：
    gold patch 改没改测试文件。

## 处置清单是人工裁决，不是算出来的

`DECISIONS` 逐条对应 T00 裁决②③（CI/CD 方案 §6.6），每条带一句理由。
⛔ 不许把它改成关键词扫描：缺陷 8 的关键词扫描有误报（T0014 / T0055 的原句是
「按文档执行代码修复」，「排查」只出现在文档标题里），逐条读过原句才定的。

用法：`python3 scripts/build-scoring-set.py [--check]`
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

OUT = c.MVP_META / "scoring-set.json"
SURVIVORS = c.MVP_REPORTS / "t6-recheck" / "survivors.json"
RULING = "CI/CD 方案 §6.6 T00 裁决（2026-11-04）"

#: group → {task: 理由}。不在表里的存活题全部进 `scored`。
DECISIONS: dict[str, dict[str, str]] = {
    # 裁决②：产物是一份「哪些值得做 / 是否落地」的报告，gold patch 是当时会话的一个选择，不是唯一解
    "audit": {
        "T0026": "二次评审「方案中哪些值得做」，要的是判断清单",
        "T0034": "检查方案需求是否全部落地，要的是核对结论",
        "T0052": "检查文档提到的问题是否落地并汇总结果",
        "T0056": "检查两份方案的落地情况并汇总结果",
        "T0065": "检查方案的问题与 todo 是否落地并汇总结果",
    },
    # 裁决②：原句依赖题面之外的会话上下文，不自包含
    "excluded_context": {
        "T0012": "原句指向「你刚刚修改的代码」「你的任务」，依赖题面之外的会话上下文",
    },
    # 裁决③：题面装不进命令行，换模型必复现的假 0
    "excluded_infra": {
        "T0009": "eval 题面剥掉代码块后仍 >120KB，逼近 MAX_ARG_STRLEN（131072）；投递方式另立待办",
    },
}
#: 裁决②里关键词扫描命中、但逐条读过后**保留计分**的题。只作记录，便于复核。
KEPT_AFTER_REVIEW = {
    "T0014": "关键词误报：原句是「按照文档来执行代码修复」",
    "T0055": "关键词误报：原句是「按照文档执行代码修复」",
    "T0007": "bug 报告型：给了症状，「做完」= bug 不再出现",
    "T0011": "bug 报告型：给了症状，「做完」= bug 不再出现",
    "T0063": "bug 报告型：给了症状，「做完」= bug 不再出现",
}

_DIFF_FILE = re.compile(r"^diff --git a/(\S+)", re.M)


def task_kind(task: str) -> str:
    """从 gold patch 实算：改了测试文件 ⇒ `test_change`，否则 `source_change`。"""
    gp = c.MVP_TASKS / task / "solution" / "gold_patch.diff"
    files = _DIFF_FILE.findall(gp.read_text(encoding="utf-8", errors="replace"))
    return "test_change" if any(".test." in f or "/tests/" in f for f in files) else "source_change"


def build() -> dict:
    surv = sorted(json.loads(SURVIVORS.read_text(encoding="utf-8"))["survivors"])
    decided = {t: g for g, items in DECISIONS.items() for t in items}
    unknown = sorted(set(decided) - set(surv)) + sorted(set(KEPT_AFTER_REVIEW) - set(surv))
    if unknown:
        raise SystemExit(f"⛔ 处置清单里有不在存活集的题：{unknown}")
    if set(decided) & set(KEPT_AFTER_REVIEW):
        raise SystemExit("⛔ 同一题既被移出又被保留")

    groups: dict[str, list[str]] = {"scored": [t for t in surv if t not in decided]}
    for g in DECISIONS:
        groups[g] = sorted(t for t, gg in decided.items() if gg == g)

    kinds: dict[str, str] = {}
    labels: dict[str, str] = {}
    for t in surv:
        kinds[t] = task_kind(t)
        labels[t] = json.loads((c.MVP_TASKS / t / "meta.json").read_text(encoding="utf-8")).get("category")

    def tally(d: dict[str, str], ts: list[str]) -> dict[str, int]:
        out: dict[str, int] = {}
        for t in ts:
            out[d[t]] = out.get(d[t], 0) + 1
        return dict(sorted(out.items()))

    return {
        "_note": (
            "v0.2.1 计分集。由 scripts/build-scoring-set.py 生成，⛔ 不要手改。"
            "交付集仍是 survivors.json 的 39 条；scored 之外的题留在交付集里、不计分。"
            "task_kind 从 gold patch 实算；upstream_category 是上游会话分类器的原始标签，"
            "其中 test_authoring 的语义在反解成 task 后已翻转（测试是判据，不是产物），仅作 provenance。"
        ),
        "version": "v0.2.1",
        "ruling": RULING,
        "n_delivered": len(surv),
        "n_scored": len(groups["scored"]),
        "groups": groups,
        "reasons": {g: dict(sorted(items.items())) for g, items in DECISIONS.items()},
        "kept_after_review": dict(sorted(KEPT_AFTER_REVIEW.items())),
        "task_kind": {"scored": tally(kinds, groups["scored"]), "delivered": tally(kinds, surv)},
        "upstream_category": {"scored": tally(labels, groups["scored"]), "delivered": tally(labels, surv)},
        "per_task": {t: {"group": next(g for g, ts in groups.items() if t in ts),
                         "task_kind": kinds[t], "upstream_category": labels[t]} for t in surv},
    }


def render(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成 meta/scoring-set.json")
    ap.add_argument("--check", action="store_true", help="只比对不写，不一致退出 1")
    args = ap.parse_args(argv)
    want = render(build())
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != want:
            print(f"::error::{OUT.name} 与现算结果不一致 —— 跑 scripts/build-scoring-set.py 重新生成，⛔ 不要手改")
            return 1
        print(f"✅ {OUT.name} 与现算结果一致")
        return 0
    OUT.write_text(want, encoding="utf-8")
    doc = json.loads(want)
    print(f"写出 {OUT.name}：交付 {doc['n_delivered']}，计分 {doc['n_scored']}；"
          f"task_kind（计分集）{doc['task_kind']['scored']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
