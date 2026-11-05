#!/usr/bin/env python3
"""T15 — v0.2.1 计分集 k=3 基线（deepseek-v4.1-flash）的**唯一可执行入口**。

方案见 docs-research `20261003-评测接入CI-CD-分层门禁与基线闭环.md` §6.6 T15。

## 与 t8-rerun.py 的关系（为什么另起一个文件）

t8-rerun 是 v0.2-mini 39 题那一批的复现入口，**要留着**（37.8% 的执行链）。
它有三处与 T15 不兼容，且都不是加个参数能补的：

  1. 题集读 `t6-recheck/survivors.json`（39 条），闸 1 硬编码 `!= 39`；
     T15 跑的是 `dist/v0.2.1/tasks`（计分集 32 题，题面已在 T04 定型，不再现场 stage）。
  2. 二进制钉死在 `bins/sid-code-*-30586ff003c9`（09 月的旧 commit）。
  3. 不支持按硬顶分档传 `max_duration_ms`（T10b 新增的墙钟预算）。

## 🔴 一轮 = 两次 harbor run（按 agent 硬顶分档）

`--ak` 对一次 run 内**所有题同值**，而 v0.2.1 的 `task.toml` `timeout_sec` 有两档：

    | 档     | 题数 | 硬顶（×3）| max_duration_ms（硬顶×0.9）|
    | 1800s  |  8   | 5400s     | 4860000                    |
    | 2700s  | 24   | 8100s     | 7290000                    |

⛔ 不要全用 4860000 跑一次：那会把 24 题的墙钟预算砍掉 40%，测的不是同一个能力。
⛔ 也不要在这里写死 8/24 —— 分档**每次从 task.toml 现算**（`tiers()`），
   题集变了这里跟着变；没见过的档直接拒跑（`DURATION_BY_TIMEOUT` 里没有）。

×0.9 的理由：留 10% 给强制总结轮 + SessionEnd 落盘（T10b 强制轮实测超出预算 18–37s），
否则到点收尾会再撞一次硬顶 ——「修了一层只是换了个杀手」（evals/CLAUDE.md §3.10）。

## 产物布局

    reports/t15-baseline/
      round1/t1800/<harbor 时间戳目录>/   ← 每轮每档一个 jobs 目录（未入库）
      round1/t2700/...
      round2/... round3/...
      fingerprints/round{r}-t{tier}.json  ← run_fingerprint.py collect 的产物

同一档跨轮的指纹必须 VALID（`run_fingerprint.py compare`）；不一致即整组作废。

## 跑前闸（复用 t7 的实现，只替换与题集/二进制/定价相关的那几条）

| 闸 | 来源 | 本文件的处理 |
|---|---|---|
| 存活集条数 | t7 闸1（`!= 39`） | ⛔ 不复用 —— 换成「计分集 = 发布目录 = version.json.task_count」 |
| 网络策略 allowlist | t7 闸2 | 同判据，读发布目录的 task.toml |
| shim 上游 / 占位 token | t7 闸3/4 | **原样 import 复用** |
| pricing | t7 闸5（读宿主 settings.json） | ⛔ 不复用：**会误报**。宿主那条没配 pricing，真实取价走 sid-code 内置注册表（`packages/core/src/llm/model-registry.ts` 的 `deepseek-v4-1-flash` 条目，剥 `origin-` 前缀命中）。T10b 两轮成本 $0.17–0.70 与历史读数同量级，证明这条链路是对的。本闸改为**宿主配了就用宿主的，没配就必须在内置注册表命中且是真价**（拒绝网关占位价 75/75） |
| 二进制 + ELF | t7 闸6（钉旧 commit） | 改为显式 `--binary`，读 ELF + 读 `build-info.json` 的 commit，dirty 拒跑 |
| 题集 digest | 新增 | 现算 `export-release.digest()` == `version.json` == `dist/v0.2.1/taskset_digest.txt` |
| 分档 | 新增 | 每题 timeout 都在 `DURATION_BY_TIMEOUT` 里，且两档非空 |
| 快照 | 新增 | 每题 `environment/repo-snapshot.tar.gz` 存在 |

## 用法

    # 只过闸，不跑（$0）。T15 开跑前**必须**先跑这一条并全绿
    ~/.local/share/uv/tools/harbor/bin/python scripts/t15-baseline.py --dry-run \\
        --binary ~/Code/person/sid-code/dist/branch-builds/main-<commit12>/sid-code

    # 正式跑：3 轮 × 2 档，用 caffeinate 包住（evals/CLAUDE.md §3.11）
    caffeinate -dimsu ~/.local/share/uv/tools/harbor/bin/python scripts/t15-baseline.py \\
        --binary <同上>

    # 中断后续跑：已判分的 (轮, 档) 整组跳过；没跑完的那一组只补没判分的题
    ... scripts/t15-baseline.py --binary <同上> --resume

    # 只跑某一轮（分天跑时用）
    ... scripts/t15-baseline.py --binary <同上> --rounds 2

⚠️ 要用 harbor 的 uv 环境里的 python（闸 2 要 `import harbor`），系统 python3 没装它。
⚠️ 不能看退出码：harbor 失败时也返 0。判据是产物里的逐题 reward。
"""

