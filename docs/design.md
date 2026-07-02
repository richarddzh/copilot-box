# Copilot Box 设计文档

## 1. 背景与目标

Copilot Box 是一个部署在 Windows 服务器上的命令行应用。它会被包装成 Windows Service 长期运行，并通过 GitHub Copilot SDK 提供 agent 能力。Android 客户端不直接连接 Windows Service，而是连接一个部署在 Azure Web App 上的 FastAPI broker。Broker 负责认证、连接管理、路由和审计，并通过 WebSocket 在 Android 客户端和后端 worker 之间转发 JSON 消息。

核心目标：

1. 提供 `copilot-box` CLI，既能本地调试，也能作为 Windows Service 主进程运行。
2. 使用 GitHub Copilot SDK 提供 agent/session 能力。
3. Android、broker、Windows backend worker 之间使用 WebSocket 通信。
4. Broker 运行在 Azure Web App，作为公网入口和消息路由层。
5. Work dir 决定 agent 的执行上下文，使用户可以远程在不同服务器目录中利用 Copilot 开展工作。
6. 支持 session 创建、继续、实时 token/delta 流式输出、最终结果和错误事件。
7. 支持复杂 HTML/Markdown 报告输出到 backend 本地 report workspace，并允许 Android 通过 broker WebSocket 读取。

非目标：

1. 不引入额外云存储作为 Android 与 backend 之间的通信通道。
2. 不让 Android 直接连接 Windows Service。
3. 首版不实现完整多租户沙箱；通过 allowlist、认证、审计和 backend 全局单活跃 session 降低风险。

## 2. 总体架构

```text
Android Client
    |
    | WebSocket: /ws/client
    v
Broker Service
Azure Web App + FastAPI
    |
    | WebSocket route by workerId/workDir/sessionId
    v
Copilot Box Backend Worker
Windows Service / CLI
    |
    | GitHub Copilot SDK session in selected work dir
    v
GitHub Copilot SDK Agent

Backend Report Workspace Folder
    ^
    | report.read / report.content through broker WebSocket
    |
Android Client
```

## 2.1 已确认设计决策

1. Android 与 backend 的实时通信使用 broker WebSocket。
2. Broker 使用 Azure Web App 承载 FastAPI。
3. Backend worker 主动向 broker 建立 outbound WebSocket，适合 Windows 服务器在 NAT/防火墙后运行。
4. Android 默认只连接 broker，不保存任何云资源密钥。
5. Broker 本地开发支持 shared token；正式部署使用 Entra ID/MSAL，Android 发送 user delegated bearer token，worker 使用 managed identity 或 service principal 获取 broker API token。
6. 每个消息都有 `messageId` 和 `requestId`，便于幂等、日志关联和客户端重试。
7. Android client 必须呈现为聊天界面：用户消息显示在右侧/本端气泡，agent 消息显示在左侧/远端气泡，并在收到流式 delta 时原地追加内容。
8. 每个 backend worker 首版只允许一个活跃 session/request；新的 request 在已有 request 运行时会被 broker 或 worker 拒绝为 `worker_busy`。
9. Client 对 agent 响应按 Markdown 渲染；流式过程中持续追加并刷新 Markdown，`agent.final` 到达后用完整 Markdown 内容覆盖校正。
10. Android UI 分为连接配置页和聊天页；聊天页不显示连接配置，并提供退出回连接配置页以重新开始。
11. Broker 在 `broker.hello` 中返回当前 running active session；Android 可加入该 session，先显示 `session.snapshot` 中的最新输出，再继续接收后续 streaming。

## 3. 运行形态

### 3.1 Backend CLI

CLI 是 backend worker 的唯一进程入口：

```powershell
copilot-box version
copilot-box service prompt --config C:\copilot-box\config.toml --work-dir Q:\repo --prompt "..."
copilot-box service run --config C:\copilot-box\config.toml
```

其中：

1. `service prompt`：本地直接调用 GitHub Copilot SDK，适合调试。
2. `service run`：作为长期运行 worker，连接 broker 并处理 WebSocket request。

### 3.2 Windows Service

推荐首版继续使用 WinSW 包装 CLI。服务主体命令：

```powershell
python -m copilot_box service run --config C:\ProgramData\copilot-box\config.toml
```

安装脚本职责：

1. 复制或引用 WinSW exe。
2. 生成服务 XML，设置 `PYTHONPATH`、工作目录、日志目录和服务参数。
3. 调用 `winsw.exe install` 与 `winsw.exe start`。

