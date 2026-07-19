# 项目开发历史记录

## v2.9.12 (2026-07-19)

### UI 统一
- **family_monitor**: 统一主页字体和样式与其他页面（仪表盘、提醒、记录等）
  - 移除 `index.html` 的 Google Fonts 引入（Newsreader, Poppins, Lora）
  - body class 从 `page-home` 改为 `bg-gradient`，与其他页面保持一致
  - 修复主页导航栏字体和图标显示与其他页面不一致的问题

---

## v2.9.11 (2026-07-19)

### Bug 修复
- **family_monitor**: 修复注册失败时前端显示 `[object Object]` 的问题
  - `_parse_server_error` 函数增加对 FastAPI 422 验证错误格式的处理
  - 当 `detail` 是列表时，提取所有错误消息并用分号连接显示
- **family_monitor**: 注册页面添加用户名格式提示
  - 输入框添加 `pattern` 和 `title` 属性，前端预校验
  - 添加 `.form-hint` 提示文字："用户名只能包含字母、数字和下划线，长度3-20位（不支持邮箱）"

---

## v2.9.10 (2026-07-19)

### Bug 修复
- **family_monitor**: 修复静态文件在 PATH_PREFIX 模式下被重定向到登录页的问题
  - `is_public` 检查中的 `/static/` 和 `/.well-known/` 前缀改为动态拼接 PATH_PREFIX
  - 修复 `/eating-medication/family/static/css/style.css` 不匹配 `/static/` 导致的 302 重定向

---

## v2.9.9 (2026-07-19)

### Bug 修复
- **family_monitor**: 修复 PATH_PREFIX 模式下 auth_middleware 重定向循环（ERR_TOO_MANY_REDIRECTS）
  - public_paths 从硬编码改为动态拼接 PATH_PREFIX
  - 修复隧道子路径模式下 `/eating-medication/family/login` 不匹配 `/login` 导致的无限重定向

---

## v2.9.8 (2026-07-19)

### Bug 修复
- **family_monitor**: 修复登录成功后用户名仍显示"用户"的问题
  - 补回 Turnstile 改动时误删的 GET /login 和 GET /register 路由
  - login/register 成功后 redirect 值显式拼接 PATH_PREFIX，修复隧道子路径模式下跳转错误
  - logout 重定向 URL 显式拼接 PATH_PREFIX
- **family_monitor**: auth_middleware 和 _verify_jwt_via_server 添加诊断日志，定位 JWT 验证失败根因

### 改进
- **family_monitor**: 所有需认证路由（home.py 10个 + chat.py 2个）添加 _require_login 二次校验
- **family_monitor**: Turnstile JS 加载失败/site_key 为空时降级为直接提交（后端兜底校验）
- **family_monitor**: _verify_jwt_via_server 异常处理从 `except: pass` 改为输出详细日志

### 版本统一
- 全模块版本号统一至 2.9.8（server、family_monitor、elderly_assistant）

---

## v2.9.7 (2026-07-17)

---

## v2.9.6 (2026-07-15)

### 安全清理
- 使用 `git filter-repo` 清理 Git 历史中的敏感文件：
  - 删除 `upload_123pan.py`（含明文账号密码）
  - 删除 `代码审查报告.md`（含敏感信息引用）
  - 删除所有 `.zip` 和 `.sha256` 文件历史记录
- 统一所有 commit 的 author/committer 为 diaoyunxi
- 删除 main 以外的分支

### 文档更新
- 更新 `README.md`：版本号、三模块差异表格版本号同步到 2.9.6
- 更新 `elderly_assistant/README.md`：版本号同步到 2.9.6
- 更新 `history.md`：追加 v2.9.6 ~ v2.9.5 变更记录

### 版本统一
- 全模块版本号统一至 2.9.6（server、family_monitor、elderly_assistant）

---

## v2.9.5 (2026-07-15)

### 版本统一
- 全模块版本号统一至 2.9.5

---

## v2.9.4 (2026-07-15)

### Bug 修复
- **family_monitor**: 修复 Starlette 0.28+ 版本兼容性问题
  - `Jinja2Templates.TemplateResponse` 签名变更：`request` 参数变为第一个位置参数
  - 影响文件：`routes/auth.py`、`routes/home.py`、`routes/chat.py`、`routes/admin.py`
  - 错误表现：`TypeError: unhashable type: 'dict'`（GET /login 500 Internal Server Error）

---

## 项目概述

本项目包含三个主要模块：
1. **elderly_assistant** - 老人端TUI应用
2. **server** - 后端服务器
3. **family_monitor** - 子女看护Web端

---

## elderly_assistant 模块

### 初始完善
- 完善elderly_assistant下的所有文件
- 解决install.py和对应的txt文件问题
- 确保无bug

### 重复日逻辑
- 解释重复日逻辑（支持"1,2,3"格式，1=周一等）
- 验证提醒逻辑
- 重复日允许设置为"1,2,3"这种，1代表周一，2代表周二，以此类推

### 调试模式
- 启动main.py时如果带特殊参数，则允许在终端时使用Ctrl+C退出
- 允许调试各功能，日志更加详细

### 依赖安装优化
- 让install.py只安装未拥有的库
- 减少安装时间

### 行空板适配
- 所有功能仅使用行空板的A,B键
- 不用触控，也支持电脑翻页的上下键

### 跨平台兼容
- 适配多个系统Windows
- 也允许TUI

### 错误修复
- 修复`ModuleNotFoundError: No module named 'termios'`错误
- 在main.py中条件导入termios（仅非Windows系统）
- Windows使用msvcrt

### TTS问题修复（第二次）
- 修复TTS时而有用时而无用的问题（根本性修复）
- 改进_init_engine方法：
  - 添加endLoop()确保引擎完全停止
  - 延迟导入pyttsx3，确保环境正确
  - 为每个setProperty调用添加独立的异常处理
  - 改进中文语音检测，支持'中文'关键字
  - 添加语音选择日志输出
  - 未找到中文语音时自动使用默认语音
- 改进_speak_worker工作线程：
  - 为音量设置添加独立异常处理
  - 错误日志包含播报文本前50字符，便于调试
  - 引擎重置成功后立即重试当前播报
  - 增加更详细的错误日志
- 改进stop方法：
  - 添加hasattr检查避免属性不存在错误
  - 添加endLoop()确保引擎完全停止
  - 添加停止日志
- 测试结果：4/4测试用例全部通过，TTS功能稳定可靠

### TTS问题修复（第三次）- 解决中文发音乱码问题
- 问题根因：espeak引擎的中文语音质量极差，听起来像乱码
- 解决方案：使用edge-tts（微软Edge在线TTS）作为主要TTS引擎
- 修改speech.py：
  - 优先使用edge-tts，pyttsx3作为离线备选
  - edge-tts使用zh-CN-XiaoxiaoNeural高质量中文女声
  - 使用playsound3播放生成的mp3文件
  - 添加asyncio支持用于edge-tts异步通信
  - 临时文件自动生成和清理
- 优势：
  - 中文发音自然流畅，质量远超espeak
  - 支持多种中文语音选择（普通话、粤语等）
  - 可调节语速和音量
- 测试结果：4/4测试用例全部通过，中文发音清晰自然

