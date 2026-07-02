# Copilot Box 设计文档

## 1. 背景与目标

Copilot Box 是一个部署在 Windows 服务器上的命令行应用。它会被包装成 Windows Service 长期运行，为远程客户端提供 GitHub Copilot agent 能力。客户端不直接连接服务进程，而是通过 Azure Storage Account 的 Blob Container 投递请求、扫描结果，从而实现弱连接、可重试、易审计的远程 agent 工作流。

核心目标：

1. 提供 `copilot-box` CLI，既能本地调试，也能作为服务主进程运行。
2. 支持通过脚本安装、卸载 Windows Service。
3. 使用 GitHub Copilot SDK 提供 agent/session 能力。
4. 通过 Blob Storage 的 list/lease/read/write 协议接收请求并返回输出。
5. 让 request 中的 work dir 决定 agent 的上下文，使用户可以远程在不同服务器目录中开展工作。
6. 支持复杂 HTML/Markdown 报告输出到一个独立 GitHub repo，并由 GitHub Actions 部署到启用认证的 Azure Static Web Apps。

非目标：

1. 不把 Blob Storage 当作强实时消息队列；首版接受秒级轮询延迟。
2. 不让客户端直接访问 Windows Service。
3. 不在首版实现多租户隔离沙箱；首版通过 allowlist、身份认证、审计和并发控制降低风险。

## 2. 总体架构

```text
Android Client
    |
    | write request blob / list response blobs
    v
Azure Storage Account
    | containers:
    | - requests
    | - responses
    | - dead-letter
    | - optional session-state backups
    v
Copilot Box Windows Service
    |
    | normalize work dir, acquire blob lease, route session
    v
GitHub Copilot SDK Agent
    |
    | read/write files, run tools in work dir, stream events
    v
Response Blobs

Agent Report Workspace GitHub Repo
    |
    | push markdown/html report
    v
GitHub Actions
    |
    | deploy
    v
Azure Static Web Apps with authentication required
```

## 2.1 已确认设计决策

1. Storage 后端使用 Azure Storage Account。
2. Request、response、dead-letter 均基于 Azure Blob Storage container 实现。
3. 服务通过 Blob list + lease 的方式发现并领取 request，客户端通过扫描 response blob 获取结果。
4. 服务端访问 Azure Storage Account 首选 Managed Identity；如果不在 Azure VM/Arc/托管环境中运行，则使用服务专用 Entra 应用身份。
5. Android 客户端不得内置 Storage Account key。首版推荐由受信任 broker 签发短期、最小权限 SAS，让客户端只拥有写 request、读 response 的能力。

## 3. 运行形态

### 3.1 CLI

CLI 是唯一的进程入口，建议命令结构如下：

```powershell
copilot-box version
copilot-box service run --config C:\copilot-box\config.toml
copilot-box service once --config C:\copilot-box\config.toml
copilot-box request validate .\sample-request.json
```

其中：

1. `service run`：长期轮询 Blob，适合 Windows Service。
2. `service once`：处理一轮或一个 request，适合本地调试、CI 和排障。
3. `request validate`：校验 request blob 的 JSON schema。

### 3.2 Windows Service

推荐首版使用 WinSW 包装 CLI，而不是一开始直接写 pywin32 ServiceFramework。

原因：

1. WinSW 可以把普通 CLI 稳定包装成 Windows Service，降低首版复杂度。
2. stdout/stderr、工作目录、环境变量、自动重启策略都可以通过 XML 配置。
3. 后续如果需要更深的 SCM 控制，再引入 pywin32 原生 service。

安装脚本职责：

1. 复制或引用 WinSW exe。
2. 生成服务 XML，设置 `PYTHONPATH`、工作目录、日志目录和服务参数。
3. 调用 `winsw.exe install` 与 `winsw.exe start`。

卸载脚本职责：

1. 调用 `winsw.exe stop`。
2. 调用 `winsw.exe uninstall`。
3. 保留日志和配置，避免误删排障信息。

## 4. Blob 协议设计

### 4.1 Container 划分

建议使用以下 container：

| Container | 用途 |
| --- | --- |
| `requests` | 客户端投递 request blob |
| `responses` | 服务写入 agent 输出、状态、最终结果 |
| `dead-letter` | 解析失败、权限失败、执行失败且不可重试的请求 |
| `session-state` | 可选，用于备份 session 元数据，不作为首版强依赖 |

### 4.2 Request 命名

用户要求 blob 以 `work-dir-name + timestamp` 命名。建议规范化为：

