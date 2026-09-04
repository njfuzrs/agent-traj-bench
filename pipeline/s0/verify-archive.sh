#!/usr/bin/env bash
# verify-archive.sh — 验收镜像归档
#
# 对应 bench-curation-design.md §9 Phase 0 的验收标准：
#   「任取 20 个历史 commit 可 checkout；未合并分支与 worktree 分支的 tip
#     均在镜像内可解析」
#
# 做法：不真的 checkout（bare 仓库无工作区，且 20 次 checkout 很慢），
# 改用 `git rev-parse <sha>^{commit}` + `git cat-file -e <sha>^{tree}` 验证
# commit 与其 tree 对象在镜像内完整存在 —— 这与「可 checkout」等价，
# 因为 checkout 失败的唯一原因就是对象缺失。

set -uo pipefail

ARCHIVE_DIR="${ARCHIVE_DIR:-$HOME/Code/_archive/bench-mirrors}"
CODE_ROOT="${CODE_ROOT:-$HOME/Code}"
SAMPLE_N="${SAMPLE_N:-20}"

[ -d "$ARCHIVE_DIR" ] || { echo "归档目录不存在：$ARCHIVE_DIR，先跑 archive-repos.sh"; exit 1; }

total_pass=0; total_fail=0

for dst in "$ARCHIVE_DIR"/*.git; do
  [ -d "$dst" ] || continue
  name="$(basename "$dst" .git)"
  repo="$(echo "$name" | sed 's|_|/|')"
  echo "── $repo"

  # ① 抽 N 个历史 commit，验证对象完整
  pass=0; fail=0
  # 均匀抽样：按步长在整个历史跨度上取 N 个，而不是只取最近 N 个
  # —— 最近的 commit 一定在，验不出对象缺失。
  #
  # 不用 `mapfile` / `readarray`：macOS 自带的是 bash 3.2，没有这两个内建，
  # 会让脚本在「0 个仓库通过 / 0 个有问题」的假绿状态下退出（正是两份方案
  # 都点名的 F4「假门禁」）。改用 awk 抽样 + while read，POSIX 范围内实现。
  n=$(git -C "$dst" rev-list --all --count 2>/dev/null || echo 0)
  if [ "${n:-0}" -eq 0 ]; then
    echo "  ✗ 镜像内无 commit"
    total_fail=$((total_fail+1))
    continue
  fi
  step=$(( n / SAMPLE_N )); [ "$step" -lt 1 ] && step=1
  while read -r sha; do
    [ -n "$sha" ] || continue
    if git -C "$dst" rev-parse -q --verify "$sha^{commit}" >/dev/null 2>&1 \
       && git -C "$dst" cat-file -e "$sha^{tree}" 2>/dev/null; then
      pass=$((pass+1))
    else
      fail=$((fail+1)); echo "  ✗ commit 对象不完整：$sha"
    fi
  done <<EOF
$(git -C "$dst" rev-list --all 2>/dev/null | awk -v s="$step" -v m="$SAMPLE_N" '(NR-1)%s==0 && c<m {print; c++}')
EOF
  echo "  commit 抽样：$pass/$((pass+fail)) 通过（历史共 $n 个 commit）"

  # 抽样数为 0 视为失败，不是通过。
  # 反向自证时发现的残留假绿：破坏对象库后 `rev-list --all` 只剩空输出，
  # pass=fail=0，而「fail -eq 0」会被当成通过。若此时源仓库又不在本地
  # （ref 比对被跳过），该仓库就会一路绿灯通过。
  if [ "$((pass+fail))" -eq 0 ]; then
    echo "  ✗ 抽样数为 0 —— 镜像可读但取不出任何 commit（对象库可能已损坏）"
    fail=$((fail+1))
  fi

  # ② 源仓库的每个 ref 都必须在镜像内可解析（含未合并分支）
  src="$CODE_ROOT/$repo"
  ref_miss=0
  if [ -d "$src/.git" ]; then
    while read -r sha ref; do
      git -C "$dst" rev-parse -q --verify "$sha^{commit}" >/dev/null 2>&1 || {
        echo "  ✗ ref 未进镜像：$ref ($sha)"; ref_miss=$((ref_miss+1)); }
    done < <(git -C "$src" for-each-ref --format='%(objectname) %(refname)')

    # ③ worktree 的 HEAD 不是 ref，需单独验证（bench 方案 §2.6：
    #    已有 14 条会话的 wd 落在 worktree 内）
    wt_miss=0; wt_n=0
    while read -r wt; do
      [ -n "$wt" ] || continue
      wt_n=$((wt_n+1))
      wsha=$(git -C "$wt" rev-parse HEAD 2>/dev/null) || continue
      git -C "$dst" rev-parse -q --verify "$wsha^{commit}" >/dev/null 2>&1 || {
        echo "  ✗ worktree HEAD 未进镜像：$wt ($wsha)"; wt_miss=$((wt_miss+1)); }
    done < <(git -C "$src" worktree list --porcelain 2>/dev/null | awk '/^worktree /{print $2}')
    echo "  ref 完整性：$([ $ref_miss -eq 0 ] && echo 全部可解析 || echo "$ref_miss 个缺失")"
    [ "$wt_n" -gt 0 ] && echo "  worktree：$wt_n 个，$([ $wt_miss -eq 0 ] && echo tip 全部可解析 || echo "$wt_miss 个 tip 缺失")"
  else
    echo "  （源仓库已不在本地，跳过 ref 比对）"
  fi

  if [ "$fail" -eq 0 ] && [ "$ref_miss" -eq 0 ]; then
    total_pass=$((total_pass+1))
  else
    total_fail=$((total_fail+1))
  fi
done

echo
echo "验收结果：$total_pass 个仓库通过 / $total_fail 个仓库有问题"
[ "$total_fail" -eq 0 ] || exit 1