### TTS问题修复（第四次）- 添加本地TTS备选方案
- 问题：pyttsx3+espeak中文发音质量差，需要更好的本地备选
- 解决方案：添加spd-say（speech-dispatcher）作为本地TTS备选
- TTS引擎优先级：
  1. edge-tts（在线，高质量中文女声zh-CN-XiaoxiaoNeural）
  2. spd-say（本地离线，speech-dispatcher命令行）
  3. pyttsx3（本地离线，最后备选）
- 修改speech.py：
  - 添加_tts_type字段标识当前使用的TTS类型
  - _init_engine按优先级依次尝试edge-tts → spd-say → pyttsx3
  - 新增_speak_spd_say方法使用spd-say命令行播放中文
  - _speak_worker根据_tts_type选择对应的播放方法
- spd-say配置：
  - 语言：zh（中文）
  - 语速：-10（稍慢，更清晰）
  - 等待模式：-w（等待播放完成）
- 测试结果：
  - edge-tts：4/4通过，中文发音清晰自然
  - spd-say：测试通过，本地离线可用

### TTS问题修复（第五次）- 使用espeak-ng作为本地TTS
- 问题：spd-say和pyttsx3中文发音质量差
- 解决方案：使用espeak-ng的cmn-latn-pinyin语音作为本地TTS
- TTS引擎优先级：
  1. edge-tts（在线，高质量中文女声zh-CN-XiaoxiaoNeural）
  2. espeak-ng（本地离线，cmn-latn-pinyin语音）
  3. spd-say（本地离线，speech-dispatcher命令行）
  4. pyttsx3（本地离线，最后备选）
- 修改speech.py：
  - 新增_speak_espeak_ng方法使用espeak-ng命令行播放中文
  - 使用espeak-ng -v cmn-latn-pinyin --stdout生成音频
  - 使用aplay -q播放生成的音频流
  - _init_engine按优先级依次尝试edge-tts → espeak-ng → spd-say → pyttsx3
  - _speak_worker根据_tts_type选择对应的播放方法
- 测试结果：
  - edge-tts：3/3通过，中文发音清晰自然
  - espeak-ng：3/3通过，本地离线可用，cmn-latn-pinyin语音

### TTS简化 - 直接使用pyttsx3 (2026-06-14)
- 问题：之前的TTS实现过于复杂，包含edge-tts、espeak-ng、spd-say、pyttsx3四级回退链
- 解决方案：移除所有在线TTS和命令行TTS，直接使用pyttsx3作为唯一TTS引擎
- 修改speech.py：
  - 移除edge-tts、espeak-ng、spd-say相关代码
  - 移除asyncio、tempfile、subprocess、socket等不再需要的导入
  - 移除_try_init_offline_tts、_check_network、_reset_engine等方法
  - 移除_tts_type状态管理和复杂错误重试计数逻辑
  - _init_engine直接使用pyttsx3.init()，设置volume=50/100，rate=200
  - _speak_worker简化为直接调用engine.say(text) + engine.runAndWait()
  - speak()方法简化，队列只传text（不再传volume）
  - Vosk语音识别部分保持不变
- 优势：
  - 代码从332行精简到约180行
  - 无需网络连接即可使用
  - 无需系统级依赖（espeak-ng、speech-dispatcher）
  - 维护简单，逻辑清晰

### install.py完善
- requirements.txt添加edge-tts
- install.py添加edge-tts和espeak-ng的安装逻辑
- 添加系统级依赖检查（espeak-ng）

### 设备ID获取优化 - 使用pinpong库获取FCC ID
- 修改`elderly_assistant/services/device_id.py`：
  - 行空板M10设备标识改为通过pinpong库获取FCC ID格式（FCC_开头+12位MAC地址）
  - 移除Linux和Windows兼容代码，老人端仅用于M10平台
  - 添加详细的日志输出，便于调试
- 修改`elderly_assistant/tui/tui_app.py`：
  - 系统设置菜单新增"设备FCC ID"显示项
  - 选择后可语音播报FCC ID，提示用户在子女端输入此ID完成绑定
- 修改`family_monitor/templates/settings.html`：
  - 设备绑定表单标签改为"设备FCC ID"
  - 更新placeholder和提示信息，明确格式为FCC_开头后跟12位十六进制字符

### 老人端WiFi配置功能 - 热点+Web配置界面
- 新增`elderly_assistant/services/hotspot_manager.py`：
  - 使用nmcli创建无密码热点（SSID: M10-Config）
  - 支持热点启动、停止、状态检查
- 新增`elderly_assistant/services/wifi_config.py`：
  - 内置HTTP服务器（端口8088）提供Web配置界面
  - WiFi扫描：使用nmcli扫描周边网络，按信号强度排序
  - WiFi连接：支持加密和开放网络，显示连接状态
  - 服务器地址配置：保存至本地配置文件
  - 响应式移动端UI，支持手机直接访问配置
- 修改`elderly_assistant/main.py`：
  - 启动时自动创建热点并启动Web配置服务
  - 退出时自动清理热点和Web服务
  - 日志输出热点名称和访问地址

### WiFi配置端口冲突与Bug修复 (2026-06-10)
- 问题: 日志显示 [Errno 98] Address already in use - 端口4321被占用
- 解决方案: 将WiFi配置Web服务端口从4321改为8088
- 修改的文件:
  - elderly_assistant/services/wifi_config.py:
    - CONFIG_PORT 从 4321 改为 8088
    - 修复 _handle_save_config 方法中的bug: 缺少 data = json.loads(body) 解析步骤，导致使用未定义的 data 变量
  - elderly_assistant/main.py:
    - 日志消息中的地址从 http://10.0.0.1:4321 改为 http://10.0.0.1:8088
- 修复的Bug详情:
  - _handle_save_config 方法中，代码读取了body = self.rfile.read(content_length) 但没有将其解析为JSON
  - 随后直接使用 data.get('server_url', '')，导致 NameError: name 'data' is not defined
  - 添加 data = json.loads(body) 修复此问题
- 日志中发现的其他问题（无需修改，代码已正确处理）:
  - Edge TTS播放失败: Temporary failure in name resolution - DNS解析失败
  - 代码已正确处理: 自动切换到本地离线TTS（espeak-ng）

---

### 摄像头功能重构 - 使用 dfrobot_huskylensv2 库 (2026-06-14)
- 问题: OpenCV (cv2) 在 M10 嵌入式平台上依赖重、兼容性差，需要更轻量的摄像头方案
- 解决方案: 使用 DFRobot HuskyLensV2 AI 摄像头模块替代 OpenCV
- 修改的文件:
  - `elderly_assistant/core/camera.py`:
    - 移除 cv2 (OpenCV) 依赖
    - 新增 `_init_huskylens(config)` - 初始化 HuskyLens 连接（支持 I2C 和 UART）
    - 新增 `get_huskylens(config)` - 获取 HuskyLens 单例实例
    - 重构 `capture_image(config)` - 使用 `hl.takePhoto()` 替代 `cv2.VideoCapture`
    - 新增 `recognize_objects(config, algorithm)` - 物体识别功能
    - 新增 `recognize_face(config)` - 人脸识别功能
    - 新增 `reset_connection()` - 重置连接
  - `elderly_assistant/tui/tui_app.py`:
    - `capture_and_upload` 方法改用 HuskyLens API
    - 移除 `import cv2` 和 `cv2.VideoCapture` 调用
    - 改为 `from core.camera import get_huskylens` + `hl.takePhoto()`
  - `elderly_assistant/utils/config_loader.py`:
    - DEFAULT_CONFIG 新增 camera 配置节:
      - `connection`: "i2c" (支持 "i2c" 或 "uart")
      - `uart_tty`: "/dev/ttyS1"
      - `uart_baudrate`: 115200
      - `save_path`: "data/captures"
  - `elderly_assistant/core/__init__.py`:
    - 模块说明更新为 "HuskyLens AI摄像头功能"