```text
requests/{workDirSafe}/{yyyyMMddTHHmmssfffZ}-{requestId}.json
```

示例：

```text
requests/q-gitroot-copilot-box/20260702T060110226Z-01J2REQ9J8Y4.json
```

设计理由：

1. `workDirSafe` 便于按目录 prefix 扫描和分区。
2. timestamp 保持人类可读与时间排序。
3. requestId 保证同一毫秒内不冲突，并支持幂等。
4. 原始 work dir 不直接放入 blob name，避免泄露完整路径和引入非法字符。

### 4.3 Request JSON Schema 首版草案

```json
{
  "protocolVersion": "2026-07-02",
  "requestId": "01J2REQ9J8Y4",
  "createdAt": "2026-07-02T06:01:10.226Z",
  "client": {
    "type": "android",
    "userId": "user-or-device-id"
  },
  "workDir": "Q:\\gitroot\\copilot-box",
  "session": {
    "mode": "auto",
    "sessionId": null
  },
  "agent": {
    "model": null,
    "prompt": "请分析当前项目并生成报告",
    "attachments": []
  },
  "response": {
    "container": "responses",
    "prefix": "q-gitroot-copilot-box/20260702T060110226Z-01J2REQ9J8Y4"
  }
}
```

`session.mode` 建议支持：

| Mode | 行为 |
| --- | --- |
| `new` | 强制创建新 session |
| `continue` | 必须继续指定 `sessionId`，不存在则失败 |
| `auto` | 优先继续指定 session；未指定时按 work dir 找最近活跃 session；找不到则新建 |

### 4.4 Response 命名

为了支持客户端扫描和近实时显示，建议每个 request 使用独立 response prefix：

```text
responses/{workDirSafe}/{timestamp}-{requestId}/000001.status.json
responses/{workDirSafe}/{timestamp}-{requestId}/000002.agent.delta.json
responses/{workDirSafe}/{timestamp}-{requestId}/000003.tool.call.json
responses/{workDirSafe}/{timestamp}-{requestId}/999999.final.json
```

事件格式示例：

```json
{
  "protocolVersion": "2026-07-02",
  "requestId": "01J2REQ9J8Y4",
  "sessionId": "sess_abc",
  "sequence": 2,
  "type": "agent.delta",
  "createdAt": "2026-07-02T06:01:12.000Z",
  "payload": {
    "text": "正在读取项目结构..."
  }
}
```

最终结果：

```json
{
  "protocolVersion": "2026-07-02",
  "requestId": "01J2REQ9J8Y4",
  "sessionId": "sess_abc",
  "type": "final",
  "status": "succeeded",
  "summary": "已完成分析",
  "reportUrl": "https://example.azurestaticapps.net/reports/01J2REQ9J8Y4/",
  "completedAt": "2026-07-02T06:05:00.000Z"
}
```

### 4.5 Request 领取与幂等

服务扫描 `requests` 后不能直接执行，必须先尝试获取 blob lease：

1. `list_blobs` 找到候选 request。
2. 对 request blob acquire lease。
3. 成功拿到 lease 的 worker 才能处理。
4. 写入 `responses/.../000001.status.json` 表示 accepted。
5. 执行期间周期性 renew lease。
6. 成功后写 final response，并标记本地 request 状态为 completed。
7. 失败且可重试时释放 lease；不可重试时复制 request 到 `dead-letter` 并写 final failed。

幂等策略：

1. requestId 是全局幂等键。
2. 本地 SQLite 记录 requestId、blob etag、lease 状态、处理结果。
3. 如果重复扫描到已完成 request，直接忽略或补写 final response。

### 4.6 Azure Storage 认证与授权

服务端推荐使用 Azure Identity 默认凭据链，并在生产环境绑定 Managed Identity。该身份只需要以下最小权限：

| Scope | Role |
| --- | --- |
| `requests` container | `Storage Blob Data Reader` 与 lease 所需写权限；实际可用 `Storage Blob Data Contributor` |
| `responses` container | `Storage Blob Data Contributor` |
| `dead-letter` container | `Storage Blob Data Contributor` |
| `session-state` container | `Storage Blob Data Contributor`，如果启用该 container |

Android 客户端推荐通过一个极小的认证 broker 获取短期 SAS：

1. 客户端先用用户身份登录 broker。
2. broker 根据用户、设备、work dir allowlist 和 request scope 签发短期 SAS。
3. request SAS 只允许 `create/write` 到指定 prefix。
4. response SAS 只允许 `read/list` 指定 response prefix。
5. SAS TTL 建议 5 到 30 分钟，并且所有 request 都带 `requestId` 方便吊销和审计。

