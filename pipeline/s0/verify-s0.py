#!/usr/bin/env python3
"""verify-s0.py — S0 归一化与仓库反解的验收门禁

对应 bench-curation-design.md §9 Phase 0 的两条验收标准：
  ① S0 归一化脚本 → sessions-v2.jsonl，6019 条，含逐 step 统计的 4 个新字段
  ② working_directory 反解 → 锚定率 ≥85%（目标 88.7%）；
     抽样 50 条人工确认反解仓库正确率 ≥95%

关于第 ② 条的「人工确认」：本脚本把它换成**可复现的客观裁判**，而不是目测。
做法是拿 §9.0 的 mirror 归档当事实基准 —— 把会话轨迹里操作过的绝对路径，
按反解出的仓库转成相对路径，去该仓库镜像的全历史路径集里查存在性；
再对全部 18 个候选仓库算同样的命中率。若反解出的仓库不是命中率最高的那个，
即判为反解错误。这比人工目测更严格（人只看 wd 像不像，看不出路径是否真在该仓库里），
且可重复执行。

⚠️ 门禁自证（§9.0 的教训：任何门禁都必须故意弄红一次才算交付）：
  python3 s0/verify-s0.py --self-test
会注入 4 类已知缺陷，每一类都必须让门禁变红。

用法：
  python3 s0/verify-s0.py              # 正常验收
  python3 s0/verify-s0.py --sample 100 # 指定裁判抽样量
  python3 s0/verify-s0.py --self-test   # 反向自证
"""

import argparse
import collections
import json
import os
import random
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import repo_map  # noqa: E402

META_DIR = os.environ.get("OUT_DIR", "data/bench-staging/meta")
INDEX = os.path.join(META_DIR, "sessions-v2.jsonl")
INSTR_DIR = os.path.join(META_DIR, "instructions")
SESSIONS_DIR = os.environ.get("SESSIONS_DIR", "data/pulled_sessions")
ARCHIVE_DIR = os.environ.get(
    "ARCHIVE_DIR", os.path.expanduser("~/Code/_archive/bench-mirrors")
)

# 可裁判样本下限。低于此数不给结论 —— n=29 时 95% 阈值只容 1 个错，
# 实测 --sample 30 得 93.1%（失败）而 --sample 150 得 97.7%（通过），
# 同一份数据两种结论，差别全是噪声。
# 注意这不是放水：样本不足时判**失败**（要求提高覆盖），不是放过。
MIN_JUDGED = 50

# 验收阈值（来自方案 §9 Phase 0 验收列）
#
# MIN_SESSIONS 不写死具体条数：数据每天新增（实测日增约 77 条），且上一轮手工
# 移入 _trash/ 的 1722 条已移回主目录。写死 6019 会在下次拉取后误报。
# 改为「索引条数必须等于磁盘上可解析的会话数」—— 这才是 S0 真正的验收语义：
# 不许悄悄漏掉会话。
MIN_SESSIONS = 6019  # 历史下限，仅作兜底
MIN_ANCHOR_RATE = 0.85
MIN_REPO_ACCURACY = 0.95
MAX_INDEX_MB = 10.0
REQUIRED_FIELDS = [
    "sid", "model", "vendor", "start_time", "end_time", "steps",
    "tool_call_count", "total_tokens", "cost_usd", "exit_status",
    "working_directory", "repo", "repo_resolution", "instruction_len",
    # §4.2 点名必须逐 step 才能得到的四个新字段
    "n_edit_ops", "n_error_ops", "n_test_cmds", "file_paths_hash",
    # v1.3 §8.5 强制要求的 provenance 标注
    "provenance", "excluded_hit",
    # v1.5 新增：采集通道（线上非单一来源）+ 上一轮手工清洗标记
    "agent_source", "legacy_trashed",
]

_ABS_PATH = re.compile(r"/Users/[^\s\"'`,)\]}]+")

failures: list[str] = []
warnings: list[str] = []


def fail(msg: str):
    failures.append(msg)
    print(f"  ✗ {msg}")


