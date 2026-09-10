"""T5 门禁的判定与取数层 —— 与 harbor 的跑批解耦，便于单测与复算。

出处：docs-research/trajectory-platform/bench-mvp-plan.md v1.2 §4 T5

## 为什么单独一个 lib 而不是全塞进 t5-gate.sh

三道门禁的判定都是**逐 task 读 result.json 再比对**，bash 里做 json 解析既难写又
容易静默出错（`jq` 缺失时 `|| true` 会把空值当 0 分）。跑批仍由 shell 调 harbor，
判定与报告在这里，`--from-runs` 可以在既有产物上纯复算（$0，不重跑）。

## 🔴 三条取数纪律（每条都有实测代价）

① **reward 走 `verifier_result.rewards`，不是 `verifier_result.reward`**（§3.8-D）。
   后者恒为 `None`，而 `None` 在下游被 `or 0` 一吃就变成「全 0 分且不报错」。
   用 `common.read_reward()`，别自己拼路径。

② **不能看 harbor 的退出码**。TZ 期间四次失败运行的退出码全是 0。判据只有
   `Trials` / `Exceptions` 两个数，以及逐 task 的 reward。

③ **reward 双源核对**：`result.json` 的值必须与 `verifier/reward.txt` 一致。
   不一致 = 取数路径写错，不是分数变了。

## 🔴 门禁②看 f2p 分量，不是总 reward（v1.2 修正）

nop 什么都不改，P2P 本该全绿、F2P 本该全红。总 reward 是两者的与，等于 0
**无法区分**「F2P 正确失败」（task 有效）与「P2P 意外失败」（环境坏了）。
后者是快照缺文件 / 依赖装不上 / P2P 采到被剔除的测试 —— **是基础设施问题，
不要去动 task**。这两类混在一起报，会让人去改本来没坏的 task。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import common as c

#: `reward.json` 的 error_code 编码（与 t3-build-harbor-tasks.py 的两处同源）。
#: reward.json 只能放标量（T5 实测：harbor 的 rewards 是 dict[str, float | int]，
#: 放 str/dict 会让整条 trial 判 ValidationError），所以错误用数值编码。
ERROR_CODE_MEANING = {
    0: "正常跑完",
    1: "test.sh 没跑完（兜底值未被覆盖）",
    2: "test_patch 打不上",
    3: "f2p/p2p 名单为空",
    4: "junit XML 缺失（测试文件没加载起来）",
    5: "junit XML 解析失败",
}


@dataclass
class TrialRow:
    """一个 trial 的判定输入。字段名对齐 reward.json 的键，便于逐字核对。"""

    task: str
    trial_dir: Path
    reward: float | None = None
    f2p: float | None = None
    p2p: float | None = None
    error_code: int | None = None
    exception: str | None = None
    #: 源 B：verifier 自己写的 reward.txt，用于双源核对（纪律③）
    reward_txt: float | None = None

    @property
    def dual_source_ok(self) -> bool:
        """双源一致。两边都缺也算不一致 —— 那说明 verifier 根本没写分。"""
        if self.reward is None or self.reward_txt is None:
            return False
        return abs(self.reward - self.reward_txt) < 1e-9


def read_trial(trial_dir: Path) -> TrialRow | None:
    """读一个 trial 目录。不是 trial 目录（如 job 根）返回 None。"""
    result = trial_dir / "result.json"
    if not result.exists():
        return None
    try:
        doc = json.loads(result.read_text(encoding="utf-8"))
    except Exception:
        return None
    # job 根的 result.json 没有 task_name，用它来区分
    task = doc.get("task_name")
    if not task:
        return None

    rewards = (doc.get("verifier_result") or {}).get("rewards") or {}
    exc = doc.get("exception_info")
    # exception_info 的形态在 harbor 里不止一种，取到能读的那层就够判红
    exc_str = None
    if exc:
        exc_str = exc.get("exception_type") if isinstance(exc, dict) else str(exc)
        if isinstance(exc, dict) and not exc_str:
            exc_str = json.dumps(exc, ensure_ascii=False)[:200]

    txt_path = trial_dir / "verifier" / "reward.txt"
    reward_txt = None
    if txt_path.exists():
        try:
            reward_txt = float(txt_path.read_text(encoding="utf-8").strip())
        except Exception:
            reward_txt = None

    def num(key):
        v = rewards.get(key)
        return float(v) if isinstance(v, (int, float)) else None

    ec = rewards.get("error_code")
    return TrialRow(
        task=task,
        trial_dir=trial_dir,
        # 走 common.read_reward() 而不是自己从 rewards 取 —— 让纪律①只有一处实现
        reward=c.read_reward(trial_dir),
        f2p=num("f2p"),
        p2p=num("p2p"),
        error_code=int(ec) if isinstance(ec, (int, float)) else None,
        exception=exc_str,
        reward_txt=reward_txt,
    )


def collect_run(run_dir: Path) -> list[TrialRow]:
    """收一个 job 目录下所有 trial。`-k 3` 时同一 task 会有多行，刻意不去重。"""
    rows = []
    for d in sorted(Path(run_dir).iterdir()):
        if not d.is_dir():
            continue
        row = read_trial(d)
        if row is not None:
            rows.append(row)
    return rows


def latest_run(jobs_dir: Path) -> Path | None:
    """harbor 每次 run 在 `-o` 下建一个 `YYYY-MM-DD__HH-MM-SS` 目录，取最新那个。"""
    jobs_dir = Path(jobs_dir)
    if not jobs_dir.exists():
        return None
    runs = sorted(p for p in jobs_dir.iterdir() if p.is_dir() and p.name[:2] == "20")
    return runs[-1] if runs else None


# ── 三道门禁的判定 ──────────────────────────────────────────────────


@dataclass
class Verdict:
    """一条 task 在一道门禁上的结论。`ok=False` 一律附 reason，报告直接引用。"""

    task: str
    ok: bool
    reason: str = ""
    #: 基础设施问题（而非 task 问题）—— 这类**不该淘汰 task**，要去修环境
    infra: bool = False


def gate_oracle(rows: list[TrialRow]) -> list[Verdict]:
    """门禁①可解性：参考解必须全绿（reward == 1）。

    不符合说明 gold patch 打不上、或测试本身坏了 —— 两者都是 task 不可用。
    """
    out = []
    for r in rows:
        if r.exception:
            out.append(Verdict(r.task, False, f"trial 异常：{r.exception}", infra=True))
        elif not r.dual_source_ok:
            out.append(
                Verdict(
                    r.task,
                    False,
                    f"reward 双源不一致（json={r.reward} txt={r.reward_txt}）—— 取数路径或 verifier 有问题",
                    infra=True,
                )
            )
        elif r.reward == 1.0:
            out.append(Verdict(r.task, True))
        elif r.f2p == 1.0 and r.p2p != 1.0:
            # 🔴 F2P 全绿但 P2P 红 = **参考解打上后砸了别处**，与「gold patch 打不上」
            # 是两个完全不同的诊断，不能混报（2026-09-10 实测：T0017/T0027 属此类，
            # 且它们在 nop 下 P2P 是全绿的 —— 即失败由 patch 引入，不是环境本来就坏）。
            #
            # 两种可能，**必须复跑才能分辨**，所以先不判 task 死刑：
            #   ① 参考解真的引入回归 → task 该淘汰（gold patch 不干净）
            #   ② 这些 P2P 是 flaky（timing / 并发类）→ 环境问题，task 无罪
            # 标 infra=True 让它进「要复查」而不是「已淘汰」，避免误杀。
            out.append(
                Verdict(
                    r.task,
                    False,
                    f"⚠️ 参考解砸了 P2P（f2p=1 但 p2p={r.p2p}）—— "
                    f"须复跑分辨「gold patch 真引入回归」vs「P2P 是 flaky」，先不淘汰",
                    infra=True,
                )
            )
        else:
            why = ERROR_CODE_MEANING.get(r.error_code or 0, f"error_code={r.error_code}")
            side = []
            if r.f2p != 1.0:
                side.append(f"f2p={r.f2p}")
            if r.p2p != 1.0:
                side.append(f"p2p={r.p2p}")
            out.append(
                Verdict(r.task, False, f"oracle reward={r.reward}（{' '.join(side)}；{why}）")
            )
    return out


def gate_nop(rows: list[TrialRow]) -> list[Verdict]:
    """门禁②有效性：nop 下 **f2p 必须为 0 且 p2p 必须为 1**。

    🔴 看分量不看总 reward（见模块 docstring）：
      - `f2p == 1` → **假 task**：什么都不改测试就绿，F2P 不构成 fail-to-pass
      - `p2p == 0` → **坏环境**：基础设施问题，标 infra，不要去动 task
    """
    out = []
    for r in rows:
        if r.exception:
            out.append(Verdict(r.task, False, f"trial 异常：{r.exception}", infra=True))
            continue
        if not r.dual_source_ok:
            out.append(
                Verdict(
                    r.task,
                    False,
                    f"reward 双源不一致（json={r.reward} txt={r.reward_txt}）",
                    infra=True,
                )
            )
            continue
        if r.f2p == 1.0:
            out.append(
                Verdict(r.task, False, "🔴 假 task：nop 下 f2p=1，测试不改代码就绿")
            )
        elif r.p2p == 0.0:
            why = ERROR_CODE_MEANING.get(r.error_code or 0, "")
            out.append(
                Verdict(
                    r.task,
                    False,
                    f"⚠️ 坏环境：nop 下 p2p=0（{why}）—— 修环境，不要动 task",
                    infra=True,
                )
            )
        elif r.f2p == 0.0 and r.p2p == 1.0:
            out.append(Verdict(r.task, True))
        else:
            out.append(Verdict(r.task, False, f"f2p={r.f2p} p2p={r.p2p} 不在预期取值内"))
    return out


def gate_consistency(rows: list[TrialRow]) -> list[Verdict]:
    """门禁③稳定性：同一 task 多次运行的 reward 必须一致。

    不一致说明测试有随机性或依赖外部状态 —— 这种 task 会让基线数字不可复现。
    """
    by_task: dict[str, list[TrialRow]] = {}
    for r in rows:
        by_task.setdefault(r.task, []).append(r)

    out = []
    for task, group in sorted(by_task.items()):
        if any(g.exception for g in group):
            excs = [g.exception for g in group if g.exception]
            out.append(
                Verdict(task, False, f"{len(excs)}/{len(group)} 次 trial 异常：{excs[0]}", infra=True)
            )
            continue
        vals = [g.reward for g in group]
        if len(group) < 2:
            out.append(Verdict(task, False, f"只有 {len(group)} 次运行，无法判一致性", infra=True))
        elif len(set(vals)) == 1:
            out.append(Verdict(task, True, f"{len(group)} 次均为 {vals[0]}"))
        else:
            out.append(Verdict(task, False, f"{len(group)} 次结果不一致：{vals}"))
    return out


# ── 汇总 ────────────────────────────────────────────────────────────


@dataclass
class GateSummary:
    """一道门禁的汇总。`survivors` 是过了这道门的 task 名单。"""

    name: str
    verdicts: list[Verdict] = field(default_factory=list)

    @property
    def survivors(self) -> list[str]:
        return sorted(v.task for v in self.verdicts if v.ok)

    @property
    def failures(self) -> list[Verdict]:
        """淘汰的（task 自身问题）—— 真正该从交付集里去掉的。"""
        return [v for v in self.verdicts if not v.ok and not v.infra]

    @property
    def infra_issues(self) -> list[Verdict]:
        """基础设施问题 —— 要修环境后重跑，**不是** task 的错。"""
        return [v for v in self.verdicts if not v.ok and v.infra]

    def line(self) -> str:
        n = len(self.verdicts)
        return (
            f"{self.name}: {len(self.survivors)}/{n} 过；"
            f"淘汰 {len(self.failures)}；基础设施问题 {len(self.infra_issues)}"
        )


# ── 反向自证（方案 §4 T5：「v1.2 增到四条，都要做」）──────────────────


@dataclass
class SelftestCase:
    """一条反向自证：**故意破坏一处，然后要求门禁报红**。

    🔴 这个机制本身也会坏，而且坏法是**恒绿** —— T4 的
    `--selftest-substring-leak` 把阈值拍成「剔除量 > 900」而实测最大 829，
    于是它自称在检查却永远返绿（T4 交接 #6 点名的教训）。两条防线：

      ① 断言**红得对不对**，不只看 `ok=False`：还核 `infra` 与理由。
         否则「因为环境坏了而红」会被当成「因为检测生效而红」——
         这是最容易骗过自己的一种假绿。
      ② 批次里必须带一个**未变异的对照**（`M0-control`）并要求它**过**。
         若整批因构建失败而全红，对照会一起红，于是自证报的是
         「对照没过」而不是「四条全部通过」。
    """

    #: 变异体目录名 —— 就是 harbor 的 `task_name`（`LocalTaskId.get_name()` 取目录名）
    name: str
    #: 该由哪道门禁来判（决定用哪个 agent 跑）
    gate: str
    #: 门禁**应当**放它过吗
    must_pass: bool
    #: 这条自证在证明什么，进报告
    why: str
    #: 期望的 `infra` 取值（只在 must_pass=False 时校验）。
    #: `False` = 必须判成「task 自身问题」，不能混成基础设施问题。
    expect_infra: bool | None = None
    #: 理由里必须出现的字样 —— 钉住「红的原因」而不只是「红了」
    expect_reason_has: str | None = None
    #: 期望的 `reward.json` error_code（同时校验 trial **不是** error）
    expect_error_code: int | None = None


@dataclass
class SelftestOutcome:
    case: SelftestCase
    ok: bool
    detail: str


def check_selftest(
    cases: list[SelftestCase],
    verdicts: dict[str, list[Verdict]],
    rows: dict[str, list[TrialRow]],
) -> list[SelftestOutcome]:
    """核对每条反向自证是否成立。纯函数，可单测。

    「产物里找不到这个变异体」一律判**不成立** —— 没跑起来不能算通过，
    否则「变异体全都没被 harbor 发现」会静默变成「四条全绿」。
    """
    out: list[SelftestOutcome] = []
    for cs in cases:
        v = next((x for x in verdicts.get(cs.gate, []) if x.task == cs.name), None)
        if v is None:
            out.append(
                SelftestOutcome(
                    cs,
                    False,
                    f"门禁 `{cs.gate}` 的产物里找不到 `{cs.name}` —— "
                    f"没跑起来，**不算通过**",
                )
            )
            continue

        problems: list[str] = []
        if v.ok != cs.must_pass:
            problems.append(
                f"门禁判 ok={v.ok}，应为 {cs.must_pass}"
                f"（理由：{v.reason or '无'}）"
            )
        if not cs.must_pass:
            if cs.expect_infra is not None and v.infra != cs.expect_infra:
                problems.append(
                    f"infra={v.infra} 应为 {cs.expect_infra} —— **红的理由不对**，"
                    f"实际理由：{v.reason}"
                )
            if cs.expect_reason_has and cs.expect_reason_has not in v.reason:
                problems.append(
                    f"理由里没有「{cs.expect_reason_has}」，实际是「{v.reason}」"
                )
        if cs.expect_error_code is not None:
            r = next((x for x in rows.get(cs.gate, []) if x.task == cs.name), None)
            if r is None:
                problems.append("读不到 trial 行，无法核 error_code")
            else:
                if r.error_code != cs.expect_error_code:
                    problems.append(
                        f"error_code={r.error_code}，应为 {cs.expect_error_code}"
                    )
                # 方案原话：「trial 状态不是 error」—— 要 reward=0，不要 trial error
                if r.exception:
                    problems.append(
                        f"trial 判了 error（{r.exception}）—— 应当是 reward=0 而非 trial error"
                    )
        out.append(SelftestOutcome(cs, not problems, "；".join(problems) or "符合预期"))
    return out
