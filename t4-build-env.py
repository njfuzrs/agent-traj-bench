#!/usr/bin/env python3
"""T4 — env 镜像 + 仓库快照【T0 阶段：骨架，未实现】

出处：`docs-research/trajectory-platform/bench-mvp-plan.md` v1.2 §4 T4（1.5 天）

⚠️ **这是 T0 产出的骨架**，`main()` 直接以非零码退出。

输入：mirror（只读）+ `resolved.jsonl`
输出：`environment/`（Dockerfile）+ `repo-snapshot.tar.gz`

## 这是唯一允许把 mirror 内容取出到工作区的 task

纪律 2 说「mirror 只读、不 clone 到工作区」，**T4 是明确的例外**（§4 T0）——
它就是要产出快照。但仍然只读 mirror 本身：用 `git archive` / `git worktree`
取内容，不在 mirror 目录里写任何东西。

## 🔴 新增泄漏面（§3.8-E）

base 快照里含 **harbor 自身与判分校准集**，必须剔除。这条是 harbor 接入带来的
新泄漏面，v1.0 没有 —— 不剔除的话 agent 能直接读到判分逻辑。

## ⚠️ 步骤④交叉验收（§4.9 三处衔接之一，v1.2 新增）

T2 在 **mirror 真实 commit** 上验 `git apply --check`；T4 的快照**剔除过泄漏路径**。
patch 若触及被剔除的路径，**两处验收都通过而容器里必然失败**。
所以 T4 出快照后要回头把 T2 的每条 patch 在**快照上重验一次** `apply --check`。

这是「两层各自都绿、合起来是坏的」的典型 —— 单看 T2 或单看 T4 都发现不了。

## 运行期网络

方案要求运行期 `--network none`（避免 agent 联网找答案）。
⚠️ TZ 实测记了一条相关的：`host.docker.internal` 在 colima 下不可解析，
要用 `192.168.5.2`（本机 dockerd 带 `--host-gateway-ip=192.168.5.2`）。
正常 `--network none` 时不该依赖它。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common as c  # noqa: E402,F401  （T4 实现时要用）

NOT_IMPLEMENTED = "T4 尚未实现 —— T0 只交付骨架。实现契约见本文件 docstring 与方案 §4 T4。"


def main() -> int:
    print(NOT_IMPLEMENTED, file=sys.stderr)
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
