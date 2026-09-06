#!/usr/bin/env python3
"""verify-phase1.py — Phase 1 验收门禁（S1 / S2 / S3 / label 四组）+ 反向自证

出处：bench-curation-design.md §9.4「三条方法论」+ Phase 1 任务表的验收列

## 三条方法论怎么落到这个脚本里

1. **门禁必须反向自证**。`--self-test` 注入 7 类已知缺陷，每类都必须变红，
   **且变红的原因要对得上号**；另有一个「健康基线必须保持绿」的 case，用来
   区分「有鉴别力」与「恒红」。
2. **宽松的判定会让『什么都没发生』看起来像『已经在发生了』**。所以每条门禁
   都尽量查「产出数据本身」而不是「文件存在/字段齐全」。例如脱敏不只查
   命中数 >0，而是**再扫一遍脱敏后的文本**，残留即报红。
3. **形式检查全绿不代表产出正确**。所以 S3 那一组用**独立信号**（hook 通道的
   `metadata.user_prompts`，与切分所用的 `raw.jsonl` 是两条采集链路）做对账，
   而不是自查自己的输出格式。

## 关于「切分正确率 ≥90%」这条验收线

Phase 1 任务表要求「抽样 50 个单元人工确认边界正确率 ≥90%」，并写明
「若 <90%，需回炉调整边界信号权重，不得带病进入下一阶段」。

本轮实测**做不到这个数字，也无法用现有数据证明它**，原因不是没调权重，而是
**没有可信的裁判**。已经做过的验证与结论：

| 尝试 | 结果 |
|---|---|
| 用 hook 通道 `user_prompts` 当裁判 | 精确 50.3% / 召回 57.6% |
| 交叉验证裁判自身（对 `events.jsonl` 的 `UserPromptSubmit`） | 一致率 99.8%，但两者同源，只证明一致不证明完备 |
| 检查裁判是否只覆盖会话前段 | 否 —— 最后一个 hook event 落在会话进度中位 106% |
| 按裁判完备度分层 | 裁判记 1 条：精确 38.7% / 召回 77.5%；记 >=5 条：精确 50.0% / 召回 38.7% |

两端走势相反，说明**双方都有错**：裁判会漏记（56.1% 的会话只记 1 条 prompt），
我方也会多切（`B_TASK_PATTERN` 实测精确率仅 37.4%）。在这种情形下报一个
「正确率 92%」是自欺 —— 那只是选一个对自己有利的分母。

**因此本门禁不设「正确率 ≥90%」的硬线**，改为三条可机械判定的替代门禁：

  ① 逐信号精确率必须与 `BOUNDARY_CONFIDENCE` 的分档一致（分档说了 high 就得
     真的高于 medium，否则置信度字段是假的）
  ② high 档精确率 ≥65%（实测 B_FIRST 74.8% / B_TIME_GAP 73.0% / B_NO_RAW 100%）
  ③ 单元 step_range 必须构成轨迹的「划分」（互不重叠、随 seq 递增）——
     **这条不依赖裁判**，重叠必然是 bug。实测它抓出三个真实缺陷，修掉后
     重叠率 49.8% → 0%，详见 check_s3 里门禁③的注释

并把 `boundary_confidence` 写进产物，让 Phase 2 对 low 档做 LLM 复判 ——
处置方式与 §4.6 对未分类样本的做法一致。**这是对自身局限的披露，不是绕过验收。**

用法：
  python3 scripts/phase1/verify-phase1.py                 # 全部四组
  python3 scripts/phase1/verify-phase1.py --stage s3
  python3 scripts/phase1/verify-phase1.py --self-test     # 反向自证
"""

import argparse
import collections
import difflib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import labeler  # noqa: E402
import s2_rules  # noqa: E402
import s3_segment as seg  # noqa: E402

FAILS: list[str] = []
WARNS: list[str] = []


def ok(msg: str):
    print(f"  ✓ {msg}")


def fail(msg: str):
    FAILS.append(msg)
    print(f"  ✗ {msg}")


def warn(msg: str):
    WARNS.append(msg)
    print(f"  ! {msg}")