from __future__ import annotations

import argparse
import importlib.util as _ilu
import json
import os
import subprocess
import sys
import time
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402


def _load(name: str, file: str):
    spec = _ilu.spec_from_file_location(name, Path(__file__).parent / file)
    assert spec is not None and spec.loader is not None, file
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def bypass_loopback_proxy() -> None:
    """让**本进程**的 urllib 不走系统代理访问 loopback。

    🔴 2026-11-05 实测：macOS 系统代理（127.0.0.1:7881）开着时，
    `urllib.request.getproxies()` 会把它用在 `127.0.0.1:4101` 上
    （`proxy_bypass("127.0.0.1:4101")` 返回 False）⇒ 闸F/G 打到代理拿 502，
    报「shim 坏了」，而 shim 本身直连是 200。t8-rerun 只给 harbor 子进程设了
    no_proxy，跑前闸那个进程没设 —— 闸在报一个不存在的故障。
    """
    for k in ("no_proxy", "NO_PROXY"):
        cur = [x for x in os.environ.get(k, "").split(",") if x]
        for h in ("127.0.0.1", "localhost"):
            if h not in cur:
                cur.append(h)
        os.environ[k] = ",".join(cur)


# ⛔ 复用 t7 的网关常量与闸实现、export-release 的 digest 算法 —— 不复制（改一处漏一处）
t7 = _load("t7_baseline", "t7-baseline.py")
rel = _load("export_release", "export-release.py")

VERSION = rel.VERSION
DIST_TASKS = rel.DIST / "tasks"
OUT = c.MVP_REPORTS / "t15-baseline"
FP_DIR = OUT / "fingerprints"
FINGERPRINT_PY = t7.HARBOR_DIR / "run_fingerprint.py"

K_ROUNDS = 3
MAX_TURNS = 120
MAX_BUDGET_USD = "1.8"          # 与 t8-rerun 同值（论证见那里的常量注释）
AGENT_TIMEOUT_MULT = 3.0
#: ⚠️ 并发 -n 6：traj-bench verifier 是容器内本地 bun test、零网络（t8-rerun §2.3，
#: E1 实测 -n 6 判分零损伤）。evals/CLAUDE.md §3.4 的 `-n 1` 针对 verifier 要联网装 uv 的场景。
N_CONCURRENT = 6
#: 硬顶 × 0.9（见 docstring）。键 = task.toml 的 agent.timeout_sec。
DURATION_BY_TIMEOUT = {1800: 4_860_000, 2700: 7_290_000}

