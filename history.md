# 项目开发历史记录

> 本文件依据 git 实际提交历史整理：每个版本取「本版本号最后一次提交」与「上一版本号最后一次提交」的 git diff 作为该版本相对上一版本的全部改动。
> 条目按版本号倒序（最新在前）。

## v2.29.6 (2026-08-04) — 修复 updater API 返回版本号与 VERSION 文件不一致

### 概述
`updater.py` 中 `__version__ = _load_version()` 在模块加载时（进程启动时）执行一次，之后不再更新。当服务运行期间 VERSION 文件被更新（如 git pull 或自动更新覆盖）但进程未重启时，`GET /api/v1/updater` 返回的 `current_version` 仍是旧版本号，导致与 `cat VERSION` 不一致。

### 主要变更
- fix(updater): `get_update_info()` 中 `current_version` 改为每次调用时动态读取 `_load_version()`，不再使用模块加载时固定的 `__version__`
- fix(updater): `check_for_update()` 中所有版本比较与日志输出改为使用 `info["current_version"]`（动态读取值）
- 保留 `__version__` 模块级常量供 `server/app/main.py` 和 `family_monitor/main.py` 的 `from updater import __version__` 使用（FastAPI 应用 version 参数，启动时设置）

### 涉及文件
- `updater.py` — `get_update_info()` 和 `check_for_update()` 中 `__version__` 替换为动态读取
- `VERSION` — 2.29.5 → 2.29.6
- `history.md`

---

## v2.29.5 (2026-08-04) — 修复 unihiker GUI origin 参数值错误

### 概述
验证 M10 相关依赖库（pinpong / unihiker / dfrobot_huskylensv2 / pyttsx3）的函数调用是否真实存在，发现 `core/display.py` 中 `origin='top right'`（带空格）不符合 unihiker 库 API 规范，应使用 `top_right`（带下划线）。传入错误值会导致 unihiker 静默回退到 `top_left`（左上角对齐），使底部服务器状态文本显示位置错误。

### M10 依赖库 API 验证结果
- **pinpong**（11 项 API）：全部真实存在（Board.begin / Pin.P25 / write_digital / button_a.is_pressed / buzzer.play / buzzer.BA_DING / buzzer.JUMP_UP / buzzer.Once / buzzer.stop / light）
- **unihiker GUI**（7 项 API）：6 项真实存在，1 项**不存在**（`origin='top right'`，应为 `top_right`）
- **dfrobot_huskylensv2**（6 项 API）：全部真实存在（HuskylensV2_I2C / HuskylensV2_UART / knock / takePhoto）
- **pyttsx3**（6 项 API）：全部真实存在（init / setProperty / say / runAndWait / stop）

### 主要变更
- fix(display): 修复 `core/display.py` 中 2 处 `origin='top right'` → `origin='top_right'`（show_main_screen 和 show_status 方法中的底部服务器状态文本）

### 涉及文件
- `elderly_assistant/core/display.py` — 2 处 origin 参数值修正
- `VERSION` — 2.29.4 → 2.29.5
- `history.md`

---

## v2.29.4 (2026-08-04) — updater 端点改为访问即更新且无需鉴权

### 概述
将服务端 `/api/v1/updater` 端点从「GET 仅返回版本信息、POST 触发更新、均需登录」改为「GET/POST 均直接触发更新检查与安装、无需鉴权」，使 CI / 部署脚本 / 浏览器直接访问即可完成自更新。

### 主要变更
- refactor(updater): GET `/updater` 从仅返回版本信息改为直接触发更新检查与安装（与 POST 行为一致）
- refactor(updater): 移除 GET/POST 端点的 JWT 鉴权依赖（`get_current_user`），改为公开访问
- refactor(updater): 移除不再使用的导入（`Depends`、`get_update_info`、`get_current_user`、`User`）
- docs(readme): 新增「服务端 HTTP 触发更新」章节，说明 GET/POST 均触发更新且无需鉴权
- docs(readme): API 文档新增 `/updater` 端点表格
- docs(readme): 修正自动更新机制中 `auto_pull` 描述（实际由 `.env` 的 `AUTO_PULL` 控制，缺省 True）

### 涉及文件
- `server/app/api/v1/endpoints/updater.py` — GET/POST 均改为 `check_for_update()`，移除鉴权
- `VERSION` — 2.29.3 → 2.29.4
- `README.md` — API 文档新增 `/updater` 表格、自动更新机制章节更新
- `history.md`

---

## v2.28.0 (2026-08-01) — 多登录方式注册与绑定管理

### 概述
相对 v2.27.1，本版本对账号注册与登录方式管理进行了重大改进：OAuth 首次登录不再跳转注册页补全手机号/密码，而是直接自动注册；注册页移除第三方绑定入口；设置页新增「登录方式管理」板块，支持绑定/解绑手机号、邮箱、GitHub、Gitee 四种登录方式。

### 主要变更
- feat(auth): OAuth 首次登录改为自动注册（`AuthService.auto_register_oauth`），不再跳转注册页要求补全手机号/密码
- feat(auth): 新增登录方式管理端点（查询绑定状态、绑定/解绑手机号、绑定/解绑邮箱、解绑 OAuth）
- feat(auth): 新增 OAuth 绑定流程（bind mode），已登录用户可在设置页直接绑定 GitHub/Gitee
- feat(auth): 邮箱冲突时自动合并绑定到现有账号
- feat(frontend): 注册页移除"或绑定第三方账号"分区及 OAuth 绑定按钮
- feat(frontend): 设置页新增「登录方式管理」卡片，绿色显示已绑定、灰色显示未绑定，点击可绑定/解绑
- feat(frontend): 绑定手机号弹窗（手机号+密码）、绑定邮箱弹窗（邮箱+验证码）
- fix(auth): 解绑时至少保留一种登录方式，防止用户无法登录
- refactor(oauth): OAuth 回调流程重构，支持 bind mode（`oauth_bind_jwt` cookie）
- docs: 更新 README 中 OAuth 流程说明，版本号升至 v2.28.0

