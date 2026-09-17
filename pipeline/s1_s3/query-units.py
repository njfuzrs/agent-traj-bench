#!/usr/bin/env python3
"""query-units.py — 按源信息与分类筛选查看单元（用户 2026-09-05 提出的需求）

Phase 1 的产物是 7094 行 jsonl。没有检索入口的话，「按 claude code / codex 分开看」
「只看某个模型的 bug_fix」这类问题只能每次现写 python。这个脚本就是那个入口。

## 可筛的维度

源信息（S0 一路带下来，见 common.py）
  --agent-source  采集通道：claude_code / codex / sid_code / short_id
  --vendor        厂商：anthropic / deepseek / openai / zhipu / alibaba / …
  --model         模型名，子串匹配（如 --model opus-5）
  --repo          仓库，子串匹配（如 --repo sid-code）
  --resolution    仓库锚定置信度：direct / voted / inferred / conflict / unresolved

分类与标注
  --category      bug_fix / feature_impl / refactor / test_authoring /
                  doc_authoring / code_comprehension / env_ops / unclassified
  --difficulty    easy / medium / hard / unrated
  --tag           标签，可重复（--tag typescript --tag error_recovery）
  --confidence    分类置信度：high / medium / low

质量与来源过滤
  --boundary-confidence  切分边界置信度：high / medium / low
  --min-edit-ops / --min-error-ops / --min-steps
  --exclude-review       排除 needs_review（含 high 级敏感命中）的单元
  --exclude-conflict     排除仓库锚定为 conflict 的单元（§9.4 坑②）

输出
  默认打印分组统计；--list 列出单元；--json 输出完整记录；--out 写文件

用法：
  # 各通道 × 类别的交叉分布
  python3 s1_s3/query-units.py --group agent_source,category

  # 只看 codex 通道里 deepseek 的 bug_fix，且切分边界可信
  python3 s1_s3/query-units.py --agent-source codex --vendor deepseek \\
      --category bug_fix --boundary-confidence high --list

  # 导出可进 Phase 2 的高质量子集
  python3 s1_s3/query-units.py --boundary-confidence high \\
      --confidence high --exclude-review --exclude-conflict \\
      --out data/bench-staging/phase1/meta/candidates-high.jsonl
"""

import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

LABELED = os.path.join(common.P1_META, "labeled-v2.jsonl")

GROUPABLE = (
    "agent_source", "vendor", "model", "repo", "repo_resolution",
    "category", "category_confidence", "difficulty", "boundary_confidence",
    "ended_by", "boundary_reason", "provenance", "batch_version",
)


