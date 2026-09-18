"""污染字段扫描。出处：sid-code 13 号清单 PR4 / B6-10 五个黑名单字段。

「拿什么证明生效」⛔ 不是「脚本在仓里」，是：
  1. 干净 tasks/ → rc=0
  2. 塞一个字段 → rc=1 且点名字段（反向自证）
  3. 空作用域 → rc=2，⛔ 不许当通过
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
SCRIPT = SCRIPTS / "check-contamination.py"

KEYWORDS = (
    "tool_result_content",
    "response_content",
    "patch_content",
    "observation_content",
    "completion_text",
)


def _load():
    spec = importlib.util.spec_from_file_location("check_contamination", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
    )


def test_keywords_are_the_five_sid_code_fields():
    """与 sid-code B6-10 逐字一致。少一个就是防线缺口，多一个会逼人改题面。"""
    m = _load()
    assert tuple(m.KEYWORDS) == KEYWORDS


def test_real_tasks_are_clean():
    """生产路径：本仓 tasks/ 现在 0 命中。这是 CI 门禁⑫ 的同一条命令。"""
    r = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert r.returncode == 0, r.stderr
    assert "0 hits" in r.stdout


def test_empty_tasks_dir_is_error_not_pass(tmp_path):
    """空集必须 exit 2。sid-code 原扫描器对空集返回 0，那是 PR3d 后的中间态，这里不许复发。"""
    (tmp_path / "tasks").mkdir()
    r = _run(tmp_path)
    assert r.returncode == 2, r.stderr
    assert "0 个文件" in r.stderr


def test_missing_tasks_dir_is_error_not_pass(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 2, r.stderr


def test_inject_one_field_is_red_and_named(tmp_path):
    """反向自证：塞 tool_result_content → 必须红，且点名字段与文件。"""
    task = tmp_path / "tasks" / "T0002"
    task.mkdir(parents=True)
    (task / "instruction.md").write_text("修一个 bug\n", encoding="utf-8")
    dirty = task / "meta.json"
    dirty.write_text('{"tool_result_content": "上一轮答案"}\n', encoding="utf-8")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    combined = r.stdout + r.stderr
    assert "tool_result_content" in combined
    assert "meta.json" in combined


def test_each_of_five_fields_is_caught(tmp_path):
    """五个字段每一个单独都能抓住。漏一个 = 那个字段没人守。"""
    for kw in KEYWORDS:
        root = tmp_path / kw
        d = root / "tasks" / "T0001"
        d.mkdir(parents=True)
        (d / "instruction.md").write_text(f"hello {kw} world\n", encoding="utf-8")
        r = _run(root)
        assert r.returncode == 1, f"{kw} 没抓住: {r.stdout}{r.stderr}"
        assert kw in (r.stdout + r.stderr)


def test_clean_fixture_is_green(tmp_path):
    d = tmp_path / "tasks" / "T0001"
    d.mkdir(parents=True)
    (d / "instruction.md").write_text("修一个 bug\n", encoding="utf-8")
    (d / "task.toml").write_text('task_id = "T0001"\n', encoding="utf-8")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert "0 hits" in r.stdout


def test_ci_yml_wires_the_script():
    """建好未接线会让单测绿、CI 永远不跑生产路径。"""
    ci = (REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "scripts/check-contamination.py" in ci
    assert "gate12 - tasks/ 无 5 个污染字段" in ci
    # CI 的 pytest 必须收集本文件，否则反向自证只在本地绿
    assert "tests/test_contamination.py" in ci