### 3.3 Broker Service

Broker 是一个 FastAPI app，部署到 Azure Web App。入口：

```bash
python -m uvicorn copilot_box_broker.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

核心 endpoint：

| Endpoint | 用途 |
| --- | --- |
| `GET /healthz` | 健康检查 |
| `WS /ws/client` | Android 客户端连接 |
| `WS /ws/worker` | Windows backend worker 连接 |

## 4. WebSocket 连接模型

### 4.1 Client 连接

Android 连接：

```text
wss://<broker-app>.azurewebsites.net/ws/client
```

本地开发认证：

```text
X-Copilot-Box-Token: <shared-token>
```

正式部署认证：

```text
Authorization: Bearer <MSAL access token for broker API>
```

连接成功后，client 先发送 `client.hello`：

```json
{
  "type": "client.hello",
  "protocolVersion": "2026-07-02",
  "messageId": "msg-001",
  "clientId": "android-device-1",
  "capabilities": {
    "streaming": true,
    "chatUi": true,
    "markdown": true
  }
}
```

Broker 返回：

```json
{
  "type": "broker.hello",
  "protocolVersion": "2026-07-02",
  "messageId": "msg-002",
  "payload": {
    "connectionId": "client-conn-abc",
    "availableWorkers": [
      {
        "workerId": "worker-home-pc",
        "displayName": "Home PC",
        "allowedWorkDirs": ["Q:\\gitroot\\copilot-box"],
        "reportWorkspace": {
          "enabled": true,
          "root": "Q:\\copilot-box-reports"
        },
        "busy": false
      }
    ],
    "activeSessions": [
      {
        "requestId": "req-active",
        "workerId": "worker-home-pc",
        "workDir": "Q:\\gitroot\\copilot-box",
        "sessionId": "sess_abc",
        "status": "running",
        "prompt": "请生成项目报告",
        "outputPreview": "正在分析..."
      }
    ]
  }
}
```

### 4.2 Worker 连接

Backend worker 连接：

```text
wss://<broker-app>.azurewebsites.net/ws/worker
```

本地开发认证：

```text
X-Copilot-Box-Worker-Token: <worker-token>
```

正式部署认证：

```text
Authorization: Bearer <managed identity or service principal token for broker API>
```

连接成功后，worker 发送 `worker.hello`：

```json
{
  "type": "worker.hello",
  "protocolVersion": "2026-07-02",
  "messageId": "msg-101",
  "workerId": "worker-home-pc",
  "displayName": "Home PC",
  "allowedWorkDirs": ["Q:\\gitroot\\copilot-box"],
  "reportWorkspace": {
    "enabled": true,
    "root": "Q:\\copilot-box-reports"
  },
  "capabilities": {
    "models": [],
    "streaming": true,
    "maxConcurrentRequests": 1,
    "singleActiveSession": true,
    "markdown": true,
    "reportRead": true
  }
}
```

Broker 返回：

```json
{
  "type": "broker.worker.accepted",
  "protocolVersion": "2026-07-02",
  "messageId": "msg-102",
  "payload": {
    "workerId": "worker-home-pc"
  }
}
```

## 5. JSON Payload 设计

### 5.1 通用 envelope

所有 WebSocket JSON 消息都使用统一 envelope：

```json
{
  "type": "agent.request",
  "protocolVersion": "2026-07-02",
  "messageId": "msg-123",
  "requestId": "req-456",
  "timestamp": "2026-07-02T12:00:00Z",
  "payload": {}
}
```

字段：

| 字段 | 说明 |
| --- | --- |
| `type` | 消息类型 |
| `protocolVersion` | 协议版本 |
| `messageId` | 单条消息幂等 id |
| `requestId` | 一次 agent request 的关联 id |
| `timestamp` | UTC 时间 |
| `payload` | 类型相关内容 |

### 5.2 Client 发起 agent request

Client -> Broker -> Worker：

```json
{
  "type": "agent.request",
  "protocolVersion": "2026-07-02",
  "messageId": "msg-201",
  "requestId": "req-001",
  "timestamp": "2026-07-02T12:00:00Z",
  "payload": {
    "workerId": "worker-home-pc",
    "workDir": "Q:\\gitroot\\copilot-box",
    "session": {
      "mode": "auto",
      "sessionId": null
    },
    "agent": {
      "prompt": "请总结当前项目",
      "model": null,
      "timeoutSeconds": 120
    }
  }
}
```

### 5.3 Broker ack

Broker -> Client：

```json
{
  "type": "broker.accepted",
  "protocolVersion": "2026-07-02",
  "messageId": "msg-202",
  "requestId": "req-001",
  "timestamp": "2026-07-02T12:00:01Z",
  "payload": {
    "workerId": "worker-home-pc"
  }
}
```

### 5.4 Worker session started

Worker 在选定或创建 Copilot SDK session 后先发送 `session.started`。Broker 用它更新 active session 的 `sessionId`，加入该 running session 的 client 之后会用这个 `sessionId` 继续工作。

```json
{
  "type": "session.started",
  "protocolVersion": "2026-07-02",
  "messageId": "msg-300",
  "requestId": "req-001",
  "timestamp": "2026-07-02T12:00:02Z",
  "payload": {
    "sessionId": "sess_abc",
    "createdSession": true,
    "workDir": "Q:\\gitroot\\copilot-box",
    "status": "running"
  }
}
```

### 5.5 Worker delta

Worker -> Broker -> Client：

```json
{
  "type": "agent.delta",
  "protocolVersion": "2026-07-02",
  "messageId": "msg-302",
  "requestId": "req-001",
  "timestamp": "2026-07-02T12:00:03Z",
  "payload": {
    "role": "assistant",
    "sequence": 1,
    "text": "项目"
  }
}
```

`agent.delta` 是聊天界面实时显示的核心事件。Android 对同一 `requestId` 的 assistant 气泡执行 append，而不是每次新增一条消息。`sequence` 从 1 递增，client 可用它忽略重复 delta。

### 5.6 Worker final

Worker -> Broker -> Client：

```json
{
  "type": "agent.final",
  "protocolVersion": "2026-07-02",
  "messageId": "msg-401",
  "requestId": "req-001",
  "timestamp": "2026-07-02T12:00:30Z",
  "payload": {
    "status": "succeeded",
    "sessionId": "sess_abc",
    "createdSession": true,
    "workDir": "Q:\\gitroot\\copilot-box",
    "output": "项目总结...",
    "reportPath": null
  }
}
```

`agent.final.payload.output` 必须包含完整 assistant 文本，便于 client 在丢失某些 delta 时用 final 内容校正聊天气泡。

如果 agent 生成了大型报告，`agent.final` 可以同时返回 `reportPath`：

```json
{
  "type": "agent.final",
  "protocolVersion": "2026-07-02",
  "messageId": "msg-402",
  "requestId": "req-001",
  "timestamp": "2026-07-02T12:00:30Z",
  "payload": {
    "status": "succeeded",
    "sessionId": "sess_abc",
    "output": "报告已生成：reports/req-001/index.md",
    "reportPath": "reports/req-001/index.md",
    "contentType": "text/markdown"
  }
}
```

### 5.7 Active session join

Client 可加入 `broker.hello.payload.activeSessions` 中的 running session：

```json
{
  "type": "session.join",
  "protocolVersion": "2026-07-02",
  "messageId": "msg-450",
  "requestId": "join-001",
  "timestamp": "2026-07-02T12:00:10Z",
  "payload": {
    "workerId": "worker-home-pc",
    "requestId": "req-active"
  }
}
```

Broker 返回当前快照并把 client 加入该 request 的订阅者集合。后续 `agent.delta`、`agent.final` 或错误会广播给原始 client 和所有 joined clients。

```json
{
  "type": "session.snapshot",
  "protocolVersion": "2026-07-02",
  "messageId": "msg-451",
  "requestId": "req-active",
  "timestamp": "2026-07-02T12:00:10Z",
  "payload": {
    "activeSession": {
      "requestId": "req-active",
      "workerId": "worker-home-pc",
      "workDir": "Q:\\gitroot\\copilot-box",
      "sessionId": "sess_abc",
      "status": "running",
      "prompt": "请生成项目报告",
      "outputPreview": "正在分析..."
    },
    "outputSoFar": "正在分析..."
  }
}
```

### 5.8 Error

任意方向：

```json
{
  "type": "error",
  "protocolVersion": "2026-07-02",
  "messageId": "msg-500",
  "requestId": "req-001",
  "timestamp": "2026-07-02T12:00:31Z",
  "payload": {
    "code": "worker_not_available",
    "message": "Requested worker is not connected.",
    "retryable": true
  }
}
```

### 5.9 Report read

Client -> Broker -> Worker：

```json
{
  "type": "report.read",
  "protocolVersion": "2026-07-02",
  "messageId": "msg-601",
  "requestId": "report-001",
  "timestamp": "2026-07-02T12:01:00Z",
  "payload": {
    "workerId": "worker-home-pc",
    "path": "reports/req-001/index.md"
  }
}
```

Worker -> Broker -> Client：

```json
{
  "type": "report.content",
  "protocolVersion": "2026-07-02",
  "messageId": "msg-602",
  "requestId": "report-001",
  "timestamp": "2026-07-02T12:01:01Z",
  "payload": {
    "path": "reports/req-001/index.md",
    "contentType": "text/markdown",
    "content": "# 报告\n\n..."
  }
}
```

Report path 必须是 report workspace root 下的相对路径；禁止绝对路径和 `..` 越界。

## 6. Broker 路由与状态

Broker 维护内存连接表：

| 表 | Key | Value |
| --- | --- | --- |
| clients | `clientConnectionId` | client WebSocket |
| workers | `workerId` | worker WebSocket + metadata |
| requests | `requestId` | clientConnectionId + workerId + status |

首版不持久化消息。断线后的行为：

1. Client 断开：broker 继续等待 worker final，但无法投递时丢弃并记录日志。
2. Worker 断开：broker 对该 worker 的 in-flight request 返回 `error(worker_disconnected)`。
3. Broker 重启：所有 WebSocket 连接重建，client 需要重新发送 request。
4. Worker 已有活跃 request：broker 直接返回 `error(worker_busy)`，client 在聊天界面显示为失败的 assistant 气泡。

后续如果需要强可靠投递，可以再引入 durable queue；首版优先实时性和简单性。

## 7. Session 设计

Session 的上下文由 work dir 决定，但 sessionId 仍然是显式对象。每个 backend worker 首版只允许一个活跃 session/request，原因是 Copilot agent 会访问真实 work dir、可能执行工具操作，并且 Windows Service 进程需要避免多个远程 prompt 同时修改同一台机器上的文件。Backend worker 的可选 work dir 来自配置白名单，并在 `worker.hello` 中上报给 broker；Android 不需要手动输入任意路径，只从 broker 下发的白名单中选择。Backend worker 本地 SQLite 记录：

| 字段 | 说明 |
| --- | --- |
| `session_id` | Copilot Box session id |
| `work_dir` | canonical absolute path |
| `created_at` | 创建时间 |
| `last_active_at` | 最近活跃时间 |
| `status` | active, idle, closed, failed |

决策顺序：

1. `session.mode == new`：总是创建新 session。
2. `session.mode == continue`：必须存在 `session.sessionId`，且 work dir 匹配。
3. `session.mode == auto` 且提供 sessionId：尝试继续该 session。
4. `session.mode == auto` 且未提供 sessionId：查找同 work dir 最近活跃且未过期 session。
5. 找不到可用 session：创建新 session。

Android 端简化为两个动作：

| 动作 | 协议映射 | 说明 |
| --- | --- | --- |
| 继续现有 session | `session.mode = "auto"` | 对选中 work dir 继续最近活跃 session；如果没有则创建 |
| 在该 work dir 新建 session | `session.mode = "new"` | 强制创建新 session |

默认 session TTL 为 24 小时。

并发规则：

1. Worker 进程内使用单个全局 async lock 包住一次完整 agent request。
2. Lock 被占用时，worker 不启动第二个 Copilot SDK session，直接返回 `error(worker_busy)`。
3. Broker 也维护 worker busy 状态，尽量在转发前拒绝新 request。
4. `service prompt` 本地调试命令仍然直接执行，但它和 Windows Service 不应同时针对同一 state dir 运行。

## 8. Work Dir 安全模型

Backend worker 不能信任 client 传入的 work dir。必须：

1. canonicalize 路径，解析 `..`。
2. 要求路径位于配置的 allowlist root 中。
3. 拒绝系统目录和敏感目录，除非显式允许。
4. 同一 backend worker 首版只允许一个 agent request 并发执行。
5. 记录 requestId、clientId、workerId、workDir、sessionId 和关键 tool 操作。

示例配置：

```toml
[workdirs]
allowed = ["Q:\\gitroot\\copilot-box"]
```

## 9. GitHub Copilot SDK 集成

Backend worker 通过适配层调用 GitHub Copilot SDK：

```text
WebSocketWorker
    -> AgentService
    -> SessionManager
    -> CopilotAgentAdapter
        -> GitHub Copilot SDK
