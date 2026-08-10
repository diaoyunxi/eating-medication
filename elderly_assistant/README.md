# 老人用药助手（Elderly Medication Assistant）

> 当前版本：v2.9.6（2026-07-15，安全清理与文档更新）

基于 Python 的智能用药管理系统（老人使用端），适用于行空板及通用设备（Windows/Linux）。提供用药提醒、药品识别、AI 语音问答、服药记录上传、库存管理、家属沟通和紧急呼叫等功能。所有配置均通过扁平 `.env` 文件管理（与 server / family_monitor 统一），无硬编码。

---

## 功能列表

- **多人按时提醒**：支持按姓名、时间、药品、用量配置提醒，未确认服药时每 1 分钟音量自动放大直至确认。
- **扫码识别药品**：点击主界面「扫码查药」触摸按钮，打开摄像头扫描药盒条码/二维码，按药品编号匹配用药计划后语音播报「药品名 + 用量 + 服药时间」。支持两条通路：HuskyLens 板载解码（默认，无需本机解码）与 USB 摄像头 + pyzbar 本地解码（自动回退）。
- **计划离线可用**：每 20 分钟拉取一次用药计划，成功后写入本地缓存；断网时自动回退本地缓存，提醒与扫码查询均不中断。
- **摄像头识别药名**：拍照后进行 OCR 文字识别，与本地药品库模糊匹配，语音播报用量。
- **AI 语音问答**：老人可语音提问，通过配置的 AI 接口回复（如 OpenAI 或本地模型）。
- **服药画面上传**：确认服药后自动拍照上传到服务器，便于家属通过小程序查看日志。
- **库存管理与低量提醒**：记录药品剩余量，低于设定天数时提醒。
  - **网络状态切换**：WiFi 在线时支持与家属文字聊天及一键呼叫 120；离线时保留基于本地缓存的计划提醒和扫码查询，仅暂停依赖网络的功能（拍照上传、家属聊天、紧急呼救、AI 问答），网络恢复后自动切回在线模式。
- **大字体 GUI**：全屏 unihiker GUI 界面，按钮大、操作简单，适合老人使用。
- **完整日志**：所有运行日志保存到本地，错误信息同时显示在界面状态栏并写入日志，程序不会因异常退出。

---

## 项目结构

```
elderly_assistant/
├── main.py                     # 程序入口
├── .env                        # 所有可配置项（扁平 .env，首次运行自动生成）
├── .env.example                # 配置模板（纳入版本管理）
├── requirements.txt
├── core/                       # 核心业务逻辑
│   ├── __init__.py
│   ├── reminder.py             # 提醒调度、蜂鸣器、未确认升级
│   ├── medication.py           # 药品库存管理、剩余量计算
│   ├── camera.py               # 摄像头拍照
│   ├── ai_assistant.py         # 语音问答、AI 回复
│   ├── uploader.py             # 服药画面上传
│   ├── network.py              # 网络状态检测、聊天、紧急呼叫
│   └── local_fallback.py       # 无网时的基础提醒
├── services/                   # 底层服务抽象
│   ├── __init__.py
│   ├── speech.py               # 语音合成、语音识别（队列模式防冲突）
│   ├── buzzer.py               # 蜂鸣器（音频文件/GPIO）
│   ├── ocr_engine.py           # OCR 引擎（Tesseract）
│   ├── ai_client.py            # AI 接口客户端
│   ├── http_client.py          # 通用 HTTP 请求
├── utils/                      # 工具模块
│   ├── __init__.py
│   ├── config_loader.py        # 配置加载与默认值
│   └── logger.py               # 日志（每日一个文件，永久保留）
└── data/                       # 运行时数据文件
    ├── schedules.json          # 提醒时间表（自动创建）
    └── medications.json        # 药品库存（自动创建）
```

---

## 快速开始

### 1. 环境要求
- Python 3.6 或更高版本
- 操作系统：Windows / Linux（含行空板等 ARM 设备）
- 可选硬件：USB 摄像头、麦克风、音箱/蜂鸣器（用于语音提示）
- OCR 识别需要安装 Tesseract（详见下方说明）

### 2. 安装依赖

依赖安装已统一为仓库根目录 `common/install.py`（各模块不再各自维护），需传入本模块 `requirements.txt` 路径，老人端额外加 `--huskylens` 安装摄像头依赖：

```bash
python ../common/install.py requirements.txt --huskylens
```

`common/install.py` 行为：

1. 先检测 `pip` 是否存在；无则按平台自动安装（Linux 优先 `apt-get install python3-pip`，Windows 下载 `get-pip.py`，其他走 `ensurepip` 后备）。
2. 正常 `pip install`：**默认不使用任何镜像源（走系统/官方默认源）**，首选源安装失败自动回退官方 PyPI 源 `https://pypi.org/simple`；可用环境变量 `PIP_INDEX_URL` 指定首选源（仍会回退官方源），不修改全局 pip 配置。
3. 若 `pip install` 输出包含 `--break-system-packages`（PEP 668 `externally-managed-environment` 错误），自动加上该参数重新 `pip install`。
4. 已安装的包自动跳过（优先 `importlib.import_module` 检测，回退 `pip show`）。
5. `--huskylens`：额外从官方仓库下载 `dfrobot_huskylensv2.py`（PyPI 未发布），GitHub 下载代理统一读根目录 `.env` 的 `GITHUB_PROXY`。