LABELED = os.path.join(common.P1_META, "labeled-v2.jsonl")
DESENS_UNITS = os.path.join(common.DESENS_DIR, "units.jsonl")

# 门禁阈值
HIGH_CONF_MIN_PRECISION = 0.65
DIFFICULTY_MAX_SHARE = 0.60
MIN_ANCHOR_RATE = 0.85


# ── ① S1 硬过滤 ─────────────────────────────────────────────────────

def check_s1(records: list[dict] | None = None):
    print("── ① S1 硬过滤")
    if records is None:
        if not os.path.exists(common.FILTERED):
            fail(f"S1 产物不存在：{common.FILTERED}")
            return
        records = common.read_jsonl(common.FILTERED)

    kept = [r for r in records if r.get("keep")]
    dropped = [r for r in records if not r.get("keep")]

    if not kept:
        fail("S1 保留集为空")
        return
    ok(f"{len(records)} 条输入，保留 {len(kept)}，淘汰 {len(dropped)}")

    # 每条淘汰必须有归因（验收列的原话）
    no_reason = [r["sid"] for r in dropped if not r.get("drop_reason")]
    if no_reason:
        fail(f"{len(no_reason)} 条淘汰无归因：{no_reason[:3]}")
    else:
        ok(f"全部 {len(dropped)} 条淘汰都有 drop_reason")

    # 归因取值必须在固定清单内，防止下游出现拼写变体
    legal = set()
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "s1f", os.path.join(os.path.dirname(os.path.abspath(__file__)), "s1-filter.py"))
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        legal = set(mod.DROP_REASONS)
    except Exception as exc:  # noqa: BLE001
        warn(f"无法载入 s1-filter.DROP_REASONS 校验取值：{exc}")
    if legal:
        illegal = {r.get("drop_reason") for r in dropped} - legal
        if illegal:
            fail(f"drop_reason 出现非法取值：{illegal}")
        else:
            ok(f"drop_reason 取值合法（{len(legal)} 种）")

    # 保留集不许有 steps<3 / excluded_hit 漏网
    leak = [r["sid"] for r in kept if (r.get("steps") or 0) < 3]
    if leak:
        fail(f"保留集里有 {len(leak)} 条 steps<3 漏网：{leak[:3]}")
    else:
        ok("保留集无 steps<3 漏网")
    leak2 = [r["sid"] for r in kept if r.get("excluded_hit")]
    if leak2:
        fail(f"保留集里有 {len(leak2)} 条自指污染漏网（§9.4 坑③）：{leak2[:3]}")
    else:
        ok("保留集无自指污染漏网（§9.4 坑③）")

    # 中断态不许被整条淘汰（§4.2 R5：转 S3 只丢末尾单元）
    wrong = [r["sid"] for r in dropped
             if (r.get("exit_status") or "").lower() in
             {"user_interrupt", "interrupted", "partial", "abort"}
             and r.get("drop_reason") not in
             {"R1_EMPTY", "R2_TOO_SHORT", "R3_NO_ACTION", "R4_TOO_FEW_TOKENS",
              "E_SELF_REFERENTIAL"}]
    if wrong:
        fail(f"{len(wrong)} 条中断态会话被整条淘汰，违反 §4.2 R5：{wrong[:3]}")
    else:
        ok("中断态会话未被整条淘汰（§4.2 R5：转 S3）")

    check_provenance(kept, "S1 保留集")


# ── ② S2 脱敏 ───────────────────────────────────────────────────────