def matches(rec: dict, args) -> bool:
    if args.agent_source and rec.get("agent_source") != args.agent_source:
        return False
    if args.vendor and rec.get("vendor") != args.vendor:
        return False
    if args.model and args.model.lower() not in (rec.get("model") or "").lower():
        return False
    if args.repo and args.repo.lower() not in (rec.get("repo") or "").lower():
        return False
    if args.resolution and rec.get("repo_resolution") != args.resolution:
        return False
    if args.category and rec.get("category") != args.category:
        return False
    if args.difficulty and rec.get("difficulty") != args.difficulty:
        return False
    if args.confidence and rec.get("category_confidence") != args.confidence:
        return False
    if args.boundary_confidence and \
            rec.get("boundary_confidence") != args.boundary_confidence:
        return False
    if args.tag:
        tags = set(rec.get("tags") or [])
        if not set(args.tag) <= tags:
            return False
    if args.min_edit_ops and (rec.get("edit_ops") or 0) < args.min_edit_ops:
        return False
    if args.min_error_ops and (rec.get("error_ops") or 0) < args.min_error_ops:
        return False
    if args.exclude_review and rec.get("needs_review"):
        return False
    if args.exclude_conflict and rec.get("repo_resolution") == "conflict":
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="按源信息与分类筛选 Phase 1 单元",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default=LABELED)
    # 源信息
    ap.add_argument("--agent-source", choices=common.AGENT_SOURCES)
    ap.add_argument("--vendor")
    ap.add_argument("--model")
    ap.add_argument("--repo")
    ap.add_argument("--resolution",
                    choices=["direct", "voted", "inferred", "conflict", "unresolved"])
    # 分类
    ap.add_argument("--category")
    ap.add_argument("--difficulty", choices=["easy", "medium", "hard", "unrated"])
    ap.add_argument("--tag", action="append")
    ap.add_argument("--confidence", choices=["high", "medium", "low"])
    ap.add_argument("--boundary-confidence", choices=["high", "medium", "low"])
    # 质量
    ap.add_argument("--min-edit-ops", type=int, default=0)
    ap.add_argument("--min-error-ops", type=int, default=0)
    ap.add_argument("--exclude-review", action="store_true")
    ap.add_argument("--exclude-conflict", action="store_true")
    # 输出
    ap.add_argument("--group", default="agent_source,category",
                    help=f"分组维度，逗号分隔。可选：{', '.join(GROUPABLE)}")
    ap.add_argument("--list", action="store_true", help="列出命中单元")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--json", action="store_true", help="输出完整 JSON 记录")
    ap.add_argument("--out", help="把命中记录写到文件（jsonl）")
    args = ap.parse_args(argv)

    if not os.path.exists(args.input):
        print(f"产物不存在：{args.input}\n  先跑 label-units.py", file=sys.stderr)
        return 1
    records = common.read_jsonl(args.input)
    hits = [r for r in records if matches(r, args)]

    print(f"命中 {len(hits)} / {len(records)} 单元"
          f"（{len(hits) / max(len(records), 1):.1%}）")
    if not hits:
        return 0

    dims = [d.strip() for d in (args.group or "").split(",") if d.strip()]
    bad = [d for d in dims if d not in GROUPABLE]
    if bad:
        print(f"不支持的分组维度：{bad}\n  可选：{', '.join(GROUPABLE)}",
              file=sys.stderr)
        return 1

    if dims:
        print(f"\n按 {' × '.join(dims)} 分组：")
        counter = collections.Counter(
            tuple(str(r.get(d)) for d in dims) for r in hits)
        for key, n in counter.most_common(30):
            print(f"  {' | '.join(key):<58} {n:>6} {n / len(hits):>6.1%}")
        if len(counter) > 30:
            print(f"  …… 另有 {len(counter) - 30} 组")

    # 客观量概览
    edits = sorted(r.get("edit_ops") or 0 for r in hits)
    errs = sum(1 for r in hits if (r.get("error_ops") or 0) >= 3)
    tests = sum(1 for r in hits if (r.get("n_test_cmds") or 0) > 0)
    anchored = sum(1 for r in hits if r.get("repo"))
    review = sum(1 for r in hits if r.get("needs_review"))
    print(f"\n客观量：edit_ops 中位 {edits[len(edits) // 2]}，"
          f"有测试命令 {tests}（{tests / len(hits):.0%}），"
          f"error_ops>=3 的 {errs}（{errs / len(hits):.0%}）")
    print(f"仓库锚定 {anchored}（{anchored / len(hits):.0%}）；"
          f"needs_review {review}")

    if args.list or args.json:
        print(f"\n前 {min(args.limit, len(hits))} 条：")
        for r in hits[:args.limit]:
            if args.json:
                print(json.dumps(r, ensure_ascii=False))
                continue
            instr = " ".join((r.get("instruction_clean") or "").split())[:88]
            print(f"  {r['unit_id']}")
            print(f"    {r.get('agent_source')} / {r.get('model')} / "
                  f"{r.get('repo')} | {r.get('category')}"
                  f"({r.get('category_confidence')}) / {r.get('difficulty')} | "
                  f"边界 {r.get('boundary_reason')}({r.get('boundary_confidence')})")
            print(f"    {instr}")

    if args.out:
        common.write_jsonl(args.out, hits)
        print(f"\n已写出 {len(hits)} 条 → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
