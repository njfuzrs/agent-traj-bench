# TZ — harbor 底座预检报告

> 日期：2026-09-07
> 方案依据：`docs-research/trajectory-platform/bench-mvp-plan.md` §4 TZ（v1.2）
> 结论：**五项全过，oracle=1 且 nop=0，reward 双源一致 → 可以开工灌数据**

## 一、结论速览

| # | 检查项 | 结果 | 备注 |
|---|---|---|---|
| ① | `docker compose` 插件在 CLI 搜索路径内 | ✅ 通过 | `Docker Compose version 5.0.2` |
| ② | 能拉到镜像 | ⚠️ **初始不通，已修复** | 见 §2「修复记录 R-1」 |
| ③ | harbor 本体可用且版本带上界 | ✅ 通过 | `0.22.0`，上界声明在 sid-code 侧 |
| ④ | 遥测已显式关闭 | ⚠️ **初始未设，已确认处置方式** | 见 §2「修复记录 R-2」 |
| ⑤ | `oracle` 在 hello-world 上 reward=1 | ✅ 通过 | 另有 **R-3 / R-4** 两处环境坑，见 §2 |
| 附加 | `nop` 负向基线 reward=0 | ✅ 通过 | v1.2 强制要求，见 §3 |

**四项检查在首次执行时不成立**（②③⑤各自的成因互不相同），全部定位到根因并修复。
这正是 TZ 单列的价值：**这四个坑的失败形态都伪装成「我们的 task 有问题」** ——
若不做 TZ 直接进 T1，后面每一个 `reward=0` 都无法归因。

## 二、修复记录（四处，均已实测验证）

### R-1 🔴 `docker pull` 全线失败 —— dockerd 指向一个死掉的代理端口

**症状**：

```
Error response from daemon: failed to resolve reference "docker.io/oven/bun:1.3.14":
proxyconnect tcp: dial tcp 192.168.5.2:7881: connect: connection refused
```

**根因**（两件事叠加，缺一不成立）：

1. VM 内 dockerd 的 systemd drop-in（`/etc/systemd/system/docker.service.d/http-proxy.conf`）
   写死了宿主代理端口 `7881`，而**宿主上现在没有任何代理在跑** ——
   `scutil --proxy` 三个 Enable 全是 0，`lsof` 在 7890/7891/7881/1087/8888/10808
   上都没有监听进程。用 sid-code 的 `lib/detect-proxy-port.sh` 从宿主侧与
   VM 侧（`192.168.5.2`）各探一次，两次都返回「无可用代理」。
2. `registry-1.docker.io` **直连也不通**：宿主 `code=000`（20s 超时），
   VM 内 `--noproxy '*'` 同样 `code=000`。所以 harbor README ② 给的
   「宿主搬运」绕路在这台机器上**同样不可行** —— 宿主自己也拉不到。

⚠️ **这条与 README ② 记录的形态不同**，值得单独记一笔：README 的场景是
「宿主有代理、VM 内 dockerd 没配代理」，处置是**给 dockerd 加代理**；
这里是反过来的 —— **dockerd 配了代理、而那个代理已经不存在了**。
照 README 加代理会让问题更糟。

**处置**（改动两处，均在 VM 内，已备份到 `tz-backup/`）：

```bash
# ① 停用指向死端口的 drop-in（改名保留，可随时回滚，不删除）
colima ssh -p swebench -- sudo mv \
  /etc/systemd/system/docker.service.d/http-proxy.conf \
  /etc/systemd/system/docker.service.d/http-proxy.conf.disabled-tz

# ② 加 registry mirror —— VM 内实测 daocloud 可达（401 = 连上了）
#    /etc/docker/daemon.json 增加：
#    "registry-mirrors": ["https://docker.m.daocloud.io"]
colima ssh -p swebench -- sudo systemctl daemon-reload
colima ssh -p swebench -- sudo systemctl restart docker
```

选 mirror 而非代理的依据是 VM 内的实证探测：

