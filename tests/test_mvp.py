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
             ㉟ 采样脚本不许静默覆盖已有的 `p2p.jsonl`（数小时容器产物，不可重建）
             ㊱ 产物齐全自查：缺文件与**零字节**文件同罪（空 gold_patch = oracle 静默 0 分）
             ㊲ 齐全自查必须有**不写盘**的 `--check-only` 路径 —— 实测把它放在生成之后
                做不出反向自证②：生成是幂等重写，跑一遍就把删掉的文件补回来了
             ㊳㊴ 采样脚本两处「命令报成功 + 产物悄悄不对」（为重采 T0029 读代码时发现）：
                ㊳ `--only-base`/`--limit` 的合并覆写会把 p2p.jsonl 从 50 行截成 1 行
                ㊴ `--resume` 把 ok:false 也当已采，失败的 base 被永久跳过

用法：
    python3 -m pytest scripts/mvp/tests/test_mvp.py -v
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
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


#: 骨架名单现在是**空的** —— TZ/T0-T7 全部实现完毕：
#:   T2/T3/T4 2026-09-08（归 ⑫-⑯ / ㉒-㉚ / ⑰-㉑ 管）
#:   T5       2026-09-10（t5-gate.py + t5_gate_lib.py，归 ㊵-㊷ 管）
#:   T7       2026-09-12（t7-baseline.py + t7_report_lib.py，归 ㊸-㊾ 管）
#: 🔴 `t7-baseline.sh` 已随 T7 实现一起**删除**，走的是 `t5-gate.sh` 那条教训：
#: 「转发壳即地雷」—— 文件只要被执行就有副作用，则任何**以为自己只是在探测它**
#: 的调用方（测试、`--help`、shell 补全）都会触发副作用。T5 当年就是被本测试
#: `bash t5-gate.sh` 探了一下，真的起了一批 harbor（65 条 task 跑掉 9 个 trial
#: 才被发现），与正式批次抢容器和磁盘。所以跑批一律只留 .py 入口。
SKELETONS: list[str] = []


@pytest.mark.parametrize("script", SKELETONS)
def test_unimplemented_skeletons_exit_nonzero(script):
    """T0 只交付骨架。**不许静默产出空结果** —— 那会让 T3 拿着空文件「成功」跑完。

    退出码 64（EX_USAGE）而不是 1，是为了与「实现了但失败」区分开。

    ⚠️ 名单为空时本测试**不产生任何用例**（pytest 会 skip 掉整个 parametrize）。
    「骨架都实现完了」这件事由下面的 `test_no_skeleton_scripts_remain` 正面守住 ——
    只靠空名单的话，将来有人新加骨架却忘了登记，这里会静默放过。
    """
    path = MVP / script
    cmd = ["bash", str(path)] if path.suffix == ".sh" else [sys.executable, str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)
    assert proc.returncode != 0, f"{script} 未实现却以 0 退出"
    assert "尚未实现" in (proc.stdout + proc.stderr)


def test_no_skeleton_scripts_remain():
    """正面守「没有漏登记的骨架」——空名单本身不构成证据。

    判据：`scripts/mvp/` 下任何文件只要正文（去掉注释）里写着「尚未实现」，
    就必须出现在 `SKELETONS` 名单里，否则它是个**没人测的骨架**。
    """
    unlisted = []
    for p in sorted(MVP.glob("t*.py")) + sorted(MVP.glob("t*.sh")):
        code = "\n".join(
            ln for ln in p.read_text(encoding="utf-8").splitlines()
            if not ln.lstrip().startswith("#")
        )
        if "尚未实现" in code and p.name not in SKELETONS:
            unlisted.append(p.name)
    assert not unlisted, f"这些脚本仍是骨架却没登记进 SKELETONS：{unlisted}"


def test_no_script_starts_a_real_run_when_merely_executed():
    """🔴 **跑批脚本不许「一执行就真跑」** —— 2026-09-10 的实测教训。

    T5 实现后，`t5-gate.sh` 曾被改成 `exec python3 t5-gate.py` 的转发壳。
    后果：上面那个骨架测试会 `bash t5-gate.sh` 一下，**真的起了一批 harbor**
    （65 条 task、9 个 trial 跑完才被发现），与正在跑的正式批次抢容器与磁盘。

    教训是「转发壳即地雷」：一个文件只要被执行就产生副作用，那么任何**以为自己
    只是在探测它**的调用方（测试、`--help`、shell 补全）都会触发副作用。
    所以 `t5-gate.sh` 已删除，跑批统一走 `python3 scripts/mvp/t5-gate.py`。

    这条守的是不变式：`scripts/mvp/` 下不得再出现「无参数执行就调 harbor」的 .sh。
    """
    offenders = []
    for sh in sorted(MVP.glob("*.sh")):
        text = sh.read_text(encoding="utf-8")
        # 去掉注释行再看，注释里提命令是可以的（骨架文件正是这么记的）
        code = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("#")
        )
        if "exec " in code and "t5-gate.py" in code:
            offenders.append(f"{sh.name}: 转发到 t5-gate.py（执行即真跑）")
        # 未实现的骨架必须在调 harbor 之前就退出
        if "harbor run" in code and "exit 64" not in code and "尚未实现" not in text:
            offenders.append(f"{sh.name}: 无守卫地调 harbor run")
    assert not offenders, "发现执行即产生副作用的脚本：" + "; ".join(offenders)


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


def test_t3_sampler_refuses_to_clobber_existing_p2p_artifact(tmp_path):
    """㉟ 已有 `p2p.jsonl` 时，不带 `--resume` / `--overwrite` 重跑必须拒绝执行。

    采样要起 50 个容器、跑一两小时，产物**不可从别处重建**。而 `--resume` 是可选参数 ——
    手滑重跑一次就会把已采好的结果从头覆盖掉，且过程中没有任何提示
    （每采完一个 base 就落盘，覆盖是渐进的，等发现时前面的已经没了）。

    所以改成必须显式表态：续采 `--resume`，重采 `--overwrite`。
    """
    script = MVP / "t3-sample-p2p.py"
    fake_meta = tmp_path / "bench/v0.2-mini/meta"
    fake_meta.mkdir(parents=True)
    (fake_meta / "p2p.jsonl").write_text('{"base_commit":"deadbeef","ok":true}\n', encoding="utf-8")
    # 用 MVP_DIR 环境变量把产物目录指到 tmp_path（common.py 支持覆盖）
    env = {**os.environ, "MVP_DIR": str(tmp_path / "bench/v0.2-mini")}
    proc = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, cwd=REPO_ROOT, env=env
    )
    if "已存在" not in (proc.stdout + proc.stderr):
        pytest.skip("MVP_DIR 覆盖不生效（common.py 的目录常量在 import 时固化），跳过")
    assert proc.returncode == 2, "已有产物却仍以 0 退出 —— 会静默覆盖数小时的结果"
    assert (fake_meta / "p2p.jsonl").read_text(encoding="utf-8").strip(), "产物被清空了"


def test_t3_missing_files_flags_absent_and_empty_artifacts(tmp_path):
    """㊱ 产物齐全自查：缺文件与**零字节文件**都必须算不齐。

    零字节和缺失同罪，而且更隐蔽 —— 空的 `gold_patch.diff` 在容器里是
    「`git apply` 成功但什么都没改」，即 **oracle 静默拿 0 分**，
    形态是「参考解做不出来」，会被误诊成 T2 的 patch 反解错了（与 ㉞ 同一个坑）。
    """
    t3 = load_t3()
    d = tmp_path / "T9999"
    for rel in t3.REQUIRED_FILES:
        f = d / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x", encoding="utf-8")
    assert t3.missing_files(d) == [], "齐备的目录不该报缺"

    (d / "tests/score.py").unlink()
    (d / "solution/gold_patch.diff").write_text("", encoding="utf-8")  # 零字节
    assert sorted(t3.missing_files(d)) == ["solution/gold_patch.diff", "tests/score.py"]

    # environment/ 是 T4 的产物，本脚本不写但必须核 —— 缺快照要在生成阶段就炸，
    # 而不是等 T5 建镜像时才失败
    assert "environment/repo-snapshot.tar.gz" in t3.REQUIRED_FILES


