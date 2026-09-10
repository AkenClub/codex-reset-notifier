# Codex 重置通知服务

一个单实例、无入站端口的 Python 服务。它每 15 分钟读取 CodexRunway 的公开重置记录，把可信的排期、额度重置和重置卡发放事件发送到企业微信群机器人。

## 功能范围

- 支持 `global`、`banked`、`global_and_banked` 三类重置事件。
- 支持排期提醒和完成提醒。
- 使用企业微信纯文本（`text`）消息，公告链接直接展示 URL；按 UTF-8 2048 字节上限分批，单条超长事件会截断并标注。
- 使用本地 JSON 文件持久化去重，容器重启后不重复播报。
- 先建立排期与完成记录的关联，再决定是否通知；同一完成事件只发送一次。
- `DRY_RUN=true` 时只输出消息预览，不请求机器人、不写入发送状态。
- 不包含管理页面、数据库、用户系统或服务器端口。

## 本地运行

需要 Python 3.12 或更高版本：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

程序自动读取项目根目录的 `.env`，同名系统环境变量优先。链接直接填写完整 URL，不需要转义，也不要使用 Markdown 链接格式。

Windows PowerShell 可使用以下命令，无需激活虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

先把 `.env` 中的 `DRY_RUN` 设置为 `true`，本地运行时将 `STATE_FILE` 设置为 `./data/state.json`，然后执行一次预览：

```bash
python -m app.main --once
```

PowerShell 未激活虚拟环境时，使用 `.\.venv\Scripts\python.exe -m app.main --once`。

确认消息内容后填写 `WECOM_WEBHOOK_URL`，将 `DRY_RUN` 改为 `false`。正式运行：

```bash
python -m app.main
```

## 使用 Docker 镜像部署（推荐）

直接使用 `docker.io/ppken/codex-reset-notifier:latest`，无需下载源码或安装 Python。以下步骤在已安装 Docker Engine 和 Docker Compose 的 Linux 服务器上执行，适用于 x86_64（`linux/amd64`）平台。

### 1. 创建部署目录和配置

```bash
mkdir -p codex-reset-notifier/data
cd codex-reset-notifier
```

在该目录新建 `docker-compose.yml`，填写：

```yaml
services:
  notifier:
    image: docker.io/ppken/codex-reset-notifier:latest
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      - ./data:/app/data
    init: true
    stop_grace_period: 15s
    logging:
      driver: json-file
      options:
        max-size: 10m
        max-file: "3"
```

在同一目录新建 `.env`，将 `替换为你的机器人key` 改为企业微信群机器人实际 Webhook 中的 key：

```dotenv
WECOM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=替换为你的机器人key
POLL_INTERVAL_SECONDS=900
CONFIDENCE_THRESHOLD=0.90
DISPLAY_TIMEZONE=Asia/Shanghai
STATE_FILE=/app/data/state.json
HTTP_TIMEOUT_SECONDS=15
DRY_RUN=true
```

Webhook 是机器人凭据，请勿提交到 Git 或公开分享。服务不需要开放入站端口，但服务器需要能够访问 CodexRunway 和企业微信接口。

### 2. 拉取镜像并预览

镜像以非 root 用户运行，首次部署时需要让该用户能够写入 `data/`：

```bash
docker compose pull notifier
sudo chown "$(docker run --rm --network none docker.io/ppken/codex-reset-notifier:latest id -u)" data
docker compose run --rm --no-deps -e DRY_RUN=true notifier python -m app.main --once
```

检查输出是否有成功检查结果或消息预览；若出现 API 错误，应先解决网络问题。预览不会发送群消息，也不会写入已发送状态。首次正式启动会处理当前接口返回的符合条件记录，可能包含历史消息。

### 3. 开启通知

确认预览正常后，将 `.env` 中的 `DRY_RUN=true` 改为 `DRY_RUN=false`，然后执行：

```bash
docker compose up -d --no-build notifier
docker compose ps
docker compose logs -f --tail=100 notifier
```

