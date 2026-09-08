#!/usr/bin/env python3
"""T3 — harbor task 目录生成（七个文件 × 65 条）

出处：`docs-research/trajectory-platform/bench-mvp-plan.md` v1.2 §4 T3（1.5 天）

输入：`meta/resolved.jsonl`（T2）+ `meta/snapshots.jsonl`（T4）+ `meta/p2p.jsonl`
      （`t3-sample-p2p.py`，在 T4 剔除后的快照上采的，见衔接①）
输出：`bench/v0.2-mini/tasks/T####/` 的七个文件（`environment/` 由 T4 产出，本脚本不动）

本脚本是**纯文本处理、秒级完成**，可反复重跑；贵的那一半（起 50 个容器采 P2P）
在 `t3-sample-p2p.py` 里，产物缓存成 `p2p.jsonl`。分开的理由见那个文件的 docstring。

## 🔴 实测纠正方案的一处硬错误：reward 文件名是 `reward.json`，不是 `rewards.json`

方案 §3.8-D / §4 T3 有十来处写 `rewards.json`（复数），**harbor 不读这个名字**。
核 harbor 源码 `models/trial/paths.py:45-46`：

    reward_text_path = verifier_dir / "reward.txt"
    reward_json_path = verifier_dir / "reward.json"      ← 单数

`verifier/verifier.py:226` 的取值顺序是 **`reward.json` 存在就用它，否则退到
`reward.txt`**，两个都没有才抛 `RewardFileNotFoundError`。

照方案写 `rewards.json` 的后果**不是报错，而是静默降级**：harbor 找不到它 →
退回读 `reward.txt`（单值）→ `f2p` / `p2p` 两个键**永远不进 result.json**。
形态是「门禁看起来在跑、但 F2P 与 P2P 的分永远读不到」，正是 §3.8-D 要避免的
「退化成单值判定」。所以本脚本写 **`reward.json`**，并**同时**写 `reward.txt`
（两个源必须一致，T5 会核对，见 §3.8-D 的双源交叉验证）。

## 🔴 第二处实测纠正：junit XML 会整份漏掉「加载失败」的文件

`t3-sample-p2p.py` 的 docstring 有完整实测形态。对判分侧的影响：

    bun test --reporter=junit good.test.ts loadfail.test.ts
    → XML root: tests="6" failures="0"     ← 只读 failures 就是满分
    → 日志:     6 pass / 1 fail / 1 error  ← 有个文件根本没加载起来

所以 `score.py` **不能只看失败计数**，必须做**文件覆盖核对**：
名单里的每个文件都得在 XML 里出现（证明它真的跑了），少一个即该侧判 0。
只单跑一个加载失败的文件时更极端 —— **XML 文件根本不写**，
此时「解析不到」必须判 0 而不是抛异常（规则1：每条路径都要写 reward）。

## ⚠️ 第三处纠正：测试保护不能按 `git checkout -- tests/` 做

方案 §4 T3 的规则4 写的是 `git checkout -- tests/` + `git clean -fd tests/`。
实测 `resolved.jsonl`：**65 条 task 里有 4 条的测试文件不在 `tests/` 下**
（`src/` 3 个 + `packages/` 2 个，共 5 个文件）—— 只还原 `tests/` 就漏掉它们，
agent 改了这些测试不会被还原。

（`resolved.jsonl` 全量 70 条里还有 6 个 `anka-app/` 下的测试文件，但那 5 条
`ruijie/iam-studio-fe` 无可构建 env、不在 65 条之内，见 `t4-env.md` §5。）

而把它改成 `git clean -fd src/` 更糟：**那会删掉 agent 新建的源码文件**，
即删掉它的解答本体，形态是「agent 明明写了代码却判 0」。

所以本脚本改成**按路径逐个还原**（名单在生成时字面写入）：
base 上存在的 → `git checkout -- <path>`；base 上不存在的（87/161 是新增测试）
→ `rm -f <path>`。F2P 与 P2P 的路径都要还原 —— P2P 全是 base 上就绿的测试，
agent 改动它们同样是作弊。**只碰这些路径，不碰目录**，agent 的代码改动完整保留。

## 七个文件（§4 T3 的表）

    instruction.md          agent 读 —— 直接取 instruction_clean，不加工
    task.toml               harbor 读 —— 三个 timeout 都显式写（对应 R2 双层超时互掩）
    solution/solve.sh       OracleAgent 挂 /solution
    solution/gold_patch.diff
    tests/test.sh           Evaluator 挂 /tests
    tests/test_patch.diff
    tests/score.py
    meta.json               我们自己的溯源，harbor 不读

`environment/{Dockerfile,repo-snapshot.tar.gz}` 是 T4 的产物，本脚本**只读不写**。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common as c

SNAPSHOTS = c.MVP_META / "snapshots.jsonl"
P2P_IN = c.MVP_META / "p2p.jsonl"
STATS_OUT = c.MVP_META / "tasks.stats.json"

#: 三个 timeout 都显式写（方案 §4 T3：对应 R2「双层超时互掩」——
#: 只设一层时，外层先杀会把内层的真实超时掩盖成 error）。
#:
#: `build_timeout_sec` 取 1800 而非方案示例的 600：实测冷构建一个 base
#: **160 秒**（`docker build` 计时，含 apt + `bun install --frozen-lockfile`），
#: 但那是 `oven/bun:1.3.14` 基础层已在本地的情况。换机器首次构建要拉 335MB 基础镜像，
#: 600 秒容易压线 —— 而构建超时的形态是 trial error，会被误读成 task 坏了。
VERIFIER_TIMEOUT = 900.0
BUILD_TIMEOUT = 1800.0

#: agent 超时按难度分档给。方案示例统一 900，但 L 档（38/65 条）的原始会话
#: `edit_ops` 远高于 S 档，给同样的墙钟时间会让 L 档系统性超时 ——
#: 超时在 harbor 里是 error 而不是低分，会污染基线的「做不出来」与「没做完」两类。
AGENT_TIMEOUT_BY_BAND = {"S": 900.0, "M": 1800.0, "L": 2700.0}

#: 一个 task 目录**必须齐**的文件。方案 §4 T3 的验收项写的是「脚本自查每个 task 目录，
#: 缺一个即报错」，且反向自证②要求「删掉某条的 tests/score.py → 自查必须报错」。
#:
#: 为什么要显式列成常量而不是「生成完就完事」：生成器写文件的路径分支不止一条
#: （patch 落盘、名单落盘、模板渲染各一处），少写一个文件**不会报错** ——
#: 形态是 harbor 的 `Task.is_valid_dir()` 照样报 VALID（它只查它关心的那几个），
#: 而缺的那个在跑到容器里时才炸，此时已经过了门禁。所以在生成的**出口**核一次。
#:
#: `environment/` 两个文件是 T4 的产物，本脚本不写但**必须核** ——
#: 缺快照的 task 进了产物，形态是 T5 建镜像时才失败（见 t4-env.md §9.1 的重建提示）。
REQUIRED_FILES = (
    "instruction.md",
    "task.toml",
    "meta.json",
    "solution/solve.sh",
    "solution/gold_patch.diff",
    "tests/test.sh",
    "tests/test_patch.diff",
    "tests/score.py",
    "tests/f2p.json",
    "tests/p2p.json",
    "environment/Dockerfile",
    "environment/repo-snapshot.tar.gz",
)


def missing_files(task_dir: Path) -> list[str]:
    """返回缺失或**空**的必需文件。空文件与缺文件同罪 —— 零字节的 `gold_patch.diff`
    在容器里是「apply 成功但什么都没改」，即 oracle 静默拿 0 分。"""
    out = []
    for rel in REQUIRED_FILES:
        f = task_dir / rel
        if not f.exists() or f.stat().st_size == 0:
            out.append(rel)
    return out


def sh_single_quote(s: str) -> str:
    """POSIX 单引号转义。测试路径来自仓库、不是用户输入，但生成器**不该假定**输入干净。"""
    return "'" + s.replace("'", "'\\''") + "'"


#: bun 只认文件名里带这四种标记的文件为测试（实测报错原文：
#: `Tests need ".test", "_test_", ".spec" or "_spec_" in the filename`）。
BUN_TEST_MARKERS = (".test.", ".spec.", "_test_", "_spec_")


def is_bun_test_file(path: str) -> bool:
    """这个文件 bun 会不会当测试收集。

    ## 🔴 为什么必须过这道滤网（实测抓到的第四处坑）

    T2 的 `is_test` 标记是**按用途**判的（`tests/` 目录下、随 test_patch 一起进来），
    但 bun 是**按文件名**收集的。两者不等价，实测撞到一个真实反例：

        tests/preload-isolate-sid-home.ts     ← is_test=true，但**没有 `.test.`**

    它是个 preload 辅助文件（给同进程后续测试设 HOME 隔离兜底），不是测试。
    把它塞进 `bun test` 的参数里，实测行为是：

        单独跑它            → 报 `Tests need ".test" ... in the filename`，**不写 XML**
        与正常测试一起跑    → **exit 0**、日志只报正常那个文件、它从 XML 里**整个消失**

    第二种是致命的：bun **不报错也不非零退出**，而 `score.py` 的文件覆盖核对会发现
    它不在 XML 里 → 判 f2p=0 → **这条 task 连 oracle 都做不出来**，
    形态是「参考解也拿 0 分」，会被误判成 patch 反解错了。

    与 §2.2 那条正好互补：那条是「文件加载失败被漏掉」，这条是「文件根本没被收集」，
    两条都靠**文件覆盖核对**兜住 —— 这是它第二次证明自己不是多余的。

    ⚠️ **但这类文件仍要参与测试保护**：它随 test_patch 落地，agent 同样能改它，
    所以 `restore` / `remove` 名单**不过这道滤网**，只有 `bun test` 的参数过。
    """
    name = path.rsplit("/", 1)[-1]
    return any(m in name for m in BUN_TEST_MARKERS)


def instruction_md(snap: dict, instruction: str) -> str:
    """题面 = `instruction_clean` 原文（§4 T3 ①「不加工」）。

    只在原文后面补一段**环境事实**（工作目录、测试命令、离线）。这不是加工题意 ——
    agent 在容器里需要知道用什么命令跑测试，而 `test_cmd` 因 base 时点而异
    （3 条 monorepo base 带 `--test-name-pattern`，§3.5）。不写它等于让 agent 猜。

    ⚠️ `instruction_clean` 只在 **`candidates.jsonl`**（T1 产物）里，
    `resolved.jsonl` 没有这个字段 —— T2 反解时没带上。第一版从 `row` 里取，
    结果 65 条题面**全是空的**，而 `Task.is_valid_dir()` 仍然报 VALID
    （它只查文件存在，不查内容）。形态会是「agent 拿到一道没有题目的题，
    全批 reward=0，看着像 task 太难」。所以题面由调用方从 candidates 取好传进来，
    并在 `build_one()` 里硬校验非空。
    """
    body = instruction.strip()
    return (
        f"{body}\n"
        f"\n"
        f"---\n"
        f"\n"
        f"## 环境事实\n"
        f"\n"
        f"- 仓库已在 `/repo`，你的改动直接留在工作区即可（不需要 commit、不需要生成 patch）\n"
        f"- 跑测试：`{snap['test_cmd']}`\n"
        f"- 容器**离线运行**（`--network none`），依赖已装好，不要尝试联网安装\n"
    )


def task_toml(task_id: str, row: dict) -> str:
    """harbor 读的配置。`[metadata]` 里的自定义键 harbor 不校验，放溯源摘要。"""
    band = row.get("band") or "M"
    agent_timeout = AGENT_TIMEOUT_BY_BAND.get(band, 1800.0)
    return (
        'schema_version = "1.4"\n'
        "\n"
        "[metadata]\n"
        f'task_id = "{task_id}"\n'
        f'source_unit_id = "{row["unit_id"]}"\n'
        f'repo = "{row["repo"]}"\n'
        f'base_commit = "{row["base_commit"]}"\n'
        f'difficulty_band = "{band}"\n'
        f'category = "{row.get("category") or ""}"\n'
        "\n"
        "[verifier]\n"
        f"timeout_sec = {VERIFIER_TIMEOUT}\n"
        "\n"
        "[agent]\n"
        f"timeout_sec = {agent_timeout}\n"
        "\n"
        "[environment]\n"
        f"build_timeout_sec = {BUILD_TIMEOUT}\n"
    )


def solve_sh() -> str:
    """参考解入口。OracleAgent 把 `solution/` 挂到 `/solution`。

    ⚠️ 用 `git apply --3way`：`code_patch` 是从轨迹反解的，上下文可能与快照有微小偏移
    （T2 验过 `--check` 全过，但 `--3way` 在等价情况下更宽容且不会静默错位）。

    ## 🔴 实测：不刷 index 的话 `--3way` 必然失败（`does not match index`）

    这一条 T2/T4 都不可能发现，因为它只在**容器里**出现：

        git apply --3way /solution/gold_patch.diff
        → error: src/app.ts: does not match index      ← 100% 复现
        git apply /solution/gold_patch.diff            ← 同一个 patch，纯 apply 成功

    根因是 T4 的镜像用 `tar -xzf` 解包再 `git add -A` + `commit`，解出来的文件
    **mtime/ctime 与 index 记录的不一致**。实测 `git diff-files --name-only | wc -l`
    = **1215**（即快照里每一个文件都是 stat-dirty），`git update-index --refresh`
    之后归 **0**。`git apply --3way` 会查 index（要做三方合并），一旦 stat-dirty
    就拒绝动手；纯 `git apply` 只碰工作区，所以 T2/T4 的 `apply --check` 全过。

    危险的地方在于它的**形态**：oracle 跑完 `solve.sh` 失败 → 代码没改 →
    但 `test.sh` 照样跑完并给分，看着像「参考解不对」而不是「patch 根本没打上」。
    所以修法是在 apply 前 `git update-index -q --refresh`（`|| true` 是因为它
    在有真实改动时返回非零，而我们只要它刷新 stat 缓存）。
    """
    return (
        "#!/bin/bash\n"
        "# T3 生成，勿手改。参考解入口（OracleAgent 跑它）\n"
        "set -euo pipefail\n"
        "cd /repo\n"
        "# ⚠️ 必须先刷 index，否则 --3way 报 `does not match index`（见 solve_sh docstring）\n"
        "git update-index -q --refresh || true\n"
        "git apply --3way /solution/gold_patch.diff\n"
    )


def test_sh(task_id: str, f2p: list[str], p2p: list[str], restore: list[str], remove: list[str], test_cmd: str) -> str:
    """判分入口。**整条链路最容易「绿着坏掉」的文件**，七条规则逐条落地。

    规则1 每条路径都写 reward   规则2 先无条件覆盖为 0    规则3 test_patch 在此应用
    规则4 防 agent 改测试       规则5 名单字面写入        规则6 结构化判分不 grep
    规则7 reward 写三个键

    ⚠️ `exit 0` 不是笔误（§4 T3）：test_patch 打不上时要的结果是「这条 task 得 0 分」，
    而不是「trial 崩了」—— 后者是 harbor 的 error 状态，会被误读成基础设施问题。
    """
    f2p_arg = " ".join(sh_single_quote(p) for p in f2p)
    p2p_arg = " ".join(sh_single_quote(p) for p in p2p)
    restore_lines = "\n".join(f"git checkout -- {sh_single_quote(p)} 2>/dev/null || true" for p in restore)
    remove_lines = "\n".join(f"rm -f {sh_single_quote(p)}" for p in remove)
    return f"""#!/bin/bash
