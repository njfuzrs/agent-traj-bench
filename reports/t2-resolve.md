# T2 — base_commit 反查 + patch 反解报告

> 日期：2026-09-08
> 方案：`docs-research/trajectory-platform/bench-mvp-plan.md` v1.2 §4 T2（2 天，最重的一步）
> 产物：`bench/v0.2-mini/meta/resolved.jsonl`（182 行，含淘汰留痕）+ `resolved.stats.json`
> 脚本：`scripts/mvp/t2-resolve-base-patch.py`

## 一、结论速览

| 项 | 结果 | 阈值 | 判定 |
|---|---|---|---|
| **反解成功** | **70 条** | 目标 40-50 | ✅ 超出 |
| `exact` 占比 | **100%**（182/182） | ≥85% | ✅ |
| 锚点达标候选（≥0.7） | **147** | ≥100 | ✅ |
| `git apply --check` 通过 | **70/70** | 全通过 | ✅ |
| 反向自证（模糊切分） | 退出码 3，抓到 8 个泄漏路径 | 必须报红 | ✅ |
| 单测 | **85 passed**（T0 的 68 + T2 新增 17） | 全绿 | ✅ |

70 条的分布：`S 5 / M 25 / L 40`，`bug_fix 28 / test_authoring 42`，
`sid-code 65 / iam-studio-fe 5`，月份 `2026-06 24 / 07 26 / 08 20`，
落在 54 个不同的 base_commit 上。共 413 个 code 文件 + 161 个 test 文件（含 149 个新建）。

**锚点命中率 96.1%，远高于方案 §3.4 预估的 70.7%** —— 差距来自两处：严格路径映射
（§3.4 那 21 条失败正是模糊切分造成的）与下面第二节的失败写操作过滤。

## 二、两条方案没写、但不做就会产出错 patch 的实测结论

### R-1 🔴 必须按 `is_error` 跳过「采集当时就失败」的写操作

轨迹忠实记录 agent 的**每一次尝试**，包含失败的那些。182 条候选的 `step_range` 内
有 **43 次写操作是失败的**（Edit 41 / Write 2），三种形态：

```
<tool_use_error>String to replace not found in file.</tool_use_error>
<tool_use_error>No changes to make: old_string and new_string are exactly the same.</tool_use_error>
<tool_use_error>File has been modified since read, either by the user or by a linter.</tool_use_error>
```

判据在轨迹里是现成的：`trajectory[]` 是 action / observation 成对的，
`message_type == 'observation'` 的 step 带 `tool_use_id` 与 `is_error`，指向前一个 action 的结果。

**这个坑的形态很坑**：把失败的编辑当成生效的改动重放，表现为「重建到某个文件时
`old_string` 对不上」—— 它**看着像轨迹质量差、或 base 反查偏了**，实际是我们重放了
一次本就没生效的编辑。方案 §3.2 只说「`tool_input` 参数完整、足以精确重建 diff」，
没提这一层。

实测跳掉之后：

| | 跳过前 | 跳过后 |
|---|---|---|
| 全文件重建成功的候选 | 99 | **110** |
| 锚点命中率 | 95.9% | **96.1%** |
| 最终合格候选 | 63 | **71** |

实现见 `common.iter_write_actions()`。**它产出 `failed=True` 而不是直接跳过** ——
T2 要把跳过次数写进 `resolved.jsonl` 的 `n_failed_ops_skipped` 留痕。静默丢弃等于
让后面的人无法判断「这条 patch 缺不缺东西」。

### R-2 🔴 「在仓库目录下」不等于「是仓库内容」

严格前缀映射（§3.4 要求的那条）**不足以**挡住所有非仓库内容。实测抓到的真实泄漏：

```
.claude/worktrees/fix-lsp-client-frame-protocol/packages/core/tests/lsp/client.test.ts
.claude/worktrees/fix-lsp-client-frame-protocol/.git-commit-msg.tmp
.claude/worktrees/fix-lsp-client-frame-protocol/.pr-body.tmp
```

它**通过了**严格前缀映射（确实在 `/Users/zhourusheng/Code/person/sid-code/` 下面），
往返不变式也成立 —— 但那是 **git worktree，另一个分支的临时检出**。
sid-code 的 `.gitignore` 用 `.claude/*` fail-closed 把它挡在库外。
**12 条候选、214 次写操作命中**，其中 1 条已经混进了首轮的 `ok` 结果。