def warn(msg: str):
    warnings.append(msg)
    print(f"  ! {msg}")


def ok(msg: str):
    print(f"  ✓ {msg}")


def load_index(path: str = INDEX) -> list[dict]:
    if not os.path.exists(path):
        fail(f"索引不存在：{path}，先跑 s0-normalize.py")
        return []
    records = []
    with open(path) as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception as e:
                fail(f"索引第 {i} 行无法解析：{e}")
                return []
    return records


def check_index(records: list[dict]):
    """① 索引完整性"""
    print("── ① 索引完整性")
    n = len(records)
    if n < MIN_SESSIONS:
        fail(f"索引仅 {n} 条，低于历史下限 {MIN_SESSIONS}")
    else:
        ok(f"{n} 条记录（≥历史下限 {MIN_SESSIONS}）")

    # 与磁盘对账：S0 不许悄悄漏掉会话。这比「条数 ≥ 某个数」严格得多 ——
    # 数据每天在增，只验下限等于不验。
    if os.path.isdir(SESSIONS_DIR):
        on_disk = {
            d for d in repo_map.iter_session_dirs(SESSIONS_DIR)
            if os.path.exists(os.path.join(SESSIONS_DIR, d, "session.traj"))
        }
        indexed = {r["sid"] for r in records}
        missed = on_disk - indexed
        ghost = indexed - on_disk
        if missed:
            fail(f"磁盘上有 {len(missed)} 条会话未进索引（索引已过期，"
                 f"重跑 s0-normalize.py）：{sorted(missed)[:3]}")
        elif ghost:
            fail(f"索引里有 {len(ghost)} 条会话已不在磁盘（会话被删或移走，"
                 f"重跑 s0-normalize.py）：{sorted(ghost)[:3]}")
        else:
            ok(f"与磁盘对账一致（{len(on_disk)} 条 session.traj 全部进索引）")

        # _trash/ 不应再出现：移目录会让 pull.py 的 .pulled 去重失效并重复下载
        if os.path.isdir(os.path.join(SESSIONS_DIR, "_trash")):
            fail("_trash/ 又出现了 —— 淘汰须用索引字段标注表达，不靠移目录"
                 "（移走会让 pull.py 把这批会话全部重新下载）")
        else:
            ok("无 _trash/ 目录（淘汰在元数据层表达）")

    if not records:
        return

    missing = [f for f in REQUIRED_FIELDS if f not in records[0]]
    if missing:
        fail(f"缺字段：{missing}")
    else:
        ok(f"{len(REQUIRED_FIELDS)} 个必需字段齐全")

    sids = [r["sid"] for r in records]
    if len(set(sids)) != len(sids):
        dup = [s for s, c in collections.Counter(sids).items() if c > 1][:3]
        fail(f"sid 重复：{dup}")
    else:
        ok("sid 无重复")

    size_mb = os.path.getsize(INDEX) / 1024 / 1024
    if size_mb > MAX_INDEX_MB:
        fail(f"索引 {size_mb:.1f}MB 超过 {MAX_INDEX_MB}MB（§4.2 要求拆两层后 <10MB）")
    else:
        ok(f"索引体积 {size_mb:.1f}MB（<{MAX_INDEX_MB}MB）")

    # 四个新字段必须真的被填过，不能全是 0 —— 那等于没扫 trajectory
    for field in ("n_edit_ops", "n_error_ops", "n_test_cmds"):
        nonzero = sum(1 for r in records if r.get(field))
        if nonzero == 0:
            fail(f"{field} 全为 0 —— 逐 step 扫描未生效（v0.1 只读 metadata 的老问题）")
        else:
            ok(f"{field} 非零 {nonzero} 条")
    hashed = sum(1 for r in records if r.get("file_paths_hash"))
    if hashed == 0:
        fail("file_paths_hash 全为空 —— 未采集文件路径集")
    else:
        ok(f"file_paths_hash 非空 {hashed} 条")

    # 指令正文必须分离出去（v0.1 的 51MB 问题）
    long_instr = [r for r in records if len(str(r.get("instruction", ""))) > 200]
    if long_instr:
        fail(f"{len(long_instr)} 条把指令正文塞进了索引，应落 instructions/<sid>.txt")
    else:
        n_files = len(os.listdir(INSTR_DIR)) if os.path.isdir(INSTR_DIR) else 0
        with_instr = sum(1 for r in records if r.get("instruction_len", 0) > 0)
        if n_files < with_instr:
            fail(f"instructions/ 仅 {n_files} 个文件，索引却标了 {with_instr} 条有指令")
        else:
            ok(f"指令正文已分离：{n_files} 个文件")


