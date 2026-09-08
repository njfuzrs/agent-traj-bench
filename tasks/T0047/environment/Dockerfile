# T4 生成，勿手改。repo=person/sid-code mode=external
FROM oven/bun:1.3.14
RUN apt-get update && apt-get install -y --no-install-recommends \
        git make python3 ripgrep \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /eval-framework \
 && printf '{"name":"eval-framework","version":"0.1.0","private":true}\n' > /eval-framework/package.json
WORKDIR /repo
COPY repo-snapshot.tar.gz /tmp/
# ② 容器内 git init 重建 base：test.sh 需要 git apply 打 test_patch、
#    以及 git checkout -- tests/ 还原被 agent 动过的测试。且**不带任何历史** ——
#    顺带消除「agent 翻 git log 找答案」这条泄漏路径。
#    -f：见本文件 dockerfile_for() 的 docstring（gitignore 但已入库的文件）
RUN tar -xzf /tmp/repo-snapshot.tar.gz -C /repo \
    && rm /tmp/repo-snapshot.tar.gz \
    && git init -q -b main \
    && git add -A -f \
    && git -c user.email=bench@local -c user.name=bench commit -qm "base state" \
    && bun install --frozen-lockfile
# 运行期 --network none，所以依赖必须在上面这层装好
ENV CI=1
# 判分用的测试命令（从 base 时点的 package.json 读，§3.5）：bun test
