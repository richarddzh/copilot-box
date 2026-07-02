# copilot-box

`copilot-box` 是一个面向 Windows Service 部署的 Python CLI/backend。Backend worker 通过 GitHub Copilot SDK 在配置白名单中的 work dir 里运行 agent session；Android 客户端通过 Azure Web App 上的 FastAPI broker 建立 WebSocket，实时查看 Markdown response stream，并以聊天界面继续或新建 session。

设计文档见 [`docs\design.md`](docs\design.md)。

## 本地运行

```powershell
python -m copilot_box --help
python -m copilot_box version
```

下载 GitHub Copilot SDK runtime：

```powershell
python -m copilot download-runtime
```

本地直接发送一个 prompt：

```powershell
python -m copilot_box service prompt `
  --config .\config\copilot-box.example.toml `
  --work-dir Q:\gitroot\copilot-box `
  --prompt "请用 Markdown 总结当前项目" `
  --json
```

启动 backend worker，连接 broker：

```powershell
python -m copilot_box service run --config .\config\copilot-box.example.toml
```

## Broker

Broker 是 FastAPI WebSocket 服务：

| Endpoint | 用途 |
| --- | --- |
| `GET /healthz` | 健康检查 |
| `WS /ws/client` | Android client 连接 |
| `WS /ws/worker` | Windows backend worker 连接 |

本地启动：

```powershell
.\.venv\Scripts\python.exe -m uvicorn copilot_box_broker.main:app `
  --app-dir .\broker `
  --host 127.0.0.1 `
  --port 8000
```

## Android

Android 客户端项目位于 [`android`](android)，使用文档见 [`docs\android.md`](docs\android.md)。

CLI 构建 debug APK：

```powershell
.\android\scripts\build-debug.ps1
```

## Windows Service

推荐使用 [WinSW](https://github.com/winsw/winsw) 包装 CLI 进程：

```powershell
.\scripts\install-service.ps1 -WinSWPath C:\tools\WinSW-x64.exe
.\scripts\uninstall-service.ps1
```

服务主体命令：

```powershell
python -m copilot_box service run --config .\config\copilot-box.example.toml
```

## 构建文档

```powershell
.\.venv\Scripts\python.exe -m pip install -e .[docs]
.\.venv\Scripts\sphinx-build.exe -b html .\docs .\docs\_build\html
```