或手动安装：
```bash
pip install -r requirements.txt
# 若 Linux 系统提示需使用 --break-system-packages：
pip install --break-system-packages -r requirements.txt
```

**Tesseract 安装（可选）**  
若需要使用摄像头识别药品文字，请安装 Tesseract OCR：
- Windows：下载安装 [Tesseract-OCR for Windows](https://github.com/UB-Mannheim/tesseract/wiki)，安装时勾选中文简体语言包。
- Linux：`sudo apt install tesseract-ocr tesseract-ocr-chi-sim`
- 安装后确保 `tesseract` 命令在系统 PATH 中，或修改 `services/ocr_engine.py` 中 `tesseract_cmd` 变量指向安装路径。

### 3. 配置文件
编辑根目录下的 `.env`（首次运行无 `.env` 时会自动生成完整模板），根据实际情况修改：
- `SERVER_BASE_URL`：服务端 API 基址（用于上传、聊天、紧急呼救等）
- `HEARTBEAT_INTERVAL`：心跳上报间隔（秒）
- `HOTSPOT_*`：热点配网 SSID / IP / 端口
- `POLL_INTERVAL` / `SNOOZE_MINUTES` / `BUZZER_LOOP_INTERVAL`：提醒与蜂鸣器间隔
- `CAMERA_*`：摄像头连接方式与保存路径
- `SCAN_*`：药品条码扫描来源、USB 摄像头序号与扫码超时

配置文件包含合理默认值，即使不修改程序也能运行（仅语音提醒和基础功能可用）。

### 4. 运行程序
```bash
python main.py
```
首次启动会自动创建 `data/` 文件夹及必要的 JSON 数据文件（空提醒列表和空药品库存）。

---

## 使用说明

### 主界面
全屏显示大字体按钮，老人可直接触摸（或鼠标点击）：
- **扫码查药**：打开摄像头扫描药盒条码，按药品编号匹配用药计划并语音播报名称与用量。
- **我已服药**：确认当前提醒并自动拍照上传（需联网）。
- **识别药品**：打开摄像头拍照，OCR 识别并与库存药品模糊匹配，语音播报用量。
- **询问助手**：通过麦克风提问，AI 语音回复（需 AI 密钥和网络）。
- **提醒设置**：添加/删除/编辑用药提醒（姓名、药品、时间、用量、重复日）。
- **药品库存**：查看药品列表、添加新药、查看剩余量。
- **家属聊天**：在线时打开与家属的消息窗口，支持实时收发文字。
- **紧急呼救**：发送紧急请求到服务器（需联网），离线时语音提示拨打 120。

### 添加提醒示例
1. 点击“提醒设置” → “添加”。
2. 输入：姓名（如“张三”）、药品（如“降压药”）、时间（如 `08:30`）、用量（如“2片”）、重复日（如 `mon,tue,wed,thu,fri`）。
3. 保存后，到达设定时间系统会自动语音提醒：“张三，该服用降压药了，用量2片”，同时蜂鸣器响。
4. 若老人一分钟内未点击“我已服药”，音量将逐次增大直至确认。

### 药品识别流程
1. 将药盒置于摄像头前，点击“识别药品”。
2. 系统拍照后调用 Tesseract OCR 提取文字。
3. 将提取的文字与 `data/medications.json` 中的药品名称进行模糊匹配（相似度 >60%）。
4. 匹配成功后语音播报：“识别为 XX 药，建议每次用量 Y 片”。

### 操作方式说明

| 操作 | 场景 | 动作 |
|------|------|------|
| 物理键 A 短按 | 提醒响铃中 | 确认服药（停止响铃、上报服务端、拍照上传） |
| 物理键 A 长按（>`LONG_PRESS_SEC`） | 提醒响铃中 | 询问 AI 该药服用注意事项并语音播报 |
| 物理键 B 按下 | 提醒响铃中 | 暂缓提醒（`SNOOZE_MINUTES` 分钟后再响） |
| 屏幕「扫码查药」按钮 | 主界面 | 扫描药品条码并语音播报用量 |

> 扫码使用屏幕触摸按钮而非物理按键，避免与「暂缓提醒」语义冲突及误触摄像头；按钮位于主界面下方，点击后在后台线程扫码，不影响时间刷新与提醒触发。

### 扫码查询药品用量

1. 家属先在网页端「添加用药计划」时填写**药品编号/条形码**（可手输或用手机摄像头扫描，非必填）。
2. 老人点击主界面「扫码查药」按钮，语音提示「请把药盒上的条码对准摄像头」。
3. 系统在 `SCAN_TIMEOUT_SEC` 秒内轮询扫码：优先 HuskyLens 板载条码（算法 17）/ 二维码（算法 18）识别，不可用时自动回退 USB 摄像头 + pyzbar 本地解码。
4. 用识别到的编号在当前用药计划中按 `product_code` 匹配（忽略大小写与首尾空白），命中后语音播报「药品名，每次用量，服药时间」。
5. 未识别到条码 / 未匹配到计划时分别播报「没有识别到药品条码，请再试一次」「没有找到这个药品的用药信息，请让家人在手机上添加」。

> USB 通路为可选依赖：`sudo apt install -y libzbar0 && pip install opencv-python-headless pyzbar`；未安装时自动降级为仅用 HuskyLens，不影响程序运行。

### 离线运行

用药计划采用「有网优先、失败回退本地、无网走本地」策略：
- 每 `POLL_INTERVAL` 秒（默认 1200 秒 = 20 分钟）拉取一次用药计划，成功后原子写入 `data/schedules.json`。
- 网络异常/非 200 响应时回退读取本地缓存；连本地缓存都没有时保留内存中的既有计划，绝不清空（避免网络抖动导致漏提醒）。
- 启动时先载入本地缓存，断网开机也能按既有计划提醒、扫码查询。
- 其余离线行为：保留语音提醒和蜂鸣器；拍照上传、家属聊天、紧急呼救、AI 问答暂停，网络恢复后自动切回在线模式。

---

## 配置说明

所有功能开关和参数都在 `.env` 中（扁平键），重要项：

| 配置键 | 说明 |
|--------|------|
| `SERVER_BASE_URL` | 后端服务器地址 |
| `SERVER_UPLOAD_ENDPOINT` | 服药照片上传接口路径 |
| `SERVER_TIMEOUT` | HTTP 超时（秒） |
| `HEARTBEAT_INTERVAL` | 心跳上报间隔（秒） |
| `HOTSPOT_SSID` / `HOTSPOT_IP` / `HOTSPOT_WEB_PORT` | 热点配网 SSID / IP / 端口 |
| `POLL_INTERVAL` | 用药计划轮询间隔（秒），默认 `1200`（20 分钟） |
| `SNOOZE_MINUTES` | 暂缓提醒间隔（分钟） |
| `BUZZER_LOOP_INTERVAL` | 蜂鸣器循环间隔（秒） |
| `LONG_PRESS_SEC` | 按钮长按判定阈值（秒），默认 `1.5` |
| `CAMERA_CONNECTION` / `CAMERA_UART_TTY` / `CAMERA_UART_BAUDRATE` / `CAMERA_SAVE_PATH` | 摄像头连接方式与保存路径 |
| `SCAN_SOURCE` | 扫码来源：`auto`（默认，优先 HuskyLens 并回退 USB）/ `huskylens` / `usb` |
| `SCAN_USB_INDEX` | USB 摄像头设备序号，默认 `0` |
| `SCAN_TIMEOUT_SEC` | 单次扫码超时秒数，默认 `8` |

所有配置均可热加载（修改后重启程序生效），无需改动代码。

---

## 常见问题

**Q：打开程序后提示“语音识别初始化失败”或“语音播报失败”？**  
A：电脑无麦克风或扬声器，不影响提醒功能，仅语音输入禁用。可在 Windows 声音设置中检查默认设备。

**Q：摄像头打开失败？**  
A：检查摄像头是否被其他程序占用，或修改 `.env` 中 `CAMERA_CONNECTION` / `CAMERA_UART_TTY` 等参数尝试不同连接方式。

**Q：OCR 识别结果为空白或报错？**  
A：请确保已安装 Tesseract 并配置好环境变量。中文识别需安装 `chi_sim` 语言包。

**Q：语音播报出现“run loop already started”错误？**  
A：程序已使用队列模式解决线程冲突，若仍出现请检查 `services/speech.py` 是否为最新版本。

**Q：如何更换 AI 服务为本地模型（如 Ollama）？**  
A：老人端 AI 问答复用服务端地址（`.env` 的 `SERVER_BASE_URL`），AI 服务由服务端统一配置（详见服务端 `.env` 的 `ZHIPUAI_*`），老人端无需单独配置 AI 密钥。

**Q：如何在没有 GUI 的服务器上运行？**  
A：当前版本依赖 unihiker GUI 图形界面，若需纯终端运行，可改写 `main.py` 为命令行交互模式（不推荐，老人端需大按钮）。

---

## 日志管理

系统运行日志保存在 `logs/` 目录下，按日期生成文件 `assistant_YYYYMMDD.log`。  
所有错误信息会同时显示在 GUI 底部状态栏（红色字体，5 秒后恢复）并写入日志，程序不会因任何异常退出。  
日志文件**永久保留**，不会自动删除，可用于长期查看用药情况。

---

## 开发与扩展

项目采用模块化设计，每个功能拆分为独立文件，方便二次开发：
- 新增识别模式：修改 `core/camera.py` 和 `services/ocr_engine.py`
- 更换语音引擎：替换 `services/speech.py` 中的 pyttsx3 为其他 TTS 服务
- 自定义 GUI 组件：在 `core/display.py` 中添加

所有路径、接口均从 `.env` 读取，切换环境时仅需修改该文件。

---

## 许可
本项目仅供学习和个人使用，药品信息及健康建议请以医生指导为准。