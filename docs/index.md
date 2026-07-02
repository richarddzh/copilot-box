# copilot-box 文档

`copilot-box` 是一个可包装为 Windows Service 的命令行 backend，通过 broker WebSocket 接收 Android 客户端请求，并使用 GitHub Copilot SDK 在配置白名单中的 work dir 里运行 agent session。

```{toctree}
:maxdepth: 2
:caption: 目录

usage
android
broker
design
```

## 快速入口

1. 先阅读 {doc}`usage`，了解如何安装依赖、下载 Copilot runtime、运行 backend worker。
2. 再阅读 {doc}`design`，了解 WebSocket 协议、单活跃 session、聊天式流式输出和 report workspace 设计。