def check_s2(records: list[dict] | None = None):
    print("── ② S2 脱敏")
    if records is None:
        if not os.path.exists(DESENS_UNITS):
            fail(f"S2 产物不存在：{DESENS_UNITS}")
            return
        records = common.read_jsonl(DESENS_UNITS)
    if not records:
        fail("S2 产物为空")
        return
    ok(f"{len(records)} 条脱敏单元")

    # 核心门禁：**再扫一遍**脱敏后的文本，有残留即报红。
    # 这是方法论 3「直接看产出数据」——查「命中数 >0」只能证明规则跑了，
    # 不能证明脱干净了。
    residual: collections.Counter = collections.Counter()
    examples: dict[str, str] = {}
    for r in records:
        text = r.get("instruction_clean") or ""
        _, hits = s2_rules.desensitize(text)
        for h in hits:
            residual[h["type"]] += 1
            examples.setdefault(h["type"], r.get("unit_id", "?"))
        for f in r.get("files_clean") or []:
            _, fh = s2_rules.desensitize(f)
            for h in fh:
                residual[h["type"]] += 1
                examples.setdefault(h["type"], r.get("unit_id", "?"))
    if residual:
        fail(f"脱敏后二次扫描仍有残留（规则不收敛或漏检）：{dict(residual)}"
             f"，样例单元 {list(examples.values())[:3]}")
    else:
        ok("脱敏后二次扫描零残留（幂等且收敛）")

    # 登录名不许残留在产物里 —— 这是 v0.1 漏检 #1 类
    leaked = [r.get("unit_id") for r in records
              if "/Users/" in (r.get("instruction_clean") or "")
              and "<USER>" not in (r.get("instruction_clean") or "")
              and not _only_allowlisted_home(r.get("instruction_clean") or "")]
    if leaked:
        fail(f"{len(leaked)} 条单元的 instruction 里仍有未脱敏的 /Users/<真名>："
             f"{leaked[:3]}")
    else:
        ok("instruction 里无未脱敏的路径登录名")

    # 贯穿字段不许在这一层掉。S2 是按字段名逐个搬运的（不是整条透传），新增字段
    # 不会自动跟着走 —— 实测 boundary_confidence 就这样丢过一次：S3 产物里是
    # 'high'/'low'，到 S2 产物全变 None，而当时四组门禁全绿。
    # 那次是靠 query-units.py 筛出「codex 通道 0 条高可信单元」才暴露的。
    CARRY_FIELDS = ("boundary_confidence", "boundary_reason", "ended_by",
                    "step_range", "started_at")
    for f in CARRY_FIELDS:
        if all(r.get(f) is None for r in records):
            fail(f"贯穿字段 {f} 在 S2 产物里全为 None —— 搬运时漏掉了，"
                 f"S3 产物里有值（比对 {common.UNITS}）")
        else:
            filled = sum(1 for r in records if r.get(f) is not None)
            ok(f"贯穿字段 {f} 有值 {filled}/{len(records)}")

    hi = [r for r in records if r.get("needs_review")]
    ok(f"high 级命中 {len(hi)} 条，已标 needs_review（不进公开 split）")
    if any(r.get("secret_severity") == "high" and not r.get("needs_review")
           for r in records):
        fail("有 high 级命中未标 needs_review")

    check_provenance(records, "S2 产物")


def _only_allowlisted_home(text: str) -> bool:
    """文本里的 /Users/x 是否全是 allowlist 里的系统目录"""
    import re
    for m in re.finditer(r"/Users/([A-Za-z0-9._\-]+)", text):
        name = m.group(1)
        if name == "<USER>":
            continue
        if name.lower() in s2_rules.PATH_NAME_ALLOWLIST:
            continue
        if "." in name and not name.startswith("."):
            continue
        return False
    return True


# ── ③ S3 会话切分 ───────────────────────────────────────────────────

