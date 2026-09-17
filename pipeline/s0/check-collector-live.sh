#!/usr/bin/env bash
# check-collector-live.sh — 检查 claude-trace 采集器「跑的代码是不是最新的」
#
# 为什么需要这个（bench-curation-design.md §9.3）：
#   §8.5 记录两个 P0「已完成」，但实测新采会话的 session.traj 里一条 git 状态
#   都没有。根因是 proxy 以 PyInstaller onefile 二进制运行，进程启动于
#   09-04 17:37，而含 P0 的二进制构建于 22:27 —— 启动时代码就进内存了，
#   之后改磁盘不影响已运行的进程，而它从未重启。
#
#   热重载也没兜住：watch-reload.sh 监的是仓库里的 .py 源文件，生产实际跑的是
#   ~/.claude-trace/bin/claude-trace-proxy 二进制。源文件变了二进制没变、
#   二进制重建了 watch 又不监它 —— 两边都没覆盖到。
#
#   hook 侧之所以正常，是因为每次事件都由 Claude Code 新起一个 python3 进程，
#   天然加载最新代码。这解释了「events.jsonl 有而 session.traj 没有」。
#
# 这类故障靠人眼盯不住：进程活着、端口通着、健康检查也绿，唯一的症状是
# 产出数据里缺字段。所以必须机械化检查。
#
# 用法：
#   ./s0/check-collector-live.sh              # 检查，退出码非 0 即有问题
#   ./s0/check-collector-live.sh --self-test  # 反向自证（故意弄红）
#   REPO=/path/to/claude-trace ./check-collector-live.sh
#
# 退出码：0 一切最新；1 运行中的代码已过期（需 claude-trace restart）；2 无法判定

set -uo pipefail

# ─── 反向自证 ───
# §9.0 的规矩：门禁必须故意弄红一次才算交付。这里造三种假象，每种都必须被抓到。
if [ "${1:-}" = "--self-test" ]; then
  echo "=== 反向自证：三类注入缺陷都必须被抓到 ==="
  echo
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  passed=0

  # ① 只有旧字段 metadata.git 的会话，不能算「已生效」
  #    这正是掩盖了本次故障的那个误判。
  mkdir -p "$tmp/legacy/sid-a"
  cat > "$tmp/legacy/sid-a/session.traj" <<'JSONEOF'
{"metadata":{"start_time":"2026-09-05T10:00:00","git":{"sha":"abc","branch":"main","originUrl":"http://x/y.git"}}}
JSONEOF
  if python3 "$(dirname "$0")/_check_traj_git.py" "$tmp/legacy" >/dev/null 2>&1; then
    echo "  [✗ 仍绿] 只有旧字段 metadata.git —— 这就是掩盖故障的那个误判"
  else
    echo "  [✓ 抓到] 只有旧字段 metadata.git，不算已生效"
    passed=$((passed+1))
  fi

  # ② 完全没有 git 字段
  mkdir -p "$tmp/none/sid-b"
  echo '{"metadata":{"start_time":"2026-09-05T10:00:00"}}' > "$tmp/none/sid-b/session.traj"
  if python3 "$(dirname "$0")/_check_traj_git.py" "$tmp/none" >/dev/null 2>&1; then
    echo "  [✗ 仍绿] 完全无 git 字段"
  else
    echo "  [✓ 抓到] 完全无 git 字段"
    passed=$((passed+1))
  fi

  # ③ 有新字段 git_state → 必须放行（否则门禁恒红，同样没有鉴别力）
  mkdir -p "$tmp/good/sid-c"
  cat > "$tmp/good/sid-c/session.traj" <<'JSONEOF'
{"metadata":{"start_time":"2026-09-05T10:00:00","git_state":{"head":"abc","branch":"main","dirty":false}}}
JSONEOF
  if python3 "$(dirname "$0")/_check_traj_git.py" "$tmp/good" >/dev/null 2>&1; then
    echo "  [✓ 放行] 有新字段 git_state，正常通过"
    passed=$((passed+1))
  else
    echo "  [✗ 误报] 有新字段却报红 —— 门禁恒红，失去鉴别力"
  fi

  echo
  echo "自证结果：$passed/3"
  [ "$passed" -eq 3 ] && exit 0 || exit 1
fi

INSTALL_DIR="${INSTALL_DIR:-$HOME/.claude-trace}"
REPO="${REPO:-$HOME/Code/person/claude-trace}"
BINARY="$INSTALL_DIR/bin/claude-trace-proxy"
HOOK_DIR="${HOOK_DIR:-$HOME/.claude/hooks}"

fail=0
warn=0

