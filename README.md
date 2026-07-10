# 老人用药管理智能助手

> 当前版本：**v2.6.0**（2026-07-08，新增删除用户 API 版本） | 仓库：[diaoyunxi/eating-medication](https://github.com/diaoyunxi/eating-medication)
> 版本号文件见 [`VERSION`](./VERSION)。

一套面向独居老人的智能用药管理系统，包含**老人端**、**服务端**、**家属看护端（子女端）**三个模块，覆盖用药提醒、药品识别、AI 语音问答、服药记录上传、家属沟通、紧急呼叫、库存管理等完整场景。适用于行空板 M10 及通用 Windows/Linux 设备。

---

## 目录

- [功能概览](#功能概览)
- [系统架构与网络请求流图](#系统架构与网络请求流图)
- [HTTPS 与 Cloudflare 隧道](#https-与-cloudflare-隧道)
- [项目结构](#项目结构)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [API 文档](#api-文档)
- [WebSocket 协议](#websocket-协议)
- [数据模型](#数据模型)
- [定时任务](#定时任务)
- [自动更新机制](#自动更新机制)
- [部署与运维](#部署与运维)
- [安全特性](#安全特性)
- [贡献与开发指南](#贡献与开发指南)
- [版本历史](#版本历史)
- [已知问题与待办](#已知问题与待办)
- [感谢贡献](#感谢贡献)
- [许可](#许可)

---

## 功能概览

| 模块 | 定位 | 主要功能 |
|------|------|----------|
| [`elderly_assistant`](./elderly_assistant) | 老人端（行空板 M10 GUI / TUI 备用） | 按时用药提醒、摄像头识别药名、AI 语音问答、服药画面上传、库存管理、家属聊天、紧急呼叫、热点配网 |
| [`server`](./server) | 服务端（FastAPI） | 用户认证、用药计划管理、服药日志、药品库存、AI 服务、WebSocket 实时通信、百度 OCR 药品识别、库存定时检查 |
| [`family_monitor`](./family_monitor) | 家属看护端（FastAPI Web） | 远程查看老人服药记录、实时聊天、用药计划配置、健康仪表板、管理后台 |

---

## 系统架构与网络请求流图

系统采用 **三端 + Cloudflare 边缘隧道** 架构。老人端与子女端均通过 HTTPS（Cloudflare 隧道）与服务端通信；子女端浏览器与老人端服务端的聊天 WebSocket 为直连；老人端本地另起一个热点配网 Web 服务。

### 三端网络请求总览图

下图三列从左到右分别为 **老人端**、**服务端**、**子女端**，箭头表示项目运行中所有网络请求的方向与用途。

```
┌──────────────────────┐        ┌──────────────────────┐        ┌──────────────────────┐
│       老人端          │        │       服务端          │        │       子女端          │
│  elderly_assistant   │        │       server          │        │  family_monitor      │
│  (行空板 M10 / TUI)   │        │  (FastAPI :1059)      │        │  (FastAPI Web :4430) │
│                      │        │                       │        │  浏览器 + BFF 后端    │
└──────────┬───────────┘        └──────────┬────────────┘        └──────────┬───────────┘
           │                               │                                │
           │  ① 启动：自动更新检查           │                                │  ① 启动：自动更新检查
           │  GET api.github.com/.../      │                                │  GET api.github.com/.../
           │  releases/latest ─────────►   │                                │  releases/latest ─────────►(GitHub)
           │                               │                                │
           │  ② 配网：设备注册              │                                │  ② 绑定设备：先校验后注册
           │  POST /api/v1/public/device/  │                                │  GET  /api/v1/public/device/
           │  register ─────────────────►  │                                │  check/{id} ─────────────►
           │                               │                                │  POST /api/v1/public/device/
           │                               │                                │  register ──────────────►
           │  ③ 运行：健康检查（每 10s）    │                                │
           │  GET /health ───────────────► │                                │  ③ 首页/各页渲染：设备状态
           │                               │                                │  GET /api/v1/public/device/
           │  ④ 运行：拉取用药计划（每60s） │                                │  status/{id} ─────────────►
           │  GET /api/v1/public/device/   │                                │
           │  schedule/{id} ─────────────► │                                │  ④ 用药设置页：拉取计划
           │                               │                                │  GET /api/v1/public/device/
           │  ⑤ 按钮确认：上报服药          │                                │  plans/{id} ───────────────►
           │  POST /api/v1/public/device/  │                                │
           │  message (type=medication)    │                                │  ⑤ 添加用药计划
           │  ──────────────────────────►  │  ⑤' 推送给家庭组 (WS)          │  POST /api/v1/public/device/
           │                               │  ─────────────────────────────►│  medication_plan ──────────►
           │  ⑥ 上传服药/药品照片          │                                │
           │  POST /api/upload ──────────► │                                │  ⑥ 删除用药计划
           │                               │                                │  DELETE /api/v1/public/device/
           │  ⑦ AI 问答（经服务端中转）     │  ⑦' 调用智谱 AI GLM-4          │  medication_plan/{id} ─────►
           │  POST /api/v1/public/ai/ask   │  POST api.zhipuai / ... ──►   │
           │  ──────────────────────────►  │  (第三方)                      │  ⑦ 提醒/记录/仪表板页
           │                               │                                │  GET /api/v1/medication/plans
           │  ⑧ 紧急呼叫                   │                                │  GET /api/v1/medication/history
           │  POST /api/v1/public/device/  │                                │  ──────────────────────────►
           │  message (type=emergency)     │                                │
           │  ──────────────────────────►  │                                │  ⑧ 健康检查（页面轮询）
           │                               │                                │  GET /health ──────────────►
           │  ⑨ 聊天 WebSocket（仅 TUI）   │                                │
           │  WS /ws/device/{id} ◄══════►  │  ⑨' 聊天 WS（浏览器直连）      │
           │                               │  ◄═════════════════════════════│  WS /api/v1/chat/ws/{user_id}
           │                               │                                │  （子女端浏览器 → 服务端，直连）
           │                               │                                │
           │  本地监听：热点配网服务        │                                │  本地监听：Web 页面服务
           │  0.0.0.0:8088 (HTTP)          │                                │  0.0.0.0:4430 (HTTP)
           │  热点 SSID: M10-Config        │                                │  浏览器访问 /login /dashboard ...
           └───────────────────────────────┴────────────────────────────────┴───────────────────────────────┘

           图例： ─────►  HTTP 请求      ◄════►  WebSocket 双向长连接      (第三方)  服务端向第三方发起的请求
```

### 网络请求清单（按方向分组）

#### 老人端 → 服务端（HTTP）

| # | 方法 | 路径（相对 `base_url`） | 用途 | 触发时机 |
|---|------|------------------------|------|----------|
| 1 | POST | `/api/v1/public/device/register` | 设备注册（提交 device_id / device_name） | 配网页面提交表单时 |
| 2 | GET | `/health` | 健康检查 / 连接状态探测 | 主循环每 10 秒 |
| 3 | GET | `/api/v1/public/device/schedule/{device_id}` | 拉取用药计划 | 启动后立即一次，之后每 60 秒轮询 |
| 4 | POST | `/api/v1/public/device/message` | 上报服药确认（`message_type=medication`） | 用户按下按钮 A 确认服药 |
| 5 | POST | `/api/v1/public/device/message` | 紧急呼叫（`message_type=emergency`） | 触发紧急求助 |
| 6 | POST | `/api/v1/public/device/message` | 聊天消息（`message_type=chat`，HTTP 备用） | TUI 聊天（备用链路） |
| 7 | POST | `/api/v1/public/ai/ask` | AI 问答（经服务端中转智谱 AI） | TUI 中用户输入问题 |
| 8 | POST | `/api/upload` | 上传服药/药品照片（multipart `file`） | TUI 确认服药 / 识别药品时 |

> 所有请求统一携带 `X-Device-ID` 请求头用于设备识别；公开接口仅通过 device_id 校验。

#### 老人端 → 服务端（WebSocket，仅 TUI 形态）

| # | 协议 | 路径 | 用途 |
|---|------|------|------|
| 9 | WS/WSS | `/ws/device/{device_id}` | 长连接实时收发家属端下发的聊天 / 提醒消息，断线每 5 秒重连 |

#### 老人端 → 第三方 / 本地

| # | 类型 | 目标 | 用途 |
|---|------|------|------|
| 10 | HTTP GET | `api.github.com/repos/diaoyunxi/eating-medication/releases/latest`（回退 `/tags`） | 启动时自动更新检查 |
| 11 | HTTP POST | `{ai.base_url}/chat/completions` | 直连大模型（OpenAI 兼容协议，配置 `ai.base_url` 为第三方时启用） |
| 12 | 本地子进程 | Tesseract 可执行文件 | OCR 识别（无网络请求） |
| 13 | 本地引擎 | pyttsx3 | TTS 语音合成（无网络请求） |
| 14 | TCP socket | `8.8.8.8:53`（可配置） | 互联网连通性探测 |
| 15 | 本地监听 | `0.0.0.0:8088` HTTP | 热点配网 Web 服务（用户连热点后访问 `10.0.0.1:8088`） |

#### 服务端 → 第三方

| # | 方法 | 目标 | 用途 | 触发时机 |
|---|------|------|------|----------|
| 20 | HTTP POST | 智谱 AI `glm-4.7-flash`（`zhipuai` SDK） | AI 健康问答 | `/ai/chat`、`/ai/chat/public`、`/public/ai/ask` 被调用 |
| 21 | HTTP GET + POST | 百度 OCR `aip.baidubce.com` | 药品图片识别药名（先换 token，再调通用文字识别） | `/vision/recognize` 被调用 |
| 22 | HTTP GET | `api.github.com/.../releases/latest` | 启动时自动更新检查（含 SHA256 资产校验） | 启动时 |
| 23 | 内部调度 | APScheduler `AsyncIOScheduler` | 库存不足检查，向家庭组广播 `low_stock` | 每天 02:00 自动执行 |

#### 子女端 → 服务端（HTTP，由 BFF 后端 `core/api_client.py` 发起）

| # | 方法 | 路径（相对 `ELDERLY_SERVER_URL`） | 用途 | 触发时机 |
|---|------|----------------------------------|------|----------|
| 30 | GET | `/health` | 检查服务端连接 | 首页/各页渲染 + 前端每 30 秒轮询 `/status` |
| 31 | GET | `/api/v1/public/device/check/{device_id}` | 校验设备是否已注册 | 设置页点击"绑定设备" |
| 32 | POST | `/api/v1/public/device/register` | 绑定设备 | check 通过后 |
| 33 | GET | `/api/v1/public/device/plans/{device_id}` | 拉取设备用药计划 | 用药设置页渲染 |
| 34 | GET | `/api/v1/public/device/status/{device_id}` | 获取设备状态信息 | 首页/提醒/记录/仪表板/设置页渲染 |
| 35 | POST | `/api/v1/public/device/medication_plan` | 添加用药计划 | 用药设置页提交表单 |
| 36 | DELETE | `/api/v1/public/device/medication_plan/{plan_id}` | 删除用药计划 | 用药设置页点击删除 |
| 37 | GET | `/api/v1/medication/plans` | 获取提醒列表 | 提醒页 / 仪表板统计 |
| 38 | GET | `/api/v1/medication/history` | 获取用药历史 | 记录页 / 仪表板统计 |

#### 子女端浏览器 → 服务端（WebSocket 直连，不经 BFF 转发）

| # | 协议 | 路径 | 用途 |
|---|------|------|------|
| 39 | WS/WSS | `/api/v1/chat/ws/{user_id}` | 浏览器直接连接服务端聊天 WS，断线每 5 秒重连 |

#### 浏览器 → 子女端（入站路由）

子女端后端作为 BFF，对外提供 10 个页面与若干 POST 接口（详见 [API 文档-家属端路由](#家属看护端路由)），监听 `0.0.0.0:4430`。

---

## HTTPS 与 Cloudflare 隧道

本系统**不再使用本地证书文件**，所有模块均以纯 HTTP 监听，HTTPS 由 **Cloudflare 隧道（cloudflared）边缘自动配置**：

- 本地服务监听 HTTP，cloudflared 建立加密隧道到 Cloudflare 边缘节点。
- 用户通过 `https://your-domain.example.com` 访问（部署时替换为实际域名），SSL 在 Cloudflare 边缘终止，流量经隧道转发到本地 HTTP 服务。
- 两个服务通过路径前缀区分转发：
  - `https://your-domain.example.com/eating-medication/server` → 服务端（本地端口 `1059`）
  - `https://your-domain.example.com/eating-medication/family` → 家属看护端（本地端口 `4430`）
- 应用内置路径前缀中间件，自动剥离/补回前缀，本地直连（前缀为空）与隧道访问均兼容。

---

## 项目结构

```
.
├── elderly_assistant/             # 老人端
│   ├── main.py                    # 程序入口（行空板 M10 GUI 主流程）
│   ├── updater.py                 # 自动更新检查模块
│   ├── install.py                 # 依赖自动安装
│   ├── config.yaml.example        # 配置文件示例
│   ├── requirements.txt           # 依赖清单
│   ├── core/                      # 核心业务逻辑
│   │   ├── ai_assistant.py        # AI 助手交互
│   │   ├── camera.py              # 摄像头封装
│   │   ├── display.py             # 屏幕显示
│   │   ├── local_fallback.py      # 离线本地降级
│   │   ├── medication.py          # 用药管理
│   │   ├── network.py             # 网络连通性管理
│   │   ├── reminder.py            # 提醒调度
│   │   └── uploader.py            # 服药照片上传
│   ├── services/                  # 底层服务
│   │   ├── ai_client.py           # 大模型客户端（OpenAI 兼容）
│   │   ├── buzzer.py              # 蜂鸣器
│   │   ├── device_id.py           # 设备 ID 生成
│   │   ├── hotspot_manager.py     # 热点创建（nmcli）
│   │   ├── http_client.py         # HTTP 客户端
│   │   ├── ocr_engine.py          # Tesseract OCR
│   │   ├── speech.py              # pyttsx3 TTS
│   │   ├── wifi_config.py         # 配网 Web 服务（:8088）
│   │   └── ws_client.py           # WebSocket 客户端
│   ├── tui/                       # 终端界面（备用形态）
│   │   └── tui_app.py
│   ├── utils/                     # 工具模块
│   │   ├── config_loader.py       # YAML 配置加载
│   │   └── logger.py
│   └── data/                      # 运行时数据（用药计划/计划模板）
├── server/                        # 服务端
│   ├── main.py                    # 启动脚本（uvicorn:1059）
│   ├── updater.py                 # 自动更新检查（含 SHA256 校验）
│   ├── install.py                 # 依赖自动安装
│   ├── requirements.txt           # 运行依赖
│   ├── requirements-dev.txt       # 测试依赖
│   ├── app/                       # FastAPI 应用
│   │   ├── main.py                # 应用实例 + 路径前缀中间件
│   │   ├── api/v1/endpoints/      # API 路由（auth/users/medication/ai/vision/public/chat）
│   │   ├── api/v1/websocket.py    # 通用 WebSocket
│   │   ├── core/                  # config/database/security/dependencies/exceptions
│   │   ├── middleware/            # cors/logging/exception_handler
│   │   ├── models/                # SQLAlchemy 数据模型
│   │   ├── schemas/               # Pydantic 数据校验
│   │   ├── services/              # 业务服务（ai/auth/medication/user/vision）
│   │   ├── tasks/                 # 定时任务（stock_checker）
│   │   ├── utils/                 # http_client/rate_limit/time_utils/validators
│   │   ├── websocket/             # manager/notifier
│   │   └── migrations/            # Alembic 迁移（已就位，生产建议启用）
├── family_monitor/                # 家属看护端
│   ├── main.py                    # FastAPI 应用 + 中间件链
│   ├── updater.py                 # 自动更新检查
│   ├── install.py                 # 依赖自动安装
│   ├── config.json.example        # 配置文件示例
│   ├── requirements.txt
│   ├── core/                      # 认证 / 会话 / 配置 / api_client(BFF)
│   │   ├── api_client.py          # 调用老人端服务端的 BFF 客户端
│   │   ├── auth.py                # bcrypt + 会话令牌
│   │   ├── config.py              # 配置加载
│   │   └── session.py             # itsdangerous 会话管理
│   ├── routes/                    # 路由（home/auth/chat/admin）
│   ├── static/css/                # 样式表
│   └── templates/                 # 10 个 Jinja2 页面模板
├── history.md                     # 项目开发历史记录（版本基准）
├── VERSION                        # 当前版本号（v2.4.0）
├── deploy/                        # 部署辅助文件（systemd 单元 + cloudflared 配置）
│   ├── eating-medication-server.service
│   ├── eating-medication-family.service
│   ├── cloudflared.service
│   ├── cloudflared-config.yml
│   └── README.md
└── .gitignore
```

---

## 技术栈

| 层级 | 老人端 | 服务端 | 子女端 |
|------|--------|--------|--------|
| 语言 | Python 3.6+（推荐 3.12） | Python 3.8+（推荐 3.12） | Python 3.8+（推荐 3.12） |
| Web 框架 | — | FastAPI 0.115.0 + Uvicorn 0.32.0 | FastAPI 0.104 + Uvicorn 0.24 |
| GUI / 硬件 | pinpong 1.2.0（行空板 M10）+ unihiker GUI | — | Jinja2 3.1 模板 |
| HTTP 客户端 | requests 2.31.0 | httpx 0.27.2 | httpx 0.25.0 |
| 数据库 | — | SQLAlchemy 2.0.36 + SQLite | users.json + 文件锁（bcrypt 4.1） |
| 认证 | 仅通过 device_id 校验 | python-jose 3.4.0（JWT HS256）+ bcrypt | itsdangerous 会话令牌（7 天） |
| AI | pyttsx3 / edge-tts | 智谱 AI `glm-4.7-flash`（zhipuai SDK） | — |
| OCR | pytesseract 0.3.10（本地） | 百度 OCR（aip.baidubce.com） | — |
| 调度 | schedule 1.2.1 | APScheduler 3.11.0 | — |
| 配置 | PyYAML 6.0.1 | pydantic-settings 2.6 + .env | config.json + .env |
| 模糊匹配 | rapidfuzz 3.6.2 | — | — |
| 图像 | Pillow 10.0.1 | Pillow 10.4.0 | — |
| HTTPS | Cloudflare 隧道 | Cloudflare 隧道 | Cloudflare 隧道 |

---

## 快速开始

### 环境要求

- Python 3.8+（推荐 3.12；行空板 M10 自带 Python 3.6 也可运行老人端）
- 操作系统：Windows / Linux（含行空板 M10 等 ARM 设备）
- 可选硬件：USB 摄像头、麦克风、音箱/蜂鸣器
- OCR 识别需安装 Tesseract（可选，老人端本地用）
- HTTPS 由 Cloudflare 隧道处理，无需本地证书

> 三模块的 `install.py` 内容已统一为同一份脚本，行为：
> 1. 先检测 `pip` 是否存在，无则按平台自动安装（Linux 优先 `apt-get install python3-pip`、Windows 用 `get-pip.py`、其他走 `ensurepip` 后备）；
> 2. 正常 `pip install`（使用 `-i PIP_INDEX_URL` 临时指定镜像源，默认清华源，可通过环境变量覆盖）；
> 3. 若输出包含 `--break-system-packages`（PEP 668 错误），自动加该参数重试。
> 已安装的包自动跳过，无需重复安装。可通过 `PIP_INDEX_URL` 环境变量切换镜像源。

### 老人端

```bash
cd elderly_assistant
python install.py          # 自动安装依赖
# config.yaml 默认服务器地址已配置为公网域名，可在热点配网页面修改
python main.py             # 启动（--debug 启用调试模式）
```

启动后默认显示时间 + 后台创建热点 `M10-Config`（WPA2 加密，密码启动时随机生成并打印到终端），用户连接热点后用浏览器访问 `http://10.0.0.1:8088` 进行配网（填写 WiFi 与服务端地址）。

### 服务端

```bash
cd server
python install.py          # 自动安装依赖
# 编辑 .env 配置数据库、密钥、智谱 AI、京东比价、PATH_PREFIX、ALLOWED_ORIGINS
python main.py             # 启动服务（本地端口 1059，HTTP 监听）
```

- API 文档：`http://localhost:1059/eating-medication/server/docs`（或本地直连 `http://localhost:1059/docs`）
- 健康检查：`http://localhost:1059/eating-medication/server/health`

### 家属看护端

```bash
cd family_monitor
python install.py          # 自动安装依赖
# 编辑 .env（SECRET_KEY 等）和 config.json（服务器地址、PATH_PREFIX）
python main.py             # 启动服务（本地端口 4430，HTTP 监听）
```

- 访问：`http://localhost:4430/eating-medication/family/`（或本地直连 `http://localhost:4430/`）
- 管理员入口：`{PATH_PREFIX}/admin/administrator/setting`

> **注意**：`.env`、数据库（`*.db`）、`users.json`、`bound_device.json` 等敏感文件已通过 `.gitignore` 排除，不会上传至仓库，部署时需自行配置。生产模式（`DEBUG=False`）下，服务端与子女端若未配置 `SECRET_KEY`（或为已知弱值）将**拒绝启动**。

---

## 配置说明

| 模块 | 配置文件 | 关键配置项 |
|------|----------|------------|
| elderly_assistant | `config.yaml` | `server.base_url`（默认公网域名）、`ai.base_url`、摄像头、语音引擎、蜂鸣器、热点、轮询间隔 |
| server | `.env` | `DATABASE_URL`、`SECRET_KEY`、`ALGORITHM`、`ACCESS_TOKEN_EXPIRE_MINUTES`、`ZHIPUAI_API_KEY`、`OCR_*`、`JD_*`、`PATH_PREFIX`、`ALLOWED_ORIGINS` |
| family_monitor | `.env` + `config.json` | `ELDERLY_SERVER_URL`、`SECRET_KEY`、`SERVER_PORT`、`PATH_PREFIX`、`DISPLAY_*` |

### 路径前缀（PATH_PREFIX）

| 模块 | 默认值 | 本地直连 |
|------|--------|----------|
| server | `/eating-medication/server` | 设为空字符串 |
| family_monitor | `/eating-medication/family` | 设为空字符串 |

中间件实现位于 [server/app/main.py](./server/app/main.py) 与 [family_monitor/main.py](./family_monitor/main.py)：请求阶段剥离前缀供路由匹配，响应阶段为 3xx 重定向的 `Location` 头补回前缀。

### 服务端 `.env` 关键项

```ini
APP_NAME=老年人用药管理系统
DEBUG=False
API_V1_PREFIX=/api/v1
PATH_PREFIX=/eating-medication/server
DATABASE_URL=sqlite:///./data/elderly_care.db
SECRET_KEY=<必须配置，生产模式弱密钥将拒绝启动>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
ZHIPUAI_API_KEY=<智谱 AI Key>
ZHIPUAI_MODEL=glm-4.7-flash
OCR_PROVIDER=baidu
OCR_API_KEY=<百度 OCR Key>
OCR_SECRET_KEY=<百度 OCR Secret>
OCR_APP_ID=<百度 OCR AppID>
ALLOWED_ORIGINS=https://your-domain.example.com
WS_HEARTBEAT_INTERVAL=30
```

首次启动 `server/main.py` 会自动生成 `.env` 模板（v2.3.0 已修复弱密钥问题，但生产环境仍需手动填入真实密钥）。

---

## API 文档

> 完整外部路径 = `PATH_PREFIX`（`/eating-medication/server`） + `API_V1_PREFIX`（`/api/v1`） + router prefix + 端点路径。下表省略前缀，仅列 router prefix + 端点。

### 服务端 REST API

#### 认证 `/auth`

| 方法 | 路径 | 用途 | 认证 | 限流 |
|------|------|------|------|------|
| POST | `/auth/register` | 用户注册（老人/家属） | 否 | 5 次/分钟/IP |
| POST | `/auth/login` | 用户登录，返回 JWT | 否 | — |

#### 用户 `/users`

| 方法 | 路径 | 用途 | 认证 |
|------|------|------|------|
| GET | `/users/me` | 获取当前用户信息 | JWT |
| PUT | `/users/me` | 更新当前用户信息 | JWT |
| POST | `/users/bind` | 家属绑定老人（须提供老人 device_id） | JWT（仅 family） |
| DELETE | `/users/me` | 注销当前用户账号（硬删除，级联清理用药计划/记录/AI日志） | JWT |
| DELETE | `/users/{user_id}` | 家属删除同家庭组的老人账号（硬删除） | JWT（仅 family，须同组） |

#### 用药管理 `/medication`

| 方法 | 路径 | 用途 | 认证 |
|------|------|------|------|
| POST | `/medication/plan` | 创建用药计划（仅老人） | JWT（仅 elderly） |
| GET | `/medication/plans` | 获取用药计划（老人看自己，家属看同组老人） | JWT |
| POST | `/medication/take` | 记录服药并原子扣减库存 | JWT（仅 elderly） |
| GET | `/medication/history` | 服药历史（支持 `start`/`end` 过滤） | JWT |

#### AI 健康助手 `/ai`

| 方法 | 路径 | 用途 | 认证 | 限流 |
|------|------|------|------|------|
| POST | `/ai/chat` | 向 AI 提问（落库 `AIQueryLog`） | JWT | — |
| POST | `/ai/chat/public` | 公开 AI 提问（供老人端） | 否 | 10 次/分钟/IP |

#### 药品识别 `/vision`

| 方法 | 路径 | 用途 | 认证 | 限制 |
|------|------|------|------|------|
| POST | `/vision/recognize` | 上传药品图片识别药名（百度 OCR） | JWT | 文件 ≤ 5MB |

#### 聊天 `/chat`

| 方法 | 路径 | 用途 | 认证 |
|------|------|------|------|
| POST | `/chat/send` | 发送聊天消息并通过 WS 推送给接收者 | JWT |
| GET | `/chat/history/{user_id}` | 获取与指定用户的聊天历史（`limit` 1~200） | JWT |

#### 设备公开接口 `/public`（供老人端 / 子女端 BFF 调用）

| 方法 | 路径 | 用途 | 认证 |
|------|------|------|------|
| POST | `/public/device/register` | 设备注册 / 心跳上报 | device_id |
| POST | `/public/device/message` | 接收设备上报消息（含 `emergency` 紧急） | device_id |
| GET | `/public/device/check/{device_id}` | 检查设备是否已注册 | 无 |
| GET | `/public/device/status/{device_id}` | 获取设备状态（计划/记录数） | device_id |
| GET | `/public/device/schedule/{device_id}` | 获取设备用药计划（老人端轮询） | device_id |
| GET | `/public/device/plans/{device_id}` | 获取设备所有用药计划 | device_id |
| POST | `/public/device/medication_plan` | 家属通过 device_id 设置用药计划 | device_id |
| DELETE | `/public/device/medication_plan/{plan_id}` | 删除用药计划 | device_id |
| POST | `/public/ai/ask` | 设备端 AI 提问 | 否（限流 10 次/分钟/IP） |

#### 根路径

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/health` | 健康检查（容器编排/监控用） |
| GET | `/` | 根路径，返回欢迎信息与 docs/health 链接 |

### 家属看护端路由

子女端后端作为 BFF，对外提供以下页面与接口（路径已含 `PATH_PREFIX` 前缀）：

| 方法 | 路径 | 用途 | CSRF |
|------|------|------|------|
| GET | `/` | 首页 | — |
| GET | `/status` | 服务器状态 JSON（前端每 30 秒轮询） | — |
| GET | `/reminders` | 提醒页 | — |
| GET | `/records` | 记录页 | — |
| GET | `/dashboard` | 健康仪表板 | — |
| GET | `/settings` | 系统设置页 | — |
| POST | `/settings/server` | 更新老人端服务器地址 | `X-CSRF-Token` |
| POST | `/settings/display` | 更新显示设置 | `X-CSRF-Token` |
| POST | `/settings/bind_device` | 绑定设备（先 check 后 register） | `X-CSRF-Token` |
| POST | `/settings/unbind_device` | 解绑设备 | `X-CSRF-Token` |
| GET | `/medication_settings` | 用药设置页 | — |
| POST | `/medication_settings/add` | 添加用药计划 | `X-CSRF-Token` |
| POST | `/medication_settings/delete/{plan_id}` | 删除用药计划 | `X-CSRF-Token` |
| GET | `/login` `/register` `/logout` | 登录 / 注册 / 登出 | 表单 csrf_token |
| GET | `/admin/administrator/setting` | 管理员设置页（仅 admin） | — |
| POST | `/admin/administrator/setting/server` | 更新服务端配置 | 表单 csrf_token |
| POST | `/admin/administrator/setting/advanced` | 更新高级配置（生产禁改 DEBUG） | 表单 csrf_token |

> 登录接口 `POST /login` 含内存级限流：每 IP 每分钟最多 5 次，超限返回 429。

---

## WebSocket 协议

服务端提供两个独立的 WebSocket 入口：

### 1. 通用 WebSocket `/ws/ws`

- **完整路径**：`{PATH_PREFIX}/ws/ws?token=<JWT>`
- **认证**：Query 参数 `token`（JWT，长度上限 2048）；无效则 close code=1008
- **消息**：客户端发 `"ping"`，服务端回 `"pong"`；用于接收服务端主动推送通知

### 2. 聊天 WebSocket `/api/v1/chat/ws/{user_id}`

- **完整路径**：`{PATH_PREFIX}/api/v1/chat/ws/{user_id}?token=<JWT>`
- **认证**：Query 参数 `token`，以 token 中 `sub` 覆盖 URL 中的 user_id
- **客户端 → 服务端**（JSON）：
  - `{"type":"chat","content":"...","receiver_id":N,"sender_name":"..."}` —— 发送聊天消息（落库 + 推送接收者）
  - `{"type":"ping"}` —— 心跳
- **服务端 → 客户端**（JSON）：
  - `{"type":"chat_message","id":..,"sender_id":..,"sender_name":"..","content":"..","timestamp":".."}` —— 推送给接收者
  - `{"type":"message_sent","id":..}` —— 回执给发送者
  - `{"type":"pong"}` —— 心跳响应

### 服务端主动推送消息类型（经 `ConnectionManager` + `Notifier`）

| `type` | 触发场景 |
|--------|----------|
| `medication_taken` | 老人已服药 |
| `medication_missed` | 老人漏服药品 |
| `low_stock` | 药品库存不足（定时任务每天 02:00 触发） |
| `family_message` | 家庭消息 |
| `chat_message` | 聊天消息（chat 端点直接调用） |

---

## 数据模型

服务端使用 SQLAlchemy + SQLite（`./data/elderly_care.db`），5 张表：

| 模型 | 表名 | 主要字段 |
|------|------|----------|
| `User` | `users` | id, username(唯一), hashed_password, full_name, role(elderly/family), phone, group_id, created_at, is_active, last_login_at |
| `MedicationPlan` | `medication_plans` | id, user_id(FK), drug_name, dosage, frequency, schedule_times(JSON), total_quantity, remaining_quantity, unit, low_stock_threshold(默认5.0), created_at, updated_at |
| `MedicationRecord` | `medication_records` | id, plan_id(FK), user_id(FK), scheduled_time, taken_time, status(pending/taken/missed/skipped), note |
| `ChatMessage` | `chat_messages` | id, sender_id(FK, 索引), receiver_id(FK, 可空, 索引), sender_name(50), content(Text), created_at |
| `AIQueryLog` | `ai_query_logs` | id, user_id(FK), question, answer, model(默认 glm-4.7-flash), created_at |

启动时通过 `Base.metadata.create_all` 自动建表；生产环境建议启用 Alembic 迁移（`app/migrations/` 已就位）。

---

## 定时任务

**文件**：[`server/app/tasks/stock_checker.py`](./server/app/tasks/stock_checker.py)

- **调度器**：APScheduler `AsyncIOScheduler`（全局单例）
- **任务**：`check_low_stock_job`，CronTrigger **每天 02:00** 执行一次
- **逻辑**：查询所有 `role=elderly` 用户 → 遍历每位老人的 `MedicationPlan` → 若 `remaining_quantity <= low_stock_threshold`，调用 `notifier.notify_low_stock(...)` 向家庭组广播 `low_stock` 消息
- **生命周期**：`start_scheduler()` 在 `app/main.py` 的 `lifespan` 启动时调用，`shutdown_scheduler()` 在关闭时调用

---

## 自动更新机制

所有模块均内置**启动时自动更新检查**功能（`updater.py`），符合"上传到云端的代码均需有自动更新功能，启动时检查"的要求。

- 启动时通过 GitHub API 查询最新 Release（优先）/ Tag（回退）版本号。
- 发现新版本时打印提示（当前版本、最新版本、下载地址），**非阻塞**，不影响主程序运行。
- `auto_pull=True` 时若当前目录为 git 仓库，可执行 `git pull` 自动更新（默认 `False`）。
- 网络异常或检查失败时静默/警告处理，不中断启动。

### 三模块差异

三模块的 `updater.py` 已统一为同一份实现（均含完整 C9 加固）：

| 模块 | SHA256 校验 | 异常处理 | 版本号 |
|------|-------------|----------|--------|
| elderly_assistant | **完整 C9 加固**：尝试在 Release 资产中查找 SHA256SUMS 校验文件 | `logger.warning` 不静默 | 2.4.0 |
| server | **完整 C9 加固**：同上 | `logger.warning` 不静默 | 2.4.0 |
| family_monitor | **完整 C9 加固**：同上 | `logger.warning` 不静默 | 2.4.0 |

> 三个 `updater.py` 的 `__version__` 已与 `VERSION` 文件同步为 `2.4.0`。

---

## 部署与运维

仓库已内置部署辅助文件，位于 [`deploy/`](./deploy) 目录，包含 systemd 服务单元与 cloudflared 隧道配置示例，详见 [`deploy/README.md`](./deploy/README.md)。

### Cloudflare 隧道（cloudflared）配置

1. 在 Cloudflare Zero Trust 控制台创建隧道，获取 tunnel token。
2. 安装 cloudflared 并使用 [`deploy/cloudflared.service`](./deploy/cloudflared.service)（把 `<TUNNEL_TOKEN>` 替换为实际 token）：
   ```bash
   sudo cp deploy/cloudflared.service /etc/systemd/system/
   sudo vi /etc/systemd/system/cloudflared.service   # 替换 <TUNNEL_TOKEN>
   sudo systemctl daemon-reload
   sudo systemctl enable --now cloudflared
   ```
3. 配置隧道路由规则（在 Cloudflare 控制台或参考 [`deploy/cloudflared-config.yml`](./deploy/cloudflared-config.yml)）：
   - `https://your-domain.example.com/eating-medication/server` → `http://localhost:1059`
   - `https://your-domain.example.com/eating-medication/family` → `http://localhost:4430`
4. 在 Cloudflare DNS 为域名添加 CNAME 指向隧道 ID（控制台可自动完成）。

### 进程守护（systemd）

为服务端与子女端各使用 [`deploy/eating-medication-server.service`](./deploy/eating-medication-server.service) 与 [`deploy/eating-medication-family.service`](./deploy/eating-medication-family.service)（示例中部署目录为 `/opt/eating-medication/`，运行用户为 `deploy`，按实际环境修改 `WorkingDirectory`/`User`/`ExecStart`）：

```bash
sudo cp deploy/eating-medication-server.service deploy/eating-medication-family.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now eating-medication-server eating-medication-family
sudo systemctl status eating-medication-server eating-medication-family
```

日志查看：
```bash
journalctl -u eating-medication-server -f       # 服务端日志
journalctl -u eating-medication-family -f       # 家属端日志
journalctl -u cloudflared -f                    # 隧道日志
```

## 贡献与开发指南

### 开发环境

```bash
git clone https://gh.llkk.cc/https://github.com/diaoyunxi/eating-medication.git
cd eating-medication
# 服务端开发依赖
cd server && pip install -r requirements-dev.txt
```

### 目录约定

- 新增 API 端点放 `server/app/api/v1/endpoints/`，对应 schema 放 `server/app/schemas/`，service 放 `server/app/services/`，model 放 `server/app/models/`。
- 子女端页面放 `family_monitor/templates/`，路由放 `family_monitor/routes/`，样式放 `family_monitor/static/css/`。
- 老人端硬件相关放 `elderly_assistant/services/`，业务逻辑放 `elderly_assistant/core/`。

### 编码规范

- 使用中文注释、中文提交信息、中文文档。
- 提交信息遵循约定式提交（`feat: ` / `fix: ` / `docs: ` / `refactor: ` / `test: ` / `chore: `）。
- 敏感信息（密钥、token、密码）一律不得硬编码或入库。
- 新增端点须同步更新本 README 的 [API 文档](#api-文档)。

### 提交流程

1. 从 `main` 拉取最新代码。
2. 新建分支开发：`git checkout -b feat/xxx`。
3. 提交并推送：`git commit -m "feat: xxx"` → `git push origin feat/xxx`。
4. 以提交PR形式给上流仓库提交代码，在经过AI的review并更改（ai的不一定符合规范，需要手动检查）再经过简单人工review后合并。

## 感谢贡献

本项目的开发与运行离不开以下服务与 API 提供方的支持（排名不分先后）：

### 基础设施与网络

- **[Cloudflare](https://www.cloudflare.com/)** — 提供 Cloudflare Tunnel（cloudflared）边缘隧道，承担 HTTPS 终止与子路径转发，使本地服务无需自备证书即可对外提供安全访问。
- **[dnshe](https://www.dnshe.com/)** — 提供免费域名，用于 Cloudflare 隧道对外接入。
- **[gh.llkk.cc](https://gh.llkk.cc/)** — 提供 GitHub 加速代理，用于在受限网络环境下克隆仓库与下载 Release 资产（`git clone https://gh.llkk.cc/https://github.com/...`）。
- **[GitHub](https://github.com/)** — 代码托管与 Release 分发，自动更新检查通过 GitHub API 获取最新版本。

### AI 与识别服务

- **[智谱 AI](https://open.bigmodel.cn/)** — 提供 GLM-4 系列大模型（默认 `glm-4.7-flash`），支撑老人端 / 子女端的健康问答与用药咨询。
- **[Tesseract OCR](https://github.com/tesseract-ocr/tesseract)** — 开源本地 OCR 引擎，供老人端离线识别药名。
- **[pyttsx3](https://github.com/nateshmbhat/pyttsx3)** — 离线中文 TTS 引擎，供老人端语音播报用药提醒。

### 硬件平台

- **[DFRobot 行空板 M10](https://www.unihiker.com/)** — 老人端目标硬件，提供屏幕、按钮、GPIO 与 WiFi，通过 `pinpong` 库与 `unihiker` GUI 库实现图形化交互。

> 如有遗漏或需要补充/调整致谢信息，欢迎提 issue。

---

## 许可

本项目仅供学习和个人使用，药品信息及健康建议请以医生指导为准。