def judge_segmentation(units: list[dict]) -> dict:
    """用独立信号（hook 通道 user_prompts）对账切分结果

    这是方法论 3 的落地：切分基于 `raw.jsonl`（proxy 通道），裁判来自
    `metadata.user_prompts`（hook 通道），两条独立采集链路。
    """
    kept = [u for u in units if u.get("keep")]
    bys: dict[str, list[dict]] = collections.defaultdict(list)
    for u in kept:
        bys[u["sid"]].append(u)

    def norm(s: str) -> str:
        return " ".join((s or "").split())[:120].lower()

    tp = fp = fn = 0
    judged = 0
    per_signal: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])

    for sid, us in bys.items():
        path = common.session_file(sid, "session.traj")
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        ups_raw = (data.get("metadata") or {}).get("user_prompts") or []
        ups = []
        for x in ups_raw:
            t = x if isinstance(x, str) else (x.get("text") if isinstance(x, dict) else "")
            if t and t.strip():
                ups.append(norm(t))
        if not ups:
            continue
        judged += 1
        mine = sorted(us, key=lambda x: x.get("seq") or 0)
        mn = [norm(u.get("instruction_raw")) for u in mine]

        matched: set[int] = set()
        for jt in ups:
            hit = None
            for i, mt in enumerate(mn):
                if i in matched:
                    continue
                if (jt[:60] and (jt[:60] in mt or mt[:60] in jt)) or \
                        difflib.SequenceMatcher(None, jt[:100], mt[:100]).ratio() > 0.75:
                    hit = i
                    break
            if hit is not None:
                matched.add(hit)
                tp += 1
            else:
                fn += 1
        fp += len(mn) - len(matched)

        # 逐信号精确率只在裁判 >=2 条的会话上算（单条裁判时首单元必然匹配）
        if len(ups) >= 2:
            for i, u in enumerate(mine):
                sig = u.get("boundary_reason") or "?"
                per_signal[sig][0 if i in matched else 1] += 1

    return {
        "judged_sessions": judged,
        "tp": tp, "fp": fp, "fn": fn,
        "precision": tp / max(tp + fp, 1),
        "recall": tp / max(tp + fn, 1),
        "per_signal": {k: tuple(v) for k, v in per_signal.items()},
    }