| 目标 | VM 内直连结果 |
|---|---|
| `registry-1.docker.io` | **000（不通）** |
| `docker.m.daocloud.io` | **401（通）** |
| `ghcr.io` | 401（通） |
| `registry.cn-hangzhou.aliyuncs.com` | 401（通） |
| `archive.ubuntu.com` / `pypi.org` / `astral.sh` | 200（通） |

**验证**：

```
docker pull ubuntu:24.04      → Status: Downloaded newer image ✅
docker pull oven/bun:1.3.14   → Status: Downloaded newer image ✅（TZ ② 判据）
docker build（FROM ubuntu:24.04）→ Successfully built ✅
```

**顺带清掉一个坏镜像**：本地那个 `ubuntu:24.04` 是**残缺条目** ——
manifest 在、blob 不在，`docker build` 报
`NotFound: content digest sha256:95fa...: not found`，而**它长得像网络错误**。
已 `docker rmi` 后重拉。

⚠️ **重启 daemon 的影响已确认可接受**：重启前 `docker ps` 为空（无运行中容器），
四个已退出的容器（含 `sid-swebench-proxy`）不受影响。

### R-2 ⚠️ harbor 遥测默认开启，环境里未设开关

`HARBOR_TELEMETRY` 实测为**空**。已回源码核对
（`harbor/telemetry.py:45` `_DISABLED_VALUES = {"0","false","no","off","disabled"}`、
`:480` `_telemetry_disabled()`）：**空值不在这个集合里 → 遥测是开的**，发往
`us.i.posthog.com`。

我们的 `instruction.md` 含私有仓库信息，**必须关**。处置方式沿用 harbor README
的规矩：**写进命令本身，不写进「注意事项」**（写在注意事项里没人看）。
本报告所有命令均以 `HARBOR_TELEMETRY=0` 前缀执行，T5/T7 的脚本同样照此写。

### R-3 🔴 `RewardFileNotFoundError` —— colima 只挂载 `$HOME`，`/tmp` 不在 VM 里

**这是本次 TZ 最值得记的一条，harbor README 与方案文档都没有记录。**

**症状**：`-o /tmp/tz-check` 跑 oracle，`Trials=0 / Exceptions=1`：

```
RewardFileNotFoundError: No reward file found at .../verifier/reward.txt or .../verifier/reward.json
```

**误导性**：这个报错长得像「verifier 没跑 / test.sh 挂了」。但逐项排查后发现
**verifier 跑得非常正常**：

```bash
# 宿主侧：verifier/ 目录根本不存在
find /tmp/tz-check3 -type f     # 只有 job.log / result.json / config.json / trial.log

# VM 内的同一个路径：reward.txt、ctrf.json、test-stdout.txt 全都在
colima ssh -p swebench -- cat /private/tmp/tz-check3/*/*/verifier/reward.txt
# → 1
colima ssh -p swebench -- cat /private/tmp/tz-check3/*/*/verifier/ctrf.json
# → {'tests': 2, 'passed': 2, 'failed': 0, ...}
```

**根因**：harbor 的 docker environment 声明
`capabilities.mounted=True`（`environments/docker/docker.py:303`），于是
`verifier/verifier.py:203` 的 `if not self.environment.capabilities.mounted:`
分支**整个跳过 download** —— 它假定 trial 目录是 bind mount，容器写完宿主直接就能读到。

而这台 colima 的 `mounts: []`，VM 内实际只挂了一个 virtiofs：

```
mount0 on /Users/zhourusheng type virtiofs (rw,relatime)
```

**宿主 `/tmp` 不在 VM 里**。docker 是 VM 内的原生 dockerd，
`-v /private/tmp/xxx:/logs` 挂的是 **VM 自己的 `/private/tmp`**（owner `root root`，
与宿主同名不同源）。所以 verifier 的产出全部写在 VM 里，宿主永远读不到。

**处置**：**jobs 目录必须落在 `$HOME` 之下**。已用探针确认 `$HOME` 双向同源：

