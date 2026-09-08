# TZ — harbor 底座预检报告

> 日期：2026-09-07（首轮）／2026-09-07 复核重跑
> 方案依据：`docs-research/trajectory-platform/bench-mvp-plan.md` §4 TZ（v1.2）
> 结论：**五项全过，oracle=1 且 nop=0，reward 双源一致 → 检查点 Z 通过**
> 最终配置：**宿主开飞鸟云（全局 + TUN）+ dockerd 走宿主代理 `192.168.5.2:7881`**
> —— 即 `sid-code` 笔记 `2026-08-28-harbor跑前环境三条硬约束复核.md` 记录的那套配置，
> **本轮未对它做任何净改动**

## 〇、首轮的误诊与更正（这一节最重要）

⚠️ **首轮预检是在「宿主代理软件没开」的状态下做的**，据此写出的两条根因结论
**已被推翻**。留下这一节是因为误诊过程本身是有价值的教训。

| 首轮结论 | 实际 | 教训 |
|---|---|---|
| 🔴「dockerd 的 proxy drop-in 指向死端口，**是配置错了**」→ 停用它 + 加 registry mirror | **配置一直是对的**。`192.168.5.2:7881` 正是飞鸟云的端口，只是当时代理软件没启动 | **「端口没人监听」不等于「配置写错了」。** 先问「这个端口本该由谁监听、它启动了吗」，再改配置 |
| 🔴「`registry-1.docker.io` 直连不通，docker.io 整体不可达」 | 直连本就不该通（DNS 被污染到 `199.59.150.45`，Twitter 段）。**正确路径就是走代理** —— 代理一开，VM 内 `-x` 探测立得 401 | 把「直连不通」当成「整体不可达」，会去找绕路（mirror），而正解是走既有代理 |

**误诊的代价**：我改了两处共享 VM 配置（停用 drop-in、加 daocloud mirror）。
虽然当时确实让 pull 通了，但那是**用绕路掩盖了「代理没开」这个真因** ——
一旦别人开着代理跑，配置就与团队笔记记录的基线不一致了。

**已完全还原**（与 `tz-backup/` 下的备份逐字节 `diff` 一致）：

```
/etc/docker/daemon.json                              ✅ 与备份一致（mirror 已撤）
/etc/systemd/system/docker.service.d/http-proxy.conf ✅ 与备份一致（drop-in 已恢复）
```

**本轮对 VM 的净改动：零。** 最终跑通用的就是笔记里那套配置。

⚠️ **另一处误诊**：我用 `lib/detect-proxy-port.sh 192.168.5.2` 在**宿主上**跑，
得「无可用代理」，与 VM 内手测 401 矛盾。原因是**宿主到不了 `192.168.5.2`** ——
那是 VM 眼里的宿主网关，只在 VM 内有意义。
**「VM 视角」的探测必须在 VM 里跑**，在宿主上带这个参数跑出来的是假阴性。

## 一、结论速览

| # | 检查项 | 结果 | 备注 |
|---|---|---|---|
| ① | `docker compose` 插件在 CLI 搜索路径内 | ✅ 通过 | `Docker Compose version 5.0.2` |
| ② | 能拉到镜像 | ✅ 通过 | 经 dockerd 代理，`ubuntu:24.04` 1.9s、`oven/bun:1.3.14` 正常 |
| ③ | harbor 本体可用且版本带上界 | ✅ 通过 | `0.22.0`；上界 `harbor>=0.22.0,<0.23` 声明在 sid-code 侧 |
| ④ | 遥测已显式关闭 | ✅ 通过（需显式设） | 见 §2 R-2 |
| ⑤ | `oracle` 在 hello-world 上 reward=1 | ✅ 通过 | **第 3 次才过**，前两次是 uv 下载抖动，见 §2 R-4 |
| 附加 | `nop` 负向基线 reward=0 | ✅ 通过 | v1.2 强制要求，见 §3 |

## 二、四条要带进后续 Task 的实测结论

### R-1 ✅ docker.io 必须走 dockerd 代理，不能直连（与团队笔记一致）

**这条不是本轮新发现，而是复核确认了笔记的结论。**

根因是两件事叠加（引 `2026-08-28-harbor跑前环境三条硬约束复核.md`）：

1. `registry-1.docker.io` 的 DNS 被**污染**到 `199.59.150.45`（Twitter 段）——
   **TCP 握手成功但 TLS 无响应**。所以 `nc -z` 会报 OPEN，**连通性探测会骗你**。