# T3 生成，勿手改。task={task_id}
# 规则1：每条代码路径都必须写 reward —— 绝不能有「文件已存在就不写」的分支，
#        否则 agent 可以自己往 reward 文件里写个 1
# 规则2：先无条件覆盖为 0，跑完再按结果改写
mkdir -p /logs/verifier
echo 0 > /logs/verifier/reward.txt
printf '{{"reward":0.0,"f2p":0.0,"p2p":0.0,"error":"test_sh_did_not_finish"}}\\n' \\
  > /logs/verifier/reward.json

cd /repo

# ── 规则4：测试保护 ────────────────────────────────────────────────
# ⚠️ 按**路径逐个**还原，不按目录 —— 65 条 task 里有 4 条的测试文件不在 tests/ 下
# （src/ 3 个、packages/ 2 个），只还原 tests/ 会漏掉它们；
# 而 `git clean -fd src/` 会删掉 agent 新建的源码，即删掉它的解答本体。
# 名单由 T3 生成时字面写入。
{restore_lines or "# （本条 task 无 base 上已存在的测试文件需还原）"}
{remove_lines or "# （本条 task 无 agent 可能新建的测试文件需删除）"}

# ── 规则3：test_patch 在 verifier 阶段应用，不在 agent 阶段 ────────
# ⚠️ 先刷 index：tar 解包出来的文件全是 stat-dirty（实测 1215/1215），
#    而 --3way 要查 index，不刷必报 `does not match index`（见 solve_sh docstring）
git update-index -q --refresh || true
if ! git apply --3way /tests/test_patch.diff 2>>/logs/verifier/apply.log; then
  echo "TEST_PATCH_APPLY_FAILED" >> /logs/verifier/apply.log
  printf '{{"reward":0.0,"f2p":0.0,"p2p":0.0,"error":"test_patch_apply_failed"}}\\n' \\
    > /logs/verifier/reward.json
  echo 0 > /logs/verifier/reward.txt
  exit 0    # 注意：exit 0 —— 要 reward=0，不要 trial error（§4 T3）