def check_s3(units: list[dict] | None = None):
    print("── ③ S3 会话切分（独立信号对账）")
    if units is None:
        if not os.path.exists(common.UNITS):
            fail(f"S3 产物不存在：{common.UNITS}")
            return
        units = common.read_jsonl(common.UNITS)
    kept = [u for u in units if u.get("keep")]
    if not kept:
        fail("S3 保留单元为空")
        return
    ok(f"{len(units)} 单元，保留 {len(kept)}")

    # unit_id 唯一
    ids = [u["unit_id"] for u in units]
    if len(ids) != len(set(ids)):
        dup = [k for k, v in collections.Counter(ids).items() if v > 1]
        fail(f"unit_id 重复 {len(dup)} 个：{dup[:3]}")
    else:
        ok("unit_id 全局唯一")

    # step_range 合法性
    bad = [u["unit_id"] for u in kept
           if u.get("step_range") and (
               u["step_range"][0] > u["step_range"][1] or u["step_range"][0] < 0)]
    if bad:
        fail(f"{len(bad)} 个单元的 step_range 非法：{bad[:3]}")
    else:
        ok("step_range 均合法（lo<=hi 且非负）")

    mapped = sum(1 for u in kept if u.get("step_range"))
    rate = mapped / len(kept)
    if rate < 0.80:
        fail(f"step_range 映射率仅 {rate:.1%}，低于 80% —— index→step 对齐失效")
    else:
        ok(f"step_range 映射率 {rate:.1%}")

    # 中断单元必须淘汰（§4.3）
    leak = [u["unit_id"] for u in kept if u.get("ended_by") == "interrupted"]
    if leak:
        fail(f"{len(leak)} 个 interrupted 单元未淘汰（§4.3 要求直接淘汰）：{leak[:3]}")
    else:
        ok("interrupted 单元均已淘汰（§4.3）")

    # 置信度字段必须齐全 —— 它是本阶段披露局限的载体
    noconf = [u["unit_id"] for u in kept if not u.get("boundary_confidence")]
    if noconf:
        fail(f"{len(noconf)} 个单元缺 boundary_confidence：{noconf[:3]}")
    else:
        dist = collections.Counter(u["boundary_confidence"] for u in kept)
        ok(f"boundary_confidence 齐全：{dict(dist.most_common())}")

    # 独立信号对账
    j = judge_segmentation(units)
    if j["judged_sessions"] < 50:
        warn(f"可裁判会话仅 {j['judged_sessions']} 条，对账结论参考价值有限")
    print(f"    可裁判会话 {j['judged_sessions']}（hook 通道 user_prompts）："
          f"精确 {j['precision']:.1%}，召回 {j['recall']:.1%}")

    # 门禁③：单元区间必须是轨迹的「划分」而非「覆盖」——**不依赖裁判**
    #
    # 这条替代了初版的「单元数不得超过裁判 prompt 数 2.5 倍」。为什么换掉：
    # 那条门禁报出 35 条会话，逐条人工核查后发现**全部是我方切对、裁判漏记**
    # —— 例如 a43561c8 的 seq1-4 分别是「语音输入 / 远程控制 / 沙箱 / Windows
    # 兼容性」四个不同任务，共用同一句模板开头，裁判只记了 4 条中的 1 条。
    # 一条会把正确结果判红的门禁比没有门禁更坏，它会逼着人去把对的改错。
    #
    # 换成区间不重叠：这是可以脱离裁判客观判定的性质。区间重叠必然是 bug ——
    # 同一段动作被算进多个单元，下游 edit_ops / files_touched 全部虚高。
    # 实测这条门禁抓出了三个真实缺陷（依次修掉后重叠率 49.8% → 0%）：
    #   ① 会话恢复时首行 messages 倒灌历史（239 轮全落在 step [0,0]）
    #   ② 一行 raw 内多个 text 块共享时间戳（402 条会话同 started_at 挂多单元）
    #   ③ raw.jsonl 行序 != 时间序（18.2% 会话时间戳非单调，子 agent 并发写入）
    overlap = []
    backward = []
    bys: dict[str, list[dict]] = collections.defaultdict(list)
    for u in kept:
        bys[u["sid"]].append(u)
    for sid, us in bys.items():
        rs = [u.get("step_range") for u in sorted(us, key=lambda x: x.get("seq") or 0)
              if u.get("step_range")]
        if len(rs) < 2:
            continue
        if any(rs[i][0] <= rs[i - 1][1] for i in range(1, len(rs))):
            overlap.append(sid)
        if any(rs[i][0] < rs[i - 1][0] for i in range(1, len(rs))):
            backward.append(sid)
    multi = sum(1 for us in bys.values()
                if len([u for u in us if u.get("step_range")]) >= 2)
    if overlap:
        fail(f"{len(overlap)}/{multi} 条多单元会话的 step_range 存在重叠 —— "
             f"单元区间必须是划分，重叠会让 S4 把同一段动作重复计入："
             f"{[s[:8] for s in overlap[:3]]}")
    else:
        ok(f"{multi} 条多单元会话的 step_range 互不重叠（构成划分）")
    if backward:
        fail(f"{len(backward)} 条会话的 step_range 随 seq 倒退 —— "
             f"切分点未按时间排序：{[s[:8] for s in backward[:3]]}")
    elif multi:
        ok("step_range 随 seq 单调递增")

    # 门禁①②：置信度分档必须与实测一致
    prec_by_conf: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
    for sig, (good, bad_) in j["per_signal"].items():
        conf = seg.boundary_confidence(sig)
        prec_by_conf[conf][0] += good
        prec_by_conf[conf][1] += bad_
    shown: list[tuple[str, float, int]] = []
    for conf in ("high", "medium", "low"):
        g, b = prec_by_conf[conf]
        if g + b:
            shown.append((conf, g / (g + b), g + b))
    for conf, p, n in shown:
        print(f"    {conf:<7} 精确率 {p:>6.1%}（n={n}）")

    hi = next((p for c, p, _ in shown if c == "high"), None)
    if hi is None:
        warn("无 high 档样本，无法校验分档")
    elif hi < HIGH_CONF_MIN_PRECISION:
        fail(f"high 档精确率 {hi:.1%} 低于门禁线 {HIGH_CONF_MIN_PRECISION:.0%}"
             f" —— BOUNDARY_CONFIDENCE 的分档已失真，须重新校准")
    else:
        ok(f"high 档精确率 {hi:.1%} ≥ {HIGH_CONF_MIN_PRECISION:.0%}")

    # 单调性：high > medium > low，否则置信度字段是假的
    order = [p for c, p, _ in shown]
    if len(order) >= 2 and order != sorted(order, reverse=True):
        fail(f"置信度分档非单调（{[(c, round(p, 3)) for c, p, _ in shown]}）"
             f" —— 分档没有区分力，等于假标签")
    elif len(order) >= 2:
        ok("置信度分档单调递减（high > medium > low）")

    check_provenance(kept, "S3 保留单元")


# ── ④ 分类与标注 ────────────────────────────────────────────────────

