#!/usr/bin/env python3
"""T2 — base_commit 反查 + patch 反解【T0 阶段：骨架，未实现】

出处：`docs-research/trajectory-platform/bench-mvp-plan.md` v1.2 §4 T2（2 天，最重的一步）

⚠️ **这是 T0 产出的骨架**，`main()` 直接以非零码退出。T0 的交付是「脚本骨架 +
目录约定 + common.py 与单测」，不含 T2 的实现。把契约先写进 docstring 是为了
让 T2 开工时不必回头翻方案 —— 也为了让任何人 `--help` 一眼看出它还没实现，
而不是跑出一个空 `resolved.jsonl` 然后以为成功了。

输入：`bench/v0.2-mini/meta/candidates.jsonl`（T1 产物，182 条）
      + `data/pulled_sessions/<sid>/session.traj`（只读）
      + mirror（只读）
输出：`bench/v0.2-mini/meta/resolved.jsonl`（含 base_commit + 双侧 patch）

## 要做的四件事

1. **反查 base_commit**：`common.resolve_base_commit(repo, started_at)`。
   §3.3 实测：**只查 `refs/heads/main`**，多 ref 搜索零收益（命中 17 vs 17）。
2. **重建 diff**：遍历单元 `step_range` 内的 `Edit` / `Write` step，
   用 `old_string` / `new_string` / `file_path` / `replace_all` 精确重建。
   `common.iter_traj_actions()` 已经把 `tool_input` 解析好了。
3. **锚点校验**：`old_string` 首行是否存在于 base_commit 的该文件中。
   §3.4 实测命中 145/205，**真实失败仅 3 条** —— 另外 36 条是会话内新建文件
   （本来就不该存在，不算失败）、21 条是路径映射粗糙（用
   `common.map_repo_path()` 严格前缀匹配即可避免）。
4. **拆双侧 patch**：测试文件进 `test_patch`，其余进 `gold_patch`（§3.6 F2P 范式）。

## 验收（§4.9）

- `exact ≥ 85%`
- `anchor ≥ 0.7` 的候选 ≥ 100 条
- **反向自证**：把 `map_repo_path` 改成 `split('sid-code/')` 这类模糊切分，
  锚点命中率必须显著下降并报红（§3.4 的 21 条失败就是这么来的）
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common as c  # noqa: E402,F401  （T2 实现时要用）

NOT_IMPLEMENTED = "T2 尚未实现 —— T0 只交付骨架。实现契约见本文件 docstring 与方案 §4 T2。"


def main() -> int:
    print(NOT_IMPLEMENTED, file=sys.stderr)
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