后果与 `same_repo_worktree` 同级：patch 里混进了不属于 base 的文件树，
`apply` 得上去也是错的，还会把 `.git-commit-msg.tmp` / `.pr-body.tmp` 这类过程垃圾
带进 task。所以按 `gitignored_paths` 淘汰，**不做「悄悄删掉那几个文件然后照发」**。

判据用 **`git check-ignore` + base 时点的 `.gitignore`**，两个决定都是必要的：

- **用 git 而不是自己写 pattern**：`.gitignore` 的语义远不止 glob。本仓就有
  `.claude/*` 配 `!.claude/skills/` 的否定放行（`skills/` 是仓库资产，确实入库了 3 个文件）。
  自己实现一定漏掉否定规则、目录不下降、`**` 与前导 `/` 的差别。实测 git 判得对：
  `worktrees/...` 判 ignore，`skills/eval-session/SKILL.md` 放行。
- **用 base 时点而不是 HEAD**：§3.5 已证明工具链在漂移，`.gitignore` 也一样在长 ——
  `.claude/*` 这条规则是后来才加的。拿 HEAD 的规则判一个 2026-06 的 commit，
  等于用今天的标准判过去。

## 三、七个步骤的实现要点

| 步 | 做法 | 关键决定 |
|---|---|---|
| ① base 反查 | `git rev-list -1 --before={started_at} refs/heads/main` | 只查 `main`（§3.3 实测跨 ref 零收益）；182/182 全部命中 |
| ② 写操作提取 | `step_range` 内的 Edit/Write/MultiEdit | **按 `is_error` 过滤**（R-1） |
| ③ 路径映射 | `common.map_repo_path` 严格前缀 | 加往返不变式守卫 + `gitignore` 复核（R-2） |
| ④ 分侧 | `IS_TEST` 正则 | 用 `git diff -- <paths>` 分侧，**不切 diff 文本** |
| ⑤ 剔文档 | `docs/` 前缀 + `*.md` | 49 个文件被剔、13 条候选受影响，记入 `excluded_files` |
| ⑥ 锚点校验 | 每文件**首次** Edit 的 `old_string` 首行 | 只看首次：后续 Edit 的 old_string 来自前一次结果，算进去是假阴性 |
| ⑦ 生成 diff | 临时 git 仓库 `git diff --cached` | 见下 |

**⑦ 为什么用临时 git 仓库而不是 `git diff --no-index`**：后者在新建文件上会把 a 侧
写成 `a/b/src/x.ts`（把两个比较目录名也带进路径），要靠 `-p2` 去凑，换个目录层级就错。
临时仓库出的是标准 `a/<rel>` / `b/<rel>` 头，`git apply -p1` 直接吃 ——
新建 / 删除 / 无末尾换行 / 中文四种情况全部实测通过。

**重建失败即整条淘汰，不「尽力而为地跳过」**：一个 Edit 对不上，后续 Edit 的上下文
就都不可信了，硬跑下去会产出一份**看着像** gold patch、实际错位的 diff ——
正是 §3.8-F「绿着坏掉」那一类。

## 四、112 条淘汰的归因

| 原因 | 条数 | 判读 |
|---|---|---|
| `rebuild_failed` | 55 | 见下拆解 |
| `not_two_sided` | 37 | 只有 code 或只有 test，做不出 F2P（§3.6 前提） |
| `gitignored_paths` | 12 | R-2 抓到的 worktree 泄漏 |
| `no_code_ops` | 5 | 剔掉文档与非仓库路径后没有代码改动了 |
| `incomplete_paths` | 3 | 同仓 worktree / 跨仓路径被丢弃 → patch 缺一块 |

`rebuild_failed` 的文件级拆解：`old_string_not_found` 65 / `phantom_file` 57。

**两者分开命名是因为根因不同**，混成一个名字，T6 人工过目时就没法判断该查哪边：

- `phantom_file` —— base 里没这个文件，且首个 Edit 带非空 `old_string`。
  实测 122 例（含被淘汰候选），归因：**78 条分支未合/后被删/路径已改、
  36 条只在别的 ref、8 条 base 之后才合入 main**。这是仓库历史的问题，不是我们的 bug。