2. **lima 把宿主代理写进 `/etc/environment`，而 systemd 服务不读那个文件** ——
   于是 VM 里 `curl` 走代理一切正常、`dockerd` 却完全没代理。
   > 这就是「VM 里 curl 得通、`docker pull` 超时」这个矛盾形态的来源：
   > **它们走的不是同一条路。**

生效中的配置（`/etc/systemd/system/docker.service.d/http-proxy.conf`，
落在 `/dev/vda1` ext4 上，**跨 VM 重启保留**）：

```
HTTP_PROXY=http://192.168.5.2:7881
HTTPS_PROXY=http://192.168.5.2:7881
NO_PROXY=localhost,127.0.0.1,192.168.5.0/24,10.0.0.0/8,172.16.0.0/12,*.local,
         ghcr.io,pkg-containers.githubusercontent.com,*.githubusercontent.com
```

⚠️ **`ghcr.io` 与 `*.githubusercontent.com` 刻意进 `NO_PROXY`**：两条路都通，
但实测直连 blob **3.3 MB/s** vs 走代理 **2.6 MB/s**，而 terminal-bench 全部镜像
都在 ghcr（单个 260MB+）。**只有 `docker.io` 需要代理。**

**本轮验证**（先 `docker rmi` 清掉镜像，确保是真拉）：

```
docker pull ubuntu:24.04     → Downloaded newer image，1.9s  ✅
docker pull oven/bun:1.3.14  → Downloaded newer image        ✅（TZ ② 判据）
```

⚠️ **这一层只作用于 dockerd 自己拉镜像，不会传给容器里的进程。**
容器要不要走代理是另一件事，答案见 R-4。

### R-2 ⚠️ harbor 遥测默认开启，必须显式关

`HARBOR_TELEMETRY` 实测为**空**。已回源码核对（`harbor/telemetry.py:45`
`_DISABLED_VALUES = {"0","false","no","off","disabled"}`、`:480` `_telemetry_disabled()`）：
**空值不在这个集合里 → 遥测是开的**，发往 `us.i.posthog.com`。

我们的 `instruction.md` 含私有仓库信息，**必须关**。沿用 harbor README 的规矩：
**写进命令本身，不写进「注意事项」**（写在注意事项里没人看）。

### R-3 🔴 harbor 的 jobs 目录（`-o`）必须落在 `$HOME` 之下

**这条是本轮真正的新发现，方案与 harbor README、团队笔记都没有记录。**

**症状**：`-o /tmp/tz-check` 跑 oracle，`Trials=0 / Exceptions=1`：

```
RewardFileNotFoundError: No reward file found at .../verifier/reward.txt or .../verifier/reward.json
```

**误导性**：报错长得像「verifier 没跑 / test.sh 挂了」。但 verifier **跑得非常正常**：

```bash
# 宿主侧：verifier/ 目录根本不存在
find /tmp/tz-check3 -type f     # 只有 job.log / result.json / config.json / trial.log

# VM 内的同一路径：reward.txt、ctrf.json、test-stdout.txt 全都在
colima ssh -p swebench -- cat /private/tmp/tz-check3/*/*/verifier/reward.txt   # → 1
```

**根因**：harbor 的 docker environment 声明
`capabilities.mounted=True`（`environments/docker/docker.py:303`），于是
`verifier/verifier.py:203` 的 `if not self.environment.capabilities.mounted:`
分支**整个跳过 download** —— 它假定 trial 目录是 bind mount，容器写完宿主直接能读。

而这台 colima 的 `mounts: []`，VM 内实际只挂了一个 virtiofs：

```
mount0 on /Users/zhourusheng type virtiofs (rw,relatime)
```

**宿主 `/tmp` 不在 VM 里**。`-v /private/tmp/xxx:/logs` 挂的是 **VM 自己的
`/private/tmp`**（owner `root root`，与宿主同名不同源）。

**处置**：jobs 目录必须在 `$HOME` 之下。已用探针确认 `$HOME` 双向同源。
已固定进 `common.assert_jobs_dir_ok()` 与单测。

🔴 **T5/T7 的 `-o` 不许用 `/tmp`。** 失败形态 `RewardFileNotFoundError` 指向的是
「reward 文件没写」这个**错误方向**，真因是「写了但宿主看不见」。

### R-4 ⚠️ 容器内 uv 下载有已知残余失败率（**不是已解决问题**）

`oracle` **前两次拿 0 分**（但 `Exceptions=0`）。读 `verifier/test-stdout.txt` 得真因：

```
downloading uv 0.9.7 aarch64-unknown-linux-gnu
curl: (35) OpenSSL SSL_connect: SSL_ERROR_SYSCALL in connection to github.com:443
failed to download https://github.com/astral-sh/uv/releases/download/0.9.7/...tar.gz
/tests/test.sh: line 11: uvx: command not found
```

