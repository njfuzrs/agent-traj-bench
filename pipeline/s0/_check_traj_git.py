#!/usr/bin/env python3
"""_check_traj_git.py — check-collector-live.sh 的第 ④ 项：端到端验证

前三项都是「形式检查」（进程新旧、文件一致性）—— 全绿也不代表产出数据里
真有字段。这一项直接看 session.traj 的内容。

退出码：0 有 git 状态或无从判断；1 明确缺失（两个 P0 未生效）
"""

import json
import os
import sys
import time


def main() -> int:
    traj_dir = sys.argv[1]
    hours = float(os.environ.get("CHECK_HOURS", "24"))
    now = time.time()

    checked = with_git = 0
    newest = None
    for sid in os.listdir(traj_dir):
        path = os.path.join(traj_dir, sid, "session.traj")
        if not os.path.exists(path):
            continue
        if (now - os.path.getmtime(path)) / 3600 > hours:
            continue
        try:
            with open(path) as f:
                metadata = json.load(f).get("metadata") or {}
        except Exception:
            continue
        checked += 1
        # 只认新版字段。旧字段 metadata.git（{sha, branch, originUrl}）来自更早的
        # 采集路径，把它算进来会让「什么都没发生」看起来像「已经生效了」——
        # §9.3 记录的正是这个误判掩盖了真实故障。
        if metadata.get("git_state") or metadata.get("git_head"):
            with_git += 1
        start = metadata.get("start_time") or ""
        if newest is None or start > newest:
            newest = start

    if checked == 0:
        print(f"  ! 最近 {hours:g} 小时无本地会话，无法端到端验证")
        return 0
    if with_git == 0:
        print(f"  ✗ 最近 {hours:g} 小时 {checked} 条会话，含 git 状态 0 条 —— 两个 P0 未生效")
        print(f"      最新会话 start_time={newest}")
        print("      这是 §9.3 记录的故障：前几项形式检查可能全绿而这里仍红。")
        return 1
    print(f"  ✓ 最近 {hours:g} 小时 {checked} 条会话，{with_git} 条含 git 状态")
    return 0


if __name__ == "__main__":
    sys.exit(main())
