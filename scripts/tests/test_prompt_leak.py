"""T03 / traj 缺陷 1、6：题面泄漏门禁 `check-prompt-leak.py`。

阳性对照用入库的 t8 题面（现拼），阴性对照用原句 `instruction.md`，
变异自证用合成题。判据见脚本 docstring。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

MVP = Path(__file__).resolve().parent.parent


def _load():
    # common 先按本层那份占住（同 test_mvp.py 顶部的理由：pipeline/ 层有同名 common.py）
    cspec = importlib.util.spec_from_file_location("common", MVP / "common.py")
    assert cspec and cspec.loader
    cmod = importlib.util.module_from_spec(cspec)
    sys.modules["common"] = cmod
    cspec.loader.exec_module(cmod)
    spec = importlib.util.spec_from_file_location("_check_prompt_leak", MVP / "check-prompt-leak.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, cmod


leak, c = _load()

#: 缺陷 1 实测的 8 条（2026-09-28）。⛔ 改这张表之前先确认是题面变了，不是判据松了。
DEFECT1_LEAKED = {"T0008", "T0014", "T0026", "T0040", "T0050", "T0059", "T0064", "T0065"}


def test_t8_prompts_flag_exactly_the_defect1_tasks():
    """阳性对照：37.8% 那批题面必须报出缺陷 1 的 8/34 条，一条不少、不多报。"""
    prompts = leak.load_prompts("t8", c.MVP_TASKS)
    res = leak.scan(prompts, c.MVP_TASKS)
    bad = {t for t, r in res.items() if r["leaked"]}
    assert bad == DEFECT1_LEAKED, f"多报 {bad - DEFECT1_LEAKED}，漏报 {DEFECT1_LEAKED - bad}"
    assert len(res["T0008"]["leaked"]) >= 20, "T0008 泄的是实现主体，命中行数不该只有零星几行"


def test_raw_instruction_is_clean():
    """阴性对照：原句 + 环境事实里没有 gold patch 代码。"""
    res = leak.scan(leak.load_prompts("raw", c.MVP_TASKS), c.MVP_TASKS)
    assert len(res) == 39
    assert not {t for t, r in res.items() if r["leaked"]}


def _mk_task(root: Path, name: str, prompt: str, gold: str) -> None:
    d = root / name
    (d / "solution").mkdir(parents=True)
    (d / "instruction.eval.md").write_text(prompt, encoding="utf-8")
    (d / "solution" / "gold_patch.diff").write_text(gold, encoding="utf-8")


GOLD = "\n".join([
    "diff --git a/src/x.ts b/src/x.ts",
    "+++ b/src/x.ts",
    "+  if (matcher.startsWith('/') && matcher.endsWith('/')) {",
    "+    return matcher.split('|').some((n) => n === toolName);",
    "+  const pattern = matcher.slice(1, -1) + suffixOfSomething;",
    "+export type HookPermissionDecision = 'allow' | 'deny' | 'ask';",
    "+  getPermissionDecision(): HookPermissionDecision | undefined {",
    "+  // 这是一行很长很长很长很长很长很长很长的注释，不算实现",
    "+  }",
])


def test_mutation_injecting_gold_lines_turns_red(tmp_path):
    """变异自证：干净题面 → 0；注入 5 行 gold patch → 必须报红，且 5 行都报出来。"""
    clean = "请修复 matcher 的匹配逻辑，让测试通过。\n"
    _mk_task(tmp_path, "T9001", clean, GOLD)
    assert leak.main(["--tasks", str(tmp_path)]) == 0

    injected = clean + "\n".join(
        l[1:] for l in GOLD.splitlines() if l.startswith("+") and not l.startswith("+++"))
    (tmp_path / "T9001" / "instruction.eval.md").write_text(injected, encoding="utf-8")
    assert leak.main(["--tasks", str(tmp_path)]) == 1
    hit = leak.scan(leak.load_prompts("eval", tmp_path), tmp_path)["T9001"]["leaked"]
    assert len(hit) == 5, hit


def test_short_and_comment_lines_are_not_candidates():
    cand = leak.gold_candidates(GOLD)
    assert "}" not in cand
    assert not any(x.startswith("//") for x in cand)
    assert all(len(x) >= leak.MIN_LEN for x in cand)


def test_empty_scope_is_not_a_pass(tmp_path):
    """⛔ 0 份题面 0 命中不许当通过：`instruction.eval.md` 还没生成时默认模式必须红。"""
    assert leak.main(["--tasks", str(tmp_path)]) == 2
    (tmp_path / "T9002").mkdir()  # 有题目录但没有 eval 题面
    assert leak.main(["--tasks", str(tmp_path)]) == 2


# ── 豁免清单 ─────────────────────────────────────────────────────────

def test_allowlist_suppresses_only_listed_lines_and_flags_stale(tmp_path):
    clean = "请修复 matcher。\n"
    line = "return matcher.split('|').some((n) => n === toolName);"
    _mk_task(tmp_path, "T9001", clean + line + "\n", GOLD)
    allow = tmp_path / "allow.json"
    allow.write_text(json.dumps({"T9001": [{"line": line, "reason": "r", "evidence": "e"}]}))
    assert leak.main(["--tasks", str(tmp_path), "--allowlist", str(allow)]) == 0
    # 再泄一行没豁免的 ⇒ 红
    (tmp_path / "T9001" / "instruction.eval.md").write_text(
        clean + line + "\nexport type HookPermissionDecision = 'allow' | 'deny' | 'ask';\n")
    assert leak.main(["--tasks", str(tmp_path), "--allowlist", str(allow)]) == 1
    # 豁免项不再命中 ⇒ 红（防清单腐烂）
    (tmp_path / "T9001" / "instruction.eval.md").write_text(clean)
    assert leak.main(["--tasks", str(tmp_path), "--allowlist", str(allow)]) == 1


def test_allowlist_entry_without_evidence_is_rejected(tmp_path):
    allow = tmp_path / "allow.json"
    allow.write_text(json.dumps({"T9001": [{"line": "x" * 30, "reason": "r"}]}))
    with pytest.raises(SystemExit):
        leak.load_allowlist(allow)


def test_committed_allowlist_entries_all_carry_evidence():
    allow = leak.load_allowlist(leak.ALLOWLIST)  # 缺字段会直接 SystemExit
    assert set(allow) == {"T0014"}, f"豁免清单变了，逐条复核证据：{sorted(allow)}"


# ── T04：instruction.eval.md 生成器 ────────────────────────────────────

def _gen():
    spec = importlib.util.spec_from_file_location("_build_eval", MVP / "build-eval-instruction.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_strip_fenced_blocks_removes_code_and_keeps_prose():
    gen = _gen()
    doc = "前文\n```ts\nconst secret = 1;\n```\n中间\n```\nmore();\n"  # 第二块未闭合
    out = gen.strip_fenced_blocks(doc)
    assert "secret" not in out and "more()" not in out and "```" not in out
    assert "前文" in out and "中间" in out
    assert out.count(gen.FENCE_PLACEHOLDER) == 2


def test_committed_eval_instructions_match_generator():
    """入库的 instruction.eval.md 必须是生成器现拼的结果（防手改）。"""
    assert _gen().main(["--check"]) == 0


def test_eval_instruction_drops_module_hint_and_keeps_raw_sentence():
    for t in ("T0008", "T0026"):
        ev = (c.MVP_TASKS / t / "instruction.eval.md").read_text(encoding="utf-8")
        raw = (c.MVP_TASKS / t / "instruction.md").read_text(encoding="utf-8")
        assert "文件名指示了实现应落在哪个模块" not in ev
        assert raw.partition("\n---\n")[0].strip() in ev, "原句必须原样保留"


def test_eval_instructions_carry_no_real_login_name():
    """内联文档按 instruction.md 同一口径脱敏（`/Users/<USER>`）。"""
    bad = [p.parent.name for p in c.MVP_TASKS.glob("*/instruction.eval.md")
           if "/Users/zhourusheng" in p.read_text(encoding="utf-8")]
    assert not bad, f"题面里有本机登录名：{bad[:5]}"
