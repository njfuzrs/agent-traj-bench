"""T15 跑批脚本的纯逻辑：定价判据、分档、命令行、二进制点名。

不跑 harbor、不起容器、不调模型（$0，CI 上真跑）。网关/容器那几道闸依赖本机环境，
由 `t15-baseline.py --dry-run` 在采集机上实测，不在这里 mock —— mock 出来的绿不证明任何事。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

MVP = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("_t15", MVP / "t15-baseline.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


t15 = _load()

REAL = {"input": 2, "output": 8, "currency": "CNY", "asOf": "2026-10-10"}


# ── 闸H 定价：宿主没配时改看内置注册表（旧 t7 闸5 在这里会误报）────────────


def test_pricing_registry_only_is_green():
    # 这正是 2026-11-05 的真实形态：宿主 settings.json 没配 pricing，内置注册表有真价
    src, red = t15.judge_pricing(None, REAL)
    assert red is None and "内置注册表" in src


def test_pricing_host_wins_over_registry():
    host = {"input": 1, "output": 4}
    src, red = t15.judge_pricing(host, {"input": 75, "output": 75})
    assert red is None and "宿主" in src


def test_pricing_both_missing_is_red():
    _, red = t15.judge_pricing(None, None)
    assert red and "网关采集价" in red


@pytest.mark.parametrize("p", [{"input": 75, "output": 75}, {"input": 75.0, "output": 75.0}])
def test_pricing_placeholder_is_red(p):
    _, red = t15.judge_pricing(None, p)
    assert red and "占位" in red


def test_pricing_incomplete_is_red():
    _, red = t15.judge_pricing(None, {"input": 2})
    assert red and "不完整" in red


# ── 闸D 分档：从 task.toml 现算，值 = 硬顶 × 0.9 ─────────────────────────────


def test_duration_table_is_hard_cap_times_0_9():
    for sec, ms in t15.DURATION_BY_TIMEOUT.items():
        assert ms == int(sec * t15.AGENT_TIMEOUT_MULT * 0.9 * 1000), sec
    assert t15.DURATION_BY_TIMEOUT == {1800: 4_860_000, 2700: 7_290_000}


def _task(root: Path, name: str, sec) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "task.toml").write_text(f"[agent]\ntimeout_sec = {sec}\n", encoding="utf-8")


def test_tiers_groups_by_timeout(tmp_path):
    _task(tmp_path, "T0001", "1800.0")
    _task(tmp_path, "T0002", "2700.0")
    _task(tmp_path, "T0003", "2700.0")
    assert t15.tiers(tmp_path) == {1800: ["T0001"], 2700: ["T0002", "T0003"]}


def test_tiers_rejects_fractional_timeout(tmp_path):
    _task(tmp_path, "T0001", "1800.5")
    with pytest.raises(SystemExit):
        t15.tiers(tmp_path)


def test_real_release_has_only_known_tiers():
    """真发布目录：每档都在表里（出现新档必须先定值，否则闸D 拒跑）。"""
    if not t15.DIST_TASKS.exists():
        pytest.skip("dist/v0.2.1/tasks 未导出（CI 上不导出发布目录）")
    tt = t15.tiers()
    assert set(tt) <= set(t15.DURATION_BY_TIMEOUT)
    assert sum(len(v) for v in tt.values()) == len(t15.scored_tasks())


# ── 命令行：每档传自己的 max_duration_ms，并发与预算固定 ─────────────────────


def _ak(cmd: list[str]) -> dict[str, str]:
    return dict(cmd[i + 1].split("=", 1) for i, x in enumerate(cmd) if x == "--ak")


@pytest.mark.parametrize("sec", [1800, 2700])
def test_cmd_passes_tier_duration(sec, tmp_path):
    cmd = t15.build_cmd(tmp_path, tmp_path, t15.DURATION_BY_TIMEOUT[sec])
    ak = _ak(cmd)
    assert ak["max_duration_ms"] == str(t15.DURATION_BY_TIMEOUT[sec])
    assert ak["max_turns"] == "120" and ak["max_budget_usd"] == "1.8"
    assert cmd[cmd.index("-k") + 1] == "1", "轮次由脚本控制，harbor 每次只跑 1 轮"
    assert cmd[cmd.index("--agent-timeout-multiplier") + 1] == "3.0"


def _elf(path: Path, machine: int) -> Path:
    path.write_bytes(b"\x7fELF" + b"\0" * 14 + machine.to_bytes(2, "little") + b"\0" * 8)
    return path


def test_env_names_only_matching_arch(tmp_path):
    env = t15.build_env(_elf(tmp_path / "sid-code", 0xB7))
    assert env["SID_HARBOR_BINARY_ARM64"].endswith("sid-code")
    assert "SID_HARBOR_BINARY_X64" not in env or env["SID_HARBOR_BINARY_X64"] != env["SID_HARBOR_BINARY_ARM64"]
    assert env["HARBOR_TELEMETRY"] == "0"


def test_elf_arch_reads_bytes_not_name(tmp_path):
    # 文件名写 arm64、字节是 x86-64 ⇒ 判 x64（目录名/文件名都不是判据）
    assert t15.elf_arch(_elf(tmp_path / "sid-code-arm64", 0x3E)) == "x64"


def test_bypass_loopback_proxy_adds_without_clobbering(monkeypatch):
    monkeypatch.setenv("no_proxy", "corp.example")
    monkeypatch.delenv("NO_PROXY", raising=False)
    t15.bypass_loopback_proxy()
    import os

    assert os.environ["no_proxy"].split(",") == ["corp.example", "127.0.0.1", "localhost"]
    assert set(os.environ["NO_PROXY"].split(",")) == {"127.0.0.1", "localhost"}
