> [← 返回文档目录](../README.md) ｜ 本分册由 `README.md` 的「HTTPS 与 Cloudflare 隧道」章节拆分而来。

## HTTPS 与 Cloudflare 隧道

本系统**不再使用本地证书文件**，所有模块均以纯 HTTP 监听，HTTPS 由 **Cloudflare 隧道（cloudflared）边缘自动配置**：

- 本地服务监听 HTTP，cloudflared 建立加密隧道到 Cloudflare 边缘节点。
- 用户通过 `https://your-domain.example.com` 访问（部署时替换为实际域名），SSL 在 Cloudflare 边缘终止，流量经隧道转发到本地 HTTP 服务。
- 两个服务通过路径前缀区分转发：
  - `https://your-domain.example.com/eating-medication/server` → 服务端（本地端口 `1059`）
  - `https://your-domain.example.com/eating-medication/family` → 家属看护端（本地端口 `4430`）
- 应用内置路径前缀中间件，自动剥离/补回前缀，本地直连（前缀为空）与隧道访问均兼容。

---
