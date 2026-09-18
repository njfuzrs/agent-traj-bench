#!/usr/bin/env python3
"""T10 — 把 v0.2-mini 评测过程证据打成 job 级 tar.zst，落到公开 HF dataset。

出处：`docs-research/trajectory-platform/20260917-evidence-archive-plan.md` §5.3。

## 为什么要有这个脚本

源仓 `trajectory-platform` 的 `bench/` 即将被清空（curation-migration §5.4）。
题面与快照已经在公开仓 / HF，但 **21 个 job 的过程证据（3.63 G）四处远端全无副本**。
本脚本把它们按 job 打包（342 M）进已有的公开 dataset `njfuzrs/agent-traj-bench`，
与 39 份快照同仓。

🔴 **脱敏是前置**（`redact-evidence.py`），本脚本假定 `--root` 已经过门禁⑤。
上传前会再解压扫一遍 —— HF commit 历史不可逆，传上去再删旧 revision 仍可取回。

## 用法

    python3 scripts/t10-archive-evidence.py --root <reports根> --out <近线目录> --dry-run
    python3 scripts/t10-archive-evidence.py --root <reports根> --out <近线目录> --pack
    python3 scripts/t10-archive-evidence.py --root <reports根> --out <近线目录> --scan-packed
    python3 scripts/t10-archive-evidence.py --root <reports根> --out <近线目录> --push
    python3 scripts/t10-archive-evidence.py --root <reports根> --out <近线目录> --write-git

`--root` / `--out` **必须显式给，⛔ 无默认值**（同 `redact-evidence.py`：
默认成仓内路径，在公开仓上就是「目录不存在 ⇒ 恒绿」）。

退出码：0 成功；2 缺必填参数或目录不存在；4 判据不成立；5 缺 huggingface_hub。
⛔ 不用 1 —— 那和 argparse 的参数错混了。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

HF_REPO = "njfuzrs/agent-traj-bench"
HF_PREFIX = "evidence/v0.2-mini"
STAGE_NAME = "_stage-prompts"
STAGE_MEMBERS = ("t8-fix/stage", "t8-rerun/tasks")

# §3.3 allowlist。脚本实现是整目录打包；这只作验收判据。
JOB_FILES = frozenset({"config.json", "lock.json", "result.json", "job.log"})
TRIAL_FILES = frozenset({
    "config.json", "lock.json", "result.json", "trial.log",
    "exception.txt", "analysis.md",
})
TRIAL_DIRS = frozenset({"agent", "verifier", "artifacts"})

# 实测脱敏作用面（Python 全树扫，⛔ 不是 ugrep 那次漏扫的 3/95）。
# 10 个文件里 1 个（t8-fix/docs/...md）不在任何 job 包内，公开仓已有脱敏版。
REDACTED_BY_JOB = {
    "t8-rerun/2026-09-13__19-35-38": (9, 813),
}

MANIFEST_COLS = (
    "job_path", "batch", "harbor_version", "created_at",
    "n_concurrent_trials", "n_planned", "n_scored", "n_total_trials",
    "agent", "model", "dataset_source", "task_digest_head",
    "src_bytes", "archive_bytes", "sha256", "allowlist_diff",
    "hf_path", "archived_at", "redacted", "leak_hits",
)

# 四类内网判据（corpus README §1），组装以免在源码里写出完整形态。
# 作用是清单上的**披露事实**，⛔ 不是「能不能公开」的判据（方案 §2.0）。
_NAME = "zhou" "rusheng"
_LEAK_PATTERNS = (
    _NAME,
    "ruishan" ".cc",
    ".ruijie" ".com",
    "anka" "-app",
    "tag" "-studio",
    "ontology" "-studio",
    "iam" "-",
    "ruijie" "/",
)


def _redact_mod():
    """按路径加载 `redact-evidence.py`（文件名有连字符，不能普通 import）。"""
    p = Path(__file__).resolve().parent / "redact-evidence.py"
    spec = importlib.util.spec_from_file_location("redact_evidence", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def die(msg: str, code: int) -> int:
    print(f"::error::{msg}", file=sys.stderr)
    return code


def job_dirs(root: Path) -> list[Path]:
    """归档单元：名字匹配 `20*__*` 的目录。⛔ 不是 `T0*`（会漏掉 M# / hash 哨兵）。"""
    found = [p for p in root.rglob("*")
             if p.is_dir() and p.name.startswith("20") and "__" in p.name]
    # 只要「自己是 job」的那一层：父目录不再是 job
    jobs = []
    for p in found:
        if any(q in p.parents for q in found):
            continue
        jobs.append(p)
    return sorted(jobs, key=lambda x: str(x.relative_to(root)))