- HuskyLens API 使用:
  - `HuskylensV2_I2C()` / `HuskylensV2_UART(tty, baudrate)` - 连接方式
  - `knock()` - 检测连接
  - `takePhoto()` - 拍照
  - `switchAlgorithm(algo)` - 切换算法
  - `getResult(algo)` / `available(algo)` - 获取识别结果
  - 算法常量: `ALGORITHM_OBJECT_RECOGNITION`, `ALGORITHM_FACE_RECOGNITION` 等

## server 模块

### 依赖问题修复
- 修复Pillow 10.1.0与Python 3.14的兼容性问题
- server/requirements.txt中更新Pillow至10.4.0
- 修复zhipuai>=2.2.0 not found错误
- requirements.txt中改为zhipuai>=2.1.5

### Python版本管理
- 卸载Python 3.14
- 使用winget安装Python 3.12.10
- 配置项目使用Python 3.12

### ZhipuAI集成
- 集成ZhipuAI SDK到服务端
- API Key单独存储
- 排除上传到GitHub
- 处理老人端POST消息
- 使用模型glm-4.7-flash

### 日志增强
- 服务器端添加连接显示日志
- 包含客户端信息、请求体和响应状态

### 配置持久化
- 老人端所有配置保存
- 启动时读取，包括服务器地址等
- 老人端只负责设置服务器地址，别的设置都不要

### TTS问题修复
- 解决TTS时而有用时而无用的问题
- 添加引擎错误恢复和重置机制
- 所有操作都TTS播放语音

### 麦克风问题
- 解决麦克风录音失败（PyAudio缺失）问题
- 优化代码处理PyAudio缺失情况
- 语音功能不可用时自动切换打字输入
- 未正确启动打字询问，有麦克风仍报错问题
- 修改_ask_assistant_voice方法，语音输入失败后询问用户是否切换打字输入

### 日志乱码修复
- post图片至服务器，服务器日志显示文件内容为乱码
- 修改LoggingMiddleware，对文件上传请求只记录元信息，不解码二进制数据

### 公开端点
- 添加public端点供老人端使用
- 401 Unauthorized error for AI API修复

### install.py完善
- 重写install.py，添加包安装检查逻辑
- 支持跨平台pip配置
- 显示安装摘要（新安装/已跳过/失败）

---

## family_monitor 模块

### 项目架构
- 在项目根目录创建一个文件夹
- 纯Python开发
- 所有配置不写死
- 不要只用一个文件完成
- 将每个功能拆成一个文件
- 项目架构不要只有一层
- 要根据需要建立多个文件夹及子文件夹

### 自动安装
- 自动pip python库
- Linux带--break-system-packages参数
- 自动换为清华源并备份原源

### Web端开发
- 为子女查看的web端
- UI精美
- 端口443（后改为4430）
- 持续工作直到所有功能符合要求可用无bug

### UI设计
- UI不少于10000字符
- 响应式设计
- 丰富的动画和交互效果
- 数据统计和可视化展示

### 页面实现
- 首页（index.html）
- 仪表板（dashboard.html）
- 用药提醒（reminders.html）
- 用药记录（records.html）
- 系统设置（settings.html）

### 用户认证系统
- 注册密码用不可逆加密
- 输入密码进行加密校验是否相等
- 使用bcrypt算法进行密码加密
- 12轮盐值加密
- 密码验证使用bcrypt.checkpw

### 认证模块实现
- 创建core/auth.py - 用户认证核心功能
- 创建core/session.py - 会话管理功能
- 创建routes/auth.py - 认证路由
- 创建templates/login.html - 登录页面
- 创建templates/register.html - 注册页面

### 依赖添加
- bcrypt>=4.1.0
- itsdangerous>=2.1.2

### 中间件实现
- 认证中间件保护需要登录的页面
- 公开路径不需要认证（/login, /register, /static, /favicon.ico）
- 会话令牌验证
- Cookie安全设置（httponly=True）

### 会话管理
- 使用itsdangerous创建加密会话令牌
- 7天有效期
- 自动过期处理

### 安全特性
- 不可逆加密：密码使用bcrypt加密，无法解密
- 盐值随机：每次加密使用不同的随机盐值
- 会话保护：所有页面（除登录/注册/静态文件）需要登录
- Cookie安全：httponly=True防止XSS攻击
- 前端验证：注册时前端检查密码匹配

### 配置文件
- .env添加SECRET_KEY配置
- requirements.txt添加依赖

### 路由保护
- 更新routes/__init__.py导出auth_router
- 更新main.py注册认证路由
- 添加认证中间件

### 页面更新
- 所有页面模板添加用户信息显示
- 添加登出按钮
- 安全访问request.state.user变量

### 错误修复
- 修复模板中request.state.user不存在的错误
- 中间件初始化用户状态为None
- 所有模板使用安全的变量访问方式（`{{ request.state.user or '用户' }}`）

### 端口修改
- 从443端口改为4430端口

### 安装脚本与执行入口修复 (2026-06-10)
- 问题: `./main.py` 运行时 shell 误将 Python 当作脚本解析，出现 `$'\n...\n': 未找到命令` / `from: can't read /var/mail/...` / `未预期的符号('` 等错误
- 根因: `family_monitor/main.py` 缺少 shebang 声明；`family_monitor/install.py` 未与 `elderly_assistant/install.py` 对齐（缺少系统检查、清华源配置、`--break-system-packages` 回退等）
- 修复:
  - `family_monitor/main.py`: 首行添加 `#!/usr/bin/env python3`，确保 Linux/macOS 下 `./main.py` 可直接执行
  - `family_monitor/install.py`: 完全重写为与 `elderly_assistant/install.py` 同构的安装脚本
- install.py 关键能力:
  - `check_system_requirements()`: 检查 Python 3.8+ 与 pip 可用性
  - `backup_pip_source()`: 备份原 pip 源并切换为清华源（Windows 写 `~/pip/pip.ini`，Linux 写 `~/.pip/pip.conf`）
  - `is_package_installed()`: 优先 `importlib`，失败回落到 `pip show`；内置 `python-multipart -> multipart`、`python-dotenv -> dotenv` 名称映射
  - `install_package()`: 优先 `pip install`，失败自动回退到 `pip install --break-system-packages`，适配 Debian/Ubuntu 的 `EXTERNALLY-MANAGED`
  - `install_requirements()`: 读取 `requirements.txt`，跳过已安装包，输出新安装/跳过/失败摘要
- 验证:
  - `python -m py_compile family_monitor/install.py` 通过
  - `family_monitor/main.py` 首行为 `#!/usr/bin/env python3`

### 设置页面配置保存修复 (2026-06-14)
- 问题: 显示配置及链接配置中的API密钥UI显示保存成功，但刷新后全部丢失
- 根因分析:
  1. config.py 的 save_config() 方法缺少 DISPLAY_* 字段，显示设置未写入配置文件
  2. home.py 以 GBK 编码保存，且第100行有字面量反引号r反引号n导致Python语法错误
  3. home.py 的 get_settings 路由未将 display_settings 传递到模板
  4. settings.html 缺少页面加载时的显示设置初始化代码
  5. settings.html 的 saveDisplaySettings 中 checkbox 选择器不精确
