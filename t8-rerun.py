#!/usr/bin/env python3
"""T8 — 整改后全量重跑（39 条 × 三项修复 × -n 6）。

方案见 `docs-research/trajectory-platform/bench-v0.2-mini-remediation.md`。
本文件是那份文档的**唯一可执行入口** —— 文档描述「改什么、为什么」，这里落地「怎么跑」。

## 与 t7-baseline.py 的关系

t7-baseline 跑出了 0/39 的废数据。它缺三件本轮必需的能力，且**都不是加个参数能补的**：

  1. `-n 1` 硬编码（第 206 行注释「README ⑤」）—— 那条结论的前提是
     verifier 要联网下 uv，我们这批 verifier 零网络请求，实验 E1 实测 `-n 6` 判分零损伤。
  2. 题面直接 symlink `tasks/`，**没有内联文档的入口**。
  3. 没有 `max_turns` 旋钮，静默用 agent default=40。

所以本轮另起一个文件，**不改 t7-baseline** —— 那份要留着复现第一轮的读数，
否则「整改前 vs 整改后」的对照就没有可执行的基线侧。

## 三项修复（逐条对应文档章节）

| 修复 | 做什么 | 文档 |
|---|---|---|
| ① 题面内联文档 | 36 处引用 → 内联原文（数据湖 30 / 镜像 6） | §3 |
| ② `max_turns` 40→120 | `--ak max_turns=120` + agent 超时 ×3 | §4 |
| ③ f2p 路径清单 | 题面追加「验收标准」，只给路径不给内容 | §5 |

并发 `-n 6`（§2.3 实测 39/39 oracle 全绿，3.4 分钟 vs 95.4 分钟）。

## 🔴 九条跑前闸

沿用 t7-baseline 的六条（存活集读 survivors.json / 网络策略 allowlist / shim 上游逐字匹配 /
占位 token 探活 / pricing 防成本高报 355 倍 / pin 二进制 ELF 架构），**原样 import 复用**，
外加本轮三条新的（见 `preflight_t8`）。

⛔ **不复制那六条的实现** —— 复制就意味着以后改一处漏一处，而两侧都不报错。

## 不作判据的东西（与 t7 同一套，刻意不另立标准）

  - **退出码**：harbor 失败时退出码仍是 0（TZ 四次失败全复现）。
  - **汇总表的 Mean**：它把 f2p/p2p/error_code 混在一列。
  - reward 取 `verifier_result.rewards.reward`，
    ⛔ 不是 `verifier_result.reward`（**恒为 None**，写错的形态是全体 0 分且不报错）。

## 三条 TZ 硬约束

  1. `-o` 必须在 `$HOME` 之下（R-3），否则 verifier 产物写进 VM 的 /private/tmp，
     宿主读不到，形态是 `RewardFileNotFoundError`（指向「没写分」，是**错误方向**）。
  2. `HARBOR_TELEMETRY=0` 写进命令本身（R-2）。
  3. `stdin=DEVNULL`：harbor 构建 egress sidecar 走 `buildx bake --file -`，
     bake 从 stdin 读；父进程 stdin 是已关闭管道时会**永久阻塞**，
     形态是 %CPU=0、日志停在 "Building Docker image" 一行不动，**既不报错也不超时**。
"""

from __future__ import annotations

import argparse
import importlib.util as _ilu
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

# ⚠️ 判分口径只认 t7_report_lib。原先还导入 t5_gate_lib 取 `latest_run`，
# 但 `summarize()` 改为**跨所有 run 目录**后不再需要它（只读最新会漏掉补跑前那批）。
import t7_report_lib as rlib  # noqa: E402

# ⛔ 复用 t7 的闸与配置常量，不复制实现（改一处漏一处，且两侧都不报错）
_spec = _ilu.spec_from_file_location("t7_baseline", Path(__file__).parent / "t7-baseline.py")
t7 = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(t7)

OUT = c.MVP_REPORTS / "t8-rerun"
STAGE = OUT / "tasks"          # ⚠️ 真目录不是 symlink：要改 instruction.md，symlink 会写穿到真身
FIX = c.MVP_REPORTS / "t8-fix"
MAX_TURNS = 120
N_CONCURRENT = 6
AGENT_TIMEOUT_MULT = 3.0       # 轮数 ×3 ⇒ 墙钟也要放开，否则被超时截断、把「轮数够了」掩盖成「还是不行」