#: 网关采集价里出现过的占位值（USD/1M）。命中即判红：成本会高报几百倍。
PLACEHOLDER_PRICES = {75, 75.0}


# ───────────────────────────────────────────────────────────── 题集 / 分档


def scored_tasks() -> list[str]:
    return sorted(rel.scored_tasks())


def tiers(dist_tasks: Path = DIST_TASKS) -> dict[int, list[str]]:
    """{timeout_sec: [task, ...]}，**从发布目录的 task.toml 现算**。"""
    out: dict[int, list[str]] = {}
    for d in sorted(p for p in dist_tasks.iterdir() if p.is_dir()):
        cfg = tomllib.loads((d / "task.toml").read_text(encoding="utf-8"))
        sec = cfg.get("agent", {}).get("timeout_sec")
        if not isinstance(sec, (int, float)) or sec != int(sec):
            raise SystemExit(f"⛔ {d.name} 的 agent.timeout_sec 不是整数秒：{sec!r}")
        out.setdefault(int(sec), []).append(d.name)
    return out


def tier_dir(tier: int) -> Path:
    """一个档的 stage 目录（symlink 到发布目录，harbor `-p` 收「装着 task 的目录」）。"""
    return OUT / "stage" / f"t{tier}"


def stage_tier(tier: int, tasks: list[str], dist_tasks: Path = DIST_TASKS) -> Path:
    d = tier_dir(tier)
    d.mkdir(parents=True, exist_ok=True)
    for p in d.iterdir():
        if p.is_symlink():
            p.unlink()
    for t in tasks:
        (d / t).symlink_to((dist_tasks / t).resolve())
    got = sorted(p.name for p in d.iterdir())
    if got != sorted(tasks):
        raise SystemExit(f"stage t{tier} 与名单不一致：{len(got)} vs {len(tasks)}")
    return d


# ───────────────────────────────────────────────────────────── 闸


def gate_taskset() -> tuple[list[str], list[str]]:
    """计分集 = 发布目录 = version.json.task_count；digest 三处一致；快照齐全。"""
    red: list[str] = []
    want = scored_tasks()
    have = sorted(p.name for p in DIST_TASKS.iterdir() if p.is_dir()) if DIST_TASKS.exists() else []
    ver = json.loads((c.MVP_DIR / "version.json").read_text(encoding="utf-8"))
    if want != have:
        red.append(f"闸A 计分集与发布目录不一致：只在计分集 {sorted(set(want) - set(have))[:5]}，"
                   f"只在发布目录 {sorted(set(have) - set(want))[:5]} —— 重跑 export-release.py")
    if ver.get("version") != VERSION or ver.get("task_count") != len(want):
        red.append(f"闸A version.json 是 {ver.get('version')}/{ver.get('task_count')} 题，"
                   f"期望 {VERSION}/{len(want)}")
    print(f"  闸A 题集 {len(have)} 题（计分集 {len(want)}，version.json {ver.get('task_count')}）")

    live = rel.digest(rel.plan(want))
    txt = (rel.DIST / "taskset_digest.txt").read_text(encoding="utf-8").strip() \
        if (rel.DIST / "taskset_digest.txt").exists() else None
    if not (live == ver.get("taskset_digest") == txt):
        red.append(f"闸B taskset_digest 三处不一致：现算 {live[:12]} / version.json "
                   f"{str(ver.get('taskset_digest'))[:12]} / dist {str(txt)[:12]}")
    print(f"  闸B taskset_digest {live[:16]}…（现算 = version.json = dist）")

    no_snap = [t for t in have if not (DIST_TASKS / t / "environment" / rel.SNAP_NAME).is_file()]
    if no_snap:
        red.append(f"闸C 缺快照：{no_snap[:5]}（共 {len(no_snap)}）—— export-release.py --snapshots")
    print(f"  闸C 快照 {len(have) - len(no_snap)}/{len(have)}")
    return red, have


