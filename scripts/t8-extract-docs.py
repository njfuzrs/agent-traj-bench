"""从数据湖 + 镜像双通道提取 39 条题面引用的文档原文。

## 两条通道的优先级（刻意排这个顺序）

  1. **数据湖 `raw.jsonl` 的 tool_result** —— 这是**当时那份文档的字面内容**。
     原始会话第一步就是 Read 那个路径，返回值留在轨迹里。
  2. **docs-research 镜像**同名文件 —— 只在通道 1 拿不到时用。
     它可能已被后续改动过 ⇒ 与 base_commit 时点不一致 ⇒ 次优。

⚠️ 反过来（先镜像后轨迹）会静默引入时点漂移：题面描述的缺陷可能已在镜像版本里
被修掉，于是 agent 读到一份「已修复」的文档去改一个「未修复」的仓库。
两侧都不报错，形态是 agent 困惑 + 低分。

## 每条产物记 provenance

`agent_source` / `doc_channel` / `doc_bytes` / `doc_sha256` 必须写进 meta，
否则下游算 pass@1 时无法区分「内联了原文」与「内联了镜像近似版」。
"""
import hashlib, json, os, re, tomllib
from pathlib import Path

# ⚠️ 仓库根从 __file__ 反推，⛔ 不写死本机绝对路径。
# 且公开仓的题集在**仓库根**（tasks/ reports/ 与 scripts/ 平级），不再有 bench/v0.2-mini/ 前缀。
ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "tasks"
#: 🔴 只读数据湖，**公开仓不含它**（66G 未入库）⇒ 本脚本要重跑须 export LAKE_DIR 指到源仓那侧
LAKE = Path(os.environ.get("LAKE_DIR", ROOT / "data/pulled_sessions"))
REPORTS = ROOT / "reports"
OUT = REPORTS / "t8-fix/docs"
DOC_EXT = {".md", ".txt", ".jsonl", ".ts", ".yaml", ".yml"}
#: ⛔ `.json` **刻意不算文档**。唯一引用它的 T0011 指的是用户自己的
#: `~/.sid-code/settings.json`,而那条题面**已经自包含**:复现步骤(`/effort -p max`)、
#: 报错原文(`未设置 OPENAI_API_KEY`)全在题面里,settings.json 只是顺带提到的落点。
#: 把它当"必须内联的文档"去找,只会捞到 assistant 的分析文本 —— 那是**上一轮的结论**,
#: 内联进去等于泄漏答案(实测捞到 5875B 的「Now I have a complete understanding…」)。

def refs_in(instr: str) -> list[str]:
    return re.findall(r"'(/Users/[^']+)'", instr)

def from_lake(sid: str, want: str) -> str | None:
    """通道 1：轨迹里任何工具读到该文件的最长返回值。

    取**最长**而不是第一个：agent 可能先 Read 前 N 行（截断），后来再读全文。
    """
    raw = LAKE / sid / "raw.jsonl"
    if not raw.exists(): return None
    base = Path(want).name
    best = None
    for line in raw.open(errors="ignore"):
        try: d = json.loads(line)
        except Exception: continue
        # ⚠️ tool_use 与 tool_result 在**不同 message** 里(assistant 发起、user 回填)。
        # 把 ids 的作用域限制在单个 message 内 ⇒ 永远匹配不上 ⇒ 整条通道静默返回 None,
        # 形态是「数据湖一条都恢复不了」而探针明明说 89% 能恢复。所以 ids 必须跨整个 request。
        ids = set()
        for m in (d.get("request") or {}).get("messages") or []:
            c = m.get("content")
            if not isinstance(c, list): continue
            for b in c:
                if not isinstance(b, dict): continue
                if b.get("type") == "tool_use":
                    if base in json.dumps(b.get("input"), ensure_ascii=False):
                        ids.add(b.get("id"))
                elif b.get("type") == "tool_result" and b.get("tool_use_id") in ids:
                    raw_c = b.get("content")
                    txt = raw_c if isinstance(raw_c, str) else "\n".join(
                        x.get("text", "") for x in raw_c if isinstance(x, dict)
                    ) if isinstance(raw_c, list) else str(raw_c)
                    if best is None or len(txt) > len(best): best = txt
    # ⚠️ **匹配到工具调用 ≠ 拿到文档内容。** 实测三种假恢复:
    #   ① `wc -l <path>` 的返回是 "1854 /path/to/doc.md"(114 字节)——文件名在里面,
    #      所以 base-in-input 的匹配会命中,但内容是行数不是文档。
    #   ② `ls -la <path>` 同理。
    #   ③ agent 只是在自己的文本里提到该路径,tool_result 是别的东西。
    # 判据: 内容长度 < 800 字节,或整段只有一行且含该路径 ⇒ 判为未恢复。
    # 不设这道闸的形态是「37/37 全绿」而实际内联进去的是几行 shell 输出,
    # 且**两侧都不报错** —— agent 拿到一份空文档,行为与题面缺失时一模一样。
    if best is not None:
        stripped = best.strip()
        if len(stripped.encode()) < 800: return None
        if stripped.count("\n") <= 1 and Path(want).name in stripped: return None
        # ④ 后缀类型校验:`.json` 必须真能解析成 JSON。实测 T0011 引用
        #    `~/.sid-code/settings.json`,匹配到的却是 assistant 那段
        #    「Now I have a complete understanding…」分析文本(5875B,过了长度闸)。
        #    形态最阴:内联进去的是**上一轮 agent 的结论**,等于泄漏答案。
        if Path(want).suffix.lower() == ".json":
            try: json.loads(stripped)
            except Exception: return None
    return best