def src_bytes(path: Path) -> int:
    """源体积：不跟随 symlink（lstat），与「打包存 symlink 本身」一致。"""
    total = 0
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        dp = Path(dirpath)
        for name in dirnames + filenames:
            q = dp / name
            try:
                st = q.lstat()
            except OSError:
                continue
            if not q.is_symlink() and q.is_file():
                total += st.st_size
            elif q.is_symlink():
                total += st.st_size  # symlink 节点本身的大小
    return total


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pack_tar_zst(cwd: Path, members: list[str], dest: Path,
                 extra_tar_args: list[str] | None = None) -> None:
    """`tar -cf - <members> | zstd -19 -T0`。⛔ 不加 -h（不解引用 symlink）。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tar_cmd = ["tar", "-C", str(cwd), "-cf", "-"]
    if extra_tar_args:
        tar_cmd.extend(extra_tar_args)
    tar_cmd.extend(members)
    tar = subprocess.Popen(tar_cmd, stdout=subprocess.PIPE)
    assert tar.stdout is not None
    zst = subprocess.run(
        ["zstd", "-19", "-T0", "-f", "-o", str(dest)],
        stdin=tar.stdout, check=False,
    )
    tar.stdout.close()
    rc = tar.wait()
    if rc != 0 or zst.returncode != 0:
        raise RuntimeError(f"打包失败 tar={rc} zstd={zst.returncode} members={members}")


def trial_dirs(job: Path) -> list[Path]:
    return [p for p in job.iterdir() if p.is_dir() and p.name != "_digests"]


def allowlist_diff(job: Path) -> str:
    extras: list[str] = []
    for p in job.iterdir():
        if p.is_dir():
            if p.name == "_digests":
                continue
            # trial 目录：再核它的顶层
            for q in p.iterdir():
                if q.is_dir() and q.name not in TRIAL_DIRS:
                    extras.append(f"{p.name}/{q.name}/")
                elif q.is_file() and q.name not in TRIAL_FILES:
                    extras.append(f"{p.name}/{q.name}")
        else:
            if p.name not in JOB_FILES:
                extras.append(p.name)
    return "none" if not extras else ",".join(sorted(extras))


def leak_hits(job: Path) -> int:
    """四类判据命中的**文件数**（打包前披露事实）。Python 走目录树，不经过 grep。"""
    pats = [re.compile(x.encode("utf-8")) for x in _LEAK_PATTERNS]
    n = 0
    for p in job.rglob("*"):
        if p.is_symlink() or not p.is_file():
            continue
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw[:8192]:
            continue
        if any(r.search(raw) for r in pats):
            n += 1
    return n


def read_lock_fields(job: Path) -> dict:
    """从 lock.json / result.json 派生清单字段。⛔ 不发明 schema。"""
    empty = dict(
        harbor_version="", created_at="", n_concurrent_trials="",
        n_planned="", n_scored="", n_total_trials="",
        agent="", model="", dataset_source="", task_digest_head="",
    )
    lock_p, res_p = job / "lock.json", job / "result.json"
    if not lock_p.is_file():
        return empty
    lock = json.loads(lock_p.read_text(encoding="utf-8"))
    res = json.loads(res_p.read_text(encoding="utf-8")) if res_p.is_file() else {}
    trials = lock.get("trials") or []
    agents = sorted({(t.get("agent") or {}).get("name") for t in trials} - {None})
    models = sorted({(t.get("agent") or {}).get("model_name") for t in trials} - {None})
    sources = [(t.get("task") or {}).get("source") for t in trials]
    src_set = sorted({s for s in sources if s is not None})
    digest = ((trials[0].get("task") or {}).get("digest") if trials else None) or ""
    # dataset_source：原样；全 None 就空着，⛔ 不写成 unknown，也不归一成 tasks
    if src_set:
        dataset_source = ",".join(src_set)
    elif trials and all(s is None for s in sources):
        dataset_source = ""
    else:
        dataset_source = ",".join(src_set)
    return dict(
        harbor_version=(lock.get("harbor") or {}).get("version") or "",
        created_at=lock.get("created_at") or "",
        n_concurrent_trials=lock.get("n_concurrent_trials"),
        n_planned=len(trials),
        n_scored=len(trial_dirs(job)),
        n_total_trials=res.get("n_total_trials"),
        agent=",".join(str(a) for a in agents),
        model=",".join(str(m) for m in models),  # 空 = 桩 agent，是正确值
        dataset_source=dataset_source,
        task_digest_head=digest[:16],
    )


def redacted_cell(job_path: str) -> str:
    if job_path in REDACTED_BY_JOB:
        n_f, n_s = REDACTED_BY_JOB[job_path]
        return f"yes({n_f} files/{n_s} sites)"
    return "no"


def dest_for(out: Path, job_path: str) -> Path:
    return out / f"{job_path}.tar.zst"


def hf_path_for(job_path: str) -> str:
    return f"{HF_PREFIX}/{job_path}.tar.zst"


def row_for(root: Path, job: Path, out: Path, packed: Path | None,
            archived_at: str, leaks: int) -> dict:
    rel = str(job.relative_to(root))
    batch = rel.split("/", 1)[0]
    fields = read_lock_fields(job)
    src = src_bytes(job)
    if packed and packed.is_file():
        ab = packed.stat().st_size
        sha = sha256_file(packed)
    else:
        ab, sha = "", ""
    return {
        "job_path": rel,
        "batch": batch,
        **fields,
        "src_bytes": src,
        "archive_bytes": ab,
        "sha256": sha,
        "allowlist_diff": allowlist_diff(job),
        "hf_path": hf_path_for(rel),
        "archived_at": archived_at,
        "redacted": redacted_cell(rel),
        "leak_hits": leaks,
    }


def stage_row(root: Path, packed: Path | None, archived_at: str) -> dict:
    src = 0
    for m in STAGE_MEMBERS:
        p = root / m
        if p.exists():
            src += src_bytes(p)
    if packed and packed.is_file():
        ab, sha = packed.stat().st_size, sha256_file(packed)
    else:
        ab, sha = "", ""
    return {
        "job_path": STAGE_NAME,
        "batch": STAGE_NAME,
        "harbor_version": "", "created_at": "",
        "n_concurrent_trials": "", "n_planned": "", "n_scored": "",
        "n_total_trials": "", "agent": "", "model": "",
        "dataset_source": "", "task_digest_head": "",
        "src_bytes": src, "archive_bytes": ab, "sha256": sha,
        "allowlist_diff": "none",
        "hf_path": hf_path_for(STAGE_NAME),
        "archived_at": archived_at,
        "redacted": "no",
        "leak_hits": 0,
    }


def write_manifest(rows: list[dict], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    lines = ["\t".join(MANIFEST_COLS)]
    jsonl = []
    sums = []
    for r in rows:
        lines.append("\t".join("" if r[k] is None else str(r[k]) for k in MANIFEST_COLS))
        jsonl.append({k: r[k] for k in MANIFEST_COLS})
        if r.get("sha256"):
            sums.append(f"{r['sha256']}  {r['hf_path']}")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (dest.parent / "evidence.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in jsonl),
        encoding="utf-8")
    (dest.parent / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")


def do_pack(root: Path, out: Path) -> list[dict]:
    jobs = job_dirs(root)
    if len(jobs) != 21:
        raise SystemExit(die(f"job 数是 {len(jobs)}，期望 21（find 20*__*）", 4))
    print(f"打包 {len(jobs)} 个 job + {STAGE_NAME} → {out}", file=sys.stderr)
    rows = []
    for j in jobs:
        rel = str(j.relative_to(root))
        dest = dest_for(out, rel)
        print(f"  pack {rel} ...", file=sys.stderr, flush=True)
        pack_tar_zst(root, [rel], dest)
        leaks = leak_hits(j)
        rows.append(row_for(root, j, out, dest, "", leaks))
        print(f"    {dest.stat().st_size} B  sha={rows[-1]['sha256'][:16]}  "
              f"leak_hits={leaks}  redacted={rows[-1]['redacted']}", file=sys.stderr)
    print(f"  pack {STAGE_NAME} ...", file=sys.stderr, flush=True)
    present = [m for m in STAGE_MEMBERS if (root / m).exists()]
    if len(present) != 2:
        raise SystemExit(die(f"stage 成员缺失：现有 {present}，期望 {list(STAGE_MEMBERS)}", 4))
    dest = dest_for(out, STAGE_NAME)
    pack_tar_zst(root, list(STAGE_MEMBERS), dest,
                 extra_tar_args=["--exclude=repo-snapshot.tar.gz"])
    rows.append(stage_row(root, dest, ""))
    print(f"    {dest.stat().st_size} B  sha={rows[-1]['sha256'][:16]}", file=sys.stderr)

    total = sum(int(r["archive_bytes"]) for r in rows)
    print(f"合计 archive_bytes = {total} ({total/1024/1024:.1f} MiB)；"
          f"期望 ≈ 342 MiB（偏差 > 5% 即 allowlist/cwd 错）", file=sys.stderr)
    expected = 342 * 1024 * 1024
    if abs(total - expected) / expected > 0.05:
        raise SystemExit(die(f"合计 {total} 与 342 MiB 偏差超过 5%", 4))
    if len(rows) != 22:
        raise SystemExit(die(f"行数 {len(rows)} ≠ 22", 4))
    return rows


def tar_first_member(zst: Path) -> str:
    p = subprocess.run(["zstd", "-d", "-c", str(zst)], check=True, stdout=subprocess.PIPE)
    t = subprocess.run(["tar", "-tf", "-"], input=p.stdout, check=True, stdout=subprocess.PIPE)
    first = t.stdout.decode("utf-8", "replace").splitlines()[0]
    return first


def scan_packed(out: Path, rows: list[dict]) -> int:
    """§5.3②：逐个解到临时目录跑门禁⑤。⛔ 不许扫 .tar.zst 本身。"""
    redact = _redact_mod()
    pat = redact._compiled(redact.PATTERN)
    bad = 0
    for r in rows:
        zst = dest_for(out, r["job_path"])
        first = tar_first_member(zst)
        expect_prefix = r["job_path"] if r["job_path"] != STAGE_NAME else STAGE_MEMBERS[0].split("/")[0]
        # job 包第一行必须是 `<job_path>/...`，⛔ 不是散落的 T0002__
        if r["job_path"] != STAGE_NAME and not first.startswith(r["job_path"] + "/"):
            print(f"::error::{r['job_path']}: tar 首条是 {first!r}，未保留 job 目录层",
                  file=sys.stderr)
            bad += 1
        with tempfile.TemporaryDirectory(prefix="atb-ev-") as td:
            tmp = Path(td)
            raw = subprocess.run(["zstd", "-d", "-c", str(zst)], check=True,
                                 stdout=subprocess.PIPE)
            subprocess.run(["tar", "-xf", "-", "-C", str(tmp)],
                           input=raw.stdout, check=True)
            hits = redact.scan(tmp, pat)
            n = sum(n for _, n in hits)
            if hits:
                print(f"::error::{r['job_path']}: 解压后门禁⑤ 命中 {len(hits)} 文件 / {n} 处",
                      file=sys.stderr)
                for hp, hn in hits[:5]:
                    print(f"    {hp.relative_to(tmp)}  sites={hn}", file=sys.stderr)
                bad += 1
            else:
                print(f"✅ 门禁⑤ 0  {r['job_path']}")
    return 4 if bad else 0


def _hub():
    try:
        from huggingface_hub import HfApi
    except ImportError:
        print("⛔ 缺 huggingface_hub —— --push 需要它", file=sys.stderr)
        raise SystemExit(5)
    return HfApi()


def do_push(out: Path, rows: list[dict], git_dir: Path) -> int:
    """逐份 `upload_file`。⛔ 不用 upload_folder（会把本地缺失的 snapshots/ 当要删）。"""
    api = _hub()
    existing = set(api.list_repo_files(HF_REPO, repo_type="dataset"))
    n_snap = sum(1 for f in existing if f.startswith("snapshots/"))
    if n_snap != 39:
        return die(f"上传前 snapshots/ 已是 {n_snap} 份（期望 39）⇒ 先停，别再动这个仓", 4)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for r in rows:
        r["archived_at"] = now
        zst = dest_for(out, r["job_path"])
        path_in = r["hf_path"]
        if path_in in existing:
            # 幂等：HF 上已有同路径且 sha256 相符 ⇒ 跳过
            from huggingface_hub import hf_hub_download
            local = Path(hf_hub_download(HF_REPO, path_in, repo_type="dataset"))
            got = sha256_file(local)
            if got == r["sha256"]:
                print(f"skip {path_in}（sha256 相符）")
                continue
            print(f"⚠️  {path_in} 已在 HF 但 sha256 不同，覆盖上传")
        api.upload_file(path_or_fileobj=str(zst), path_in_repo=path_in,
                        repo_id=HF_REPO, repo_type="dataset",
                        commit_message=f"chore: evidence {r['job_path']}")
        print(f"⬆️  {path_in}")

    write_manifest(rows, git_dir / "MANIFEST.tsv")
    # evidence.jsonl 与 README（现算）一起传
    ev = git_dir / "evidence.jsonl"
    api.upload_file(path_or_fileobj=str(ev), path_in_repo="evidence.jsonl",
                    repo_id=HF_REPO, repo_type="dataset",
                    commit_message="chore: evidence.jsonl 索引")
    print("⬆️  evidence.jsonl")

    # README：走 t9 的现算，把 evidence.jsonl 喂进去
    import t9_publish as t9  # 下面 main 里会把 t9-publish-hf 别名装上
    ids = t9.delivered_ids()
    readme = t9.build_readme(t9.build_tasks_jsonl(ids), t9.build_snapshots_jsonl(ids),
                             t9.version(), evidence_jsonl=ev.read_text(encoding="utf-8"))
    # 🔴 落临时目录，⛔ 不写进 git_dir：那会让工作树多一份不该入库的 HF README。
    tmp = Path(tempfile.mkdtemp(prefix="atb-ev-readme-")) / "README.md"
    tmp.write_text(readme, encoding="utf-8")
    api.upload_file(path_or_fileobj=str(tmp), path_in_repo="README.md",
                    repo_id=HF_REPO, repo_type="dataset",
                    commit_message="chore: README 现算补 evidence 章节")
    print("⬆️  README.md")

    files = set(api.list_repo_files(HF_REPO, repo_type="dataset"))
    n_ev = sum(1 for f in files if f.startswith("evidence/"))
    n_snap2 = sum(1 for f in files if f.startswith("snapshots/"))
    print(f"HF evidence/ = {n_ev}（期望 22），snapshots/ = {n_snap2}（期望 39）")
    if n_ev != 22:
        return die(f"evidence/ 计数 {n_ev} ≠ 22", 4)
    if n_snap2 != 39:
        return die(f"snapshots/ 被改成 {n_snap2} ≠ 39", 4)
    return 0


def load_t9():
    p = Path(__file__).resolve().parent / "t9-publish-hf.py"
    spec = importlib.util.spec_from_file_location("t9_publish", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    sys.modules["t9_publish"] = m
    return m


def main() -> int:
    ap = argparse.ArgumentParser(description="T10 — 证据层打包上传")
    ap.add_argument("--root", required=True, type=Path,
                    help="脱敏后的 reports 根（⛔ 无默认值）")
    ap.add_argument("--out", required=True, type=Path,
                    help="近线副本目录，写入 <job_path>.tar.zst（⛔ 无默认值）")
    ap.add_argument("--git-dir", type=Path, default=None,
                    help="清单落点（默认公开仓 reports/evidence/）")
    ap.add_argument("--dry-run", action="store_true",
                    help="打包 + 算 sha256，不上传、不解压扫")
    ap.add_argument("--pack", action="store_true", help="只打包")
    ap.add_argument("--scan-packed", action="store_true",
                    help="对已打的包解压扫门禁⑤（上传前必做）")
    ap.add_argument("--push", action="store_true",
                    help="upload_file 逐份上传（先 --scan-packed）")
    ap.add_argument("--write-git", action="store_true",
                    help="把 MANIFEST.tsv / SHA256SUMS / evidence.jsonl 写入 --git-dir")
    args = ap.parse_args()

    root = args.root.expanduser()
    out = args.out.expanduser()
    if not root.is_dir():
        return die(f"--root 不存在: {root}", 2)
    git_dir = (args.git_dir.expanduser() if args.git_dir
               else c.MVP_REPORTS / "evidence")

    if not any([args.dry_run, args.pack, args.scan_packed, args.push, args.write_git]):
        return die("请指定 --dry-run / --pack / --scan-packed / --push / --write-git", 2)

    load_t9()

    def _load_rows() -> list[dict]:
        man = git_dir / "MANIFEST.tsv"
        if not man.is_file():
            raise SystemExit(die("没有清单，先 --pack", 2))
        hdr, *body = man.read_text(encoding="utf-8").splitlines()
        cols = hdr.split("\t")
        loaded = [dict(zip(cols, line.split("\t"))) for line in body if line.strip()]
        if len(loaded) != 22:
            raise SystemExit(die(f"清单 {len(loaded)} 行 ≠ 22", 4))
        return loaded

    rows = None
    if args.dry_run or args.pack:
        rows = do_pack(root, out)
        write_manifest(rows, git_dir / "MANIFEST.tsv")
        print(f"清单写入 {git_dir / 'MANIFEST.tsv'}（{len(rows)} 行）")

    if args.scan_packed or args.push:
        if rows is None:
            rows = _load_rows()
        rc = scan_packed(out, rows)
        if rc:
            return rc
        print("✅ 22 个包解压后门禁⑤ 命中 0")

    if args.push:
        return do_push(out, rows, git_dir)

    if args.write_git and rows is None:
        return die("--write-git 需要先 --pack（同一次或清单已在 --git-dir）", 2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