### 涉及文件
- `server/app/services/auth_service.py` — 新增 `auto_register_oauth`、`get_login_methods`、`bind_phone`、`bind_email`、`unbind_phone`、`unbind_email`、`unbind_oauth`、`count_bound_methods` 方法
- `server/app/schemas/auth.py` — 新增 `BindPhoneReq`、`BindEmailReq`、`BindEmailSendCodeReq` schema
- `server/app/api/v1/endpoints/auth.py` — 新增 `/login-methods`、`/bind-phone`、`/bind-email/send-code`、`/bind-email`、`/unbind-phone`、`/unbind-email`、`/unbind-oauth/{provider}` 端点
- `server/app/api/v1/endpoints/oauth.py` — 新增 `_bind_authorize` 函数、`/oauth/{provider}/bind` 端点、回调中 bind mode 检测、`_mask_email` 导入修复
- `family_monitor/templates/register.html` — 移除 OAuth 绑定分区与相关 JS
- `family_monitor/templates/settings.html` — 新增登录方式管理卡片、绑定弹窗、CSS/JS
- `family_monitor/routes/auth.py` — 新增登录方式管理代理路由与 OAuth 绑定入口路由
- `VERSION`、`README.md`、`history.md`

---

## v2.24.1 (2026-07-29) — 版本号升至 2.24.1（.env 注释修正）

### 概述
相对 v2.24.0，本版本仅 1 个提交、无功能性代码改动（仅 `.env` 注释微调），为纯版本号对齐。

### 主要变更
- chore: 版本 2.24.0 -> 2.24.1（.env 注释修正）

---

## v2.24.0 (2026-07-29) — 重构版本收尾：.env 注释修正 + read_env_dict bug 修复标注

### 概述
相对 v2.23.0，本版本共 2 个提交、1 个文件（`.env`）变更。作为 v2.23.0「单一事实来源」重构的收尾，修正 `.env` 模板中 install.py 路径说明为 `common/install.py`，并在版本说明中标注同步修复了 `read_env_dict` bug。

### 主要变更
- docs(.env): 修正注释中 install.py 路径说明为 common/install.py
- chore: 版本 2.23.0 -> 2.24.0（重构版本：受保护路径 / 设备解析 / 家属端样板 / .env 写入统一 + read_env_dict bug 修复）

---

## v2.23.0 (2026-07-29) — 多端样板与基础设施「单一事实来源」收口 + install venv 自动引导

### 概述
相对 v2.22.3，本版本共 5 个提交、20 个文件变更，是近期最大的一次结构收口：将散落在三端的 `.env` 写入、受保护路径规则、device_id→用户解析、家属端路由样板统一到 `common/` 单一模块；install 脚本新增 venv 自动引导。

### 主要变更
- refactor(env): .env 模板生成与写入统一到 common.envfile；路由改用绝对导入
- refactor(family): 路由鉴权 / Jinja / 用户 JWT 客户端样板合并为 routes.web_helpers
- refactor(server): device_id→用户解析合并为 DeviceService.find_device_accounts 单一原语
- refactor(protection): 受保护路径规则三份合一为 common.runtime_protection 单一事实来源
- feat(install): 依赖安装脚本增加 venv 自动引导（自动建/复用仓库根 .venv 并 re-exec；Linux 缺 venv 走 apt 安装，Windows 降级提示）

### 涉及文件
- `common/envfile.py`、`common/install.py`、`common/runtime_protection.py`、`server/app/services/device_service.py`、`family_monitor/routes/web_helpers.py`、`updater.py`、`reset_runtime.py`、三端 `main.py` / `README.md` / `requirements.txt`，以及 `tests/` 下 4 个新增测试（`test_envfile_helpers.py`、`test_family_web_helpers.py`、`test_runtime_protection.py`、`test_server_device_service.py`）等共 20 个文件

---

## v2.22.3 (2026-07-29) — 版本号对齐 v2.22.2（修复发布版本冲突）

### 概述
相对 v2.22.2，本版本仅 1 个提交、无代码文件变更，为版本号对齐发布（2.22.2 -> 2.22.3），说明本批 install.py 迁移已合入。

### 主要变更
- chore: 版本号 2.22.2 -> 2.22.3（对齐最新发布 v2.22.2，修复版本冲突；本批变更含 install.py 迁移至 common/）

---

## v2.22.2 (2026-07-29) — 将 install.py 迁移至 common/ 统一基础设施

### 概述
相对 v2.22.1，本版本共 1 个提交、11 个文件变更，把三端各自的 install.py 收敛到 `common/install.py` 单一实现：`ROOT_DIR` 指向仓库根并注入 `sys.path`，同步更新三端 `main.py` 与文档引用。

### 主要变更
- refactor(common): 将 install.py 迁移至 common/ 统一基础设施（阶段一收口首项；ROOT_DIR 指向仓库根并注入 sys.path；三端 main.py 与文档引用同步更新）

### 涉及文件
- `common/envfile.py`、`common/install.py`、`elderly_assistant/main.py`、`elderly_assistant/README.md`、`elderly_assistant/requirements.txt`、`family_monitor/main.py`、`family_monitor/README.md`、`server/main.py`、`server/README.md`、`reset_runtime.py`、`updater.py`

## v2.22.1 (2026-07-29) — 批量修复 P0 缺陷 + 公共基座提取（阶段 A0/A1）

### 概述
相对 v2.22.0，本版本共 3 个提交、13 个文件变更，批量修复 P0 缺陷并提取公共基座（`common/envfile`、`common/runtime_protection`、`common/security`、`common/validators`），新增默认老人端 `.env`。

### 主要变更
- 批量修复 P0 缺陷 + 公共基座提取（阶段 A0+A1）
- chore: 增加默认老人端 .env 文件
- build(release): 版本号升至 2.22.1

