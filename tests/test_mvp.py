#!/usr/bin/env python3
"""Agent-Traj-Bench v0.2-mini（MVP）的单元测试

出处：`docs-research/trajectory-platform/bench-mvp-plan.md` v1.2 §4 T0

与 phase0/phase1 的分工一致：门禁验「产物合不合格」，本文件验「逻辑对不对」——
用构造输入固定住每条**实测得来**的判定规则，防止后续改动悄悄把它们改回错的写法。

被固定的实测结论（每条都对应方案里的一段标定，或 TZ 的一次实测）：

  common  ① `tool_input` 是 Python repr 时也要能解析（§3.2）
          ② 路径映射必须严格前缀匹配，`.claude/projects/` 与跨仓路径要丢弃（§3.4）
          ③ 难度分档按 edit_ops 现算，不用 Phase 1 的 difficulty（§3.7 坑二）
          ④ reward 要从 `verifier_result.rewards.reward` 读，
             `verifier_result.reward` 恒为 None（§3.8-D + TZ 实测）
          ⑤ harbor jobs 目录必须在 $HOME 之下（TZ R-3，colima 只挂 $HOME）
          ⑥ mirror 只读访问：仓库不在名单内要抛而不是猜
  T1      ⑦ 终点 high 的判据是「末单元或下一单元起点 high」（§4 T1）
          ⑧ 条件⑤写成 in ('none','low') 必须把候选池筛成 0（§3.1 陷阱）
          ⑨ 八条筛选链的顺序固定 —— funnel 的逐条剩余数是对账依据
  T3 格式 ⑩ 生成的 task 目录要能被 harbor 的 `Task.is_valid_dir()` 认（§3.8-B）
  骨架    ⑪ 尚未实现的 T5/T7 必须以非零码退出，不许静默产出空结果
             （T2/T3/T4 已于 2026-09-08 实现，各归 ⑫-⑯ / ㉒-㉙ / ⑰-㉑ 管）
  T2      ⑫-⑯ 反解 base+patch 的五条实测判定（⑫⑯ 方案里没有）
  T4      ⑰-㉑ 快照剔除泄漏面 + 步骤④交叉验收
  T3      ㉒-㉚ 判分链路的八条实测判定，其中四条是本轮实测纠正方案的写法：
             ㉒ reward 文件名是 `reward.json`（单数）—— 方案写的复数 harbor 不读，
                且**静默降级**成读 reward.txt，f2p/p2p 两键永远不进 result.json
             ㉓㉔ junit XML 会**整份漏掉加载失败的文件**（root failures=0 却有文件没跑）
                → 判分必须核对文件覆盖，XML 缺失/空名单一律判 0 且不抛异常
             ㉕ `--3way` 前必须刷 index —— tar 解包后全库 stat-dirty（实测 1215/1215），
                不刷则 100% 报 does not match index，而纯 apply 无此问题（两层都测不出）
             ㉖ 测试保护按**路径**逐个还原，不按目录（4 条 task 的测试在 tests/ 之外；
                而 clean -fd src/ 会删掉 agent 新建的源码）
             ㉗ 每条退出路径都写 reward，先无条件覆盖为 0
             ㉘ F2P 必须在 base 上是红的，全绿即 `is_f2p:false`（nop 也能满分）
             ㉙ task.toml 要能被 harbor 的 TaskConfig 解析、题面不许为空
                （`is_valid_dir()` 只查文件存在，空题面照样报 VALID）
             ㉚ 生成的 shell 要过 `bash -n`，且含引号/空格的路径不能破语法
                （3 条 monorepo 的 test_cmd 自带带引号的正则）
          ㉛-㉝ P2P **真实产物**的对账（没跑过采样就跳过）：不与自身 patch 重叠、
                不含 T4 的两个 canary（含即证明采错了文件树）、名单不短于下限
             ㉞ F2P 只放 bun 会收集的文件（`.test.`/`.spec.`/`_test_`/`_spec_`）——
                T2 的 is_test 按用途判、bun 按文件名收集，两者不等价。实测 T0010 的
                preload 辅助文件混进 F2P 会让 bun **静默跳过**（exit 0、不进 XML）
                → f2p 恒 0 → 连 oracle 都做不出来。但它仍须留在保护名单里

用法：
    python3 -m pytest scripts/mvp/tests/test_mvp.py -v
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

MVP = Path(__file__).resolve().parent.parent
REPO_ROOT = MVP.parent.parent
sys.path.insert(0, str(MVP))

import common as c  # noqa: E402


def load_t1():
    """T1 脚本名带连字符，不能直接 import，用 spec 加载。"""
    spec = importlib.util.spec_from_file_location("t1_select", MVP / "t1-select-candidates.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── ① tool_input 双格式解析（§3.2） ────────────────────────────────


def test_parse_tool_input_json():
    assert c.parse_tool_input('{"file_path": "a.ts"}') == {"file_path": "a.ts"}


def test_parse_tool_input_python_repr():
    """§3.2：`tool_input` 可能是 Python repr —— 单引号 + False/True/None。

    只用 `json.loads` 会在这种输入上静默失败，形态是「patch 反解出来是空的」，
    完全不指向解析器。所以两个解析器都要试。
    """
    raw = "{'file_path': 'a.ts', 'replace_all': False, 'x': None, 'y': True}"
    got = c.parse_tool_input(raw)
    assert got == {"file_path": "a.ts", "replace_all": False, "x": None, "y": True}


def test_parse_tool_input_dict_passthrough():
    """T0 实测：本项目切片里 4933/4933 个 tool_input 已经是 dict，dict 是主路径。"""
    d = {"file_path": "a.ts"}
    assert c.parse_tool_input(d) is d


@pytest.mark.parametrize("bad", [None, 123, "", "not-a-dict", "[1,2,3]"])
def test_parse_tool_input_bad_returns_empty(bad):
    """解析不出来返回 {} 而不是抛 —— 单条脏数据不该让整批反解中断。"""
    assert c.parse_tool_input(bad) == {}


# ── ② 路径映射严格前缀（§3.4） ─────────────────────────────────────


def test_map_repo_path_in_repo():
    p = "/Users/zhourusheng/Code/person/sid-code/src/agent/x.ts"
    assert c.map_repo_path(p) == "src/agent/x.ts"


def test_map_repo_path_rejects_claude_projects():
    """§3.4：21 次锚点失败是路径映射粗糙导致的，其中一类是 .claude/projects/memory/。

    这条测试盯着的是**不许写 `split('sid-code/')`** —— 那种模糊切分会把下面这个
    路径也当成仓库内文件，形态是「锚点校验失败率虚高」，看着像轨迹质量差，
    实际是映射写糙了。
    """
    p = "/Users/zhourusheng/.claude/projects/memory/sid-code/notes.md"
    assert c.map_repo_path(p) is None


def test_map_repo_path_rejects_cross_repo():
    """§3.4 的另一类失败：跨仓路径混进来。指定 repo 时必须拒绝别的仓库。"""
    p = "/Users/zhourusheng/Code/ruijie/iam-studio-fe/src/x.vue"
    assert c.map_repo_path(p, repo="person/sid-code") is None
    assert c.map_repo_path(p, repo="ruijie/iam-studio-fe") == "src/x.vue"


def test_map_repo_path_repo_root_is_not_a_file():
    assert c.map_repo_path("/Users/zhourusheng/Code/person/sid-code/") is None


@pytest.mark.parametrize("bad", [None, "", 123, "relative/path.ts", "/tmp/x.ts"])
def test_map_repo_path_bad_input(bad):
    assert c.map_repo_path(bad) is None


# ── ③ 难度分档（§3.7 坑二） ────────────────────────────────────────


@pytest.mark.parametrize(
    "edit_ops,expected",
    [(0, "S"), (1, "S"), (3, "S"), (4, "M"), (10, "M"), (11, "L"), (99, "L")],
)
def test_band_boundaries(edit_ops, expected):
    """档位边界写死在代码里，报告直接引它。改了这里就要同步改报告口径。"""
    assert c.band(edit_ops) == expected


# ── ④ reward 读取路径（§3.8-D + TZ 实测） ──────────────────────────


def test_read_reward_uses_nested_rewards(tmp_path):
    """§3.8-D + TZ 实测：正确路径是 `verifier_result.rewards.reward`（嵌套 dict）。

    ⚠️ 同一份 result.json 里 `verifier_result.reward` **恒为 None** ——
    TZ 实测确认（reports/tz-preflight.md §3）。写错这个路径的形态是
    「所有 task 都 0 分 / None」**且不报错**，是 R1「绿着坏掉」的经典成因。
    这条测试就是拿一份「嵌套有值、平铺为 None」的真实形状来固定读法。
    """
    trial = tmp_path / "trial"
    trial.mkdir()
    (trial / "result.json").write_text(
        json.dumps({"verifier_result": {"reward": None, "rewards": {"reward": 1.0, "f2p": 1.0}}}),
        encoding="utf-8",
    )
    assert c.read_reward(trial) == 1.0


def test_read_reward_zero_is_not_none(tmp_path):
    """0.0 与「读不到」必须分得开 —— 混了就无法区分「真 0 分」与「路径写错」。"""
    trial = tmp_path / "trial"
    trial.mkdir()
    (trial / "result.json").write_text(json.dumps({"verifier_result": {"rewards": {"reward": 0.0}}}), encoding="utf-8")
    assert c.read_reward(trial) == 0.0


def test_read_reward_missing_returns_none(tmp_path):
    assert c.read_reward(tmp_path) is None


# ── ⑤ harbor jobs 目录必须在 $HOME 下（TZ R-3） ────────────────────


def test_assert_jobs_dir_rejects_tmp():
    """TZ R-3：本机 colima `mounts: []`，VM 内只挂了 $HOME 一个 virtiofs。

    harbor 的 docker environment 声明 `capabilities.mounted=True`
    （environments/docker/docker.py:303），于是 verifier/verifier.py:203 跳过
    download，假定 trial 目录是 bind mount。用 /tmp 时 verifier 的产出全写在
    **VM 自己的 /private/tmp**，宿主永远读不到 —— 形态是
    `RewardFileNotFoundError`，而它指向「reward 没写」这个**错误方向**。
    """
    with pytest.raises(ValueError, match="HOME"):
        c.assert_jobs_dir_ok("/tmp/harbor-runs")


def test_assert_jobs_dir_accepts_home():
    p = c.assert_jobs_dir_ok(c.MVP_REPORTS / "t5-gate")
    assert p.is_relative_to(Path.home().resolve())


def test_harbor_env_disables_telemetry():
    """TZ R-2：遥测默认**开**（`telemetry.py:45` 的 _DISABLED_VALUES 不含空串）。

    我们的 instruction.md 含私有仓库信息，必须关。"0" 在那个集合里。
    """
    assert c.HARBOR_ENV["HARBOR_TELEMETRY"] == "0"


# ── ⑥ mirror 只读访问（§3.3 / 纪律 2） ─────────────────────────────


def test_mirror_path_rejects_unknown_repo():
    """仓库不在名单内要抛，不猜路径 —— 猜出来的形态是「mirror 里没有这个 commit」。"""
    with pytest.raises(KeyError):
        c.mirror_path("person/does-not-exist")


def test_repo_mirrors_are_the_two_target_repos():
    """条件②只做这两个仓库（mirror 可用且 commit 密度够，§3.3）。"""
    assert set(c.REPO_MIRRORS) == {"person/sid-code", "ruijie/iam-studio-fe"}


# ── ⑦ 终点 high 的判据（§4 T1） ────────────────────────────────────


def _unit(sid, seq, conf="high", **kw):
    d = {"sid": sid, "seq": seq, "boundary_confidence": conf, "unit_id": f"{sid}#{seq}"}
    d.update(kw)
    return d


def test_endpoint_high_last_unit_of_session():
    """会话最后一个单元：终点就是会话结束，算 high。"""
    t1 = load_t1()
    units = [_unit("s1", 1), _unit("s1", 2)]
    by_sid = {"s1": units}
    assert t1.endpoint_is_high(by_sid, units[1]) is True


def test_endpoint_high_next_unit_low_is_rejected():
    """§4 T1：下一个单元起点 low → 本单元终点不可信。

    只看单元自己的 `boundary_confidence` 会把这种「起点 high 但尾巴被 low 边界
    切断」的单元放进来，它的 step_range 终点不可信，patch 会反解出多余改动。
    """
    t1 = load_t1()
    units = [_unit("s1", 1), _unit("s1", 2, conf="low")]
    by_sid = {"s1": units}
    assert t1.endpoint_is_high(by_sid, units[0]) is False
    assert t1.endpoint_is_high(by_sid, units[1]) is True  # 它自己是末单元


def test_endpoint_high_uses_nearest_next_not_any():
    """要看**紧邻的**下一个单元，不是「任意后继」—— seq 有空洞时也得取最小的那个。"""
    t1 = load_t1()
    units = [_unit("s1", 1), _unit("s1", 5, conf="low"), _unit("s1", 9)]
    by_sid = {"s1": units}
    assert t1.endpoint_is_high(by_sid, units[0]) is False


# ── ⑧⑨ 筛选链与陷阱（§3.1 / §4 T1） ───────────────────────────────


def _candidate_unit(**kw):
    """一条能通过全部八条筛选的单元，测试按需改单个字段让它落选。"""
    d = {
        "unit_id": "sidA#01",
        "sid": "sidA",
        "seq": 1,
        "boundary_confidence": "high",
        "repo": "person/sid-code",
        "repo_resolution": "exact",
        "edit_ops": 5,
        "n_test_cmds": 2,
        "secret_severity": "medium",  # ⚠️ 覆盖 80% 单元，不是真实泄漏
        "started_at": "2026-07-01T10:00:00",
        "category": "bug_fix",
        "instruction_len": 200,
        "instruction_clean": "修一个 bug",
        "step_range": [0, 10],
    }
    d.update(kw)
    return d


def test_select_keeps_medium_secret_severity():
    """§3.1 的陷阱本体：`medium` 是脱敏残留标记，**不能**被过滤掉。

    分布是 medium 6136 / None 1524 / high 32 —— medium 覆盖 80% 单元。
    """
    t1 = load_t1()
    kept, _ = t1.select([_candidate_unit(secret_severity="medium")])
    assert len(kept) == 1


def test_select_drops_high_secret_severity():
    t1 = load_t1()
    kept, _ = t1.select([_candidate_unit(secret_severity="high")])
    assert kept == []


def test_select_strict_secret_zeroes_the_pool():
    """§4 T1 反向自证的逻辑内核：错写法必须把候选池筛成 0。

    脚本级的自证（`--selftest-strict-secret`）验的是「主路径以非零码退出」，
    这里验的是「筛选函数本身在错写法下归零」。两层各管一段。
    """
    t1 = load_t1()
    units = [_candidate_unit(secret_severity="medium") for _ in range(5)]
    kept, funnel = t1.select(units, strict_secret=True)
    assert kept == []
    assert any(cnt == 0 for _, cnt in funnel)


@pytest.mark.parametrize(
    "field,value",
    [
        ("boundary_confidence", "low"),  # ①
        ("repo", "person/claude-trace"),  # ②不在名单
        ("repo_resolution", "unresolved"),  # ②未锚定
        ("repo_resolution", "conflict"),  # ②冲突
        ("edit_ops", 0),  # ③
        ("n_test_cmds", 0),  # ④
        ("started_at", "2026-05-31T23:59:59"),  # ⑥
        ("category", "doc_authoring"),  # ⑦
        ("instruction_len", 59),  # ⑧下界
        ("instruction_len", 1201),  # ⑧上界
    ],
)
def test_select_each_condition_rejects(field, value):
    """八条筛选链逐条都要真的起作用 —— 少任何一条都会放进不该有的候选。"""
    t1 = load_t1()
    kept, _ = t1.select([_candidate_unit(**{field: value})])
    assert kept == []


def test_select_boundary_values_are_inclusive():
    """⑧ 是闭区间 [60, 1200]，⑥ 是 >= '2026-06'。边界值必须**留下**。"""
    t1 = load_t1()
    for value in (60, 1200):
        kept, _ = t1.select([_candidate_unit(instruction_len=value)])
        assert len(kept) == 1, f"instruction_len={value} 应保留"
    kept, _ = t1.select([_candidate_unit(started_at="2026-06-01T00:00:00")])
    assert len(kept) == 1


def test_select_funnel_order_is_fixed():
    """funnel 的逐条剩余数是与 §3.1 实测值对账的依据，顺序不能变。

    ①→2937 是方案写明的锚点；调顺序会让这个数字失去可比性。
    """
    t1 = load_t1()
    _, funnel = t1.select([_candidate_unit()])
    labels = [label for label, _ in funnel]
    assert labels[0] == "全量单元"
    for i, marker in enumerate("①②③④⑤⑥⑦⑧", start=1):
        assert labels[i].startswith(marker), f"第 {i} 步应是 {marker}，实际 {labels[i]}"


def test_band_is_attached_to_rows():
    t1 = load_t1()
    rows = t1.build_rows([_candidate_unit(edit_ops=2), _candidate_unit(edit_ops=20)])
    assert [r["band"] for r in rows] == ["S", "L"]


# ── T1 真实产物的对账（跑过 T1 才有，没有就跳过） ──────────────────


@pytest.mark.skipif(not c.CANDIDATES_STATS.exists(), reason="尚未跑过 T1，无 candidates.stats.json")
def test_t1_artifact_matches_plan_anchors():
    """T1 产物要对上方案 §4 T1 的三个实测预期：①→2937、⑦→266、⑧→约 182。

    对不上不一定是代码错了 —— 也可能是 labeled-v2.jsonl 重跑过。
    但**必须有人看一眼**，所以固定成断言而不是打印。
    """
    stats = json.loads(c.CANDIDATES_STATS.read_text(encoding="utf-8"))
    funnel = {row["step"]: row["remaining"] for row in stats["funnel"]}
    step1 = next(v for k, v in funnel.items() if k.startswith("①"))
    step7 = next(v for k, v in funnel.items() if k.startswith("⑦"))
    assert step1 == 2937, f"①「两端 high」实测应为 2937，实际 {step1}"
    assert step7 == 266, f"⑦「四类」实测应为 266，实际 {step7}"
    assert stats["n_candidates"] >= 120, "候选池须 ≥120（目标交付 50，需 2 倍余量）"
    bands = stats["distributions"]["by_band"]
    for b in ("S", "M", "L"):
        assert bands.get(b, 0) >= 15, f"难度档 {b} 只有 {bands.get(b, 0)} 条，须 ≥15"


@pytest.mark.skipif(not c.CANDIDATES.exists(), reason="尚未跑过 T1")
def test_t1_candidates_rows_are_wellformed():
    rows = list(c.read_jsonl(c.CANDIDATES))
    assert rows
    for r in rows[:50]:
        assert r["repo"] in c.REPO_MIRRORS
        assert r["boundary_confidence"] == "high"
        assert r["secret_severity"] != "high"
        assert r["edit_ops"] >= 1
        assert r["band"] == c.band(r["edit_ops"])
        assert 60 <= r["instruction_len"] <= 1200


# ── ⑩ 生成的 task 目录要被 harbor 认（§3.8-B） ─────────────────────


def _write_minimal_task(task_dir: Path) -> None:
    """按 harbor 的 TaskPaths 契约写一个最小 task（§3.8-B 的官方 docstring）。"""
    (task_dir / "environment").mkdir(parents=True)
    (task_dir / "solution").mkdir()
    (task_dir / "tests").mkdir()
    (task_dir / "instruction.md").write_text("修一个 bug。\n", encoding="utf-8")
    (task_dir / "task.toml").write_text(
        'schema_version = "1.4"\n\n'
        "[metadata]\n\n"
        "[verifier]\ntimeout_sec = 900.0\n\n"
        "[agent]\ntimeout_sec = 900.0\n\n"
        "[environment]\nbuild_timeout_sec = 600.0\n",
        encoding="utf-8",
    )
    (task_dir / "environment" / "Dockerfile").write_text("FROM ubuntu:24.04\nWORKDIR /repo\n", encoding="utf-8")
    (task_dir / "solution" / "solve.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    (task_dir / "tests" / "test.sh").write_text("#!/bin/bash\n", encoding="utf-8")


#: harbor 是 `uv tool install` 装的，**自带一个 python 3.13**。
#: 不能把它的 site-packages 塞进 sys.path 来 import —— `pydantic_core` 是原生扩展，
#: 编给 3.13 的 .so 在本仓库的 venv（3.14）里加载不了，形态是
#: `No module named 'pydantic_core._pydantic_core'`，看着像 harbor 没装。
#: 所以走 subprocess，用**它自己的解释器**跑校验。
HARBOR_PYTHON = Path.home() / ".local/share/uv/tools/harbor/bin/python"


def harbor_task_is_valid(task_dir: Path) -> bool:
    """问 harbor 自己「这个目录是不是合法 task」。

    ⚠️ 用 `Task.is_valid_dir()` 而**不是** `harbor check`：后者要跑 LLM 评委
    （`--agent` 默认 claude-code），既慢又要密钥，还会因为模型心情不同而抖动，
    不能当格式门禁。前者是纯确定性校验，正是我们要的「harbor 认不认这个格式」。
    """
    if not HARBOR_PYTHON.exists():
        pytest.skip(f"未找到 harbor 自带解释器: {HARBOR_PYTHON}")
    proc = subprocess.run(
        [
            str(HARBOR_PYTHON),
            "-c",
            "import sys\n"
            "from harbor.models.task.task import Task\n"
            "print('VALID' if Task.is_valid_dir(sys.argv[1]) else 'INVALID')\n",
            str(task_dir),
        ],
        capture_output=True,
        text=True,
    )
    if "VALID" not in proc.stdout:
        pytest.fail(f"调 harbor 校验失败：\n{proc.stdout}\n{proc.stderr}")
    return "INVALID" not in proc.stdout


def test_minimal_task_dir_is_valid_for_harbor(tmp_path):
    """§3.8-B：T3 产出的目录必须被 harbor 直接认。

    v1.0 原先设计的 `task.yaml` / `gold_patch.diff` 扁平布局 harbor 认不出来 ——
    这条测试把「直接产出终态」这个决定固定住（§4 T0 验收项之一）。
    """
    task_dir = tmp_path / "T0001"
    _write_minimal_task(task_dir)
    assert harbor_task_is_valid(task_dir) is True


def test_task_dir_missing_instruction_is_invalid(tmp_path):
    """反向：缺 instruction.md 必须**不**被认 —— 否则上一条等于没验。"""
    task_dir = tmp_path / "T0002"
    _write_minimal_task(task_dir)
    (task_dir / "instruction.md").unlink()
    assert harbor_task_is_valid(task_dir) is False


def test_task_dir_missing_test_script_is_invalid(tmp_path):
    task_dir = tmp_path / "T0003"
    _write_minimal_task(task_dir)
    (task_dir / "tests" / "test.sh").unlink()
    assert harbor_task_is_valid(task_dir) is False


# ── ⑪ 未实现的骨架必须非零退出 ─────────────────────────────────────


@pytest.mark.parametrize(
    "script",
    [
        # T2 已在 2026-09-08 实现，从这张名单里移出（它现在归下面的 ⑫-⑯ 管）
        # T4 已在 2026-09-08 实现，归下面的 ⑰-㉑ 管
        # T3 已在 2026-09-08 实现，归下面的 ㉒-㉘ 管
        "t5-gate.sh",
        "t7-baseline.sh",
    ],
)
def test_unimplemented_skeletons_exit_nonzero(script):
    """T0 只交付骨架。**不许静默产出空结果** —— 那会让 T3 拿着空文件「成功」跑完。

    退出码 64（EX_USAGE）而不是 1，是为了与「实现了但失败」区分开。
    """
    path = MVP / script
    cmd = ["bash", str(path)] if path.suffix == ".sh" else [sys.executable, str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)
    assert proc.returncode != 0, f"{script} 未实现却以 0 退出"
    assert "尚未实现" in (proc.stdout + proc.stderr)


# ── 目录约定（§4 T0 四条纪律） ─────────────────────────────────────


def test_mvp_dir_is_separate_from_v01():
    """纪律 3：v0.2-mini 是新目录，不覆盖、不迁移 bench/ 下 v0.1 的 844 条。"""
    assert c.MVP_DIR.name == "v0.2-mini"
    assert c.MVP_DIR.parent.name == "bench"
    assert c.MVP_DIR != c.MVP_DIR.parent


def test_sessions_dir_is_readonly_by_convention():
    """纪律 1：`data/pulled_sessions/` 只读。

    这条没法用代码强制（Python 拦不住 open(..., 'w')），所以退一步验
    「常量指向的是那个只读湖，且本模块没有任何写它的辅助函数」——
    真正的护栏是 code review 与这条测试的存在本身。

    背景：`pull.py:246` 的去重只查 `<sid>/.pulled`，移走/改名/删除会让下次
    同步判为「未拉取」并重复下载 —— 上一轮 1722 条就是这么来的。
    """
    assert c.SESSIONS_DIR.name == "pulled_sessions"
    writers = [n for n in dir(c) if n.startswith(("write_", "move_", "delete_")) and n != "write_jsonl"]
    assert writers == [], f"common.py 不该有写原始层的辅助函数: {writers}"


def test_no_harbor_base_files_are_written():
    """纪律 4：不改 harbor 底座里的任何文件。

    `sid-code/evals/external-benchmarks/harbor/` 是它自己的资产 ——
    `registry.local.json` 是已发表结论（59 个 run）的取数源，动它等于让旧结论
    不可复算。这里验 common.py 里没有任何指向那个目录的**代码**常量。

    ⚠️ 判据必须走 AST 而不是逐行 grep：注释与 docstring 里**要**写清这条纪律
    （不写下来纪律就传不下去），逐行 grep 会把这些说明文字本身判成违规。
    要禁的是**可执行的字符串常量**，不是对它的描述。
    """
    import ast

    src = (MVP / "common.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    # 收集全部 docstring 节点的 id，遍历时跳过它们
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr):
                    docstrings.add(id(first.value))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or id(node) in docstrings:
            continue
        if isinstance(node.value, str) and "external-benchmarks" in node.value:
            pytest.fail(f"common.py 第 {node.lineno} 行有指向 harbor 底座的字符串常量: {node.value[:80]!r}")


def test_ensure_mvp_dirs_creates_only_under_v02(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "MVP_META", tmp_path / "v0.2-mini" / "meta")
    monkeypatch.setattr(c, "MVP_TASKS", tmp_path / "v0.2-mini" / "tasks")
    monkeypatch.setattr(c, "MVP_REPORTS", tmp_path / "v0.2-mini" / "reports")
    c.ensure_mvp_dirs()
    assert (tmp_path / "v0.2-mini" / "meta").is_dir()
    assert (tmp_path / "v0.2-mini" / "tasks").is_dir()
    assert (tmp_path / "v0.2-mini" / "reports").is_dir()
    assert sorted(os.listdir(tmp_path)) == ["v0.2-mini"]


# ── 真实数据的冒烟（缺数据就跳过） ─────────────────────────────────


@pytest.mark.skipif(not c.LABELED_V2.exists(), reason="无 labeled-v2.jsonl")
def test_labeled_v2_has_fields_t1_depends_on():
    """T1 依赖的字段必须都在 —— 上游改字段名时这条先红，而不是候选池悄悄变空。"""
    row = next(iter(c.read_jsonl(c.LABELED_V2)))
    for field in (
        "unit_id",
        "sid",
        "seq",
        "boundary_confidence",
        "repo",
        "repo_resolution",
        "edit_ops",
        "n_test_cmds",
        "secret_severity",
        "started_at",
        "category",
        "instruction_len",
        "step_range",
    ):
        assert field in row, f"labeled-v2 缺字段 {field}"


@pytest.mark.skipif(
    not (Path.home() / "Code/_archive/bench-mirrors/person_sid-code.git").exists(),
    reason="无 mirror 归档",
)
def test_resolve_base_commit_on_real_mirror():
    """§3.3：按时间戳反查真的能取到 commit（只查 refs/heads/main）。"""
    sha = c.resolve_base_commit("person/sid-code", "2026-07-15T10:00:00")
    assert sha and len(sha) == 40


@pytest.mark.skipif(not (c.SESSIONS_DIR).exists(), reason="无 data/pulled_sessions/")
def test_iter_traj_actions_respects_step_range():
    """`step_range` 是闭区间，且只产出带 tool_name 的 action step。"""
    sid = next(
        (
            r["sid"]
            for r in (c.read_jsonl(c.CANDIDATES) if c.CANDIDATES.exists() else [])
            if (c.SESSIONS_DIR / r["sid"] / "session.traj").exists()
        ),
        None,
    )
    if not isinstance(sid, str):
        pytest.skip("候选池里没有本地可读的 session.traj")
    steps = list(c.iter_traj_actions(sid, [0, 5]))
    assert all(0 <= i <= 5 for i, _, _ in steps)
    assert all(tn for _, tn, _ in steps)
    assert all(isinstance(ti, dict) for _, _, ti in steps)


# ══════════════════════════════════════════════════════════════════
# T2 — base_commit 反查 + patch 反解（2026-09-08 实现）
#
# 固定住 T2 实测得来的五条判定规则。每条都是**跑 182 条候选跑出来的**，
# 不是从方案抄的 —— 方案里没有 ⑫ 与 ⑯ 这两条。
# ══════════════════════════════════════════════════════════════════


def load_t2():
    """T2 脚本名带连字符，同 load_t1。"""
    spec = importlib.util.spec_from_file_location("t2_resolve", MVP / "t2-resolve-base-patch.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── ⑫ 采集当时失败的写操作必须跳过（T2 实测，方案没写） ──────────────


def test_observation_errors_maps_tool_use_id():
    """`is_error` 是从 observation step 上读的，按 `tool_use_id` 配对。"""
    traj = [
        {"message_type": "action", "tool_name": "Edit", "tool_use_id": "a"},
        {"message_type": "observation", "tool_use_id": "a", "is_error": True},
        {"message_type": "action", "tool_name": "Edit", "tool_use_id": "b"},
        {"message_type": "observation", "tool_use_id": "b", "is_error": False},
    ]
    assert c.observation_errors(traj) == {"a": True, "b": False}


def test_failed_write_ops_are_flagged_not_silently_dropped(tmp_path, monkeypatch):
    """失败的写操作要**带 `failed=True` 产出**，而不是在迭代器里悄悄消失。

    为什么不在 `iter_write_actions` 里直接跳过：T2 要把跳过的次数写进
    `resolved.jsonl`（`n_failed_ops_skipped`）留痕。静默丢弃等于让后面的人
    无法判断「这条 patch 到底缺不缺东西」。
    """
    sid = "sess-fail"
    d = tmp_path / sid
    d.mkdir()
    (d / "session.traj").write_text(
        json.dumps(
            {
                "trajectory": [
                    {"message_type": "action", "tool_name": "Edit", "tool_use_id": "t1",
                     "tool_input": {"file_path": "/x/a.ts", "old_string": "a", "new_string": "b"}},
                    {"message_type": "observation", "tool_use_id": "t1", "is_error": True,
                     "content": "<tool_use_error>String to replace not found in file.</tool_use_error>"},
                    {"message_type": "action", "tool_name": "Edit", "tool_use_id": "t2",
                     "tool_input": {"file_path": "/x/a.ts", "old_string": "c", "new_string": "d"}},
                    {"message_type": "observation", "tool_use_id": "t2", "is_error": False},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(c, "SESSIONS_DIR", tmp_path)
    got = [(tn, ti.get("old_string"), failed) for _, tn, ti, failed in c.iter_write_actions(sid)]
    assert got == [("Edit", "a", True), ("Edit", "c", False)]


def test_replaying_failed_edit_would_corrupt_patch():
    """反向自证 ⑫：把失败的 Edit 也重放，重建就会在**后一个** Edit 上崩。

    这正是实测踩到的形态 —— 它表现为「old_string 对不上」，看着像轨迹质量差或
    base 反查偏了，其实是我们重放了一次本就没生效的编辑。
    """
    t2 = load_t2()
    original = "keep\nreal\n"
    failed_edit = ("Edit", {"old_string": "ghost", "new_string": "X"})   # 采集当时就没匹配上
    good_edit = ("Edit", {"old_string": "real", "new_string": "fixed"})

    # 正确做法：跳过失败的那次
    ok, reason = t2.apply_edits(original, [good_edit])
    assert reason is None and ok == "keep\nfixed\n"

    # 错误做法：连失败的一起重放 → 立刻报 old_string_not_found
    bad, reason = t2.apply_edits(original, [failed_edit, good_edit])
    assert bad is None and reason == "old_string_not_found"


# ── ⑬ 重建失败要淘汰整条候选，不许「尽力而为」 ─────────────────────


def test_apply_edits_aborts_instead_of_skipping_bad_edit():
    """一个 Edit 对不上，后续 Edit 的上下文就都不可信了 —— 必须整条淘汰。

    「跳过这一个、继续应用后面的」会产出一份**看着像** gold patch、
    实际错位的 diff。这是 §3.8-F「绿着坏掉」那一类，宁可淘汰。
    """
    t2 = load_t2()
    seq = [
        ("Edit", {"old_string": "nope", "new_string": "X"}),
        ("Edit", {"old_string": "line", "new_string": "Y"}),
    ]
    out, reason = t2.apply_edits("line\n", seq)
    assert out is None
    assert reason == "old_string_not_found"


def test_apply_edits_write_replaces_whole_file():
    t2 = load_t2()
    out, reason = t2.apply_edits("old\n", [("Write", {"content": "brand new\n"})])
    assert reason is None and out == "brand new\n"


def test_apply_edits_replace_all_semantics():
    """`replace_all` 决定替换次数，默认只替第一处。"""
    t2 = load_t2()
    once, _ = t2.apply_edits("a a a\n", [("Edit", {"old_string": "a", "new_string": "b"})])
    assert once == "b a a\n"
    allof, _ = t2.apply_edits(
        "a a a\n", [("Edit", {"old_string": "a", "new_string": "b", "replace_all": True})]
    )
    assert allof == "b b b\n"


def test_phantom_file_is_named_distinctly():
    """base 里没有、且首个 Edit 带非空 old_string → `phantom_file`。

    实测 122 例：开发者工作区里有、但从未进 main（分支未合 78 / 只在别的 ref 36 /
    base 之后才合入 8）。它与 `old_string_not_found` 分开命名，是因为**根因不同**：
    前者是仓库历史的问题，后者是重建逻辑或 base 反查的问题。混成一个名字，
    T6 人工过目时就没法判断该去查哪边。
    """
    t2 = load_t2()
    out, reason = t2.apply_edits(None, [("Edit", {"old_string": "x", "new_string": "y"})])
    assert out is None and reason == "phantom_file"


def test_new_file_via_empty_old_string_succeeds():
    """空 `old_string` = 新建文件的整体写入，不算 phantom。"""
    t2 = load_t2()
    out, reason = t2.apply_edits(None, [("Edit", {"old_string": "", "new_string": "hello\n"})])
    assert reason is None and out == "hello\n"


# ── ⑭ 文档必须从 code patch 剔除（§3.7 坑一） ──────────────────────


@pytest.mark.parametrize(
    "rel,expected",
    [
        ("docs/bugfixes/todo/20260807-遥测落盘恒空.md", True),
        ("README.md", True),
        ("packages/core/README.md", True),
        ("src/app.ts", False),
        ("tests/permission/mode.test.ts", False),
    ],
)
def test_is_doc(rel, expected):
    """`docs/bugfixes/*.md` 直接写明根因与修复方案 —— 留在 patch 里就是答案泄漏。"""
    assert load_t2().is_doc(rel) is expected


# ── ⑮ 路径映射的往返不变式（反向自证的观测点） ─────────────────────


def test_roundtrip_holds_for_strict_mapping():
    """严格映射下 `前缀 + 相对路径 == 原绝对路径` 恒成立（182 条实测 0 违反）。"""
    t2 = load_t2()
    abs_path = "/Users/zhourusheng/Code/person/sid-code/src/app.ts"
    rel = c.map_repo_path(abs_path, "person/sid-code")
    assert rel == "src/app.ts"
    assert t2.roundtrip_ok(abs_path, rel, "person/sid-code") is True


def test_roundtrip_breaks_for_fuzzy_mapping():
    """反向自证 ⑮：模糊切分把 `.claude/projects/.../memory/MEMORY.md`
    切成仓库内的 `memory/MEMORY.md`，往返不变式立刻破。

    这就是 §3.4 那 21 条锚点失败的来源，也是 `--selftest-fuzzy-path` 的原理。
    """
    t2 = load_t2()
    leaky = (
        "/Users/zhourusheng/.claude/projects/"
        "-Users-zhourusheng-Code-person-sid-code/memory/MEMORY.md"
    )
    assert c.map_repo_path(leaky, "person/sid-code") is None      # 严格映射丢弃
    fuzzy = t2.fuzzy_map_repo_path(leaky, "person/sid-code")
    assert fuzzy == "memory/MEMORY.md"                            # 模糊切分放进来了
    assert t2.roundtrip_ok(leaky, fuzzy, "person/sid-code") is False   # 守卫抓住


def test_selftest_fuzzy_path_reds_out():
    """`--selftest-fuzzy-path` 必须以退出码 3 报红，且真的列出泄漏路径。

    自证的对象是**主路径上的守卫**（注入 path_mapper），不是另写一段只验自己的
    分支 —— 沿用 T1 `--selftest-strict-secret` 的做法。
    """
    proc = subprocess.run(
        [sys.executable, str(MVP / "t2-resolve-base-patch.py"), "--selftest-fuzzy-path", "--limit", "40"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 3, f"期望退出码 3，实得 {proc.returncode}"
    assert "泄漏守卫生效" in proc.stderr
    assert ".claude/projects" in proc.stderr


# ── ⑯ 「在仓库目录下」≠「是仓库内容」（T2 实测，方案没写） ────────────


def test_dropped_path_classification_distinguishes_worktree():
    """三类被丢弃的路径**后果不同**，不能都当无害。

    - `out_of_scope`：`~/.claude/projects/*/memory/*.md` → 真不是仓库内容，丢掉无损
    - `same_repo_worktree`：同仓 worktree 的真代码 → patch 缺一块，该淘汰
    - `cross_repo`：另一个目标仓库 → 混仓单元，该淘汰
    """
    t2 = load_t2()
    assert t2.classify_dropped("/tmp/scratch.ts", "person/sid-code") == "out_of_scope"
    assert (
        t2.classify_dropped(
            "/Users/zhourusheng/Code/person/sid-code-worktrees/obs/packages/x.ts", "person/sid-code"
        )
        == "same_repo_worktree"
    )
    assert (
        t2.classify_dropped(
            "/Users/zhourusheng/Code/ruijie/iam-studio-fe/src/x.ts", "person/sid-code"
        )
        == "cross_repo"
    )


def test_gitignored_uses_base_gitignore_not_head():
    """`.claude/worktrees/...` **通过了**严格前缀映射，只有 `.gitignore` 能拦住它。

    实测抓到的真实泄漏：它确实在 `/Code/person/sid-code/` 下面（所以前缀映射放行、
    往返不变式也成立），但那是 git worktree —— 另一个分支的临时检出。本仓
    `.gitignore` 用 `.claude/*` fail-closed 挡住了它。12 条候选、214 次写操作命中。

    判据用 `git check-ignore` 而不是自己写 pattern：`.claude/*` 配 `!.claude/skills/`
    的否定放行、目录不下降、`**` 与前导 `/` 的差别，自己实现一定漏。
    这里就验它认得那条否定规则。
    """
    t2 = load_t2()
    repo = "person/sid-code"
    base = c.resolve_base_commit(repo, "2026-09-01T00:00:00")
    assert base, "mirror 里应能反查到 base"
    ignored = t2.gitignored(
        repo,
        base,
        [
            ".claude/worktrees/fix-lsp/packages/core/tests/lsp/client.test.ts",
            ".claude/skills/eval-session/SKILL.md",
            "src/app.ts",
        ],
    )
    assert ".claude/worktrees/fix-lsp/packages/core/tests/lsp/client.test.ts" in ignored
    assert ".claude/skills/eval-session/SKILL.md" not in ignored, "skills/ 是仓库资产，被否定规则放行"
    assert "src/app.ts" not in ignored


# ── ⑰-㉑ T4：快照剔除泄漏面 + 步骤④交叉验收（2026-09-08 实现） ──────


def load_t4():
    spec = importlib.util.spec_from_file_location("t4_env", MVP / "t4-build-env.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_t4_strip_uses_removeprefix_not_lstrip():
    """⑰ `.claude/` 必须被剔掉 —— `lstrip('./')` 会把它啃成 `claude/` 导致漏剔。

    这是实现过程中真实中过的一枪，由**容器内泄漏扫描**抓出来：
    `'.claude/x'.lstrip('./')` → `'claude/x'`（字符集剥离，不是前缀剥离），
    于是 `.claude/` 前缀整个失效、泄漏面静默存活。
    """
    t4 = load_t4()
    assert t4.strip_leaks(".claude/skills/eval-session/SKILL.md")
    assert t4.strip_leaks("./.claude/skills/eval-session/SKILL.md")
    # 反证：错的写法（lstrip）会漏，固定住这个差异
    assert ".claude/x".lstrip("./") == "claude/x"
    assert ".claude/x".removeprefix("./") == ".claude/x"


def test_t4_strip_is_top_level_anchored():
    """⑱ 剔除必须顶层锚定 —— 嵌套的 skill `evals/` 是真实仓库资产，不能剔。

    实测：`packages/core/src/skill/builtin/*/evals/` 下 61 个文件是 skill 的
    baseline case，且 `tests/skill/code-review.test.ts:66` 明确断言该目录存在。
    按子串剔 `evals` 会打断这些**存活测试**。
    """
    t4 = load_t4()
    assert t4.strip_leaks("evals/_judge/calibration-set/summary.md")
    assert not t4.strip_leaks("packages/core/src/skill/builtin/code-review/evals/case_cr_001.yaml")
    assert not t4.strip_leaks("src/skill/builtin/ci-self-heal/evals/case_csh_001.yaml")
    assert not t4.strip_leaks("evals-foo/bar.ts"), "尾 / 是契约，别让 evals 误命中 evals-foo/"


def test_t4_leak_files_are_file_granular():
    """⑲ 评测工作流按**文件**剔，不能整剔 `.github/` —— 同目录有无关资产。

    这四个是容器内扫描抓出来的漏网（前缀清单只锚顶层目录，抓不到散落在
    `.github/workflows/` 下的评测工作流）。而 `ci.yml` / `docs-lint.yml`
    是无关资产，整剔 `.github/` 会连它们一起丢。
    """
    t4 = load_t4()
    assert t4.strip_leaks(".github/workflows/judge-calibration.yml")
    assert t4.strip_leaks(".github/workflows/eval-weekly.yml")
    assert not t4.strip_leaks(".github/workflows/ci.yml")
    assert not t4.strip_leaks(".github/workflows/docs-lint.yml")


def test_t4_eval_framework_mode_distinguishes_two_mechanisms():
    """⑳ `file:` 与 `workspace:` 必须分开判 —— 混为一谈会白淘汰 47 条 task。

    实测推翻了方案 §3.8-E 的假设：47 条 base 把 eval-framework 声明成
    `file:../eval-framework`（**仓库外**），`bun install` 在**未剔除的对照镜像**上
    同样失败 —— 那是既有问题，与剔除无关。只有 3 条 monorepo base 的
    `workspace:*` 才真被剔除打断。
    """
    t4 = load_t4()
    repo = "person/sid-code"
    # 2026-07 的 base：file:../eval-framework
    assert t4.eval_framework_mode(repo, "9b5706c047921c0de089f0ca6a9fc4a931e50ce5") == "external"
    # monorepo base：workspace:*
    assert t4.eval_framework_mode(repo, "16cb147266b9131896460972aba3f6b873ac8f48") == "workspace"


def test_t4_cross_verify_catches_patch_touching_stripped_path():
    """㉑ 步骤④必须抓出「patch 触及被剔除路径」——这正是两层各自都绿的破口。

    T2 在 mirror 真实 commit 上验 apply --check，T4 的快照剔过泄漏路径。
    patch 若触及被剔的路径，两处验收都通过而容器里必然失败（§4.9 衔接②）。
    这里注入一条必中的前缀，守卫必须报红 —— 防止步骤④退化成空转。
    """
    t4 = load_t4()
    rows = [r for r in c.read_jsonl(c.RESOLVED) if r.get("ok") and r["repo"] != t4.IAM_REPO]
    assert rows, "T2 应已交付 ok 候选"
    row = rows[0]
    mode = t4.eval_framework_mode(row["repo"], row["base_commit"])
    gz, _ = t4.build_snapshot(row["repo"], row["base_commit"], mode)
    assert t4.cross_verify(gz, row)["cross_ok"], "正常路径下步骤④应通过"

    # 注入：把 patch 必然触及的 src/ 也当泄漏面 → 守卫必须报红
    keep = t4.LEAK_PREFIXES
    try:
        t4.LEAK_PREFIXES = keep + ("src/", "tests/")
        res = t4.cross_verify(gz, row)
        assert not res["cross_ok"], "步骤④是空转：patch 触及被剔路径却仍报绿"
        assert "被剔除路径" in (res["cross_fail_reason"] or "")
    finally:
        t4.LEAK_PREFIXES = keep


# ── ㉒-㉗ T3：harbor task 生成（2026-09-08 实现） ────────────────────


def code_lines(script: str) -> str:
    """剥掉 shell/python 的注释行**与 python docstring**，只留可执行部分。

    生成的 `test.sh` 与 `score.py` 的注释与 docstring 里**大量在讲「不要写成 X」**
    （`rewards.json`、`git clean -fd src/`…）。整文串查会命中这些解释文字，
    让「禁止出现 X」的断言恒假 —— 第一版三条断言就是这么误报的。

    ⚠️ 只剥 `#` 行还不够：`score.py` 的模块 docstring 是 `\"\"\"` 块，
    里面整段在解释「harbor 没有 rewards.json 这个名字」。第二版又中了一次。
    """
    out: list[str] = []
    in_doc = False
    for ln in script.splitlines():
        fence = ln.count('"""')
        if in_doc:
            if fence:
                in_doc = False
            continue
        if ln.lstrip().startswith("#"):
            continue
        if fence == 1:  # docstring 起始（成对出现在同一行的不算）
            in_doc = True
            continue
        out.append(ln)
    return "\n".join(out)


