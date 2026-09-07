#!/usr/bin/env python3
"""T3 — harbor task 目录生成【T0 阶段：骨架，未实现】

出处：`docs-research/trajectory-platform/bench-mvp-plan.md` v1.2 §4 T3（1.5 天）

⚠️ **这是 T0 产出的骨架**，`main()` 直接以非零码退出。

输入：`resolved.jsonl`（T2 产物）+ T4 的仓库快照
输出：`bench/v0.2-mini/tasks/T*/`，**harbor 原生格式**（七个文件）

## 目录格式必须严格照 harbor 的 TaskPaths 契约（§3.8-B）

    T0001/
    ├── instruction.md
    ├── task.toml                # schema_version = "1.4"
    ├── environment/Dockerfile
    ├── solution/solve.sh        # OracleAgent 挂到 /solution
    ├── tests/test.sh            # Evaluator 挂到 /tests
    ├── tests/score.py           # 解析 junit，见规则6
    └── meta.json                # 我们的溯源信息（harbor 不读）

**直接产出终态**，不要先出中间格式再转换 —— 少一层转换少一处失真（§4 T0）。
`Task.is_valid_dir()` 是格式的判据（见 `tests/test_mvp.py`），
它是**确定性**校验；`harbor check` 要跑 LLM 评委，不适合当 T0/T3 的格式门禁。

## 执行模型（§4.0，先读它否则会实现错）

**agent 与 verifier 跑在同一个容器里**（已核源码：`verifier/verifier.py:150`
上传 tests 到 `self.environment`、`:199` 在同一 environment exec）。
agent 改完就地留在 `/repo`，**不存在提取 patch 再重放的环节**。

## 七条规则（§4 T3，每条都对应一种「绿着坏掉」）

1. 每条代码路径都必须写 reward，**绝不能有「文件已存在就不写」的分支** ——
   否则 agent 可以自己往 reward 文件里写个 1
2. 先无条件覆盖为 0，跑完再按结果改写
3. `test_patch` 在 verifier 阶段应用，**不在 agent 阶段**
4. 防 agent 改测试：`git checkout -- tests/` + `git clean -fd tests/`，
   并用 `git apply --3way`
5. F2P / P2P 名单由 T3 **字面写入** test.sh，用**文件路径**而非
   `--test-name-pattern` —— 实测测试名含中文与空格（`切换权限模式`），走正则要转义
6. **不许 `grep -q "0 fail"` 判分**（R1 的经典成因：日志格式一变就恒真/恒假**且不报错**）。
   用 `--reporter=junit` 结构化输出 + `tests/score.py` 解析
7. reward 写三个键（`reward` / `f2p` / `p2p`），缺一个 T5 的门禁就退化成单值判定（§3.8-D）

## ⚠️ 与 T4 的衔接（§4.9 三处最容易漏的衔接之一）

**P2P 名单必须在 T4 剔除泄漏路径后的快照上采**，否则会采到 `evals/` 下已被剔除的
测试 → P2P 恒败 → 全部 reward=0，形态像「task 太难」而不像「名单采错了」。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common as c  # noqa: E402,F401  （T3 实现时要用）

NOT_IMPLEMENTED = "T3 尚未实现 —— T0 只交付骨架。实现契约见本文件 docstring 与方案 §4 T3。"


def main() -> int:
    print(NOT_IMPLEMENTED, file=sys.stderr)
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