#: per-trial 成本熔断。**这是熔断器，不是剪枝闸** —— 定位差别决定了取值。
#:
#: ⛔ 不要指望它「拦住不收敛的题」：实测（C/D 臂 n=11）两类的成本**区间重叠**，
#:    做不到只拦坏的：
#:      error_max_turns: $1.242 – $1.611
#:      success:         $0.054 – $1.467   ← T0036 花 $1.467 主动收尾
#:    任何能拦住撞上限（>$1.24）的阈值，都会误伤 T0036 那条正常完成的题。
#:    最初拍的 $1.5 差 3 分钱就砍掉它 —— 那样的形态是「误伤记成没解出」，
#:    比不设闸更糟（污染分母，且不报错）。
#:
#: ✅ 它真正的作用：**在墙钟触顶前抢先干净终止**。这条是 D 臂 T0029 教出来的 ——
#:    它跑了 528 个 tool_progress、$2.111，最后撞的是 **agent 超时 8100s**，
#:    终止形态是 `AgentTimeoutError` ⇒ 进 Exceptions ⇒ **被剔出 pass@1 的分母**。
#:    那是最糟的形态：一条纯粹跑得慢的题被记成基础设施故障。
#:
#: 🔴 取值靠实测扫描定，⛔ 不是「success 最大值 × 2」那种拍脑袋：
#:      | 阈值 | 误伤 success | 抢先熔断 T0029 那条脏终止 |
#:      | $1.6 / $1.8 / $2.0 |  0  |  ✅ |
#:      | $2.5 / $3.0        |  0  |  ❌ 拦不住（它只花了 $2.111）|
#:    ⇒ 最初写的 $3.0 **太高，等于没装**。取 **$1.8**：
#:      比已观测 success 最大值（$1.467，T0036 跑 110 轮）高 23% 留余量，
#:      同时能在 T0029 那种形态烧到墙钟之前干净终止。
#:
#: 超限以 `subtype: "error_max_budget_usd"` 终止（独立 subtype，⛔ 不进 Exceptions）。
#: 全量 39 条：现实预估 39 × 均值 $0.766 ≈ **$30**；最坏（每题都熔断）$70。
MAX_BUDGET_USD = "1.8"


#: 内联文档正文里的控制字符 → 可见记法。⛔ 不能原样带进题面。
#:
#: 🔴 2026-09-13 全量重跑实测踩到（T0009，整批唯一的 Exception）：
#:   那份文档**本身在讲**「分隔符用 `\x00`/`\x01` 而非空格」，正文里带了真的 NUL。
#:   题面经命令行传给 `docker exec`，`subprocess.Popen` 拒绝含 NUL 的参数
#:   ⇒ `ValueError: embedded null byte`，**容器还没起就炸**，reward=None ⇒ 剔出分母。
#:
#: 形态之所以难查：报错在 asyncio/subprocess 深处，traceback 里**一个字都不提题面**
#: （满屏 `_fork_exec` / `Popen.__init__`），看着像 harbor 或 docker 坏了。
#:
#: ⚠️ §3.4 那四道「假恢复」闸（长度 / 单行 / JSON 可解析 / 移出 DOC_EXT）
#: 全是查**内容够不够真**，没有一道查**内容能不能安全传输** —— 这是漏网的第五类。
_CTRL_MAP = {c: f"\\x{c:02x}" for c in list(range(0, 9)) + [11, 12] + list(range(14, 32))}


def _visible_ctrl(txt: str) -> str:
    """把 C0 控制字符（除 \\t \\n \\r）换成 `\\xNN` 字面量。

    ⛔ 不是删除：那份文档正文在**讨论**这些字节的语义，删掉等于改题面内容。
    换成可见记法既保住语义，又能安全经命令行传输。
    """
    return txt.translate(_CTRL_MAP)


