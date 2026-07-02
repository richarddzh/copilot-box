# Broker Service

## 1. 目标

Broker 是部署在 Azure Web App 上的 Python FastAPI 服务。Android client 和 Windows backend worker 都主动连接 broker WebSocket；broker 不运行 Copilot agent，也不访问 backend 文件系统，只负责认证、连接管理和消息转发。

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

Web App app settings：

| Setting | 示例 |
| --- | --- |
| `COPILOT_BOX_BROKER_AUTH_MODE` | `shared_secret` |
| `COPILOT_BOX_CLIENT_SHARED_TOKEN` | Android client token |
| `COPILOT_BOX_WORKER_SHARED_TOKEN` | backend worker token |

Startup command：

```bash
bash startup.sh
```

## 4. GitHub Actions 部署

Workflow：`.github\workflows\broker.yml`。

需要配置：

| Name | Type | 用途 |
| --- | --- | --- |
| `AZURE_BROKER_WEBAPP_NAME` | GitHub Actions variable | Azure Web App 名称 |
| `AZURE_BROKER_PUBLISH_PROFILE` | GitHub Actions secret | Azure Web App publish profile XML |

Workflow 会运行 broker WebSocket 测试，并部署 `broker/` 目录。