def load_t3():
    spec = importlib.util.spec_from_file_location("t3_build", MVP / "t3-build-harbor-tasks.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_t3_p2p():
    spec = importlib.util.spec_from_file_location("t3_p2p", MVP / "t3-sample-p2p.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_t3_reward_file_is_singular_reward_json():
    """㉒ reward 文件名必须是 `reward.json`（单数）—— 方案写的复数 harbor 不读。

    核 harbor 源码 `models/trial/paths.py`：`reward_json_path = verifier_dir / "reward.json"`。
    写成 `rewards.json` 的后果**不是报错而是静默降级** —— harbor 退回读 `reward.txt`
    （单值），`f2p` / `p2p` 两个键永远不进 result.json，门禁退化成单值判定（§3.8-D）。
    """
    t3 = load_t3()
    score = t3.score_py()
    assert '"reward.json"' in score or "'reward.json'" in score
    # 反向：不许出现复数名（那个名字 harbor 永远不会读）。
    # ⚠️ 只查**可执行行**：两个脚本的注释里都在讲「不要写 rewards.json」这件事，
    # 整文串查会命中解释文字本身（第一版就这么误报的）。
    assert "rewards.json" not in code_lines(score)
    test = t3.test_sh("T0001", ["a.test.ts"], ["b.test.ts"], [], [], "bun test")
    assert "rewards.json" not in code_lines(test)


def test_t3_score_py_requires_file_coverage_not_just_failures():
    """㉓ 判分必须核对**文件覆盖**，不能只读 failures —— junit 会整份漏掉加载失败的文件。

    实测形态：`bun test --reporter=junit good.test.ts loadfail.test.ts` 的 XML 根节点是
    `tests="6" failures="0"`（看着全绿），日志却是 `6 pass / 1 fail / 1 error`。
    加载失败的文件不生成 `<testsuite>` 节点，从 XML 里整个消失。
    只读 failures 会把「测试根本没跑起来」判成满分 —— R1「绿着坏掉」的一个新形态。
    """
    src = t3 = load_t3().score_py()
    assert "def side_score" in src
    assert "missing" in src, "必须记录哪些文件没出现在 XML 里"
    assert "no_tests" in src, "零用例的文件不构成回归保护，必须单独标记"
    del t3


def _run_side_score(tmp_path, xml_text: str | None, required: list[str]):
    """在临时目录里跑 score.py 的 side_score 逻辑（改写 VERIFIER_DIR 后 exec）。"""
    t3 = load_t3()
    src = t3.score_py()
    src = src.replace('VERIFIER_DIR = Path("/logs/verifier")', f'VERIFIER_DIR = Path(r"{tmp_path}")')
    src = src.replace('F2P_FILES = json.loads(Path("/tests/f2p.json").read_text())', "F2P_FILES = []")
    src = src.replace('P2P_FILES = json.loads(Path("/tests/p2p.json").read_text())', "P2P_FILES = []")
    if xml_text is not None:
        (tmp_path / "x.xml").write_text(xml_text, encoding="utf-8")
    ns: dict = {}
    exec(compile(src, "score.py", "exec"), ns)
    return ns["side_score"]("x.xml", required)


def test_t3_score_py_scores_zero_when_file_silently_missing_from_xml(tmp_path):
    """㉓' 同上，行为验证：XML 全绿但少一个文件 → 必须判 0，不许给满分。

    这是本轮实测抓到的真实形态（见 t3-sample-p2p.py docstring），
    构造成单测钉住：XML 里只有 good，required 里还有 loadfail。
    """
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<testsuites name="bun test" tests="6" failures="0">\n'
        '  <testsuite name="good" file="tests/good.test.ts" tests="6" failures="0"/>\n'
        "</testsuites>\n"
    )
    score, detail = _run_side_score(tmp_path, xml, ["tests/good.test.ts", "tests/loadfail.test.ts"])
    assert score == 0.0, "加载失败的文件从 XML 消失，却给了满分 —— 判分是坏的"
    assert detail["missing"] == ["tests/loadfail.test.ts"]


def test_t3_score_py_zero_when_xml_missing_and_does_not_raise(tmp_path):
    """㉔ XML 不存在 → 判 0 且**不抛异常**（规则1：每条路径都要写 reward）。

    实测：只跑一个加载失败的文件时，bun **连 XML 都不写**，这条路径真实会走到。
    抛异常的形态是 trial error，会被误读成基础设施坏了而不是 task 没过。
    """
    score, detail = _run_side_score(tmp_path, None, ["tests/x.test.ts"])
    assert score == 0.0
    assert detail["error"] == "xml_missing"


def test_t3_score_py_empty_file_list_is_not_full_marks(tmp_path):
    """㉔' 空名单必须判 0 —— 那是「没有判据」，不是「通过了」。

    若空名单给满分，一条采不到 P2P 的 task 会拿着 p2p=1 混过 T5 的门禁。
    """
    xml = '<?xml version="1.0"?>\n<testsuites tests="0" failures="0"></testsuites>\n'
    score, detail = _run_side_score(tmp_path, xml, [])
    assert score == 0.0
    assert detail["error"] == "empty_file_list"


def test_t3_refreshes_git_index_before_3way_apply():
    """㉕ `--3way` 前必须 `git update-index --refresh` —— 否则 100% 报 does not match index。

    T4 的镜像用 `tar -xzf` 解包再 `git add -A` + commit，解出的文件 mtime 与 index
    不一致：实测 `git diff-files | wc -l` = **1215**（快照里每个文件都 stat-dirty），
    刷新后归 0。`--3way` 要查 index 做三方合并，stat-dirty 就拒绝动手；
    纯 `git apply` 只碰工作区，所以 T2/T4 的 `apply --check` 全过、发现不了。

    形态很危险：oracle 的 `solve.sh` 失败 → 代码没改 → `test.sh` 照样跑完给分，
    看着像「参考解不对」而不是「patch 根本没打上」。
    """
    t3 = load_t3()
    solve = t3.solve_sh()
    assert "update-index" in solve, "solve.sh 缺 index 刷新，--3way 必报 does not match index"
    assert solve.index("update-index") < solve.index("git apply"), "刷新必须在 apply 之前"
    test = t3.test_sh("T0001", ["a.test.ts"], ["b.test.ts"], [], [], "bun test")
    assert "update-index" in test, "test.sh 打 test_patch 前也要刷 index"
    assert test.index("update-index") < test.index("git apply"), "刷新必须在 apply 之前"


def test_t3_test_protection_is_per_path_not_per_directory():
    """㉖ 测试保护必须按**路径**还原，不能 `git clean -fd tests/`。

    两个理由，都是实测数据：
      ① 65 条 task 里 **4 条的测试文件不在 `tests/` 下**（src/ 3 个 + packages/ 2 个）
         —— 只还原 tests/ 会漏掉它们。
      ② 而把范围扩到 `git clean -fd src/` 更糟：**会删掉 agent 新建的源码文件**，
         即删掉它的解答本体，形态是「agent 明明写了代码却判 0」。
    """
    t3 = load_t3()
    test = t3.test_sh(
        "T0001",
        ["src/ui/x.test.ts"],
        ["tests/b.test.ts"],
        restore=["tests/b.test.ts"],
        remove=["src/ui/x.test.ts"],
        test_cmd="bun test",
    )
    # 只查可执行行：注释里正在解释「为什么不能这么写」，整文串查会命中解释文字
    body = code_lines(test)
    assert "git clean -fd tests/" not in body, "按目录 clean 会漏掉 tests/ 之外的 11 个测试文件"
    assert "git clean -fd src/" not in body, "clean src/ 会删掉 agent 新建的源码（它的解答本体）"
    assert "git checkout -- 'tests/b.test.ts'" in test
    assert "rm -f 'src/ui/x.test.ts'" in test


def test_t3_test_sh_writes_reward_on_every_path():
    """㉗ 规则1+2：每条退出路径都写 reward，且开头先无条件覆盖为 0。

    「文件已存在就不写」的分支等于让 agent 自己往 reward 里写个 1。
    apply 失败那条路径必须 `exit 0`（要 reward=0，不要 trial error）。
    """
    t3 = load_t3()
    test = t3.test_sh("T0001", ["a.test.ts"], ["b.test.ts"], [], [], "bun test")
    head = test.split("cd /repo")[0]
    assert "echo 0 > /logs/verifier/reward.txt" in head, "必须先无条件覆盖为 0"
    assert "reward.json" in head, "reward.json 也要先落一个 0，否则 harbor 可能读到 agent 写的"
    assert "if [ ! -f" not in test, "不许有「文件已存在就不写」的分支"
    # ⚠️ 按 "\nfi" 切，不能按 "fi" —— 后者会先命中 "/logs/verifier" 里的 fi，
    # 把分支截断成 '" >> /logs/veri'，断言随即误报（第一版就中了这一枪）
    apply_branch = test.split("TEST_PATCH_APPLY_FAILED")[1].split("\nfi")[0]
    assert "exit 0" in apply_branch, "apply 失败要 reward=0 而不是 trial error"
    assert '"f2p":0.0' in apply_branch and '"p2p":0.0' in apply_branch


def test_t3_f2p_precheck_treats_green_at_base_as_not_f2p():
    """㉘ F2P 自检的判据：不改代码时**必须红**，全绿即 `is_f2p=False`。

    实测 T0001（`test_authoring`）在 base 上就 14 pass / 0 fail —— 它的新测试测的是
    已有行为，于是 `nop`（空 patch）也能满分，oracle 与 nop 的分无法区分。
    这条判据放在采 P2P 时做，因为那时容器本来就活着；留给 T5 要重建 50 个镜像（约 2.5h）。
    """
    p2p = load_t3_p2p()
    # 纯函数部分：parse_green 的三条判据（出现 + 无失败 + 有用例）
    assert callable(p2p.f2p_precheck)
    assert p2p.P2P_MIN == 20 and p2p.P2P_MAX == 30, "口径②：20-30 个文件"
    assert p2p.P2P_MARGIN > 0, "复跑要留余量，否则 flaky 踢掉几个就跌破下限"


def test_t3_parse_green_requires_file_to_appear_in_xml(tmp_path):
    """㉘' 采样侧同一条判据：加载失败的文件不在 XML 里，不许被当成绿。

    采样侧误判为绿的后果是它进了 P2P 名单 → 容器里恒败 → reward 全 0，
    形态像「task 太难」。与判分侧是同一个坑的两个面。
    """
    p2p = load_t3_p2p()
    xml = tmp_path / "g.xml"
    xml.write_text(
        '<?xml version="1.0"?>\n<testsuites tests="6" failures="0">\n'
        '  <testsuite file="tests/good.test.ts" tests="6" failures="0"/>\n'
        '  <testsuite file="tests/empty.test.ts" tests="0" failures="0"/>\n'
        "</testsuites>\n",
        encoding="utf-8",
    )
    green, _ = p2p.parse_green(xml)
    assert "tests/good.test.ts" in green
    assert "tests/empty.test.ts" not in green, "零用例不构成回归保护"
    assert "tests/loadfail.test.ts" not in green, "没出现在 XML 里的文件不许当绿"
    # XML 不存在 → 空绿名单而不是异常
    green2, summary2 = p2p.parse_green(tmp_path / "nope.xml")
    assert green2 == {} and summary2.get("xml_missing") is True


def test_t3_generated_task_toml_parses_as_harbor_config():
    """㉙ 生成的 `task.toml` 必须能被 harbor 的 `TaskConfig` **解析**，不只是目录合法。

    `Task.is_valid_dir()` 只查文件存在与否 —— 它对 `task.toml` 的**内容**一无所知。
    实测过一次同源的教训：题面写空了、`is_valid_dir` 照样报 VALID（见 instruction_md）。
    所以这里让 harbor 自己把 toml 喂进 pydantic，schema 不合会直接抛。

    顺带钉住三个 timeout 都显式落到了配置里（对应 R2 双层超时互掩）。
    """
    if not HARBOR_PYTHON.exists():
        pytest.skip(f"未找到 harbor 自带解释器: {HARBOR_PYTHON}")
    task_dirs = sorted(p for p in c.MVP_TASKS.glob("T*") if (p / "task.toml").exists())
    if not task_dirs:
        pytest.skip("T3 还没生成任何 task（需要先跑 t3-sample-p2p.py + t3-build-harbor-tasks.py）")
    proc = subprocess.run(
        [
            str(HARBOR_PYTHON),
            "-c",
            "import sys, tomllib, json\n"
            "from pathlib import Path\n"
            "from harbor.models.task.config import TaskConfig\n"
            "out = []\n"
            "for d in sys.argv[1:]:\n"
            "    cfg = TaskConfig.model_validate(tomllib.loads((Path(d)/'task.toml').read_text()))\n"
            "    out.append([cfg.schema_version, cfg.agent.timeout_sec,\n"
            "                cfg.verifier.timeout_sec, cfg.environment.build_timeout_sec,\n"
            "                sorted(cfg.metadata)])\n"
            "print(json.dumps(out))\n",
            *[str(p) for p in task_dirs],
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"harbor 解析 task.toml 失败：\n{proc.stdout}\n{proc.stderr[-1500:]}"
    rows = json.loads(proc.stdout)
    assert len(rows) == len(task_dirs)
    for schema, agent_t, verifier_t, build_t, meta_keys in rows:
        assert schema == "1.4"
        # 三个 timeout 一个都不能是 None —— 只设一层时外层先杀会掩盖内层真实超时
        assert agent_t and verifier_t and build_t
        assert "base_commit" in meta_keys and "task_id" in meta_keys


def test_t3_generated_tasks_have_nonempty_instruction():
    """㉙' 已生成的 task 题面**不许为空** —— 空题面不会被任何格式校验抓到。

    第一版就写空过 65 条：`instruction_clean` 只在 `candidates.jsonl` 里，
    从 `resolved.jsonl` 取会得到 None，而 `is_valid_dir()` 仍报 VALID。
    形态是「agent 拿到一道没题目的题，全批 reward=0，看着像 task 太难」。
    """
    task_dirs = sorted(p for p in c.MVP_TASKS.glob("T*") if (p / "instruction.md").exists())
    if not task_dirs:
        pytest.skip("T3 还没生成任何 task")
    for d in task_dirs:
        text = (d / "instruction.md").read_text(encoding="utf-8")
        body = text.split("## 环境事实")[0].strip()
        assert body, f"{d.name} 的题面是空的（只剩环境事实段）"
        assert len(body) >= 10, f"{d.name} 的题面只有 {len(body)} 字，疑似截断：{body!r}"


def test_t3_generated_shell_is_syntactically_valid_and_quote_safe():
    """㉚ 生成的 `test.sh` / `solve.sh` 必须过 `bash -n`，且路径里的引号不能破语法。

    两个真实风险点：
      ① 3 条 monorepo base 的 `test_cmd` 自带**带引号的正则**
         （`bun test --test-name-pattern '^(?!.*\\[slow\\])'`），它被原样插进脚本。
      ② 测试路径来自仓库。虽然实测没有含单引号的路径，但生成器**不该假定**输入干净 ——
         `sh_single_quote()` 就是为此存在的，这里注入一个含单引号的路径验证它。

    语法错的形态是 `test.sh` 一进容器就崩 → reward 文件只剩开头那个 0 → 全批 0 分。
    """
    t3 = load_t3()
    cases = [
        ("bun test", ["tests/a.test.ts"]),
        # monorepo 的真实命令，含单引号包裹的 negative-lookahead 正则
        ("bun test --test-name-pattern '^(?!.*\\[slow\\])'", ["tests/b.test.ts"]),
    ]
    # 故意注入含单引号的路径：POSIX 转义没写对的话 bash -n 会直接报错
    nasty = ["tests/it's-here.test.ts", 'tests/say-"hi".test.ts', "tests/a b.test.ts"]
    for test_cmd, f2p in cases:
        sh = t3.test_sh("T0001", f2p, nasty, restore=f2p + nasty, remove=nasty, test_cmd=test_cmd)
        proc = subprocess.run(["bash", "-n"], input=sh, capture_output=True, text=True)
        assert proc.returncode == 0, f"test.sh 语法错（cmd={test_cmd}）：{proc.stderr[:300]}"
    proc = subprocess.run(["bash", "-n"], input=t3.solve_sh(), capture_output=True, text=True)
    assert proc.returncode == 0, f"solve.sh 语法错：{proc.stderr[:300]}"
    # score.py 必须是合法 python
    compile(t3.score_py(), "score.py", "exec")


# ── P2P 真实产物的对账（跑过 t3-sample-p2p.py 才有，没有就跳过） ─────


def _p2p_rows():
    path = c.MVP_META / "p2p.jsonl"
    if not path.exists():
        pytest.skip("还没跑 t3-sample-p2p.py（要起容器，几十分钟）")
    rows = list(c.read_jsonl(path))
    if not rows:
        pytest.skip("p2p.jsonl 是空的")
    return rows


def test_t3_p2p_never_overlaps_the_tasks_own_patched_files():
    """㉛ P2P 名单不许包含该 task 自己 patch 触及的文件。

    重叠的后果：同一个文件既当 F2P（要求打完 patch 才过）又当 P2P（要求 base 上就过），
    两个要求互相矛盾 —— 而矛盾会以「P2P 恒败」的形式出现，看着像 task 太难。
    """
    snaps = {r["task_id"]: r for r in c.read_jsonl(c.MVP_META / "snapshots.jsonl") if r.get("ok")}
    resolved = {r["unit_id"]: r for r in c.read_jsonl(c.RESOLVED) if r.get("ok")}
    n = 0
    for rec in _p2p_rows():
        for tid, p2p in (rec.get("p2p") or {}).items():
            touched = set(resolved[snaps[tid]["unit_id"]]["files"])
            overlap = touched & set(p2p)
            assert not overlap, f"{tid} 的 P2P 与自己 patch 触及的文件重叠：{overlap}"
            n += 1
    assert n, "p2p.jsonl 里没有任何 task 的名单"


def test_t3_p2p_excludes_the_t4_canary_files():
    """㉜ T4 交接的两个 canary 不许进 P2P —— 它们在，就说明采样跑在了错的文件树上。

    `tests/skill/{incident-rca,security-audit}.test.ts` 断言被剔除的 runner 落盘存在
    （`t4-env.md` §9.2）。在剔除后的快照上采样会自然排除它们，所以它们出现即证明
    **采到了未剔除的文件树** → P2P 恒败 → 全批 reward=0，形态像「task 太难」。
    """
    canary = {"tests/skill/incident-rca.test.ts", "tests/skill/security-audit.test.ts"}
    for rec in _p2p_rows():
        assert not rec.get("canary_leaked"), f"{rec['base_commit'][:8]} canary 泄漏"
        for tid, p2p in (rec.get("p2p") or {}).items():
            leak = canary & set(p2p)
            assert not leak, f"{tid} 采到了被剔除的测试 {leak} —— 采样跑在了错的文件树上"


def test_t3_p2p_lists_meet_the_size_floor():
    """㉝ 达标 base 的每条 task 的 P2P 名单不少于下限（口径②：20-30 个文件）。

    名单过短会让「防回归」这层保护形同虚设；空名单更糟 —— `score.py` 对空名单判 0
    （见 ㉔'），但那时形态是「所有 task 的 p2p 都是 0」，容易被误读成判分坏了。
    """
    p2p_mod = load_t3_p2p()
    for rec in _p2p_rows():
        if not rec.get("ok"):
            continue
        for tid, lst in (rec.get("p2p") or {}).items():
            assert len(lst) >= p2p_mod.P2P_MIN, f"{tid} 的 P2P 只有 {len(lst)} 个"
            assert len(lst) == len(set(lst)), f"{tid} 的 P2P 名单有重复"


def test_t3_f2p_only_contains_files_bun_will_collect():
    """㉞ F2P 只许放 bun 会收集的文件；辅助文件要排除，但**仍须受保护**。

    T2 的 `is_test` 是**按用途**判的（`tests/` 下、随 test_patch 进来），
    bun 是**按文件名**收集的（`.test.` / `.spec.` / `_test_` / `_spec_`）。两者不等价，
    实测撞到真实反例 —— T0010 的 `tests/preload-isolate-sid-home.ts`（preload 辅助）：

        单独跑它         → 报 `Tests need ".test" ... in the filename`，**连 XML 都不写**
        与正常测试一起跑 → **exit 0**、日志不提它、它从 XML 里**整个消失**

    第二种致命：bun 不报错也不非零退出，`score.py` 的文件覆盖核对会判它 missing →
    f2p=0 → **连 oracle 都做不出来**，形态是「参考解也拿 0 分」，
    会被误诊成 T2 的 patch 反解错了。

    ⚠️ 反向要求同样重要：这类文件随 test_patch 落地、agent 能改它，
    所以它**必须留在 restore/remove 保护名单里**，只是不进 `bun test` 的参数。
    """
    t3 = load_t3()
    assert t3.is_bun_test_file("tests/a.test.ts")
    assert t3.is_bun_test_file("tests/a.spec.tsx")
    assert t3.is_bun_test_file("tests/_test_helper.ts")
    # 真实反例：用途是测试相关，但 bun 不收集
    assert not t3.is_bun_test_file("tests/preload-isolate-sid-home.ts")
    assert not t3.is_bun_test_file("tests/helpers/setup.ts")
    # 目录名里带 .test. 不算 —— bun 看的是**文件名**
    assert not t3.is_bun_test_file("tests/x.test.dir/helper.ts")


def test_t3_generated_meta_keeps_helper_protected_but_out_of_f2p():
    """㉞' 行为验证：已生成的 task 里，被排除的辅助文件必须仍在保护名单中。

    只做「排除」不做「保护」的话，agent 改掉 preload 辅助文件就能影响同进程后续测试，
    而没有任何机制会还原它。
    """
    metas = sorted(c.MVP_TASKS.glob("T*/meta.json"))
    if not metas:
        pytest.skip("T3 还没生成任何 task")
    checked = 0
    for mp in metas:
        m = json.loads(mp.read_text(encoding="utf-8"))
        excluded = m.get("f2p_excluded_not_bun_test") or []
        protected = set(m["protection"]["restore"]) | set(m["protection"]["remove"])
        for p in excluded:
            assert p not in m["f2p"], f"{mp.parent.name}: {p} 不该进 F2P"
            assert p in protected, f"{mp.parent.name}: {p} 被排除了却没受保护"
            checked += 1
        # 正向：F2P 里每一个都必须是 bun 认的文件名
        t3 = load_t3()
        for p in m["f2p"]:
            assert t3.is_bun_test_file(p), f"{mp.parent.name}: F2P 含 bun 不收集的 {p}"
    print(f"（checked {checked} 个被排除的辅助文件）")
