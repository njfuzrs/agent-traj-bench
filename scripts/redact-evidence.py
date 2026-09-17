#!/usr/bin/env python3
"""证据层脱敏 —— 把私有仓源码物料路径换成占位符，让证据能进公开落点。

出处：`docs-research/trajectory-platform/20260917-evidence-archive-plan.md` §4.5。

## 为什么要有这个脚本

公开仓已有**两条脱敏先例**，作用不同，⛔ 别混：

| 先例 | 占位符 | 产出方 | 作用 |
|---|---|---|---|
| ① 路径登录名 | `<USER>` | `pipeline/s1_s3/s2_rules.py` 的 `redact_home_paths()`，**自动** | `/Users/<真名>` → `/Users/<USER>`，⚠️ **路径其余部分保留**（下游 S4 分诊要靠它） |
| ② 私有仓源码路径 | `<REDACTED-PRIVATE-PATH>` | **无脚本** ⇒ 拆仓时手工逐处改 | 消掉门禁⑤ 盯的私有仓源码物料路径 |

⇒ **本脚本补的是先例② 缺的那个。** 手工做过一次可以（`reports/t8-fix/docs/` 下那份
T0063 报告就是手工改的），做第二次就必须有脚本 —— 否则下次跑评测又是一轮手工，
且**无法自证做全了**。

## 判据是「门禁⑤ 归零」，不是「看起来干净」

模式**必须与 `.github/workflows/ci.yml` 的门禁⑤ 逐字一致**（见 `PATTERN_PARTS`）。
⛔ 不许写宽（例如只写裸仓名）：门禁⑤ 的注释自己写着，写宽会误伤
`reports/t4-env.md` 与 card 里的**合规披露散文**（解释「哪些仓被挡了、为什么」）
—— 那是另一种破坏，且会让门禁永远红然后被人关掉。

⚠️ **两个分支会重叠**（实测）：一条完整的源码文件路径同时命中
分支①（仓名 + 前端源码后缀）与分支②（仓名 + `src`/`packages` 目录段）。
⇒ 替换必须**循环到不再命中**，单趟替换会剩下残串，门禁⑤ 仍然红。

## 用法

    python3 scripts/redact-evidence.py --root <证据根目录> --dry-run   # 只列，不改
    python3 scripts/redact-evidence.py --root <证据根目录>             # 实改
    python3 scripts/redact-evidence.py --root <证据根目录> --verify    # 只验（正向 + JSONL 合法性）
    python3 scripts/redact-evidence.py --root <证据根目录> --self-test-narrow   # 反向自证

`--root` **必须显式给，⛔ 无默认值**：默认成仓内某目录，在公开仓上就是
「目录不存在 ⇒ 命中 0 ⇒ 恒绿」（同 `check-evidence-due.py` 的 `EVIDENCE_RUNS_ROOT` 纪律）。

退出码：0 成功；4 判据不成立（命中数与预期不符 / 验证失败）；5 缺参数或根目录不存在。
⛔ 不用 1 —— 那和 argparse 的参数错混了（同 `t4-build-env.py` 的约定）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

#: 门禁⑤ 的模式，**拆成不可拼接的片段**再在运行时组装。
#:
#: 🔴 为什么拆：门禁⑤ 扫**全仓**（只排 `.git`/`__pycache__`/`tests`/两个 cache 目录），
#: `scripts/` 不在排除表里 ⇒ 本文件自己会被扫。实测模式**原文**不自命中
#: （原文里仓名后面跟的是 `|` 或 `)`，不是两个分支都要求的 `/`），但只要有人在注释里
#: 写一条**举例用的完整路径**（形如 `<私有仓>/<子目录>/packages/…`）就会立刻触发。
#: ⇒ 拆片段是把「不许在本文件里写出完整形态」这条约束**变成结构上做不到**，
#: ⛔ 不是因为原文会自命中。同 `ci.yml` 门禁⑧ 注释里那条「举例写全会被门禁⑤ 自己扫到」。
_REPOS_A = ("anka" "-app", "iam" "-studio" "-fe", "tag" "-studio", "ontology" "-studio")
_REPOS_B = ("anka" "-app", "iam" "-studio" "-fe")
_SUFFIXES = ("vue", "tsx", "ts", "json")
_DIRSEGS = ("src", "packages")

#: 组装结果与 ci.yml 门禁⑤ 的 `PAT` **逐字一致**，由单测
#: `test_redact_pattern_matches_gate5` 逐字符盯着（⛔ 别只靠人眼比对）。
PATTERN_PARTS = (
    f"({'|'.join(_REPOS_A)})/[A-Za-z0-9_./-]*\\.({'|'.join(_SUFFIXES)})",
    f"({'|'.join(_REPOS_B)})/[A-Za-z0-9_.-]+/({'|'.join(_DIRSEGS)})/",
)
PATTERN = "|".join(PATTERN_PARTS)

#: 占位符 —— 照先例②（公开仓现存 164 处）。
#: ⚠️ 它本身**不匹配** `PATTERN`（无 `/`、无源码后缀）⇒ 脚本天然幂等。
PLACEHOLDER = "<REDACTED-PRIVATE-PATH>"

#: 期望的作用面（本次归档实测值），用于 `--dry-run` 的自证。
#: ⛔ 不是硬编码路径白名单：脚本仍扫全树，这只是「扫出来的应该正好是这些」的判据。
#:
#: 🔴 **这两个数不是 3/95 —— 那是一次真实的漏扫，务必读完再改。**
#: 方案文档 §2.2 用 `grep -rlIE` 量出「4 文件 / 95 处」，实测**漏了 6 个文件 / 728 处**。
#: 原因：本机 `grep` 是 **ugrep**（`grep --version` 自报 `ugrep 7.8.4`），
#: 它**默认读 `.gitignore`**；而证据里有
#: `<trial>/agent/sid-home/.gitignore`（sid-code 启动时自动生成，忽略
#: `sessions/` `trajectories/` `*.log` 等运行时目录）⇒ 递归扫时那 6 个文件被静默跳过。
#: 实测同一目录同一模式三种扫法：
#:     ugrep 默认 → 4 文件 ｜ ugrep --no-ignore-files → 10 ｜ /usr/bin/grep → 10
#: ⚠️ 逐个点名文件时 ugrep **能**命中 ⇒ 漏扫只在**递归**时发生，最难自查的形态。
#: ⇒ 本脚本用 Python 自己走目录树（`rglob`），**不经过任何 grep**，
#: ⛔ 别把它改回 `subprocess` 调 grep —— 那会把这个漏扫重新引进来。
#: ⚠️ CI 上是 GNU grep（不读 .gitignore）⇒ **CI 会看见这 6 个文件**。
#: 也就是说：漏扫的方向是「本地假绿、CI 报红」，而不是反过来。
EXPECTED_SITES = 823
EXPECTED_FILES = 10


def _compiled(pattern: str) -> re.Pattern[bytes]:
    """按**字节**编译。

    ⚠️ 证据里的 `job.log` / `trial.log` 含 ANSI 转义与 box-drawing 字符 ⇒ 按字节处理，
    ⛔ 不解码成文本、⛔ 不做行宽重排、⛔ 不 strip 尾部空格 —— 那会改掉终端输出的原貌。
    """
    return re.compile(pattern.encode("utf-8"))


def _is_probably_binary(raw: bytes) -> bool:
    """与 `grep -I` 同口径：含 NUL 即视为二进制，跳过。

    ⚠️ 这是为了让本脚本的作用面与门禁⑤（`grep -rIE`）**完全对齐**：
    门禁跳过的文件，脚本改了也没意义；门禁不跳过的，脚本必须覆盖。
    """
    return b"\x00" in raw[:8192]


def redact_bytes(raw: bytes, pat: re.Pattern[bytes]) -> tuple[bytes, int]:
    """循环替换到不再命中，返回 (新字节, 替换处数)。

    🔴 **必须循环**：两个分支重叠（实测一条完整源码路径同时命中两支），
    单趟 `sub` 会把长匹配换掉后剩下短残串 ⇒ 门禁⑤ 仍然红。
    ⚠️ 每轮都重新扫，直到 `subn` 报 0 —— 而占位符不匹配模式 ⇒ 必然收敛。
    """
    total = 0
    for _ in range(100):  # 上限只为兜住理论上的不收敛，实测 2 轮内结束
        raw, n = pat.subn(PLACEHOLDER.encode("utf-8"), raw)
        total += n
        if n == 0:
            return raw, total
    raise RuntimeError("替换未收敛 —— 占位符本身可能命中了模式，检查 PLACEHOLDER")


def scan(root: Path, pat: re.Pattern[bytes]) -> list[tuple[Path, int]]:
    """扫全树，返回 [(文件, 命中处数)]，按路径排序。⛔ 不改任何字节。"""
    hits: list[tuple[Path, int]] = []
    for p in sorted(root.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue  # ⚠️ symlink 不跟随：它的目标串是历史事实，且门禁⑤ 也不读它
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        if _is_probably_binary(raw):
            continue
        n = len(pat.findall(raw))
        if n:
            hits.append((p, n))
    return hits


def _json_ok(blob: bytes) -> bool:
    """这段字节是否为合法 JSON。"""
    try:
        json.loads(blob)
        return True
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return False


def json_damage(old_raw: bytes, new_raw: bytes, whole: bool) -> list[str]:
    """差分判据：返回「原本合法、脱敏后变不合法」的位置列表（空 = 无损伤）。

    🔴 **判据必须是差分的，⛔ 不是「整个文件逐行合法」。** 实测证据里两个文件
    脱敏**前**就有大量非 JSON 行 —— `agent/sid-code.jsonl` 7816 行里 7391 行、
    `session.traj` 11438 行里 11287 行都不是 JSON（那是 agent 的**日志与 JSON 混排**，
    后缀 `.jsonl` 只是命名习惯）。用绝对判据 ⇒ 第 1 行就报红，
    而那**与脱敏无关**：报的是历史事实，不是本次损伤。
    ⚠️ 绝对判据的危害不只是假红：它把「脱敏改坏了行」和「这文件本来就不是 JSONL」
    混成同一个信号 ⇒ 真出损伤时反而看不出来。

    `whole=True` 时按**整份** JSON 判（`.json` 单体文档），否则**逐行**判。
    """
    if whole:
        if _json_ok(old_raw) and not _json_ok(new_raw):
            return ["整份 JSON 由合法变为不合法"]
        return []
    bad: list[str] = []
    old_lines, new_lines = old_raw.split(b"\n"), new_raw.split(b"\n")
    if len(old_lines) != len(new_lines):
        return [f"行数变了：{len(old_lines)} → {len(new_lines)}（替换引入/删除了换行）"]
    for i, (a, b) in enumerate(zip(old_lines, new_lines), 1):
        if a == b or not a.strip():
            continue
        if _json_ok(a) and not _json_ok(b):
            bad.append(f"第 {i} 行由合法 JSON 变为不合法")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description="证据层脱敏（先例② 的脚本化）")
    ap.add_argument("--root", required=True, type=Path,
                    help="证据根目录（⛔ 无默认值，见模块 docstring）")
    ap.add_argument("--dry-run", action="store_true", help="只列出将改的文件与处数")
    ap.add_argument("--verify", action="store_true",
                    help="只验：门禁⑤ 归零（+ 给了 --baseline 时验 JSON 无损伤）")
    ap.add_argument("--baseline", type=Path, default=None,
                    help="脱敏前的原件目录，用于 --verify 的 JSON 损伤差分比对")
    ap.add_argument("--self-test-narrow", action="store_true",
                    help="反向自证：故意只用分支① 扫，必须仍点名 job.log。"
                         "🔴 --root 必须给**脱敏前的原件目录**（见下方注释）")
    ap.add_argument("--expect-sites", type=int, default=EXPECTED_SITES,
                    help=f"预期总处数（默认 {EXPECTED_SITES}，仅 --dry-run 校验）")
    ap.add_argument("--expect-files", type=int, default=EXPECTED_FILES,
                    help=f"预期文件数（默认 {EXPECTED_FILES}，仅 --dry-run 校验）")
    args = ap.parse_args()

    root: Path = args.root.expanduser()
    if not root.is_dir():
        print(f"::error::根目录不存在: {root}", file=sys.stderr)
        return 5

    pat = _compiled(PATTERN)

    # ── 反向自证：把模式故意改窄，必须仍报红并**点名** ──────────────
    #
    # 🔴 **必须跑在「脱敏前的原件」上**（`pre-redact-originals/` 那类目录），
    # ⛔ 不是已脱敏的归档根 —— 后者命中恒为 0，于是这条自证会输出
    # 「命中 0 个文件 / ❌ 未点名」。那**不是**判据不成立，是**判据本身失效**：
    # 一个「必须能发现问题」的自证，跑在没有问题的目录上，永远无法证明它有效。
    # ⚠️ 实测踩过：脱敏实跑后顺手对归档根跑这条，得到 exit=4，
    # 一眼看去像「反向自证没过」，其实是取数源选错了。
    if args.self_test_narrow:
        narrow = _compiled(PATTERN_PARTS[0])  # 只留分支①，去掉 packages/src 那支
        hits = scan(root, narrow)
        print(f"[反向自证] 窄模式（仅分支①）命中 {len(hits)} 个文件：")
        for p, n in hits:
            print(f"  {p.relative_to(root)}  sites={n}")
        named = [str(p.relative_to(root)) for p, _ in hits]
        ok = any(x.endswith("job.log") for x in named)
        print(f"[反向自证] 是否点名 job.log：{'✅ 是' if ok else '❌ 否'}")
        if not hits:
            print("::error::窄模式命中 0 ⇒ 本次自证**无效**（不是不成立）。"
                  "--root 大概给了已脱敏的目录，请改指脱敏前的原件目录", file=sys.stderr)
        return 0 if ok else 4

    hits = scan(root, pat)
    total_sites = sum(n for _, n in hits)

    # ── 只验 ────────────────────────────────────────────────────
    if args.verify:
        print(f"[验证] 门禁⑤ 模式命中：{len(hits)} 个文件 / {total_sites} 处")
        for p, n in hits:
            print(f"  ❌ {p.relative_to(root)}  sites={n}")
        bad = False
        if hits:
            print("::error::门禁⑤ 模式仍有命中 ⇒ 脱敏未做全")
            bad = True
        # JSON 损伤只能**差分**判 ⇒ 需要基线。⛔ 不在这里做绝对判据
        # （证据里两个文件脱敏前本就大量非 JSON 行，见 json_damage 的 docstring）。
        if args.baseline:
            base = args.baseline.expanduser()
            if not base.is_dir():
                print(f"::error::基线目录不存在: {base}", file=sys.stderr)
                return 5
            n_cmp = 0
            for bp in sorted(base.rglob("*")):
                if bp.is_symlink() or not bp.is_file():
                    continue
                if bp.suffix not in (".jsonl", ".json", ".traj"):
                    continue
                cur = root / bp.relative_to(base)
                if not cur.is_file():
                    continue
                n_cmp += 1
                for x in json_damage(bp.read_bytes(), cur.read_bytes(),
                                     whole=(bp.suffix == ".json")):
                    print(f"::error::JSON 损伤 {bp.relative_to(base)}: {x}")
                    bad = True
            print(f"[验证] 与基线差分比对了 {n_cmp} 个 JSON/JSONL 文件")
        else:
            print("[验证] ⚠️ 未给 --baseline ⇒ 只验门禁⑤ 归零，"
                  "**未验** JSON 损伤（那需要脱敏前的基线）")
        if not bad:
            print("✅ 门禁⑤ 归零" + ("，且无 JSON 损伤" if args.baseline else ""))
        return 4 if bad else 0

    # ── 干跑 ────────────────────────────────────────────────────
    if args.dry_run:
        print(f"[干跑] 将改 {len(hits)} 个文件 / {total_sites} 处：")
        for p, n in hits:
            print(f"  {p.relative_to(root)}  sites={n}")
        ok = (total_sites == args.expect_sites and len(hits) == args.expect_files)
        print(f"[干跑] 判据：期望 {args.expect_files} 文件 / {args.expect_sites} 处 "
              f"⇒ 实得 {len(hits)} / {total_sites}  {'✅' if ok else '❌'}")
        if not ok:
            print("::error::偏差说明模式写错了 —— 多了是写宽（会误伤合规披露散文），"
                  "少了是写窄（门禁⑤ 会红）", file=sys.stderr)
            print("::error::⚠️ 若你是拿 `grep -r` 的数来对：先跑 `grep --version`。"
                  "ugrep 默认读 .gitignore，会在递归时静默漏掉 sid-home 下 6 个文件"
                  "（见 EXPECTED_SITES 上方注释）", file=sys.stderr)
            return 4
        return 0

    # ── 实改 ────────────────────────────────────────────────────
    changed = 0
    damage: list[str] = []
    for p, _ in hits:
        raw = p.read_bytes()
        new, n = redact_bytes(raw, pat)
        if new == raw:
            continue
        # 🔴 JSON 损伤判据在**写盘前**用内存里的前后两份字节现算 —— 这样判据自带基线，
        # ⛔ 不依赖外部备份目录（备份是回退手段，不该是判据的取数源）。
        if p.suffix in (".jsonl", ".json", ".traj"):
            d = json_damage(raw, new, whole=(p.suffix == ".json"))
            damage += [f"{p.relative_to(root)}: {x}" for x in d]
        p.write_bytes(new)
        changed += 1
        print(f"  改 {p.relative_to(root)}  {n} 处")
    print(f"[实改] {changed} 个文件已脱敏，共 {total_sites} 处 → {PLACEHOLDER}")

    # 改完立刻自验，⛔ 不留给下一条命令
    left = scan(root, pat)
    if left:
        print(f"::error::改后仍有 {len(left)} 个文件命中 ⇒ 替换未收敛", file=sys.stderr)
        return 4
    print("[自验①正向] 门禁⑤ 模式命中 0 ✅")
    if damage:
        for x in damage:
            print(f"::error::JSON 损伤 {x}", file=sys.stderr)
        return 4
    print("[自验④JSON] 无任何原本合法的 JSON 行/文档被改坏 ✅（差分判据，见 json_damage）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