```bash
echo host-written > ~/tmp-mount-probe/probe.txt
colima ssh -p swebench -- cat /Users/zhourusheng/tmp-mount-probe/probe.txt
# → host-written  ✅ 同源
```

改用 `-o bench/v0.2-mini/reports/tz-runs/...`（在 `$HOME` 下）后异常立即消失。

🔴 **这条要带进 T5/T7**：`t5-gate.sh` / `t7-baseline.sh` 的 `-o` **不许用 `/tmp`**。
失败形态是 `RewardFileNotFoundError`，它指向的是「reward 文件没写」这个**错误方向**，
真正的原因是「写了但宿主看不见」。

### R-4 ⚠️ oracle 首次拿到 0 分 —— github.com 间歇性不可达

修掉 R-3 后 oracle 仍是 `reward=0`（但 `Exceptions=0`）。读 `verifier/test-stdout.txt`
拿到真因，**不在我们这一侧**：

```
downloading uv 0.9.7 aarch64-unknown-linux-gnu
curl: (7) Failed to connect to github.com port 443 after 32445 ms: Couldn't connect to server
failed to download https://github.com/astral-sh/uv/releases/download/0.9.7/uv-...tar.gz
/tests/test.sh: line 8: /root/.local/bin/env: No such file or directory
/tests/test.sh: line 11: uvx: command not found
```

hello-world 的 `test.sh` 要从 github release 装 uv。宿主侧连续探 5 次
`https://github.com`：**000 / 000 / 000 / 000 / 200** —— 间歇性可达。
release 真实下载域连探 3 次全 200 后原地重跑，oracle 即拿到 1。

**判读经验**（带进 T5）：`Exceptions=0` 但 `reward=0` 时，
**第一件事是读 `verifier/test-stdout.txt`**，不要先怀疑 task。
本例的 0 分完全是外网抖动，与 task 质量无关 —— 这正是 §7.2「先怀疑基础设施」的实例。

## 三、门禁结果（TZ ⑤ + v1.2 负向基线）

两条命令，`hello-world` 本地 `path` 模式（= T3 产物将使用的同一模式）：

```bash
HW=$(ls -d ~/.cache/harbor/tasks/packages/hello-world/hello-world/*/ | head -1)

HARBOR_TELEMETRY=0 harbor run -p "$HW" -a oracle -n 1 \
  -o bench/v0.2-mini/reports/tz-runs/oracle --verifier-timeout-multiplier 6 -y

HARBOR_TELEMETRY=0 harbor run -p "$HW" -a nop -n 1 \
  -o bench/v0.2-mini/reports/tz-runs/nop --verifier-timeout-multiplier 6 -y
```

| agent | Trials | Exceptions | reward（源 A：`result.json`） | reward（源 B：`reward.txt`） | 双源一致 | ctrf 摘要 |
|---|---|---|---|---|---|---|
| `oracle` | 1 | 0 | **1.0** | **1** | ✅ | `tests:2 passed:2 failed:0` |
| `nop` | 1 | 0 | **0.0** | **0** | ✅ | `tests:2 passed:0 failed:2` |

**为什么两条都要跑**（v1.2 的要求，本次实测印证了它的必要性）：
`nop` 的 ctrf 显示 **2 个测试真的跑了、真的 fail**。这一条排除了 R1
「verifier 恒返 1」—— 只跑 oracle 拿到 1 是**无法区分**「底座正常」与
「verifier 恒返 1」的，而后者会让后面每条 task 都假绿。

⚠️ **reward 读取路径的坑已实测确认**（§3.8-D）：

```python
d['verifier_result']['rewards']['reward']  # → 1.0   ✅ 正确路径
d['verifier_result'].get('reward')         # → None  ❌ 常见错写法
```

写错这个路径的形态是「所有 task 都 None/0 分」，**且不报错**。T5 的一致性
核对必须读嵌套的 `rewards` 字典。