- 修复的文件:
  - family_monitor/core/config.py:
    - save_config() 的 config_data 字典中添加 DISPLAY_THEME、DISPLAY_COLOR、DISPLAY_LANGUAGE、DISPLAY_ANIMATIONS、DISPLAY_COMPACT 五个字段
  - family_monitor/routes/home.py:
    - 文件编码从 GBK 转为 UTF-8
    - 移除第100行的字面量反引号r反引号n
    - get_settings 路由的 TemplateResponse context 中添加 display_settings
  - family_monitor/templates/settings.html:
    - 添加 initDisplaySettings() 函数，使用 display_settings tojson 在页面加载时初始化主题、颜色、语言、动画、紧凑模式
    - 修复 saveDisplaySettings 中的 checkbox 选择器，改为在显示设置区域内精确选择

### TemplateResponse API 兼容性修复 (2026-06-14)
- 问题: 访问登录页面时报错 `TypeError: unhashable type: 'dict'`
- 根因: Starlette 新版本 `TemplateResponse` API 签名变更，旧版 `TemplateResponse(name, context)` 需改为 `TemplateResponse(request, name, context)`，旧代码将 dict 作为模板名传入 Jinja2 缓存查找，导致不可哈希错误
- 修复的文件:
  - `family_monitor/routes/auth.py` - 5处 TemplateResponse 调用
  - `family_monitor/routes/home.py` - 5处 TemplateResponse 调用
  - `family_monitor/routes/admin.py` - 1处 TemplateResponse 调用
- 修改内容: 所有 `templates.TemplateResponse("xxx.html", {"request": request, ...})` 改为 `templates.TemplateResponse(request, "xxx.html", {...})`，`request` 不再放入 context 字典

---

## 工作流程

### 注册流程
1. 用户输入用户名和密码
2. 前端验证密码匹配
3. POST到服务器
4. bcrypt加密密码
5. 保存到users.json

### 登录流程
1. 用户输入用户名和密码
2. POST到服务器
3. 加载用户数据
4. bcrypt验证密码
5. 创建会话令牌
6. 设置Cookie

### 访问保护
1. 中间件检查Cookie
2. 验证会话令牌
3. 有效则放行
4. 无效则重定向到登录页

### 登出流程
1. 删除Cookie
2. 重定向到登录页

---

## 技术栈

### elderly_assistant
- Python TUI框架
- 多线程后台任务处理
- 错误处理与日志记录
- YAML/JSON配置文件管理
- 依赖安装与管理

### server
- FastAPI REST API
- SQLAlchemy数据库
- ZhipuAI SDK
- WebSocket通信
- APScheduler定时任务
- PyAudio语音采集

### family_monitor
- FastAPI Web框架
- Jinja2模板引擎
- bcrypt密码加密
- itsdangerous会话管理
- 响应式CSS设计
- 前端JavaScript验证

---

## 文件结构

```
项目/
├── elderly_assistant/
│   ├── main.py
│   ├── install.py
│   ├── requirements.txt
│   ├── config.yaml
│   └── README.md
├── server/
│   ├── main.py
│   ├── install.py
│   ├── requirements.txt
│   ├── .env
│   └── README.md
└── family_monitor/
    ├── main.py
    ├── install.py
    ├── requirements.txt
    ├── .env
    ├── .gitignore
    ├── core/
    │   ├── config.py
    │   ├── auth.py
    │   └── session.py
    ├── routes/
    │   ├── __init__.py
    │   ├── home.py
    │   └── auth.py
    ├── templates/
    │   ├── index.html
    │   ├── dashboard.html
    │   ├── reminders.html
    │   ├── records.html
    │   ├── settings.html
    │   ├── login.html
    │   └── register.html
    ├── static/
    │   └── css/
    │       └── style.css
    └── README.md
```

---

## 安全注意事项

1. .env文件包含敏感信息，已添加到.gitignore
2. data/目录包含用户数据，已添加到.gitignore
3. SECRET_KEY应在生产环境中修改为随机字符串
4. 密码使用bcrypt加密，无法解密还原

---

## 运行方式

### elderly_assistant
```bash
cd elderly_assistant
python install.py
python main.py
```

### server
```bash
cd server
python install.py
python main.py
```

### family_monitor
```bash
cd family_monitor
python install.py
python main.py
```

访问 http://localhost:4430

---

# 大版本更新 v2.0 (2026-06-27) - 老人端 pinpong/unihiker 重构

## 概述

本次大版本更新彻底重构老人端交互模式：**舍弃 TUI 界面，改用 pinpong 库 + unihiker GUI 库实现适配行空板 M10 的图形化交互**。同时完善端到端的设备配网、注册、用药计划下发、到点提醒全流程。

完整工作流：
1. 老人端启动 → 默认显示当前时间 + 后台创建热点 `M10-Config`
2. 用户连接热点 → 访问 `10.0.0.1:8088` → 仅设置服务器地址和 WiFi（名称+密码）
3. 老人端 nmcli 连接 WiFi → 通过 pinpong 库获取 FCC ID → POST 到服务器注册设备
4. 子女端设置服务器地址和设备 FCC ID → 服务器校验设备是否存在
5. 子女端设置用药时间（药品名、剂量、服药时间列表、频率、数量）→ POST 到服务端
6. 老人端每分钟 curl 获取用药时间 → 到点使用 pinpong 蜂鸣器提醒
7. 老人按 A 键确认服药、B 键暂缓 5 分钟

## pinpong 库 API 调研

通过搜索获取了 pinpong 库的完整 API 文档（行空板 M10 专用）：

- **Board**：`Board().begin()` 初始化板子
- **Pin**：`Pin(pin, mode)` GPIO 控制，`pin.write_digital(1)` / `pin.read_digital()`
- **button_a / button_b**：`button_a.is_pressed()` 检测按下
- **buzzer**：`buzzer.melody(melody, tempo)` 播放旋律；音乐常量 `DADADADUM`、`BA_DING`、`JUMP_UP`、`POWER_DOWN`、`PRELUDE` 等；播放模式 `Once` / `Forever` / `OnceInBackground` / `ForeverInBackground`；`buzzer.off()` 停止
- **light**：`light.read()` 读光感
- **accelerometer**：`accelerometer.get_x/y/z()` 三轴加速度
- **gyroscope**：`gyroscope.get_x/y/z()` 三轴陀螺仪
- **UART / SPI / I2C**：`UART(baudrate, tx, rx)`、`SPI()`、`I2C()` 通信总线

unihiker GUI 库：
- `gui = GUI()` 实例化
- `gui.draw_text(x, y, text, ...)` 文本
- `gui.draw_digit(...)` 数字
- `gui.draw_image(...)` / `gui.draw_emoji(...)` 图像
- `gui.add_button(...)` 按钮
- `gui.draw_clock(...)` / `gui.fill_clock(...)` 时钟
- `gui.draw_qr_code(...)` 二维码

## 服务端改动

### 新增 5 个设备公开接口（无需 JWT 认证）
文件：[server/app/api/v1/endpoints/public.py](server/app/api/v1/endpoints/public.py)

- 新增 `FamilyMedicationPlan` Pydantic 模型
- `GET /api/v1/public/device/check/{device_id}` - 子女端绑定前校验设备是否已注册
- `GET /api/v1/public/device/schedule/{device_id}` - 老人端每分钟轮询用药时间表（聚合所有计划的每个时间点）
- `POST /api/v1/public/device/medication_plan` - 家属通过设备 ID 设置用药计划
- `GET /api/v1/public/device/plans/{device_id}` - 获取设备所有用药计划
- `DELETE /api/v1/public/device/medication_plan/{plan_id}` - 删除用药计划

