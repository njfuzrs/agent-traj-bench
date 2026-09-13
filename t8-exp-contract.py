"""实验 E3：第五臂 —— 内联文档 + f2p 路径清单 + 120 轮（重跑候选配置）。

## 为什么需要第五臂

E2 的 B 臂证明：只内联文档 solved 仍 0/6，且 A/B 两臂 pass/fail 逐条几乎相同 ——
**题面不是主要瓶颈**。真正的天花板是 §3.6 量化出的符号契约缺口：
20/39 条的 f2p 测试 import 了 89 个 base 里不存在的符号，
agent 必须凭空猜出同名同签名，否则测试连模块都加载不起来。

用户已定方案：**给 f2p 测试文件路径清单，不给测试内容**（SWE-bench 官方口径）。
本实验验证这个口径能补多少。

## 预期（写在跑之前，不事后调整）

f2p 文件名 → 模块路径的可推出率实测只有 26%，符号名 0% ⇒
**预期这一臂对重契约题（T0011/T0047 类）仍然无效**。
它真正能救的是那些「测试只 import base 已有符号」的题 —— 那 19 条零缺口 task。
所以选题刻意**混合**：3 条零缺口 + 3 条有缺口，看两组的分化。

若零缺口那 3 条出现 solved > 0 而有缺口 3 条仍 0 ⇒ 结论是
「19 条零缺口子集可作主基线，20 条重契约题需单独口径」（用户选项 4 的结论）。
"""
import json, os, shutil, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, "/Users/zhourusheng/Code/person/trajectory-platform/scripts/mvp")
import common as c
import t5_gate_lib as lib

BASE = c.MVP_REPORTS / "t8-fix"
DOCS = BASE / "docs"
IDX = json.loads((BASE / "docs-index.json").read_text())
GAP = json.loads((BASE / "symbol-gap.json").read_text())
# 3 条零缺口（契约完备）+ 3 条有缺口，看分化
CLEAN = ["T0002", "T0029", "T0052"]
GAPPY = ["T0011", "T0047", "T0028"]
TASKS = CLEAN + GAPPY
FAMILY, MODEL, GW = "openai", "origin-deepseek-v4-1-flash", "192.168.5.2:4101"

def build_instruction(task: str) -> str:
    """题面 = 原句 + 内联文档 + f2p 路径清单（不给测试内容）。"""
    instr = (c.MVP_TASKS / task / "instruction.md").read_text(encoding="utf-8")
    body, _, envfacts = instr.partition("\n---\n")
    parts = [body.strip()]
    blocks = []
    for e in IDX.get(task, {}).get("docs", []):
        if e.get("channel") not in ("lake", "mirror"): continue
        txt = (DOCS / e["file"]).read_text(encoding="utf-8", errors="replace")
        blocks.append(f"### `{e['ref']}`\n\n"
                      f"> 以下为该文件原文（评测环境无法访问你本机路径，故内联附上）。\n\n"
                      f"```\n{txt}\n```\n")
    if blocks:
        parts.append("---\n\n## 引用文档原文\n\n" + "\n".join(blocks))
    f2p = json.loads((c.MVP_TASKS / task / "tests/f2p.json").read_text())
    # ⛔ 只给**路径**，不给内容 —— 给内容就是泄漏答案(agent 能从断言反推实现),
    #    那样测的是「照测试写代码」而不是「解决问题」,pass@1 虚高且不可对照。
    parts.append("---\n\n## 验收标准\n\n"
                 "你的修复必须让以下测试文件**全部通过**（`bun test <路径>`）：\n\n"
                 + "\n".join(f"- `{p}`" for p in f2p)
                 + "\n\n> 这些测试文件当前**不在**工作区，验收时才会放入。\n"
                   "> 文件名指示了实现应落在哪个模块（本仓库约定：`tests/x/y.test.ts` ↔ `src/x/y.ts`）。\n"
                   "> ⚠️ 不要自己创建这些测试文件 —— 验收时会覆盖掉。\n")
    return "\n\n".join(parts) + "\n\n---\n" + envfacts

def main():
    st = BASE / "stage/E-contract"
    if st.exists(): shutil.rmtree(st)
    st.mkdir(parents=True)
    for t in TASKS:
        shutil.copytree(c.MVP_TASKS / t, st / t, symlinks=False)
        (st / t / "instruction.md").write_text(build_instruction(t), encoding="utf-8")
    out = BASE / "exp-fix/E-contract"
    out.mkdir(parents=True, exist_ok=True)
    c.assert_jobs_dir_ok(out)
    cmd = ["harbor", "run", "-p", str(st), "-a", "sid_code_agent:SidCodeAgent",
           "-m", f"{FAMILY}/{MODEL}", "-n", "6", "-k", "1", "-o", str(out),
           "--ak", "max_turns=120",
           # 熔断器,与 t8-rerun 同一取值(= 已观测 success 最大成本 $1.467 × 2)。
           # ⛔ 不是剪枝闸:实测两类终止的成本区间重叠,做不到只拦不收敛的。
           "--ak", "max_budget_usd=1.8",
           "--verifier-timeout-multiplier", "6",
           "--agent-timeout-multiplier", "3", "-y"]
    env = {**os.environ, "HARBOR_TELEMETRY": "0",
           "PYTHONPATH": "/Users/zhourusheng/Code/person/sid-code/evals/external-benchmarks/harbor",
           "SID_HARBOR_GATEWAY_URL": f"http://{GW}", "SID_HARBOR_PROVIDER": FAMILY,
           "SID_HARBOR_BINARY_ARM64": str(Path("~/.local/share/sid-harbor-gateway/bins/sid-code-arm64-30586ff003c9").expanduser()),
           "SID_HARBOR_BINARY_X64": str(Path("~/.local/share/sid-harbor-gateway/bins/sid-code-x64-30586ff003c9").expanduser()),
           "no_proxy": "127.0.0.1,localhost", "NO_PROXY": "127.0.0.1,localhost"}
    print(f"实验 E3：{len(TASKS)} 条（零缺口 {CLEAN} / 有缺口 {GAPPY}）× 内联+清单 × 120 轮")
    t0 = time.time()
    with open(out / "run.log", "w", encoding="utf-8") as f:
        subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env=env,
                       check=False, stdin=subprocess.DEVNULL)
    print(f"耗时 {(time.time()-t0)/60:.1f} 分钟")
    rd = lib.latest_run(out)
    rows = []
    for f in sorted((rd or Path()).glob("T0*/result.json")):
        d = json.loads(f.read_text())
        rw = (d.get("verifier_result") or {}).get("rewards") or {}
        md = ((d.get("agent_result") or {}).get("metadata") or {})
        rows.append({"task": d["task_name"], "group": "clean" if d["task_name"] in CLEAN else "gappy",
                     "reward": rw.get("reward"), "f2p": rw.get("f2p"), "p2p": rw.get("p2p"),
                     "subtype": md.get("sid_subtype"), "turns": md.get("sid_num_turns"),
                     "cost": (d.get("agent_result") or {}).get("cost_usd")})
    (out / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    for g in ("clean", "gappy"):
        sub = [r for r in rows if r["group"] == g]
        s = sum(1 for r in sub if r["reward"] and r["reward"] >= 1)
        print(f"  {g}: solved {s}/{len(sub)}")
    print(f"  合计 ${sum(r['cost'] or 0 for r in rows):.2f}")

if __name__ == "__main__":
    main()