第 3 次原地重跑即得 reward=1。**这与团队笔记的记录完全吻合**
（`2026-08-28-harbor跑前环境三条硬约束复核.md`）：

> **残余误差不掩饰**：`-n 1` 仍有 **1/10** 的 verifier 会坏。真治法是一台网络干净
> 的机器，或在镜像里预装 uv（**要改上游任务，破坏「同题同 verifier」可比性，不做**）。
> **在本机上这是已知残余误差，不是已解决问题。**

**本轮独立复现了这个量级**：容器内连拉 uv tarball 5 次 → **3 成 2 败**
（成功 20300539 字节 / 失败 curl 000）。`curl: (35)` 也正是笔记记录的
「三个 curl 错误码（7/18/35）」之一 —— 那个多域名多错误码的形态是**带宽争抢的指纹**，
不是某个域名被墙。

**容器内的网络形态（本轮新测细节）**：容器 DNS 指向 `192.168.5.1`，
`github.com` 解析为 `198.19.0.4` —— 这是**飞鸟云 TUN 的 fake-ip**。fake-ip
只在 TUN 拦得到的地方有意义，所以容器内直连**能否成功取决于抖动**。

⚠️ **两条已被笔记明确否决的「优化」，不要重新发明**：

| 试过的做法 | 结果 |
|---|---|
| ❌ 容器走宿主 HTTP 代理（注入 `*_proxy`） | 小规模探针 14/14 全绿，**真跑却是四种配置里最差的 6/10**。「探针全绿」不能外推到真实 run |
| ❌ squid 缓存代理（共享 uv tarball） | 下载走 HTTPS，squid 只看得到 `CONNECT` 隧道、缓存不了内容；要缓存就得 MITM + 往每个任务镜像塞 CA ——**改被测环境迁就基础设施，不做** |

🔴 **`-n 1` 是硬要求**（笔记的核心产出）：四轮 `nop` 对照，
`-n 1` 直连 **1/10** 坏、`-n 3` 直连 **4/10**、`-n 3`+代理 **6/10**。
**并发是主因，代理是加重项。**

⚠️ **给 T5/T7 的判读经验**：`Exceptions=0` 但 `reward=0` 时，
**第一件事是读 `verifier/test-stdout.txt`**，判据用笔记那条 grep：

```bash
grep -E "uv: command not found|failed to download|curl: command not found" <trial>/verifier/test-stdout.txt
```

命中 = 基础设施抖动，**原地重跑**，不要去动 task。
另可直接用 harbor 侧的 `verifier_health.py`（它的 `agent_started` / `llm_fatal`
判据正是为分辨「真 0 分 / 假 0 分」写的），**别自己重写**。

## 三、门禁结果（TZ ⑤ + v1.2 负向基线）

```bash
HW=$(ls -d ~/.cache/harbor/tasks/packages/hello-world/hello-world/*/ | head -1)
RUNS=bench/v0.2-mini/reports/tz-runs        # ⚠️ 必须在 $HOME 之下（R-3）

HARBOR_TELEMETRY=0 harbor run -p "$HW" -a oracle -n 1 \
  -o "$RUNS/oracle" --verifier-timeout-multiplier 6 -y
HARBOR_TELEMETRY=0 harbor run -p "$HW" -a nop -n 1 \
  -o "$RUNS/nop" --verifier-timeout-multiplier 6 -y
```

| agent | Trials | Exceptions | 源 A `result.json` | 源 B `reward.txt` | 双源一致 | ctrf 摘要 |
|---|---|---|---|---|---|---|
| `oracle` | 1 | 0 | **1.0** | **1** | ✅ | `tests:2 passed:2 failed:0` |
| `nop` | 1 | 0 | **0.0** | **0** | ✅ | `tests:2 passed:0 failed:2` |

**为什么两条都要跑**（v1.2 要求，本轮实测印证了必要性）：
`nop` 的 ctrf 显示 **2 个测试真的跑了、真的 fail**。这一条排除了 R1
「verifier 恒返 1」—— 只跑 oracle 拿到 1 是**无法区分**「底座正常」与
「verifier 恒返 1」的，而后者会让后面每条 task 都假绿。

⚠️ **reward 读取路径的坑已实测确认**（§3.8-D）：

```python
d['verifier_result']['rewards']['reward']  # → 1.0   ✅ 正确路径
d['verifier_result'].get('reward')         # → None  ❌ 常见错写法（两个 agent 均为 None）
```