def check_anchor_rate(records: list[dict]) -> list[dict]:
    """② 锚定率"""
    print("── ② 仓库锚定率")
    ge3 = [r for r in records if (r.get("steps") or 0) >= 3]
    anchored = [r for r in ge3 if r.get("repo")]
    if not ge3:
        fail("无 steps>=3 的会话")
        return []
    rate = len(anchored) / len(ge3)
    msg = f"steps>=3 共 {len(ge3)} 条，锚定 {len(anchored)} 条 = {rate:.1%}"
    if rate < MIN_ANCHOR_RATE:
        fail(f"{msg}，低于验收线 {MIN_ANCHOR_RATE:.0%}")
    else:
        ok(f"{msg}（≥{MIN_ANCHOR_RATE:.0%}）")

    dist = collections.Counter(r["repo_resolution"] for r in ge3)
    print(f"    置信度分布：{dict(dist.most_common())}")
    conflict = dist.get("conflict", 0)
    if conflict / len(ge3) > 0.10:
        warn(f"conflict {conflict} 条（{conflict/len(ge3):.1%}）超过 10%，下游需降权处理")
    return anchored


def build_mirror_pathsets() -> dict[str, set]:
    """从 §9.0 的 mirror 归档构建每仓库的**全历史**路径集，作为客观裁判基准

    必须用 `log --all --name-only` 而不是 `ls-tree HEAD`。后者只覆盖当前 HEAD tree，
    而会话发生在过去 —— sid-code 已从 `src/agent/*` 重构到 `packages/core/src/*`，
    早期会话操作的路径在 HEAD 里根本不存在。用 HEAD tree 做裁判时，这类会话的
    本仓库命中数掉到 0~1，被轨迹里少量跨仓库引用路径反超，产生假错判
    （实测正确率被压到 86.3%，其中至少 4 例是裁判错而非反解错）。

    成本：18 个仓库全历史约 5s，可接受。
    """
    if not os.path.isdir(ARCHIVE_DIR):
        return {}
    pathsets: dict[str, set] = {}
    for entry in sorted(os.listdir(ARCHIVE_DIR)):
        if not entry.endswith(".git"):
            continue
        mirror = os.path.join(ARCHIVE_DIR, entry)
        repo = entry[:-4].replace("_", "/", 1)
        try:
            out = subprocess.run(
                ["git", "-C", mirror, "log", "--all", "--name-only", "--format="],
                capture_output=True, text=True, timeout=600,
            ).stdout
            paths = {ln for ln in out.splitlines() if ln}
        except Exception:
            continue
        if paths:
            pathsets[repo] = paths
    return pathsets


def session_paths(sid: str) -> list[str]:
    """从原始 traj 里取轨迹操作过的绝对路径（裁判用，不依赖索引自述）"""
    traj_path = os.path.join(SESSIONS_DIR, sid, "session.traj")
    if not os.path.exists(traj_path):
        return []
    try:
        with open(traj_path) as f:
            data = json.load(f)
    except Exception:
        return []
    paths: set = set()
    for step in data.get("trajectory") or []:
        tool_input = step.get("tool_input")
        if not isinstance(tool_input, dict):
            continue
        for key in ("file_path", "path", "notebook_path", "filePath"):
            value = tool_input.get(key)
            if isinstance(value, str) and value.startswith("/"):
                paths.add(value)
    return sorted(paths)


