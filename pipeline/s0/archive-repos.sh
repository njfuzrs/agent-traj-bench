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

# 待归档仓库清单 —— 与 repo_map.py 的 KNOWN_REPOS 同源，两处读同一个 JSON。
# 原先两处各写一份数组、靠注释保持同源；漏掉一个仓的代价是不可逆的
# （对应会话的 base_commit 从此无从定位），所以判据落到单一文件上。
#
# 仓内默认清单只含已公开披露的 10 个仓。归档要用完整的 18 个：
#   export REPO_MAP_CONFIG=<trajectory-platform>/data/bench-staging/repos.json
REPO_MAP_CONFIG="${REPO_MAP_CONFIG:-$(dirname "$0")/../config/repos.example.json}"
if [ ! -f "$REPO_MAP_CONFIG" ]; then
  echo "✗ 仓库清单不存在：$REPO_MAP_CONFIG" >&2
  exit 1
fi
# ⚠️ 不用 mapfile：macOS 自带的 bash 3.2 没有它，而本脚本的 shebang 是
#   /usr/bin/env bash ⇒ 在采集机上可能解析到 3.2 那份。while read 两处都兼容。
REPOS=()
while IFS= read -r _r; do
  [ -n "$_r" ] && REPOS+=("$_r")
done < <(python3 -c "import json,sys;print('\n'.join(json.load(open(sys.argv[1]))['repos']))" "$REPO_MAP_CONFIG")
if [ "${#REPOS[@]}" -eq 0 ]; then
  echo "✗ 仓库清单为空：$REPO_MAP_CONFIG" >&2
  exit 1
fi
echo "仓库清单：${REPO_MAP_CONFIG}（${#REPOS[@]} 个仓）"

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
    echo "跳过 ${repo}（本地不存在）"
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