```

适配层提供：

1. `create_session(work_dir, options) -> session`
2. `resume_session(session_ref) -> session`
3. `send_message(session, prompt, attachments, on_delta) -> event stream`
4. `cancel(session, request_id)`
5. `close(session)`

## 10. Report Workspace

复杂报告写入 backend 本地目录：

```text
Q:\copilot-box-reports\
  reports/
    {requestId}/
      index.md
      index.html
      assets/
```

Backend worker 只允许通过配置的 `reports.root_dir` 读取报告文件。Broker 不直接访问文件系统，只负责把 `report.read` 转发到对应 worker，并把 `report.content` 转发回 client。Android 根据 `contentType` 渲染内容：

1. `text/markdown`：用聊天界面的 Markdown renderer 展示。
2. `text/html`：首版按文本显示；后续如引入 WebView，必须禁用任意脚本或只允许受信任报告。
3. 其他类型：以纯文本显示，具体后续扩展。

## 11. 配置设计

Backend worker：

```toml
[broker]
url = "wss://<broker-app>.azurewebsites.net/ws/worker"
worker_id = "worker-home-pc"
worker_token = "<secret>"
display_name = "Home PC"
heartbeat_seconds = 30

[sessions]
state_dir = "C:\\ProgramData\\copilot-box\\state"
ttl_seconds = 86400
max_concurrent_requests = 1
single_active_session = true