设备注册沿用原 `POST /api/v1/public/device/register`，自动以 FCC ID 作为 username 创建 role=elderly 用户。

## 老人端重构

### main.py 完全重写
文件：[elderly_assistant/main.py](elderly_assistant/main.py)

- 舍弃原 TUI（tui_app.py 不再使用）
- 主循环每秒更新 unihiker GUI 时间显示
- 后台线程创建热点并启动配网 Web 服务
- `MedicationPoller` 线程每 60 秒轮询用药计划
- 到点触发：调用蜂鸣器 + GUI 显示提醒；A 键确认服药、B 键暂缓 5 分钟
- 防重复触发：同一计划同一时间点 60 秒内只触发一次
- 暂缓后 5 分钟复活，可再次暂缓或确认
- 所有 pinpong/unihiker 导入放 try-except ImportError，非 M10 环境可调试运行

### 新建 core/display.py
文件：[elderly_assistant/core/display.py](elderly_assistant/core/display.py)

集中所有屏幕显示逻辑：
- `show_time(now)` 显示当前时间
- `show_reminder(drug_name, dosage)` 显示用药提醒
- `show_config_mode()` 显示配网模式提示
- `show_status(server_url, connected)` 显示网络状态
- `show_fcc_id(fcc_id)` 显示设备 FCC ID
- `show_next_reminder(time, drug)` 显示下次提醒

### buzzer.py 重写
文件：[elderly_assistant/services/buzzer.py](elderly_assistant/services/buzzer.py)

- `play_reminder()` 在独立线程循环播放 `buzzer.BA_DING`，直到 stop
- `stop()` 停止蜂鸣
- `play_success()` 播放 `buzzer.JUMP_UP` 表示确认服药

### wifi_config.py 重写
文件：[elderly_assistant/services/wifi_config.py](elderly_assistant/services/wifi_config.py)

- 使用标准库 `http.server.BaseHTTPRequestHandler`（无额外依赖）
- `CONFIG_PORT=8088`，提供 HTML 配网页面
- 仅收集：服务器地址 + WiFi 名称 + WiFi 密码
- 表单提交后调用 nmcli 连接 WiFi
- WiFi 连接成功后获取 FCC ID 并 POST 注册到服务器

### hotspot_manager.py 修改
文件：[elderly_assistant/services/hotspot_manager.py](elderly_assistant/services/hotspot_manager.py)

统一热点参数：
- `HOTSPOT_SSID = "M10-Config"`
- `HOTSPOT_IP = "10.0.0.1"`
- `HOTSPOT_WEB_PORT = 8088`

### http_client.py 修改
文件：[elderly_assistant/services/http_client.py](elderly_assistant/services/http_client.py)

新增方法：
- `get_medication_schedule()` → GET `/api/v1/public/device/schedule/{device_id}`
- `confirm_medication()` 确认服药上报

### device_id.py（沿用，无需修改）
文件：[elderly_assistant/services/device_id.py](elderly_assistant/services/device_id.py)

- 优先通过 pinpong `Board().begin()` 获取 `FCC_{MAC}`
- 失败回退 `DEV_{UUID}`

### 配置文件
- `config.yaml` 与 `utils/config_loader.py` 新增 `server.base_url`、`hotspot.*`、`reminder.poll_interval=60`、`reminder.snooze_minutes=5`

## 子女端改动

### api_client.py 修改
文件：[family_monitor/core/api_client.py](family_monitor/core/api_client.py)

- **Bug 修复**：原 `register_device` 方法存在 `return` 后紧跟 `return` 的死代码，缺少 else 分支，已重构为显式 if/else
- 新增方法：`check_device()`、`get_device_plans()`、`set_medication_plan()`、`delete_medication_plan()`

### home.py 修改
文件：[family_monitor/routes/home.py](family_monitor/routes/home.py)

- `bind_device` 路由绑定前先调用 `check_device` 校验设备是否已注册
- 新增路由：
  - `GET /medication_settings` - 用药设置页面
  - `POST /medication_settings/add` - 新增用药计划
  - `POST /medication_settings/delete/{plan_id}` - 删除计划

### 新建 medication_settings.html
文件：[family_monitor/templates/medication_settings.html](family_monitor/templates/medication_settings.html)

- 当前用药计划列表（可删除）
- 添加计划表单：药品名、剂量、可动态增删的服药时间、频率、数量
- fetch API 提交，Toast 通知反馈

### settings.html 修改
- `bindDevice()` JS 函数增加非 JSON 响应容错
- 绑定成功后才刷新页面

## 测试验证

- 老人端所有模块导入测试通过
- 老人端用药提醒全流程测试通过（触发 → 防重复 → 暂缓 → 复活 → 确认）
- 子女端语法检查通过
- 非 M10 环境优雅降级运行正常（pinpong/unihiker 缺失时主循环仍可工作）

## 端口/IP 统一

本次重构统一了多处端口不一致问题（原 hotspot_manager.py 用 4321、main.py 日志用 8088 等）：
- 热点 IP：`10.0.0.1`
- 配网 Web 端口：`8088`
- 子女端 Web 端口：`4430`（HTTPS）
- 服务端 API 端口：HTTPS 默认

---

# v2.2.0 - 安全加固版本（2026-07-01）

## 背景

基于对 `diaoyunxi/eating-medication` 仓库的全面严格审查，发现 47+ 个安全问题（11 严重 + 15 高危 + 21 中危 + 20+ 低危），详见 `SECURITY_AUDIT_REPORT.md`。本次发布为安全加固版本，允许破坏性变更。

## 服务端（server）修复

### 严重问题修复
- **C2**：`main.py` 默认 `.env` 中 `DEBUG=False`，`SECRET_KEY` 用 `secrets.token_urlsafe(32)` 动态生成
- **C3**：`config.py` 启动时校验 SECRET_KEY，弱密钥拒绝启动
- **C4**：聊天端点（send/history/ws）全部加 `Depends(get_current_user)`，sender_id 从 token 提取
- **C5**：设备端点引入 `X-Device-Token` 机制，写/读操作需携带 token；AI 端点 IP 限流
- **C7**：删除内联 CORS，改用 `setup_cors(app)` 从 `ALLOWED_ORIGINS` 环境变量读取白名单
- **C8**：日志中间件对敏感路径跳过请求体记录，对敏感字段脱敏
- **C9**：updater 加 SHA256 校验查找，auto_pull 默认 False

### 高危问题修复
- **H7**：JWT sub 统一为 str，增加 type/jti 字段，token 有效期缩短至 1 小时
- **H8**：登录防时序攻击（用户不存在时执行 dummy bcrypt）
- **H9**：库存扣减原子化，按 plan_id+scheduled_time 去重，status 计算（missed/taken/pending）
- **H10**：异常不返回客户端，logger.exception 记录
- **H11**：stock_checker 改用 AsyncIOScheduler
- **H12**：删除 env.py 中 purchase_suggestion 引用，修正 alembic.ini script_location
- **H13**：bind_family 增加 device_id 校验（弱保护）
- **H14**：WebSocket token 长度校验
- **H15**：文件上传限制 5MB