### 涉及文件
- `common/envfile.py`、`common/runtime_protection.py`、`common/security.py`、`common/validators.py`、`elderly_assistant/.env`、`server/app/services/auth_service.py`、`server/app/services/device_service.py`、`server/app/tasks/stock_checker.py`、`server/app/utils/datetime_utils.py`、`server/app/utils/rate_limit.py`、`family_monitor/routes/home.py`、`install.py`、`updater.py`

---

## v2.22.0 (2026-07-28) — 大规模重构收口（.env 统一读写 / HTTP 客户端 / 模板消重 / 老人端分层）

### 概述
相对 v2.21.0，本版本共 9 个提交、64 个文件变更，是近期最大的一次结构重构：新建 `common/envfile` 统一 .env 读写、`common/server_client` 统一 HTTP 客户端；服务端抽 `device_service` 并将 config 导入副作用外移至 `bootstrap`；家属端抽 `medication_service`、以 `base.html` 消除 9 个模板重复；老人端将 `main` 分层为 `workflow`/`hardware`；并修复三处破窗缺陷。

### 主要变更
- refactor(server): 抽 device_service + 统一 mask_device_id 脱敏
- refactor(server): 将 config 导入期副作用外移至 bootstrap.bootstrap_config()
- refactor(family): 抽取 base.html 消除 9 模板 head/nav 重复，活动导航改为 request.url.path 自动计算
- refactor(family): 统一 HTTP 客户端到 common.server_client.BaseServerClient
- refactor(family): 抽 medication_service 校验、删 auth/session 死代码
- refactor(elderly): 分层 main -> workflow/hardware，集中 Board 初始化，删死代码
- refactor: 新建 common/envfile 统一 .env 读写，install/updater/elderly/family 接入；server/main 注入仓库根
- fix: 修复三处破窗缺陷（install PIP_INDEX_URL / elderly Path 导入 / 库存不足保留记录）
- chore: 版本号升级 2.21.0 -> 2.22.0

### 涉及文件
- `common/envfile.py`、`common/server_client.py`、`server/app/core/bootstrap.py`、`server/app/core/config.py`、`server/app/core/security.py`、`server/app/services/device_service.py`、`server/app/services/medication_service.py`、`family_monitor/core/*`、`family_monitor/routes/*`、`family_monitor/templates/*`（9 个）、`elderly_assistant/workflow/*`、`elderly_assistant/hardware/*`、`install.py`、`updater.py` 及 `tests/` 下 9 个用例等共 64 个文件

---

## v2.21.0 (2026-07-28) — 老人端接入 AI 问答与服药拍照；systemd 一键部署；CodeQL 安全修复

### 概述
相对 v2.20.1，本版本共 13 个提交、41 个文件变更，重大功能版本：老人端接入 AI 问答（长按按钮 A 问药品注意事项并 TTS 播报）与 HuskyLens 拍照 base64 上传服药照片；新增 systemd 一键部署（`deploy/setup.sh` + 免密 sudoers）；修复 6 条 CodeQL 真问题告警；AI 助手支持多厂商并按用户独立配置（数据库存储）。

### 主要变更
- feat(elderly): 接入 AI 问答——长按按钮 A(>1.5s) 问药品注意事项并 TTS 播报
- feat(elderly): 接入 HuskyLens 拍照并以 base64 上传服药照片到服务端
- fix: 修复 M10 确认落库 / 家属通知、漏服实时通知，接入 TTS 语音播报
- feat(deploy): updater 更新后自动重启 systemd 服务（配 deploy 免密 sudoers）
- fix(deploy): setup.sh 改用独立 venv，避免 PEP 668 污染系统 Python
- chore: 新增 deploy/setup.sh 一键部署脚本（server+family 经 systemd）
- security: 修复 6 条 CodeQL 真问题告警（DOM XSS / 临时文件 / 异常泄露 / 权限 / 日志脱敏）
- feat: AI 助手支持多厂商并按用户独立配置（数据库存储）
- 其它：.gitignore 放行 elderly_assistant 源码、README 版本对齐、删除未启用的 ai-code-reviewer 目录、CI 推送 tag 改用 PAT 鉴权

### 涉及文件
- `deploy/setup.sh`、`deploy/*.service`、`server/app/services/ai_service.py`、`server/app/services/ai_config_service.py`、`server/app/services/auth_service.py`、`server/app/api/v1/endpoints/{ai,ai_config,oauth,updater}.py`、`server/app/models/user_ai_config.py`、`elderly_assistant/main.py`、`family_monitor/routes/ai_config.py`、`updater.py` 等共 41 个文件

---

## v2.20.1 (2026-07-28) — 合并 CI 工作流并补充自动更新端点

### 概述
相对 v2.20.0，本版本共 2 个提交、2 个文件变更，合并 CI 工作流并补充自动更新端点，版本号提升至 2.20.1。

### 主要变更
- chore: 合并 CI 工作流并补充自动更新端点
- chore: 版本号提升至 2.20.1

### 涉及文件
- `.github/workflows/python-app.yml`、`.github/workflows/update.yml`

---

## v2.20.0 (2026-07-28) — 统一三端配置为单一 .env，install.py 收敛至根目录

### 概述
相对 v2.19.14，本版本共 1 个提交、28 个文件变更，把三端各自的配置/install 收敛为单一 `.env` 与根目录 `install.py`，并同步更新对应 README、CI 与测试。

### 主要变更
- refactor(config): 统一三端配置为单一 .env，install.py 收敛至根目录 (v2.20.0)

### 涉及文件
- `.env`、`.gitignore`、`README.md`、`config.json`、三端 `main.py` / `install.py` / `config.*` / `README.md`、`reset_runtime.py`、`server/app/core/config.py`、`updater.py` 及 `tests/` 下 3 个用例等共 28 个文件

---

## v2.19.14 (2026-07-28) — 删除默认镜像源；updater 改为仅替换文件

### 概述
相对 v2.19.12，本版本共 2 个提交、2 个文件变更，删除默认镜像源，并移除 updater 自动重启逻辑（更新后仅替换文件，交由人工手动重启）。

