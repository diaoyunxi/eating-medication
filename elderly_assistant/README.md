# 老人用药助手（Elderly Medication Assistant）

> 当前版本：v2.4.0（2026-07-07，移动端导航优化版本）

基于 Python 的智能用药管理系统（老人使用端），适用于行空板及通用设备（Windows/Linux）。提供用药提醒、药品识别、AI 语音问答、服药记录上传、库存管理、家属沟通和紧急呼叫等功能。所有配置均通过 YAML 文件管理，无硬编码。

---

## 功能列表

- **多人按时提醒**：支持按姓名、时间、药品、用量配置提醒，未确认服药时每 1 分钟音量自动放大直至确认。
- **摄像头识别药名**：拍照后进行 OCR 文字识别，与本地药品库模糊匹配，语音播报用量。
- **AI 语音问答**：老人可语音提问，通过配置的 AI 接口回复（如 OpenAI 或本地模型）。
- **服药画面上传**：确认服药后自动拍照上传到服务器，便于家属通过小程序查看日志。
- **库存管理与低量提醒**：记录药品剩余量，低于设定天数时提醒。
- **网络状态切换**：WiFi 在线时支持与家属文字聊天及一键呼叫 120；离线时仅提供基础语音提醒。
- **大字体 GUI**：全屏 unihiker GUI 界面，按钮大、操作简单，适合老人使用。
- **完整日志**：所有运行日志保存到本地，错误信息同时显示在界面状态栏并写入日志，程序不会因异常退出。

---

## 项目结构

```
elderly_assistant/
├── main.py                     # 程序入口
├── config.yaml                 # 所有可配置项（API、服务器、路径等）
├── install.py                  # 自动安装依赖并切换清华源
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

直接运行安装脚本（会自动备份原有 pip 源并切换为清华源，Linux 下会添加 `--break-system-packages` 参数）：
```bash
python install.py
```

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
编辑根目录下的 `config.yaml`，根据实际情况修改：
- 服务器地址和接口（用于上传、聊天、紧急呼救等）
- AI 服务密钥（若需 AI 问答）
- 京东 API 密钥（若需比价）
- 摄像头设备 ID、分辨率
- 语音合成参数、蜂鸣器类型（声音文件或 GPIO 引脚）
- 提醒升级间隔等

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

### 离线运行
当检测不到网络时，系统自动切换为离线模式：
- 保留本地语音提醒和蜂鸣器功能。
- 拍照上传、家属聊天、紧急呼救、AI 问答等功能暂停。
- 网络恢复后自动切回在线模式。

---

## 配置说明

所有功能开关和参数都在 `config.yaml` 中，重要项：

| 配置节点 | 说明 |
|----------|------|
| `server.base_url` | 后端服务器地址 |
| `server.upload_endpoint` | 服药照片上传接口路径 |
| `server.chat_endpoint` | 家属聊天消息收发接口 |
| `ai.api_key` | AI 服务密钥（支持 OpenAI 格式） |
| `ai.base_url` | 可切换为私有部署的大模型地址 |
| `camera.device_id` | 摄像头设备编号（一般为 0） |
| `speech.engine` | 语音合成引擎（默认为 pyttsx3） |
| `buzzer.type` | 蜂鸣器类型：`sound`（播放音频文件）或 `gpio`（树莓派 GPIO） |
| `reminders.escalation_interval` | 未确认时音量升级间隔（秒） |
| `paths.data_dir` | 数据文件存放目录 |

所有配置均可热加载（修改后重启程序生效），无需改动代码。

---

## 常见问题

**Q：打开程序后提示“语音识别初始化失败”或“语音播报失败”？**  
A：电脑无麦克风或扬声器，不影响提醒功能，仅语音输入禁用。可在 Windows 声音设置中检查默认设备。

**Q：摄像头打开失败？**  
A：检查摄像头是否被其他程序占用，或修改 `config.yaml` 中 `camera.device_id` 尝试 0、1 等不同编号。

**Q：OCR 识别结果为空白或报错？**  
A：请确保已安装 Tesseract 并配置好环境变量。中文识别需安装 `chi_sim` 语言包。

**Q：语音播报出现“run loop already started”错误？**  
A：程序已使用队列模式解决线程冲突，若仍出现请检查 `services/speech.py` 是否为最新版本。

**Q：如何更换 AI 服务为本地模型（如 Ollama）？**  
A：修改 `config.yaml` 中 `ai.base_url` 为 `http://localhost:11434/v1`，`ai.model` 填写模型名（如 `qwen:7b`），`ai.api_key` 填任意非空字符串即可。

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

所有路径、接口、密钥均从 `config.yaml` 读取，切换环境时仅需修改该文件。

---

## 许可
本项目仅供学习和个人使用，药品信息及健康建议请以医生指导为准。