### 中危问题修复
- M12：schemas/auth.py 集成 validators
- M13：schedule_times 加时间格式校验
- M14：所有 datetime.utcnow() 改 datetime.now(timezone.utc)
- M16：chat ws 用 `with SessionLocal() as db`
- M17：get_db 统一从 dependencies 导入
- M18：异常处理器脱敏
- M19：low_stock_threshold 改 Float
- M20：confidence 改 Optional

### 低危修复
- L8：注册端点 IP 限流
- L9：User 模型增加 is_active、last_login_at 字段
- L11：ChatMessage 字段加索引
- L12：history limit 上限 200
- L14：ai_query_log 默认模型改 glm-4.7-flash

### 依赖升级
- python-jose 3.3.0 → 3.4.0（修复 CVE-2024-33664）
- pydantic 2.9.2 → 2.10.0（修复 CVE-2024-1561）
- sqlalchemy 2.0.35 → 2.0.36（修复 CVE-2024-29906）
- 新增 bcrypt>=4.0,<4.1 约束
- 测试依赖移至 requirements-dev.txt

## 家属监控端（family_monitor）修复

### 严重问题修复
- **C1**：移除 config.json 中硬编码 SECRET_KEY，改为从 .env 注入，空时自动生成临时密钥并警告；config.json 加入 .gitignore，新增 config.json.example
- **C6**：CORS 改从 ALLOWED_ORIGINS 环境变量读取；引入 CSRF 双重提交防护

### 高危问题修复
- **H2**：cookie 加 secure/samesite=strict；登出调用 invalidate_session；撤销令牌持久化到 data/revoked_tokens.json
- **H3**：移除 SECRET_KEY 的 Web 修改入口
- **H4**：公开路径精确匹配
- **H5**：chat.html XSS 修复（innerHTML → DOM + textContent）
- **H6**：medication_settings.html 移除 `| safe`，改用 data-* 属性

### 中危问题修复
- M1：config.py 不写回 os.environ
- M2：auth.py 加 fcntl 文件锁 + chmod 0600
- M3：添加安全响应头中间件
- M4：禁用 Web 修改 DEBUG
- M5：admin_settings 表单 action 路径修正
- M6：chat 路由传入 current_user 和 elderly_id
- M7：install.py 不修改全局 pip 配置
- M8：device_id URL 编码
- M9：移除未使用的 API_KEY 配置
- M10：端口使用 config.SERVER_PORT

### 低危修复
- L16：更新 README
- L17：修复 routes/__init__.py 编码
- L18：登录限流
- 依赖：requirements.txt `>=` 改 `~=`

## 老人端（elderly_assistant）修复

### 严重问题修复
- **C10**：热点加 WPA2 随机密码；配网服务加 X-Config-Token 校验；server_url 转义防 XSS；CORS 限制为本地热点网关
- **C11**：ai_client.py 改 `config.get('ai', {})` 容错；config.yaml 补充 ai 段

### 高危问题修复
- **H1**：hotspot_manager.py 改列表形式调用 subprocess，去掉 shell=True

### 低危修复
- L6：install.py 改为读取 requirements.txt
- L7：移除 opencv-python、fuzzywuzzy、python-Levenshtein，改用 rapidfuzz
- main.py 自动更新异常不静默
- tui_app.py os.system 改 ANSI 转义序列
- config.yaml 占位符替换

## 跨模块共享文件修复

- **.gitignore**：新增 family_monitor/config.json、elderly_assistant/config.yaml 忽略规则
- **README.md**：生产域名替换为占位符；新增 v2.2.0 版本记录
- **history.md**：移除本地绝对路径（file:///run/media/xixi/...）
- **VERSION**：2.1.0 → 2.2.0
- 新增 config.yaml.example、config.json.example 模板

## 破坏性变更说明

1. **SECRET_KEY 必须配置**：server 和 family_monitor 启动时若未配置 SECRET_KEY（或为已知弱值），生产模式（DEBUG=False）将拒绝启动
2. **设备 token 机制**：首次注册设备会返回 device_token，后续读写操作需在 Header 携带 X-Device-Token，老设备需重新注册
3. **JWT 有效期缩短**：从 7 天缩短至 1 小时，客户端需实现 refresh 机制或重新登录
4. **CORS 白名单**：生产环境必须配置 ALLOWED_ORIGINS 环境变量，否则跨域请求被拒绝
5. **CSRF 防护**：family_monitor 所有 POST 请求需携带 csrf_token
6. **热点加密**：elderly_assistant 热点现在需要密码连接，启动时打印

## 验证

- 服务端：`python -c "from app.main import app; print('OK')"` → OK
- 家属端：`python -c "from main import app; print('OK')"` → OK（含端到端测试通过）
- 老人端：`python -m py_compile` 全部通过，`import main` 成功

# v2.3.0 - 代码质量与安全加固版本（2026-07-07）

## 破坏性变更
- 移除 device_token/X-Device-Token 机制，所有公开接口仅通过 device_id 校验
- 家属端 logout 改为 POST 方法并要求 CSRF 校验
- 老人端删除未使用的 TUI、ReminderManager、AIAssistant、LocalFallback、AIClient、OCREngine 模块

## 安全修复
- 服务端：修复 group_id 为 None 时的数据越权泄露
- 服务端：登录端点添加 IP 限流（每分钟 10 次）
- 服务端：DELETE 用药计划接口添加设备归属校验
- 服务端：修复时区 aware/naive 混用导致的 TypeError
- 服务端：WebSocket chat 异常完全捕获，防止连接泄漏
- 家属端：修复 chat.html XSS 漏洞（用户名注入 JS 字符串）
- 家属端：CSRF 比较改用 secrets.compare_digest 防止时序攻击
- 家属端：_save_users 先加锁后截断，防止写入失败导致数据丢失
- 家属端：修复 _login_attempts 和 _revoked_tokens 内存泄漏
- 老人端：修复 socket 资源泄漏
- 老人端：修复 upload_image 文件不存在异常未捕获

## 功能修复
- 服务端：修复 Alembic 迁移路径错误（始终回退 create_all）
- 服务端：修复 env.py 缺少 chat_message 模型导入
- 服务端：接线服药通知（notify_taken_medication）
- 家属端：修复 chat.html parseInt 对字符串 device_id 返回 NaN
- 家属端：修复 CSS 未定义变量（--font-sans、--brand-color 等）
- 家属端：修复 dashboard/records/reminders 模板的 None 类型错误
- 老人端：修复 Buzzer.beep() 调用不存在的方法
- 老人端：修复 main.py 混用 logging 模块级 API 与 logger 实例
- 老人端：修复 config_loader.py yaml 解析为 None 时的崩溃

## 代码质量
- 删除大量死代码和未使用导入（服务端 8 处、家属端 13 处、老人端 5 处）
- 统一日志脱敏（device_id 前4+后4）
- 修复老人端 requirements.txt 包含未使用依赖
- 修复老人端 config.yaml.example 过时端点配置
- 统一三个子项目的版本号到 2.3.0

---

# v2.4.0 - 移动端导航优化版本（2026-07-07）

## 变更概述

修复 family_monitor（子女看护 Web 端）在移动端导航栏占比过大的问题。原布局在手机/平板上因 `flex-wrap` 换行导致导航栏占据过多垂直空间，影响主内容可视区域。