def build_instruction(task: str, *, inline_docs: bool, f2p_list: bool) -> str:
    """题面 = 原句 + [内联文档] + [验收标准] + 环境事实。

    ⛔ **不改用户那句话本身** —— T3 的「题面不加工」纪律仍然有效。
    内联做的是**把当时的环境补齐**（那份文件在真实会话里是可读的），不是提示答案。
    """
    src = (c.MVP_TASKS / task / "instruction.md").read_text(encoding="utf-8")
    body, _, envfacts = src.partition("\n---\n")
    parts = [body.strip()]

    if inline_docs:
        idx = json.loads((FIX / "docs-index.json").read_text(encoding="utf-8"))
        blocks = []
        for e in idx.get(task, {}).get("docs", []):
            if e.get("channel") not in ("lake", "mirror"):
                continue
            txt = _visible_ctrl(
                (FIX / "docs" / e["file"]).read_text(encoding="utf-8", errors="replace"))
            blocks.append(
                f"### `{e['ref']}`\n\n"
                f"> 以下为该文件原文（评测环境无法访问你本机路径，故内联附上）。\n\n"
                f"```\n{txt}\n```\n"
            )
        if blocks:
            parts.append("---\n\n## 引用文档原文\n\n" + "\n".join(blocks))

    if f2p_list:
        f2p = json.loads((c.MVP_TASKS / task / "tests/f2p.json").read_text(encoding="utf-8"))
        # ⛔ 只给**路径**，不给内容 —— 给内容 agent 就能从断言反推实现，
        #    那测的是「照测试写代码」而不是「解决问题」，pass@1 虚高且不可与外部基准对照。
        parts.append(
            "---\n\n## 验收标准\n\n"
            "你的修复必须让以下测试文件**全部通过**（`bun test <路径>`）：\n\n"
            + "\n".join(f"- `{p}`" for p in f2p)
            + "\n\n> 这些测试文件当前**不在**工作区，验收时才会放入。\n"
              "> 文件名指示了实现应落在哪个模块（本仓库约定：`tests/x/y.test.ts` ↔ `src/x/y.ts`）。\n"
              "> ⚠️ 不要自己创建这些测试文件 —— 验收时会被覆盖。\n"
        )

    return "\n\n".join(parts) + "\n\n---\n" + envfacts


def stage(tasks: list[str], *, inline_docs: bool, f2p_list: bool) -> Path:
    """把 39 条**复制**到 stage 目录并改写题面。

    ⛔ 不能 symlink 再改 instruction.md —— 那会写穿到 `tasks/` 真身，
    污染下一轮和 t7 的复现基线。tasks 里最大的是 repo-snapshot.tar.gz（1–3MB），
    39 条全拷约 100MB，可接受。
    """
    # 🔴 有批次在跑时**不许重建 stage** —— 它是那批正在用的题源。
    #
    # 2026-09-13 实测踩到：跑批进行中执行 `--resume --dry-run`，
    # stage 被整目录 rmtree 后重建。那次**侥幸没坏**（harbor 在启动容器时
    # 已把 instruction.md 读入，运行中不回读），但这是运气不是设计：
    # 尚未启动的 pending 条目要到轮到它时才读题，正好撞上重建窗口就会读到
    # 半个目录 —— 形态是 task 找不到 / 题面为空，而归因会指向「题集坏了」。
    #
    # ⛔ 判据是「有活着的 harbor 跑批进程」，不是「OUT 里有 run 目录」：
    # 后者跑完也一直在，会把正常的下一轮也拦掉。
    if STAGE.exists():
        live = subprocess.run(
            ["pgrep", "-f", f"harbor run.*{STAGE}"],
            capture_output=True, text=True, check=False).stdout.strip()
        if live:
            raise SystemExit(
                f"⛔ 有批次正在使用 stage（harbor pid {live.split()[0]}）—— 拒绝重建。\n"
                f"   stage={STAGE}\n"
                "   重建会让尚未启动的 pending 条目读到半个目录，且归因会错指「题集坏了」。\n"
                "   → 等那批跑完，或先 TaskStop / kill 它再来。")
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    for t in tasks:
        shutil.copytree(c.MVP_TASKS / t, STAGE / t, symlinks=False)
        (STAGE / t / "instruction.md").write_text(
            build_instruction(t, inline_docs=inline_docs, f2p_list=f2p_list), encoding="utf-8"
        )
    got = sorted(p.name for p in STAGE.iterdir())
    if got != sorted(tasks):
        raise SystemExit(f"stage 与名单不一致：{len(got)} vs {len(tasks)}")
    return STAGE


