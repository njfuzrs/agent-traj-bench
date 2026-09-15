"""实验 E2：2×2 拆解 —— 内联文档 / 抬 max_turns 各自贡献多少。

## 为什么必须 2×2 而不是「一起改了看结果」

一起改，结果好了也不知道是哪个变量起的作用；结果不好更糟 —— 无法区分
「文档内联没用」和「文档有用但被轮数掐死」。基线那 5 条 `success`
（20–34 轮，没撞上限，仍 0 分）已经证明轮数不是唯一瓶颈，
但没证明文档内联**够**。这个实验补上后半句。

| 臂 | 题面 | max_turns | 问的问题 |
|---|---|---|---|
| **A 对照** | 原样（引用本机 docs） | 40 | 复现基线的 0 分 |
| **B 文档** | **内联文档原文** | 40 | 只修题面够不够 |
| **C 轮数** | 原样 | **120** | 只抬轮数够不够 |
| **D 双修** | **内联** | **120** | 两个都修的上限 |

⚠️ **A 臂不是浪费**：它必须与基线跑出同样的 0 分，否则说明这 6 条题在
新环境（-n 6）下行为变了 —— 那样 B/C/D 的对比就失去基准。
README ⑤ 的教训正是「小规模探针全绿不能外推到真实 run」，反过来也成立。

## 选题（6 条，刻意分层）

按 gold_patch 规模从小到大取，覆盖 A1/A2/B/C 四档 —— 不全取小题，
否则「解出来了」可能只是因为挑了最容易的。

## 成本

6 题 × 4 臂 = 24 trial。基线均价 $0.196/trial，C/D 臂轮数 ×3 ⇒ 上限约 $10。
用户已明确授权花钱。
"""
import json, os, re, shutil, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, "/Users/zhourusheng/Code/person/trajectory-platform/scripts/mvp")
import common as c
import t5_gate_lib as lib

BASE = c.MVP_REPORTS / "t8-fix"
DOCS = BASE / "docs"
IDX = json.loads((BASE / "docs-index.json").read_text())
TASKS = ["T0026", "T0010", "T0002", "T0011", "T0029", "T0036"]  # A1/A2/B/C 混合
FAMILY, MODEL = "openai", "origin-deepseek-v4-1-flash"
GW = "192.168.5.2:4101"
ARMS = [("A-control", False, 40), ("B-doc", True, 40),
        ("C-turns", False, 120), ("D-both", True, 120)]

def inline_instruction(task: str) -> str:
    """把题面里的本机路径引用，替换成「路径 + 内联全文」。

    ⛔ 不改用户那句话本身（T3 ①「题面不加工」的纪律）——
    只在原句后面追加一段 `## 引用文档原文`，把 agent 在真实会话里
    第一步 Read 到的内容原样附上。这等价于把当时的环境补齐，不是提示答案。
    """
    instr = (c.MVP_TASKS / task / "instruction.md").read_text(encoding="utf-8")
    body, _, envfacts = instr.partition("\n---\n")
    blocks = []
    for e in IDX[task]["docs"]:
        if e.get("channel") not in ("lake", "mirror"): continue
        txt = (DOCS / e["file"]).read_text(encoding="utf-8", errors="replace")
        blocks.append(
            f"### `{e['ref']}`\n\n"
            f"> 以下为该文件的原文内容（评测环境无法访问你本机路径，故内联附上）。\n\n"
            f"```\n{txt}\n```\n"
        )
    if not blocks: return instr
    return f"{body.strip()}\n\n---\n\n## 引用文档原文\n\n" + "\n".join(blocks) + "\n---\n" + envfacts

def stage(arm: str, inline: bool) -> Path:
    """给这一臂建独立 task 目录树。

    ⛔ 不能 symlink 整个 task 目录再改 instruction.md —— 那会写穿到真身。
    用 copytree（tasks 里最大的是 repo-snapshot.tar.gz 1-3MB，6 题 × 4 臂可接受）。
    """
    st = BASE / f"stage/{arm}"
    if st.exists(): shutil.rmtree(st)
    st.mkdir(parents=True)
    for t in TASKS:
        shutil.copytree(c.MVP_TASKS / t, st / t, symlinks=False)
        if inline:
            (st / t / "instruction.md").write_text(inline_instruction(t), encoding="utf-8")
    return st

def run(arm: str, path: Path, turns: int) -> Path:
    out = BASE / f"exp-fix/{arm}"
    out.mkdir(parents=True, exist_ok=True)
    c.assert_jobs_dir_ok(out)                      # R-3
    cmd = ["harbor", "run", "-p", str(path), "-a", "sid_code_agent:SidCodeAgent",
           "-m", f"{FAMILY}/{MODEL}", "-n", "6",   # E1 已实测 -n 6 判分零损伤
           "-k", "1", "-o", str(out),
           "--ak", f"max_turns={turns}",           # 声明式旋钮，非私有环境变量
           "--verifier-timeout-multiplier", "6",
           "--agent-timeout-multiplier", "3",      # 轮数 ×3 ⇒ 墙钟也要放开，否则被超时截断
           "-y"]
    env = {**os.environ, "HARBOR_TELEMETRY": "0",
           "PYTHONPATH": "/Users/zhourusheng/Code/person/sid-code/evals/external-benchmarks/harbor",
           "SID_HARBOR_GATEWAY_URL": f"http://{GW}", "SID_HARBOR_PROVIDER": FAMILY,
           "SID_HARBOR_BINARY_ARM64": str(Path("~/.local/share/sid-harbor-gateway/bins/sid-code-arm64-30586ff003c9").expanduser()),
           "SID_HARBOR_BINARY_X64": str(Path("~/.local/share/sid-harbor-gateway/bins/sid-code-x64-30586ff003c9").expanduser()),
           "no_proxy": "127.0.0.1,localhost", "NO_PROXY": "127.0.0.1,localhost"}
    print(f"  [{arm}] inline={path.name} turns={turns} …", flush=True)
    t0 = time.time()
    with open(out / "run.log", "w", encoding="utf-8") as f:
        subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env=env,
                       check=False, stdin=subprocess.DEVNULL)
    print(f"  [{arm}] {(time.time()-t0)/60:.1f} 分钟", flush=True)
    return out

def collect(out: Path) -> list[dict]:
    rd = lib.latest_run(out)
    if rd is None: return []
    rows = []
    for f in sorted(rd.glob("T0*/result.json")):
        d = json.loads(f.read_text())
        rw = (d.get("verifier_result") or {}).get("rewards") or {}
        md = ((d.get("agent_result") or {}).get("metadata") or {})
        rows.append({"task": d["task_name"], "reward": rw.get("reward"),
                     "f2p": rw.get("f2p"), "p2p": rw.get("p2p"),
                     "error_code": rw.get("error_code"),
                     "subtype": md.get("sid_subtype"), "turns": md.get("sid_num_turns"),
                     "cost": (d.get("agent_result") or {}).get("cost_usd")})
    return rows

def main():
    only = sys.argv[1:] or None
    res = {}
    for arm, inline, turns in ARMS:
        if only and arm not in only: continue
        res[arm] = collect(run(arm, stage(arm, inline), turns))
    p = BASE / "exp-fix/results.json"
    prev = json.loads(p.read_text()) if p.exists() else {}
    prev.update(res)
    p.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding="utf-8")
    for arm, rows in prev.items():
        solved = sum(1 for r in rows if r["reward"] and r["reward"] >= 1.0)
        cost = sum(r["cost"] or 0 for r in rows)
        print(f"{arm:12} solved {solved}/{len(rows)}  ${cost:.2f}")

if __name__ == "__main__":
    main()