如果不希望引入 broker，可以评估 Android 直接使用 Microsoft Entra ID 访问 Blob，但需要处理移动端 token、RBAC 粒度和 work dir 级授权映射。禁止把 Storage Account key 或长期 SAS 固化在 Android app 中。

## 5. Session 设计

### 5.1 Session 归属

session 的上下文由 work dir 决定，但 sessionId 仍然是显式对象。建议 session key：

```text
{workDirCanonicalHash}:{sessionId}
```

本地 session 元数据保存在 SQLite：

| 字段 | 说明 |
| --- | --- |
| `session_id` | Copilot Box 侧 session id |
| `work_dir` | canonical absolute path |
| `work_dir_hash` | 用于 blob prefix 和索引 |
| `copilot_session_ref` | Copilot SDK session 引用 |
| `created_at` | 创建时间 |
| `last_active_at` | 最近活跃时间 |
| `status` | active, idle, closed, failed |

### 5.2 新建或继续 Session 的决策

建议决策顺序：

1. `session.mode == new`：总是创建新 session。
2. `session.mode == continue`：必须存在 `session.sessionId`，且 work dir 匹配，否则失败。
3. `session.mode == auto` 且提供 sessionId：尝试继续该 session。
4. `session.mode == auto` 且未提供 sessionId：查找同 work dir 最近活跃且未过期 session。
5. 找不到可用 session：创建新 session。

建议默认 session TTL 为 24 小时，可配置。

### 5.3 并发控制

首版建议同一个 work dir 同时只允许一个 agent request 执行：

1. 避免同一目录的文件修改互相覆盖。
2. 简化 session 状态一致性。
3. 后续可以按 session 或 task 类型放宽。

实现方式：

1. 本地 SQLite 加 work dir 锁。
2. 或使用一个 `responses/{workDirSafe}/.lock` blob lease 做跨进程锁。
3. 单机首版优先 SQLite；多实例部署时改为 blob lease。

## 6. Work Dir 安全模型

request 中的 work dir 不能直接信任。服务必须：

1. 将路径 canonicalize，解析符号链接和 `..`。
2. 要求路径位于配置的 allowlist root 中。
3. 拒绝 UNC 路径、系统目录、用户 profile 敏感目录，除非显式允许。
4. 限制 agent tool 权限，例如是否允许执行 shell、是否允许网络访问、是否允许 git push。
5. 记录每个 request 的 userId、workDir、sessionId 和关键 tool 操作。

示例配置：

```toml
[workdirs]
allowed_roots = [
  "Q:\\gitroot",
  "D:\\workspaces"
]
default_root = "Q:\\gitroot"
```

## 7. GitHub Copilot SDK 集成

建议在代码中引入一个适配层，而不是让业务逻辑直接依赖 SDK：

```text
BlobRequestProcessor
    -> SessionManager
    -> CopilotAgentAdapter
        -> GitHub Copilot SDK
```

`CopilotAgentAdapter` 需要提供：

1. `create_session(work_dir, options) -> session`
2. `resume_session(session_ref) -> session`
3. `send_message(session, prompt, attachments) -> event stream`
4. `cancel(session, request_id)`
5. `close(session)`

这样做的原因：

1. GitHub Copilot SDK 的语言、包名和 API 可能变化。
2. 适配层便于单元测试 request/session/blob 协议。
3. 未来可以切换为 CLI bridge、Node sidecar 或 Python SDK。

待确认点：当前项目是 Python，但 GitHub Copilot SDK 的正式可用形态需要确认。如果 SDK 首发是 Node/TypeScript，建议 Python service 通过本地 sidecar 进程或 gRPC/stdio bridge 调用。

## 8. Agent Report Workspace

### 8.1 目标

复杂报告不建议全部塞进 response blob。Agent 可以把 Markdown/HTML 报告写入一个独立 GitHub repo：

```text
copilot-box-reports/
  reports/
    {requestId}/
      index.md
      index.html
      assets/
```

写入后 push 到默认分支或专用分支，触发 GitHub Actions 部署到 Azure Static Web Apps。

### 8.2 写入策略

首版建议：

1. 服务拥有一个专门的 GitHub token 或 GitHub App installation token。
2. 每个 request 写入 `reports/{requestId}`。
3. 小报告直接 commit 到 main。
4. 大报告或需要审核的报告走 PR。
5. final response 中返回 `reportUrl` 和 Git commit SHA。

### 8.3 Static Web Apps 认证