def preflight_t8(tasks: list[str], staged: Path) -> list[str]:
    """本轮新增三条闸（t7 那六条由 `t7.preflight` 负责）。"""
    red: list[str] = []

    # 闸 7：题面内联真的生效（防 §3.4 那类「假恢复」漏网）
    idx = json.loads((FIX / "docs-index.json").read_text(encoding="utf-8"))
    want = {t for t, v in idx.items()
            if any(e.get("channel") in ("lake", "mirror") for e in v.get("docs", []))}
    bad = []
    for t in sorted(want & set(tasks)):
        txt = (staged / t / "instruction.md").read_text(encoding="utf-8")
        if "## 引用文档原文" not in txt:
            bad.append(f"{t}:无标记")
            continue
        seg = txt.split("## 引用文档原文", 1)[1]
        # 正文必须有实质内容 —— 只有 ``` 空块就是假恢复漏进来了
        if len(seg.split("## 验收标准")[0].strip()) < 1000:
            bad.append(f"{t}:正文过短")
    if bad:
        red.append(f"闸7 题面内联未生效：{bad[:5]}（共 {len(bad)} 条）")
    print(f"  闸7 题面内联 {len(want & set(tasks)) - len(bad)}/{len(want & set(tasks))} 条含文档正文")

    # 闸 10：题面能安全经命令行传输（无 C0 控制字符）
    #
    # 🔴 T0009 实测：内联文档正文里有真的 NUL（那份文档在讲分隔符用 \x00），
    # `subprocess.Popen` 拒绝含 NUL 的参数 ⇒ 容器还没起就 ValueError，
    # 而 traceback 满屏 `_fork_exec`，**一个字都不提题面** ⇒ 归因会指向 harbor/docker。
    # 这是整批 39 条里唯一的 Exception，且它把那条题剔出了分母。
    ctrl_bad = []
    for t in tasks:
        raw = (staged / t / "instruction.md").read_bytes()
        hits = {c for c in _CTRL_MAP if bytes([c]) in raw}
        if hits:
            ctrl_bad.append(f"{t}:{sorted(hex(c) for c in hits)}")
    if ctrl_bad:
        red.append(f"闸10 题面含控制字符（会让 Popen 抛 ValueError）：{ctrl_bad[:5]}"
                   f"（共 {len(ctrl_bad)} 条）—— 看 _visible_ctrl 是否漏了这条路径")
    print(f"  闸10 题面无控制字符 {len(tasks) - len(ctrl_bad)}/{len(tasks)} 条")

    # 闸 8：验收标准段落存在，且**没有把测试内容写进去**
    leaked = []
    for t in tasks:
        txt = (staged / t / "instruction.md").read_text(encoding="utf-8")
        if "## 验收标准" not in txt:
            leaked.append(f"{t}:无验收段")
            continue
        seg = txt.split("## 验收标准", 1)[1]
        # 泄漏的形态：把 test_patch 的断言贴进来了
        if "expect(" in seg or "describe(" in seg:
            leaked.append(f"{t}:疑似泄漏测试内容")
    if leaked:
        red.append(f"闸8 验收标准段异常：{leaked[:5]}")
    print(f"  闸8 验收标准段 {len(tasks) - len(leaked)}/{len(tasks)} 条正常（无测试内容泄漏）")

    # 闸 9：stage 是真目录不是 symlink（否则改题面会写穿到 tasks/ 真身）
    sym = [t for t in tasks if (staged / t).is_symlink()]
    if sym:
        red.append(f"闸9 stage 里有 symlink：{sym[:5]} —— 改题面会污染 tasks/ 真身")
    print(f"  闸9 stage 全部真目录（{len(tasks)} 条，无 symlink）")

    return red