def rel_in_repo(abs_path: str, repo: str) -> str | None:
    """绝对路径 → 仓库内相对路径（含 worktree 副本剥离）"""
    prefix = os.path.join(repo_map.CODE_ROOT, repo)
    idx = abs_path.find("/.claude/worktrees/")
    if idx > 0:
        head, tail = abs_path[:idx], abs_path[idx + len("/.claude/worktrees/"):]
        if head == prefix and "/" in tail:
            return tail.split("/", 1)[1]
        return None
    if abs_path.startswith(prefix + "/"):
        return abs_path[len(prefix) + 1:]
    return None


def check_repo_accuracy(anchored: list[dict], sample_n: int, seed: int = 20260905):
    """② 续：反解仓库正确率 —— 用 mirror 路径集做客观裁判"""
    print(f"── ③ 反解仓库正确率（mirror 客观裁判，抽样 {sample_n}）")
    pathsets = build_mirror_pathsets()
    if not pathsets:
        fail(f"归档不可用：{ARCHIVE_DIR}（先跑 archive-repos.sh），无法做客观裁判")
        return
    ok(f"载入 {len(pathsets)} 个仓库路径集，共 {sum(len(v) for v in pathsets.values())} 条路径")

    # 只抽「轨迹里有绝对路径可供裁判」的会话，否则裁判无据
    candidates = [r for r in anchored if r.get("n_file_paths", 0) >= 2]
    if len(candidates) < sample_n:
        sample_n = len(candidates)
    rng = random.Random(seed)
    sample = rng.sample(candidates, sample_n) if candidates else []
    if not sample:
        fail("无可裁判样本（锚定会话均无文件路径）")
        return

    correct = wrong = abstain = 0
    wrong_cases = []
    for rec in sample:
        claimed = rec["repo"]
        paths = session_paths(rec["sid"])
        if not paths:
            abstain += 1
            continue
        # 对每个候选仓库算「路径真实存在于该仓库」的命中数
        scores: dict[str, int] = {}
        for repo, pathset in pathsets.items():
            hits = 0
            for p in paths:
                rel = rel_in_repo(p, repo)
                if rel and rel in pathset:
                    hits += 1
            if hits:
                scores[repo] = hits
        if not scores:
            # 全部路径都不在任何镜像里（新建文件 / 已删除 / 非仓库路径），裁判弃权
            abstain += 1
            continue
        best = max(scores.values())
        winners = {r for r, s in scores.items() if s == best}
        if claimed in winners:
            correct += 1
        else:
            wrong += 1
            if len(wrong_cases) < 6:
                wrong_cases.append(
                    (rec["sid"][:8], claimed, rec["repo_resolution"],
                     sorted(scores.items(), key=lambda kv: -kv[1])[:3])
                )

    judged = correct + wrong
    if judged == 0:
        fail(f"裁判全部弃权（{abstain} 条），正确率无法判定 —— 视为不通过")
        return
    if judged < MIN_JUDGED:
        fail(f"可裁判样本仅 {judged} 条（弃权 {abstain}），少于下限 {MIN_JUDGED} —— "
             f"此规模下阈值 {MIN_REPO_ACCURACY:.0%} 只容 {judged - int(judged * MIN_REPO_ACCURACY)} "
             f"个错，结论是噪声。请加大 --sample")
        return
    acc = correct / judged
    msg = f"可裁判 {judged} 条（弃权 {abstain}）：正确 {correct}，错误 {wrong} = {acc:.1%}"
    if acc < MIN_REPO_ACCURACY:
        fail(f"{msg}，低于验收线 {MIN_REPO_ACCURACY:.0%}")
    else:
        ok(f"{msg}（≥{MIN_REPO_ACCURACY:.0%}）")
    for sid, claimed, res, top in wrong_cases:
        print(f"    错判 {sid} repo={claimed} ({res}) 裁判排名={top}")