fi

# ── 规则5+6：名单字面写入，走 --reporter=junit 结构化输出 ──────────
# ⚠️ 不许 grep 日志文本判分（R1 经典成因：格式一变就恒真/恒假且不报错）
# ⚠️ test_cmd 取自 base 时点的 package.json（§3.5），不同 base 可能不同
{test_cmd} --reporter=junit --reporter-outfile=/logs/verifier/f2p.xml {f2p_arg} \\
  > /logs/verifier/f2p.log 2>&1 || true
{test_cmd} --reporter=junit --reporter-outfile=/logs/verifier/p2p.xml {p2p_arg} \\
  > /logs/verifier/p2p.log 2>&1 || true

# 规则7：score.py 写 reward / f2p / p2p 三个键（缺一个 T5 就退化成单值判定）
python3 /tests/score.py
"""


def score_py() -> str:
    """解析 junit XML 并报分。**这个文件承担两处实测纠正**（见模块 docstring）：

    ① 写 `reward.json`（单数）—— harbor 只认这个名字，方案写的 `rewards.json` 会被静默忽略
    ② 做**文件覆盖核对** —— junit XML 会整份漏掉加载失败的文件，只看 failures 会给满分
    """
    return '''#!/usr/bin/env python3
"""T3 生成，勿手改。解析 junit XML → 写 reward.json / reward.txt。

