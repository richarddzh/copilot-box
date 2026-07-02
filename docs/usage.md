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