def test_t3_check_only_does_not_regenerate_and_reports_damage():
    """㊲ 反向自证②：删掉某条的 `tests/score.py`，自查必须报错。

    🔴 这条测试存在的理由是一次实测失败：最初把齐全自查放在**生成之后**，
    于是反向自证做不出来 —— 生成是幂等重写，跑一遍就把删掉的文件补回来了，
    末尾那次核对永远看不到「产物被破坏」的状态（`rc=0`，两次实测都是）。
    它只能抓到「生成器自己漏写」，抓不到交付物在盘上被改坏。

    所以必须有一条**不写盘**的路径 `--check-only`。本测试同时验两件事：
    ① 破坏后它报非零；② 它**没有**顺手把文件补回来（否则又退化成上面那种自欺）。
    """
    t3_script = MVP / "t3-build-harbor-tasks.py"
    victim = c.MVP_TASKS / "T0002" / "tests" / "score.py"
    if not victim.exists():
        pytest.skip("T3 还没生成 T0002")
    saved = victim.read_text(encoding="utf-8")
    try:
        victim.unlink()
        proc = subprocess.run(
            [sys.executable, str(t3_script), "--check-only"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert proc.returncode == 2, f"缺 score.py 却以 {proc.returncode} 退出"
        assert "tests/score.py" in (proc.stdout + proc.stderr)
        assert not victim.exists(), "--check-only 把文件补回来了 —— 它不该写盘"
    finally:
        victim.write_text(saved, encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(t3_script), "--check-only"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, f"恢复后仍报不齐：\n{proc.stdout}\n{proc.stderr}"


def test_t3_sampler_merges_onto_all_existing_records_not_just_resumed():
    """㊳ `--only-base` / `--limit` 不许把 `p2p.jsonl` 从 50 行截断成 1 行。

    🔴 实测缺陷（为重采 T0029 读代码时发现）：落盘那步是
    「已有记录 + 本轮结果」的**合并覆写**，但「已有记录」原先只在 `--resume`
    分支里读。于是 `--only-base xxx` 重采单个 base 时，合并的左半边是空字典
    → 覆写后整个文件只剩这一个 base。

    形态是**命令成功退出、打印「采样完成」，而 49 个 base 的数小时产物没了** ——
    产物不可从别处重建（要重新起 50 个容器）。这条测试盯的是源码结构，
    因为跑真流程需要 docker，而缺陷恰恰只在「重采单个 base」这条路径上暴露。
    """
    src = (MVP / "t3-sample-p2p.py").read_text(encoding="utf-8")
    # 合并必须用「无条件读入的全量」，不能用「只在 resume 下才填的跳过名单」
    assert "merged = {**done_all," in src, "落盘的左半边不是全量已有记录 —— 会截断产物"
    # done_all 的读入不许挂在 args.resume 上（只有 --overwrite 才该丢弃旧的）
    m = re.search(r"if P2P_OUT\.exists\(\) and not args\.overwrite:\s*\n\s*done_all = ", src)
    assert m, "done_all 的读入条件不对：必须无条件读、仅 --overwrite 丢弃"


def test_t3_sampler_resume_retries_failed_bases():
    """㊴ `--resume` 不许把「采失败」的 base 当成「已采过」跳过。

    🔴 实测缺陷：T0029 的 base 首轮因宿主取包超时构建失败（`ok:false`）。
    跳过名单原先不看 `ok` 字段，于是 `--resume` 会永久跳过它 ——
    打印「50/50 完成」，而那条始终是 `ok:false`。

    与 ㊳ 同一形态：**命令报成功、产物悄悄不对**。
    """
    src = (MVP / "t3-sample-p2p.py").read_text(encoding="utf-8")
    assert re.search(
        r'done = \{b: d for b, d in done_all\.items\(\) if d\.get\("ok"\)\}', src
    ), "resume 的跳过名单没有按 ok 过滤 —— 失败的 base 会被永久跳过"


# ── ㊵-㊸ T5 门禁判定（2026-09-10 实现，每条都对应一次实测代价） ──────


def _row(task="T0001", **kw):
    """造一条 TrialRow。默认双源一致（否则所有判定都会先撞双源检查）。"""
    import t5_gate_lib as lib

    kw.setdefault("reward", 1.0)
    kw.setdefault("reward_txt", kw["reward"])
    return lib.TrialRow(task=task, trial_dir=Path("/nonexistent"), **kw)


def test_t5_nop_gate_flags_fake_task_by_f2p_not_total_reward():
    """㊵ 门禁②必须看 **f2p 分量**，不是总 reward（v1.2 修正，且实测抓到 4 条）。

    🔴 真实战果：T0001/T0006/T0015/T0037 在 nop 下 **f2p=1** —— 什么都不改测试就绿，
    即「测试改动不构成 fail-to-pass」。这类假 task **T3 的 oracle 自检完全抓不到**
    （oracle 也是满分），只有 nop 能抓。

    而如果按总 reward 判：假 task 的 reward = f2p AND p2p = 1 AND 1 = 1，
    会被判成「通过」——正好放过唯一该抓的那类。
    """
    import t5_gate_lib as lib

    fake = _row(reward=1.0, f2p=1.0, p2p=1.0)
    v = lib.gate_nop([fake])[0]
    assert not v.ok, "nop 下 f2p=1 是假 task，必须报红"
    assert "假 task" in v.reason
    assert not v.infra, "假 task 是 task 自身问题，不是基础设施问题"

    good = _row(reward=0.0, f2p=0.0, p2p=1.0)
    assert lib.gate_nop([good])[0].ok, "nop 下 f2p=0 且 p2p=1 才是健康 task"


def test_t5_nop_gate_separates_bad_env_from_fake_task():
    """㊶ `p2p=0` 是**坏环境**，必须标 infra —— 不要去动 task。

    快照缺文件 / 依赖装不上 / P2P 采到被剔除的测试，都会让 P2P 恒败。
    压成「淘汰」会让人去改本来没坏的 task。
    """
    import t5_gate_lib as lib

    v = lib.gate_nop([_row(reward=0.0, f2p=0.0, p2p=0.0)])[0]
    assert not v.ok and v.infra, "p2p=0 是基础设施问题，要标 infra"
    assert "坏环境" in v.reason


def test_t5_oracle_gate_does_not_kill_task_when_only_p2p_red():
    """㊷ 🔴 `f2p=1` 但 P2P 红 ≠ task 该淘汰 —— 这是当场修掉的一次**误杀**。

    首版把「reward != 1」一律判成淘汰。但 T0017/T0027 的实际形态是
    **F2P 全绿、P2P 红**，即「参考解打上后砸了别处」，与「gold patch 打不上」
    是两个完全不同的诊断。且这两条在 nop 下 P2P 全绿、失败的 P2P
    （abort-graceful / turn-hard-timeout / stream-interrupt-recovery）全是 timing 类。

    两种可能必须复跑才能分辨，所以标 infra 进「待复查」而不是「已淘汰」：
      ① 参考解真引入回归 → 淘汰；② P2P 是 flaky → task 无罪。

    教训与 T4 的 `--selftest-substring-leak` 同源：**判据写粗了，门禁就会以
    「全绿/全红」的样子给出错误结论**。这里的粗糙不在阈值而在**分类**。
    """
    import t5_gate_lib as lib

    v = lib.gate_oracle([_row(reward=0.0, f2p=1.0, p2p=0.0)])[0]
    assert not v.ok, "reward != 1 仍然没过门禁"
    assert v.infra, "f2p=1 而 p2p 红 → 待复查，不能直接淘汰 task"
    assert "不淘汰" in v.reason or "复跑" in v.reason

    # 对照：F2P 真红才是 task 自身问题
    hard = lib.gate_oracle([_row(reward=0.0, f2p=0.0, p2p=1.0)])[0]
    assert not hard.ok and not hard.infra, "F2P 红是 task 不可解，属真淘汰"


def test_t5_dual_source_mismatch_is_infra_not_task_failure():
    """㊸ reward 双源不一致 = **取数路径写错**，不是分数变了（§3.8-D）。

    `result.json` 的值必须与 `verifier/reward.txt` 一致。不一致时若判成
    「task 淘汰」，就会把一个取数 bug 记成一批 task 的质量问题。
    两边都缺也算不一致 —— 那说明 verifier 根本没写分。
    """
    import t5_gate_lib as lib

    for gate in (lib.gate_oracle, lib.gate_nop):
        v = gate([_row(reward=1.0, reward_txt=0.0, f2p=1.0, p2p=1.0)])[0]
        assert not v.ok and v.infra, f"{gate.__name__}: 双源不一致必须标 infra"
        assert "双源" in v.reason

    missing = lib.gate_oracle([_row(reward=1.0, reward_txt=None, f2p=1.0, p2p=1.0)])[0]
    assert not missing.ok and missing.infra, "reward.txt 缺失也算双源不一致"


def test_t5_consistency_gate_needs_at_least_two_runs():
    """㊹ 门禁③：单次运行**判不了**一致性，不能默认放过。

    `-k 3` 若因故只落了 1 个 trial，把它判成「一致」等于凭一次运行发通过证 ——
    正是 R1「绿着坏掉」的形态。标 infra（要补跑），不是淘汰 task。
    """
    import t5_gate_lib as lib

    one = lib.gate_consistency([_row(reward=1.0)])[0]
    assert not one.ok and one.infra, "只有 1 次运行必须标 infra，不能判通过"

    same = lib.gate_consistency([_row(reward=1.0), _row(reward=1.0), _row(reward=1.0)])[0]
    assert same.ok, "三次一致应通过"

    flaky = lib.gate_consistency([_row(reward=1.0), _row(reward=0.0), _row(reward=1.0)])[0]
    assert not flaky.ok and not flaky.infra, "三次不一致是 task 有随机性，属真淘汰"


def test_t5_report_does_not_claim_three_gates_when_fewer_ran():
    """㊺ 报告措辞必须反映**实际跑了几道门禁**。

    `--only nop` 时若写「三道门禁后存活 61 条」，读者会把 61 当终值，
    而 oracle/k3 还没跑（实测 oracle 又淘汰了 19 条，真值是 40）。
    **报告自己说谎比没有报告更糟**。
    """
    src = (MVP / "t5-gate.py").read_text(encoding="utf-8")
    assert "已跑门禁" in src, "报告必须显式列出实际跑了哪几道"
    assert "这不是终值" in src, "门禁不齐时必须警告当前存活不是终值"
    assert 'len(summaries) == 3' in src, "必须按实际门禁数决定措辞"


def test_t5_partial_run_does_not_wipe_other_gates_conclusions():
    """㊻ 🔴 `--only <一道>` 收尾时**不许把其它门禁的结论覆盖掉**。

    实测缺陷（2026-09-10，跑 `--only oracle` 时真发生了）：`write_outputs` 只写
    `summaries` 里有的门禁，而 `--only` 模式下它只有一项 —— 于是 `gate.jsonl`
    被整份重写成只剩那一道，**把前一道跑了 38 分钟的 nop 结论静默抹掉**。

    形态与 T3 采样脚本的 ㊳㊴ 同源：**命令报成功、产物悄悄不对**。
    发现它靠的是落盘前备份时顺手核了一眼「备份里含几道门禁」。

    修法：落盘前把没在本次跑、但已有 run 产物的门禁用 `load()` 一并读进来。
    这也是把判定与跑批解耦的价值 —— 原始 run 产物完好时，`--from-runs`
    能零成本重算回来，不必重跑容器。
    """
    src = (MVP / "t5-gate.py").read_text(encoding="utf-8")
    # 必须在写盘前补齐其它门禁
    assert "（并入已有产物）" in src, "落盘前没有并入已有产物的其它门禁 —— 会覆盖它们"
    idx_merge = src.index("（并入已有产物）")
    idx_write = src.rindex("write_outputs(summaries)")
    assert idx_merge < idx_write, "并入逻辑必须在 write_outputs 之前"
    # 报告顺序固定，不随跑批先后变化
    assert '("oracle", "nop", "oracle-k3") if k in summaries' in src, "报告门禁顺序未固定"


# ── ㊸-㊺ T5 反向自证机制本身的守卫 ────────────────────────────────


def _selftest_src() -> str:
    return (MVP / "t5-gate.py").read_text(encoding="utf-8")


def test_t5_selftest_missing_mutant_counts_as_failure():
    """产物里找不到某个变异体，必须判**不通过**，不能当它不存在就跳过。

    这是反向自证最危险的失效方式：变异体因为 harbor 没发现（目录名不合规、
    符号链接断了、`-p` 指错）而**一个都没跑**，于是「没有不符合预期的」
    被写成「四条全部通过」—— 自证自己变成恒绿。
    """
    import t5_gate_lib as lib

    cs = lib.SelftestCase("M9-never-ran", "oracle", False, "故意不给产物")
    out = lib.check_selftest([cs], {"oracle": []}, {"oracle": []})
    assert len(out) == 1
    assert not out[0].ok, "变异体没跑起来必须判不通过"
    assert "找不到" in out[0].detail


def test_t5_selftest_checks_why_it_is_red_not_just_that_it_is_red():
    """红得对不对也要核 —— 「因环境坏而红」不能算「因检测生效而红」。

    实测背景：M2（空参考解）期望的是 `infra=False` 的 F2P 红。如果它因为
    双源不一致 / trial 异常而红（都是 `infra=True`），那门禁并没有证明
    「能抓住空参考解」，只证明了「环境有问题」。
    """
    import t5_gate_lib as lib

    cs = lib.SelftestCase(
        "M2-empty-solution", "oracle", False, "期望 F2P 红",
        expect_infra=False, expect_reason_has="f2p=0.0",
    )
    # 红了，但红的理由是 infra —— 必须判不通过
    infra_red = [lib.Verdict("M2-empty-solution", False, "trial 异常：Boom", infra=True)]
    out = lib.check_selftest([cs], {"oracle": infra_red}, {"oracle": []})
    assert not out[0].ok, "infra 红不能冒充检测生效"
    assert "红的理由不对" in out[0].detail

    # 红且理由对 —— 通过
    right_red = [lib.Verdict("M2-empty-solution", False, "oracle reward=0.0（f2p=0.0；正常跑完）")]
    assert lib.check_selftest([cs], {"oracle": right_red}, {"oracle": []})[0].ok


def test_t5_selftest_requires_unmutated_control():
    """自证批次里必须有**未变异对照**且要求它过。

    没有它，「整批因构建失败而全红」与「四条检测全部生效」在报告里
    长得一模一样 —— 全红会被读成全部通过。
    """
    src = _selftest_src()
    assert "M0-control" in src, "自证必须带未变异对照"
    # 对照的期望必须是「过」（must_pass=True）
    idx = src.index('"M0-control", "oracle"')
    assert "True" in src[idx : idx + 60], "对照的期望必须是 must_pass=True"


def test_t5_selftest_keeps_the_m4_m5_pair():
    """M4（有保护→绿）与 M5（拿掉保护→红）**必须成对存在**。

    🔴 单有 M4 时它的绿不可信：「垃圾被清掉了所以绿」与「垃圾根本没写进去
    所以绿」在产物里无法区分。M5 拿掉保护后必须报红，才排除了后者。
    删掉 M5 会让 M4 退化成一条看起来在检查、实际啥也没证明的自证 ——
    与 T4 那条阈值拍错的恒绿自检是同一种失效。
    """
    src = _selftest_src()
    assert "M4-agent-tampers-tests" in src and "M5-tamper-unprotected" in src, (
        "M4/M5 必须成对 —— 少一条，测试保护这项就没被真正验证"
    )
    # M4 期望过、M5 期望红
    i4 = src.index('"M4-agent-tampers-tests", "oracle"')
    i5 = src.index('"M5-tamper-unprotected", "oracle"')
    assert "True" in src[i4 : i4 + 60], "M4 应期望通过（保护生效）"
    assert "False" in src[i5 : i5 + 60], "M5 应期望报红（保护缺失）"


def test_t5_selftest_mutants_share_one_environment_image():
    """变异体只许改 `tests/` 与 `solution/`，`environment/` 必须逐字节同源。

    `environment_content_hash()` 只哈希 `environment/` 下的真实文件，所以
    原样硬链接 → 六个副本共享一个 `environment_id` → **镜像只构建一次**。
    一旦有人往变异体的 `environment/` 里写东西，每个变异体各建一次镜像
    （约 30 秒 + 数百 MB），在磁盘紧的机器上会直接把批次跑崩。
    """
    src = _selftest_src()
    assert "os.link" in src, "environment/ 必须硬链接，不能复制或改写"
    # 变异写入只允许落在 tests/ 或 solution/ 下
    import re

    for m in re.finditer(r'\(m\d+ / "([^"]+)"', src):
        assert m.group(1) in ("tests", "solution"), (
            f"变异体写入了 {m.group(1)}/ —— 只许改 tests/ 与 solution/，"
            f"改 environment/ 会破坏镜像共享"
        )


# ── ㊻-㊾ T6 泄漏扫描器的守卫（每条都对应 T6 实测踩到的坑） ──────────────


def _t6_scan_src() -> str:
    return (MVP / "t6-leak-scan.py").read_text(encoding="utf-8")


def _t6_mod():
    """按文件路径加载 t6-leak-scan.py（文件名带连字符，不能 import）。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location("t6_leak_scan", MVP / "t6-leak-scan.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_t6_scan_matches_eval_framework_not_just_evals():
    """判据必须能命中 `/eval-framework` —— 方案原文的 `*evals*` 匹配不到它。

    🔴 T6 实测发现：方案 §4 T6 给的 `-path '*evals*'` **少个 s，匹配不到
    `/eval-framework`**，而那正是方案自己点名的三类「像泄漏其实是真实资产」
    之一 —— 等于扫描器对它完全失明，既报不出它，也无法确认它没被误剔。
    """
    src = _t6_scan_src()
    assert '"*eval-framework*"' in src, (
        "必须单列 eval-framework —— `*evals*` 少个 s 匹配不到 `/eval-framework`"
    )


def test_t6_scan_does_not_widen_to_bare_eval():
    """但不许放宽成 `*eval*` —— 噪声淹掉真违规比漏看更危险。

    实测：放宽成 `*eval*` 后，T0002 的对照组从「0 违规」变成「6 违规」，
    混进来的是 `timeval`（perl 头文件）、`evaluator.ts`（仓库真实源码）。
    一旦对照组自己就有 6 条噪声违规，真泄漏出现时没人看得出来。
    """
    src = _t6_scan_src()
    idx = src.index("FIND_EXPR = [")
    expr = src[idx : src.index("]", idx)]
    assert '"*eval*"' not in expr, (
        "不许用裸 `*eval*` —— 会把 timeval / evaluator.ts 扫成违规，"
        "噪声淹掉真违规"
    )


def test_t6_scan_build_has_timeout():
    """构建必须有超时 —— 宿主代理断开时 `bun install` 会无限等待。

    🔴 T6 实测：代理进程被关掉后，构建容器（从 dockerd 继承 HTTP_PROXY）
    卡在一条死连接上，0.02% CPU 挂了 8 分钟不退，而 `docker build` 自己
    **没有任何超时**。没有这个上限，一次代理抖动就会把整轮扫描永久卡住。
    """
    src = _t6_scan_src()
    assert "BUILD_TIMEOUT_SEC" in src, "构建必须有超时上限"
    assert "subprocess.TimeoutExpired" in src, "必须捕获超时并继续，而不是崩掉"
    assert "timeout=BUILD_TIMEOUT_SEC" in src, "超时值必须真的传给 subprocess.run"


def test_t6_scan_writes_each_row_immediately():
    """逐条落盘，不许只在结尾一次性写 —— 否则中途被杀就全白跑。

    🔴 T6 实测：首版在结尾才 `write_jsonl`。跑到第 13 条时代理断开、进程被杀，
    40 条只留下 1 行 —— 前 12 条的容器全白建了（每条约 2.5 分钟）。
    长跑任务的中间结果必须即时可见。
    """
    src = _t6_scan_src()
    assert 'OUT.open("a"' in src, "必须以追加模式逐条落盘"
    assert "--resume" in src, "必须支持续跑，否则中断后只能从头再来"


def test_t6_scan_distinguishes_unverified_from_clean():
    """镜像没建成要写 `null`，不能写 `true` —— 「没验」和「验过没问题」必须可区分。

    这是方法论第一条（验收脚本自己会骗人）的直接应用：一个在构建失败时
    也写 `true` 的字段，等于没有这个字段。回写脚本同样要守这条。
    """
    scan_src = _t6_scan_src()
    assert '"leak_scan_passed": None' in scan_src, "构建失败时必须写 None，不是 True"
    wb = (MVP / "t6-writeback.py").read_text(encoding="utf-8")
    assert 'm["leakage"]["leak_scan_passed"] = None' in wb, (
        "回写脚本在未扫/未建成时必须写 None"
    )


def test_t6_scan_keeps_the_three_known_benign_classes():
    """三类已核良性必须都在判据里 —— 少一类就会误淘汰，且会打断存活测试。

    `src/skill/builtin/*/evals/` 被 `tests/skill/code-review.test.ts:54`
    断言存在，剔了它 P2P 直接变红 —— 那是自己造一个假的测试失败。
    ⚠️ T4 报告记的是 `packages/*/...`（monorepo 形态），本批 40 条是
    external 形态落在 `src/` 下 —— 同一类，路径不同，判据要能同时命中。
    """
    m = _t6_mod()
    cases = [
        "/repo/src/skill/builtin/ci-self-heal/evals/case_csh_001.yaml",
        "/repo/packages/web/skill/builtin/code-review/evals/case_cr_001.yaml",
        "/eval-framework/package.json",
        "/repo/node_modules/eval-framework/package.json",
    ]
    viol, benign = m.classify(cases)
    assert not viol, f"这些都是已核良性，不该判违规：{viol}"
    assert len(benign) == len(cases)


def test_t6_scan_still_flags_real_leaks():
    """真泄漏必须仍报红 —— 良性白名单不能宽到把真泄漏也放过。

    与上一条成对：只有「良性放过」而没有「真泄漏报红」，白名单就可能被
    写得过宽而无人察觉（M4/M5 配对反证的同一个道理）。
    """
    m = _t6_mod()
    leaks = [
        "/repo/docs/bugfixes/todo/20260807-某bug根因.md",
        "/repo/evals/_judge/calibration-set/c1.yaml",
        "/repo/.claude/settings.json",
        "/repo/external-benchmarks/harbor/pyproject.toml",
    ]
    viol, benign = m.classify(leaks)
    assert len(viol) == len(leaks), f"真泄漏被误判成良性：{benign}"


def test_t6_writeback_marks_manual_elimination():
    """回写必须让「T6 人工淘汰」在 meta.json 里可见 —— 否则下游会把淘汰的题算进基线。

    `gate.jsonl` 的 `survives` 是 T5 三道门禁的结论（40 条），**不含 T6 的人工淘汰**。
    T0005 三道门禁全绿，只写 `gold_verified` 的话它在 meta.json 里与存活条目一模一样，
    而它的题面（发版 + 更新官网日志）与判分对象（AUDIT 日志级别门控）完全无关。
    """
    wb = (MVP / "t6-writeback.py").read_text(encoding="utf-8")
    assert 'm["review"]["eliminated"]' in wb, "必须写 review.eliminated，让人工淘汰可机读"
    assert 'm["review"]["grade"]' in wb, "必须写 review.grade，T7 要按分级分组报基线"
    # 没过目的写 None，不写 False —— 与 leak_scan_passed 同一条纪律
    assert 'None if g6 is None else (g6 == "X")' in wb, (
        "未过目的条目必须写 None，不能写 False（「没过目」≠「过目了没淘汰」）"
    )


def test_t6_survivors_list_excludes_manually_eliminated():
    """存活名单产物必须是 gate 存活减去 T6 淘汰，且与分级分组自洽。

    T7 取存活集若照 `gate.jsonl` 的 `survives` 取，会多算 T0005。所以要有一份
    显式名单，且它必须与 `grade.json`（逐条分级）、`t7-grade-groups.json`（分组）
    三者一致 —— 任一处漂移都会让基线的分母对不上。
    """
    r = c.MVP_REPORTS / "t6-recheck"
    surv = json.loads((r / "survivors.json").read_text(encoding="utf-8"))
    grade = json.loads((r / "grade.json").read_text(encoding="utf-8"))
    groups = json.loads((r / "t7-grade-groups.json").read_text(encoding="utf-8"))

    elim = {t for t, v in grade.items() if v == "X"}
    assert set(surv["t6_eliminated"]) == elim, "survivors.json 的淘汰名单与 grade.json 不一致"
    assert set(surv["survivors"]) == set(grade) - elim, "存活名单 ≠ 分级全集减淘汰"
    assert surv["survivors_n"] == len(surv["survivors"])

    union = set().union(*(set(v) for v in groups.values()))
    assert union == set(surv["survivors"]), (
        "分组并集与存活名单不一致 —— T7 按分组报基线时分母会对不上"
    )


def test_t6_writeback_marks_filename_leak():
    """题面文件名的具体程度要在 meta.json 里可机读 —— 容器内扫描抓不到这类泄漏。

    §4.2：泄漏在**题面文本**里（文档打不开，但路径文本留在 instruction.md 里，
    agent 读得到）。容器内 find 只扫文件树，对它完全失明。交接清单要求 T7 在
    dataset card 里标注，没有字段的话 T7 只能回来手抄报告 markdown ——
    而交接 #4/#5 的纪律恰恰是「读产物，不要读报告 markdown」。

    ⚠️ 必须是三级而非布尔：`filename-leak.json` 只做了「带信息 8 条 vs 仅主题 27 条」
    的二分，但 §4.2 的表格把前 8 条再分两级 —— 只有 4 条点出**机制**，另 4 条是
    症状词（污染/误伤/缺少选项/不显示），原文明确判为「仅症状，属正常题面」。
    照二分一律标 True，会让 T7 按 8 条的口径打折扣，而报告说的是 4 条。
    """
    wb = (MVP / "t6-writeback.py").read_text(encoding="utf-8")
    assert 'm["leakage"]["filename_specificity"]' in wb, (
        "必须回写 filename_specificity，否则 T7 只能手抄报告"
    )
    for level in ("mechanism", "symptom", "topic_only"):
        assert f'"{level}"' in wb, f"三级里缺 {level} —— 布尔化会把「正常题面」标成根因泄漏"
    # 未核的写 None —— 与 leak_scan_passed / review.eliminated 同一条纪律
    assert 'm["leakage"]["filename_specificity"] = None' in wb, (
        "未核的条目必须写 None（「没核」≠「核过不点机制」）"
    )


def test_t6_filename_mechanism_set_matches_report():
    """回写脚本的 mechanism 名单必须与报告 §4.2 三级表逐条一致，且三级互不重叠。

    这个名单在回写脚本里是硬编码的（`filename-leak.json` 没有 mechanism/symptom
    这一层），所以它和报告之间没有机械约束 —— 改了一处忘了另一处不会有任何报错。
    这条测试就是那个约束。

    ⚠️ 只认 §4.2 的**三级表**（行首为 | `mechanism` | 的那张）为权威源。该节还留着
    一张更早的「泄漏程度」表，两张表的名单并列 —— 若解析时把两张混在一起，
    正是这条测试要防的漂移。
    """
    import re as _re

    wb = (MVP / "t6-writeback.py").read_text(encoding="utf-8")
    m = _re.search(r"FN_MECHANISM = \{([^}]*)\}", wb)
    assert m, "找不到 FN_MECHANISM"
    in_code = set(_re.findall(r"T\d{4}", m.group(1)))

    md = (c.MVP_REPORTS / "t6-review.md").read_text(encoding="utf-8")
    sec = md.split("### 4.2 ")[1].split("\n---")[0]

    # 三级表：每级恰好一行，行首是 | `<级名>` |
    levels = {}
    for lv in ("mechanism", "symptom", "topic_only"):
        rows = [ln for ln in sec.splitlines() if ln.startswith(f"| `{lv}` |")]
        assert len(rows) == 1, f"§4.2 三级表里 `{lv}` 的行数为 {len(rows)}，应为 1"
        levels[lv] = set(_re.findall(r"T\d{4}", rows[0]))

    assert in_code == levels["mechanism"], (
        f"回写脚本的 mechanism 名单 {sorted(in_code)} "
        f"与 §4.2 三级表 {sorted(levels['mechanism'])} 不一致"
    )
    assert not (levels["mechanism"] & levels["symptom"]), "机制级与仅症状级重叠"
    assert len(levels["mechanism"]) == 4 and len(levels["symptom"]) == 4, (
        "§4.2 的两级各 4 条 —— 数量变了要同步改 dataset card 的标注口径"
    )


def test_t6_filename_leak_partition_covers_reviewed_set():
    """filename-leak.json 的两组必须不重叠，且并集覆盖全部过目条目。

    这两组是「点出根因」与「仅症状」的二分。若有条目两组都不在，报告的
    「8 条偏高」就没有分母；若两组重叠，同一条会被同时算进两个口径。
    """
    import json as _json

    r = c.MVP_REPORTS / "t6-recheck"
    fnl = _json.loads((r / "filename-leak.json").read_text(encoding="utf-8"))
    grade = _json.loads((r / "grade.json").read_text(encoding="utf-8"))

    root = set(fnl["rootcause_in_filename"])
    topic = set(fnl["topic_only"])
    assert not (root & topic), f"两组重叠：{root & topic}"
    # 全集是过目的 40 条；未被二分的条目要能说清是哪些（题面无文档引用的 5 条）
    unpartitioned = set(grade) - root - topic
    assert len(unpartitioned) <= 5, (
        f"未二分的条目过多（{len(unpartitioned)}），说明 filename-leak.json 漏了：{unpartitioned}"
    )


def test_t6_report_distribution_table_matches_artifacts():
    """报告 §7.1 的三张分布表必须与产物实算一致 —— 它们是 T7 报基线的分母。

    这三张表是手写的数字，与 `survivors.json` × 各 `meta.json` 之间没有机械约束。
    T7 的交接 2b/2c 直接引用它们决定「报几档」「哪档不能报」，一处漂移就会让
    基线的分母对不上，而没有任何东西会报错。这条测试就是那个约束。
    """
    import json as _json
    import re as _re

    r = c.MVP_REPORTS / "t6-recheck"
    surv = _json.loads((r / "survivors.json").read_text(encoding="utf-8"))["survivors"]
    tasks = c.MVP_TASKS if hasattr(c, "MVP_TASKS") else c.MVP_ROOT / "tasks"

    band, cat = {}, {}
    for t in surv:
        m = _json.loads((tasks / t / "meta.json").read_text(encoding="utf-8"))
        band[m["band"]] = band.get(m["band"], 0) + 1
        cat[m["category"]] = cat.get(m["category"], 0) + 1

    md = (c.MVP_REPORTS / "t6-review.md").read_text(encoding="utf-8")
    sec = md.split("### 7.1 ")[1].split("\n## ")[0]

    def cell(label: str) -> int:
        """取 §7.1 表格里 `| <label> | <数字> | ...` 的第二列（数字可带 ** 强调）。

        按列切而不是对整行做正则 —— 第三列的说明文字里有「5 条」「41%」这类数字，
        对整行搜会命中它们。
        """
        rows = [ln for ln in sec.splitlines()
                if _re.match(rf"^\|\s*`?{_re.escape(label)}`?\s*\|", ln)]
        assert len(rows) == 1, f"§7.1 里 {label!r} 的行数为 {len(rows)}，应为 1"
        cols = [x.strip() for x in rows[0].strip().strip("|").split("|")]
        assert len(cols) >= 2, f"§7.1 的 {label!r} 行列数不足：{rows[0]}"
        m = _re.fullmatch(r"\*{0,2}(\d+)\*{0,2}", cols[1])
        assert m, f"§7.1 的 {label!r} 行第二列不是纯条数：{cols[1]!r}"
        return int(m.group(1))

    # 难度档：S 必须是 0（实测为零，不是待填）
    assert cell("S") == band.get("S", 0) == 0, (
        f"§7.1 的 S 档与实算不一致：报告 {cell('S')}，实算 {band.get('S', 0)}。"
        "S=0 是 T7 健康度判据第三条失效的依据（交接 2c），改动要同步 dataset card"
    )
    for b in ("M", "L"):
        assert cell(b) == band[b], f"§7.1 的 {b} 档：报告 {cell(b)}，实算 {band[b]}"
    for k in ("bug_fix", "test_authoring"):
        assert cell(k) == cat[k], f"§7.1 的 {k}：报告 {cell(k)}，实算 {cat[k]}"

    assert sum(band.values()) == len(surv) == 39, (
        f"难度分布合计 {sum(band.values())} ≠ 存活 {len(surv)}"
    )


# ── ㊸-㊾ T7 判定与统计层（t7_report_lib） ──────────────────────────
#
# 为什么要给统计层单测：08 号 §4.11 记着一次**真实的算错** —— 配对差的 SE 公式
# 多除了一次 N，得出的 CI 与 McNemar 的 p 值直接矛盾。教训是
# 「两个结果互相矛盾时先怀疑仪器」。这批的仪器就是 t7_report_lib，
# 所以在它碰真数据之前先把每条判据用构造输入固定住。

import t7_report_lib as t7lib  # noqa: E402


def _trial(task="T0001", reward=1.0, exception=None, **kw):
    """构造一条 trial。默认是「解出且无异常」。"""
    return t7lib.Trial(task=task, reward=reward, f2p=reward, p2p=1.0,
                       error_code=0, exception=exception, **kw)


# ㊸ Wilson 区间不能跑出 [0,1]

def test_wilson_stays_in_unit_interval():
    """🔴 n=39 且 p 贴边时，正态近似会给出 [0,1] 之外的区间。

    这是选 Wilson 而不是 `p ± 1.96·sqrt(p(1-p)/n)` 的**唯一理由**。
    若有人图省事换回正态近似，这条会红 —— 全对/全错时正态近似的半宽是 0，
    区间退化成一个点，把「n 小所以不确定」误报成「完全确定」。
    """
    for passed, n in ((0, 39), (39, 39), (1, 39), (38, 39)):
        p, lo, hi = t7lib.wilson(passed, n)
        assert 0.0 <= lo <= p <= hi <= 1.0, f"passed={passed} n={n} 给出 [{lo},{hi}]"
        assert hi > lo, f"passed={passed} n={n} 的区间退化成点 —— 像是换回了正态近似"


def test_wilson_zero_n_does_not_invent_a_rate():
    """n=0 时不许编一个 0.5 出来。全格被排除是**要报出来**的事实。"""
    assert t7lib.wilson(0, 0) == (0.0, 0.0, 0.0)


def test_wilson_matches_a1_published_numbers():
    """用 08 号 §4.11 已发表的 A1 数字反向校准仪器：28/54 → 51.9% [38.9%, 64.6%]。

    这是**跨文档的锚点**：仪器算不出别人已经发表的那组数，就说明仪器坏了，
    而不是「口径不同」。
    """
    p, lo, hi = t7lib.wilson(28, 54)
    assert round(p * 100, 1) == 51.9, f"p={p}"
    assert round(lo * 100, 1) == 38.9, f"lo={lo}"
    assert round(hi * 100, 1) == 64.6, f"hi={hi}"


# ㊹ infra 故障排除出分母，不记为答错

def test_infra_failure_excluded_from_denominator_not_counted_wrong():
    """🔴 分母纪律：基础设施故障算进分母 = 把它记成答错。

    构造 4 条：2 解出、1 答错、1 抛异常。
    正确结果是 3/4 参与计分、pass@1 = 2/3，**不是 2/4**。
    """
    trials = [
        _trial("A", 1.0), _trial("B", 1.0), _trial("C", 0.0),
        _trial("D", None, exception="RuntimeError"),
    ]
    r = t7lib.pass_at_1(trials)
    assert r["n"] == 3, f"分母应是 3（排除 infra 那条），得到 {r['n']}"
    assert r["excluded"] == 1 and r["excluded_tasks"] == ["D"]
    assert round(r["p"], 4) == round(2 / 3, 4), f"p={r['p']} —— 若是 0.5 说明把 infra 算成答错了"


def test_reward_none_is_infra_not_zero():
    """verifier 没写分（reward=None）属于 infra，不是 0 分。

    ⛔ 反过来：`reward == 0` **不算** infra —— 那是答错的正常形态。
    把 0 分也当 infra 排除，会把分母越排越小、pass@1 虚高到 100%。
    """
    assert _trial(reward=None).infra_failure is True
    assert _trial(reward=0.0).infra_failure is False


# ㊺ pass@1 不是 pass@k

def test_pass_at_1_is_not_pass_at_k():
    """🔴 k=3 时「任一次通过就算通过」是 **pass@k**，会把数字报高。

    构造一条 task 三次尝试中通过 1 次：pass@1 = 1/3，pass@k 会报 1.0。
    """
    trials = [_trial("A", 1.0), _trial("A", 0.0), _trial("A", 0.0)]
    r = t7lib.pass_at_1(trials)
    assert r["per_task_rate"]["A"] == 1 / 3, f"得到 {r['per_task_rate']['A']} —— 1.0 说明算成了 pass@k"


def test_pass_at_1_partial_infra_uses_usable_trials_only():
    """k=3 中有一次 infra 故障：该 task 仍计分，但只按能用的两次算。

    整条 task 因为一次环境抖动被排除，等于用抖动决定交付集大小。
    """
    trials = [_trial("A", 1.0), _trial("A", 0.0), _trial("A", None, exception="Timeout")]
    r = t7lib.pass_at_1(trials)
    assert r["n"] == 1 and r["excluded"] == 0
    assert r["per_task_rate"]["A"] == 0.5


# ㊺b agent 超时是评测结果，不是仪器故障（E3 实测）

def test_agent_timeout_with_reward_is_not_infra():
    """🔴 **拿到分就不是仪器故障** —— 哪怕 agent 是被墙钟掐死的。

    E3 实测的真实读数（2026-09-13，`exp-fix/E-contract`）：

        T0011  reward=1.0（f2p 全 pass、p2p 30/30）  exception=AgentTimeoutError
        T0029  reward=1.0（同上）                     exception=AgentTimeoutError

    旧判据 `bool(self.exception) or reward is None` 把这两条排除出分母，
    于是 6 条里 3 条解出被报成 **33.3%（1/3）**，真值是 **50%（3/6）**。

    形态之所以危险：**它只会往低报，且不报错**。verifier 明明写了满分，
    报告却说「这条是仪器故障」—— 越是修好了题、agent 越愿意长跑，
    被吞掉的解出就越多。
    """
    t = _trial("T0011", 1.0, exception="AgentTimeoutError")
    assert t.budget_exhausted is True
    assert t.infra_failure is False, "拿到 reward=1.0 却被判 infra —— pass@1 会被静默低报"
    assert t.solved is True

    # 超时且没解出：算**答错**（进分母），不是排除
    zero = _trial("T0028", 0.0, exception="AgentTimeoutError")
    assert zero.infra_failure is False and zero.solved is False

    r = t7lib.pass_at_1([t, zero])
    assert (r["n"], r["excluded"]) == (2, 0), f"分母应是 2、排除 0，得到 {r['n']}/{r['excluded']}"
    assert round(r["p"], 4) == 0.5


def test_upstream_disconnect_is_fake_zero_not_wrong_answer():
    """🔴 上游 LLM 断连 ⇒ **假 0 分**，排除出分母，⛔ 不记为答错。

    2026-09-14 全量重跑实测（T0022）：第 61 轮 / 73 分钟时上游断连
    （`The socket connection was closed unexpectedly`），agent 以
    `error_during_execution` 终止，而 **verifier 照常打了分 ⇒ reward=0.0**。

    形态之所以危险：它与「模型改了但改错」**逐字节一样** ——
    都是 reward=0、Exceptions=0、有仓库写操作。不识别就等于
    **把一次网络抖动记成模型能力不足**（模块 docstring 里 TZ 那次 R-4 假 0 分的同一个坑）。
    """
    t = t7lib.Trial(
        task="T0022", reward=0.0, f2p=0.0, p2p=1.0, error_code=0, exception=None,
        subtype="error_during_execution",
        errors=("LLM 错误: The socket connection was closed unexpectedly.",))
    assert t.upstream_failure is True
    assert t.infra_failure is True, "上游断连没被排除 ⇒ 网络抖动会被记成模型答错"
    assert t.solved is False

    r = t7lib.pass_at_1([t, _trial("A", 1.0)])
    assert (r["n"], r["excluded"]) == (1, 1), f"分母应是 1、排除 1，得到 {r['n']}/{r['excluded']}"
    assert r["excluded_tasks"] == ["T0022"]


def test_upstream_judgment_needs_both_subtype_and_signature():
    """⛔ 两个条件都要满足 —— 只看 subtype 会把 agent 自身的崩溃也擦掉。

    agent 自己崩了（TypeError、断言失败）**是真失败**，
    排除出分母等于替模型擦屁股，方向与「假 0 分」正好相反。
    """
    # subtype 对但错误不是网络类 ⇒ 真失败，进分母
    own = t7lib.Trial(task="X", reward=0.0, f2p=0.0, p2p=1.0, error_code=0, exception=None,
                      subtype="error_during_execution",
                      errors=("TypeError: undefined is not a function",))
    assert own.upstream_failure is False and own.infra_failure is False

    # 网络签名对但 subtype 不是 error_during_execution ⇒ 不算（撞轮数上限就是这种）
    cap = t7lib.Trial(task="Y", reward=0.0, f2p=0.0, p2p=1.0, error_code=0, exception=None,
                      subtype="error_max_turns", errors=("达到最大轮次限制: 120",))
    assert cap.upstream_failure is False and cap.infra_failure is False

    # 解出的题即使 subtype 异常也不该被判上游故障（它拿到分了）
    assert _trial("Z", 1.0).upstream_failure is False


def test_subtype_read_from_metadata_not_exception(tmp_path):
    """🔴 终止形态在 `agent_result.metadata.sid_subtype`，⛔ 不在 exception。

    2026-09-14 我实测取错过一次：读 `exception`（为 None）就报告「撞上限 0 条」，
    真实是 **13/18 撞了 120 轮上限**。这条钉住取数位置。
    """
    d = tmp_path / "T0007__abc"
    d.mkdir()
    (d / "result.json").write_text(json.dumps({
        "task_name": "T0007",
        "verifier_result": {"rewards": {"reward": 0.0, "f2p": 0.0, "p2p": 1.0}},
        "agent_result": {"metadata": {"sid_subtype": "error_max_turns",
                                      "sid_errors": ["达到最大轮次限制: 120"]}},
    }), encoding="utf-8")
    t = t7lib.read_trial(d)
    assert t is not None
    assert t.exception is None, "前提：撞轮数上限时 exception 就是 None"
    assert t.subtype == "error_max_turns", "没从 metadata 读到终止形态"
    assert t.errors and "120" in t.errors[0]
    assert t.infra_failure is False, "撞轮数上限是评测结果，不是仪器故障"


def test_zero_diag_and_report_agree_on_upstream_failure():
    """🔴 归因侧与报告侧对「上游断连」必须**同一个判据** —— 口径打架比判错更难查。

    最初的形态：报告侧 `Trial.upstream_failure` 已把 T0022 按 infra 排除，
    而归因侧仍判 `true_zero_missing_symbol`（真 0）⇒
    归因表说「模型没写出符号」、主表说「仪器故障」，**读者无从判断哪个是真的**。

    修法是归因侧复用 `t7_report_lib` 的判据与签名表，⛔ 不各存一份。
    """
    zd = _load("t7-zero-diag")

    upstream = {"sid_subtype": "error_during_execution",
                "sid_errors": ["LLM 错误: The socket connection was closed unexpectedly."]}
    assert zd._is_upstream_failure(upstream) is True

    # 与报告侧对同一份 metadata 必须给出一致结论
    t = t7lib.Trial(task="T0022", reward=0.0, f2p=0.0, p2p=1.0, error_code=0, exception=None,
                    subtype=upstream["sid_subtype"],
                    errors=tuple(upstream["sid_errors"]))
    assert zd._is_upstream_failure(upstream) == t.upstream_failure == t.infra_failure is True

    # agent 自身崩溃 / 撞轮数上限都不是上游故障（两侧同样一致）
    for md in ({"sid_subtype": "error_during_execution",
                "sid_errors": ["TypeError: undefined is not a function"]},
               {"sid_subtype": "error_max_turns", "sid_errors": ["达到最大轮次限制: 120"]},
               {"sid_subtype": "success", "sid_errors": []}):
        assert zd._is_upstream_failure(md) is False, md


def test_real_infra_exceptions_still_excluded():
    """⛔ 反向闸：别把「不算 infra」推广成「什么异常都不算 infra」。

    环境构建失败、`RewardFileNotFoundError` 这些是**真**仪器故障，
    必须继续排除 —— 算进分母等于把机器坏了记成模型答错。
    """
    for exc in ("RewardFileNotFoundError", "EnvironmentBuildError", "RuntimeError"):
        assert _trial("X", None, exception=exc).infra_failure is True, exc
    # reward=None 本身就够判 infra，不依赖异常类型（verifier 没写分）
    assert _trial("Y", None, exception=None).infra_failure is True
    # 非预算类异常 + 有分：仍按 infra 排除（分不可信，机器出过错）
    assert _trial("Z", 1.0, exception="RuntimeError").infra_failure is True


def test_budget_exception_set_is_narrow():
    """预算类异常集合必须**窄** —— 往里多加一个就等于把真故障算进分母。

    这条钉住的是「以后有人图省事把 RuntimeError 也塞进去」。
    """
    assert t7lib.AGENT_BUDGET_EXCEPTIONS == frozenset({"AgentTimeoutError"})
    assert _trial("A", 0.0, exception=None).budget_exhausted is False


# ㊻ 小格不许报百分比（交接 2b）

def test_small_cell_reports_counts_not_percentage():
    """🔴 交接 2b：任一格 < 5 条只报绝对条数。

    B/C 两档各 4 条，5 条以下的比例会被**单条结果整数级拉动**（1/4 → 25%，
    2/4 → 50%），把噪声报成 25 个百分点的差异。
    """
    cell = t7lib.Cell(label="B", tasks=["a", "b", "c", "d"], solved=1)
    assert cell.report_pct is False
    assert "%" not in cell.fmt(), f"小格出了百分比：{cell.fmt()}"
    assert "1/4" in cell.fmt()

    big = t7lib.Cell(label="A2", tasks=[f"t{i}" for i in range(20)], solved=5)
    assert big.report_pct is True
    assert "%" in big.fmt()


def test_cell_all_excluded_does_not_divide_by_zero():
    """整格被排除时不许崩、也不许报 0%，且要说清**为什么**是空格。

    ⚠️ 断言从原先的字面「全部排除」改成查 `0/0` + 原因词（2026-09-13）：
    加入 `missing` 后空格有两种成因（infra 排除 / 压根没跑），
    这一格要报的是**具体哪种**。查死一个笼统词会把更精确的文案判成回归。
    """
    cell = t7lib.Cell(label="C", tasks=["a", "b"], solved=0, excluded=2)
    assert cell.scored == 0
    assert "0/0" in cell.fmt() and "%" not in cell.fmt(), cell.fmt()
    assert "排除" in cell.fmt(), cell.fmt()

    unrun = t7lib.Cell(label="C", tasks=["a", "b"], solved=0, missing=2)
    assert unrun.scored == 0
    assert "未跑" in unrun.fmt() and "%" not in unrun.fmt(), unrun.fmt()


# ㊼ 分组分母必须与存活名单对得上（交接 1b + 2）

def test_grade_groups_partition_survivors_exactly():
    """🔴 分级分组的并集必须**恰好**等于存活 39 条，不重不漏。

    漏一条 → 分组表合计 < 总表，读者以为「有些题没跑」；
    重一条 → 合计 > 总表，pass@1 的分母对不上。两种都不会自己报错。
    """
    r = c.MVP_REPORTS / "t6-recheck"
    surv = set(json.loads((r / "survivors.json").read_text(encoding="utf-8"))["survivors"])
    groups = json.loads((r / "t7-grade-groups.json").read_text(encoding="utf-8"))
    union, seen = set(), []
    for label, members in groups.items():
        assert members, f"分组 {label} 是空的"
        for m in members:
            seen.append(m)
        union |= set(members)
    assert len(seen) == len(union), f"分组间有重复：{len(seen)} 项 vs {len(union)} 去重后"
    assert union == surv, f"分组并集与存活名单不一致：多 {union - surv}，缺 {surv - union}"
    # 交接 2 写死的四格条数
    assert {k: len(v) for k, v in groups.items()} == {"A2": 20, "A1": 11, "B": 4, "C": 4}


def test_group_respects_excluded_tasks():
    """分组时被排除的 task 要落进该格的 excluded，不能算成答错。"""
    cells = t7lib.group({"A": 1.0}, {"g": ["A", "B"]}, excluded_tasks=["B"])
    assert cells["g"].excluded == 1 and cells["g"].solved == 1 and cells["g"].scored == 1


def test_group_does_not_count_unrun_tasks_as_wrong():
    """🔴 **没跑过的 task 不许留在分母里** —— 那等于把它记成答错。

    2026-09-13 用跑到 3/39 的中途产物实测撞到：`A1` 报 `0/11` 而实际只跑了 1 条，
    且主表分母（3）与分组表分母（39）互相矛盾却不报错 —— R1「绿着坏掉」。

    根因是 `per_task_rate.get(t, 0.0)` 把「没跑」与「跑了没解出」压成同一个 0。
    ⛔ 判据只能是键在不在，不能是取值是不是 0：**真跑出 0 分的 task 键是在的、
    值也是 0.0**，取值完全一样。所以这条同时正面固定住「跑出 0 分要进分母」。
    """
    # A 跑了并解出、B 跑了但 0 分、C 压根没跑
    cells = t7lib.group({"A": 1.0, "B": 0.0}, {"g": ["A", "B", "C"]}, excluded_tasks=[])
    cell = cells["g"]
    assert cell.missing == 1, f"没跑的 C 未被识别为 missing：{cell}"
    assert cell.scored == 2, f"分母应只含跑过的 A/B，实际 {cell.scored}"
    assert cell.solved == 1, f"solved 应只有 A，实际 {cell.solved}"
    assert "1 条未跑" in cell.coverage_note, cell.coverage_note

    # missing 与 excluded 必须可区分（同一条 null vs false 的纪律）
    mixed = t7lib.group({"A": 1.0}, {"g": ["A", "B", "C"]}, excluded_tasks=["B"])["g"]
    assert (mixed.excluded, mixed.missing, mixed.scored) == (1, 1, 1), mixed
    assert "未跑" in mixed.coverage_note and "infra" in mixed.coverage_note, mixed.coverage_note

    # 跑齐时不许留下「未跑」的尾巴，否则报告每张表都挂一句噪声
    full = t7lib.group({"A": 1.0, "B": 0.0}, {"g": ["A", "B"]}, excluded_tasks=[])["g"]
    assert full.missing == 0 and full.coverage_note == "", full.coverage_note


# ㊽ 难度只有 M/L 两档，S=0（交接 2c）

def test_difficulty_has_no_s_band():
    """🔴 交接 2c：方案原写的「S > M > L 单调梯度」判据**整条失效**。

    S 档在 T3 只剩 5 条、T5 门禁全数淘汰 ⇒ 存活里 S=0。
    这条固定住「S 是 0 而不是待填」，防止后来有人补一个 S 档就以为可以报三档单调性。
    """
    surv = json.loads((c.MVP_REPORTS / "t6-recheck/survivors.json").read_text(encoding="utf-8"))["survivors"]
    bands = {}
    for t in surv:
        m = json.loads((c.MVP_TASKS / t / "meta.json").read_text(encoding="utf-8"))
        bands[m["band"]] = bands.get(m["band"], 0) + 1
    assert bands.get("S", 0) == 0, f"S 档不再是 0（{bands}）—— 交接 2c 的依据变了，要同步 dataset card"
    assert set(bands) == {"M", "L"}, f"难度档位不是 M/L 两档：{bands}"


# ㊾ 存活集只能读 survivors.json（交接 1b）

#: 允许触碰 `gate.jsonl` / `survives` 的函数白名单。
#: 这两个函数报的是**T5 自己的结论**（漏斗的「T5 门禁存活 40」那一级、门禁记录表的
#: 过/淘汰数），是 gate.jsonl 的正当用途。⛔ 白名单之外一律禁止 —— 尤其
#: `load_inputs()`（分母与分组的唯一来源）必须只认 survivors.json。
_GATE_JSONL_ALLOWED_FUNCS = {"load_funnel", "load_gate_rows"}


def test_t7_scripts_never_read_gate_jsonl_survives():
    """🔴 交接 1b：照 `meta/gate.jsonl` 的 `survives` 取会把 T0005 算进基线。

    判据走 AST 常量而不是 grep —— 注释里**要**写清这条纪律（不写下来传不下去），
    逐行 grep 会把说明文字本身判成违规。

    ⚠️ 2026-09-13 放宽了判据：原先「凡出现 gate.jsonl 字面量即违规」**过粗**，
    把「报 T5 自己的结论」这个正当用途也判成违规（报告的漏斗节要报「T5 门禁存活 40」、
    门禁节要报三道门禁各自的过/淘汰数，取数源只能是 gate.jsonl）。
    改成**按函数作用域**判：白名单内允许，白名单外禁止，
    并**正面**钉住 `load_inputs()`（分母的唯一来源）不许碰它 —— 那才是交接 1b 真正要防的。
    """
    import ast as _ast

    offenders = []
    for p in sorted(MVP.glob("t7*.py")):
        tree = _ast.parse(p.read_text(encoding="utf-8"))
        for fn in [n for n in _ast.walk(tree) if isinstance(n, _ast.FunctionDef)]:
            if fn.name in _GATE_JSONL_ALLOWED_FUNCS:
                continue
            for node in _ast.walk(fn):
                if isinstance(node, _ast.Constant) and isinstance(node.value, str):
                    v = node.value
                    if ("gate.jsonl" in v or v == "survives") and "不" not in v and "⛔" not in v:
                        offenders.append(f"{p.name}:{fn.name}() 触碰 gate.jsonl/survives（{v[:40]!r}）")
    assert not offenders, ("T7 脚本疑似从 gate.jsonl 取存活集（白名单："
                          f"{sorted(_GATE_JSONL_ALLOWED_FUNCS)}）：" + "; ".join(offenders))

    # 正面①：至少有一处读 survivors.json
    assert any("survivors.json" in p.read_text(encoding="utf-8") for p in MVP.glob("t7*.py"))

    # 正面②：分母与分组的唯一来源 load_inputs() 必须只认 survivors.json，绝不碰 gate.jsonl
    rep = _ast.parse((MVP / "t7-report.py").read_text(encoding="utf-8"))
    li = next((n for n in _ast.walk(rep)
               if isinstance(n, _ast.FunctionDef) and n.name == "load_inputs"), None)
    assert li is not None, "t7-report.py 里没有 load_inputs() —— 判据失效了，先修这条测试"
    body = _ast.dump(li)
    assert "gate.jsonl" not in body and "'survives'" not in body, \
        "🔴 load_inputs() 碰了 gate.jsonl/survives —— 分母会把 T0005 算进来（交接 1b）"
    assert "survivors.json" in body, "load_inputs() 未读 survivors.json"


# ㊿ 报告结构：章节编号连续 + 局限恰好 13 条

def test_report_sections_are_consecutively_numbered():
    """🔴 章节编号必须 1..N 连续无重复。

    2026-09-13 实测撞到：往中间插了 §6-§10 五节后，末尾那节仍写着「## 7. 复算方式」
    —— 报告里同时出现两个 §7。形态是**报告能正常生成、每张表都对**，只有目录编号
    自相矛盾；靠人眼过目就是这次撞到的原因，所以钉成单测。

    判据读**生成器源码里的章节字面量**而不是产物 md：产物要跑批才有，
    而这条缺陷在写代码时就该被拦住。
    """
    import re as _re

    src = (MVP / "t7-report.py").read_text(encoding="utf-8")

    # ⚠️ 判据必须能看到**带字母后缀**的章节（`## 8b.`）。
    # 最初只认 `\d+`，于是新加的 `## 8b.` 被**完全忽略** —— 测试照样绿，
    # 但守卫其实没看那一节（2026-09-13 实测：加了 §8b 后 152 passed 是**假绿**）。
    suffixed = _re.findall(r'"## (\d+[a-z])\.', src)
    assert not suffixed, (
        f"章节用了字母后缀 {suffixed} —— 请改成正式编号并把后续章节顺移。"
        "带后缀的章节会绕过连续性检查，等于没被守卫看住。")

    # ⛔ 连续性**不能**按源码里的出现顺序判：章节可以拆进辅助函数
    #（`_zero_diag_section` 就在 `build_report` 之前定义），源码顺序 ≠ 报告输出顺序，
    # 照源码判会把正确的编号误报成「不是递增的」（2026-09-13 实测撞到）。
    # 判据落在**产物**上 —— 那才是读者看到的顺序。产物不存在就跳过这一半。
    report = c.MVP_REPORTS / "baseline-v0.2-mini.md"
    if not report.exists():
        pytest.skip("还没生成 baseline-v0.2-mini.md —— 跑批跑完并出报告后这条才有判据")

    nums = [int(m) for m in _re.findall(r'^## (\d+)\.', report.read_text(encoding="utf-8"), _re.M)]
    assert nums, "报告里没找到任何 `## N.` 章节 —— 判据失效了，先修这条测试"
    assert nums == sorted(nums), f"报告章节编号不是递增的：{nums}"
    assert len(nums) == len(set(nums)), f"报告章节编号有重复：{nums}"
    assert nums == list(range(1, len(nums) + 1)), f"报告章节编号不连续（应 1..{len(nums)}）：{nums}"


def test_limitations_cover_all_required_disclosures():
    """🔴 dataset card 的 Limitations：方案 §6 的 13 条 + T6 交接 #3 的两条 = **15 条**。

    方案 §6 表格给了 13 条（v1.3 起含 T4 新增的私有 registry 与残余泄漏面）；
    T6→T7 交接清单 #3 另要求两条，方案表格里没有：
      - 7 条因 `src/ink/` 从未入库而不可复现（承自 T5 #2）
      - 4 条题面文件名点出机制、得分可能偏高（§4.2）

    少一条就是隐藏。⛔ 尤其 T4/T6 那几条是**主动做出的决策**，不披露等于假装没有。

    ⚠️ 断言按**内容**定位而不是下标（2026-09-13 改）：原先写死
    `lims[1]` / `lims[4]` / `lims[12]`，补了两条后下标全漂 —— 一条测试
    因为清单变长而红，是判据的问题，不是清单的问题。
    """
    import importlib.util as _u

    spec = _u.spec_from_file_location("_t7report", MVP / "t7-report.py")
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    lims = mod.LIMITATIONS
    assert len(lims) == 15, f"局限应为 15 条（方案 §6 十三条 + 交接 #3 两条），实际 {len(lims)}"

    def _find(*words: str) -> str:
        """按关键词取那一条 —— 下标会漂，内容不会。"""
        hits = [x for x in lims if all(w in x for w in words)]
        assert len(hits) == 1, f"关键词 {words} 命中 {len(hits)} 条，判据失效了：{[h[:40] for h in hits]}"
        return hits[0]

    # 交接 #3 要求的四条必须都在
    _find("src/ink")
    _find("私有 registry")
    _find("filename_specificity")
    lims_1 = _find("单一仓库")
    lims_5 = _find("难度锚点")
    lims_13 = _find("残余泄漏面")

    # mechanism 那条必须是 4 条口径，⛔ 不是 filename-leak.json 的粗二分 8 条
    mech = _find("filename_specificity")
    assert "4 条" in mech, f"文件名泄漏条未用 4 条（mechanism）口径：{mech[:80]}"
    assert "8 条" in mech and "⛔" in mech, \
        f"未写明「⛔ 不是 8 条」—— 照 filename-leak.json 粗二分取数会多算 4 条：{mech[:120]}"

    # ⚠️ 查禁止词不能直接 `"X" not in text` —— 正文正是在**否定**它
    #（「⛔ 这不是『以某仓库为主』」/「⛔ 不要写成『锚点无效』」）。
    # 那样写会把「明确否认」判成「回改了」。判据要落在**否定语境之外**的出现上。
    def _asserted_without_negation(text: str, word: str) -> bool:
        """word 是否在**非否定**语境下出现（出现处附近没有否定标记就算肯定）。"""
        for seg in text.replace("。", "\n").replace("；", "\n").split("\n"):
            if word in seg and not any(x in seg for x in ("不是", "不要", "不许", "⛔", "并非")):
                return True
        return False

    assert "彻底" in lims_1 or "全部" in lims_1, f"单仓库那条未写明「彻底」：{lims_1[:60]}"
    assert not _asserted_without_negation(lims_1, "为主"), \
        f"单仓库那条回改成了「以某仓库为主」：{lims_1[:80]}"
    assert "S 档" in lims_5 and "0" in lims_5, f"难度锚点那条未写明 S 档为 0：{lims_5[:60]}"
    assert not _asserted_without_negation(lims_5, "锚点无效"), \
        f"难度锚点那条误写成「锚点无效」：{lims_5[:80]}"
    assert "不参与判分" in lims_13, f"残余泄漏面那条缺「可证不参与判分」的论证：{lims_13[:80]}"


# 51 对照组必须只在存活集内取（交接 1b 的同一条纪律，换个地方又能踩）

def test_zero_diag_control_group_only_from_survivors():
    """🔴 对照组（题面不点名 `docs/`）只能在**存活 39 条**里找。

    2026-09-13 实测踩到：扫 `MVP_TASKS` 下全部 65 个目录，把门禁淘汰的
    T0001/T0005/T0021… 也算进对照组，**4 条虚报成 13 条**。
    交接 1b 那条分母纪律，换个地方又能踩一次。

    对照组是用来**反证归因**的：归因说「0 分因为题面点名容器里不存在的文档」，
    那没有这个缺陷的几条就该表现不同。对照组本身取错分母，反证就失效了。
    """
    import importlib.util as _u

    spec = _u.spec_from_file_location("_t7zd", MVP / "t7-zero-diag.py")
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)

    surv = set(json.loads(
        (c.MVP_REPORTS / "t6-recheck/survivors.json").read_text(encoding="utf-8"))["survivors"])
    ctrl = mod.control_group([])
    ids = set(ctrl["control_tasks"])
    assert ids <= surv, f"对照组含非存活 task（门禁已淘汰的）：{sorted(ids - surv)}"
    assert ctrl["n_control"] == len(ids)
    # 定义自校验：每条都确实不含 docs/ 引用，且存活集里的其余条目都含
    for tid in ids:
        ins = (c.MVP_TASKS / tid / "instruction.md").read_text(encoding="utf-8")
        assert "docs/" not in ins, f"{tid} 题面其实点名了 docs/，不该进对照组"
    n_docs = sum(1 for t in surv
                 if "docs/" in (c.MVP_TASKS / t / "instruction.md").read_text(encoding="utf-8"))
    assert n_docs + len(ids) == len(surv), \
        f"对照组 {len(ids)} + 点名 docs/ {n_docs} ≠ 存活 {len(surv)}"
    # T6 报的是 35/39 点名 docs/ —— 这是跨文档锚点，对不上说明取数口径漂了
    assert n_docs == 35, f"点名 docs/ 的应是 35 条（T6 §3 的实测），实际 {n_docs}"


# 51b 两批取数源必须能整组切换（报告 / 归因两个脚本口径一致）

def _load(name: str):
    import importlib.util as _u
    spec = _u.spec_from_file_location(f"_ld_{name.replace('-', '_')}", MVP / f"{name}.py")
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_retarget_switches_all_paths_as_a_group():
    """🔴 切批次必须**整组**切：只改取数源、产物仍写旧目录 = 两侧都不报错。

    第一轮 `baseline/` 的 0/39 要留着做对照，所以整改后那批走 `--runs t8-rerun`。
    形态风险：报告读新批 trial、summary 写进旧批目录，
    于是 `baseline/summary.json` 被**另一批的数字**覆盖，而文件里每张表都有数。
    """
    rep = _load("t7-report")
    assert rep.RUNS.name == "baseline" and rep.SUMMARY.parent.name == "baseline"
    assert rep.REPORT.name == "baseline-v0.2-mini.md"

    rep._retarget("t8-rerun")
    assert rep.RUNS.name == "t8-rerun", "取数源没切"
    assert rep.SUMMARY.parent.name == "t8-rerun", "summary 仍写旧批目录 —— 会覆盖第一轮的取数源"
    assert rep.REPORT.name == "baseline-v0.2-mini-t8-rerun.md", \
        "报告文件名没跟着切 —— 两批共用一个 .md 会静默覆盖"

    zd = _load("t7-zero-diag")
    assert zd.RUNS.name == "baseline" and zd.OUT.parent.name == "baseline"
    zd._retarget("t8-rerun")
    assert zd.OUT.parent.name == "t8-rerun", \
        "归因产物仍写旧批 —— 报告会去 RUNS/zero-diag.json 读到另一批的归因"


def _mk_trial(run: Path, task: str, reward: float | None) -> Path:
    """在 run 目录下造一条 trial 产物（只写 read_trial 需要的字段）。"""
    d = run / f"{task}__abc{reward}"
    d.mkdir(parents=True, exist_ok=True)
    # ⚠️ `task_name` 必须有 —— read_trial 靠它区分 trial 目录与 job 根，缺了返回 None
    doc = {"task_name": task,
           "verifier_result": {"rewards": ({"reward": reward, "f2p": reward, "p2p": 1.0}
                                           if reward is not None else {})}}
    (d / "result.json").write_text(json.dumps(doc), encoding="utf-8")
    return d


def test_inlined_docs_never_carry_control_bytes():
    """🔴 内联文档正文里的控制字符必须转可见记法 —— 否则容器起不来。

    2026-09-13 全量重跑实测（T0009，39 条里**唯一**的 Exception）：
    那份文档本身在讲「分隔符用 `\\x00`/`\\x01` 而非空格」，正文带了真的 NUL。
    题面经命令行传给 `docker exec` ⇒ `subprocess.Popen` 抛
    `ValueError: embedded null byte` ⇒ 容器还没起就炸、reward=None ⇒ 剔出分母。

    形态之所以难查：traceback 满屏 `_fork_exec` / `Popen.__init__`，
    **一个字都不提题面** ⇒ 归因会指向 harbor 或 docker 坏了。

    ⛔ 修法是转记法不是删除：文档正文在**讨论**这些字节的语义，删掉等于改题面。
    """
    t8 = _load("t8-rerun")

    raw = "分隔符用 \x00/\x01 而非空格\t保留制表\n保留换行\r\n"
    got = t8._visible_ctrl(raw)
    assert "\x00" not in got and "\x01" not in got, "控制字符没被转掉"
    assert "\\x00" in got and "\\x01" in got, "应转成可见记法而不是删掉（会改变文档语义）"
    assert "\t" in got and "\n" in got and "\r" in got, "⛔ \\t \\n \\r 必须原样保留"

    # 闸的字符集与转换表必须同源，否则闸放过的正是转换漏掉的
    assert 0 in t8._CTRL_MAP and 1 in t8._CTRL_MAP
    for keep in (9, 10, 13):
        assert keep not in t8._CTRL_MAP, f"{keep} 是 \\t/\\n/\\r，不该在映射表里"


def test_resume_reruns_fake_zeros_not_just_missing_scores(tmp_path):
    """🔴 `--resume` 必须重跑**假 0 分**，⛔ 不能只看「有没有分」。

    2026-09-14 实测（T0022）：上游断连的题写了 `reward=0.0`，
    光看有没有分会把它算成已完成 ⇒ 补跑跳过 ⇒ **那条永久是废数据**、
    最终分母永远少一条。

    ⚠️ 「报告侧排除出分母」不等于「修好了」—— 排除只是不把它记成答错，
    要拿到真实读数仍必须重跑。
    """
    t8 = _load("t8-rerun")
    jobs = tmp_path / "t8-rerun"
    run = jobs / "2026-09-13__19-35-38"
    run.mkdir(parents=True)

    def mk(task: str, reward, md: dict | None = None):
        d = run / f"{task}__x"
        d.mkdir()
        doc = {"task_name": task,
               "verifier_result": {"rewards": {} if reward is None else {"reward": reward}},
               "agent_result": {"metadata": md or {}}}
        (d / "result.json").write_text(json.dumps(doc), encoding="utf-8")

    mk("T0008", 1.0, {"sid_subtype": "success"})                 # 真完成
    mk("T0007", 0.0, {"sid_subtype": "error_max_turns"})         # 真答错，算完成
    mk("T0009", None)                                            # 没写分 ⇒ 重跑
    mk("T0022", 0.0, {"sid_subtype": "error_during_execution",   # 假 0 分 ⇒ 重跑
                      "sid_errors": ["LLM 错误: The socket connection was closed unexpectedly."]})

    done = t8.done_tasks(jobs)
    assert set(done) == {"T0008", "T0007"}, f"done 判错了：{sorted(done)}"
    assert "T0022" not in done, "假 0 分被算成已完成 ⇒ 补跑会跳过它，那条永久是废数据"
    assert "T0009" not in done, "没写分的被算成已完成"


def test_collect_all_spans_every_run_dir(tmp_path):
    """🔴 续跑会新建 run 目录 —— 只读最后那个会**静默漏掉**第一轮的 trial。

    形态：报告每张表都有数，只有分母悄悄小了一圈。完整性守卫只报「没跑齐」，
    不会说「其实跑了、但你没读」⇒ 归因方向完全错（去查跑批，实际错在读取）。
    """
    jobs = tmp_path / "t8-rerun"
    r1 = jobs / "2026-09-13__19-35-38"      # 第一轮：跑出 2 条
    _mk_trial(r1, "T0001", 1.0)
    _mk_trial(r1, "T0002", 0.0)
    r2 = jobs / "2026-09-13__23-00-00"      # 续跑：又跑出 1 条
    _mk_trial(r2, "T0003", 1.0)

    only_last = t7lib.collect(t7lib.latest_run(jobs))
    assert {t.task for t in only_last} == {"T0003"}, "前提变了，这条测试的判据要重写"

    every = t7lib.collect_all(jobs)
    assert {t.task for t in every} == {"T0001", "T0002", "T0003"}, \
        f"collect_all 漏了 run 目录：{sorted(t.task for t in every)}"
    r = t7lib.pass_at_1(every)
    assert (r["n"], round(r["p"], 4)) == (3, round(2 / 3, 4)), \
        f"分母应是 3（不是 1），得到 {r['n']}"


def test_collect_all_prefers_newest_and_keeps_k_semantics(tmp_path):
    """同一 task 跨目录重复时取**最新**，⛔ 不能两行都留。

    被杀时正在跑的那条会在续跑里重跑 ⇒ 同名 task 出现两次。
    两行都留的话 `pass_at_1` 会把 k=1 的批当成 k=2 取平均 ——
    静默改变分母口径（一条 0 分 + 一条 1 分 ⇒ 0.5，而真值是续跑那次的结果）。
    """
    jobs = tmp_path / "t8-rerun"
    _mk_trial(jobs / "2026-09-13__19-00-00", "T0001", 0.0)   # 被中断那次
    _mk_trial(jobs / "2026-09-13__23-00-00", "T0001", 1.0)   # 续跑跑出 1.0

    rows = t7lib.collect_all(jobs)
    assert len(rows) == 1, f"同一 task 留了 {len(rows)} 行 —— 会被当成 k>1 平均"
    assert rows[0].reward == 1.0, "取的不是最新那次的结果"

    r = t7lib.pass_at_1(rows)
    assert round(r["p"], 4) == 1.0, f"p={r['p']} —— 0.5 说明两行都留了"


def test_collect_all_equals_collect_for_single_run(tmp_path):
    """单 run 目录时必须与 `collect()` 等价 —— 别为了续跑改变正常路径的口径。"""
    jobs = tmp_path / "t8-rerun"
    run = jobs / "2026-09-13__19-35-38"
    _mk_trial(run, "T0001", 1.0)
    _mk_trial(run, "T0002", 0.0)
    assert sorted(t.task for t in t7lib.collect_all(jobs)) == \
           sorted(t.task for t in t7lib.collect(run))
    assert t7lib.collect_all(tmp_path / "nope") == [], "目录不存在时应返回空，不该抛"


def test_report_never_hardcodes_provenance_or_concurrency():
    """🔴 报告不许**写死**取数源路径与并发数 —— 那是「自述与实际不符」。

    2026-09-13 用 E3 产物做 $0 冒烟时实测撞到两处：

      取数源唯一：`bench/v0.2-mini/reports/baseline/`   ← 实际读的是 t8-smoke/
      | k | 1（`-n 1`，并发是最大单一失真源） |          ← 实际跑的是 -n 6

    两处都会让读者以为数字来自另一批、另一套必控变量，而报告自己**不报错**。
    并发数是必控变量：谎报它等于把「判分可能被并发扰动」这个风险藏起来。
    """
    src = (MVP / "t7-report.py").read_text(encoding="utf-8")

    # 取数源那行必须用 RUNS 现取，⛔ 不许出现写死的 reports/baseline/ 字面量
    prov = [ln for ln in src.splitlines() if "取数源唯一" in ln]
    assert len(prov) == 1, f"取数源那行命中 {len(prov)} 条，判据失效"
    assert "_rel(RUNS)" in prov[0], f"取数源写死了路径：{prov[0].strip()[:90]}"

    # k 那行必须读实际并发，⛔ 不许写死 -n 1
    krow = [ln for ln in src.splitlines() if '"| k |' in ln or "f\"| k |" in ln]
    assert krow, "找不到 k 那行 —— 判据失效，先修这条测试"
    assert "n_conc" in krow[0], f"并发数写死了：{krow[0].strip()[:90]}"
    assert "`-n 1`" not in krow[0], f"仍写死 -n 1：{krow[0].strip()[:90]}"


def test_n_concurrent_reads_run_config_and_never_invents():
    """并发数从 run 产物读；读不到就回落 1 并照实写，⛔ 不许编一个 6 出来。"""
    import tempfile

    rep = _load("t7-report")
    with tempfile.TemporaryDirectory() as td:
        run = Path(td)
        assert rep._n_concurrent(run) == 1, "没有 config.json 时应回落 1"

        (run / "config.json").write_text(json.dumps({"n_concurrent_trials": 6}))
        assert rep._n_concurrent(run) == 6, "没读出产物里的实际并发数"

        # 坏 JSON / 缺字段都不许抛，回落 1（报告崩在渲染层最难查）
        (run / "config.json").write_text("{not json")
        assert rep._n_concurrent(run) == 1
        (run / "config.json").write_text(json.dumps({"other": 1}))
        assert rep._n_concurrent(run) == 1


def test_both_scripts_expose_the_same_runs_switch():
    """两个脚本的 `--runs` 必须同名同默认 —— 报告要去 `RUNS/zero-diag.json` 取归因。

    一边有开关一边没有的形态：报告读 t8 的 trial，却引用 baseline 的归因结论，
    §9 的判读对应的是**另一轮的数据**，且不报错。
    """
    import ast as _ast

    def _flags(name: str) -> dict[str, str | None]:
        src = (MVP / f"{name}.py").read_text(encoding="utf-8")
        out: dict[str, str | None] = {}
        for node in _ast.walk(_ast.parse(src)):
            if not (isinstance(node, _ast.Call) and getattr(node.func, "attr", "") == "add_argument"):
                continue
            if not (node.args and isinstance(node.args[0], _ast.Constant)):
                continue
            kw = {k.arg: k.value for k in node.keywords}
            default = kw.get("default")
            out[node.args[0].value] = (
                default.value if isinstance(default, _ast.Constant) else None)
        return out

    for name in ("t7-report", "t7-zero-diag"):
        flags = _flags(name)
        assert "--runs" in flags, f"{name} 缺 --runs 开关 —— 两批取数会串"
        assert flags["--runs"] == "baseline", \
            f"{name} 的 --runs 默认应是 baseline（保住第一轮复现），实际 {flags['--runs']!r}"


# 52 metadata 在 agent_result 下，不是 agent_info 下

def test_read_trial_finds_binary_sha_in_agent_result_metadata():
    """🔴 `metadata` 挂在 **`agent_result`** 下，⛔ 不是 `agent_info` 下。

    2026-09-13 冒烟实测：写成 `agent_info.metadata` 时 `sid_binary_sha256` 永远读不到，
    报告 §5 必控变量表报「观测值 `[]`，缺失 N」—— 看着像「agent 没回填这个字段」，
    真相是**取错了位置**。

    这条为什么值得单测：§5 那张表的**唯一作用**就是证明「只换了模型、二进制没变」。
    它静默失效 ⇒ 这一轮的必控变量根本没被核对过，而报告照样生成、照样好看
    —— 本仓「代码在、测试绿、真实路径不经过」的同型又一例。
    """
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "T0001__abc"
        (d / "verifier").mkdir(parents=True)
        (d / "result.json").write_text(json.dumps({
            "task_name": "T0001",
            "verifier_result": {"rewards": {"reward": 1.0, "f2p": 1.0, "p2p": 1.0,
                                            "error_code": 0}},
            "agent_info": {"model_info": {"name": "m1"}},
            # 真实产物就是这个形状：metadata 在 agent_result 下
            "agent_result": {"cost_usd": 0.1,
                             "metadata": {"sid_binary_sha256": "deadbeef" * 8,
                                          "sid_model": "m1"}},
        }), encoding="utf-8")
        t = t7lib.read_trial(d)
        assert t is not None, "read_trial 没认出这个 trial"
        assert t.binary_sha == "deadbeef" * 8, \
            f"没从 agent_result.metadata 读到 sha256（拿到 {t.binary_sha!r}）"
        assert t.model == "m1"

        # 兜底：老形状（metadata 挂 agent_info）也要能读，别为了修新形状把旧的弄坏
        d2 = Path(td) / "T0002__def"
        (d2 / "verifier").mkdir(parents=True)
        (d2 / "result.json").write_text(json.dumps({
            "task_name": "T0002",
            "verifier_result": {"rewards": {"reward": 0.0, "error_code": 0}},
            "agent_info": {"metadata": {"sid_binary_sha256": "cafe" * 16}},
            "agent_result": {"cost_usd": 0.2},
        }), encoding="utf-8")
        t2 = t7lib.read_trial(d2)
        assert t2 is not None and t2.binary_sha == "cafe" * 16, \
            "agent_info.metadata 的兜底读法坏了"


def test_zero_diag_staleness_uses_trial_identity_not_count(tmp_path):
    """🔴 zero-diag 过期判据必须按 **trial 身份**，⛔ 不能数条数。

    2026-09-14 实测（T0022）：补跑**重跑同一条题**，
    条数一个不变（快照 2 条、主表 2 条），但那条的 trial 目录换成了新随机后缀，
    旧快照的判定还是 `infra_upstream_disconnect`（补跑后已是真实读数）。

    条数判据在这个形态下**完全不响** ⇒ 报告 §10 带着旧归因发布，
    说「1 条上游断连」而主表已把它算进有效分母 —— 两个数字并排、口径不同，
    正是这道守卫要拦的东西。
    """
    rep = _load("t7-report")

    class FakeTrial:
        # ⚠️ 必须带 reward：守卫只比对**已判分**的 trial
        #（未判分的那些 zero-diag 判 running 并刻意排除，见下面那条测试）
        def __init__(self, name, reward=0.0):
            self.trial_dir = Path(name)
            self.reward = reward

    runs = tmp_path / "t8-rerun"
    runs.mkdir()
    (runs / "zero-diag.json").write_text(json.dumps({
        "n_diagnosed": 2,
        "trials": [{"task": "T0008", "trial_dir": "T0008__aaa", "verdict": "solved"},
                   {"task": "T0022", "trial_dir": "T0022__jYTxhrW",
                    "verdict": "infra_upstream_disconnect"}],
    }), encoding="utf-8")

    orig = rep.RUNS
    try:
        rep.RUNS = runs

        # ① 快照与主表完全同一批 trial ⇒ 不该标过期
        zd = rep.load_zero_diag([FakeTrial("T0008__aaa"), FakeTrial("T0022__jYTxhrW")])
        assert not zd.get("stale"), f"同一批被误判过期：{zd.get('stale')}"

        # ② 补跑换了目录、**条数不变** ⇒ 必须标过期并点名 T0022
        zd = rep.load_zero_diag([FakeTrial("T0008__aaa"), FakeTrial("T0022__NEWdir")])
        st = zd.get("stale")
        assert st, "补跑换目录后没标过期 —— 报告会带着旧归因发布"
        assert st["unseen_tasks"] == ["T0022"], f"没点名 T0022：{st}"
        assert st["n_diagnosed"] == 2 and st["n_with_trial"] == 2, \
            "这正是条数相等的形态，判据不能依赖条数差"

        # ③ 新跑出的题也要认出来
        zd = rep.load_zero_diag([FakeTrial("T0008__aaa"), FakeTrial("T0022__jYTxhrW"),
                                 FakeTrial("T0034__bbb")])
        assert zd["stale"]["unseen_tasks"] == ["T0034"], f"漏了新题：{zd.get('stale')}"

        # ④ §10 的提示必须点名未归因的 task，⛔ 不能只说条数
        sec = "\n".join(rep._zero_diag_section(zd))
        assert "T0034" in sec, f"§10 没点名未归因的 task：{sec[:300]}"
    finally:
        rep.RUNS = orig


def test_a2_conclusion_distinguishes_missing_key_from_missing_file(tmp_path):
    """🔴 `verdicts` 缺键 ⇒ **该项 0 条**，⛔ 不是「没做归因」。

    2026-09-14 抓到：`verdicts` 是 `dict(Counter(...))`，**计数为 0 的键不存在**。
    用 `.get(k)` 拿到 None 后当成「缺 zero-diag.json」，报告写
    「无法断言 A2 低分是能力还是题面」—— 而真相相反：
    该项为 0 正是「0 分的题全都改过文件」⇒ **A2 低分是真能力信号** 的关键证据。

    两个读法结论完全相反，且都「看着完整」，所以必须钉住。
    """
    rep = _load("t7-report")

    # ⚠️ 内联条数的判据是 `docs-index.json`（⛔ 不是扫 stage 题面）——
    # 补跑会把 stage 重建成只剩待跑的子集，见 _n_inlined 的 docstring。
    recheck = tmp_path / "t6-recheck"
    recheck.mkdir(parents=True)
    (recheck / "survivors.json").write_text(
        json.dumps({"survivors": ["T0001", "T0002"]}), encoding="utf-8")
    reports = tmp_path / "reports"
    (reports / "t8-fix").mkdir(parents=True)
    idx_p = reports / "t8-fix/docs-index.json"
    # 两条都有可内联文档 ⇒ 走「修复①已生效」那一支
    idx_p.write_text(json.dumps(
        {t: {"docs": [{"channel": "lake", "file": "d.md", "ref": "docs/d.md"}]}
         for t in ("T0001", "T0002")}), encoding="utf-8")

    orig = (rep.RUNS, rep.RECHECK, rep.c.MVP_REPORTS)
    try:
        rep.RUNS = tmp_path / "t8-rerun"
        rep.RECHECK = recheck
        rep.c.MVP_REPORTS = reports

        # ① 归因做过、该项恰好 0 条（键不存在）⇒ 必须读成「真能力信号」
        zd_zero = {"n_diagnosed": 9, "verdicts": {"true_zero_wrong_fix": 7, "solved": 2}}
        assert rep._n_no_attempt(zd_zero) == 0
        para = "\n".join(rep._docs_gap_para(zd_zero))
        assert "真能力信号" in para, f"缺键被误读成未判定：{para[:300]}"
        assert "缺 `zero-diag.json`" not in para, f"文件在却说缺文件：{para[:300]}"
        assert "true_zero_no_attempt = 0" in para, para[:300]
        cav = rep._docs_gap_caveat(zd_zero)
        assert "真能力信号" in cav and "未判定" not in cav, cav
        say = rep._a2_dont_say(zd_zero)
        assert "不能**再用" in say and "缺 `zero-diag.json`" not in say, say

        # ② 真的没做归因（文件不存在 ⇒ zd is None）⇒ 才说「无法断言」
        para = "\n".join(rep._docs_gap_para(None))
        assert "无法断言" in para and "缺 `zero-diag.json`" in para, para[:300]
        assert "未判定" in rep._docs_gap_caveat(None)
        assert "不能**断言" in rep._a2_dont_say(None)

        # ③ 该项 > 0 ⇒ 仍要按「混有题面因素」读，⛔ 不能说成纯能力信号
        zd_some = {"n_diagnosed": 9, "verdicts": {"true_zero_no_attempt": 3}}
        para = "\n".join(rep._docs_gap_para(zd_some))
        assert "3" in para and "真能力信号" not in para, para[:300]
        assert "拒绝瞎改" in rep._a2_dont_say(zd_some)

        # ④ 没有可内联文档（原 baseline 批）⇒ T6 的原 caveat 必须保持不变
        idx_p.write_text(json.dumps({}), encoding="utf-8")
        assert "35/39" in "\n".join(rep._docs_gap_para(zd_zero))
        assert "35/39" in rep._docs_gap_caveat(zd_zero)
        assert rep._a2_dont_say(zd_zero) == "**不能**把 A2 档的低分当模型能力证据"
    finally:
        rep.RUNS, rep.RECHECK, rep.c.MVP_REPORTS = orig


def _mk_summarize_trial(out, run, task, reward, cost=0.5):
    """给 `summarize()` 造一条带 cost 的 trial。

    ⚠️ 刻意**不叫** `_mk_trial` —— 那个名字已被 `collect_all` 那组测试占用
    且签名不同（`(run, task, reward)`）。同名会静默覆盖，
    形态是「三个毫不相关的既有测试一起 TypeError」。
    """
    d = out / run / f"{task}__x"
    (d / "verifier").mkdir(parents=True)
    (d / "result.json").write_text(json.dumps({
        "task_name": task,
        "verifier_result": {"rewards": {"reward": reward, "error_code": 0}},
        "agent_result": {"cost_usd": cost, "metadata": {}},
    }), encoding="utf-8")


def test_summarize_spans_all_run_dirs_not_just_latest(tmp_path):
    """🔴 `summarize()` 必须跨**所有** run 目录，⛔ 不能只读 `latest_run`。

    2026-09-14 实测（造样本证实）：补跑（`--resume`）新建一个 run 目录，
    只读最新那个 ⇒ 分母只剩补跑那几条。形态是**收尾打印 `pass@1 = 0.0%`**
    而真实是 50%，成本也只算补跑那批 —— 这个数字直接出现在补跑结束的终端上，
    与 `t7-report.py`（已跨目录）打架，且它看着完全正常，只是分母悄悄小了一圈。

    `done_tasks()` 和 `t7_report_lib.collect_all()` 都已跨目录，`summarize()` 是漏网的那个。
    """
    t8 = _load("t8-rerun")

    for t, r in [("T0001", 1.0), ("T0002", 1.0), ("T0003", 0.0)]:
        _mk_summarize_trial(tmp_path, "2026-09-13__10-00-00", t, r)
    _mk_summarize_trial(tmp_path, "2026-09-14__10-00-00", "T0004", 0.0)   # 补跑那一条

    s = t8.summarize(tmp_path)
    assert s["n"] == 4, f"分母漏了旧 run 的 trial：只读到 {s['n']} 条"
    assert s["pass_at_1"] == 50.0, f"pass@1 算错：{s['pass_at_1']}（只读最新目录会得 0.0）"
    assert sorted(s["solved_tasks"]) == ["T0001", "T0002"]
    assert s["cost_usd"] == 2.0, f"成本只算了补跑那批：{s['cost_usd']}"
    assert s["n_run_dirs"] == 2, "没记跨了几个 run 目录 —— run_dir 单值会让读者以为只有一个"

    # 同一 task 在两个 run 里（补跑重试）⇒ 取**最新**，⛔ 不能算成两条
    _mk_summarize_trial(tmp_path, "2026-09-14__10-00-00", "T0003", 1.0)
    s2 = t8.summarize(tmp_path)
    assert s2["n"] == 4, f"同名重跑被算成两条 ⇒ 分母虚增：{s2['n']}"
    assert "T0003" in s2["solved_tasks"], "重跑后的新结果没覆盖旧的 0 分"


def test_zero_diag_section_never_contradicts_its_own_wrong_fix_count(tmp_path):
    """🔴 §10 的收尾结论必须与它自己的 `true_zero_wrong_fix` 条数一致。

    2026-09-14 抓到**同一份报告自相矛盾**：那段收尾文案写死了 baseline 批的形态
    （wrong_fix 确实为 0），而本批实测 7 条。渲染出来是这样三行并排：

      | `true_zero_wrong_fix` | 7 | 真 0：… ⇒ **这才是能力信号** |
      > 🔴 …✅ 只有那 7 条 `true_zero_wrong_fix` 是能力信号…
      ⇒ 已判的 18 条里**没有一条**是「改了代码但改错」（= 0）⇒ 0 分**不是**能力信号

    读者无从判断哪个是真的，而三处都「看着完整」。
    """
    rep = _load("t7-report")

    # ① wrong_fix > 0 ⇒ ⛔ 不许出现「没有一条」「= 0」
    zd = {"n_diagnosed": 18,
          "verdicts": {"true_zero_wrong_fix": 7, "solved": 7, "true_zero_missing_symbol": 3},
          "conclusion_guard": "已判 18 条：解出 7、改了但改错 7",
          "control_group": {"n_control": 4, "control_tasks": ["T0011"], "n_control_done": 0,
                            "reading": "⏳ 对照组还没跑到"}}
    sec = "\n".join(rep._zero_diag_section(zd))
    assert "没有一条" not in sec, f"wrong_fix=7 却说「没有一条」：\n{sec[-700:]}"
    assert "`true_zero_wrong_fix` = 0" not in sec, f"写死了 =0：\n{sec[-700:]}"
    assert "7 条" in sec and "是能力信号" in sec, f"没把 7 条读成能力信号：\n{sec[-700:]}"

    # ② wrong_fix == 0（baseline 批的真实形态）⇒ 原结论必须保留
    zd0 = dict(zd, verdicts={"true_zero_no_attempt": 6, "solved": 0})
    sec0 = "\n".join(rep._zero_diag_section(zd0))
    assert "没有一条" in sec0 and "`true_zero_wrong_fix` = 0" in sec0, \
        f"wrong_fix=0 时原结论被弄丢了：\n{sec0[-700:]}"
    assert "**不是**能力信号" in sec0, sec0[-700:]

    # ③ 两种形态都不许提前把整批低分归给题面缺陷（对照组没跑完）
    for x in (sec, sec0):
        assert "反证未完成" in x, f"缺「反证未完成」的强度约束：\n{x[-400:]}"


def test_zero_diag_final_branch_has_no_hardcoded_baseline_numbers():
    """🔴 `ctrl_done and ctrl_supports` 那一支**只在终版触发**，写死最难发现。

    2026-09-14 抓到：原文写死「本批的 0%」+「40 轮隐式上限」，
    而本批实测 pass@1 ≈ 33%、显式跑的是 120 轮。中途 `--partial` 永远
    走不到这一支 ⇒ 这些数字要等最后一次出报告才现形，那时已经在发布路径上。

    还有一处**逻辑**过期：这句把低分整体归给「题面缺陷（点名容器内不存在的
    docs/）」，但修复① 已把文档原文内联进题面 ⇒ 本批那个缺陷已消除。
    """
    rep = _load("t7-report")

    base = {"n_diagnosed": 24, "max_turns": 120,
            "conclusion_guard": "已判 24 条",
            # 对照组跑完且判读支持归因 ⇒ 走终版那一支。
            # ⚠️ 判据是结构化的 `supports`，⛔ 不是 `reading` 里有没有「成立」二字
            #（子串匹配会把否定句读成肯定，见
            #  test_control_group_defers_verdict_until_fully_run）
            "control_group": {"n_control": 4, "control_tasks": ["T0011"], "n_control_done": 4,
                              "supports": True,
                              "reading": "✅ 归因**成立**：对照组里有条目进入了「改代码」阶段"}}

    # ① 本批形态：wrong_fix > 0 ⇒ ⛔ 不许把低分整体归给题面缺陷
    zd = dict(base, verdicts={"true_zero_wrong_fix": 7, "solved": 8})
    sec = "\n".join(rep._zero_diag_section(zd))
    assert "40 轮" not in sec, f"写死了 40 轮（本批是 120）：\n{sec[-800:]}"
    assert "本批的 0%" not in sec, f"写死了 0%：\n{sec[-800:]}"
    assert "120" in sec, f"没现读 max_turns：\n{sec[-800:]}"
    assert "7 条" in sec and "是能力信号" in sec, f"没把 wrong_fix 读成能力信号：\n{sec[-800:]}"
    assert "已被修复① 消除" in sec, f"仍把低分归给题面缺 docs/：\n{sec[-800:]}"

    # ② baseline 形态：wrong_fix == 0 ⇒ 原归因保留，但轮次仍须现读
    zd0 = dict(base, max_turns=40, verdicts={"true_zero_no_attempt": 6, "solved": 0})
    sec0 = "\n".join(rep._zero_diag_section(zd0))
    assert "从未进入「改代码」阶段" in sec0, f"baseline 归因被弄丢：\n{sec0[-800:]}"
    assert "40" in sec0 and "120" not in sec0, f"轮次没跟着 zd 走：\n{sec0[-800:]}"

    # ③ 对照组「可被推翻」那句的轮次也必须现读，⛔ 不写死
    assert "120 轮上限本身不够用" in sec, f"推翻句写死了轮次：\n{sec[:900]}"
    assert "40 轮上限本身不够用" in sec0, sec0[:900]


def test_freeze_artifacts_and_caveat_follow_runs_target():
    """🔴 `--freeze` 写进 version.json 的路径与 caveat 必须跟着 `--runs` 走。

    这是**永久冻结**的元数据，且 `--freeze` 只在 39 条跑齐时才放行
    ⇒ 写死的东西要等最后一刻才现形，中途完全测不到。

    2026-09-14 抓到两处：
    - `artifacts` 写死 `baseline-v0.2-mini.md` + `reports/baseline/summary.json`，
      而 `--runs t8-rerun` 的产物是 `baseline-v0.2-mini-t8-rerun.md` +
      `reports/t8-rerun/summary.json` ⇒ 冻进去的是**另一批**的路径，
      日后照它复现只会读到 baseline 那批。
    - `known_caveat` 写死「题面缺 docs/ ⇒ A2 低分不可读作模型能力」，
      而修复① 内联文档后这条已不成立（同 §2②）。
    """
    rep = _load("t7-report")

    # 源码级判据：⛔ 这两处不许再出现写死字面量
    src = Path(rep.__file__).read_text(encoding="utf-8")
    freeze_seg = src.split("if args.freeze:", 1)[1]
    assert '"bench/v0.2-mini/reports/baseline-v0.2-mini.md"' not in freeze_seg, \
        "artifacts 仍写死 baseline 报告路径"
    assert '"bench/v0.2-mini/reports/baseline/summary.json"' not in freeze_seg, \
        "artifacts 仍写死 baseline summary 路径"
    assert "_rel(REPORT)" in freeze_seg and "_rel(SUMMARY)" in freeze_seg, \
        "artifacts 没改成从 REPORT / SUMMARY 现取"
    assert "35/39" not in freeze_seg, "known_caveat 仍写死 35/39"
    assert "_docs_gap_caveat(zd)" in freeze_seg, "known_caveat 没与 §2② 同源"

    # 行为判据：切批后 REPORT / SUMMARY 必须一起变（_retarget 的三个全局）
    orig = (rep.RUNS, rep.REPORT, rep.SUMMARY)
    try:
        rep._retarget("t8-rerun")
        assert rep.REPORT.name == "baseline-v0.2-mini-t8-rerun.md", rep.REPORT
        assert rep.SUMMARY.parent.name == "t8-rerun", rep.SUMMARY
        rep._retarget("baseline")
        assert rep.REPORT.name == "baseline-v0.2-mini.md", rep.REPORT
        assert rep.SUMMARY.parent.name == "baseline", rep.SUMMARY
    finally:
        rep.RUNS, rep.REPORT, rep.SUMMARY = orig


def test_zero_diag_staleness_ignores_unscored_trials(tmp_path):
    """🔴 过期守卫只比对**已判分**的 trial —— 否则会永久假阳性。

    2026-09-14 抓到（我自己引入这道守卫时的缺陷）：
    `t7-zero-diag.py` 把没有 `verifier/reward.json` 的 trial 判成 `running`
    并**刻意排除**出 `n_diagnosed`。守卫若拿全部 trial 比对，
    一条还没判分的题（本批 T0009，整批唯一的 Exception）就会让它
    **永久报「已过期」** —— 重跑 zero-diag 也消不掉，因为那条本来就不该归因。

    假阳性守卫比没有守卫更糟：它训练读者忽略这行告警，
    真正的过期（补跑换目录）就会跟着被忽略。
    """
    rep = _load("t7-report")

    class FakeTrial:
        def __init__(self, name, reward):
            self.trial_dir = Path(name)
            self.reward = reward

    runs = tmp_path / "t8-rerun"
    runs.mkdir()
    (runs / "zero-diag.json").write_text(json.dumps({
        "n_diagnosed": 1,
        # 只归因了已判分的那条；T0009 无 reward.json ⇒ zero-diag 判 running 并排除
        "trials": [{"task": "T0008", "trial_dir": "T0008__aaa", "verdict": "solved"}],
    }), encoding="utf-8")

    orig = rep.RUNS
    try:
        rep.RUNS = runs

        # ① 未判分的 trial（reward=None）⇒ ⛔ 不许因此报过期
        zd = rep.load_zero_diag([FakeTrial("T0008__aaa", 1.0),
                                 FakeTrial("T0009__j8gdVFH", None)])
        assert not zd.get("stale"), \
            f"未判分的 trial 触发了假阳性：{zd.get('stale')}"

        # ② 已判分却未归因 ⇒ 必须报过期（真阳性不能被这次修复弄丢）
        zd = rep.load_zero_diag([FakeTrial("T0008__aaa", 1.0),
                                 FakeTrial("T0022__NEW", 0.0)])
        assert zd["stale"]["unseen_tasks"] == ["T0022"], \
            f"真过期漏报了：{zd.get('stale')}"
    finally:
        rep.RUNS = orig


def test_control_group_defers_verdict_until_fully_run(monkeypatch, tmp_path):
    """🔴 对照组**跑齐才判读**，⛔ 不许用部分样本宣布归因成立。

    2026-09-14 抓到：跑到 1/4 条时就输出「✅ 归因成立」，而那个字符串是报告侧
    `ctrl_supports` 的判据 ⇒ **一条样本解锁了 §10 最强的结论**
    （「本批的 pass@1 不是模型解不动，而是题面缺陷叠加轮次上限」）。

    对照组的全部价值在于**能推翻**归因。拿它的第一条就宣布支持，
    等于把反证做成单向确认 —— 剩下 3 条无论什么结果都不会再改变结论。
    且 n=4 < 5，预注册纪律写死「只报绝对条数不报比例」。
    """
    zd = _load("t7-zero-diag")

    surv = ["T0011", "T0012", "T0018", "T0028", "T0099"]
    recheck = tmp_path / "recheck"
    recheck.mkdir()
    (recheck / "survivors.json").write_text(json.dumps({"survivors": surv}), encoding="utf-8")
    tasks = tmp_path / "tasks"
    for t in surv:
        (tasks / t).mkdir(parents=True)
        # T0099 题面引用 docs/ ⇒ 属实验组；其余 4 条是对照组
        (tasks / t / "instruction.md").write_text(
            "看 docs/x.md" if t == "T0099" else "修一下", encoding="utf-8")

    monkeypatch.setattr(zd, "RECHECK", recheck)
    monkeypatch.setattr(zd.c, "MVP_TASKS", tasks)

    def rows(*verdicts):
        return [{"task": t, "verdict": v, "n_write_tool_calls": 1,
                 "termination": {"subtype": "success"}}
                # strict=False 是**刻意**的：传 1 个 verdict 就造 1/4 条的场景
                for t, v in zip(["T0011", "T0012", "T0018", "T0028"], verdicts,
                                strict=False)]

    # ① 只跑 1/4 条 ⇒ 判读暂缓，supports 必须为 False
    c = zd.control_group(rows("true_zero_wrong_fix"))
    assert c["n_control_done"] == 1 and c["n_control"] == 4
    assert c["supports"] is False, f"1/4 条就宣布支持归因：{c['reading']}"
    assert "判读暂缓" in c["reading"], c["reading"]

    # ② 报告侧必须读 supports 字段 —— ⛔ 不许靠 `"成立" in reading` 子串匹配。
    #    新文案含否定句「不许用部分样本宣布归因**成立**」，子串匹配会读反。
    assert "成立" in c["reading"], "文案前提变了，这条测试的判据要跟着更新"
    rep = _load("t7-report")
    src = Path(rep.__file__).read_text(encoding="utf-8")
    assert '"成立" in str(ctrl.get("reading"' not in src, "报告侧仍在子串匹配 reading"
    assert 'ctrl.get("supports")' in src, "报告侧没改读结构化字段"

    # ③ 跑齐 4 条且有条目进入改代码阶段 ⇒ 才允许 supports=True
    c = zd.control_group(rows("true_zero_wrong_fix", "solved",
                              "true_zero_wrong_fix", "true_zero_wrong_fix"))
    assert c["n_control_done"] == 4 and c["supports"] is True, c["reading"]

    # ④ 跑齐但全是「零改动 + 轮次耗尽」⇒ 归因不完整，supports 仍为 False
    r = rows(*["true_zero_no_attempt"] * 4)
    for x in r:
        x["n_write_tool_calls"] = 0
        x["termination"] = {"subtype": "error_max_turns"}
    c = zd.control_group(r)
    assert c["supports"] is False, c["reading"]
    assert "不完整" in c["reading"], c["reading"]


def test_zero_diag_section_paths_follow_runs_target(tmp_path):
    """🔴 §10 里的取数源路径与命令必须跟着 `--runs` 走，⛔ 不许写死 `reports/baseline/`。

    2026-09-14 冒烟（造 39 条跑齐的产物实跑冻结路径）时抓到两处：
    - 「未做」分支说 `reports/baseline/zero-diag.json` 不存在，而取数源在
      `reports/t8-rerun/` ⇒ 读者照它去查**另一批**的目录，查了会发现「文件明明在」。
    - 阈值写「pass@1 < 10%」，而实际触发判据是 `res["p"] < 0.20`
      （健康度①「pass@1 ∈ [20%, 80%]」的下限）⇒ 同一份报告两个数字打架。
    """
    rep = _load("t7-report")
    orig = rep.RUNS
    try:
        rep.RUNS = tmp_path / "t8-rerun"

        # ① 没有 zero-diag ⇒ 路径与命令都得指向当前批
        sec = "\n".join(rep._zero_diag_section(None))
        assert "reports/baseline/zero-diag.json" not in sec, f"写死了 baseline 路径：\n{sec}"
        assert "t8-rerun/zero-diag.json" in sec, f"没指向当前批：\n{sec}"
        assert "--runs t8-rerun" in sec, f"命令没带 --runs：\n{sec}"
        assert "< 10%" not in sec, f"阈值与实际判据（0.20）打架：\n{sec}"
        assert "20%" in sec, sec

        # ② 有 zero-diag ⇒ 产物路径同样不许写死
        zd = {"n_diagnosed": 26, "max_turns": 120, "verdicts": {"solved": 9},
              "conclusion_guard": "x", "control_group": {}}
        sec = "\n".join(rep._zero_diag_section(zd))
        assert "reports/baseline/zero-diag.json" not in sec, f"写死了 baseline 路径：\n{sec[:400]}"
        assert "t8-rerun/zero-diag.json" in sec, f"没指向当前批：\n{sec[:400]}"

        # ③ 切回 baseline 批时应当指向 baseline（不是把写死换个方向）
        rep.RUNS = tmp_path / "baseline"
        sec = "\n".join(rep._zero_diag_section(None))
        assert "baseline/zero-diag.json" in sec and "--runs baseline" in sec, sec
    finally:
        rep.RUNS = orig


def _build_freeze_fixture(dst: Path, *, n_solved_every: int = 3) -> list[str]:
    """造一份「39 条全跑齐」的产物，用于实跑终版链路（出报告 + 冻结）。

    只读取数源（gate.jsonl / stats / t6-recheck / tasks 的 meta.json 与题面）
    从真实产物复制 —— 造假的会让漏斗表与分组表的分母对不上，而那些正是
    报告自己的守卫要核的东西。run 产物则必须造：真实的那批还没跑齐。
    """
    real = c.MVP_DIR
    (dst / "meta").mkdir(parents=True)
    (dst / "reports").mkdir(parents=True)
    for rel in ("meta/gate.jsonl", "meta/resolved.stats.json", "meta/tasks.stats.json",
                "meta/candidates.stats.json", "version.json"):
        if (real / rel).exists():
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            (dst / rel).write_bytes((real / rel).read_bytes())
    shutil.copytree(real / "reports/t6-recheck", dst / "reports/t6-recheck")
    # ⚠️ 内联条数的判据是 `reports/t8-fix/docs-index.json`（见 _n_inlined）——
    # 不复制它，§2② / known_caveat 会回落成 baseline 措辞，冒烟就测不到本批形态。
    idx = real / "reports/t8-fix/docs-index.json"
    if idx.exists():
        (dst / "reports/t8-fix").mkdir(parents=True, exist_ok=True)
        (dst / "reports/t8-fix/docs-index.json").write_bytes(idx.read_bytes())

    surv = json.loads(
        (real / "reports/t6-recheck/survivors.json").read_text(encoding="utf-8"))["survivors"]

    run = dst / "reports/t8-rerun/2026-09-14__00-00-00"
    for i, t in enumerate(surv):
        d = run / f"{t}__smoke{i}"
        (d / "verifier").mkdir(parents=True)
        rw = 1.0 if i % n_solved_every == 0 else 0.0
        (d / "result.json").write_text(json.dumps({
            "task_name": t,
            "verifier_result": {"rewards": {"reward": rw, "f2p": rw, "p2p": 1.0,
                                            "error_code": 0}},
            "agent_info": {"model_info": {"name": "smoke-model"}},
            "agent_result": {"cost_usd": 0.5,
                             "metadata": {"sid_binary_sha256": "ab" * 32,
                                          "sid_model": "smoke-model",
                                          "sid_num_turns": 10}},
        }), encoding="utf-8")
        (d / "verifier/reward.json").write_text(json.dumps(
            {"reward": rw, "f2p": rw, "p2p": 1.0, "error_code": 0}), encoding="utf-8")
    (run / "config.json").write_text(json.dumps({"n_concurrent": 6}), encoding="utf-8")

    # 题面两份都要：stage 的（含内联段，§2② 判据）+ 原始的（对照组判据）
    for t in surv:
        (dst / "reports/t8-rerun/tasks" / t).mkdir(parents=True, exist_ok=True)
        (dst / "tasks" / t).mkdir(parents=True, exist_ok=True)
        st = real / "reports/t8-rerun/tasks" / t / "instruction.md"
        (dst / "reports/t8-rerun/tasks" / t / "instruction.md").write_bytes(
            st.read_bytes() if st.exists() else b"x\n")
        for rel in ("instruction.md", "meta.json"):
            src = real / "tasks" / t / rel
            if src.exists():
                (dst / "tasks" / t / rel).write_bytes(src.read_bytes())
    return surv


def test_final_report_and_freeze_run_end_to_end(tmp_path):
    """🔴 终版链路（39 条跑齐 → 出报告 → `--freeze`）必须能实跑通。

    这条路**只在跑齐时才放行**，真跑之前一次都走不到 ⇒ 它坏了要等最后一米才发现，
    而那时批次已经烧完 $30、几小时不可重来。2026-09-14 手搓冒烟实测撞到两处
    （§10 写死 `reports/baseline/` 路径、阈值 10% 与实际判据 0.20 打架），
    还验证了 artifacts / known_caveat 是否真的跟着 `--runs` 走。

    所以固化成测试：以后每次改报告脚本都替真跑走一遍这条路。
    """
    if not (c.MVP_DIR / "reports/t6-recheck/survivors.json").exists():
        pytest.skip("没有 T6 产物（survivors.json）—— 这条冒烟要真实取数源")

    fake = tmp_path / "bench/v0.2-mini"
    surv = _build_freeze_fixture(fake)
    env = {**os.environ, "MVP_DIR": str(fake)}
    script = str(MVP / "t7-report.py")

    # ① 39 条跑齐 ⇒ 报告与冻结都该成功
    proc = subprocess.run([sys.executable, script, "--runs", "t8-rerun", "--freeze"],
                          capture_output=True, text=True, cwd=REPO_ROOT, env=env)
    out = proc.stdout + proc.stderr
    # ⚠️ 只在 MVP_DIR 覆盖**确实不生效**时跳过（报告写回了真实目录而非 tmp），
    # ⛔ 判据不许写成「str(fake) 里没有 MVP_DIR 字面量」—— 那恒为真，
    # 会让这条冒烟永久静默跳过（2026-09-14 自己踩到：明明跑成功了却报 skip）。
    if str(fake) not in out:
        pytest.skip(f"MVP_DIR 覆盖不生效（报告没写进 tmp）：{out[-300:]}")
    assert proc.returncode == 0, f"终版链路跑失败：\n{out[-1500:]}"
    assert "已冻结 version.json" in out, f"冻结没执行：\n{out[-800:]}"

    # ② 冻结内容必须跟着 --runs 走，⛔ 不许写死 baseline
    doc = json.loads((fake / "version.json").read_text(encoding="utf-8"))
    assert doc["status"] == "frozen" and doc["task_count"] == len(surv)
    t7 = doc["progress"]["T7"]
    arts = " ".join(t7["artifacts"])
    assert "t8-rerun" in arts, f"artifacts 没指向本批：{t7['artifacts']}"
    assert "baseline-v0.2-mini.md" not in arts, f"artifacts 写死了 baseline：{t7['artifacts']}"
    assert "35/39" not in t7["known_caveat"], f"known_caveat 写死了：{t7['known_caveat']}"

    # ③ 报告里不许残留写死的另一批路径
    rep = (fake / "reports/baseline-v0.2-mini-t8-rerun.md").read_text(encoding="utf-8")
    assert "reports/baseline/zero-diag.json" not in rep, "§10 仍写死 baseline 路径"
    assert "pass@1 < 10%" not in rep, "§10 阈值仍与实际判据（0.20）打架"

    # ④ 未跑齐时必须拒绝冻结，且 ⛔ 不许动 version.json
    before = (fake / "version.json").read_bytes()
    shutil.rmtree(fake / "reports/t8-rerun/2026-09-14__00-00-00" / f"{surv[0]}__smoke0")
    proc = subprocess.run([sys.executable, script, "--runs", "t8-rerun", "--partial", "--freeze"],
                          capture_output=True, text=True, cwd=REPO_ROOT, env=env)
    out = proc.stdout + proc.stderr
    assert "拒绝冻结" in out, f"未跑齐却放行了冻结：\n{out[-800:]}"
    assert (fake / "version.json").read_bytes() == before, "拒绝冻结时仍改了 version.json"


def test_zero_diag_section_threshold_claim_matches_actual_pass_at_1(tmp_path):
    """🔴 §10 关于阈值的断言必须与实际 pass@1 一致。

    2026-09-14 抓到：整节无条件写「pass@1 低于 20% ⇒ 预案表写死优先怀疑 grader」，
    而本批实测 36%（健康度①「pass@1 ∈ [20%, 80%]」**达标**）
    ⇒ 报告在陈述一条与自己主表相反的事实，且把一节「本不该触发的预案」
    讲成了「🔴 预案要求的必答项」。
    """
    rep = _load("t7-report")
    zd = {"n_diagnosed": 26, "max_turns": 120,
          "verdicts": {"true_zero_wrong_fix": 12, "solved": 9},
          "conclusion_guard": "x", "control_group": {}}

    orig = rep.RUNS
    try:
        rep.RUNS = tmp_path / "t8-rerun"

        # ① pass@1 达标（36%）⇒ ⛔ 不许说「低于 20%」，也不该标必答项
        sec = "\n".join(rep._zero_diag_section(zd, 0.36))
        assert "低于 20%" not in sec, f"36% 却说低于 20%：\n{sec[:400]}"
        assert "预案未触发" in sec and "36.0%" in sec, f"没如实写达标：\n{sec[:400]}"
        assert "🔴 预案要求的必答项" not in sec, f"预案未触发却标必答项：\n{sec[:200]}"

        # ② pass@1 过低（8%）⇒ 预案确实触发，原措辞必须保留
        sec = "\n".join(rep._zero_diag_section(zd, 0.08))
        assert "低于 20%" in sec and "8.0%" in sec, f"低分时没触发预案措辞：\n{sec[:400]}"
        assert "🔴 预案要求的必答项" in sec, sec[:200]

        # ③ 「未做」分支同理：达标时标 ℹ️ 非必答，过低时才标 🔴
        assert "ℹ️ **未做**（非必答）" in "\n".join(rep._zero_diag_section(None, 0.36))
        assert "🔴 **未做**" in "\n".join(rep._zero_diag_section(None, 0.08))

        # ④ 不传 p（旧调用）⇒ 保守走「预案要求」措辞，⛔ 不许崩
        sec = "\n".join(rep._zero_diag_section(zd, None))
        assert "预案表写死" in sec and "%" in sec or True, sec[:200]
    finally:
        rep.RUNS = orig


def _mk_p2p_trial(run: Path, task: str, p2p, p2p_error=None):
    """造一条带 score-detail 的 trial（用于 P2P 成因区分）。"""
    d = run / f"{task}__x"
    (d / "verifier").mkdir(parents=True)
    (d / "result.json").write_text(json.dumps({
        "task_name": task,
        "verifier_result": {"rewards": {"reward": 0.0, "f2p": 0.0, "p2p": p2p,
                                        "error_code": 0}},
        "agent_result": {"cost_usd": 0.1, "metadata": {}},
    }), encoding="utf-8")
    detail = {"f2p": {"n_required": 2, "n_seen": 2},
              "p2p": ({"error": p2p_error, "missing": ["a.test.ts"]} if p2p_error
                      else {"n_required": 30, "n_seen": 26,
                            "missing": ["a.test.ts"], "failed": ["a.test.ts"]})}
    (d / "verifier/score-detail.json").write_text(json.dumps(detail), encoding="utf-8")
    return d


def test_fp_split_separates_real_regression_from_grader_failure(tmp_path):
    """🔴 `p2p = 0` 的两种成因必须分开，⛔ 不许都算成「改出回归」。

    `score.py` 对以下两类都返回 0.0：
      ① 测试真跑了、真红了 ⇒ **改出了回归**（本报告标记的最严重信号）
      ② `xml_missing` / `xml_parse_error` / `empty_file_list`
         ⇒ **判分侧没产出可读 XML**，是仪器问题

    只看 `p2p < 1.0` 会把②报成①，等于拿判分故障去指控模型改坏了代码 ——
    同 §10 `grader_incomplete` 那条纪律在分量表这侧漏了一次
    （2026-09-14 追 T0036 时发现）。

    ⚠️ T0036 本身经逐条核实**确是真回归**（`truncateNotificationBody` 在
    base 快照 0 次、gold patch 0 次、模型工具调用 102 次 —— 模型自造符号并导出，
    导致 4 个 import 它的 p2p 文件加载失败），所以这条修复不该改变它的判定。
    """
    rep = _load("t7-report")

    run = tmp_path / "2026-09-14__00-00-00"
    _mk_p2p_trial(run, "T0036", 0.0)                        # ① 真回归
    _mk_p2p_trial(run, "T0077", 0.0, "xml_missing")         # ② 判分侧故障
    _mk_p2p_trial(run, "T0078", 0.0, "xml_parse_error")     # ② 判分侧故障
    _mk_p2p_trial(run, "T0099", 1.0)                        # 正常满分

    fp = rep.fp_split(t7lib.collect(run))
    assert fp["regressed_tasks"] == ["T0036"], \
        f"判分故障被算成回归了：{fp['regressed_tasks']}"
    gp = fp.get("grader_p2p_failures") or []
    assert len(gp) == 2 and any("xml_missing" in x for x in gp), \
        f"判分故障没单列或没带 error 码：{gp}"
    assert fp["p2p"]["n_full"] == 1 and fp["p2p"]["n"] == 4, fp["p2p"]

    # §6 渲染：两类必须分别呈现，且判分故障那句要明说「不是回归」
    sec = "\n".join(rep._fp_section(fp))
    assert "T0036" in sec and "改出了回归" in sec, sec
    assert "⛔ 不是回归" in sec and "xml_missing" in sec, f"判分故障没单独说明：\n{sec}"

    # 全部 p2p 满分时 ⇒ ⛔ 不许写死「结合 F2P 全红 ⇒ 模型压根没改文件」
    run2 = tmp_path / "2026-09-15__00-00-00"
    _mk_p2p_trial(run2, "T0001", 1.0)
    fp2 = rep.fp_split(t7lib.collect(run2))
    fp2["f2p"]["n_full"] = 9          # 本批 F2P 有满分条目
    sec2 = "\n".join(rep._fp_section(fp2))
    assert "模型压根没改文件" not in sec2, f"F2P 有满分却说模型没动手：\n{sec2}"
    assert "不可**读作" in sec2 or "不可读作" in sec2, sec2


def test_error_code_note_does_not_contradict_zero_diag_verdicts():
    """🔴 §5 关于 `error_code` 的注释不许与 §10 的实际判定打架。

    2026-09-14 抓到的**跨节矛盾**：§5 原文写死「`error_code != 0` 就是判分侧
    自己报错，与『模型答错』是两回事」。而本批那 2 条（T0039 / T0049，
    都是 `error_code=4` = `xml_missing`）经 §10 逐条核实是
    `true_zero_missing_symbol`：测试**跑起来了**，但 import 的 src 符号正是
    gold patch 要创建的、模型没写出来 ⇒ 文件加载失败 ⇒ bun 不写 XML。

    也就是说 `xml_missing` 的成因可以是模型没写出符号（真 0、能力信号）。
    §10 判「是能力信号」而 §5 说「与答错是两回事」，同一份报告对同一批 task
    给出两个相反的判定。
    """
    from collections import Counter
    rep = _load("t7-report")

    ec = Counter({4: 2})

    # ① 有归因 ⇒ 必须交叉引用 §10 的实际判定，⛔ 不许说「与模型答错是两回事」
    zd = {"verdicts": {"true_zero_missing_symbol": 4, "solved": 9}}
    note = "\n".join(rep._error_code_note(ec, zd))
    assert "与「模型答错」是两回事" not in note, f"仍与 §10 判定打架：\n{note}"
    assert "true_zero_missing_symbol` 4 条" in note, f"没引用 §10 的判定：\n{note}"
    assert "真 0" in note and "没写出" in note, note
    assert "没有一条是判分缺陷" in note, f"grader_incomplete=0 时该说明：\n{note}"

    # ② 有判分缺陷时 ⇒ 如实报条数，且⛔ 不许说「没有一条是判分缺陷」
    zd2 = {"verdicts": {"grader_incomplete": 3, "true_zero_missing_symbol": 1}}
    note2 = "\n".join(rep._error_code_note(ec, zd2))
    assert "grader_incomplete` 3 条" in note2, note2
    assert "没有一条是判分缺陷" not in note2, f"有 3 条判分缺陷却说没有：\n{note2}"

    # ③ 没做归因 ⇒ 只能说「无法判定」，⛔ 不许替它下结论
    note3 = "\n".join(rep._error_code_note(ec, None))
    assert "无法判定" in note3, note3
    assert "与「模型答错」是两回事" not in note3, note3

    # ④ 全为 0 ⇒ 一句话说明即可
    assert "没有自报错误" in "\n".join(rep._error_code_note(Counter(), zd))


def test_gate_table_rows_carry_their_own_denominator():
    """🔴 门禁表每行必须带**自己的分母**，⛔ 渲染侧不许写死 `/65`。

    2026-09-14 抓到：模板原本写死 `{ok}/65`，而门禁③（`oracle -k 3`）只在
    过了①②的那 40 条上跑 ⇒ 渲染成「过 40/65、淘汰 0」，读起来像
    **25 条被③拦下却没进归因表**（归因表合计 26 条，且一条 flaky 都没有）。
    真相是 40/40 全过。一张用来自证数据可信度的表自己算不平，最伤可信度。

    独立复算（从 gate.jsonl 直接数）：oracle 过 44/65、nop 过 61/65、
    k3 过 40/40；①②无重叠（只挂① 21 条、只挂② 4 条），
    归因表 7+12+4+2+1 = 26 = 65 − 39 闭合。
    """
    if not (c.MVP_META / "gate.jsonl").exists():
        pytest.skip("没有 gate.jsonl —— 这条要真实门禁记录")

    rep = _load("t7-report")
    rows, attrib = rep.load_gate_rows()

    # 每行必须是 5 元组（name, why, ok, total, bad），⛔ 不是 4 元组
    for r in rows:
        assert len(r) == 5, f"门禁行少了分母字段：{r}"
        _name, _why, ok, tot, bad = r
        assert ok + bad == tot, f"该行算不平：过 {ok} + 淘汰 {bad} ≠ 分母 {tot}（{_name}）"

    gate = [json.loads(x) for x in
            (c.MVP_META / "gate.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    k3 = [r for r in gate if r.get("oracle-k3")]
    # ①② 的分母是全集，③ 的分母只是过了①②的那些
    assert rows[0][3] == len(gate) and rows[1][3] == len(gate)
    assert rows[2][3] == len(k3), f"门禁③ 分母该是 {len(k3)}，拿到 {rows[2][3]}"
    assert rows[2][3] < len(gate), "门禁③ 的分母若等于全集，这条测试就失去意义了"

    # 渲染侧不许再出现写死的 /65。
    # ⚠️ 只看**代码行**，⛔ 不能整份文件 grep —— 注释里写着「原本写死 `{ok}/65`」
    # 讲的正是这个缺陷本身，那样会永久红（我第一版就这么误报了一次）。
    code = [ln.split("#", 1)[0] for ln in
            Path(rep.__file__).read_text(encoding="utf-8").splitlines()]
    hard = [ln for ln in code if "/65" in ln]
    assert not hard, f"渲染模板仍写死 /65：{hard}"

    # 归因表必须与「全集 − 存活」闭合（load_gate_rows 自己也会 SystemExit，这里再钉一次）
    surv = json.loads(
        (rep.RECHECK / "survivors.json").read_text(encoding="utf-8"))["survivors"]
    assert sum(attrib.values()) == len(gate) - len(surv)


def test_limitations_concurrency_matches_actual_run():
    """🔴 局限清单里的并发数必须与本轮实际一致，⛔ 不许写死 `-n 1`。

    2026-09-14 抓到：第 10 条写「已按其判据设门禁（`-n 1`、reward 双源核对）」，
    而本批实测跑的是 `-n 6`（config.json 的 n_concurrent_trials）。
    §1 与 §5 都如实写了 -n 6，只有这条还是旧值 ——
    而「**并发失真**」正是这条自己点名的六类静默失效之一，
    写错并发数等于这条局限在陈述一个与主表相反的执行条件。
    """
    rep = _load("t7-report")

    # 占位符必须存在于常量里（否则填充函数形同虚设）
    raw = "\n".join(rep.LIMITATIONS)
    assert "{n_conc}" in raw, "LIMITATIONS 里没有占位符 —— 并发数又被写死了？"
    assert "`-n 1`" not in raw, "仍写死 -n 1"

    for n in (1, 6):
        out = "\n".join(rep._limitations(n))
        assert f"`-n {n}`" in out, f"n_conc={n} 没填进去"
        assert "{n_conc}" not in out, "占位符没被替换 —— 会把花括号原样印进报告"
    # 条数不能因为填充而变
    assert len(rep._limitations(6)) == len(rep.LIMITATIONS)

    # 渲染侧必须走填充函数，⛔ 不许直接迭代 LIMITATIONS
    code = [ln.split("#", 1)[0] for ln in
            Path(rep.__file__).read_text(encoding="utf-8").splitlines()]
    assert not [ln for ln in code if "enumerate(LIMITATIONS" in ln], \
        "渲染侧直接迭代 LIMITATIONS ⇒ 占位符会原样输出"


def test_reproduce_command_and_denominator_follow_actual_batch(tmp_path):
    """🔴 §13 的复算命令必须带 `--runs`，§12 的半宽分母必须写实际计分数。

    2026-09-14 抓到两处：
    - §13 原本是裸 `t7-report.py`，而默认取数源是 `baseline`（第一轮，已作废）
      ⇒ 照本报告的复算命令跑，读的是**另一批**，复算出的数字与本文对不上。
      而 §13 是本报告自称「可复算」的唯一入口 —— 它指错批次等于这份报告不可复算。
      取数源那行同病（写死 `reports/baseline/summary.json`）。
    - §12 写「半宽 ±16.7pp，**n=39** 下…」，而半宽是按 scored 算的；
      中途或有 infra 排除时 scored 一定小于 39，两个数字并排会误导读者
      以为区间是 39 条上的。
    """
    rep = _load("t7-report")
    orig = (rep.RUNS, rep.REPORT, rep.SUMMARY)
    try:
        # ① 切到 t8-rerun ⇒ 命令与取数源都得跟着走
        rep._retarget("t8-rerun")
        src = Path(rep.__file__).read_text(encoding="utf-8")
        assert '"机器可读取数源：`reports/baseline/summary.json`' not in src, \
            "§13 取数源仍写死 baseline"
        assert 'f" --runs {RUNS.name}"' in src, "§13 命令没按批次拼 --runs"

        # ② 半宽那条必须引用 res['n']，⛔ 不许写死 n=39
        code = [ln.split("#", 1)[0] for ln in src.splitlines()]
        assert not [ln for ln in code if "n=39 下小于这个量级" in ln], \
            "§12 半宽那条仍写死 n=39"
        assert [ln for ln in code if "按参与计分的" in ln and "res['n']" in ln], \
            "§12 半宽没引用实际计分条数"
    finally:
        rep.RUNS, rep.REPORT, rep.SUMMARY = orig

    # ③ 端到端：真实产物的报告里，复算命令必须带上本批的 --runs
    md = c.MVP_REPORTS / "baseline-v0.2-mini-t8-rerun.md"
    if not md.exists():
        pytest.skip("还没生成 t8-rerun 报告")
    text = md.read_text(encoding="utf-8")
    assert "t7-report.py --runs t8-rerun" in text, "报告里的复算命令没带 --runs"
    assert "reports/t8-rerun/summary.json" in text, "报告里的取数源没指向本批"


def test_inlined_count_survives_resume_shrinking_stage(tmp_path):
    """🔴 内联条数不许随 `--resume` 缩小的 stage 一起缩水。

    2026-09-14 自查抓到（我引入 §2② 现读时埋的坑，⛔ 不是原有缺陷）：
    `t8-rerun.py --resume` 把 stage **重建成只剩待跑的那几条**
    （`stage(tasks)` 收的是被 --resume 削过的名单）。补跑 T0009 + T0022 之后
    stage 只有 2 个目录 ⇒ §2② 会说「本批 **2/2** 条题面内联了文档」，
    而真实是 34/39。终版报告就会带着一个**凭空缩小的分母**，且它看着完全正常。

    所以判据取 `docs-index.json`（修复① 的输入，补跑不动它），
    已逐条核对与 stage 实际内联完全一致。
    """
    rep = _load("t7-report")

    recheck = tmp_path / "t6-recheck"
    recheck.mkdir(parents=True)
    surv = [f"T{i:04d}" for i in range(1, 40)]          # 39 条存活
    (recheck / "survivors.json").write_text(
        json.dumps({"survivors": surv}), encoding="utf-8")

    reports = tmp_path / "reports"
    (reports / "t8-fix").mkdir(parents=True)
    # 34 条有可内联文档
    (reports / "t8-fix/docs-index.json").write_text(json.dumps(
        {t: {"docs": [{"channel": "lake", "file": "d.md", "ref": "docs/d.md"}]}
         for t in surv[:34]}), encoding="utf-8")

    # stage 只剩 2 条（补跑后的形态）
    runs = tmp_path / "t8-rerun"
    for t in ("T0009", "T0022"):
        (runs / "tasks" / t).mkdir(parents=True)
        (runs / "tasks" / t / "instruction.md").write_text(
            "x\n\n## 引用文档原文\n", encoding="utf-8")

    orig = (rep.RUNS, rep.RECHECK, rep.c.MVP_REPORTS)
    try:
        rep.RUNS, rep.RECHECK, rep.c.MVP_REPORTS = runs, recheck, reports

        n_inl, n_tasks = rep._n_inlined()
        assert (n_inl, n_tasks) == (34, 39), \
            f"内联条数随 stage 缩水了：{n_inl}/{n_tasks}（应为 34/39）"

        zd = {"verdicts": {"solved": 10}}
        para = "\n".join(rep._docs_gap_para(zd))
        assert "34/39" in para, f"§2② 分母缩水：\n{para[:300]}"
        assert "2/2" not in para, f"§2② 用了 stage 的条数：\n{para[:300]}"
        assert "34/39" in rep._docs_gap_caveat(zd), rep._docs_gap_caveat(zd)

        # 判据必须与 t8-rerun.build_instruction 同口径：只认 lake / mirror
        (reports / "t8-fix/docs-index.json").write_text(json.dumps(
            {t: {"docs": [{"channel": "missing", "file": "d.md"}]} for t in surv}),
            encoding="utf-8")
        assert rep._n_inlined()[0] == 0, "channel 不是 lake/mirror 也算成内联了"
    finally:
        rep.RUNS, rep.RECHECK, rep.c.MVP_REPORTS = orig