## 🔴 为什么文件名是 reward.json（单数）

核 harbor 源码 `models/trial/paths.py:45-46` + `verifier/verifier.py:226`：
harbor 读 `/logs/verifier/reward.json`，**没有** `rewards.json` 这个名字。
写复数的后果不是报错而是**静默降级** —— harbor 退回读 `reward.txt`（单值），
`f2p` / `p2p` 两个键永远不进 result.json。

## 🔴 为什么必须做文件覆盖核对，不能只读 failures

实测：`bun test --reporter=junit good.test.ts loadfail.test.ts` 的 XML 根节点是
`tests="6" failures="0"`（看着全绿），而日志是 `6 pass / 1 fail / 1 error` ——
**加载失败的文件不会生成 `<testsuite>` 节点，从 XML 里整个消失**。
只读 `failures` 会把「一个测试文件根本没跑起来」判成满分通过。

所以判绿要求**三条同时成立**：① 名单里每个文件都在 XML 里出现（证明加载成功）
② 该文件 `failures == 0` ③ 该文件 `tests > 0`（零用例不构成回归保护）。

## 每条路径都要写 reward（规则1）

XML 缺失或解析失败 → 判 0 并在 `reward.json` 记 `error`，**不抛异常**。
只单跑一个加载失败的文件时 bun 连 XML 都不写，这条路径是真实会走到的。
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

