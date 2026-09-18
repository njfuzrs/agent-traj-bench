"""证据层归档脚本的门禁级单测。

出处：`docs-research/trajectory-platform/20260917-evidence-archive-plan.md` §4.5 / §6.3。
"""
from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / file)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_redact_pattern_matches_gate5():
    """组装出的模式必须与 ci.yml 门禁⑤ 的 PAT **逐字一致**。

    写宽会误伤合规披露散文；写窄会让门禁⑤ 报红。两条都是破坏。
    """
    redact = _load("redact_evidence", "redact-evidence.py")
    ci = (REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    m = re.search(r"^          PAT='(.*)'$", ci, re.M)
    assert m, "ci.yml 里找不到门禁⑤ 的 PAT"
    # 门禁⑤ 是 PAT 出现的第一处（门禁⑧ 那处是另一条）
    first = re.findall(r"^          PAT='(.*)'$", ci, re.M)[0]
    assert redact.PATTERN == first, (
        f"redact-evidence.PATTERN 与门禁⑤ 不一致\n"
        f"  脚本: {redact.PATTERN}\n"
        f"  ci  : {first}"
    )


def test_redact_placeholder_does_not_match_pattern():
    """占位符本身不许再命中模式，否则替换不收敛、幂等自证必红。"""
    redact = _load("redact_evidence", "redact-evidence.py")
    assert redact._compiled(redact.PATTERN).search(
        redact.PLACEHOLDER.encode("utf-8")
    ) is None


def test_check_evidence_due_requires_env(tmp_path):
    """没给 EVIDENCE_RUNS_ROOT 必须 exit 2，⛔ 不是跳过。"""
    env = {k: v for k, v in os.environ.items() if k != "EVIDENCE_RUNS_ROOT"}
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "check-evidence-due.py")],
        env=env, capture_output=True, text=True,
    )
    assert r.returncode == 2, r.stderr
    assert "EVIDENCE_RUNS_ROOT" in r.stderr


def test_check_evidence_due_names_missing_job(tmp_path):
    """反向自证：清单里拿掉一个 job ⇒ 闸必须报红并**点名**。"""
    runs = tmp_path / "runs"
    (runs / "t8-rerun" / "2026-09-13__19-35-38").mkdir(parents=True)
    (runs / "baseline" / "2026-09-12__23-46-37").mkdir(parents=True)
    man = tmp_path / "MANIFEST.tsv"
    man.write_text(
        "job_path\tsha256\n"
        "baseline/2026-09-12__23-46-37\tabc\n"
        # 故意不写 t8-rerun 那一行
        "_stage-prompts\tdef\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["EVIDENCE_RUNS_ROOT"] = str(runs)
    env["MANIFEST"] = str(man)
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "check-evidence-due.py")],
        env=env, capture_output=True, text=True,
    )
    assert r.returncode == 4, r.stdout + r.stderr
    assert "t8-rerun/2026-09-13__19-35-38" in (r.stdout + r.stderr)