### 主要变更
- chore: 删除默认镜像源
- refactor(updater): 移除自动重启逻辑，更新后仅替换文件交由人工手动重启 (v2.19.14)

### 涉及文件
- `install.py`、`updater.py`

> 注：版本号由 v2.19.12 直接跳至 v2.19.14，v2.19.13 未发布。

---

## v2.19.12 (2026-07-26) — 对齐 email_code 真实实现，修复 CI 失败用例

### 概述
相对 v2.19.11，本版本共 1 个提交、1 个文件变更，对齐 `email_code` 真实实现，修复 python-app CI 失败用例。

### 主要变更
- test: 对齐 email_code 真实实现，修复 python-app CI 失败用例 (v2.19.12)

### 涉及文件
- `tests/test_email_code.py`

---

## v2.19.11 (2026-07-26) — 修正 update.yml 否定条件，ci 提交不再被 skip

### 概述
相对 v2.19.10，本版本共 1 个提交、2 个文件变更，修正 `update.yml` 否定条件（去掉多余 ci），使 `ci:` 提交触发的 update 不再被 skip。

### 主要变更
- ci: 修正 update.yml 否定条件（去掉多余 ci），使 ci: 提交触发 update 不再被 skip (v2.19.11)

### 涉及文件
- `.github/workflows/update.yml`、`history.md`

---

## v2.19.10 (2026-07-26) — 新增 update 步骤与独立 update.yml

### 概述
相对 v2.19.9，本版本共 1 个提交、3 个文件变更，新增 update 步骤与独立 `update.yml`，update 目标为 `{public_url}/server/api/v1/updater`。

### 主要变更
- ci: 新增 update 步骤与独立 update.yml，update 目标为 {public_url}/server/api/v1/updater (v2.19.10)

### 涉及文件
- `.github/workflows/python-app.yml`、`.github/workflows/update.yml`、`history.md`

---

## v2.19.9 (2026-07-26) — 新增根目录 config.json（含 public_url）

### 概述
相对 v2.19.8，本版本共 1 个提交、4 个文件变更，新增根目录 `config.json`（含 `public_url`）并纳入版本管理。

### 主要变更
- feat(config): 新增根目录 config.json（含 public_url）并纳入版本管理 (v2.19.9)

### 涉及文件
- `.gitignore`、`config.json`、`history.md`、`updater.py`

## v2.19.8 (2026-07-25) — 修复注册页 OAuth 补全流程 Turnstile 容器缺失报错

### 概述
相对 v2.19.7，本版本仅 1 个提交，修复注册页 OAuth 补全流程下 Turnstile 容器缺失导致 `container` 类型无效的报错（前端）。

### 主要变更
- fix(frontend): 注册页 OAuth 补全流程下 Turnstile 容器缺失导致 container 类型无效报错 (v2.19.8)

---

## v2.19.7 (2026-07-25) — 修复 v2.19.6 启动崩溃（public.py 重复参数）

### 概述
相对 v2.19.6，本版本仅 1 个提交，删除 `public.py` 重复的 `username` 关键字参数，修复 v2.19.6 启动崩溃。

### 主要变更
- fix(server): 删除 public.py 重复的 username 关键字参数，修复 v2.19.6 启动崩溃 (v2.19.7)

---

## v2.19.6 (2026-07-25) — 清理 updater 中 check_for_update 的重复请求

### 概述
相对 v2.19.5，本版本仅 1 个提交，删除 `check_for_update` 中重复的 API 请求与日志输出（updater 代码清理）。

### 主要变更
- refactor(updater): 删除 check_for_update 重复的 API 请求与日志输出 (v2.19.6)

---

## v2.19.5 (2026-07-25) — 修复镜像代理误判导致无法检查更新

### 概述
相对 v2.19.4，本版本仅 1 个提交，修复镜像代理被误判为正向代理导致无法检查更新的问题。

### 主要变更
- fix(updater): 修复镜像代理被误判为正向代理导致无法检查更新 (v2.19.5)

---

## v2.19.4 (2026-07-25) — 修复生产环境 SECRET_KEY 无法启动

### 概述
相对 v2.19.3，本版本仅 1 个提交，修复 `env_file` 相对 CWD 解析导致 `SECRET_KEY` 在生产环境无法启动的问题。

### 主要变更
- fix(server): 修复 env_file 相对 CWD 解析导致 SECRET_KEY 生产环境无法启动 (v2.19.4)

---

## v2.19.3 (2026-07-25) — 修复邮箱验证码接口未登录被重定向

### 概述
相对 v2.19.2，本版本仅 1 个提交，修复邮箱验证码接口在未登录时被重定向到登录页的问题（家属端）。

### 主要变更
- fix(family): 修复邮箱验证码接口未登录被重定向到登录页 (v2.19.3)

---

## v2.19.2 (2026-07-25) — 修复 email_code 模块缺失导致启动崩溃

### 概述
相对 v2.19.1，本版本仅 1 个提交，修复 `email_code` 模块缺失导致的服务端启动崩溃。

### 主要变更
- fix(server): 修复 email_code 模块缺失导致的启动崩溃 (v2.19.2)

---

## v2.19.1 (2026-07-25) — updater 未检测到 config.json 时自动生成模板

### 概述
相对 v2.19.0，本版本仅 1 个提交，updater 在未检测到 `config.json` 时自动生成模板，降低首次部署门槛。

### 主要变更
- feat(updater): 未检测到 config.json 时自动生成模板 (v2.19.1)

---

## v2.19.0 (2026-07-25) — 新增更新信息端点 /api/v1/updater 与前端轮询重启

### 概述
相对 v2.18.1，本版本共 2 个提交，新增更新信息端点 `/api/v1/updater`，前端轮询更新并在下载后自动重启（对应 PR #7）。

### 主要变更
- feat: 关于 updater.py 的修改
- feat(updater): 新增更新信息端点 /api/v1/updater、前端轮询与下载后重启（#7）

---

## v2.18.1 (2026-07-25) — 修复 MAIL_PORT 空串导致启动崩溃