VERIFIER_DIR = Path("/logs/verifier")
#: 名单由 T3 字面写入（规则5），与 test.sh 里那两行同源
F2P_FILES = json.loads(Path("/tests/f2p.json").read_text())
P2P_FILES = json.loads(Path("/tests/p2p.json").read_text())


def side_score(xml_name: str, required: list[str]) -> tuple[float, dict]:
    """一侧的分：要求的每个文件都必须**出现且全绿**，否则 0。"""
    if not required:
        # 空名单不该判满分 —— 那是「没有判据」，不是「通过了」
        return 0.0, {"error": "empty_file_list"}
    path = VERIFIER_DIR / xml_name
    if not path.exists():
        # bun 在「唯一的文件加载失败」时不写 XML，这条路径是实测走到过的
        return 0.0, {"error": "xml_missing", "missing": required}
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        return 0.0, {"error": "xml_parse_error", "detail": str(e)[:200]}

    seen: dict[str, tuple[int, int]] = {}
    for suite in root:  # 只看直接子节点：bun 一个文件一个顶层 testsuite
        f = suite.get("file")
        if f:
            seen[f] = (int(suite.get("tests") or 0), int(suite.get("failures") or 0))

    missing = [f for f in required if f not in seen]          # 没加载起来 = 没跑
    empty = [f for f in required if seen.get(f, (0, 0))[0] == 0 and f not in missing]
    failed = [f for f in required if seen.get(f, (0, 1))[1] > 0]
    ok = not missing and not empty and not failed
    return (1.0 if ok else 0.0), {
        "n_required": len(required),
        "n_seen": len(required) - len(missing),
        "missing": missing,
        "no_tests": empty,
        "failed": failed,
    }


