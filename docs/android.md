# Android 客户端

## 1. 目标

Android 客户端用于把用户 prompt 写入 Azure Storage Account 的 `requests` container，并通过轮询 `responses` container 获得 agent 输出。当前首版客户端使用 **container SAS URL** 接入 Blob Storage，方便在没有 broker 的阶段做端到端测试。

后续生产版本建议改为：

1. Android app 登录受信任 broker。
2. broker 根据用户、设备、work dir 权限签发短期 SAS。
3. Android app 只拿到最小权限 SAS：request container 只允许 create/write，response container 只允许 list/read 指定 prefix。

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

1. Eclipse Temurin JDK 17。
2. Gradle 8.10.2。
3. Android command-line tools。
4. Android SDK Platform 35。
5. Android Build Tools 35.0.0。

首次准备环境：

```powershell
Set-Location Q:\gitroot\copilot-box
.\android\scripts\setup-cli.ps1
```

构建 debug APK：

```powershell
.\android\scripts\build-debug.ps1
```

输出 APK：

```text
android\app\build\outputs\apk\debug\app-debug.apk
```

该 APK 是 debug-signed，可以直接安装到 emulator 或测试设备。

## 4. Emulator 测试

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

这些脚本不会把 JDK、SDK、Gradle 或 AVD 写入 Git；相关本地产物会放在 `.tools\android-cli`、`android\local.properties` 和 Android 用户目录中。

## 5. GitHub Actions 构建与 Release

仓库包含 `.github\workflows\android.yml`。

触发方式：

1. push 到 `main` 或 `master` 且修改了 `android/**`。
2. pull request 修改了 `android/**`。
3. 手动 `workflow_dispatch`。
4. 推送 `v*` 或 `android-v*` tag。

workflow 会：

1. 安装 JDK 17。
2. 安装 Android SDK。
3. 使用 Gradle 8.10.2。
4. 构建 `assembleDebug`。
5. 上传 `copilot-box-android-debug.apk` artifact。
6. 如果是 tag 触发，则创建 GitHub Release，并附加 `copilot-box-android-debug.apk`。

发布示例：

```powershell
git tag android-v0.1.0
git push origin android-v0.1.0
```

Release 页面会出现可下载、可安装的 debug APK。

## 6. Storage Account 认证方式

Android 客户端当前使用 **container SAS URL** 访问 Storage Account。客户端不直接使用 Storage Account key，也不内置长期凭据。

需要填写两个 SAS URL：

| SAS URL | 权限 | 用途 |
| --- | --- | --- |
| `requests` container SAS URL | `create` / `write` | 上传 request blob |
| `responses` container SAS URL | `list` / `read` | 轮询并下载 final response blob |

测试阶段可以手动生成短期 SAS；生产阶段推荐由 auth broker 签发 5 到 30 分钟有效期的最小权限 SAS。

示例生成 `requests` SAS：

```powershell
$expiry = (Get-Date).ToUniversalTime().AddHours(1).ToString("yyyy-MM-ddTHH:mmZ")

az storage container generate-sas `
  --account-name <storage-account> `
  --name requests `
  --permissions cw `
  --expiry $expiry `
  --auth-mode login `
  --as-user `
  --output tsv
```

示例生成 `responses` SAS：

```powershell
az storage container generate-sas `
  --account-name <storage-account> `
  --name responses `
  --permissions rl `
  --expiry $expiry `
  --auth-mode login `
  --as-user `
  --output tsv
```

拼接成完整 URL 后填入 Android app：

```text
https://<storage-account>.blob.core.windows.net/requests?<sas-token>
https://<storage-account>.blob.core.windows.net/responses?<sas-token>
```

## 7. 生成测试 SAS

当前客户端需要两个 container SAS URL：

1. `requests` container SAS URL：需要 create/write 权限。
2. `responses` container SAS URL：需要 read/list 权限。

示例 URL 形态：

```text
https://<storage-account>.blob.core.windows.net/requests?<sas-token>
https://<storage-account>.blob.core.windows.net/responses?<sas-token>
```

> 不要把长期 SAS、account key 或其他秘密提交到 Git。客户端 UI 会把输入保存在 Android 本机 SharedPreferences 中，仅用于本地测试便利。

## 8. 使用客户端

启动 app 后填写：

| 字段 | 示例 | 说明 |
| --- | --- | --- |
| Requests container SAS URL | `https://<storage-account>.blob.core.windows.net/requests?...` | 用于上传 request blob |
| Responses container SAS URL | `https://<storage-account>.blob.core.windows.net/responses?...` | 用于 list/download response blob |
| Request prefix | `manual-test/android/` | request blob 前缀；服务端 `storage.request_prefix` 需要匹配或为空 |
| Remote work dir | `Q:\gitroot\copilot-box` | Windows service 所在机器上的工作目录 |
| Session mode | `auto`、`new` 或 `continue` | 对应服务端 session 策略 |
| Session id | 可空 | `continue` 模式时必填；成功响应后 app 会保存最新 session id |
| Prompt | `请只回复 pong，不要修改文件` | 用户 prompt |

点击 **Send request** 后，客户端会：

1. 生成 request JSON。
2. 上传到 `requests/{prefix}/{timestamp}-{requestId}.json`。
3. 轮询 `responses/{prefix}/{timestamp}-{requestId}/999999.final.json`。
4. 显示 final response 中的 `status`、`sessionId` 和 `output`。

## 9. 服务端配套配置

如果 Android 使用 `manual-test/android/` 作为 request prefix，服务端配置可以设置：

```toml
[storage]
account_url = "https://<storage-account>.blob.core.windows.net"
request_container = "requests"
response_container = "responses"
dead_letter_container = "dead-letter"
request_prefix = "manual-test/android/"
poll_interval_seconds = 5
max_requests_per_poll = 10
```

启动服务端轮询：

```powershell
.\.venv\Scripts\python.exe -m copilot_box service run `
  --config .\config\copilot-box.local.toml
```

调试时只处理一轮：

```powershell
.\.venv\Scripts\python.exe -m copilot_box service once `
  --config .\config\copilot-box.local.toml
```

## 10. 当前实现范围

已实现：

1. 原生 Android Kotlin app。
2. 基于 SAS URL 的 Azure Blob REST 调用。
3. request JSON 生成与上传。
4. response final blob 轮询。
5. session id 保存与复用输入。
6. CLI 构建脚本和 emulator 启动/安装脚本。
7. GitHub Actions APK artifact 与 tag release。

暂未实现：

1. broker 登录与短期 SAS 自动获取。
2. 流式展示 accepted/running/agent delta events。
3. work dir 列表发现。
4. Android 端安全存储和设备绑定。
5. UI 美化和错误分类展示。