[workdirs]
allowed = ["Q:\\gitroot\\copilot-box"]

[agent]
adapter = "github_copilot_sdk"
model = ""
timeout_seconds = 120
approve_all_tool_requests = true
base_directory = "C:\\ProgramData\\copilot-box\\copilot-home"

[reports]
enabled = true
root_dir = "Q:\\copilot-box-reports"
max_file_bytes = 1048576
```

Broker Web App settings：

| Setting | 示例 |
| --- | --- |
| `COPILOT_BOX_BROKER_AUTH_MODE` | `shared_secret` |
| `COPILOT_BOX_CLIENT_SHARED_TOKEN` | Android shared token |
| `COPILOT_BOX_WORKER_SHARED_TOKEN` | Worker shared token |

Android app：

| 字段 | 说明 |
| --- | --- |
| Broker WebSocket URL | `wss://<broker-app>.azurewebsites.net/ws/client` |
| Client token | `COPILOT_BOX_CLIENT_SHARED_TOKEN` |
| Worker ID | 要路由到的 backend worker |
| Work dir | 从 worker 上报白名单中选择 |
| Session action | 继续现有 session，或在选中 work dir 新建 session |
| Prompt | 用户输入 |

Android 聊天 UI：

| 元素 | 说明 |
| --- | --- |
| 连接配置页 | Broker URL、token、worker 下拉、work dir 下拉、session action |
| 消息列表 | 纵向滚动的聊天气泡 |
| 用户气泡 | 点击发送后立即追加，显示用户 prompt |
| Agent 气泡 | 收到 `broker.accepted` 后创建占位，收到 `agent.delta` 时实时 append |
| Markdown 渲染 | Agent 气泡按 Markdown 显示，支持标题、列表、代码块、链接等常见语法 |
| 状态文本 | 显示 connected/running/failed/succeeded |
| 输入框 | 多行 prompt，底部发送按钮 |
| 退出按钮 | 断开当前 WebSocket，清空当前聊天状态，返回连接配置页重新开始 |