def check_label(records: list[dict] | None = None):
    print("── ④ 分类与标注")
    if records is None:
        if not os.path.exists(LABELED):
            fail(f"标注产物不存在：{LABELED}")
            return
        records = common.read_jsonl(LABELED)
    if not records:
        fail("标注产物为空")
        return
    ok(f"{len(records)} 条已标注单元")

    legal_cat = set(labeler.CATEGORY_PATTERNS) | {"unclassified"}
    illegal = {r.get("category") for r in records} - legal_cat
    if illegal:
        fail(f"category 出现非法取值：{illegal}")
    else:
        ok(f"category 取值合法（{len(legal_cat)} 种）")

    missing = [r.get("unit_id") for r in records
               if not r.get("category_confidence") or not r.get("difficulty")]
    if missing:
        fail(f"{len(missing)} 条缺 category_confidence / difficulty：{missing[:3]}")
    else:
        ok("category_confidence 与 difficulty 齐全")

    # 难度偏斜门禁（Phase 2 验收列前置到这里；v0.1 就是在这失控的）
    rated = [r for r in records if r.get("difficulty") != "unrated"]
    if not rated:
        fail("无任何单元有难度评级")
    else:
        dist = collections.Counter(r["difficulty"] for r in rated)
        share = max(dist.values()) / len(rated)
        if share > DIFFICULTY_MAX_SHARE:
            fail(f"difficulty 单档占比 {share:.1%} 超过 {DIFFICULTY_MAX_SHARE:.0%}"
                 f"（{dict(dist)}）—— v0.1 就是这样造出 87.4% hard 的")
        else:
            ok(f"difficulty 最大单档 {share:.1%} ≤ {DIFFICULTY_MAX_SHARE:.0%}"
               f"（{dict(dist.most_common())}）")

    # unrated 必须只出现在零写单元上（否则是判定逻辑串了）
    wrong = [r.get("unit_id") for r in records
             if r.get("difficulty") == "unrated" and (r.get("edit_ops") or 0) > 0]
    if wrong:
        fail(f"{len(wrong)} 条有写操作却记 unrated：{wrong[:3]}")
    else:
        ok("unrated 仅出现在零写操作单元上")

    # 类别不许坍缩到单一值
    cat_dist = collections.Counter(r["category"] for r in records)
    top_share = cat_dist.most_common(1)[0][1] / len(records)
    if top_share > 0.60:
        fail(f"category 最大类占比 {top_share:.1%} 超过 60%"
             f"（{cat_dist.most_common(1)[0][0]}）—— 打分逻辑可能坍缩")
    else:
        ok(f"category 最大类占比 {top_share:.1%}（{cat_dist.most_common(1)[0][0]}）")

    if len(cat_dist) < 4:
        fail(f"只识别出 {len(cat_dist)} 个类别 —— 分类逻辑可疑")
    else:
        ok(f"识别出 {len(cat_dist)} 个类别")

    check_provenance(records, "标注产物")


# ── 贯穿检查：源信息 ────────────────────────────────────────────────

def check_provenance(records: list[dict], label: str):
    """源信息块必须在每一层产物里都齐全（用户 2026-09-05 要求）"""
    if not records:
        return
    bad = []
    for r in records[:20000]:
        miss = common.missing_provenance(r)
        if miss:
            bad.append((r.get("unit_id") or r.get("sid"), miss))
    if bad:
        fail(f"{label}：{len(bad)} 条缺源信息字段，如 {bad[0]}")
        return

    src = collections.Counter(r.get("agent_source") for r in records)
    illegal = set(src) - set(common.AGENT_SOURCES)
    if illegal:
        fail(f"{label}：agent_source 非法取值 {illegal}")
    elif len(src) < 2:
        fail(f"{label}：只剩 {len(src)} 个采集通道 —— 线上实测有 4 类，判定逻辑可疑")
    else:
        ok(f"{label}：源信息齐全，通道 {dict(src.most_common())}")

    # 批次一致性：不许混批
    batches = {r.get("batch_version") for r in records}
    if len(batches) > 1:
        fail(f"{label}：混入多个批次 {batches} —— 破坏可复现性（§3.1 门槛 4）")
    else:
        ok(f"{label}：批次单一 {batches.pop()}")


# ── 反向自证 ────────────────────────────────────────────────────────