服务启动后立即检查一次，此后默认每 15 分钟检查。按 `Ctrl+C` 退出日志查看不会停止后台服务。

### 4. 更新镜像或停止服务

发布新镜像后，在原部署目录执行：

```bash
docker compose pull notifier
docker compose up -d --no-build notifier
docker compose logs --tail=100 notifier
```

仅执行 `docker compose restart` 不会使用新镜像。更新时保留 `.env`、`data/state.json` 和原挂载路径，只运行一个实例，以保留去重结果。已有源码部署切换镜像时，也应继续使用原来的 `data/`。

停止服务使用 `docker compose down`；绑定挂载的 `data/` 会保留。不要删除状态文件，否则再次启动可能重复发送历史消息。

## 从源码构建部署

`.env` 不提交 Git。部署时执行：

```bash
cp .env.example .env
# 编辑 .env，填写企业微信机器人 Webhook
docker compose up -d --build
docker compose logs -f --tail=100
```

Compose 不映射端口，使用 `./data:/app/data` 保存状态，并配置了单文件 10 MB、最多 3 个文件的 Docker 日志轮转。只部署一个容器实例，避免多个进程同时读写同一状态文件。

## 配置

| 变量 | 默认值 | 说明 |
|---|---|---|
| `WECOM_WEBHOOK_URL` | 无 | 企业微信群机器人 Webhook；服务会去掉末尾中文逗号 |
| `POLL_INTERVAL_SECONDS` | `900` | 轮询间隔，启动后立即检查 |
| `CONFIDENCE_THRESHOLD` | `0.90` | 可信度阈值，范围 `0` 到 `1` |
| `DISPLAY_TIMEZONE` | `Asia/Shanghai` | 消息展示时区 |
| `STATE_FILE` | `/app/data/state.json` | 去重状态文件路径 |
| `HTTP_TIMEOUT_SECONDS` | `15` | API 和机器人请求超时 |
| `DRY_RUN` | `false` | 预览模式不发送、不保存发送状态 |

`CODEXRUNWAY_API_URL` 也可用于测试环境覆盖默认接口地址，但不需要在生产配置中设置。

## 去重和失败恢复

状态文件结构为版本化 JSON：

```json
{
  "version": 1,
  "sent": {
    "scheduled:record-a": {"sentAt": "2026-09-08T08:00:00Z"},
    "completed:record-b": {"sentAt": "2026-09-08T09:00:00Z"}
  },
  "completedScheduleIds": ["record-a"]
}
```

只有企业微信返回 HTTP 成功且 JSON `errcode == 0` 后才写入状态。写入采用同目录临时文件加 `os.replace` 原子替换。状态文件损坏或保存失败会停止服务，不会把损坏状态当成空文件而重复发送历史通知。Webhook 失败时不标记事件，下一轮会再次评估。

首次启动不设置 24 小时窗口，会处理当前第一页 10 条中符合条件的记录；历史事件会显示其记录中的日期。API 限制为每轮第一页 10 条，不保证长时间停机后补齐全部历史新增记录。

## 测试

测试不访问真实 API，也不会调用企业微信：

```bash
python -m unittest discover -s tests -v
```

覆盖内容包括可信度判断、人工确认规则、排期/完成关联、跨轮去重、状态原子持久化、损坏状态、机器人业务错误、API 限流、预览模式和消息格式化。

## 数据和外部协议

- CodexRunway records endpoint：`https://www.codexrunway.com/openapi/v1/records?kind=all&page=1&pageSize=10`
- CodexRunway reset history：`https://www.codexrunway.com/zh/history.html`
- 企业微信官方群机器人文档：`https://developer.work.weixin.qq.com/document/path/91770`

本服务只提供公开重置信息提醒，不查询或确认个人账号实际额度。企业微信发送成功但响应丢失时，重试仍可能造成重复，这是无服务端幂等能力时无法消除的边界。