采用「横向滚动导航 + 头像下拉菜单」方案：
- 导航项改为横向滚动（不再换行），mask-image 实现滚动渐隐提示
- `nav-user`（用户名 + 登出按钮）在移动端折叠为圆形头像按钮，点击展开下拉菜单
- 桌面端（≥769px）保持原布局不变，自动隐藏移动端专属组件

## 响应式断点设计

| 断点 | 范围 | 行为 |
|------|------|------|
| 平板 | ≤1024px | 缩小尺寸但保持横向布局（logo 38px、字号 0.9rem） |
| 手机 | ≤768px | navbar-nav 横向滚动，nav-user 折叠为头像按钮 + 下拉菜单（核心改造） |
| 小屏 | ≤480px | 进一步紧凑（头像 32×32、下拉菜单 min-width 180px） |
| 桌面 | ≥769px | 隐藏头像按钮和下拉菜单，恢复原换行布局 |

## 关键技术点

### CSS 改造（style.css 末尾追加约 314 行）
- `.navbar-container` 强制 `flex-direction: row` + `flex-wrap: nowrap`，避免换行
- `.navbar-nav` 启用 `overflow-x: auto` + `-webkit-overflow-scrolling: touch`，并隐藏滚动条（`scrollbar-width: none` + `::-webkit-scrollbar { display: none }`）
- `.nav-link` 加 `white-space: nowrap` + `flex-shrink: 0`，防止单项被压缩
- 滚动渐隐提示：`mask-image: linear-gradient(to right, transparent 0, #000 12px, #000 calc(100% - 44px), transparent 100%)`
- `.nav-user-avatar`：34×34 圆形按钮，使用 `--gradient-primary` 渐变背景，含 hover 放大 + active 缩小交互
- `.nav-user-dropdown`：绝对定位下拉菜单，含 `opacity/visibility/transform` 三重过渡动画 + `.show` 状态类
- 桌面端 `@media (min-width: 769px)` 显式 `display: none` 隐藏头像按钮和下拉菜单

### HTML 结构改造（6 个模板统一）
保留桌面端原有 `.nav-username` + 登出按钮结构，新增移动端专属元素：
- `.nav-user-avatar` 头像按钮（含用户 SVG 图标 + ARIA 属性）
- `.nav-user-dropdown` 下拉菜单容器（role="menu"）
  - `.nav-user-dropdown-user`：用户信息区（含 `.nav-user-dropdown-avatar` 首字母圆形 + `.nav-user-dropdown-name` 用户名）
  - `.nav-user-dropdown-item.danger`：登出按钮（含登出 SVG 图标）

### JavaScript 交互（IIFE 模式注入）
每个模板 `</body>` 前注入相同 IIFE 脚本：
- `window.__navUserDropdownInit` 防重复初始化标志
- `window.toggleNavUserDropdown(e)`：切换下拉菜单显示状态，同步 ARIA `aria-expanded`
- `window.navLogout()`：登出流程，从 cookie 读取 `csrf_token`，`fetch` POST `/logout` 携带 `X-CSRF-Token` Header，完成后重定向到 `/login`
- `document.click` 监听：点击下拉菜单外部时自动关闭
- `document.keydown` 监听：按 ESC 键关闭下拉菜单

## 涉及的文件清单

### 修改文件（共 11 个）

**CSS 样式（1 个）**：
- `family_monitor/static/css/style.css`：末尾追加 4 个媒体查询块（共约 314 行）

**HTML 模板（6 个，导航栏改造 + CSS 版本号升级）**：
- `family_monitor/templates/index.html`
- `family_monitor/templates/dashboard.html`
- `family_monitor/templates/reminders.html`
- `family_monitor/templates/records.html`
- `family_monitor/templates/settings.html`
- `family_monitor/templates/medication_settings.html`

**CSS 缓存版本号升级（4 个，仅 ?v= 参数）**：
- `family_monitor/templates/admin_settings.html`
- `family_monitor/templates/chat.html`
- `family_monitor/templates/login.html`
- `family_monitor/templates/register.html`

**版本号同步（5 个）**：
- `VERSION`：2.3.0 → 2.4.0
- `family_monitor/updater.py`：`__version__` = "2.3.0" → "2.4.0"
- `server/updater.py`：`__version__` = "2.3.0" → "2.4.0"
- `elderly_assistant/updater.py`：`__version__` = "2.3.0" → "2.4.0"
- `README.md`：当前版本引用和三模块差异表格同步到 2.4.0
- `elderly_assistant/README.md`：当前版本声明同步到 2.4.0

## 兼容性说明

- 桌面端（≥769px）行为完全不变，原有用户名 + 登出按钮正常显示
- 移动端导航项支持横向滑动，长导航也不会换行占满屏幕
- 头像下拉菜单点击外部或按 ESC 自动关闭，符合无障碍访问规范（ARIA 属性完整）
- 登出流程保留 CSRF 防护，POST + X-CSRF-Token Header 与原桌面端一致
- 所有改造均为渐进增强，不破坏现有桌面端功能

## 验证结果

- Jinja2 模板渲染：6 个改造模板全部渲染成功，包含完整新结构
- curl 端到端测试：注册测试用户 testuser/Test1234 后访问首页，HTML 包含 `nav-user-avatar`、`nav-user-dropdown`、`nav-user-dropdown-item`、`toggleNavUserDropdown`、`navLogout` 等所有元素
- 下拉菜单首字母显示正确（"T"），用户名显示 "testuser"

---

## v2.6.0 变更（2026-07-08）

### server 模块

#### 新增删除用户 API

- **背景**：原 users 端点仅有 `GET /users/me`、`PUT /users/me`、`POST /users/bind`，缺少账号注销与家属清理老人账号的能力。
- **新增端点**：
  - `DELETE /users/me`：当前用户注销自己账号。采用**硬删除**（`db.delete`），会触发级联删除（`MedicationPlan` / `MedicationRecord` / `AIQueryLog`，依据 `User` 模型 relationship 的 `cascade="all, delete-orphan"` 配置），删除后不可恢复。
  - `DELETE /users/{user_id}`：家属删除同家庭组的老人账号。校验链：
    1. `current_user.role == "family"`（仅家属可调用）
    2. `user_id != current_user.id`（禁止删除自己，应走 `/me`）
    3. `current_user.group_id is not None`（家属须已绑定老人）
    4. 目标用户存在且 `role == "elderly"`
    5. `target.group_id == current_user.group_id`（必须同一家庭组）
- **UserService 新增方法**：
  - `delete_user(db, user_id) -> bool`：硬删除指定用户，返回是否成功（用户不存在返回 False）。
- **响应格式**：`200 + {"status": "success", "message": "账号已删除"}`，与项目现有 `medication/take` 端点返回风格一致。
- **删除策略决策**：采用硬删除而非软删除（`is_active=False`）。原因：用户已确认删除意图，且家庭组关系仅清空被删用户自身（用户记录整体移除，不影响同组其他成员）。
- **路由顺序**：`/me` 在 `/{user_id}` 之前声明，避免路径参数误匹配（虽 `user_id: int` 类型注解已可拒绝 "me" 字符串，但顺序保障更稳健）。

### 文档同步

- `VERSION`：2.5.0 → 2.6.0
- `README.md`：
  - 版本头更新为 v2.6.0（2026-07-08）
  - 用户 API 表格补充 `DELETE /users/me` 与 `DELETE /users/{user_id}` 两条记录
  - 版本历史段落追加 v2.6.0 条目

---

## v2.7.0 变更（2026-07-08）- 修复"设备即用户"设计缺陷

### 背景与根因

