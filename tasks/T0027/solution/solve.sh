#!/bin/bash
# T3 生成，勿手改。参考解入口（OracleAgent 跑它）
set -euo pipefail
cd /repo
# ⚠️ 必须先刷 index，否则 --3way 报 `does not match index`（见 solve_sh docstring）
git update-index -q --refresh || true
git apply --3way /solution/gold_patch.diff
