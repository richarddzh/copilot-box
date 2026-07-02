# 使用文档

## 1. 准备环境

```powershell
Set-Location Q:\gitroot\copilot-box
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .[dev,service,docs,broker]
.\.venv\Scripts\python.exe -m copilot download-runtime
```

## 2. 本地直接调用 agent

```powershell
.\.venv\Scripts\python.exe -m copilot_box service prompt `
  --config .\config\copilot-box.example.toml `
  --work-dir Q:\gitroot\copilot-box `
  --prompt "请用 Markdown 总结当前项目" `
  --json
```

返回示例：

```json
{
  "sessionId": "sess_xxx",
  "createdSession": true,
  "workDir": "Q:\\gitroot\\copilot-box",
  "output": "pong"
}
```

## 3. 运行 broker 与 backend worker

本地开发可以使用 shared token 启动 broker：

```powershell
$env:COPILOT_BOX_CLIENT_SHARED_TOKEN = "<client-token>"
$env:COPILOT_BOX_WORKER_SHARED_TOKEN = "<worker-token>"
.\.venv\Scripts\python.exe -m uvicorn copilot_box_broker.main:app `
  --app-dir .\broker `
  --host 127.0.0.1 `
  --port 8000
```

配置 `config\copilot-box.example.toml` 中：

```toml
[broker]
url = "ws://127.0.0.1:8000/ws/worker"
worker_id = "worker-home-pc"
auth_mode = "shared_secret"
worker_token = "<worker-token>"

[workdirs]
allowed = ["Q:\\gitroot\\copilot-box"]
```

启动 worker：

```powershell
.\.venv\Scripts\python.exe -m copilot_box service run `
  --config .\config\copilot-box.example.toml
```

### 3.1 正式部署：Entra ID / MSAL 登录

Android 当前使用 MSAL single-account 模式登录：用户在连接页选择 **Entra ID / MSAL** 后，app 会读取 `android\app\src\main\res\raw\auth_config_single_account.json` 初始化 MSAL，按 `android\app\src\main\res\values\strings.xml` 中的 `msal_broker_scopes` 申请 broker API access token，然后用 bearer access token 连接 `wss://<broker>/ws/client`。

需要准备两个 Entra app registration：

| App registration | 类型 | 用途 |
| --- | --- | --- |
| Broker API | Web/API | 表示 broker 资源，暴露 delegated scope，例如 `CopilotBox.Access`；可选定义 app role，例如 `CopilotBox.Worker` |
| Android client | Public client / Android | MSAL 登录入口，允许移动端 redirect URI，并被授权请求 Broker API scope |

Broker API app registration：

1. 设置 **Application ID URI**，例如 `api://<broker-api-app-id>`。
2. 在 **Expose an API** 中添加 delegated scope，例如 `CopilotBox.Access`。
3. 可选：在 **App roles** 中添加 worker 使用的 application role，例如 `CopilotBox.Worker`。
4. 如果 worker 使用 service principal/client secret，把 `CopilotBox.Worker` app role 分配给该 service principal；如果使用 managed identity，把 app role 分配给该 managed identity 的 service principal。

Android app registration：

1. 添加 Android platform，包名为 `com.github.richarddzh.copilotbox`，并配置调试/发布签名 hash。
2. 复制 portal 生成的 MSAL config，更新 `android\app\src\main\res\raw\auth_config_single_account.json` 的 `client_id`、`tenant_id`、`redirect_uri`。
3. 如果只允许组织账号，`audience.type` 使用 `AzureADMyOrg`；如果要允许 `hotmail.com` 这类个人 Microsoft Account，需要把 app registration 配成支持个人账号，并把 MSAL authority/audience 调整为 `AzureADandPersonalMicrosoftAccount`/`common` 或 `consumers`，同时 broker 端 issuer 校验也要相应调整。
4. 更新 `android\app\src\main\res\values\strings.xml`：

```xml
<string name="msal_broker_scopes">api://<broker-api-app-id>/CopilotBox.Access</string>
```

Broker Web App 设置：

```powershell
$env:COPILOT_BOX_BROKER_AUTH_MODE = "entra_id"
$env:COPILOT_BOX_ENTRA_TENANT_ID = "<tenant-id>"
$env:COPILOT_BOX_ENTRA_AUDIENCE = "api://<broker-api-app-id>"
$env:COPILOT_BOX_ENTRA_ALLOWED_CLIENT_APP_IDS = "<android-client-app-id>"
$env:COPILOT_BOX_ENTRA_ALLOWED_WORKER_APP_IDS = "<worker-managed-identity-or-sp-app-id>"
$env:COPILOT_BOX_ENTRA_REQUIRED_CLIENT_SCOPE = "CopilotBox.Access"
$env:COPILOT_BOX_ENTRA_REQUIRED_WORKER_ROLE = "CopilotBox.Worker"
```

其中 `COPILOT_BOX_ENTRA_REQUIRED_CLIENT_SCOPE` 和 `COPILOT_BOX_ENTRA_REQUIRED_WORKER_ROLE` 是可选但推荐的强校验；如果不设置，broker 只校验 issuer、audience 和 allowlist app id。

Worker 配置使用 managed identity：

```toml
[broker]
auth_mode = "entra_id"
entra_tenant_id = "<tenant-id>"
entra_client_id = "" # managed identity client id；系统分配 identity 可留空
entra_client_secret = ""
entra_scope = "api://<broker-api-app-id>/.default"
```

Worker 也可以使用 service principal：

```toml
[broker]
auth_mode = "entra_id"
entra_tenant_id = "<tenant-id>"
entra_client_id = "<service-principal-client-id>"
entra_client_secret = "<service-principal-secret>"
entra_scope = "api://<broker-api-app-id>/.default"
```

本地调试 worker 可以先执行 `az login`，然后让 `DefaultAzureCredential` 使用 Azure CLI 登录态获取 token；这种方式适合开发调试。生产环境建议使用 managed identity 或 service principal，并在 broker allowlist/app role 中显式授权 worker。

## 4. Session 行为

Backend worker 首版全局只允许一个活跃 session/request。Android 端新建或继续 work dir session 时暴露两个动作：

| 动作 | session mode |
| --- | --- |
| 继续现有 session | `auto` |
| 在该 work dir 新建 session | `new` |

`auto` 会复用同一 work dir 最近活跃且未过期的 session；找不到则创建新 session。

当 broker 上已经有 running request 时，新连接的 Android 会在 `broker.hello.payload.activeSessions` 中看到该 active session。用户可在连接页点击 **Join active session**，客户端发送 `session.join`，broker 返回 `session.snapshot`，其中包含原始 prompt 和 `outputSoFar`。加入后客户端继续接收同一 request 的 streaming 输出；`agent.final` 返回 `sessionId` 后，后续 prompt 使用 `continue + sessionId` 继续同一个 Copilot session。

## 5. Report workspace

报告文件位于 backend 本地配置目录：

```toml
[reports]
enabled = true
root_dir = "Q:\\copilot-box-reports"
max_file_bytes = 1048576
```

Client 通过 broker 发送 `report.read`，worker 从该目录安全读取相对路径，并返回 `report.content`。

## 6. Windows Service 脚本

安装服务：

```powershell
.\scripts\install-service.ps1 -WinSWPath C:\tools\WinSW-x64.exe
```

卸载服务：

```powershell
.\scripts\uninstall-service.ps1
```

服务主体命令：

```powershell
python -m copilot_box service run --config .\config\copilot-box.example.toml
```

## 7. 构建 HTML 文档

```powershell
.\.venv\Scripts\sphinx-build.exe -b html .\docs .\docs\_build\html
```