def main() -> int:
    VERIFIER_DIR.mkdir(parents=True, exist_ok=True)
    f2p, f2p_detail = side_score("f2p.xml", F2P_FILES)
    p2p, p2p_detail = side_score("p2p.xml", P2P_FILES)
    # reward = 两侧都过才算解出来：F2P 证明修好了，P2P 证明没砸别处
    reward = 1.0 if (f2p == 1.0 and p2p == 1.0) else 0.0
    doc = {"reward": reward, "f2p": f2p, "p2p": p2p, "f2p_detail": f2p_detail, "p2p_detail": p2p_detail}
    # 双源：harbor 优先读 reward.json，reward.txt 供 T5 交叉核对（§3.8-D）
    (VERIFIER_DIR / "reward.json").write_text(json.dumps(doc, ensure_ascii=False) + "\\n")
    (VERIFIER_DIR / "reward.txt").write_text(f"{reward}\\n")
    print(json.dumps(doc, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def normalize_patch(patch: str) -> str:
    """统一 LF 换行并保证尾换行（§4 T3 ⑥）。

    `a/` `b/` 前缀由 T2 生成时就是标准 `git diff` 格式（已抽验），这里只兜换行 ——
    CRLF 会让容器里的 `git apply` 报 "corrupt patch"，而报错文本不指向换行符。
    """
    s = patch.replace("\r\n", "\n").replace("\r", "\n")
    return s if s.endswith("\n") else s + "\n"


def build_one(task_id: str, row: dict, snap: dict, p2p: list[str], instruction: str) -> dict:
    """写一条 task 的七个文件，返回该条的统计。`environment/` 不动（T4 的产物）。"""
    # 空题面必须炸在生成阶段：harbor 的格式校验只查文件存在，不查内容（见 instruction_md）
    if not instruction.strip():
        raise ValueError(
            f"{task_id} 的 instruction_clean 为空 —— 题面缺失不会被 "
            f"Task.is_valid_dir() 抓到，会变成「全批 reward=0」"
        )
    task_dir = c.MVP_TASKS / task_id
    files: dict = row.get("files") or {}
    # test_patch 带进来的所有测试相关文件（**含 bun 不收集的辅助文件**）。
    # 保护名单用这一份 —— 辅助文件 agent 同样能改。
    test_files = sorted(p for p, v in files.items() if v.get("is_test"))
    # F2P 只放 bun 真会收集的文件：塞进辅助文件会让它从 XML 消失 → f2p 恒 0，
    # 连 oracle 都做不出来（见 is_bun_test_file 的 docstring）
    f2p = [p for p in test_files if is_bun_test_file(p)]
    f2p_excluded = [p for p in test_files if not is_bun_test_file(p)]
    if not f2p:
        # 空 F2P 等于「这条 task 没有判据」。score.py 对空名单判 0（规则：空名单不是
        # 满分），但那时形态是「所有 task 的 f2p 都 0」，容易被误读成判分坏了。
        raise ValueError(
            f"{task_id} 过滤后 F2P 为空（test_patch 带进来的 {len(test_files)} 个文件 "
            f"bun 一个都不收集：{test_files}）—— 这条 task 无判据，应由 T6 决定去留"
        )
    # 还原名单：base 上有的 checkout 回去，base 上没有的（新增测试）直接删
    restore = sorted(p for p in test_files if files[p].get("base_exists")) + sorted(p2p)
    remove = sorted(p for p in test_files if not files[p].get("base_exists"))

    (task_dir / "solution").mkdir(parents=True, exist_ok=True)
    (task_dir / "tests").mkdir(parents=True, exist_ok=True)

    (task_dir / "instruction.md").write_text(
        instruction_md(snap, instruction), encoding="utf-8"
    )
    (task_dir / "task.toml").write_text(task_toml(task_id, row), encoding="utf-8")

    solve = task_dir / "solution" / "solve.sh"
    solve.write_text(solve_sh(), encoding="utf-8")
    solve.chmod(0o755)
    (task_dir / "solution" / "gold_patch.diff").write_text(
        normalize_patch(row["code_patch"]), encoding="utf-8"
    )

    test = task_dir / "tests" / "test.sh"
    test.write_text(
        test_sh(task_id, f2p, p2p, restore, remove, snap["test_cmd"]), encoding="utf-8"
    )
    test.chmod(0o755)
    (task_dir / "tests" / "test_patch.diff").write_text(
        normalize_patch(row["test_patch"]), encoding="utf-8"
    )
    (task_dir / "tests" / "score.py").write_text(score_py(), encoding="utf-8")
    # 名单也落成 json 给 score.py 读 —— 与 test.sh 里的字面名单同源（规则5），
    # 走文件而不是环境变量：变量会被容器环境覆盖，文件不会
    (task_dir / "tests" / "f2p.json").write_text(json.dumps(f2p, ensure_ascii=False), encoding="utf-8")
    (task_dir / "tests" / "p2p.json").write_text(json.dumps(p2p, ensure_ascii=False), encoding="utf-8")

    meta = {
        "task_id": task_id,
        "unit_id": row["unit_id"],
        "sid": row.get("sid"),
        "repo": row["repo"],
        "base_commit": row["base_commit"],
        "base_resolution": row.get("base_resolution"),
        "band": row.get("band"),
        "category": row.get("category"),
        "started_at": row.get("started_at"),
        "model": row.get("model"),
        "vendor": row.get("vendor"),
        "agent_source": row.get("agent_source"),
        "test_cmd": snap["test_cmd"],
        # 口径②：单位是文件，所以过滤方式是 path（`t4-env.md` §9.3）
        "filter_mode": "path",
        "f2p": f2p,
        "p2p": p2p,
        "n_f2p": len(f2p),
        "n_p2p": len(p2p),
        # test_patch 带进来但 bun 不收集的文件（辅助/preload）。它们**不进 F2P**
        # （否则从 XML 消失 → f2p 恒 0），但**仍在保护名单里**（agent 能改它们）。
        "f2p_excluded_not_bun_test": f2p_excluded,
        "protection": {"restore": restore, "remove": remove},
        "n_code_files": row.get("n_code_files"),
        "n_test_files": row.get("n_test_files"),
        "anchor_hit_rate": row.get("anchor_hit_rate"),
        "snapshot": {
            "tar_sha256": snap.get("tar_sha256"),
            "tar_bytes": snap.get("tar_bytes"),
            "n_files_kept": snap.get("n_files_kept"),
            "n_files_stripped": snap.get("n_files_stripped"),
            "stripped_top_dirs": snap.get("stripped_top_dirs"),
            "eval_framework_mode": snap.get("eval_framework_mode"),
            "cross_apply_check": snap.get("cross_apply_check"),
        },
        "reward_keys": ["reward", "f2p", "p2p"],
        # 纠正记录：harbor 只读单数名（见本脚本 docstring），方案原文写的是复数
        "reward_file": "reward.json",
        "generated_by": "scripts/mvp/t3-build-harbor-tasks.py",
    }
    (task_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"task_id": task_id, "n_f2p": len(f2p), "n_p2p": len(p2p), "band": row.get("band")}


def main() -> int:
    ap = argparse.ArgumentParser(description="T3 — 生成 harbor 原生格式的 task 目录")
    ap.add_argument("--only", default=None, help="只生成某条 task（调试用）")
    ap.add_argument(
        "--check-only",
        action="store_true",
        help="只核对已有产物是否齐全，**不重新生成**（反向自证②要用：生成会把缺的文件补回来）",
    )
    ap.add_argument(
        "--allow-missing-p2p",
        action="store_true",
        help="P2P 未采全时也生成（**只用于调试**，正式产物必须全采完）",
    )
    args = ap.parse_args()

    c.ensure_mvp_dirs()
    snaps = {r["task_id"]: r for r in c.read_jsonl(SNAPSHOTS) if r.get("ok")}

    # 🔴 --check-only 必须在生成之前分叉出去，不能只在末尾加个核对。
    # 原因：生成是**幂等重写** —— 跑一遍就把缺的文件补回来了，末尾那次核对
    # 永远看不到「产物被破坏」的状态（只能抓到生成器自己漏写）。
    # 而验收项要的是「删掉某条的 tests/score.py → 自查必须报错」，
    # 那就必须有一条**不写盘**的路径。T5 的门禁也该用这条来复核交付物。
    if args.check_only:
        todo_c = [args.only] if args.only else sorted(snaps)
        incomplete_c = {t: m for t in todo_c if (m := missing_files(c.MVP_TASKS / t))}
        if incomplete_c:
            print(f"🔴 {len(incomplete_c)}/{len(todo_c)} 条 task 的产物不齐：", file=sys.stderr)
            for t, miss in sorted(incomplete_c.items()):
                print(f"   {t}: {miss}", file=sys.stderr)
            return 2
        print(f"✅ {len(todo_c)} 条 task 的 {len(REQUIRED_FILES)} 个文件全部齐备且非空")
        return 0
    resolved = {r["unit_id"]: r for r in c.read_jsonl(c.RESOLVED) if r.get("ok")}
    # 题面只在 candidates.jsonl 里（T1 产物），resolved.jsonl 没带上这个字段
    instructions = {
        r["unit_id"]: (r.get("instruction_clean") or "") for r in c.read_jsonl(c.CANDIDATES)
    }

    if not P2P_IN.exists():
        print(
            f"🔴 {P2P_IN} 不存在 —— 先跑 `python3 scripts/mvp/t3-sample-p2p.py`。\n"
            f"   P2P 必须采在 T4 剔除后的快照上（衔接①），采错文件树会让全批 reward=0。",
            file=sys.stderr,
        )
        return 2

    p2p_by_task: dict[str, list[str]] = {}
    for rec in c.read_jsonl(P2P_IN):
        if rec.get("ok"):
            for tid, lst in (rec.get("p2p") or {}).items():
                p2p_by_task[tid] = lst

    todo = [args.only] if args.only else sorted(snaps)
    missing = [t for t in todo if t not in p2p_by_task]
    if missing and not args.allow_missing_p2p:
        print(
            f"🔴 有 {len(missing)}/{len(todo)} 条 task 还没有 P2P 名单："
            f"{missing[:8]}{' ...' if len(missing) > 8 else ''}\n"
            f"   跑 `python3 scripts/mvp/t3-sample-p2p.py --resume` 补齐，"
            f"或 --allow-missing-p2p 强行生成（调试用，产物不可用于评测）",
            file=sys.stderr,
        )
        return 2

    built: list[dict] = []
    for task_id in todo:
        snap = snaps[task_id]
        row = resolved.get(snap["unit_id"])
        if not row:
            print(f"🔴 {task_id} 在 resolved.jsonl 里找不到 {snap['unit_id']}", file=sys.stderr)
            return 2
        built.append(
            build_one(
                task_id,
                row,
                snap,
                p2p_by_task.get(task_id, []),
                instructions.get(snap["unit_id"], ""),
            )
        )

    # 产物齐全自查（方案 §4 T3 验收项 + 反向自证②）。放在生成出口而不是逐条 build_one
    # 里面：build_one 只知道自己写了什么，核不到 T4 的 environment/ 那两个文件。
    incomplete = {t: m for t in todo if (m := missing_files(c.MVP_TASKS / t))}
    if incomplete:
        print(
            f"🔴 {len(incomplete)} 条 task 的产物不齐（缺失或空文件）：",
            file=sys.stderr,
        )
        for t, miss in sorted(incomplete.items())[:10]:
            print(f"   {t}: {miss}", file=sys.stderr)
        print(
            "   environment/ 两个文件属 T4：快照不入 git，换机器后先跑 "
            "scripts/mvp/t4-build-env.py 重建",
            file=sys.stderr,
        )
        return 2

    stats = {
        "task": "T3",
        "n_tasks": len(built),
        "files_per_task": len(REQUIRED_FILES),
        "reward_file": "reward.json",
        "reward_keys": ["reward", "f2p", "p2p"],
        "filter_mode": "path",
        "by_band": {b: sum(1 for x in built if x["band"] == b) for b in ("S", "M", "L")},
        "f2p": {
            "min": min(x["n_f2p"] for x in built),
            "max": max(x["n_f2p"] for x in built),
            "total": sum(x["n_f2p"] for x in built),
        },
        "p2p": {
            "min": min(x["n_p2p"] for x in built),
            "max": max(x["n_p2p"] for x in built),
            "total": sum(x["n_p2p"] for x in built),
        },
    }
    STATS_OUT.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