say_ok()   { echo "  ✓ $*"; }
say_bad()  { echo "  ✗ $*"; fail=$((fail+1)); }
say_warn() { echo "  ! $*"; warn=$((warn+1)); }

# mtime（秒）与可读时间
mtime()  { stat -f '%m' "$1" 2>/dev/null; }
mtimes() { stat -f '%Sm' -t '%Y-%m-%d %H:%M:%S' "$1" 2>/dev/null; }

echo "── ① proxy 进程跑的二进制是否为磁盘上的最新版"

pid="$(pgrep -f "$BINARY" 2>/dev/null | head -1)"
if [ -z "$pid" ]; then
  say_warn "找不到运行中的 proxy 进程（采集器可能未启动）"
else
  # 进程启动时间（epoch 秒）。ps 的 lstart 格式随 locale 变，用 etime 反算更稳。
  etime="$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')"
  # etime 形如 [[dd-]hh:]mm:ss
  secs="$(python3 - "$etime" <<'PY'
import re, sys
t = sys.argv[1]
m = re.match(r'^(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+)$', t)
if not m:
    print(-1)
else:
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    print(d * 86400 + h * 3600 + mi * 60 + s)
PY
)"
  if [ "${secs:-'-1'}" -lt 0 ]; then
    say_warn "无法解析进程运行时长（etime=${etime}）"
  else
    now="$(date +%s)"
    started=$((now - secs))
    bin_mtime="$(mtime "$BINARY")"
    if [ -z "$bin_mtime" ]; then
      say_bad "二进制不存在：$BINARY"
    elif [ "$bin_mtime" -gt "$started" ]; then
      say_bad "运行中的代码已过期 —— 进程启动于 $(date -r "$started" '+%Y-%m-%d %H:%M:%S')，"
      echo "      而二进制构建于 $(mtimes "$BINARY")（晚 $(( (bin_mtime - started) / 60 )) 分钟）"
      echo "      修复：claude-trace restart"
    else
      say_ok "进程启动于 $(date -r "$started" '+%m-%d %H:%M:%S')，晚于二进制构建时间 $(mtimes "$BINARY")"
    fi
  fi
fi

echo "── ② hook 侧部署是否与仓库一致"

for f in collector.py git_state.py; do
  if [ ! -f "$HOOK_DIR/$f" ]; then
    say_bad "$HOOK_DIR/$f 不存在（hook 通道不会采集）"
  elif [ ! -f "$REPO/$f" ]; then
    say_warn "仓库里没有 ${f}，跳过比对"
  elif diff -q "$HOOK_DIR/$f" "$REPO/$f" >/dev/null 2>&1; then
    say_ok "$f 与仓库一致"
  else
    say_bad "$f 与仓库不一致（hook 跑的是旧版）"
  fi
done

echo "── ③ 二进制是否落后于仓库源码"

# proxy 二进制由 proxy.py / builder.py / uploader.py 等打包而成。
# 任一源文件比二进制新 → 二进制该重建了。
newer=""
for f in proxy.py builder.py uploader.py collector.py git_state.py; do
  [ -f "$REPO/$f" ] || continue
  src="$(mtime "$REPO/$f")"
  bin="$(mtime "$BINARY")"
  [ -z "$src" ] || [ -z "$bin" ] && continue
  if [ "$src" -gt "$bin" ]; then
    newer="$newer $f"
  fi
done
if [ -n "$newer" ]; then
  say_warn "这些源文件比二进制新，可能需要重新构建：$newer"
  echo "      注意：改源文件不会影响已在跑的二进制，watch-reload.sh 也监不到二进制"
else
  say_ok "二进制不落后于任何源文件"
fi

echo "── ④ 新采会话是否真的带上了 git 状态（端到端验证）"

# 前三项都是「形式检查」—— 全绿也不代表数据里真有字段。这一项直接看产出。
# 轨迹落在部署目录，不是仓库目录（proxy 的 --output 指向这里）
TRAJ_DIR="${TRAJ_DIR:-$INSTALL_DIR/trajectories/sessions}"
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ ! -d "$TRAJ_DIR" ]; then
  say_warn "本地轨迹目录不存在：${TRAJ_DIR}，跳过端到端验证"
elif ! python3 "$HERE/_check_traj_git.py" "$TRAJ_DIR"; then
  fail=$((fail+1))
fi

echo
if [ "$fail" -gt 0 ]; then
  echo "结果：$fail 项失败，$warn 项警告 —— 采集器跑的不是最新代码"
  echo "多数情况下执行 claude-trace restart 即可（会短暂中断代理）"
  exit 1
fi
if [ "$warn" -gt 0 ]; then
  echo "结果：通过，但有 $warn 项警告"
  exit 0
fi
echo "结果：全部通过"
