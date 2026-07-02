# copilot-box

`copilot-box` 是一个面向 Windows Service 部署的 Python CLI 项目骨架。它的目标是从 Azure Blob Storage 拉取远程请求，调用 GitHub Copilot SDK 驱动 agent 在指定 work dir 中工作，并通过 Blob 与报告站点返回结果。

设计文档见 [`docs\design.md`](docs\design.md)。

HTML 文档站点使用 Sphinx 构建，入口见 [`docs\index.md`](docs\index.md)。

## 本地运行

```powershell
python -m copilot_box --help
python -m copilot_box version
```

## 调用 Copilot SDK

安装依赖后先下载 SDK runtime：

```powershell
python -m copilot download-runtime
```

发送一个 prompt，并让服务按 work dir 自动创建或继续 session：

```powershell
python -m copilot_box service prompt `
  --config .\config\copilot-box.example.toml `
  --work-dir Q:\gitroot\copilot-box `
  --prompt "请总结当前目录" `
  --json
```

返回 JSON 中的 `sessionId` 可用于后续 `--session-mode continue --session-id <id>`；不传 session id 时，`auto` 会继续同一 work dir 最近活跃的 session。

## 处理 Azure Blob Storage request

`service once` 会扫描 `storage.request_container`，领取一个或多个 request blob，调用 agent，并把状态和最终结果写入 `storage.response_container`：

```powershell
.\.venv\Scripts\python.exe -m copilot_box service once `
  --config .\config\copilot-box.example.toml
```

Windows Service 主循环使用：

```powershell
.\.venv\Scripts\python.exe -m copilot_box service run `
  --config .\config\copilot-box.example.toml
```

## Windows Service 脚本

当前推荐使用 [WinSW](https://github.com/winsw/winsw) 包装 CLI 进程：

```powershell
.\scripts\install-service.ps1 -WinSWPath C:\tools\WinSW-x64.exe
.\scripts\uninstall-service.ps1
```

服务主体命令预留为：

```powershell
python -m copilot_box service run --config .\config\copilot-box.example.toml
```

## 构建文档

```powershell
.\.venv\Scripts\python.exe -m pip install -e .[docs]
.\.venv\Scripts\sphinx-build.exe -b html .\docs .\docs\_build\html
```

推送到 GitHub 默认分支后，`.github\workflows\docs.yml` 会构建并发布到 GitHub Pages。