- `old_string_not_found` —— base 里有这个文件，但内容对不上。base 反查偏差或
  脱敏改写导致。

⚠️ **淘汰不等于永久丢弃**：182 行全部写进 `resolved.jsonl` 并带 `drop_reason`，
`ok=false` 的行同样保留 `base_commit` / `dropped_paths` / `rebuild_failures`。
T6 需要复核某条为什么被淘汰时，不用重跑。

## 五、验收对照（方案 §4 T2 + §4.9）

| 验收项 | 要求 | 实测 | |
|---|---|---|---|
| 1 | `exact ≥ 85%` | 100%（182/182） | ✅ |
| 2 | `anchor ≥ 0.7` 的候选 ≥ 100 | 147 | ✅ |
| 3 | `code_patch` 能在 base 上 `apply --check` 通过 | 70/70 | ✅ |
| 4 | **反向自证**：模糊切分下锚点命中率显著下降并报红 | 退出码 3，8 个泄漏路径 | ✅ |

**验收 4 的实现方式**：`--selftest-fuzzy-path` 把 `split('sid-code/')` 这种模糊切分
注入**主路径**（而不是另写一段只验自己的分支 —— 沿用 T1 `--selftest-strict-secret` 的做法）。
守卫是主路径上的**往返不变式** `前缀 + 相对路径 == 原绝对路径`：严格映射下 182 条
实测 0 违反；模糊切分下 `.claude/projects/-Users-...-person-sid-code/memory/MEMORY.md`
被切成仓库内的 `memory/MEMORY.md`，不变式立刻破。

```
$ python3 scripts/mvp/t2-resolve-base-patch.py --selftest-fuzzy-path --limit 40
✅ 泄漏守卫生效：6 条候选被拦下，泄漏路径 8 个
   LEAK  /Users/zhourusheng/.claude/projects/.../memory/MEMORY.md
   LEAK  /Users/zhourusheng/.claude/projects/.../memory/mcp-oauth-implementation.md
   ...
退出码 3 = 守卫按预期报红（这是自证的期望结果）
```

**额外做的独立复验**（不靠自己的 `apply --check` 自证）：随机抽 8 条，
`git clone --shared` 出真实 base checkout，用 `git apply -p1` **真打**patch —— 8/8 成功。
再扫 70 条的 573 个 patch 文件：文档 0、`.claude/` 0、worktree 0、绝对路径/越界 0、
分侧错位 0。

## 六、给 T3/T6 的三条

1. **`resolved.jsonl` 的 `ok=true` 有 70 条，但 T3 的目标是 40-50 条 task。**
   多出来的 20 条是给 T6 人工淘汰留的余量 —— 不要在 T3 就截断到 50，
   让 T6 按质量淘汰比按顺序截断好。
2. **`excluded_files` 字段必须带进 T3 的 task 元数据。** 13 条候选剔掉了文档，
   其中 `docs/bugfixes/*.md` 直接写明根因与修复方案。T6 的泄漏扫描要复核
   这些文档确实没出现在 task 的任何地方（含 instruction）。
3. **`phantom_file` 57 例说明 mirror 的 `main` 不含全部开发历史。** T4 做仓库快照时，
   如果发现某 base_commit 的 checkout 缺文件，先查是不是这一类，
   不要以为是快照做坏了。

## 七、留档

| 产物 | 说明 |
|---|---|
| `bench/v0.2-mini/meta/resolved.jsonl` | 182 行（70 ok + 112 淘汰带原因），2.9 MB |
| `bench/v0.2-mini/meta/resolved.stats.json` | 验收数字 + 淘汰归因 + 分布 |
| `scripts/mvp/t2-resolve-base-patch.py` | 实现（含 `--selftest-fuzzy-path` / `--limit`） |
| `scripts/mvp/common.py` | 新增 `iter_write_actions` / `observation_errors` / `load_trajectory` |
| `scripts/mvp/tests/test_mvp.py` | 85 passed（新增 17 条覆盖 T2 的 ⑫-⑯） |

全量跑一遍约 24 秒（182 条，含 54 次 base checkout 的 blob 读取与 70 次 apply --check）。