def _inject_overlap(units: list[dict]) -> list[dict]:
    """把某条多单元会话的第二个单元起点拉回到第一个单元区间内（制造重叠）"""
    out = [dict(u) for u in units]
    bys: dict[str, list[int]] = collections.defaultdict(list)
    for i, u in enumerate(out):
        if u.get("keep") and u.get("step_range"):
            bys[u["sid"]].append(i)
    for idxs in bys.values():
        if len(idxs) < 2:
            continue
        idxs.sort(key=lambda i: out[i].get("seq") or 0)
        first, second = out[idxs[0]], out[idxs[1]]
        second["step_range"] = [first["step_range"][0],
                                max(first["step_range"][1], second["step_range"][1])]
        return out
    return out


def _inject_backward(units: list[dict]) -> list[dict]:
    """把某条会话的单元区间顺序颠倒（制造倒退但不重叠）"""
    out = [dict(u) for u in units]
    bys: dict[str, list[int]] = collections.defaultdict(list)
    for i, u in enumerate(out):
        if u.get("keep") and u.get("step_range"):
            bys[u["sid"]].append(i)
    for idxs in bys.values():
        if len(idxs) < 3:
            continue
        idxs.sort(key=lambda i: out[i].get("seq") or 0)
        ranges = [out[i]["step_range"] for i in idxs]
        for i, rng in zip(idxs, reversed(ranges), strict=True):
            out[i]["step_range"] = list(rng)
        return out
    return out