def gate_tiers() -> list[str]:
    red: list[str] = []
    tt = tiers()
    unknown = sorted(set(tt) - set(DURATION_BY_TIMEOUT))
    if unknown:
        red.append(f"闸D 出现未定档的 timeout_sec {unknown} —— 先在 DURATION_BY_TIMEOUT 里按 ×3×0.9 定值")
    for sec, ts in sorted(tt.items()):
        ms = DURATION_BY_TIMEOUT.get(sec)
        if ms is not None and ms != int(sec * AGENT_TIMEOUT_MULT * 0.9 * 1000):
            red.append(f"闸D t{sec} 的 max_duration_ms={ms} ≠ 硬顶×0.9")
        print(f"  闸D t{sec}: {len(ts)} 题 → 硬顶 {int(sec * AGENT_TIMEOUT_MULT)}s，max_duration_ms={ms}")
    return red


def gate_network(tasks: list[str]) -> list[str]:
    """t7 闸2 的同一判据，换成读发布目录。"""
    from harbor.models.task.config import NetworkMode, TaskConfig  # noqa: PLC0415

    bad = []
    for t in tasks:
        cfg = TaskConfig.model_validate(tomllib.loads((DIST_TASKS / t / "task.toml").read_text()))
        p = cfg.environment.resolve_baseline()
        if p.network_mode != NetworkMode.ALLOWLIST or p.allowed_hosts != [t7.GW_HOST]:
            bad.append(t)
    print(f"  闸E 网络策略 {len(tasks) - len(bad)}/{len(tasks)} 条 = allowlist + [{t7.GW_HOST}]")
    return [f"闸E 网络策略未落地：{bad[:5]}（共 {len(bad)} 条）"] if bad else []


def gate_gateway() -> list[str]:
    """t7 闸3（shim 上游逐字匹配）+ 闸4（占位 token 探活）。逻辑照抄 t7.preflight 的那两段判据。"""
    red: list[str] = []
    code, body = t7._get(f"{t7.GW_LOCAL}/__stats", timeout=15)
    upstream = None
    if code == 200:
        try:
            upstream = json.loads(body).get("upstream_model")
        except Exception:
            pass
    if upstream != t7.MODEL:
        red.append(f"闸F shim 上游是 {upstream!r}，点名的是 {t7.MODEL!r}")
    print(f"  闸F shim {t7.GW_LOCAL} 上游 = {upstream!r}")
    code, _ = t7._get(
        f"{t7.GW_LOCAL}/v1/chat/completions",
        data=json.dumps({"model": t7.MODEL, "messages": [{"role": "user", "content": "ping"}],
                         "max_tokens": 4}).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {t7.PLACEHOLDER_TOKEN}"},
        timeout=90,
    )
    if code != 200:
        red.append(f"闸G 占位 token 探针 http={code} —— 上游不可达或 shim 坏了。"
                   "先直连上游探活再看 gateway-4101.log：上游通而 shim 满屏 Connection refused 就重启 shim")
    print(f"  闸G 占位 token 探针 http={code}")
    return red