Static Web Apps 必须禁止匿名访问。建议配置 `staticwebapp.config.json`：

```json
{
  "routes": [
    {
      "route": "/reports/*",
      "allowedRoles": ["authenticated"]
    },
    {
      "route": "/*",
      "allowedRoles": ["authenticated"]
    }
  ],
  "responseOverrides": {
    "401": {
      "redirect": "/.auth/login/github",
      "statusCode": 302
    }
  }
}
```

如果 Android 客户端需要内嵌 WebView 展示报告，需要提前确认认证方式：

1. GitHub 登录。
2. Microsoft Entra ID 登录。
3. Static Web Apps custom auth。
4. 由后端签发短期访问链接，但这会改变“禁止匿名访问”的语义。

## 9. 配置设计

建议使用 TOML 配置文件：

```toml
[storage]
account_url = "https://<account>.blob.core.windows.net"
request_container = "requests"
response_container = "responses"
dead_letter_container = "dead-letter"
poll_interval_seconds = 5

[identity]
mode = "managed_identity"

[sessions]
state_dir = "C:\\ProgramData\\copilot-box\\state"
ttl_seconds = 86400
max_concurrent_requests = 1

[workdirs]
allowed_roots = ["Q:\\gitroot"]

[agent]
adapter = "github_copilot_sdk"
model = "" # 空字符串表示使用 Copilot 账号/运行时默认模型

[reports]
enabled = true
repo = "owner/copilot-box-reports"
branch = "main"
base_path = "reports"
static_web_app_base_url = "https://<app>.azurestaticapps.net"
```

## 10. 错误处理与状态

每个 request 至少产生以下状态之一：

| 状态 | 含义 |
| --- | --- |
| `accepted` | 服务已领取 request |
| `running` | agent 正在执行 |
| `succeeded` | 成功完成 |
| `failed_retryable` | 可重试失败 |
| `failed_terminal` | 不可重试失败 |
| `cancelled` | 被取消 |

错误 response 必须包含：

1. 错误类型。
2. 可给客户端展示的 message。
3. 内部 correlationId。
4. 是否可重试。
5. 如果进入 dead-letter，提供 dead-letter blob name。

## 11. 可观测性

首版建议：

1. Windows Event Log：记录服务启动、停止、致命错误。
2. 文件日志：按天滚动，放在 `C:\ProgramData\copilot-box\logs`。
3. Blob response events：给客户端展示 request 级进度。
4. correlationId：贯穿 request blob、response blob、日志、report commit。
5. 指标：poll latency、request duration、success/failure count、active sessions。

## 12. 部署与升级

建议目录：

```text
C:\Program Files\copilot-box\
  app\
  scripts\
  service\
C:\ProgramData\copilot-box\
  config.toml
  state\
  logs\
```

升级策略：

1. 停止服务。
2. 备份 config/state。
3. 安装新 wheel 或替换 venv。
4. 执行配置迁移。
5. 启动服务并写 health response。

## 13. 首版里程碑

1. 项目初始化：pyproject、CLI 入口、设计文档、服务脚本骨架。
2. Blob request/response 协议：schema、轮询、lease、幂等记录。
3. SessionManager：work dir 校验、session 创建/继续策略、本地 SQLite。
4. CopilotAgentAdapter：接入 GitHub Copilot SDK 或 sidecar。
5. Windows Service：WinSW 安装卸载、日志、自动重启。
6. Report Workspace：生成报告、push repo、GitHub Actions、Static Web Apps auth。
7. Android client 对接：request 投递、response 扫描、报告页打开。

## 14. 需要进一步确认的问题

1. GitHub Copilot SDK 的目标接入形态是什么：Python SDK、Node/TypeScript SDK，还是允许通过 Copilot CLI/sidecar 间接调用？
2. Android 客户端是否接受“认证 broker 签发短期 SAS”的推荐方案？如果不接受，需要在 Entra ID 直连和其他授权方式之间选择。
3. response 是否需要 token 级别流式输出，还是 request 完成后一次性写 final blob 即可？
4. `auto` session 策略中，未指定 sessionId 时是否应该自动继续最近 session，还是为了安全总是新建？
5. 同一 work dir 是否允许并发多个 request？首版建议不允许。
6. Windows Service 包装方案是否接受 WinSW？如果必须纯 Python 原生服务，需要改为 pywin32。
7. Report Workspace 是直接 push main，还是每次生成 PR 后由人工或 Action 合并？
8. Static Web Apps 的认证提供方偏好是什么：GitHub、Microsoft Entra ID，还是自定义认证？
