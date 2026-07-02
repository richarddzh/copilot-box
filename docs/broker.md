# Broker Service

## 1. 目标

Broker 是部署在 Azure Web App 上的 Python FastAPI 服务。Android client 和 Windows backend worker 都主动连接 broker WebSocket；broker 不运行 Copilot agent，也不访问 backend 文件系统，只负责认证、连接管理、active session 状态跟踪和消息转发。

Endpoint：

| Endpoint | 用途 |
| --- | --- |
| `GET /healthz` | 健康检查 |
| `WS /ws/client` | Android client |
| `WS /ws/worker` | backend worker |

## 2. 本地运行

安装依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -e .[broker,dev]
```

设置环境变量：

```powershell
$env:COPILOT_BOX_BROKER_AUTH_MODE = "shared_secret"
$env:COPILOT_BOX_CLIENT_SHARED_TOKEN = "<client-token>"
$env:COPILOT_BOX_WORKER_SHARED_TOKEN = "<worker-token>"
```

启动：

```powershell
.\.venv\Scripts\python.exe -m uvicorn copilot_box_broker.main:app `
  --app-dir .\broker `
  --host 127.0.0.1 `
  --port 8000
```

Backend worker 配置 `broker.url = "ws://127.0.0.1:8000/ws/worker"` 后运行：

```powershell
.\.venv\Scripts\python.exe -m copilot_box service run --config .\config\copilot-box.example.toml
```

Android 填写：

```text
Broker WebSocket URL: ws://127.0.0.1:8000/ws/client
Client token: <client-token>
```

## 3. Azure Web App 部署

正式部署建议使用 Entra ID/MSAL。Shared secret 只保留给本地开发或临时调试。

Web App app settings：

| Setting | 示例 |
| --- | --- |
| `COPILOT_BOX_BROKER_AUTH_MODE` | `entra_id` |
| `COPILOT_BOX_ENTRA_TENANT_ID` | Entra tenant id |
| `COPILOT_BOX_ENTRA_AUDIENCE` | broker API app id 或 app ID URI，例如 `api://<broker-api-app-id>` |
| `COPILOT_BOX_ENTRA_ALLOWED_CLIENT_APP_IDS` | Android public client app id，逗号分隔 |
| `COPILOT_BOX_ENTRA_ALLOWED_WORKER_APP_IDS` | worker managed identity 或 service principal app id，逗号分隔 |
| `COPILOT_BOX_ENTRA_REQUIRED_CLIENT_SCOPE` | 可选，例如 `CopilotBox.Access` |
| `COPILOT_BOX_ENTRA_REQUIRED_WORKER_ROLE` | 可选，例如 `CopilotBox.Worker` |

Startup command：

```bash
bash startup.sh
```

本地开发仍可使用 shared secret：

```powershell
$env:COPILOT_BOX_BROKER_AUTH_MODE = "shared_secret"
$env:COPILOT_BOX_CLIENT_SHARED_TOKEN = "<client-token>"
$env:COPILOT_BOX_WORKER_SHARED_TOKEN = "<worker-token>"
```

## 4. GitHub Actions 部署

Workflow：`.github\workflows\broker.yml`。

需要配置：

| Name | Type | 用途 |
| --- | --- | --- |
| `AZURE_BROKER_WEBAPP_NAME` | GitHub Actions variable | Azure Web App 名称 |
| `AZURE_BROKER_PUBLISH_PROFILE` | GitHub Actions secret | Azure Web App publish profile XML |

Workflow 会运行 broker WebSocket 测试，并部署 `broker/` 目录。

## 5. Active session 发现与加入

Broker 为每个 running `agent.request` 维护一条 active session 记录，记录 `requestId`、`workerId`、`workDir`、`sessionId`、原始 prompt、已收到的输出和订阅 client。新 Android client 连接并发送 `client.hello` 后，`broker.hello.payload.activeSessions` 会返回当前 running sessions。

客户端发送 `session.join` 后，broker 返回 `session.snapshot`，其中包含原始 prompt 和 `outputSoFar`，并把该 client 加入订阅者集合。之后该 request 的 `session.started`、`agent.delta`、`agent.final` 和 `error` 会广播给原始 client 与所有 joined clients。`agent.final` 或 `error` 后 active session 会从 broker 状态中移除；历史 completed session 不在 broker 中持久保存。