def registry_pricing(model: str, sid_repo: Path) -> dict | None:
    """问 sid-code 内置注册表这个模型的价（与容器内 resolvePricing 走同一份代码）。"""
    script = (
        'import {lookupRegistry} from "./packages/core/src/llm/model-registry.ts";'
        f"console.log(JSON.stringify(lookupRegistry({json.dumps(model)})?.pricing ?? null))"
    )
    try:
        r = subprocess.run(["bun", "-e", script], cwd=sid_repo, capture_output=True,
                           text=True, timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else None
    except (ValueError, IndexError):
        return None
    return out if isinstance(out, dict) else None


def judge_pricing(host: dict | None, registry: dict | None) -> tuple[str, str | None]:
    """→ (来源描述, 红项或 None)。纯函数，单测覆盖四种组合。

    宿主配了就以宿主为准（适配器会透传进容器，`sid_code_agent._host_pricing`）；
    没配就必须在内置注册表命中且不是占位价。两者都没有 ⇒ 容器回落网关采集价 ⇒ 红。
    """
    src, p = ("宿主 settings.json", host) if host else ("sid-code 内置注册表", registry)
    if not p:
        return "无", ("闸H 宿主与内置注册表都没有该模型的价 —— 容器会回落网关采集价"
                      "（曾实测 75/75，成本高报 355 倍）")
    if p.get("input") in PLACEHOLDER_PRICES and p.get("output") in PLACEHOLDER_PRICES:
        return src, f"闸H {src} 里的价是占位值 {p.get('input')}/{p.get('output')}"
    if not p.get("input") or not p.get("output"):
        return src, f"闸H {src} 里的价不完整：{p}"
    return src, None


def gate_pricing(sid_repo: Path) -> list[str]:
    st = json.loads(Path("~/.sid-code/settings.json").expanduser().read_text(encoding="utf-8"))
    entry = next((m for m in st.get("availableModels", []) if m.get("name") == t7.MODEL), None)
    host = (entry or {}).get("pricing") or None
    reg = None if host else registry_pricing(t7.MODEL, sid_repo)
    src, red = judge_pricing(host, reg)
    p = host or reg or {}
    print(f"  闸H pricing 来源 = {src}：in={p.get('input')} out={p.get('output')} "
          f"{p.get('currency')} asOf={p.get('asOf')}")
    return [red] if red else []


def elf_arch(path: Path) -> str:
    m = int.from_bytes(path.open("rb").read(20)[18:20], "little")
    return {0xB7: "arm64", 0x3E: "x64"}.get(m, f"0x{m:x}")


def gate_binary(binary: Path) -> tuple[list[str], str | None]:
    """二进制存在 + ELF 架构与容器一致 + build-info 有干净 commit。返回 (红项, commit)。"""
    red: list[str] = []
    if not binary.is_file():
        return [f"闸I 二进制不存在：{binary}"], None
    arch = subprocess.run(["docker", "run", "--rm", "oven/bun:1.3.14", "uname", "-m"],
                          capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout.strip()
    want = "arm64" if arch in ("aarch64", "arm64") else "x64"
    got = elf_arch(binary)
    if got != want:
        red.append(f"闸I 二进制 ELF 架构 {got}，容器是 {arch!r}（需要 {want}）")
    info_p = binary.parent / "build-info.json"
    info = json.loads(info_p.read_text(encoding="utf-8")) if info_p.is_file() else {}
    commit = info.get("commit")
    if not (isinstance(commit, str) and len(commit) == 40 and all(ch in "0123456789abcdef" for ch in commit)):
        red.append(f"闸I build-info.json 没有 40 位 commit（{commit!r}）—— 用 build-branch-artifact.sh 编")
        commit = None
    if info.get("dirty") is not False:
        red.append(f"闸I 产物 dirty={info.get('dirty')!r} —— 基线必须从干净 commit 编")
    print(f"  闸I 容器 {arch} → ELF={got}，commit={str(commit)[:12]}，dirty={info.get('dirty')}")
    return red, commit


def gate_fingerprint_tool() -> list[str]:
    """指纹必须含 max_duration_ms（sid-code PR #603），否则跨轮传错档会被静默判一致。"""
    src = FINGERPRINT_PY.read_text(encoding="utf-8") if FINGERPRINT_PY.is_file() else ""
    ok = '"max_duration_ms",' in src
    print(f"  闸J run_fingerprint.py 含 max_duration_ms：{ok}")
    return [] if ok else [f"闸J {FINGERPRINT_PY} 的 FIELDS 没有 max_duration_ms —— 先拉 sid-code main（#603）"]


def preflight(binary: Path, sid_repo: Path) -> tuple[list[str], str | None]:
    red, tasks = gate_taskset()
    red += gate_tiers()
    red += gate_network(tasks)
    red += gate_gateway()
    red += gate_pricing(sid_repo)
    r, commit = gate_binary(binary)
    red += r
    red += gate_fingerprint_tool()
    return red, commit


# ───────────────────────────────────────────────────────────── 跑 / 续跑 / 指纹


def build_cmd(task_path: Path, out: Path, max_duration_ms: int) -> list[str]:
    return [
        "harbor", "run",
        "-p", str(task_path),
        "-a", "sid_code_agent:SidCodeAgent",
        "-m", f"{t7.FAMILY}/{t7.MODEL}",
        "-n", str(N_CONCURRENT),
        "-k", "1",                                    # 轮次由本脚本控制，每轮一次 run
        "-o", str(out),
        "--ak", f"max_turns={MAX_TURNS}",
        "--ak", f"max_budget_usd={MAX_BUDGET_USD}",
        "--ak", f"max_duration_ms={max_duration_ms}",
        "--verifier-timeout-multiplier", "6",
        "--agent-timeout-multiplier", str(AGENT_TIMEOUT_MULT),
        "-y",
    ]


def build_env(binary: Path) -> dict[str, str]:
    env = {
        **os.environ,
        "HARBOR_TELEMETRY": "0",
        "PYTHONPATH": str(t7.HARBOR_DIR),
        "SID_HARBOR_GATEWAY_URL": f"http://{t7.GW_HOST}:{t7.GW_PORT}",
        "SID_HARBOR_PROVIDER": t7.FAMILY,
        "no_proxy": "127.0.0.1,localhost",
        "NO_PROXY": "127.0.0.1,localhost",
    }
    # 只点名对应架构那一个：另一架构不传，适配器找不到就报错，不会静默拿别的包
    env["SID_HARBOR_BINARY_ARM64" if elf_arch(binary) == "arm64" else "SID_HARBOR_BINARY_X64"] = str(binary)
    return env


def jobs_dir(rnd: int, tier: int) -> Path:
    return OUT / f"round{rnd}" / f"t{tier}"


def judged_tasks(jobs: Path) -> set[str]:
    """已判分且不是上游假 0 分的题（跨所有 harbor 时间戳目录）。判据同 t8-rerun.done_tasks。"""
    import t7_report_lib as rlib  # noqa: PLC0415

    done: set[str] = set()
    if not jobs.exists():
        return done
    for run in sorted(p for p in jobs.iterdir() if p.is_dir() and p.name[:2] == "20"):
        for f in sorted(run.glob("T0*/result.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            rw = (d.get("verifier_result") or {}).get("rewards") or {}
            if not isinstance(rw.get("reward"), (int, float)):
                continue
            md = (d.get("agent_result") or {}).get("metadata") or {}
            if rlib.Trial(task="", reward=rw.get("reward"), f2p=None, p2p=None, error_code=None,
                          exception=None, subtype=md.get("sid_subtype"),
                          errors=tuple(str(e) for e in (md.get("sid_errors") or []))).upstream_failure:
                continue
            done.add(f.parent.name.split("__")[0])
    return done


def collect_fingerprint(jobs: Path, out: Path, traj_commit: str) -> int:
    """对 jobs 下最新那个 harbor 目录采指纹。续跑产生多个目录时，逐个采、逐个与第一个比。"""
    runs = sorted(p for p in jobs.iterdir() if p.is_dir() and p.name[:2] == "20")
    rc = 0
    for i, run in enumerate(runs):
        dst = out if i == 0 else out.with_name(f"{out.stem}.part{i}.json")
        rc |= subprocess.run([sys.executable, str(FINGERPRINT_PY), "collect", str(run), "--out", str(dst),
                              "--declare", f"traj_bench_commit={traj_commit}",
                              "--declare", "network_policy=allowlist"], check=False).returncode
        if i:
            rc |= subprocess.run([sys.executable, str(FINGERPRINT_PY), "compare", str(out), str(dst)],
                                 check=False).returncode
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="T15 k=3 基线")
    ap.add_argument("--binary", required=True, type=Path, help="linux 二进制（同目录须有 build-info.json）")
    ap.add_argument("--sid-repo", type=Path, default=t7.HARBOR_DIR.parents[2],
                    help="sid-code 仓（闸H 查内置注册表用）")
    ap.add_argument("--rounds", type=int, nargs="*", default=list(range(1, K_ROUNDS + 1)))
    ap.add_argument("--dry-run", action="store_true", help="只过闸，不跑（$0）")
    ap.add_argument("--resume", action="store_true", help="跳过已判分的题（判据同 t8-rerun --resume）")
    a = ap.parse_args(argv)
    binary = a.binary.expanduser().resolve()
    bypass_loopback_proxy()                       # 必须在闸F/G 之前

    print(f"T15：{VERSION} 计分集 × k={K_ROUNDS}，-n {N_CONCURRENT}，max_turns={MAX_TURNS}")
    print("跑前闸：")
    red, commit = preflight(binary, a.sid_repo)
    if red:
        print("\n🔴 闸未过，拒绝开跑：")
        for r in red:
            print("  -", r)
        return 1
    print("  ✅ 全绿")
    if a.dry_run:
        for sec, ts in sorted(tiers().items()):
            print(f"  [dry-run] 每轮 t{sec}: " + " ".join(build_cmd(tier_dir(sec), jobs_dir(1, sec),
                                                                   DURATION_BY_TIMEOUT[sec])[:4]) + " …")
        print("--dry-run：不跑。")
        return 0

    traj_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=c.MVP_DIR, capture_output=True,
                                 text=True).stdout.strip()
    env = build_env(binary)
    FP_DIR.mkdir(parents=True, exist_ok=True)
    rc = 0
    for rnd in a.rounds:
        for sec, ts in sorted(tiers().items()):
            jobs = jobs_dir(rnd, sec)
            todo = [t for t in ts if t not in judged_tasks(jobs)] if a.resume else ts
            if not todo:
                print(f"round{rnd} t{sec}：已全部判分，跳过")
                continue
            path = stage_tier(sec, todo)
            jobs.mkdir(parents=True, exist_ok=True)
            c.assert_jobs_dir_ok(jobs)
            print(f"round{rnd} t{sec}：{len(todo)} 题，max_duration_ms={DURATION_BY_TIMEOUT[sec]} …", flush=True)
            t0 = time.time()
            with open(jobs / f"run-{time.strftime('%Y%m%d-%H%M%S')}.log", "w", encoding="utf-8") as f:
                subprocess.run(build_cmd(path, jobs, DURATION_BY_TIMEOUT[sec]), stdout=f,
                               stderr=subprocess.STDOUT, env=env, check=False, stdin=subprocess.DEVNULL)
            print(f"  用时 {(time.time() - t0) / 60:.1f} 分钟；已判分 {len(judged_tasks(jobs))}/{len(ts)}")
            rc |= collect_fingerprint(jobs, FP_DIR / f"round{rnd}-t{sec}.json", traj_commit)
    # 跨轮同档指纹比对：任何一组 INVALID 整组作废
    for sec in sorted(tiers()):
        base = FP_DIR / f"round1-t{sec}.json"
        for rnd in range(2, K_ROUNDS + 1):
            cur = FP_DIR / f"round{rnd}-t{sec}.json"
            if base.is_file() and cur.is_file():
                rc |= subprocess.run([sys.executable, str(FINGERPRINT_PY), "compare", str(base), str(cur)],
                                     check=False).returncode
    print(f"二进制 commit {str(commit)[:12]}；指纹在 {FP_DIR}。出报告：t7-report.py（逐轮逐档跨目录合并）")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
