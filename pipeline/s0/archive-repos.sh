#!/usr/bin/env bash
# archive-repos.sh — 用 git clone --mirror 冻结全部支点仓库的完整 refs
#
# 为什么必须做（bench-curation-design.md §2.6 / §9 Phase 0）：
#   会话的 base_commit 靠「session 时间 → 反查 commit」定位。仓库还在日更，
#   分支清理 / rebase / force-push 都会让相应会话的 base_commit 永久失效。
#   --mirror 才会带上全部 refs（含未合并分支与 worktree 分支的 tip）；
#   只 clone main 等于没归档。
#
# 幂等：已存在的镜像走 remote update，不重新 clone。
#
# 用法：
#   ./archive-repos.sh                      # 归档到默认目录
#   ARCHIVE_DIR=/path ./archive-repos.sh    # 指定归档目录

set -uo pipefail

ARCHIVE_DIR="${ARCHIVE_DIR:-$HOME/Code/_archive/bench-mirrors}"
CODE_ROOT="${CODE_ROOT:-$HOME/Code}"

# 待归档仓库清单。取自 bench 方案 §2.5 的仓库分布表（按 session 数排序），
# 外加同一 Code 根下其余带 .git 的仓库 —— 归档成本极低，漏掉的代价是不可逆的。
REPOS=(
  person/sid-code                    # 支点仓库，L1/L2 主力
  person/docs-research               # L3 数据源
  ruijie/iam-studio-fe               # L4 私有基线
  person/code-graph
  person/claude-code
  person/claude-trace
  person/trajectory-platform
  person/claude-best
  person/claude-code-working
  person/eval-framework
  <私有仓1>
  <私有仓2>
  <私有仓3>
  <私有仓4>
  <私有仓5>
  <私有仓6>
  <私有仓7>
  <私有仓8>
)

mkdir -p "$ARCHIVE_DIR"
MANIFEST="$ARCHIVE_DIR/manifest.tsv"
STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

printf 'repo\tmirror\trefs\tbranches\ttags\thead_commit\thead_date\tarchived_at\n' > "$MANIFEST"

ok=0; skip=0; fail=0
for repo in "${REPOS[@]}"; do
  src="$CODE_ROOT/$repo"
  name="$(echo "$repo" | tr '/' '_')"
  dst="$ARCHIVE_DIR/$name.git"

  if [ ! -d "$src/.git" ]; then
    echo "跳过 $repo（本地不存在）"
    skip=$((skip+1))
    continue
  fi

  if [ -d "$dst" ]; then
    echo "更新 $repo → $dst"
    git -C "$dst" remote update --prune >/dev/null 2>&1 || { echo "  ✗ remote update 失败"; fail=$((fail+1)); continue; }
  else
    echo "归档 $repo → $dst"
    git clone --mirror "$src" "$dst" >/dev/null 2>&1 || { echo "  ✗ clone 失败"; fail=$((fail+1)); continue; }
  fi

  # 镜像默认只有源仓库的 refs。源仓库自身的 remote 分支（origin/*）在 --mirror
  # 下会被带进来，但 worktree 的 HEAD 不是 ref，需要显式确认 tip 可解析。
  refs=$(git -C "$dst" for-each-ref | wc -l | tr -d ' ')
  branches=$(git -C "$dst" for-each-ref --format='%(refname)' refs/heads refs/remotes 2>/dev/null | wc -l | tr -d ' ')
  tags=$(git -C "$dst" for-each-ref --format='%(refname)' refs/tags 2>/dev/null | wc -l | tr -d ' ')
  head_commit=$(git -C "$dst" rev-parse HEAD 2>/dev/null || echo '-')
  head_date=$(git -C "$dst" log -1 --format=%ad --date=short 2>/dev/null || echo '-')

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$repo" "$name.git" "$refs" "$branches" "$tags" "$head_commit" "$head_date" "$STAMP" >> "$MANIFEST"
  echo "  ✓ refs=$refs branches=$branches tags=$tags head=${head_commit:0:8} ($head_date)"
  ok=$((ok+1))
done

echo
echo "归档完成：成功 $ok / 跳过 $skip / 失败 $fail"
echo "归档目录：$ARCHIVE_DIR"
echo "清单：$MANIFEST"
echo
echo "验收（bench 方案 Phase 0）：任取 20 个历史 commit 可 checkout"
echo "  ./verify-archive.sh"