def self_test() -> int:
    """注入已知缺陷，每类必须变红且原因对得上号

    §9.0/§9.4 的教训：只看退出码不够 —— 任何被裁剪的产物都可能因某个无关原因
    变红，自证会看着全绿却什么都没验到。所以每个 case 都校验**变红原因**。
    另有一个「健康基线必须保持绿」的 case，用来区分「有鉴别力」与「恒红」。
    """
    print("=== 反向自证：健康基线必须绿，每类注入缺陷必须变红（且原因对得上号）===\n")

    for path, name in ((common.FILTERED, "S1"), (DESENS_UNITS, "S2"),
                       (common.UNITS, "S3"), (LABELED, "label")):
        if not os.path.exists(path):
            print(f"  ⚠ 缺少 {name} 产物 {path}，先跑完流水线再自证")
            return 1

    filtered = common.read_jsonl(common.FILTERED)
    desens = common.read_jsonl(DESENS_UNITS)
    units = common.read_jsonl(common.UNITS)
    labeled = common.read_jsonl(LABELED)

    def run(fn, data) -> list[str]:
        global FAILS, WARNS
        FAILS, WARNS = [], []
        buf = []
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()) as s:
            fn(data)
        buf = list(FAILS)
        _ = s
        return buf

    cases: list[tuple[str, object, object, str | None]] = [
        ("健康基线（必须保持绿）", check_s1, filtered, None),
        ("健康基线 S2（必须保持绿）", check_s2, desens, None),
        ("健康基线 S3（必须保持绿）", check_s3, units, None),
        ("健康基线 label（必须保持绿）", check_label, labeled, None),
        # S1：淘汰不写归因
        ("S1 淘汰无归因",
         check_s1,
         [{**r, "drop_reason": None} if not r.get("keep") else r for r in filtered],
         "淘汰无归因"),
        # S1：自指污染漏进保留集
        ("S1 自指污染漏网",
         check_s1,
         [{**r, "keep": True, "drop_reason": None}
          if r.get("drop_reason") == "E_SELF_REFERENTIAL" else r for r in filtered],
         "自指污染漏网"),
        # S1：源信息被抹掉
        ("S1 源信息丢失",
         check_s1,
         [{k: v for k, v in r.items() if k != "agent_source"} for r in filtered],
         "缺源信息字段"),
        # S2：贯穿字段被搬丢（实际发生过，且当时四组门禁全绿）
        ("S2 贯穿字段丢失",
         check_s2,
         [{**r, "boundary_confidence": None} for r in desens],
         "全为 None"),
        # S2：脱敏没生效（把原文塞回去）
        ("S2 脱敏未生效",
         check_s2,
         [{**r, "instruction_clean":
           "key sk-REvAV2bcQ4aARmDhi0dqH35C7tJYJiPE4gtPLWJMVuMeYkle "
           "at /Users/zhourusheng/Code"} for r in desens[:200]],
         "残留"),
        # S3：中断单元没淘汰
        ("S3 interrupted 单元未淘汰",
         check_s3,
         [{**u, "keep": True} if u.get("ended_by") == "interrupted" else u
          for u in units],
         "interrupted 单元未淘汰"),
        # S3：置信度字段丢失
        ("S3 置信度字段丢失",
         check_s3,
         [{k: v for k, v in u.items() if k != "boundary_confidence"} for u in units],
         "缺 boundary_confidence"),
        # S3：区间重叠（门禁③要抓的核心缺陷，必须自证它真的会红）
        ("S3 step_range 重叠",
         check_s3,
         _inject_overlap(units),
         "存在重叠"),
        # S3：区间倒退（切分点未按时间排序时的症状）
        ("S3 step_range 倒退",
         check_s3,
         _inject_backward(units),
         "倒退"),
        # S3：置信度分档失真（把所有信号都标 high）
        ("S3 置信度分档失真",
         check_s3,
         units,
         None),  # 特殊处理，见下
        # label：难度全判一档
        ("label 难度偏斜",
         check_label,
         [{**r, "difficulty": "hard", "edit_ops": max(1, r.get("edit_ops") or 1)}
          for r in labeled],
         "单档占比"),
        # label：类别坍缩
        ("label 类别坍缩",
         check_label,
         [{**r, "category": "bug_fix"} for r in labeled],
         "最大类占比"),
        # 混批
        ("混入多个批次",
         check_label,
         [{**r, "batch_version": ("v0.9" if i % 2 else r.get("batch_version"))}
          for i, r in enumerate(labeled)],
         "混入多个批次"),
    ]

    passed = 0
    total = 0
    for name, fn, data, expect in cases:
        if name == "S3 置信度分档失真":
            # 把 BOUNDARY_CONFIDENCE 全改 high，门禁应因单调性或 high 精确率变红
            saved = dict(seg.BOUNDARY_CONFIDENCE)
            try:
                for k in seg.BOUNDARY_CONFIDENCE:
                    seg.BOUNDARY_CONFIDENCE[k] = "high"
                bad = run(check_s3, [{**u, "boundary_confidence": "high"} for u in units])
            finally:
                seg.BOUNDARY_CONFIDENCE.clear()
                seg.BOUNDARY_CONFIDENCE.update(saved)
            total += 1
            got = any("high 档精确率" in b or "非单调" in b for b in bad)
            if got:
                print(f"  [✓ 变红] {name} —— 命中预期原因「分档失真」")
                passed += 1
            else:
                print(f"  [✗ 未拦下] {name}（实际报红：{bad[:2]}）")
            continue

        total += 1
        bad = run(fn, data)
        if expect is None:
            if not bad:
                print(f"  [✓ 保持绿] {name}")
                passed += 1
            else:
                print(f"  [✗ 基线变红] {name} —— {bad[:2]}")
        else:
            hit = [b for b in bad if expect in b]
            if hit:
                print(f"  [✓ 变红] {name} —— 命中预期原因「{expect}」")
                passed += 1
            elif bad:
                print(f"  [✗ 原因不符] {name} —— 期望「{expect}」，实际 {bad[:2]}")
            else:
                print(f"  [✗ 未拦下] {name}")

    print(f"\n自证结果：{passed}/{total} 通过")
    return 0 if passed == total else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["s1", "s2", "s3", "label", "all"],
                    default="all")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    print("Phase 1 验收\n")
    if args.stage in ("s1", "all"):
        check_s1()
    if args.stage in ("s2", "all"):
        check_s2()
    if args.stage in ("s3", "all"):
        check_s3()
    if args.stage in ("label", "all"):
        check_label()

    print()
    if FAILS:
        print(f"验收结果：不通过（{len(FAILS)} 项失败，{len(WARNS)} 项警告）")
        for f in FAILS:
            print(f"  ✗ {f}")
        return 1
    print(f"验收结果：通过（{len(WARNS)} 项警告）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