def check_excluded_list(records: list[dict]):
    """④ 自指污染排除清单"""
    print("── ④ 自指污染排除清单")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "excluded-paths.txt")
    if not os.path.exists(path):
        fail(f"清单不存在：{path}")
        return
    prefixes = repo_map.load_excluded_prefixes(path)
    expected = {"evals", "packages/eval-framework", "scripts/eval", "tests/eval"}
    got = set(prefixes)
    if not expected.issubset(got):
        fail(f"清单缺少方案 §2.5 点名的前缀：{sorted(expected - got)}")
    else:
        ok(f"四个强制前缀齐全：{sorted(expected)}")

    # 前缀匹配必须按段比对，不能裸字符串前缀
    if repo_map.is_excluded_path("evals-foo/bar.ts", prefixes):
        fail("前缀匹配未按 / 分段，evals-foo/ 被 evals/ 误命中")
    elif not repo_map.is_excluded_path("evals/grade.ts", prefixes):
        fail("前缀匹配失效，evals/grade.ts 未被命中")
    else:
        ok("按段前缀匹配正确（evals/ 命中、evals-foo/ 不命中）")

    hit = sum(1 for r in records if r.get("excluded_hit"))
    if hit == 0:
        fail("全库 excluded_hit 均为 false —— 与 §2.5 实测 evals 相关 commit 占 15.6% 矛盾，判定逻辑可疑")
    else:
        ok(f"索引已标注 {hit} 条命中会话（S4 分诊据此淘汰）")


def check_agent_source(records: list[dict]):
    """⑥ 采集通道与历史清洗标记"""
    print("── ⑥ 采集通道与历史清洗标记")
    dist = collections.Counter(r.get("agent_source") for r in records)
    legal = {"claude_code", "codex", "sid_code", "short_id"}
    illegal = set(dist) - legal
    if illegal:
        fail(f"agent_source 出现非法值：{illegal}")
    elif None in dist or "" in dist:
        fail("agent_source 存在空值 —— 每条会话都必须归到某个通道")
    else:
        ok(f"通道分布：{dict(dist.most_common())}")

    # 线上确实是多来源。若只剩一个通道，说明判定逻辑失效了。
    if len(dist) < 2:
        fail(f"只识别出 {len(dist)} 个通道 —— 实测线上有 Claude Code / Codex / sid-code "
             f"三类 id 形态，判定逻辑可疑")

    trashed = sum(1 for r in records if r.get("legacy_trashed"))
    listed = repo_map.load_legacy_trashed()

    # 这道门禁要抓的是「1722 条又被移出主目录」（§9.2 问题 1 会复发）。
    # 但清单条数不能直接当期望值：其中有会话云端本就没有 session.traj
    # （实测 1 条，`.pulled` 记 `"session.traj": "missing"`），它永远进不了
    # 索引 —— 拿它当差额会让门禁恒红，等于废掉。
    #
    # 所以拆成两条独立判定：
    #   ① 目录还在不在（真正的故障，必须红）
    #   ② 在索引里的条数 == 有 session.traj 的条数（标注是否漏打）
    # 无 traj 的那几条单独报出来，是数据事实而非故障。
    if os.path.isdir(SESSIONS_DIR):
        gone, no_traj = [], []
        for sid in listed:
            d = os.path.join(SESSIONS_DIR, sid)
            if not os.path.isdir(d):
                gone.append(sid)
            elif not os.path.exists(os.path.join(d, "session.traj")):
                no_traj.append(sid)
        if gone:
            fail(f"清单里有 {len(gone)} 条会话的目录已不在 {SESSIONS_DIR} —— "
                 f"又被移出主目录了，会让 pull.py 重复下载"
                 f"（§9.2 问题 1）：{sorted(gone)[:3]}")
        else:
            ok(f"清单 {len(listed)} 条的目录全部在主目录内（未再被移走）")
        expected = len(listed) - len(no_traj)
        if no_traj:
            warn(f"清单里 {len(no_traj)} 条云端无 session.traj，永远进不了索引"
                 f"（数据事实，非故障）：{sorted(no_traj)}")
    else:
        expected = len(listed)

    if expected and trashed != expected:
        fail(f"legacy_trashed 标注 {trashed} 条，与清单可入索引的 {expected} 条不符 —— "
             f"标注逻辑漏打或索引过期")
    else:
        ok(f"legacy_trashed 标注 {trashed} 条，与清单可入索引部分一致")