def run(task_path: Path, out: Path, k: int) -> float:
    out.mkdir(parents=True, exist_ok=True)
    c.assert_jobs_dir_ok(out)                        # R-3，别靠记性
    cmd = [
        "harbor", "run",
        "-p", str(task_path),
        "-a", "sid_code_agent:SidCodeAgent",
        "-m", f"{t7.FAMILY}/{t7.MODEL}",
        "-n", str(N_CONCURRENT),                     # §2.3：E1 实测 oracle 39/39，判分零损伤
        "-k", str(k),
        "-o", str(out),
        "--ak", f"max_turns={MAX_TURNS}",            # 声明式旋钮，⛔ 不用私有环境变量
        "--ak", f"max_budget_usd={MAX_BUDGET_USD}",  # 熔断器，见常量处的论证
        "--verifier-timeout-multiplier", "6",
        "--agent-timeout-multiplier", str(AGENT_TIMEOUT_MULT),
        "-y",
    ]
    env = {
        **os.environ,
        "HARBOR_TELEMETRY": "0",                     # R-2
        "PYTHONPATH": str(t7.HARBOR_DIR),
        "SID_HARBOR_GATEWAY_URL": f"http://{t7.GW_HOST}:{t7.GW_PORT}",
        "SID_HARBOR_PROVIDER": t7.FAMILY,            # 显式写，别只靠 -m 前缀解析
        "SID_HARBOR_BINARY_ARM64": str(
            Path("~/.local/share/sid-harbor-gateway/bins/sid-code-arm64-30586ff003c9").expanduser()),
        "SID_HARBOR_BINARY_X64": str(
            Path("~/.local/share/sid-harbor-gateway/bins/sid-code-x64-30586ff003c9").expanduser()),
        "no_proxy": "127.0.0.1,localhost",
        "NO_PROXY": "127.0.0.1,localhost",
    }
    t0 = time.time()
    with open(out / "run.log", "w", encoding="utf-8") as f:
        subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env=env, check=False,
                       stdin=subprocess.DEVNULL)     # ⚠️ 不给会挂死在 buildx bake 读 stdin
    return time.time() - t0


