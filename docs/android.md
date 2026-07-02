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

## 3. 构建环境

需要安装：

1. JDK 17 或更高版本。
2. Android Studio。
3. Android SDK Platform 35。
4. Android Gradle Plugin 8.7.3 对应的 Gradle 环境。

在 Android Studio 中选择 **Open**，打开仓库下的 `android` 目录。

命令行构建示例：

```powershell
Set-Location Q:\gitroot\copilot-box\android
.\gradlew.bat assembleDebug
```

如果当前目录没有 Gradle wrapper，可以先用 Android Studio 同步项目，或在安装 Gradle 后执行：

```powershell
gradle wrapper
.\gradlew.bat assembleDebug
```

## 4. 生成测试 SAS

当前客户端需要两个 container SAS URL：

1. `requests` container SAS URL：需要 create/write 权限。
2. `responses` container SAS URL：需要 read/list 权限。

示例 URL 形态：

```text
https://zhdonsg.blob.core.windows.net/requests?<sas-token>
https://zhdonsg.blob.core.windows.net/responses?<sas-token>
```

> 不要把长期 SAS、account key 或其他秘密提交到 Git。客户端 UI 会把输入保存在 Android 本机 SharedPreferences 中，仅用于本地测试便利。

## 5. 使用客户端

启动 app 后填写：

| 字段 | 示例 | 说明 |
| --- | --- | --- |
| Requests container SAS URL | `https://zhdonsg.blob.core.windows.net/requests?...` | 用于上传 request blob |
| Responses container SAS URL | `https://zhdonsg.blob.core.windows.net/responses?...` | 用于 list/download response blob |
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

## 6. 服务端配套配置

如果 Android 使用 `manual-test/android/` 作为 request prefix，服务端配置可以设置：

```toml
[storage]
account_url = "https://zhdonsg.blob.core.windows.net"
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

## 7. 当前实现范围

已实现：

1. 原生 Android Kotlin app。
2. 基于 SAS URL 的 Azure Blob REST 调用。
3. request JSON 生成与上传。
4. response final blob 轮询。
5. session id 保存与复用输入。

暂未实现：

1. broker 登录与短期 SAS 自动获取。
2. 流式展示 accepted/running/agent delta events。
3. work dir 列表发现。
4. Android 端安全存储和设备绑定。
5. UI 美化和错误分类展示。