写错这个路径的形态是「所有 task 都 None/0 分」，**且不报错**。

⚠️ **`--verifier-timeout-multiplier 6` 不是可选的**：hello-world 的 verifier
默认只给 120s，而它要 `apt-get update` + 装 uv。不加的形态是 `VerifierTimeoutError`。

⚠️ **不能看退出码**：`harbor run` 失败时退出码仍是 0（README 已记录，
本轮六次失败运行全部复现）。判据只有表里的 `Trials` / `Exceptions` 两个数。

## 四、环境指纹

供后续复算与《六、必须披露的局限》第 11 条引用。**换架构结果不保证可比。**

| 项 | 值 |
|---|---|
| 日期（UTC） | 2026-09-07T09:48Z（复核重跑） |
| harbor | 0.22.0（上界 `harbor>=0.22.0,<0.23`，声明于 sid-code 侧 `pyproject.toml:27`） |
| docker CLI / daemon | 29.1.4 / 28.4.0 |
| docker compose | 5.0.2 |
| bun（宿主） | 1.3.14 |
| 宿主 | Darwin 25.6.0 / **arm64** |
| 容器运行时 | colima **profile=swebench**，vz + virtiofs，aarch64 |
| VM OS / 资源 | Ubuntu 24.04.2 LTS / 8 CPUs / 15.58 GiB |
| **宿主代理** | **飞鸟云 全局 + TUN，`127.0.0.1:7881`**（scutil HTTP/HTTPS/SOCKS 均启用） |
| **dockerd 代理** | `192.168.5.2:7881`，`ghcr.io` 等在 `NO_PROXY`（团队笔记的基线配置，未改动） |
| registry mirror | **无**（首轮加过 daocloud，已撤回） |
| 遥测 | `HARBOR_TELEMETRY=0`，写进每条命令 |
| trajectory-platform HEAD | `216c399` |

⚠️ **`colima status` 不带 `-p swebench` 会报「colima is not running」** ——
本机 docker 由 `swebench` profile 提供，默认 profile 确实没跑。**这是假阴性。**

## 五、留档产物

| 路径 | 内容 |
|---|---|
| `tz-runs/oracle/2026-09-07__17-47-12/…__izeCyX5/` | oracle 门禁的完整 trial（在**最终正确配置**下跑出） |
| `tz-runs/nop/2026-09-07__17-48-07/…__7EDGBU5/` | nop 负向基线的完整 trial |
| `tz-backup/daemon.json.bak` | 改动前的 VM `daemon.json` —— 已用它验证还原 |
| `tz-backup/http-proxy.conf.bak` | 改动前的 dockerd 代理 drop-in —— 已用它验证还原 |

> 首轮（误诊配置下）的 run 产物已删除，避免与最终证据混淆。

## 六、已知坑（未撞上但要记住）

- **`host.docker.internal` 在 colima 下不可解析**（README ③）。要用 `192.168.5.2`
  （本机 dockerd 带 `--host-gateway-ip=192.168.5.2`）。T4 要求运行期
  `--network none`，正常不该依赖它。
- **`Error getting dataset` 先复跑一次**（README ④ / 笔记 §14.5：走官方 Supabase
  注册中心，实测 15 次采样 14 通 1 挂约 7%，**且 harbor 那层没有任何重试**，
  `registry/client/harbor/harbor.py:128` 把原始异常吞掉）。它长得像「数据集名字写错」。
  本方案走本地 `-p` 路径模式理论上不撞，撞上说明配置退化成走远端了。
- **`-n` 并发直接决定 verifier 坏掉的比例**（见 R-4）。全程 `-n 1`。
- **对照实验每次只许动一个变量**（笔记 §14.4 的教训：「`-n 3`+代理 6/10」vs
  「`-n 1` 直连 1/10」两个变量同时变了，补跑 `-n 3` 直连 4/10 才分开归因）。

## 七、验收对照

方案 §4.9 对 TZ 的验收是：**oracle=1 且 nop=0**，反向自证是「只跑 oracle 不算通过」。

| 验收项 | 结果 |
|---|---|
| 五项预检全过 | ✅ |
| `oracle` = 1 | ✅ 1.0（第 3 次；前两次为 uv 下载抖动，属已知残余误差） |
| `nop` = 0 | ✅ 0.0，且 ctrf 证明测试真跑真 fail |
| reward 双源一致 | ✅ 两个 agent 各自两源都一致 |
| 报告落盘含环境指纹 | ✅ §4 |
| VM 配置无净改动 | ✅ 两份配置与备份逐字节 `diff` 一致 |

**→ 检查点 Z 通过。**