def check_provenance(records: list[dict]):
    """⑦ provenance 标注（v1.3 §8.5 强制）"""
    print("── ⑦ provenance 标注")
    dist = collections.Counter(r.get("provenance") for r in records)
    if set(dist) - {"pre_upgrade", "post_upgrade"}:
        fail(f"provenance 出现非法值：{set(dist) - {'pre_upgrade', 'post_upgrade'}}")
    else:
        ok(f"取值合法：{dict(dist)}")
    if dist.get("post_upgrade", 0) == 0:
        warn("无 post_upgrade 会话 —— 本批数据全部采集于 claude-trace v0.2.0 之前属预期")


def self_test() -> int:
    """反向自证：注入已知缺陷，每一类都必须让门禁变红

    §9.0 的教训：三个 bug 叠起来能做到「18 个仓库全绿，其中 4 个根本没验」，
    外表与真绿完全一致。所以门禁必须故意弄红一次才算交付。
    """
    import shutil
    import tempfile

    print("=== 反向自证：健康基线必须绿，每类注入缺陷必须变红（且原因对得上）===\n")
    records = load_index()
    if not records:
        print("需先跑 s0-normalize.py 产出正常索引")
        return 1

    # 前置检查：索引必须与磁盘同步，否则每个 case 都会因「索引过期」这个
    # 无关原因变红，自证失去意义。这是时序问题，不是门禁问题。
    if os.path.isdir(SESSIONS_DIR):
        on_disk = {
            d for d in repo_map.iter_session_dirs(SESSIONS_DIR)
            if os.path.exists(os.path.join(SESSIONS_DIR, d, "session.traj"))
        }
        drift = len(on_disk ^ {r["sid"] for r in records})
        if drift:
            print(f"✗ 索引与磁盘差 {drift} 条，无法自证。")
            print("  自证要先有一个「健康基线」，而过期索引本身就是不健康的 ——")
            print("  此时每个注入 case 都会因『索引过期』变红，验不出门禁的鉴别力。")
            print("  请先跑：python3 s0/s0-normalize.py")
            return 1

    # 每个 case 除了「必须变红」，还要校验**变红的原因对不上号就算失败**。
    #
    # 这一条是必须的：加入磁盘对账后，任何被裁剪过的索引都会因为「索引与磁盘
    # 不一致」而变红 —— 若只看退出码，四个 case 会全部因为同一个无关原因变红，
    # 自证看着全绿却什么都没验到。这正是 §9.0 那条教训的翻版。
    cases = []

    # ⓿ 健康基线必须绿。没有这一条，自证无法区分「门禁有鉴别力」与「门禁恒红」。
    cases.append(("健康基线（必须保持绿）", records, None, None))
    # ① 记录数不足
    cases.append(("索引条数腰斩", records[: MIN_SESSIONS // 2], None, "未进索引"))
    # ② 四个新字段全为 0（等于没扫 trajectory —— v0.1 的原始缺陷）
    stripped = [dict(r, n_edit_ops=0, n_error_ops=0, n_test_cmds=0, file_paths_hash="")
                for r in records]
    cases.append(("逐 step 字段全清零", stripped, None, "逐 step 扫描未生效"))
    # ③ 锚定率归零
    unanchored = [dict(r, repo=None, repo_resolution="unresolved") for r in records]
    cases.append(("锚定率归零", unanchored, None,
                  f"低于验收线 {MIN_ANCHOR_RATE:.0%}"))
    # ④ 排除清单被清空
    cases.append(("排除清单清空", records, "", "缺少方案 §2.5 点名的前缀"))
    # ⑤ 采集通道判定失效（全部塞成同一个通道）
    single = [dict(r, agent_source="claude_code") for r in records]
    cases.append(("采集通道判定失效", single, None, "判定逻辑可疑"))
    # ⑥ 历史清洗标记丢失（等于 1722 条会话又被移出主目录）
    untrashed = [dict(r, legacy_trashed=False) for r in records]
    cases.append(("历史清洗标记丢失", untrashed, None, "与清单"))

    passed = 0
    for name, recs, excl_content, expect_reason in cases:
        tmpdir = tempfile.mkdtemp(prefix="s0-selftest-")
        try:
            tmp_index = os.path.join(tmpdir, "sessions-v2.jsonl")
            with open(tmp_index, "w") as f:
                for r in recs:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            excl_path = os.path.join(tmpdir, "excluded-paths.txt")
            if excl_content is None:
                shutil.copy(
                    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "excluded-paths.txt"),
                    excl_path,
                )
            else:
                with open(excl_path, "w") as f:
                    f.write(excl_content)

            proc = subprocess.run(
                [sys.executable, os.path.abspath(__file__), "--sample", "150",
                 "--index", tmp_index, "--excluded", excl_path],
                capture_output=True, text=True, check=False,
            )
            red = proc.returncode != 0

            if expect_reason is None:
                # 健康基线：必须绿
                if red:
                    print(f"  [✗ 误报] {name}（退出码 {proc.returncode}）")
                    print("      —— 门禁对健康数据也报红，失去鉴别力。输出：")
                    print("      " + "\n      ".join(
                        ln for ln in proc.stdout.splitlines() if "✗" in ln)[:600])
                else:
                    print(f"  [✓ 保持绿] {name}")
                    passed += 1
                continue

            # 缺陷 case：必须变红，且变红原因要对上号
            reason_hit = expect_reason in proc.stdout
            if red and reason_hit:
                print(f"  [✓ 变红] {name} —— 命中预期原因「{expect_reason}」")
                passed += 1
            elif red:
                print(f"  [✗ 红错原因] {name}（退出码 {proc.returncode}）")
                print(f"      期望命中「{expect_reason}」，但实际失败项是：")
                for ln in proc.stdout.splitlines():
                    if ln.strip().startswith("✗"):
                        print(f"      {ln.strip()}")
            else:
                print(f"  [✗ 仍绿] {name}（退出码 {proc.returncode}）")
                print("      —— 这就是假门禁。")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    print(f"\n自证结果：{passed}/{len(cases)} 类缺陷被拦下")
    return 0 if passed == len(cases) else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=100, help="仓库正确率的裁判抽样量")
    ap.add_argument("--self-test", action="store_true", help="反向自证（故意弄红）")
    ap.add_argument("--index", default=None, help="指定索引路径（自证用）")
    ap.add_argument("--excluded", default=None, help="指定排除清单路径（自证用）")
    args = ap.parse_args()

    if args.self_test:
        sys.exit(self_test())

    global INDEX
    if args.index:
        INDEX = args.index

    print(f"验收对象：{INDEX}\n")
    records = load_index(INDEX)
    if not records:
        print("\n验收结果：不通过")
        sys.exit(1)

    check_index(records)
    anchored = check_anchor_rate(records)
    check_repo_accuracy(anchored, args.sample)

    if args.excluded:
        print("── ④ 自指污染排除清单")
        try:
            prefixes = repo_map.load_excluded_prefixes(args.excluded)
        except Exception as e:
            fail(f"清单不可读：{e}")
            prefixes = []
        expected = {"evals", "packages/eval-framework", "scripts/eval", "tests/eval"}
        if not expected.issubset(set(prefixes)):
            fail(f"清单缺少方案 §2.5 点名的前缀：{sorted(expected - set(prefixes))}")
        else:
            ok("四个强制前缀齐全")
    else:
        check_excluded_list(records)
    check_agent_source(records)
    check_provenance(records)

    print()
    if failures:
        print(f"验收结果：不通过（{len(failures)} 项失败，{len(warnings)} 项警告）")
        for f in failures:
            print(f"  ✗ {f}")
        sys.exit(1)
    print(f"验收结果：通过（{len(warnings)} 项警告）")


if __name__ == "__main__":
    main()