def strip_line_numbers(txt: str) -> str:
    """Read 工具返回带 `N\t` 行号前缀，去掉它才是文档原文。

    ⚠️ 只在**每一行都匹配**时才剥离 —— 否则会把正文里恰好形如 `12\t` 的内容也切掉。
    """
    lines = txt.split("\n")
    pat = re.compile(r"^\s*\d+\t")
    hit = sum(1 for ln in lines if pat.match(ln))
    if hit < len(lines) * 0.8: return txt
    return "\n".join(pat.sub("", ln) for ln in lines)

MIRROR = json.loads((REPORTS / "t6-recheck/doc-recoverable.json").read_text())["found"]

def from_mirror(task: str, ref_tail: str) -> str | None:
    """通道 2：T6 已定位的镜像路径。key 形如 `T0014|docs/bugfixes/todo/xxx.md`。"""
    for k, v in MIRROR.items():
        t, _, docpath = k.partition("|")
        if t == task and Path(docpath).name == ref_tail:
            p = Path(v)
            if p.exists(): return p.read_text(encoding="utf-8", errors="replace")
    return None

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    surv = sorted(json.loads((REPORTS / "t6-recheck/survivors.json").read_text())["survivors"])
    index = {}
    for t in surv:
        instr = (TASKS / t / "instruction.md").read_text(encoding="utf-8")
        sid = tomllib.loads((TASKS / t / "task.toml").read_text())["metadata"]["source_unit_id"].split("#")[0]
        entries = []
        for ref in refs_in(instr):
            if Path(ref).suffix.lower() not in DOC_EXT:
                entries.append({"ref": ref, "channel": "skip-not-a-doc"})
                continue
            body, ch = from_lake(sid, ref), "lake"
            if body: body = strip_line_numbers(body)
            if not body:
                body, ch = from_mirror(t, Path(ref).name), "mirror"
            if not body:
                entries.append({"ref": ref, "channel": "MISSING"}); continue
            fn = f"{t}__{hashlib.sha1(ref.encode()).hexdigest()[:8]}.md"
            (OUT / fn).write_text(body, encoding="utf-8")
            entries.append({
                "ref": ref, "channel": ch, "file": fn,
                "bytes": len(body.encode()),
                "sha256": hashlib.sha256(body.encode()).hexdigest()[:16],
            })
        index[t] = {"source_unit_id": sid, "docs": entries}
    (OUT.parent / "docs-index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    docs = [e for v in index.values() for e in v["docs"] if e["channel"] != "skip-not-a-doc"]
    from collections import Counter
    print("通道分布:", dict(Counter(e["channel"] for e in docs)))
    miss = sorted({t for t, v in index.items() for e in v["docs"] if e["channel"] == "MISSING"})
    print(f"文档 {len(docs)} 处，缺失 {len([e for e in docs if e['channel']=='MISSING'])} 处，涉及 task: {miss}")
    print(f"产物 → {OUT}")

if __name__ == "__main__":
    main()