def summarize(out: Path) -> dict:
    """只汇总，不判定。判定与报告在 t7-report.py（可单测、可纯复算）。

    ⚠️ 必须带上 `n_repo_writes` —— 这是**区分「没答」与「答错」的唯一判据**。
    第一轮如果有这一列，「39 条里只有 2 条提交解法」在第一张表就该暴露。
    """
    WRITE = {"write", "edit", "multiedit", "str_replace", "apply_patch"}

    # 🔴 跨**所有** run 目录扫，⛔ 不能只读 `latest_run`。
    #
    # 2026-09-14 实测（造样本证实）：补跑（`--resume`）新建一个 run 目录，
    # 只读最新那个 ⇒ 分母只剩补跑那几条。形态是**收尾打印 `pass@1 = 0.0%`**
    # 而真实是 50%（旧 run 里解出的那些一条都没算），成本也只算补跑那批。
    # 这个数字直接出现在补跑结束的终端上，与 `t7-report.py`（已跨目录）打架，
    # 而它看起来完全正常 —— 只是分母悄悄小了一圈。
    #
    # ⚠️ 同一 task 出现在多个目录时取**最新**那个：补跑结果比被中断的旧结果可信
    # （与 `done_tasks()` / `t7_report_lib.collect_all()` 同口径）。
    runs = sorted(p for p in out.iterdir() if p.is_dir() and p.name[:2] == "20") \
        if out.exists() else []
    latest: dict[str, Path] = {}
    for run in runs:                      # 后面的 run 覆盖前面的同名 task
        for f in sorted(run.glob("T0*/result.json")):
            latest[f.parent.name.split("__")[0]] = f
    rd = runs[-1] if runs else None

    rows = []
    for _task, f in sorted(latest.items()):
        d = json.loads(f.read_text())
        rw = (d.get("verifier_result") or {}).get("rewards") or {}
        md = ((d.get("agent_result") or {}).get("metadata") or {})
        repo = set()
        jl = f.parent / "agent/sid-code.jsonl"
        if jl.exists():
            for line in jl.open(errors="ignore"):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue

                def walk(o):
                    if isinstance(o, dict):
                        n = (o.get("name") or o.get("tool_name") or "").lower()
                        if n in WRITE:
                            inp = o.get("input") or {}
                            fp = str(inp.get("file_path") or inp.get("path") or "")
                            if fp.startswith("/repo") and "/tmp" not in fp:
                                # ruff B023 在这里是**误报**：`walk` 不逃出本轮迭代
                                # （下一行就 `walk(obj)` 同步调用完），`repo` 绑定的
                                # 始终是当前 trial 的那个 set。
                                # ⛔ 不为消 linter 噪音去重构这段 —— 它正在产出
                                # `n_repo_writes`（「没答 vs 答错」的唯一判据）。
                                repo.add(fp)  # noqa: B023
                        for v in o.values():
                            walk(v)
                    elif isinstance(o, list):
                        for v in o:
                            walk(v)

                walk(obj)
        rows.append({
            "task": d["task_name"],
            "reward": rw.get("reward"), "f2p": rw.get("f2p"), "p2p": rw.get("p2p"),
            "error_code": rw.get("error_code"),
            "subtype": md.get("sid_subtype"), "turns": md.get("sid_num_turns"),
            "cost_usd": (d.get("agent_result") or {}).get("cost_usd"),
            "n_repo_writes": len(repo),                       # ← 「没答 vs 答错」的判据
            "sid_binary_sha256": md.get("sid_binary_sha256"),  # 必控变量
        })
    solved = [r for r in rows if r["reward"] and r["reward"] >= 1.0]
    silent = [r["task"] for r in rows if r["n_repo_writes"] == 0]
    return {
        # ⚠️ 跨目录时 run_dir 只是**最新**那个，取数其实跨了 n_run_dirs 个
        "run_dir": str(rd), "n_run_dirs": len(runs),
        "run_dirs": [r.name for r in runs],
        "n": len(rows), "solved": len(solved),
        "solved_tasks": sorted(r["task"] for r in solved),
        "pass_at_1": round(len(solved) / len(rows) * 100, 1) if rows else None,
        "n_zero_repo_writes": len(silent), "zero_repo_write_tasks": silent,
        "cost_usd": round(sum(r["cost_usd"] or 0 for r in rows), 4),
        "n_budget_capped": len([r for r in rows if r["subtype"] == "error_max_budget_usd"]),
        "config": {"max_turns": MAX_TURNS, "n_concurrent": N_CONCURRENT,
                   "max_budget_usd": MAX_BUDGET_USD,
                   "agent_timeout_multiplier": AGENT_TIMEOUT_MULT,
                   "inline_docs": True, "f2p_list": True},
        "rows": rows,
    }


