# copilot-box 文档

`copilot-box` 是一个可包装为 Windows Service 的命令行应用，用于通过 Azure Blob Storage 接收远程请求，并使用 GitHub Copilot SDK 在指定 work dir 中运行 agent session。

```{toctree}
:maxdepth: 2
:caption: 目录

usage
design
```

## 快速入口

1. 先阅读 {doc}`usage`，了解如何安装依赖、下载 Copilot runtime、发送 prompt、创建或继续 session。
2. 再阅读 {doc}`design`，了解 Blob 协议、Windows Service、session、report workspace 和 GitHub Pages/Static Web Apps 相关设计。
