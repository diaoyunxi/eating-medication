# 老人用药管理智能助手

> 版本：v2.1.0 | 仓库：[diaoyunxi/eating-medication](https://github.com/diaoyunxi/eating-medication)

一套面向独居老人的智能用药管理系统，包含**老人端**、**服务端**、**家属看护端**三个模块，覆盖用药提醒、药品识别、AI 语音问答、服药记录上传、家属沟通、紧急呼叫、库存管理等完整场景。适用于行空板 M10 及通用 Windows/Linux 设备。

---

## 功能概览

| 模块 | 定位 | 主要功能 |
|------|------|----------|
| `elderly_assistant` | 老人端（TUI/GUI） | 按时用药提醒、摄像头识别药名、AI 语音问答、服药画面上传、库存管理、家属聊天、紧急呼叫 |
| `server` | 后端服务（FastAPI） | 用户认证、用药计划管理、服药日志、药品库存、AI 服务、WebSocket 实时通信、京东比价 |
| `family_monitor` | 家属看护端（FastAPI Web） | 远程查看老人服药记录、实时聊天、用药计划配置、管理后台 |

---

## HTTPS 与 Cloudflare 隧道

本系统**不再使用本地证书文件**，所有模块均以纯 HTTP 监听，HTTPS 由 **Cloudflare 隧道（cloudflared）边缘自动配置**：

- 本地服务监听 HTTP，cloudflared 建立加密隧道到 Cloudflare 边缘节点。
- 用户通过 `https://my-website.ccwu.cc` 访问，SSL 在 Cloudflare 边缘终止，流量经隧道转发到本地 HTTP 服务。
- 两个服务通过路径前缀区分转发：
  - `https://my-website.ccwu.cc/eating-medication/server` → 服务端（本地端口 1059）
  - `https://my-website.ccwu.cc/eating-medication/family` → 家属看护端（本地端口 4430）
- 应用内置路径前缀中间件，自动剥离/补回前缀，本地直连（前缀为空）与隧道访问均兼容。

---

## 项目结构

```
.
├── elderly_assistant/      # 老人端
│   ├── main.py             # 程序入口
│   ├── updater.py          # 自动更新检查模块
│   ├── config.yaml         # 配置文件
│   ├── install.py          # 依赖自动安装
│   ├── core/               # 核心业务逻辑
│   ├── services/           # 底层服务（语音、蜂鸣器、OCR、AI、HTTP）
│   ├── tui/                # 终端界面
│   ├── utils/              # 工具模块
│   └── data/               # 运行时数据（含空模板）
├── server/                 # 服务端
│   ├── main.py             # 程序入口
│   ├── updater.py          # 自动更新检查模块
│   ├── app/                # FastAPI 应用
│   │   ├── main.py         # 应用实例
│   │   ├── api/            # API 路由
│   │   ├── core/           # 配置、认证、数据库
│   │   ├── models/         # 数据模型
│   │   ├── schemas/        # 数据校验
│   │   ├── services/       # 业务服务
│   │   ├── tasks/          # 定时任务
│   │   └── websocket/      # WebSocket 管理
│   ├── tests/              # 测试用例
│   └── install.py
├── family_monitor/         # 家属看护端
│   ├── main.py             # 程序入口
│   ├── updater.py          # 自动更新检查模块
│   ├── config.json         # 配置文件
│   ├── core/               # 认证、会话、配置
│   ├── routes/             # 路由（首页、聊天、认证、管理）
│   ├── static/             # 静态资源
│   ├── templates/          # 页面模板
│   └── install.py
├── history.md              # 项目开发历史记录
├── VERSION                 # 当前版本号
└── .gitignore
```

---

## 自动更新机制

所有模块均内置**启动时自动更新检查**功能（`updater.py`），符合"上传到云端的代码均需有自动更新功能，启动时检查"的要求。

- 启动时通过 GitHub API 查询最新 Release/Tag 版本号。
- 发现新版本时打印提示（当前版本、最新版本、下载地址），**非阻塞**，不影响主程序运行。
- 若当前目录为 git 仓库，可配置 `auto_pull=True` 执行 `git pull` 自动更新。
- 网络异常或检查失败时静默处理，不中断启动。

各模块版本统一由 `VERSION` 文件管理，当前为 **v2.1.0**。

---

## 快速开始

### 环境要求
- Python 3.6+
- 操作系统：Windows / Linux（含行空板 M10 等 ARM 设备）
- 可选硬件：USB 摄像头、麦克风、音箱/蜂鸣器
- OCR 识别需安装 Tesseract（可选）

### 老人端
```bash
cd elderly_assistant
python install.py          # 自动安装依赖
# config.yaml 默认服务器地址已配置为公网域名，可在热点配网页面修改
python main.py             # 启动（--debug 启用调试模式）
```

### 服务端
```bash
cd server
python install.py          # 自动安装依赖
# 编辑 .env 配置数据库、密钥等（.env 不上传，需自行创建）
python main.py             # 启动服务（本地端口 1059，HTTP 监听）
```

### 家属看护端
```bash
cd family_monitor
python install.py          # 自动安装依赖
# 编辑 .env 和 config.json 配置服务器地址等
python main.py             # 启动服务（本地端口 4430，HTTP 监听）
```

> **注意**：`.env`、数据库（`*.db`）等敏感文件已通过 `.gitignore` 排除，不会上传至仓库，部署时需自行配置。HTTPS 由 Cloudflare 隧道处理，无需本地证书。

---

## 配置说明

| 模块 | 配置文件 | 关键配置项 |
|------|----------|------------|
| elderly_assistant | `config.yaml` | 服务器地址（默认公网域名）、AI 接口、摄像头、语音引擎、蜂鸣器 |
| server | `.env` | 数据库、密钥、智谱 AI、京东比价、PATH_PREFIX |
| family_monitor | `.env` + `config.json` | 服务器地址、会话密钥、PATH_PREFIX |

路径前缀配置（`PATH_PREFIX`）：
- family_monitor 默认 `/eating-medication/family`
- server 默认 `/eating-medication/server`
- 本地直连时设为空字符串即可

各配置文件均含合理默认值或占位符，部署时按实际环境修改即可。

---

## 版本历史

- **v2.1.0**（2026-06-30）：移除本地 SSL 证书机制，改为 Cloudflare 隧道边缘自动配置 HTTPS；新增路径前缀支持（`/eating-medication/server`、`/eating-medication/family`）；老人端默认服务器地址改为公网域名；清除项目内部代号字样。
- **v2.0.0**（2026-06-30）：重大升级，从单文件吃药提醒工具升级为完整三端系统（老人端 + 服务端 + 家属看护端），新增自动更新检查、AI 语音问答、药品识别、家属聊天、紧急呼叫、库存管理等功能。
- **v1.0.0**：轻量级用药提醒工具（单文件），支持定时提醒和用药记录。

详细开发历史见 [`history.md`](./history.md)。

---

## 许可

本项目仅供学习和个人使用，药品信息及健康建议请以医生指导为准。