## 12. 错误处理与状态

状态：

| 状态 | 含义 |
| --- | --- |
| `accepted` | broker 已接收并路由 request |
| `running` | worker 正在执行 |
| `succeeded` | 成功完成 |
| `failed` | 不可重试失败 |
| `cancelled` | 被取消 |

错误 payload 必须包含：

1. `code`
2. `message`
3. `retryable`
4. `requestId`

## 13. 可观测性

1. Broker 日志记录连接、认证失败、路由失败、request 完成。
2. Backend worker 记录 requestId、sessionId、workDir、agent 错误。
3. Android 以聊天气泡显示用户 prompt、agent delta、final 和 error。
4. 所有日志使用 requestId 关联。

## 14. 部署

1. Broker：Azure Web App + GitHub Actions workflow 部署。
2. Backend：Windows Service + WinSW。
3. Android：GitHub Actions 构建 APK，并在 tag release 中发布安装包。
4. Docs：Sphinx + GitHub Pages。

## 15. 后续待确认

1. Broker 生产认证是否切换到 Entra ID/MSAL。
2. 是否需要 broker 持久化 in-flight request。
3. 是否需要多 worker 自动选择，而不是 Android 指定 workerId。
4. 是否需要多 worker 自动选择，而不是 Android 指定 workerId。