def done_tasks(out: Path) -> dict[str, Path]:
    """扫 `out` 下**所有** run 目录，返回 {task: trial_dir} —— 已判分的那些。

    🔴 判据是「verifier 写了分」，⛔ 不是「目录存在」：
    进程被杀时正在跑的那几条**目录已建、result.json 未写**，
    照目录判会把它们当成已完成 ⇒ 续跑跳过 ⇒ **那几条永久缺失**，
    而报告的完整性守卫要到最后才发现（且只报「没跑齐」，不说为什么）。

    ⚠️ 跨 run 目录扫描：harbor 每次调用新建一个带时间戳的目录，
    续跑一次就多一个。同一 task 在多个目录里出现时取**最新**那个
    （续跑重试过的结果比旧的可信）。
    """
    found: dict[str, Path] = {}
    if not out.exists():
        return found
    for run in sorted(p for p in out.iterdir() if p.is_dir() and p.name[:2] == "20"):
        for f in sorted(run.glob("T0*/result.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue                             # 写一半被杀 ⇒ 算未完成，重跑
            rw = (d.get("verifier_result") or {}).get("rewards") or {}
            if not isinstance(rw.get("reward"), (int, float)):
                continue                             # 没判分 ⇒ 不算完成
            # 🔴 **假 0 分也要重跑** —— 上游 LLM 断连的题写了 reward=0.0，
            # 光看「有没有分」会把它算成已完成 ⇒ 补跑跳过它 ⇒ 那条永久是废数据。
            #
            # 2026-09-14 实测（T0022）：61 轮时上游断连，verifier 照常打了 0 分。
            # 报告侧已按 infra 排除出分母（§8.8），但**排除不等于修好** ——
            # 它仍需重跑才能拿到真实读数，否则最终分母永远少一条。
            md = ((d.get("agent_result") or {}).get("metadata") or {})
            if rlib.Trial(task="", reward=rw.get("reward"), f2p=None, p2p=None,
                          error_code=None, exception=None,
                          subtype=md.get("sid_subtype"),
                          errors=tuple(str(e) for e in (md.get("sid_errors") or []))
                          ).upstream_failure:
                continue                             # 假 0 分 ⇒ 算未完成，重跑
            found[f.parent.name.split("__")[0]] = f.parent
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=1, help="每题跑几次（默认 1）")
    ap.add_argument("--dry-run", action="store_true", help="只过闸，不跑（$0）")
    ap.add_argument("--no-docs", action="store_true", help="关掉修复①（对照用）")
    ap.add_argument("--no-f2p-list", action="store_true", help="关掉修复③（对照用）")
    ap.add_argument("--resume", action="store_true",
                    help="只跑**还没判分**的那些题（进程被杀 / 断电后续跑）。"
                         "判据是 verifier 写了分，⛔ 不是目录存在 —— 被杀时在跑的那几条会重跑。"
                         "⚠️ 续跑产生新的 run 目录，出报告时 t7-report.py 会跨目录合并")
    a = ap.parse_args()

    tasks = t7.survivors()
    all_tasks = list(tasks)          # 题集闸用全集，⛔ 别用被 --resume 削过的 tasks
    if a.resume:
        done = done_tasks(OUT)
        skip = [t for t in tasks if t in done]
        tasks = [t for t in tasks if t not in done]
        print(f"--resume：已判分 {len(skip)} 条，本次要跑 {len(tasks)} 条")
        if skip:
            print(f"  跳过：{', '.join(skip[:10])}{' …' if len(skip) > 10 else ''}")
        if not tasks:
            print("✅ 39 条全部已判分，无需续跑 —— 直接出报告：\n"
                  "   t7-report.py --runs t8-rerun")
            return 0
    print(f"T8 全量重跑：{len(tasks)} 条 × -n {N_CONCURRENT} × max_turns={MAX_TURNS}")
    print("staging（复制 + 改题面）…")
    staged = stage(tasks, inline_docs=not a.no_docs, f2p_list=not a.no_f2p_list)

    print("跑前闸：")
    # 🔴 两类闸的**作用域不同**，续跑时必须分开传：
    #   - t7 那六条验的是**题集**（存活集条数、网络策略、shim、pricing、二进制）
    #     ⇒ 传**全 39 条**。闸1 硬编码 `!= 39`，传子集会红着拒跑续跑 ——
    #     而那是闸在报「存活集不对」，不是「续跑不该跑」，归因方向完全错。
    #   - 本轮三条验的是**这次 stage 出来的题面** ⇒ 传本次子集（stage 里只有它们）。
    red = t7.preflight(all_tasks) + preflight_t8(tasks, staged)
    if red:
        print("\n🔴 闸未过，拒绝开跑（红着跑等于烧钱换废数）：")
        for r in red:
            print("  -", r)
        return 1
    print("  ✅ 九条闸全绿")
    if a.dry_run:
        print("--dry-run：不跑。")
        return 0

    el = run(staged, OUT, a.k)
    print(f"跑完，耗时 {el / 60:.1f} 分钟")
    s = summarize(OUT)
    s["elapsed_min"] = round(el / 60, 1)
    (OUT / "summary-raw.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\npass@1 = {s['pass_at_1']}%（{s['solved']}/{s['n']}）  ${s['cost_usd']}")
    print(f"零仓库写（= 没答，不是答错）：{s['n_zero_repo_writes']}/{s['n']}")
    if s["n_budget_capped"]:
        # ⚠️ 熔断了就要说出来：这些题**没跑完**，把它们算进「没解出」会低报 pass@1
        print(f"⚠️ 成本熔断（${MAX_BUDGET_USD}）：{s['n_budget_capped']}/{s['n']} 条 —— "
              f"这些题未跑完，报告里必须单列，不能默认算「没解出」")
    print(f"解出：{s['solved_tasks']}")
    print(f"\n产物 → {OUT}/summary-raw.json")
    print("下一步：跑 t7-report.py 出正式报告（判定与口径在那里，本文件只负责把批跑完）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
