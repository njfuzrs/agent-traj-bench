#!/usr/bin/env python3
"""T3 前置 — 在 T4 剔除后的快照上采 P2P 名单

出处：`docs-research/trajectory-platform/bench-mvp-plan.md` v1.2 §4 T3
+ `bench/v0.2-mini/reports/t4-env.md` §9.2/§9.3（三条口径已定档）

输入：`meta/snapshots.jsonl`（65 条 ok）+ `tasks/T####/environment/`（快照与 Dockerfile）
输出：`meta/p2p.jsonl` —— 每个 unique base 一行，含该 base 的绿名单与每条 task 的 P2P 名单

## 为什么是独立脚本，不并进 t3-build-harbor-tasks.py

这一步要**起 50 个容器、跑 3-4 小时**（实测建镜像 2m40s + 全量 bun test 75s）。
task 目录生成是纯文本处理、秒级完成。混在一起会让「改个 test.sh 模板」都要重跑几小时。
所以：本脚本产出 `p2p.jsonl`（贵、可缓存），生成器只读它（便宜、可反复重跑）。

## 三条已定档的口径（`t4-env.md` §9.3，不再权衡）

① **按 `base_commit` 去重**：65 条 task 只覆盖 50 个 unique base，同 base 的容器文件树
   逐字相同。⚠️ 但 **F2P 必须按 task 独立算**（每条 `test_patch` 不同），只有 P2P 共享。
② **「20-30 个」的单位是文件**，与「用路径而非 `--test-name-pattern` 选择」自洽
   （测试名含中文与空格，实测样例 `切换权限模式`）。
③ **跑两次取交集，但复跑只跑候选文件**：全量单次 45-145 秒，候选文件复跑几乎免费。

## 🔴 本轮实测抓到的坑：junit XML 会**整份漏掉「加载失败」的文件**

这是本脚本最重要的一条，它是 R1「绿着坏掉」的一个新形态，方案与 T4 报告都没写：

    bun test --reporter=junit tests/good.test.ts tests/loadfail.test.ts
    → XML 的 root: tests="6" failures="0"      ← 看着全绿
    → 日志:        6 pass / 1 fail / 1 error   ← 实际有一个文件根本没跑起来

`tests/ui/markdown.test.ts` 这类文件 `import` 不到模块（`Cannot find package 'chalk'`），
bun **不会为它生成 `<testsuite>` 节点**，于是它从 XML 里**整个消失**。单独跑它时
更极端：**XML 文件根本不写**（`cat: /tmp/a.xml: No such file or directory`）。

后果分两处，都很隐蔽：
  - **采样侧**（本脚本）：若把「XML 里 failures==0」当绿，加载失败的文件会因为
    「不在 XML 里 → 没有 failures>0 记录」而被**误判为绿**，进 P2P 名单后恒败。
  - **判分侧**（`tests/score.py`）：只读 root 的 `failures` 属性会把
    「一个文件没跑起来」判成满分通过。所以判分必须做**文件覆盖核对**
    （要求的每个文件都必须在 XML 里出现），不能只看失败计数。

所以本脚本的绿判据是**三条同时成立**：① 文件出现在 XML 的直接子 `testsuite` 里
（证明它加载成功了）② `failures == 0` ③ `tests > 0`（没有用例的文件不构成回归保护）。

## 磁盘纪律：建一个、采完、立刻删

每个镜像约 800MB，50 个 = 40GB，而 colima VM 只剩 41GB。所以严格
**build → sample → rmi** 串行，不预建。已存在的 `t4:*` / `t3probe:*` 镜像会被复用且**不删**
（它们是 T4 交接给 T5 的资产，见 `t4-env.md` §9.5）。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common as c

SNAPSHOTS = c.MVP_META / "snapshots.jsonl"
P2P_OUT = c.MVP_META / "p2p.jsonl"

#: 容器往这里写 junit XML。**必须在 $HOME 之下** —— colima `mounts: []`，
#: VM 内只挂了 `$HOME` 一个 virtiofs，用 `/tmp` 宿主读不到
#: （与 TZ R-3 同一个坑，见 common.assert_jobs_dir_ok）。
WORK_DIR = Path.home() / ".cache/traj-bench-t3"

#: P2P 目标条数（口径②：单位是**文件**）
P2P_MIN, P2P_MAX = 20, 30

#: 复跑候选要多取的余量。复跑会踢掉 flaky，若只取 30 个去复跑，掉几个就跌破 30 ——
#: 而重新补选需要再起一轮复跑（未验过的文件不能直接进名单）。多取 10 个一次到位。
P2P_MARGIN = 10

#: T4 交接的已知落选样本（`t4-env.md` §9.2）：它们断言被剔除的 runner 落盘存在。
#: 在剔除后的快照上采会自然排除 —— 若它们进了名单，说明采样跑在了**错误的文件树**上。
CANARY_MUST_NOT_BE_GREEN = (
    "tests/skill/incident-rca.test.ts",
    "tests/skill/security-audit.test.ts",
)


def image_exists(tag: str) -> bool:
    return subprocess.run(["docker", "image", "inspect", tag], capture_output=True).returncode == 0


def build_image(task_id: str, tag: str) -> float:
    """建镜像，返回耗时秒。构建期联网（要装依赖），运行期才 `--network none`。"""
    env_dir = c.MVP_TASKS / task_id / "environment"
    snap = env_dir / "repo-snapshot.tar.gz"
    if not snap.exists():
        raise FileNotFoundError(
            f"{snap} 不存在 —— 快照不入 git（429MB），换机器后先跑 "
            f"scripts/mvp/t4-build-env.py 重建（见 t4-env.md §9.1）"
        )
    t0 = time.time()
    proc = subprocess.run(
        ["docker", "build", "-q", "-t", tag, "."], cwd=env_dir, capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise RuntimeError(f"docker build 失败 {tag}\n{proc.stderr[-1500:]}")
    return time.time() - t0


def parse_green(xml_path: Path) -> tuple[dict[str, int], dict]:
    """解析 junit XML → (绿文件 → 用例数, 汇总)。

    绿的判据是三条**同时**成立（模块 docstring 有实测形态）：
      ① 文件出现在直接子 `testsuite` 里 —— 证明它**加载成功**了。
         加载失败的文件在 XML 里整个不存在，只看 failures 会把它当绿。
      ② `failures == 0`
      ③ `tests > 0` —— 零用例的文件不构成回归保护
    """
    if not xml_path.exists():
        # 单文件加载失败时 bun 连 XML 都不写。这不是「解析失败」，是「一个都没绿」
        return {}, {"xml_missing": True}
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError as e:
        return {}, {"xml_parse_error": str(e)[:200]}

    green: dict[str, int] = {}
    red: list[str] = []
    for suite in root:  # 只看直接子节点：bun 一个文件一个顶层 testsuite
        f = suite.get("file")
        if not f:
            continue
        n_tests = int(suite.get("tests") or 0)
        n_fail = int(suite.get("failures") or 0)
        if n_fail == 0 and n_tests > 0:
            green[f] = n_tests
        else:
            red.append(f)
    return green, {
        "root_tests": int(root.get("tests") or 0),
        "root_failures": int(root.get("failures") or 0),
        "n_files_in_xml": len([s for s in root if s.get("file")]),
        "n_green_files": len(green),
        "n_red_files": len(red),
        "red_sample": sorted(red)[:10],
    }


def run_tests(tag: str, out_name: str, test_cmd: str, files: list[str] | None) -> tuple[dict[str, int], dict, float]:
    """在容器里跑测试并把 junit XML 落到宿主，返回 (绿文件, 汇总, 耗时)。

    `test_cmd` 取自 base 时点的 `package.json`（`snapshots.jsonl` 已落盘，§3.5）。
    3 条 monorepo base 带 `--test-name-pattern '^(?!.*\\[slow\\])'` —— 必须**照带**，
    否则「base 上本来就通过的测试」这个口径会和 task 自己的测试命令不一致。
    """
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    xml_host = WORK_DIR / f"{out_name}.xml"
    log_host = WORK_DIR / f"{out_name}.log"
    for p in (xml_host, log_host):
        p.unlink(missing_ok=True)

    target = " ".join(f"'{f}'" for f in files) if files else ""
    inner = (
        "cd /repo && "
        f"{test_cmd} --reporter=junit --reporter-outfile=/out/{out_name}.xml {target} "
        f"> /out/{out_name}.log 2>&1; true"
    )
    t0 = time.time()
    subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-v", f"{WORK_DIR}:/out", tag, "bash", "-lc", inner],
        capture_output=True,
        text=True,
    )
    elapsed = time.time() - t0
    green, summary = parse_green(xml_host)
    if log_host.exists():
        # 日志尾巴留证：XML 与日志的计数不一致正是「文件没跑起来」的信号
        summary["log_tail"] = log_host.read_text(errors="replace").strip().splitlines()[-6:]
    return green, summary, elapsed


def f2p_precheck(tag: str, test_cmd: str, task_id: str, test_patch: str, f2p_files: list[str]) -> dict:
    """在 base 上打 test_patch、跑该 task 的 F2P —— **必须红**，否则 F2P 名不副实。

    ## 为什么这一步必须在这里做，而不是留给 T5

    F2P 的定义是「打了 test_patch 但没打 code_patch 时**必须 FAIL**」（§4 T3 的构造图）。
    实测 T0001 就不满足：14 pass / 0 fail —— 它的新测试测的是**base 上已有的行为**，
    于是 `nop`（空 patch）也能拿满分，`oracle` 与 `nop` 的分**无法区分**。
    这正是方案 §4 T3 遗留问题里预告的 `test_authoring` 形态：
    「测试自己测自己」在 `nop` 门禁下未必报红。

    留给 T5 做的代价是**重建 50 个镜像**（实测冷构建 58-160 秒/个，约 2.5 小时）——
    而采 P2P 时容器本来就是活的，顺手多跑一次 F2P 只多几秒。所以在这里判。

    ⚠️ 这里**不打 code_patch**：那是 oracle 侧的事（T5 的 `--agent oracle` 会验），
    本函数只回答「不改代码时它红不红」这一个问题。

    返回 `{"is_f2p": bool, ...}`。`is_f2p=False` 的 task 由 T6 人工过目决定去留 ——
    本脚本只标记，不淘汰（淘汰判据属于 T5/T6，见方案 §4 T3 遗留问题）。
    """
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    patch_host = WORK_DIR / f"{task_id}-test.diff"
    patch_host.write_text(test_patch if test_patch.endswith("\n") else test_patch + "\n", encoding="utf-8")
    out_name = f"{task_id}-f2p"
    for suffix in (".xml", ".log"):
        (WORK_DIR / f"{out_name}{suffix}").unlink(missing_ok=True)

    target = " ".join(f"'{f}'" for f in f2p_files)
    inner = (
        "cd /repo && "
        # 同 test.sh：tar 解包后全库 stat-dirty，--3way 查 index 会报 does not match index
        "git update-index -q --refresh || true; "
        f"if ! git apply --3way /out/{task_id}-test.diff 2>/out/{out_name}.applyerr; then "
        f'  echo APPLY_FAILED > /out/{out_name}.log; exit 0; fi; '
        f"{test_cmd} --reporter=junit --reporter-outfile=/out/{out_name}.xml {target} "
        f"> /out/{out_name}.log 2>&1; true"
    )
    subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-v", f"{WORK_DIR}:/out", tag, "bash", "-lc", inner],
        capture_output=True,
        text=True,
    )
    log = (WORK_DIR / f"{out_name}.log").read_text(errors="replace") if (WORK_DIR / f"{out_name}.log").exists() else ""
    if log.startswith("APPLY_FAILED"):
        err = (WORK_DIR / f"{out_name}.applyerr")
        return {
            "is_f2p": False,
            "reason": "test_patch_apply_failed",
            "detail": (err.read_text(errors="replace")[-300:] if err.exists() else ""),
        }

    green, summary = parse_green(WORK_DIR / f"{out_name}.xml")
    # 红的判据要宽：XML 缺失 / 文件没出现（加载失败）/ 有 failures —— 都算「红」，
    # 都满足 F2P 的语义（不改代码时这些测试过不去）。
    n_green_required = sum(1 for f in f2p_files if f in green)
    is_red = n_green_required < len(f2p_files)
    return {
        "is_f2p": is_red,
        "reason": None if is_red else "f2p_passes_at_base",
        "n_f2p_files": len(f2p_files),
        "n_green_at_base": n_green_required,
        "xml_summary": {k: v for k, v in summary.items() if k != "log_tail"},
        "log_tail": log.strip().splitlines()[-5:],
    }


def pick_candidates(green: dict[str, int], touched: list[str], limit: int = P2P_MAX) -> list[str]:
    """从绿名单里为一条 task 选 P2P 候选：**同目录优先**（§4 T3）。

    同目录的测试更可能被这次改动波及，防回归价值更高。排序键：
      0 = 与 patch 触及文件同目录 / 1 = 同顶层目录 / 2 = 其余；同档内按用例数降序
    （用例多的文件回归覆盖面更大），最后按路径定序保证**可复算**。

    ⚠️ 先剔掉这条 task 自己 patch 触及的路径 —— 它们是 F2P，不能同时当 P2P。
    """
    touched_set = set(touched)
    dirs = {p.rsplit("/", 1)[0] for p in touched_set if "/" in p}
    tops = {p.split("/")[0] for p in touched_set}

    def rank(path: str) -> tuple[int, int, str]:
        d = path.rsplit("/", 1)[0] if "/" in path else ""
        tier = 0 if d in dirs else (1 if path.split("/")[0] in tops else 2)
        return (tier, -green[path], path)

    pool = [p for p in green if p not in touched_set]
    return sorted(pool, key=rank)[:limit]


def main() -> int:
    ap = argparse.ArgumentParser(description="T3 前置 — 在剔除后的快照上采 P2P 名单")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个 unique base（调试用）")
    ap.add_argument("--only-base", default=None, help="只处理某个 base_commit（前缀匹配）")
    ap.add_argument("--keep-images", action="store_true", help="采完不删镜像（默认删，磁盘只剩 41GB）")
    ap.add_argument("--resume", action="store_true", help="跳过 p2p.jsonl 里已采过的 base")
    ap.add_argument(
        "--overwrite",
        action="store_true",
        help="已有 p2p.jsonl 时从头重采并覆盖它（**会丢弃数小时的容器产物**，慎用）",
    )
    args = ap.parse_args()

    # 🔴 防手滑覆盖：本脚本要跑数小时（50 个容器），而 --resume 是**可选**的 ——
    # 不带它重跑会把已采好的 p2p.jsonl 从头覆盖掉，且没有任何提示。
    # 采样结果不可从别处重建（要重新起 50 个容器），所以这里改成必须显式表态。
    if P2P_OUT.exists() and not (args.resume or args.overwrite or args.only_base or args.limit):
        n_done = sum(1 for _ in c.read_jsonl(P2P_OUT))
        print(
            f"🔴 {P2P_OUT} 已存在（{n_done} 个 base）。它是数小时容器跑出来的产物，"
            f"不可从别处重建。\n"
            f"   续采：--resume（跳过已采过的 base）\n"
            f"   重采：--overwrite（**丢弃现有结果**）",
            file=sys.stderr,
        )
        return 2

    c.ensure_mvp_dirs()
    rows = [r for r in c.read_jsonl(SNAPSHOTS) if r.get("ok")]
    resolved = {r["unit_id"]: r for r in c.read_jsonl(c.RESOLVED) if r.get("ok")}

    # 按 base 分组（口径①）。同一 base 的 task 共享容器文件树
    by_base: dict[str, list[dict]] = {}
    for r in rows:
        by_base.setdefault(r["base_commit"], []).append(r)

    # 🔴 已有产物必须**无条件读进来**，哪怕本轮只重采一个 base ——
    # 落盘那步是「done + 本轮结果」的合并覆写（见函数末尾），
    # 若这里不读，`--only-base` / `--limit` 会把 p2p.jsonl 从 50 行截成 1 行，
    # 且没有任何报错。只有 --overwrite 才是「真从头来」，那时才该丢掉旧的。
    done_all: dict[str, dict] = {}
    if P2P_OUT.exists() and not args.overwrite:
        done_all = {d["base_commit"]: d for d in c.read_jsonl(P2P_OUT)}

    # 跳过名单只包含**采成功**的 base：失败的那些正是 --resume 要重试的对象。
    # 把 ok=false 也算作「已采」，会让 --resume 对着一批失败记录空转报成功。
    done: dict[str, dict] = {}
    if args.resume:
        done = {b: d for b, d in done_all.items() if d.get("ok")}
        retry = sorted(b[:8] for b, d in done_all.items() if not d.get("ok"))
        print(
            f"resume：已采成功 {len(done)} 个 base 将跳过"
            + (f"；{len(retry)} 个失败的会重采：{retry}" if retry else ""),
            file=sys.stderr,
        )

    bases = list(by_base)
    if args.only_base:
        bases = [b for b in bases if b.startswith(args.only_base)]
    if args.limit:
        bases = bases[: args.limit]

    out: list[dict] = []
    for i, base in enumerate(bases, start=1):
        group = by_base[base]
        if base in done:
            out.append(done[base])
            print(f"[{i}/{len(bases)}] {base[:8]} 跳过（已采）", file=sys.stderr)
            continue

        lead = group[0]["task_id"]
        tag = f"t4:{lead}" if image_exists(f"t4:{lead}") else f"t3p:{lead}"
        reused = image_exists(tag)
        test_cmd = group[0]["test_cmd"]
        rec: dict = {
            "base_commit": base,
            "task_ids": [g["task_id"] for g in group],
            "image": tag,
            "image_reused": reused,
            "test_cmd": test_cmd,
        }
        print(
            f"[{i}/{len(bases)}] {base[:8]} tasks={len(group)} image={tag} "
            f"{'复用' if reused else '需构建'}",
            file=sys.stderr,
        )
        try:
            if not reused:
                rec["build_sec"] = round(build_image(lead, tag), 1)
                print(f"    构建 {rec['build_sec']}s", file=sys.stderr)

            # 第一遍：全量，拿绿名单
            green1, sum1, t1 = run_tests(tag, f"{base[:8]}-full", test_cmd, None)
            rec["full_run"] = {**sum1, "elapsed_sec": round(t1, 1)}
            print(f"    全量 {round(t1,1)}s → 绿文件 {len(green1)}", file=sys.stderr)
            if not green1:
                rec.update(ok=False, drop_reason="full_run_no_green")
                out.append(rec)
                continue

            # 每条 task 先各选候选，取并集做复跑（口径③：复跑只跑候选，不跑全量）
            per_task: dict[str, list[str]] = {}
            for g in group:
                r = resolved.get(g["unit_id"]) or {}
                touched = sorted(r.get("files") or {})
                # 多取 P2P_MARGIN 个送复跑：flaky 会在复跑里被踢掉，
                # 只取 30 个的话掉几个就跌破下限，补选又要再起一轮复跑
                per_task[g["task_id"]] = pick_candidates(green1, touched, limit=P2P_MAX + P2P_MARGIN)
            union = sorted({p for v in per_task.values() for p in v})

            green2, sum2, t2 = run_tests(tag, f"{base[:8]}-recheck", test_cmd, union)
            rec["recheck_run"] = {**sum2, "elapsed_sec": round(t2, 1), "n_requested": len(union)}
            flaky = sorted(set(union) - set(green2))
            rec["flaky_dropped"] = flaky
            print(
                f"    复跑 {len(union)} 文件 {round(t2,1)}s → 交集剔除 {len(flaky)}",
                file=sys.stderr,
            )

            stable = {p: green1[p] for p in green1 if p in green2 or p not in union}
            rec["p2p"] = {}
            for g in group:
                r = resolved.get(g["unit_id"]) or {}
                touched = sorted(r.get("files") or {})
                # 用「复跑后仍绿」的池子重选，flaky 已被踢出
                pool = {p: v for p, v in stable.items() if p in green2}
                rec["p2p"][g["task_id"]] = pick_candidates(pool, touched)

            # F2P 自检：容器还活着，顺手验「不改代码时 F2P 必须红」（见 f2p_precheck）
            rec["f2p_check"] = {}
            for g in group:
                r = resolved.get(g["unit_id"]) or {}
                f2p_files = sorted(p for p, v in (r.get("files") or {}).items() if v.get("is_test"))
                rec["f2p_check"][g["task_id"]] = f2p_precheck(
                    tag, test_cmd, g["task_id"], r.get("test_patch") or "", f2p_files
                )
            n_bad = sum(1 for v in rec["f2p_check"].values() if not v.get("is_f2p"))
            if n_bad:
                bad = [t for t, v in rec["f2p_check"].items() if not v.get("is_f2p")]
                print(f"    ⚠️ F2P 在 base 上就绿（非 fail-to-pass）：{bad}", file=sys.stderr)

            # 反向核对：T4 交接的两个 canary 若进了名单，说明跑在错的文件树上
            leaked = [
                (tid, p)
                for tid, lst in rec["p2p"].items()
                for p in lst
                if p in CANARY_MUST_NOT_BE_GREEN
            ]
            rec["canary_leaked"] = leaked
            rec["ok"] = not leaked and all(len(v) >= P2P_MIN for v in rec["p2p"].values())
            if leaked:
                rec["drop_reason"] = "canary_leaked"
            elif not rec["ok"]:
                rec["drop_reason"] = "p2p_below_min"
        except Exception as e:  # 单个 base 炸掉不该让整批中断
            rec.update(ok=False, drop_reason="exception", detail=f"{type(e).__name__}: {e}"[:500])
            print(f"    🔴 {rec['detail']}", file=sys.stderr)
        finally:
            if not args.keep_images and tag.startswith("t3p:"):
                subprocess.run(["docker", "rmi", "-f", tag], capture_output=True)

        out.append(rec)
        # 每个 base 采完就落盘 —— 3-4 小时的任务，中断了不该从头再来
        merged = {**done_all, **{r["base_commit"]: r for r in out}}
        c.write_jsonl(P2P_OUT, [merged[b] for b in by_base if b in merged])

    ok = [r for r in out if r.get("ok")]
    print(f"\nP2P 采样完成：{len(ok)}/{len(out)} 个 base 达标", file=sys.stderr)
    for r in out:
        if not r.get("ok"):
            print(f"  🔴 {r['base_commit'][:8]} {r.get('drop_reason')}", file=sys.stderr)
    return 0 if len(ok) == len(out) else 1


if __name__ == "__main__":
    raise SystemExit(main())
