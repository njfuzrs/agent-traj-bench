#!/usr/bin/env python3
"""s0-pull 去重与必填环境变量。不打网、不碰真湖。

加载脚本前必须先把 TRAJ_PLATFORM_URL / TRAJ_AUTH_PASS 写进 environ，
否则模块顶层 `_require_env` 会在 import 时退出。
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PHASE0 = Path(__file__).resolve().parent.parent / "s0"
S0_PULL = PHASE0 / "s0-pull.py"


def _load_pull(monkeypatch, tmp_path, extra_env=None):
    """按绝对路径加载 s0-pull.py，绕开 import 与两层 common.py。"""
    env = {
        "TRAJ_PLATFORM_URL": "http://example.invalid/traj",
        "TRAJ_AUTH_PASS": "test-pass",
        "TRAJ_PULL_DIR": str(tmp_path),
    }
    if extra_env:
        env.update(extra_env)
    for k, v in env.items():
        if v == "":
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    # 模块顶层只读一次。每次用例用独立模块名，避免上次的 LOCAL_SESSIONS_DIR 残留。
    name = f"s0_pull_{tmp_path.name}"
    spec = importlib.util.spec_from_file_location(name, S0_PULL)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _session(**kw):
    base = {
        "session_id": "sid-1",
        "end_time": "2026-09-01T00:00:00",
        "exit_status": "0",
        "total_steps": 10,
        "duration_ms": 1000,
    }
    base.update(kw)
    return base


def _write_marker(mod, sid, fingerprint=None, raw="{}"):
    d = mod.LOCAL_SESSIONS_DIR / sid
    d.mkdir(parents=True, exist_ok=True)
    marker = d / ".pulled"
    if raw is not None and fingerprint is None:
        marker.write_text(raw)
        return marker
    marker.write_text(json.dumps({
        "pulled_at": "2026-09-01T00:00:00",
        "files": {},
        "fingerprint": fingerprint or {},
    }))
    return marker


def test_should_skip_no_marker(monkeypatch, tmp_path):
    mod = _load_pull(monkeypatch, tmp_path)
    skip, reason = mod.should_skip(_session())
    assert skip is False
    assert reason == "未拉取"


def test_should_skip_fingerprint_match(monkeypatch, tmp_path):
    mod = _load_pull(monkeypatch, tmp_path)
    s = _session()
    _write_marker(mod, s["session_id"], fingerprint=mod.fingerprint_of(s), raw=None)
    skip, reason = mod.should_skip(s)
    assert skip is True
    assert reason == "指纹一致"


def test_should_skip_fingerprint_changed(monkeypatch, tmp_path):
    mod = _load_pull(monkeypatch, tmp_path)
    s = _session()
    old = mod.fingerprint_of(s)
    old["total_steps"] = 1
    _write_marker(mod, s["session_id"], fingerprint=old, raw=None)
    skip, reason = mod.should_skip(s)
    assert skip is False
    assert reason == "指纹变化"


def test_should_skip_in_progress(monkeypatch, tmp_path):
    mod = _load_pull(monkeypatch, tmp_path)
    s = _session(end_time="")
    _write_marker(mod, s["session_id"], fingerprint=mod.fingerprint_of({
        **s, "end_time": "already-ended",
    }), raw=None)
    skip, reason = mod.should_skip(s)
    assert skip is False
    assert reason == "进行中"


def test_should_skip_legacy_marker(monkeypatch, tmp_path):
    mod = _load_pull(monkeypatch, tmp_path)
    s = _session()
    _write_marker(mod, s["session_id"], fingerprint=None, raw=json.dumps({
        "pulled_at": "2026-04-01T00:00:00",
        "files": {"session.traj": "ok"},
    }))
    skip, reason = mod.should_skip(s)
    assert skip is True
    assert reason == "已拉取(老格式)"


def test_should_skip_broken_marker(monkeypatch, tmp_path):
    mod = _load_pull(monkeypatch, tmp_path)
    s = _session()
    _write_marker(mod, s["session_id"], raw="not-json{")
    skip, reason = mod.should_skip(s)
    assert skip is False
    assert reason == "标记损坏"


def test_fingerprint_keys(monkeypatch, tmp_path):
    mod = _load_pull(monkeypatch, tmp_path)
    fp = mod.fingerprint_of(_session())
    assert set(fp) == {"end_time", "exit_status", "total_steps", "duration_ms"}


def test_local_dir_honors_traj_pull_dir(monkeypatch, tmp_path):
    lake = tmp_path / "lake"
    mod = _load_pull(monkeypatch, tmp_path, extra_env={"TRAJ_PULL_DIR": str(lake)})
    assert mod.LOCAL_SESSIONS_DIR == lake


def test_local_dir_falls_back_to_sessions_dir(monkeypatch, tmp_path):
    lake = tmp_path / "from-sessions"
    mod = _load_pull(
        monkeypatch,
        tmp_path,
        extra_env={"SESSIONS_DIR": str(lake), "TRAJ_PULL_DIR": ""},
    )
    # TRAJ_PULL_DIR 未设时落到 SESSIONS_DIR
    assert mod.LOCAL_SESSIONS_DIR == lake


def test_repo_root_is_repo_not_s0(monkeypatch, tmp_path):
    mod = _load_pull(monkeypatch, tmp_path)
    assert mod.REPO_ROOT == PHASE0.parent.parent
    assert (mod.REPO_ROOT / "pipeline" / "s0").is_dir()
    assert (mod.REPO_ROOT / "scripts").is_dir()
    # 禁止 Path(__file__).parent —— 那会落到 pipeline/s0/
    assert mod.REPO_ROOT != PHASE0


def _run_pull(env, *args):
    merged = os.environ.copy()
    merged.update(env)
    return subprocess.run(
        [sys.executable, str(S0_PULL), *args],
        capture_output=True,
        text=True,
        env=merged,
        cwd=str(PHASE0.parent.parent),
    )


def test_missing_platform_url_exits():
    env = {
        "TRAJ_PLATFORM_URL": "",
        "TRAJ_AUTH_PASS": "x",
    }
    proc = _run_pull(env, "--list-only")
    assert proc.returncode != 0
    assert "TRAJ_PLATFORM_URL" in (proc.stderr + proc.stdout)


def test_missing_auth_pass_exits():
    env = {
        "TRAJ_PLATFORM_URL": "http://example.invalid/traj",
        "TRAJ_AUTH_PASS": "",
    }
    proc = _run_pull(env, "--list-only")
    assert proc.returncode != 0
    assert "TRAJ_AUTH_PASS" in (proc.stderr + proc.stdout)