测试发现 4 个失败项，其中 3 个（家属绑定老人、获取设备状态、删除用药计划）指向同一根本问题：**设备（device）与用户（user）的关联模型不完整**。

原设计采用"设备即用户"：`device/register` 接口会自动创建一个 `role="elderly"` 的 User 记录，用 `username` 字段存储 `device_id`。这导致**两套并行的"老人"概念**：

| 老人来源 | 创建方式 | user_id 示例 | 用药计划归属 |
|---------|---------|------------|------------|
| 真实老人 | `/auth/register` 注册（有账号密码） | 13 | plan.user_id=13 |
| 设备老人 | `/public/device/register` 自动创建 | 15、16、17... | plan.user_id=15 |

连锁失败：
- **#9 家属绑定老人 (400)**：家属传 `elderly_user_id=13`（真实老人）+ `device_id=xxx`，但 `elderly.username != device_id`（真实老人 username 是账号名，不是 device_id）→ 400
- **#29 删除用药计划 (404)**：老人用 JWT 创建计划 `plan.user_id=13`，但删除接口用 device_id 反查到虚拟用户 `user_id=15`，`plan.user_id(13) != 15` → 404
- **#21 获取设备状态 (500)**：设备关联虚拟用户 user_id=15，因数据关联异常 → 500

### 修复方案：设备绑定真实老人

在 User 表新增 `device_id` 字段，建立 device_id 与真实老人的关联。家属绑定时把 device_id 关联到真实老人，并迁移虚拟用户数据。

### server 模块改动

#### 数据模型
- `app/models/user.py`：User 模型新增 `device_id` 字段（nullable, unique, index），用于关联真实老人与设备 ID

#### 数据迁移
- `app/migrations/versions/20260708_001_add_device_id_to_users.py`：新增 Alembic 迁移脚本，升级时添加 `device_id` 字段及唯一索引

#### 接口改造
- `app/api/v1/endpoints/public.py`：
  - `_get_device_user`：优先按 `User.device_id` 查找（真实老人），回退 `User.username == device_id`（兼容旧虚拟用户）
  - `register_device`：同步采用新查找逻辑，找不到时才创建虚拟用户（待家属后续绑定）
  - `device_offline`、`check_device`、`ai_ask`：统一采用新查找逻辑

- `app/api/v1/endpoints/users.py`：
  - `bind_family`：重写弱保护逻辑——校验 device_id 对应的设备已注册（虚拟用户或已绑定的真实老人），调用服务层完成数据迁移 + device_id 关联 + 家庭组绑定

#### 服务层改造
- `app/services/user_service.py`：
  - `bind_family`：新增 `device_id` 参数，处理设备关联逻辑
  - 新增 `_migrate_virtual_user_data`：将虚拟用户的用药计划、服药记录、AI 日志、聊天消息迁移到真实老人，然后删除虚拟用户
  - 绑定流程：校验 device_id 未被占用 → 迁移虚拟用户数据 → 删除虚拟用户 → 把 device_id 关联到真实老人 → 家庭组绑定

#### Schema 调整
- `app/schemas/user.py`：`UserOut` 新增 `device_id` 字段，方便家属端查看老人绑定的设备

### 兼容性说明

- **旧虚拟用户兼容**：未绑定的虚拟用户 `device_id` 字段为 None，所有设备查询接口回退到 `username == device_id` 查找，旧数据不破坏
- **设备端无感**：老人端 `elderly_assistant` 无需改动，仍通过 `X-Device-ID` 头标识设备
- **数据迁移自动化**：家属绑定老人时自动迁移虚拟用户数据，无需手动清理

### 验证

- 修复后流程：
  1. 老人通过 `/auth/register` 注册（user_id=13）
  2. 设备通过 `/public/device/register` 注册（创建虚拟用户 user_id=15）
  3. 家属调用 `/users/bind`（elderly_user_id=13, device_id=xxx）：
     - 虚拟用户 user_id=15 的数据迁移到真实老人 user_id=13
     - 删除虚拟用户 user_id=15
     - 真实老人 user_id=13 的 device_id 字段 = xxx
     - 家属加入家庭组
  4. 设备心跳：device_id → 反查到真实老人 user_id=13 → 更新心跳
  5. 设备状态查询：device_id → user_id=13 → 返回真实老人的计划/记录数
  6. 老人创建计划：user_id=13
  7. 删除计划：device_id → user_id=13 → 匹配 plan.user_id=13 → 200 OK

### 文档同步

- `VERSION`：2.6.0 → 2.7.0
- 三个子项目的 `updater.py` 版本号统一升级到 2.7.0
- `history.md` 追加 v2.7.0 变更说明

### 未修复项

- **#16 药名识别 (500)**：1x1 像素测试图无法识别，接口校验本身正常，P2 优先级暂不处理（用户已确认非 BUG）

## install.py 统一加固

### 背景
三模块（`elderly_assistant`、`server`、`family_monitor`）原本各自维护一份 `install.py`，逻辑存在差异：
- `elderly_assistant/install.py`：未做 pip 缺失检测，错误时只 fallback 一次到 `--break-system-packages`
- `server/install.py`：硬编码 Linux 默认加 `--break-system-packages`，其余平台不带
- `family_monitor/install.py`：未处理 PEP 668 错误，无 `--break-system-packages` 重试

新用户/新设备（尤其是精简 Python 镜像或全新 ARM 设备）经常遇到 `externally-managed-environment` 错误，需要手动加 `--break-system-packages`，体验不佳。

### 改造方案

将三份 `install.py` 统一为同一份脚本，逻辑分四步：

1. **检测 pip** — `python -m pip --version`，失败则进入自动安装
2. **按平台自动安装 pip**（pip 缺失时）：
   - Linux：优先 `apt-get update && apt-get install -y python3-pip`，依次尝试 `sudo` 和直接执行
   - Windows：标准库 `urllib.request` 下载 `https://bootstrap.pypa.io/get-pip.py` 并执行
   - 跨平台后备：`python -m ensurepip --upgrade`
3. **正常 pip install** — 使用 `-i PIP_INDEX_URL`（默认清华源）临时指定镜像源，不修改全局 pip 配置
4. **失败重试** — 若 `pip install` 的 stdout/stderr 包含 `--break-system-packages`（PEP 668 提示），自动追加该参数重试一次

### 兼容性

- 保留 `PIP_INDEX_URL` 环境变量覆盖镜像源
- 新增 `GET_PIP_URL` 环境变量覆盖 get-pip.py 下载地址
- 已安装包自动跳过（先 `importlib.import_module` 再回退 `pip show`）
- 失败重试只对 PEP 668 错误生效，其他错误（如版本不存在、No matching distribution）保持原样报错

### 验证

- 三个 `install.py` 内容完全一致（`diff` 无输出）
- 15/15 单元测试通过（覆盖 _split_pkg_name / _check_pip_available / is_package_installed / install_package 重试 / ensure_pip 三个平台路径）
- `elderly_assistant/install.py` 端到端跑通：8 个依赖，6 新装 / 1 跳过 / 1 失败（pinpong 1.2.0 镜像无此版本，合理失败）
- `server/install.py` 端到端跑通：15 个依赖全部成功
- `family_monitor/install.py` 端到端跑通：8 个依赖全部成功

### 文档同步

- `history.md` 追加本次 install.py 统一加固变更说明
- `README.md` 快速开始章节的 `python install.py` 说明保持不变（用户视角体验一致，内部已加固）