⚠️ **`--verifier-timeout-multiplier 6` 不是可选的**：hello-world 的 verifier
默认只给 120s，而它要 `apt-get update` + 装 uv。实测本次 oracle 单 trial
耗时 **2m18s**，已超默认值。不加的形态是 `VerifierTimeoutError`。

⚠️ **不能看退出码**：`harbor run` 失败时退出码仍是 0（README 已记录，本次
四次失败运行全部复现）。判据只有表里的 `Trials` / `Exceptions` 两个数。

## 四、环境指纹

供后续复算与《六、必须披露的局限》第 11 条引用。**换架构结果不保证可比。**

| 项 | 值 |
|---|---|
| 日期（UTC） | 2026-09-07T09:04:20Z |
| harbor | 0.22.0（上界 `harbor>=0.22.0,<0.23`，声明于 sid-code 侧 `pyproject.toml:27`） |
| docker CLI | 29.1.4（build 0e6fee6c52） |
| docker daemon | 28.4.0 |
| docker compose | 5.0.2 |
| bun（宿主） | 1.3.14 |
| 宿主 | Darwin 25.6.0 / **arm64** |
| 容器运行时 | colima **profile=swebench**，vz + virtiofs，aarch64 |
| VM OS | Ubuntu 24.04.2 LTS |
| VM 资源 | 8 CPUs / 15.58 GiB |
| registry mirror | `https://docker.m.daocloud.io`（本次新增，见 R-1） |
| 遥测 | `HARBOR_TELEMETRY=0`，写进每条命令 |
| trajectory-platform HEAD | `e7e4631` |

⚠️ **`colima status` 不带 `-p swebench` 会报「colima is not running」** ——
本机 docker 由 `swebench` profile 提供，默认 profile 确实没跑。
这是个假阴性，排查时别被它带偏。

## 五、留档产物

| 路径 | 内容 |
|---|---|
| `tz-runs/oracle/2026-09-07__17-00-09/…__WbxLrgN/` | oracle 门禁的完整 trial（`result.json` / `verifier/reward.txt` / `ctrf.json`） |
| `tz-runs/nop/2026-09-07__17-02-55/…__NnTLhSD/` | nop 负向基线的完整 trial |
| `tz-backup/daemon.json.bak` | 改动前的 VM `daemon.json`（回滚用） |
| `tz-backup/http-proxy.conf.bak` | 改动前的 dockerd 代理 drop-in（回滚用；VM 内原文件已改名为 `.disabled-tz`） |

## 六、已知坑（未撞上但要记住）

- **`host.docker.internal` 在 colima 下不可解析**（README ③）。本方案 T4 要求运行期
  `--network none`，正常不该依赖它；要用就用 `192.168.5.2`（= host-gateway，
  本机 dockerd 已带 `--host-gateway-ip=192.168.5.2`）。
- **`Error getting dataset` 先复跑一次**（README ④：约 7% 概率且无重试）。
  本方案走本地 `-p` 路径模式理论上不撞，撞上说明配置退化成走远端了。
- **`-n` 并发直接决定 verifier 坏掉的比例**（README ⑤）。慢网络下必须 `-n 1`。
  本次 TZ 全程 `-n 1`。
- **外网抖动会伪装成 task 质量问题**（本次 R-4 实证）。T5 遇到 `reward=0`
  且 `Exceptions=0` 时，先读 `verifier/test-stdout.txt`。

## 七、验收对照

方案 §4.9 对 TZ 的验收是：**oracle=1 且 nop=0**，反向自证是「只跑 oracle 不算通过」。

| 验收项 | 结果 |
|---|---|
| 五项预检全过 | ✅（②④⑤ 修复后过，过程见 §2） |
| `oracle` = 1 | ✅ 1.0 |
| `nop` = 0 | ✅ 0.0，且 ctrf 证明测试真跑真 fail |
| reward 双源一致 | ✅ 两个 agent 各自两源都一致 |
| 报告落盘含环境指纹 | ✅ 本文件 §4 |

**→ 检查点 Z 通过，可以进入 T0。**
