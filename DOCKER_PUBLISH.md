# 发布镜像到 Docker Hub

目标仓库为 `ppken/codex-reset-notifier`。当前已发布版本为 `1.1.0`，`latest` 指向同一镜像。首次发布章节保留 `1.0.0` 作为初版示例。每次发布使用一个新的版本标签，并同时更新 `latest`；正式服务器推荐固定版本标签，便于回滚。

## 1.1.0 发布记录（2026-10-09）

- Docker Hub：[ppken/codex-reset-notifier](https://hub.docker.com/r/ppken/codex-reset-notifier/tags?name=1.1.0)
- 标签：`1.1.0`、`latest`；已推送并核对远端摘要一致。
- 运行平台：`linux/amd64`；镜像索引另含构建证明，不代表额外运行平台。
- 内容：默认推送公告中文译文，缺失时回退原文；`INCLUDE_TWEET_TRANSLATION=false` 关闭正文展示。
- 验证：Python 3.12 镜像内 38 项离线测试通过，确认非 root 运行和默认译文开关，镜像未包含 `.env` 或运行状态文件。

镜像索引摘要：

```text
sha256:bd780b38029aae75469c0789d857cc7a0578a210249f28619e802897ecb01df3
```

跟随 `latest` 的服务器在部署目录执行：

```bash
docker compose pull notifier
docker compose up -d --no-build notifier
```

固定版本部署请先把 `image` 改为 `ppken/codex-reset-notifier:1.1.0`，再执行以上命令。保留原 `.env` 和 `data/` 挂载。

## 首次发布

在 Docker Hub 的 `ppken` 命名空间下创建 `codex-reset-notifier` 仓库，按需要选择公开或私有。启动 Docker Desktop（Linux containers）或 Linux Docker Engine，然后在项目根目录登录、构建：

```bash
docker login
docker build --pull --platform linux/amd64 -t ppken/codex-reset-notifier:1.0.0 -t ppken/codex-reset-notifier:latest .
```

此流程生成 `linux/amd64` 镜像，适用于 x86_64 Linux 服务器；ARM64 服务器需要另行构建对应平台镜像。登录时在本机完成认证，不把密码或令牌放入源码、Dockerfile 或命令历史。

推送前，在构建好的 Python 3.12 镜像内离线运行测试。Linux/macOS：

```bash
docker run --rm --network none --mount "type=bind,source=$(pwd)/tests,target=/app/tests,readonly" ppken/codex-reset-notifier:1.0.0 python -m unittest discover -s tests -v
```

Windows PowerShell：

```powershell
docker run --rm --network none --mount "type=bind,source=$($PWD.Path)\tests,target=/app/tests,readonly" ppken/codex-reset-notifier:1.0.0 python -m unittest discover -s tests -v
```

测试通过后，先推送版本标签，再推送 `latest`，最后检查远端摘要：

```bash
docker push ppken/codex-reset-notifier:1.0.0
docker push ppken/codex-reset-notifier:latest
docker buildx imagetools inspect ppken/codex-reset-notifier:1.0.0
docker buildx imagetools inspect ppken/codex-reset-notifier:latest
```

两次推送都应成功退出，远端检查显示的 Digest 应一致。保存版本号和摘要作为发布记录。构建上下文通过 `.dockerignore` 限定运行所需文件，`.env`、状态文件和测试目录不会打包进镜像。

## 服务器首次使用 Hub 镜像

项目自带的 `docker-compose.yml` 使用 `build: .`，用于源码构建。服务器使用 Hub 镜像时，将其中的 `build: .` 替换为以下配置，其余配置（尤其 `./data:/app/data` 挂载）保持不变：

```yaml
    image: ppken/codex-reset-notifier:1.0.0
```

服务器只需要修改后的 `docker-compose.yml`、`.env` 和 `data/`，无需应用源码。私有仓库需先在服务器运行 `docker login`。首次新部署时复制 `.env.example` 为 `.env`，设置 `STATE_FILE=/app/data/state.json`、`DRY_RUN=true` 并填写 Webhook；已有 `.env` 不要覆盖。

公告中文译文默认开启，旧 `.env` 无需补写；如需关闭译文和原文正文，添加 `INCLUDE_TWEET_TRANSLATION=false`。译文缺失时默认回退到公告原文。修改 `.env` 后执行 `docker compose up -d --no-build --force-recreate notifier` 重新加载配置。

以下命令在 Linux 服务器部署目录执行。镜像使用非 root 用户，绑定目录必须允许该用户写入；首次创建空目录后设置属主：

```bash
docker compose pull notifier
mkdir -p data
sudo chown "$(docker run --rm --network none ppken/codex-reset-notifier:1.0.0 id -u)" data
docker compose run --rm --no-deps -e DRY_RUN=true notifier python -m app.main --once
```

检查日志中确实有成功检查结果或消息预览；`--once` 在 API 错误时也可能返回退出码 0，不能仅靠退出码验收。确认预览正常后，将 `.env` 中 `DRY_RUN` 改为 `false`，启动：

```bash
docker compose up -d --no-build notifier
docker compose ps
docker compose logs --tail=100 notifier
```

## 修改代码后的更新发布

当前代码版本已从 `1.0.0` 更新到 `1.1.0`，包含公告中文译文推送与环境变量开关。在开发机项目根目录执行：

```bash
docker build --pull --platform linux/amd64 -t ppken/codex-reset-notifier:1.1.0 -t ppken/codex-reset-notifier:latest .
```

使用前面的容器测试命令，将镜像标签改为 `1.1.0`。测试通过后发布：

```bash
docker push ppken/codex-reset-notifier:1.1.0
docker push ppken/codex-reset-notifier:latest
docker buildx imagetools inspect ppken/codex-reset-notifier:1.1.0
docker buildx imagetools inspect ppken/codex-reset-notifier:latest
```

不要覆盖已经发布的版本标签。若只构建而没有推送，服务器无法获取本次修改。

服务器上把 `docker-compose.yml` 的 `image` 改为 `ppken/codex-reset-notifier:1.1.0`，再执行：

```bash
docker compose pull notifier
docker compose up -d --no-build notifier
docker compose ps
docker compose logs --tail=100 notifier
```

如果服务器选择跟随 `latest`，无需修改标签，但仍必须执行 `pull` 和 `up -d --no-build`；单独 `restart` 不会切换到新镜像。更新时保留 `.env`、`data/state.json` 和原挂载路径，维持单实例，避免丢失去重状态。

需要回滚时，将 `image` 改回上一版本（例如 `1.0.0`），重复 `pull` 和 `up`。保留当前状态文件；若未来版本修改状态格式，应先确认旧版兼容性。

## 发布故障处理

- 拉取基础镜像出现 EOF、超时：检查 Docker Desktop/Engine 的代理、DNS 和 Docker Hub 连通性，恢复后重新执行构建。
- 推送提示 `denied` 或 `unauthorized`：重新执行 `docker login`，确认账号对 `ppken/codex-reset-notifier` 有写权限。
- 推送中断：重新推送同一标签，Docker 会复用已上传层；只有推送成功并核对远端 Digest 后才算发布完成。
- 容器提示状态文件不可写：检查绑定目录及已有状态文件的属主/权限，不要通过删除状态文件解决，否则可能重复通知。
