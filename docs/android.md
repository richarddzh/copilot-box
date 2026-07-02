# Android 客户端

## 1. 目标

Android 客户端通过 broker WebSocket 与 backend worker 通信。UI 分为连接配置页和聊天页：用户先在连接配置页填写 broker URL/token，再从 worker 上报的 work dir 白名单中选择运行位置，并选择“继续现有 session”或“在该 work dir 新建 session”；也可以从 broker 返回的 active running session 列表中直接加入正在运行的 session。进入聊天页后只显示聊天内容、状态和输入框。

Agent 输出以流式 `agent.delta` 实时追加到 assistant 气泡中，并按 Markdown 渲染；`agent.final` 到达后用完整 Markdown 内容校正气泡。如果 final 返回 `reportPath`，客户端会通过 broker 请求 backend report workspace 中的文件并显示。

## 2. 项目位置

Android 项目位于：

```text
android\
  settings.gradle.kts
  build.gradle.kts
  app\
```

包名：

```text
com.github.richarddzh.copilotbox
```

## 3. 本地 CLI 构建环境

不需要完整 Android Studio。Windows 本地 CLI 构建可以使用仓库脚本自动下载工具到 `.tools\android-cli`：

```powershell
Set-Location Q:\gitroot\copilot-box
.\android\scripts\setup-cli.ps1
.\android\scripts\build-debug.ps1
```

输出 APK：

```text
android\app\build\outputs\apk\debug\app-debug.apk
```

## 4. 使用客户端

启动 app 后填写：

| 字段 | 示例 | 说明 |
| --- | --- | --- |
| Broker WebSocket URL | `wss://<app-name>.azurewebsites.net/ws/client` | broker client endpoint |
| Client token | `<client-token>` | broker client shared token |

点击 **Connect** 后，broker 会返回已连接 worker 以及每个 worker 的 `allowedWorkDirs`。客户端从下拉框选择：

| 字段 | 说明 |
| --- | --- |
| Worker | 要使用的 backend worker |
| Work dir | worker 配置白名单中的目录 |
| Session | 继续现有 session，或在该 work dir 新建 session |
| Message | 用户 prompt |

如果 broker 返回 `activeSessions`，连接页会显示 **Active running sessions** 下拉框。点击 **Join active session** 后，客户端发送 `session.join`，收到 `session.snapshot` 后进入聊天页，显示原始 prompt 与 `outputSoFar`，并继续接收同一 request 的后续 `agent.delta` / `agent.final`。`agent.final` 返回 `sessionId` 后，之后在该聊天页发送的新 prompt 会以 `session.mode = "continue"` 和该 `sessionId` 继续同一个 Copilot session。

进入聊天页并点击 **Send** 后：

1. 客户端立即添加用户聊天气泡。
2. Broker accepted 后创建 assistant 气泡。
3. 收到 `agent.delta` 时实时追加并刷新 Markdown。
4. 收到 `agent.final` 时用完整 Markdown 覆盖校正。
5. 如存在 `reportPath`，自动发送 `report.read` 并显示 `report.content`。

聊天页提供 **Exit to connection settings**，用于断开当前 WebSocket、清空当前聊天状态并返回连接配置页，从而重新连接 broker 或重新选择 worker/work dir/session action。

## 5. Emulator 测试

首次创建 AVD：

```powershell
.\android\scripts\create-emulator.ps1
```

启动 emulator 并等待 boot 完成：

```powershell
.\android\scripts\start-emulator.ps1
```

构建并安装 APK：

```powershell
.\android\scripts\install-debug.ps1
```

如果已经手动构建过 APK：

```powershell
.\android\scripts\install-debug.ps1 -SkipBuild
```

## 6. GitHub Actions 构建与 Release

仓库包含 `.github\workflows\android.yml`。Workflow 会构建 `assembleDebug`，上传 `copilot-box-android-debug.apk` artifact；推送 `v*` 或 `android-v*` tag 时会创建 GitHub Release。