### 概述
相对 v2.18.0，本版本仅 1 个提交，修复 `MAIL_PORT` 空串导致服务启动崩溃（配置容错）。

### 主要变更
- fix(config): 修复 MAIL_PORT 空串导致服务启动崩溃 (v2.18.1)

## v2.18.0 (2026-07-25) — updater auto_pull 默认改由 config.json 控制

### 概述
相对 v2.17.0，本版本主要将 updater 的 `auto_pull` 默认值改为由 `config.json` 控制（缺省 `true`），并暂时移除 CI 中的 AI review 步骤。

### 主要变更
- feat(updater): auto_pull 默认值改为由 config.json 控制（缺省 true）
- ci: 暂时删除 AI review

---

## v2.17.0 (2026-07-24) — 登录改为手机号+密码，昵称统一 username

### 概述
相对 v2.16.0，本版本核心改动为登录方式由邮箱改为「手机号+密码」，昵称统一使用 `username`（对应 #3）。该版本在 CI 调整期间被多次回退/重打，最终定稿于本次提交。

### 主要变更
- feat(auth): 登录改为手机号+密码，昵称统一使用 username (#3)
- ci: 调整 AI review 实现（robin 接入与实现方式变更，多次迭代）

---

## v2.16.0 (2026-07-24) — 新增 --reset 重置运行时；history.md 重排归集附录

### 概述
相对 v2.15.0，本版本新增 `main.py --reset` 重置运行时数据，将 `reset_runtime.py` 纳入版本控制；并把 `history.md` 按时间倒序重排、通用文档归集为附录。该版本在 CI/merge 震荡中被多次回退重打，最终定稿于本次提交。

### 主要变更
- feat: main.py 新增 --reset 重置运行时数据 (v2.16.0)
- fix: 将 reset_runtime.py 纳入版本控制（修复 .gitignore /* 遗漏）
- docs: 将 history.md 按时间倒序重排并归集通用文档为附录
- fix: 补提交 .gitignore 中 tests/__pycache__ 忽略规则
- ci: 仅在功能变更时触发

---

## v2.15.0 (2026-07-24) — install 自动下载未发布包 dfrobot_huskylensv2

### 概述
相对 v2.14.1，本版本让 install 脚本自动下载安装未发布的 `dfrobot_huskylensv2` 包，便于 HuskyLens 依赖落地。

### 主要变更
- chore(install): 自动下载安装未发布包 dfrobot_huskylensv2 (v2.15.0)

---

## v2.14.1 (2026-07-24) — 补充邮箱验证码登录测试

### 概述
相对 v2.14.0，本版本补充邮箱验证码登录的单元测试与接口测试，并新增相关测试文件。

### 主要变更
- build: 增加新的邮箱登录 tests 等文件
- test: 补充邮箱验证码登录单元测试与接口测试

---

## v2.14.0 (2026-07-24) — 新增邮箱验证码登录（SMTP / Resend 双后端）

### 概述
相对 v2.13.x，本版本新增邮箱验证码登录：支持 SMTP / Resend 双后端，邮箱未注册时自动建号。

### 主要变更
- feat: 新增邮箱验证码登录（SMTP / Resend 双后端，邮箱未注册自动建号）

## v2.13.1 (2026-07-24) — CI 完善 + GitHub OAuth 邮箱获取与冲突合并

### 概述
相对 v2.13.0，本版本为综合完善：接入 AI 代码审查机器人、补全 CI 依赖安装与缓存、修正 `family_monitor` 依赖文件名并解决 `dfrobot_huskylensv2` 包缺失；OAuth 侧支持 GitHub 获取邮箱（含私有）及邮箱冲突合并绑定；并修正 `test_vision_service` 断言与 `.gitignore`。

### 主要变更
- ci: 集成 AI 代码审查机器人；完善 python-app CI（老人端依赖安装、setup-python、pip 缓存）
- fix(oauth): GitHub OAuth 获取邮箱（含私有）+ 邮箱冲突合并绑定
- build: 修正 family_monitor 依赖文件名、解决 dfrobot_huskylensv2 包不存在、放宽老人端版本号限制
- fix: 修正 test_vision_service 对 _extract_drug_name 的断言以匹配真实实现
- chore: 增加 tests 目录、更新 .gitignore 与 README

---

## v2.13.0 (2026-07-23) — 自动更新器统一迁移至仓库根目录 updater.py

### 概述
相对 v2.12.4，本版本将自动更新器统一迁移至仓库根目录 `updater.py`，为后续统一更新流程打基础。

### 主要变更
- refactor: 将自动更新器统一迁移至仓库根目录 updater.py

---

## v2.12.4 (2026-07-23) — 修复子女端 OAuth 登录按钮不显示

### 概述
相对 v2.12.3，本版本仅 1 个提交，修复子女端 OAuth 登录按钮不显示的问题。

### 主要变更
- fix: 修复子女端 OAuth 登录按钮不显示

---

## v2.12.3 (2026-07-23) — 版本号对齐（修复 oauth.py get_db 导入）

### 概述
相对 v2.12.2，本版本为 PATCH 对齐：修复 `oauth.py` 中 `get_db` 错误导入并升级版本号至 2.12.3（无新增功能）。

### 主要变更
- chore(release): 升级版本号至 2.12.3 (PATCH) - 修复 oauth.py 中 get_db 错误导入

---

## v2.12.2 (2026-07-23) — 修正 oauth.py get_db 导入，修复启动导入错误

### 概述
相对 v2.12.1，本版本修正 `oauth.py` 中 `get_db` 的错误导入来源，并升级版本号至 2.12.2（PATCH，修复服务端启动导入错误）。

### 主要变更
- fix(server): 修正 oauth.py 中 get_db 的错误导入来源
- chore(release): 升级版本号至 2.12.2 (PATCH) - 修复服务端启动导入错误

---

## v2.12.1 (2026-07-23) — 用 fastapi-oauth20 重构 GitHub/Gitee OAuth 登录

### 概述
相对 v2.12.0，本版本用 `fastapi-oauth20` 重构 GitHub/Gitee OAuth 登录流程，并修复 `vision.py` 中 `JSONResponse` 从 fastapi 顶层错误导入导致启动失败的问题。

### 主要变更
- refactor: 使用 fastapi-oauth20 重构 GitHub/Gitee OAuth 登录流程 (v2.12.1)
- fix(server): 修复 vision.py 中 JSONResponse 从 fastapi 顶层错误导入导致启动失败

---

## v2.12.0 (2026-07-23) — 配置健壮性：可选服务缺失自动降级

### 概述
相对 v2.11.0，本版本增强配置健壮性：可选服务缺失时自动降级，基础必填项缺失则启动即报错退出。

### 主要变更
- 配置健壮性：可选服务缺失自动降级，基础必填缺失启动即报错退出 (v2.12.0)

---

## v2.11.0 (2026-07-23) — 新增 Gitee OAuth 登录，重构为通用 provider 框架

### 概述
相对 v2.10.4，本版本新增 Gitee OAuth 登录，并将 OAuth 重构为通用 provider 框架，便于扩展更多平台。

### 主要变更
- feat(oauth): 新增 Gitee OAuth 登录，重构为通用 provider 框架 (v2.11.0)

---

## v2.10.4 (2026-07-23) — 清理写死版本号，改由 VERSION 动态读取

### 概述
相对 v2.10.3，本版本清理代码中写死的版本号（_DEFAULT_VERSION / version=2.10.3 等），统一改为动态读取 `VERSION` 文件；并修复自动生成 `.env` 缺失必填字段、新增 GitHub OAuth `/enabled` 端点别名。

### 主要变更
- 重构：清理版本/变更类注释，版本号改为动态读取 VERSION；删除写死版本号改由 VERSION 文件动态读取
- fix: 修复自动生成 .env 缺失必填字段并新增 GitHub OAuth /enabled 端点别名 (v2.10.4)

---

## v2.10.3 (2026-07-23) — 删除无关文件，修正 README 配置说明

### 概述
相对 v2.10.2，本版本删除无关文件，并修正 README 配置说明以贴合代码实际。

### 主要变更
- chore: 删除无关文件
- docs: 修正 README 配置说明以贴合代码实际 (v2.10.3)

## v2.10.2 (2026-07-22) — 首次运行 .env 模板补全全部字段

### 概述
相对 v2.10.1，本版本仅 1 个提交，补全首次运行自动生成的 `.env` 模板中的全部可配置字段。

### 主要变更
- fix: 首次运行自动生成的 .env 模板补全全部可配置字段 (v2.10.2)

---

## v2.10.1 (2026-07-22) — 修复 Turnstile Secret Key 缺失导致登录/注册被拒

### 概述
相对 v2.10.0，本版本仅 1 个提交，修复 Turnstile 服务端密钥（Secret Key）缺失导致登录/注册被拒的问题。

### 主要变更
- fix: 修复 Turnstile 服务端密钥(Secret Key)缺失导致登录/注册被拒 (v2.10.1)

---

## v2.10.0 (2026-07-22) — 新增 GitHub OAuth 登录

### 概述
相对 v2.9.15，本版本新增 GitHub OAuth 登录，并调整 `.gitignore`。

### 主要变更
- feat(auth): 新增 GitHub OAuth 登录 (v2.10.0)
- chore: 更新 .gitignore

---

## v2.9.15 (2026-07-22) — 修复 8 个 Bug（localhost 复现验证）

### 概述
相对 v2.9.14，本版本修复 8 个 Bug（均在 localhost 复现验证），并调整 `.gitignore`、更新 README。

### 主要变更
- fix: v2.9.15 修复 8 个 Bug（全部 localhost 复现验证）
- docs: 更新 README.md
- chore: 更改 .gitignore

---

## v2.9.14 (2026-07-20) — 回退 v3.0.0，移除源码仓库中的 SHA256SUMS.txt

### 概述
相对 v3.0.0，本版本将版本号回退至 v2.9.14，并移除源码仓库中的 `SHA256SUMS.txt`（撤销 v3.0.0 的发布产物）。

### 主要变更
- fix: 版本号回退至 v2.9.14 + 移除源码仓库中的 SHA256SUMS.txt

---

## v3.0.0 (2026-07-20) — 安全加固版本（渗透测试 + 代码审查修复）

> 本版本为一次安全加固发布，随后在 v2.9.14 中被回退（版本号降回 2.x 并移除校验文件），保留记录以备查。

### 概述
相对 v2.9.13，本版本为安全加固版本：修复渗透测试与代码审查发现的问题，并添加 `v3.0.0` 的 SHA256 校验文件、更新 `SHA256SUMS.txt` 为最终发布校验值。

### 主要变更
- v3.0.0: 安全加固版本 — 渗透测试修复 + 代码审查修复
- chore: 添加 v3.0.0 SHA256 校验文件
- chore: 更新 SHA256SUMS.txt 为最终发布版本的校验值

---

## v2.9.13 (2026-07-19) — 删除 CSS 中 page-home 样式

### 概述
相对 v2.9.12，本版本升级版本号至 v2.9.13，并删除 CSS 中 `page-home` 样式。

### 主要变更
- chore: 版本号升级至 v2.9.13 + 删除 CSS 中 page-home 样式

---

## v2.9.12 (2026-07-19) — 统一主页字体和样式

### 概述
相对 v2.9.11，本版本升级版本号至 v2.9.12，并统一主页字体和样式。

### 主要变更
- chore: 版本号升级至 v2.9.12 + 统一主页字体和样式

---

## v2.9.11 (2026-07-19) — 修复注册错误显示

### 概述
相对 v2.9.10，本版本升级版本号至 v2.9.11，并修复注册错误显示。

### 主要变更
- chore: 版本号升级至 v2.9.11 + 修复注册错误显示

---

## v2.9.10 (2026-07-19) — 修复静态文件 PATH_PREFIX 路径匹配

### 概述
相对 v2.9.9，本版本升级版本号至 v2.9.10，并修复静态文件 `PATH_PREFIX` 路径匹配。

### 主要变更
- chore: 版本号升级至 v2.9.10 + 修复静态文件 PATH_PREFIX 路径匹配

## v2.9.9 (2026-07-19) — 版本号升至 2.9.9 + 修复重定向循环

### 概述
相对 v2.9.8，本版本仅 1 个提交，升级版本号至 v2.9.9 并修复重定向循环。

### 主要变更
- chore: 版本号升级至 v2.9.9 + 修复重定向循环

---

## v2.9.8 (2026-07-19) — 修复 PATH_PREFIX 下 auth 重定向循环；updater 动态读版本

### 概述
相对 v2.9.7，本版本修复 `PATH_PREFIX` 模式下 `auth_middleware` 重定向循环，将 `updater.py` 版本号改为从 `VERSION` 文件动态读取，并升级版本号至 v2.9.8。

### 主要变更
- fix: 修复 PATH_PREFIX 模式下 auth_middleware 重定向循环
- refactor: updater.py 版本号改为从 VERSION 文件动态读取
- chore: 版本号升级至 v2.9.8

---

## v2.9.7 (2026-07-19) — 集成 Cloudflare Turnstile + 子女端认证重构为 JWT

### 概述
相对 v2.9.6，本版本为核心安全与认证升级：集成 Cloudflare Turnstile 人机验证，并将子女端认证重构为 JWT；修复登录后用户名显示「用户」问题（含 Turnstile 降级与路由二次校验），恢复模板兜底用户名；`.gitignore` 增加打包文件排除并清除误提交的 zip；同时修复 ASGI 内部服务器错误与静态文件 404（改用 `root_path`）。

### 主要变更
- feat: 集成 Cloudflare-free Cloudflare Turnstile 人机验证 + 重构子女端认证为 JWT
- fix: 修复登录后用户名显示「用户」问题 + Turnstile 降级 + 路由二次校验
- revert: 恢复模板兜底用户名为「用户」
- chore: .gitignore 添加打包文件排除规则 + 从历史清除误提交的 zip
- feat: 解决 ASGI 应用内部服务器错误
- fix: static file 404 bug - use root_path instead of modifying scope[path]

---

## v2.9.2 (2026-07-16) — docs 页面外部资源改为本地调用

### 概述
相对 v2.9.7（上一时间节点），本版本将 docs 页面的外部资源改为本地调用（版本号置为 2.9.2）。注：该版本号在时间线上出现在 2.9.7 之后，属版本号管理波动。

### 主要变更
- feat: 将 docs 页面的外部资源改为本地调用

---

## v2.9.6 (2026-07-15) — 更新全部文档并升级版本至 2.9.6

### 概述
相对 v2.9.4，本版本更新全部文档并升级版本号至 2.9.6。

### 主要变更
- docs: update all documentation and bump version to 2.9.6

---

## v2.9.4 (2026-07-15) — 升级版本至 2.9.4 并更新 history

### 概述
相对 v2.9（2.9.0/2.9.3），本版本升级版本号至 2.9.4 并同步更新 history。

### 主要变更
- chore: bump version to 2.9.4 and update history

---

## v2.9 (2026-07-15) — 版本由 2.7.3 跃升至 2.9，集中修复启动/路由缺陷

### 概述
相对 v2.7.3，本版本将版本号由 2.7.3 统一跃升至 2.9（期间含 2.9.1/2.9.2/2.9.3 子版本），并集中修复多项缺陷：适配 Starlette 0.28+ 的 `TemplateResponse` 签名、reminders 保存无效、登录后 302 重定向回 `/login`、多模块 sha256 校验误匹配、无 `.env` 启动失败等。

### 主要变更
- chore: Update version from 2.7.3 to 2.9（统一版本号）
- fix: 适配 TemplateResponse 至 Starlette 0.28+ 签名（request 首参）
- fix: 修复 reminders 保存无效 + 版本号升级至 2.9.3
- fix: 修复登录后被 302 重定向回 /login 的问题
- fix: 修复多模块 sha256 校验文件误匹配问题
- fix: 修复无 .env 启动失败 + 版本号升级至 2.9.1

---

## v2.7.3 (2026-07-10) — 家属端 reminders 可编辑表格 + 导航/静态资源修复

### 概述
相对 v2.7.2，本版本统一版本号至 2.7.3，进行大量界面与部署修复：reminders 页改为 Cloudflare DNS 风格可编辑表格（增删改）；统一所有页面导航栏为首页样式；添加 `favicon.ico` 与 DevTools 探测文件路由消除 404；移除 `family_monitor` CSRF 防护；首次运行自动生成 `config.json` 且 `PATH_PREFIX` 默认空解决静态文件 404；解决 git clone 后本地部署 UI 样式丢失；删除 `install.py` 自动换源并优化 pip 安装脚本；更新 README、清理无关文件。

### 主要变更
- feat: reminders 页改为 Cloudflare DNS 风格表格，支持增删改
- ui: 统一所有页面导航栏为首页样式
- fix: 添加 favicon.ico 和 Chrome DevTools 探测文件路由，消除浏览器 404
- refactor: 移除 family_monitor CSRF 防护
- fix: 首次运行自动生成 config.json，PATH_PREFIX 默认空解决静态文件 404
- fix: 解决 git clone 后本地部署 UI 样式丢失问题
- feat: 删除 install.py 自动 python 换源的功能；优化 pip 安装脚本
- docs: 更新 README.md；删除无关文件

---

## v2.7.2 (2026-07-08) — 合并 PR #1，版本号更新到 2.7.2

### 概述
相对 v2.7.1，本版本合并 PR #1 并将版本号更新到 2.7.2。

### 主要变更
- Merge pull request #1 from diaoyunxi/trae/agent-plVUY7
- chore: 更新版本号到 2.7.2

## v2.7.0 (2026-07-08) — 吃药逻辑设定 + 修复「设备即用户」设计缺陷

### 概述
相对 v2.6.0，本版本新增吃药逻辑设定，并修复「设备即用户」设计缺陷导致的 3 个失败项，以及 `public.py` 第 332 行时区问题（标注 v2.7.1）。

### 主要变更
- feat: 吃药逻辑设定
- fix(device): 修复「设备即用户」设计缺陷导致 3 个失败项 (v2.7.0)
- fix(datetime): 修复 public.py 第 332 行时区问题 (v2.7.1)

---

## v2.6.0 (2026-07-08) — 版本号升至 2.6.0 并同步 README 与 history

### 概述
相对 v2.5.0，本版本升级版本号至 2.6.0，并同步 README 与 history。

### 主要变更
- docs: bump 版本到 2.6.0 并同步 README 与 history

---

## v2.5.0 (2026-07-08) — 新增删除用户 API + 修复设备离线误显示在线

### 概述
相对 v2.4.0，本版本新增删除用户 API（支持注销自己与家属删除同组老人），并修复设备离线时子女端有概率显示在线的问题。

### 主要变更
- feat(user): 新增删除用户 API 支持注销自己与家属删除同组老人
- fix(device-status): 修复设备离线时子女端有概率显示在线的问题

---

## v2.4.0 (2026-07-07) — 家属端移动端导航栏优化

### 概述
相对 v2.3.0，本版本优化家属端移动端导航栏占比过大问题，改为横向滚动 + 头像下拉菜单。

### 主要变更
- feat(family_monitor): 优化移动端导航栏占比过大问题，改为横向滚动 + 头像下拉菜单

---

## v2.3.0 (2026-07-07) — 启用启动自动更新 + 全面代码审查

### 概述
相对 v2.2.3，本版本为 CSS 引用添加版本号参数绕过 CDN 缓存，启用启动时自动拉取更新，并进行 v2.3.0 全面代码审查与修复。

### 主要变更
- fix: 给 CSS 引用添加版本号参数绕过 CDN 缓存
- feat: 启用启动时自动拉取更新
- refactor: v2.3.0 全面代码审查与修复

---

## v2.2.3 (2026-07-07) — 移除 device_token 机制，接口仅校验 device_id

### 概述
相对 v2.2.2，本版本移除 `device_token` 机制（所有接口仅校验 `device_id`），新增家属端获取设备 token API，并修复设备注册接口 `timezone` 未导入导致 500 错误、优化设置页与状态栏显示。

### 主要变更
- refactor: 移除 device_token 机制，所有接口仅校验 device_id
- feat: 新增家属端获取设备 token API
- fix: 修复设备注册接口 timezone 未导入导致 500 错误
- feat: 优化设置页和状态栏显示
- feat: API 调用返回服务器内部错误

---

## v2.2.2 (2026-07-07) — 解决设备未绑定但显示在线问题

### 概述
相对 v2.2.1，本版本继续解决设备未绑定但显示在线的问题，并升级版本号至 2.2.2。

### 主要变更
- feat: 解决设备未绑定但显示在线问题
- chore: bump version to 2.2.2

---

## v2.2.1 (2026-07-07) — 重构子女端 UI 为 Claude 设计系统风格

### 概述
相对 v2.2.0，本版本完全重构子女端 UI 为 Claude 设计系统风格，并继续解决设备未绑定但显示在线问题。

### 主要变更
- refactor(ui): 完全重构子女端 UI 为 Claude 设计系统风格
- feat: 解决设备未绑定但显示在线问题

---

## v2.2.0 (2026-07-06) — 安全加固版本（修复 6 P0 + 4 高危 + 38 缺陷）

### 概述
相对 v2.1.0，本版本为重大安全加固：修复 6 个 P0 漏洞 + 4 个高危漏洞，修复全部 38 个缺陷（5 致命 + 9 严重 + 14 一般 + 10 优化）；新增服务端 P0 安全测试（15 例）与子女端安全测试（20 例）；补充 `ALLOWED_ORIGINS` 修复启动 `extra_forbidden` 错误；删除子女端首页虚拟数据并清理无关文件；完善 README（架构图 / API 文档 / 部署运维 / 贡献指南）。

### 主要变更
- security: 修复 6 个 P0 漏洞 + 4 个高危漏洞
- fix: 修复全部 38 个缺陷（5 致命 + 9 严重 + 14 一般 + 10 优化）
- test: 新增服务端 P0 安全测试（15 例）+ 子女端安全测试（20 例）
- fix: Settings 补充 ALLOWED_ORIGINS 字段，修复启动报 extra_forbidden 错误
- feat: v2.2.0 安全加固版本
- chore: 删除所有测试文件、删除子女端首页虚拟数据、清理无关文件
- docs: 完善 README（架构图 / API 文档 / 部署运维 / 贡献指南）

---

## v2.1.0 (2026-07-01) — 移除本地 SSL，改用 Cloudflare 隧道自动 HTTPS

### 概述
相对 v2.0.0，本版本移除本地 SSL 证书，改用 Cloudflare 隧道自动配置 HTTPS。

### 主要变更
- feat: v2.1.0 移除本地 SSL 证书，改用 Cloudflare 隧道自动配置 HTTPS

---

## v2.0.0 (2026-06-30) — 升级至三端智能用药管理系统

### 概述
相对 v1.0.0，本版本升级为 v2.0.0 三端（老人端 / 服务端 / 家属端）智能用药管理系统。

### 主要变更
- feat: 升级至 v2.0.0 三端智能用药管理系统

---

## v1.0.0 (2026-06-30) — 初始发布，内置 GitHub 自动更新检查器

### 概述
项目首个正式版本，建立基础代码基线，并内置 GitHub 自动更新检查器。

### 主要变更
- feat: initial release with GitHub auto-update checker (v1.0.0)
- docs: Update README.md

# 附录：项目通用说明（概述 / 模块说明 / 技术栈 / 文件结构 / 运行方式）

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
