# 使用文档

## 1. 准备环境

进入项目目录：

```powershell
Set-Location Q:\gitroot\copilot-box
```

创建或复用虚拟环境，并安装项目依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .[dev,service,docs]
```

下载 GitHub Copilot SDK runtime：

```powershell
.\.venv\Scripts\python.exe -m copilot download-runtime
```

> 标准 GitHub Copilot SDK 使用 GitHub 登录态或 token。当前项目优先复用本机 Copilot CLI 登录态，也可以通过 SDK 支持的环境变量提供 GitHub token。

## 2. 验证 CLI

查看版本：

```powershell
.\.venv\Scripts\python.exe -m copilot_box version
```

查看 prompt 命令帮助：

```powershell
.\.venv\Scripts\python.exe -m copilot_box service prompt --help
```

## 3. 发送一个 prompt

使用示例配置向 GitHub Copilot SDK 发送 prompt：

```powershell
.\.venv\Scripts\python.exe -m copilot_box service prompt `
  --config .\config\copilot-box.example.toml `
  --work-dir Q:\gitroot\copilot-box `
  --prompt "请只回复 pong，不要修改文件" `
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

字段说明：

| 字段 | 说明 |
| --- | --- |
| `sessionId` | copilot-box 侧 session id，会传给 Copilot SDK 用于创建或继续 session |
| `createdSession` | `true` 表示本次创建了新 session；`false` 表示继续了已有 session |
| `workDir` | agent 执行上下文目录 |
| `output` | agent 最终响应文本 |

## 4. 创建或继续 session

默认 `--session-mode auto`。当同一个 work dir 已有未过期 session 时，`auto` 会继续最近活跃的 session：

```powershell
.\.venv\Scripts\python.exe -m copilot_box service prompt `
  --config .\config\copilot-box.example.toml `
  --work-dir Q:\gitroot\copilot-box `
  --prompt "继续刚才的上下文，只回复 ok" `
  --json
```

强制创建新 session：

```powershell
.\.venv\Scripts\python.exe -m copilot_box service prompt `
  --config .\config\copilot-box.example.toml `
  --work-dir Q:\gitroot\copilot-box `
  --session-mode new `
  --prompt "开启一个新 session" `
  --json
```

显式继续指定 session：

```powershell
.\.venv\Scripts\python.exe -m copilot_box service prompt `
  --config .\config\copilot-box.example.toml `
  --work-dir Q:\gitroot\copilot-box `
  --session-mode continue `
  --session-id sess_xxx `
  --prompt "请基于这个 session 的上下文继续" `
  --json
```

## 5. 配置说明

示例配置文件：`config\copilot-box.example.toml`。

关键配置：

| 配置 | 说明 |
| --- | --- |
| `sessions.state_dir` | 本地 SQLite session 元数据目录 |
| `sessions.ttl_seconds` | `auto` 模式下可复用 session 的过期时间 |
| `workdirs.allowed_roots` | 允许 agent 进入的 work dir 根目录 |
| `agent.adapter` | `github_copilot_sdk` 表示真实 SDK；`echo` 可用于本地测试 |
| `agent.model` | 空字符串表示使用 Copilot 运行时默认模型 |
| `agent.timeout_seconds` | 单次 prompt 等待 agent idle 的超时时间 |
| `agent.base_directory` | Copilot SDK 的数据目录，会作为 `COPILOT_HOME` 使用 |

## 6. 构建 HTML 文档

安装 docs 依赖后构建：

```powershell
.\.venv\Scripts\python.exe -m pip install -e .[docs]
.\.venv\Scripts\sphinx-build.exe -b html .\docs .\docs\_build\html
```

本地打开：

```powershell
Start-Process .\docs\_build\html\index.html
```

## 7. 发布到 GitHub Pages

仓库包含 `.github\workflows\docs.yml`。推送到默认分支后，GitHub Actions 会：

1. 安装 Python。
2. 安装 `.[docs]` 文档依赖。
3. 使用 Sphinx 构建 `docs\_build\html`。
4. 上传 Pages artifact。
5. 部署到 GitHub Pages。

首次使用时，需要在 GitHub 仓库设置中启用 Pages，并将 Source 选择为 **GitHub Actions**。

## 8. Windows Service 脚本

## 8. Azure Blob Storage request 接入

### 8.1 配置 Storage Account

在 `config\copilot-box.example.toml` 中配置：

```toml
[storage]
account_url = "https://<account>.blob.core.windows.net"
request_container = "requests"
response_container = "responses"
dead_letter_container = "dead-letter"
request_prefix = ""
poll_interval_seconds = 5
max_requests_per_poll = 10
```

服务端使用 `DefaultAzureCredential` 访问 Azure Storage Account。生产环境建议为运行 Windows Service 的身份配置 Managed Identity，并授予：

| Container | 建议角色 |
| --- | --- |
| `requests` | `Storage Blob Data Contributor`，用于 list、read、lease |
| `responses` | `Storage Blob Data Contributor`，用于写入状态和结果 |
| `dead-letter` | `Storage Blob Data Contributor`，用于写入失败请求 |

### 8.2 Request blob 格式

request blob 是 JSON 文件，放在 `requests` container 中，名称建议以 work dir safe name 和 timestamp 组织：

```text
requests/q-gitroot-copilot-box/20260702T060110226Z-req-1.json
```

示例内容：

```json
{
  "protocolVersion": "2026-07-02",
  "requestId": "req-1",
  "createdAt": "2026-07-02T06:01:10.226Z",
  "client": {
    "type": "android",
    "userId": "user-1"
  },
  "workDir": "Q:\\gitroot\\copilot-box",
  "session": {
    "mode": "auto",
    "sessionId": null
  },
  "agent": {
    "prompt": "请总结当前目录",
    "model": null,
    "timeoutSeconds": 120
  },
  "response": {
    "prefix": "q-gitroot-copilot-box/20260702T060110226Z-req-1"
  }
}
```

### 8.3 处理一轮 request

```powershell
.\.venv\Scripts\python.exe -m copilot_box service once `
  --config .\config\copilot-box.example.toml
```

`service once` 会：

1. list request blob。
2. acquire blob lease，避免多个服务实例重复处理。
3. 校验 request JSON。
4. 调用 `AgentService` 创建或继续 Copilot session。
5. 写入 accepted、running、final response blob。
6. 对不可处理的 request 写入 dead-letter。

### 8.4 持续轮询

```powershell
.\.venv\Scripts\python.exe -m copilot_box service run `
  --config .\config\copilot-box.example.toml
```

`service run` 会按 `storage.poll_interval_seconds` 持续轮询。调试时可以限制轮询次数：

```powershell
.\.venv\Scripts\python.exe -m copilot_box service run `
  --config .\config\copilot-box.example.toml `
  --max-iterations 1
```

### 8.5 Response blob 格式

如果 request 指定了 `response.prefix`，结果会写到该 prefix 下：

```text
responses/q-gitroot-copilot-box/20260702T060110226Z-req-1/000001.accepted.json
responses/q-gitroot-copilot-box/20260702T060110226Z-req-1/000002.running.json
responses/q-gitroot-copilot-box/20260702T060110226Z-req-1/999999.final.json
```

最终结果示例：

```json
{
  "protocolVersion": "2026-07-02",
  "sequence": 999999,
  "type": "final",
  "status": "succeeded",
  "requestId": "req-1",
  "sessionId": "sess_xxx",
  "createdSession": true,
  "workDir": "Q:\\gitroot\\copilot-box",
  "output": "agent response",
  "completedAt": "2026-07-02T06:05:00Z"
}
```

## 9. Windows Service 脚本

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
