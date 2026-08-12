# 项目开发历史记录

> 本文件依据 git 实际提交历史整理：每个版本取「本版本号最后一次提交」与「上一版本号最后一次提交」的 git diff 作为该版本相对上一版本的全部改动。
> 条目按版本号倒序（最新在前）。

## v2.38.7 (2026-08-12) — 修复 LoggingMiddleware 消费请求体流导致生产环境所有 POST 返回 400（载入史册级 Bug）

### 概述

生产环境出现**离奇现象**：所有 `GET` 请求（health / schedule / users/me）毫秒级正常，但所有 `POST` 请求（设备注册 `device/register`、TOTP 开启 `totp/enable` 等）全部**耗时 10~15 秒后返回 400**，前端收到「无法解析 JSON」。该问题在数小时前还正常，属于**近期回归**。

经多轮排查与本地复现，最终定位根因为 `LoggingMiddleware` 在 `DEBUG=true` 下读取请求体时**消费了 Starlette 的请求体流**，在多层 `BaseHTTPMiddleware` 叠加场景中破坏了下游 Pydantic 对请求体的解析。本版本（2.38.7）修复该问题，并顺带将公开设备注册路由纳入敏感路径（不记录请求体）。

### 现场铁证（服务器日志）

```
# GET 正常（无 body）
GET /server/health status=200 duration=0.000s
GET /server/api/v1/public/device/schedule/218356669348204 status=200 duration=0.002s

# POST 全慢且 400（有 body）
POST /server/api/v1/public/device/register status=400 duration=10.003s
POST /server/api/v1/auth/totp/enable    status=400 duration=14.829s
```

规律极度清晰：**有 body 的 POST 全部 400 且 10s+，无 body 的 GET 全部正常**。且日志里明确打出了 `📦 请求体:` 行，反证生产环境 `DEBUG=true`。

### 根因分析（三层叠加，缺一不可）

1. **触发器：生产环境 `DEBUG=true`**
   部署环境 `.env` 由自动生成模板创建，模板默认 `DEBUG=true`，运维未改为 `false`。`LoggingMiddleware` 仅在 `settings.DEBUG` 时打印请求体，于是生产环境也进入该分支。

2. **直接原因：`await request.body()` 消费了请求体流**
   `LoggingMiddleware.dispatch()` 在 DEBUG 下对每个 `POST/PUT/PATCH` 直接 `body_bytes = await request.body()` 读取并打印。Starlette 的请求体流是**一次性消费**的——一旦被中间件读取，下游路由再用 `req: DeviceRegister`（Pydantic 模型）解析时，拿到的就是**空 body**。

3. **放大器：fb35676 引入的 `path_prefix_middleware` 破坏了 body 重放**
   `main.py` 在 `fb35676` 提交新增了 `path_prefix_middleware`（剥离 `/eating-medication` 前缀的函数式中间件 `app.middleware("http")`），它**包在多层层叠的 `BaseHTTPMiddleware`（含 LoggingMiddleware、SecurityHeadersMiddleware、RateLimitMiddleware）最外层**。
   在 `fastapi==0.115.0` + `starlette` 的旧版 `BaseHTTPMiddleware` 实现下，外层函数式中间件与内层 `BaseHTTPMiddleware` 之间的 body 流传递依赖于「中间件读取后必须原样重放」这一隐性约定。LoggingMiddleware 读取后**没有重放**，下游 `BaseHTTPMiddleware` 再读时流已空，请求体被破坏。

**结果**：下游 `register_device` 路由拿到空 body → FastAPI 解析失败 → `422`（经异常处理器转 400）；同时 body 流被提前耗尽，下游在等待 body 时卡等 → 表现为 **10~15s 超时**（耗时接近整数秒，符合「流耗尽后的等待/超时」特征）。

**最硬佐证**：`register_device` 路由代码**本身绝不返回 400**（只 `return {"status":"ok",...}`），`register_or_heartbeat` 也不抛 400；且 `get_db`、`verify_totp_code`、`get_current_user`、`RateLimitMiddleware`、`SecurityHeadersMiddleware`、`RequestSizeLimitMiddleware` 全部确认不返回 400、也不阻塞。因此这个 400 只能来自「请求体被破坏」这一**共享中间件层**，而非任何业务代码。这也排除了"后台任务卡死事件循环""Turnstile 出网超时"等早期猜测（GET 毫秒级即证明事件循环健康）。

> 关于"前端无法解析 JSON"：后端被破坏后响应延迟/异常，经 Cloudflare 隧道在 14s 超时后可能回 HTML 错误页，前端拿到非 JSON 故报错。后端恢复正常 JSON 后该现象消失。

### 主要变更

**服务端（server）**
- `fix(middleware/logging.py)`: 将 DEBUG 请求体日志改为「读取一次后通过重放 `receive` 重建 `Request` 再下发」——

  ```python
  captured = body_bytes

  async def _replay_receive():
      return {"type": "http.request", "body": captured, "more_body": False}

  request = Request(request.scope, receive=_replay_receive)
  ```

  这是 Starlette 推荐的「读 body 后安全重放」标准模式：既保留 DEBUG 请求体日志，又**不再消费下游所需 body 流**。
- `chore(middleware/logging.py)`: `SENSITIVE_PATHS` 新增 `/public/device/register`。规范化逻辑会从路径剥离 `API_V1_PREFIX`（`/api/v1`），故 `/api/v1/public/device/register` 被规范化为 `/public/device/register`；原集合仅有 `/device/register` 匹配不到，导致 DEBUG 模式仍会记录设备注册请求体，补充后该公开路由不再落盘设备 ID 等敏感信息。

**版本**
- `VERSION` 2.38.6 → 2.38.7（修复导致生产 POST 全 400 的回归 bug，PATCH+1）

### 验证（实测闭环）

- 本地用 `TestClient` + `DEBUG=true` + **完整中间件栈（含 path_prefix_middleware）**复现生产条件：
  - `POST /api/v1/public/device/register` → **200**（修复前为 400），`duration=0.051s`；
  - `POST /api/v1/auth/totp/enable` → **401**（body 正确解析后进入鉴权，因 token 无效被拒；修复前为 400/422），`duration=0.005s`。
  - 证明 10s+ 延迟正是 body 流被破坏后下游卡等所致，修复后消失。
- 回归测试：`test_server_device_service` / `test_server_client` / `test_server_totp` 共 **32 项全部通过**。
- 生产验证：服务器 `git pull` + **重启 uvicorn 进程**后，`device/register`、`totp/enable` 等 POST 恢复正常 200/快速 400，日志 `duration` 回到毫秒级。

### 经验教训（载入史册）

1. **`BaseHTTPMiddleware` 内读取 `request.body()` 是高危操作**：在多层中间件叠加（尤其是外层还有函数式 `app.middleware("http")`）的场景下，必须「读后重放」或改为 `request.stream()`/`receive` 端到端消费，否则会破坏下游 body 解析。凡是想在中间件里看请求体的需求，统一走「读一次 → 重建 `Request(receive=_replay_receive)`」模式。
2. **生产环境务必 `DEBUG=false`**：`DEBUG=true` 会触发请求体打印、Traceback 外泄等，本就不应出现在生产。本次根因虽在代码，但 `DEBUG` 未关是触发器。代码模板已警告，本修复使 `DEBUG=true` 下也不再破坏 POST，但关 DEBUG 仍是生产最佳实践。
3. **回归排查要相信「代码真相」而非「直觉」**：早期基于"后台任务/出网超时"的假设都被 `GET 毫秒级`这一铁证推翻。诊断时优先用「哪些请求正常 / 哪些异常」做分治（GET vs POST → 是否有 body），能极快收敛到 body 处理链路。
4. **新增函数式中间件（fb35676 的 path_prefix_middleware）会改变 body 流传递契约**：此后任何在 `BaseHTTPMiddleware` 中读取 body 的逻辑都需重新审视是否破坏了重放。

### 涉及文件

- `server/app/middleware/logging.py` — DEBUG 请求体日志改为读后重放；`SENSITIVE_PATHS` 新增 `/public/device/register`
- `VERSION` — 2.38.6 → 2.38.7
- `history.md`

---

## v2.38.0 (2026-08-11) — 子女端改用家属登录态鉴权，新增 `/family/device/*` 授权接口

### 概述

修复「子女端网页设备状态显示离线」的问题。根因是**子女端复用了老人端的设备 token 鉴权路径**：老人端首次注册时服务端才下发 `device_token`，已注册设备再次调用 `register` 仅作心跳、不再返回 token（防枚举设计）。因此子女端在老人端之后绑定同一设备时，拿到的是空 token，调用 `/device/status/{device_id}` 一律 403，页面据此判定设备离线。

本版新增一组**基于家属登录态（JWT）的授权接口** `/family/device/*`，子女端在已登录且已绑定该设备的前提下改走该组接口读取数据，不再依赖老人端的设备 token；同时绑定流程改用 `/family/device/bind` 合法获取 token，从根上消除空 token 场景。

### 主要变更

**服务端（server）**
- feat(api): 新增 `app/api/v1/endpoints/family_device.py`，前缀 `/family/device`，全部端点以 `Depends(get_current_user)` 鉴权，并校验 `current_user.device_id == device_id`，不匹配返回 403
- feat(api): 端点覆盖 `POST /bind`、`GET /status/{id}`、`/plans/{id}`、`/records/{id}`、`/chat_history/{id}`、`/reminders/{id}`，以及用药计划的 `POST` / `PUT` / `DELETE`
- feat(api): `POST /bind` 在设备已注册的前提下写入 `current_user.device_id` 并**合法下发 `device_token`**，替代此前拿不到 token 的绑定路径
- feat(device_service): 新增 `DeviceService.get_reminders(db, user, limit)`，基于用药计划与当日服药记录生成今日提醒
- chore(main): 挂载 `family_device` 路由

**子女端（family_monitor）**
- feat(api_client): `ElderlyAPIClient` 增加 family 模式（`set_jwt_token` / `set_family_auth` / `_family_mode`），家属模式下以 `Authorization: Bearer` 调用 `/family/device/*`
- feat(api_client): 新增 `bind_device_family` 及 status / plans / records / chat_history / 计划增删改的 family 分支实现
- feat(api_client): 新增 `make_family_client(jwt_token)` 工厂，**每请求创建独立实例**，避免全局单例设置 token 引发并发串号
- feat(web_helpers): 新增 `get_jwt_from_request` 与 `family_client(request)`，从 cookie `access_token` 取登录态
- refactor(home/chat): 所有 `require_login` 路由改用 `fc = family_client(request) or elderly_client` 调用，兼容未登录时的旧路径
- fix(home): `bind_device` 改走 `bind_device_family` 获取合法 token 后再落盘

### 兼容性说明

**向下兼容**。原有 `/device/*` 设备 token 接口完全保留，老人端行为不变、无需升级；子女端未登录时仍回落旧调用路径。已绑定用户建议在子女端**重新执行一次绑定**以写入合法 token。

---

## v2.37.0 (2026-08-11) — 设备标识改用网卡 MAC 整数值，移除 uuid5 派生 / pinpong / 持久化兜底

### 概述

老人端设备标识由「三级来源 + uuid5 派生」简化为**直接取 `uuid.getnode()` 的十进制整数值**（形如 `218356669348204`），并同步调整子女端绑定页面的显示与输入提示。

原实现有三条来源：MAC 经 `uuid5` 派生 → pinpong `Board.uuid` → 随机持久化 UUID。其中 pinpong 分支经 v2.30.3 验证在真实 M10 上恒返回 `None`（固件未暴露该属性），持久化兜底则会产生 `data/device_id.txt` 落盘文件。而 `uuid5` 派生结果为 36 字符含连字符的长串，在 240px 小屏上难以完整显示，家属手工抄录绑定也易出错。

改用 MAC 整数值后：每台设备唯一、重启不变、无需落盘即可稳定重生，且长度仅约 15 位纯数字，屏幕可完整显示、输入不易出错。

### 主要变更

**老人端（elderly_assistant）**
- refactor(device_id): `get_device_id()` 精简为直接返回 `str(uuid.getnode())`，删除 `_get_mac_uuid()` / `_get_pinpong_uuid()` / `_get_persisted_uuid()` 三个旧实现
- refactor(device_id): 不再依赖 `hardware.board.ensure_board`，模块彻底与 pinpong 解耦；不再生成 `data/device_id.txt`
- fix(device_id): MAC 读取失败或为 0 时返回 `None` 并告警，不再静默回落其它来源
- fix(display): 设备 ID 恢复完整显示（`ID: 218356669348204`），移除上一版为规避 UUID 超宽而加的前 8 位截断与 `UUID_SHORT_LEN` 常量
- docs(wifi_config): 修正已失效的「延迟导入避免触发 pinpong 初始化」注释——`device_id` now 不再引入 pinpong
- style: 老人端「设备 UUID」相关注释、日志与 docstring 统一改称「设备 ID」

**子女端（family_monitor）**
- fix(settings): 绑定表单标签由「设备UUID」改为「设备ID」，占位符与提示改为纯数字示例，移除「标准 UUID（8-4-4-4-12 十六进制，含连字符）」的过时格式说明
- feat(settings): 输入框增加 `inputmode="numeric"`，移动端唤起数字键盘
- style(settings): 已绑定设备信息中「设备标识」标签统一为「设备ID」；未填写时的提示文案统一为「请输入设备ID」

**文档与测试**
- docs(PRIVACY): 设备标识符说明由「存储在本地 `device_id.txt`」更正为「由网卡 MAC 地址直接读取（不落盘存储）」
- test(device_id): 重写 `tests/test_elderly_device_id.py`，覆盖整数格式、跨调用一致性、MAC 不可用与异常降级，并断言三个旧实现已移除（5 项通过）

### 兼容性说明

**设备 ID 格式发生变化，属不兼容变更**：已绑定的老设备在升级后 ID 会由 36 字符 UUID 变为纯数字，需在子女端**重新绑定**。服务端 `device_id` 为 `str` 字段且无格式校验，无需迁移。

---

## v2.36.2 (2026-08-11) — 修复老人端主界面底部设备 UUID 与服务器状态文字重叠

### 概述

修复老人端主界面底部「设备 UUID」与「服务器连接状态」两处小字横向叠压、互相压字导致无法辨认的显示缺陷。

根因是二者被放在同一行 `y = SCREEN_H - 30`（即 290），共享 240px 屏宽：UUID 以左上角为基准从 `x=10` 向右延伸，状态以 `top_right` 锚定 `x=230` 向左延伸。而 `get_device_id()` 经 `uuid5` 派生返回的是**标准 36 字符 UUID**（含 4 个连字符），加上 `UUID: ` 前缀共 42 字符，在 `font_size=10` 下宽度约 210~250px，从 `x=10` 起即铺满乃至超出整个屏宽；服务器状态文本约占右侧 75~80px（起点约 `x=152`）。两者区间严重交叠，必然重合。

本版本仅调整界面布局与文本呈现，不改变任何业务逻辑与接口。

### 主要变更

**老人端（elderly_assistant/core/display.py）**
- fix(display): 底部两项由「同一行左右分列」改为「上下两行各自居中」，彻底消除横向叠压：状态行 `y=SCREEN_H-34`、设备 ID 行 `y=SCREEN_H-20`
- fix(display): 新增 `_format_uuid()`，设备 UUID 截断为前 8 位显示（形如 `ID: f47ac10b`）；`uuid5` 前 8 位派生自 MAC 哈希，现场区分设备已足够，完整 UUID 仍可在配网页面与服务端查看
- fix(display): 同步修复 `show_status()` 与 `show_device_uuid()` 中的**控件重建分支**——该分支原本仍写死旧坐标（`SCREEN_H-30` / `x=10` / `top_right`），控件被销毁后重建会让重叠复现，属易漏的隐性回归点
- style(display): 底部小字字号由 10 调整为 9，进一步压缩占宽
- refactor(display): 提取 `STATUS_TEXT_Y` / `UUID_TEXT_Y` / `BOTTOM_TEXT_SIZE` / `UUID_SHORT_LEN` 布局常量，避免坐标散落多处导致后续再次错位

### 影响范围

仅影响老人端主界面底部显示。扫码按钮及提醒界面布局未改动。

---

## v2.36.1 (2026-08-11) — 修复三端依赖检测未进入虚拟环境导致每次启动误报缺失依赖

### 概述

修复三端启动时「每次都提示缺少依赖并重复安装」的缺陷。根因是依赖检测发生在**系统 Python** 进程内，而依赖实际安装在仓库根 `.venv` 中，系统 Python 的 `sys.path` 看不到 venv 内的包，因此每轮启动都判定缺失并重新触发安装；安装完成后又以系统 Python 重启自身，形成「检测缺失 → 安装到 venv → 用系统 Python 重启 → 再次检测缺失」的死循环。

`dfrobot_huskylensv2`（PyPI 未发布的单文件模块）另有独立成因：安装脚本仅凭 `is_package_installed()` 判断是否已安装，而该函数依赖**当前进程**的 `sys.path`；安装子进程与主程序 `sys.path` 不一致，导致文件明明已落地仍被判为未安装，每次启动都联网重新下载。

本版本不改变任何业务逻辑与接口，属纯启动流程缺陷修复。

### 主要变更

**老人端（elderly_assistant）**
- fix(main): 新增 `_in_venv()` 与 `_ensure_running_in_venv()`，在 `main()` 中**先切换到 `.venv` 解释器再执行依赖检测**，确保检测与运行处于同一环境
- fix(main): 原实现仅在「检测到缺失并安装后」才切 venv，若系统 Python 中恰好已装部分包（如 requests）则直接跳过，全程停留在系统 Python——与服务端此前修复的第 2 类历史问题同源
- fix(main): 安装 huskylens 时显式传入 `--target BASE_DIR`，保证模块落地目录与主程序 `sys.path` 一致，避免「装了却仍报缺失」

**子女端（family_monitor）**
- fix(main): 新增 `_in_venv()` / `_venv_python_path()`，在模块级依赖检查**之前**补充 venv 切换逻辑（原先完全缺失该步骤）
- fix(main): 安装脚本调用与安装后 `os.execv` 重启均由 `sys.executable` 改为 `.venv` 解释器，修复「依赖装进 venv 却用系统 Python 重启」导致的死循环

**服务端（server）**
- fix(main): `check_and_install_dependencies()` 中 `subprocess.run` 由 `sys.executable` 改为显式 `venv_python`，与重启逻辑保持一致

**公共安装脚本（common/install.py）**
- fix(install): 新增 `_is_valid_huskylens_file()`，直接校验本地 `dfrobot_huskylensv2.py` 是否存在且包含全部关键符号，命中则跳过下载
- fix(install): 文件残缺（如上次下载中断）时仍会重新下载，不会因存在空文件而永久跳过
- refactor(install): 提取 `HUSKYLENS_REQUIRED_MARKERS` 模块级常量，消除下载校验与本地校验的重复定义

### 影响范围

三端启动路径均受影响。修复后首次启动仍会正常安装依赖，此后启动不再重复检测失败、不再重复联网下载 huskylens 模块。

---

## v2.33.7 (2026-08-10) — 新增根目录统一启动入口 main.py，清理 Cloudflare HTTPS 启动提示

### 概述

新增仓库根目录 `main.py` 作为「直接以文件方式启动」场景的统一入口：自动识别当前设备是否为行空板（UNIHIKER M10，基于 Debian 10 buster 的 ARM 单板机），是则启动老人端，否则后台启动服务端与子女端，使用者无需再手动 `cd` 到各子目录分别启动。同时移除服务端与子女端启动横幅中的「HTTPS: 由 Cloudflare 隧道边缘自动配置，本地监听 HTTP」提示——公网访问与 HTTPS 方案（Cloudflare 隧道 / DDNS + Caddy / 仅内网）已在 `setup.sh` / `setup.ps1` 中由用户显式选择，启动横幅再写死单一方案会与实际部署不符、产生误导。

本版本不改变任何业务逻辑与接口，属纯启动体验与文案修正。

### 主要变更

**根目录（新增入口）**
- feat(main): 新增 `main.py` 统一启动入口，仅服务于「直接使用文件启动」场景，不与 `setup.sh` / `setup.ps1` 的进程守护职责重叠
- feat(detect): 实现行空板多特征识别 `detect_unihiker()`，任一命中即判定，并打印命中证据便于排障：
  - `/proc/device-tree/model` 含 `unihiker`（设备树型号，最直接的硬件特征；已处理 FDT 字符串的 NUL 结尾）
  - 主机名含 `unihiker`（出厂主机名特征）
  - `/etc/unihiker*` 配置文件存在（出厂镜像特征，前缀匹配而非精确名匹配）
  - ARM 架构（`aarch64` / `arm*`）+ Debian 10 buster（架构与发行版组合兜底，兼容 `ID_LIKE=debian` 衍生版与 `VERSION_ID=10.13` 带小版本号写法）
- feat(main): 非 Linux 平台在 `detect_unihiker()` 中提前短路返回，不做任何 `/proc`、`/etc` 探测
- feat(main): 识别为行空板时用 `os.execv` 直接替换当前进程为 `elderly_assistant/main.py`，不引入多余父进程，信号（Ctrl+C / SIGTERM）与 GUI 行为保持原生
- feat(main): 识别为非行空板时以 nohup 语义后台启动 `server/main.py` 与 `family_monitor/main.py`，父进程打印 PID 与日志路径后立即退出，关闭终端不影响服务：
  - POSIX 用 `start_new_session=True`（等价 `setsid()`），子进程成为新会话首进程，终端关闭的 SIGHUP 不传递
  - Windows 用 `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`，子进程脱离父控制台
  - `stdin` 置 `DEVNULL`，`stdout`/`stderr` 追加重定向到 `logs/server.out`、`logs/family.out`，避免终端消失后写日志触发 EPIPE / EBADF
- feat(main): 优先使用仓库根 `.venv` 内解释器启动子程序，避免依赖装在 venv 而用系统 Python 启动导致的 `import` 失败（后台模式下重启日志不易察觉）
- feat(main): 支持 `--force-elderly` / `--force-server` 显式覆盖自动识别（二者互斥，同时指定报错退出码 2），`--check` 仅打印识别结果不产生启动副作用；其余参数原样透传给子程序
- fix(main): `_read_os_release()` 跳过空行与 `#` 注释行，避免误解析成键值对；`OSError` 统一降级为「无法识别」交由后续特征兜底
- fix(main): 入口文件缺失时给出明确路径提示并以非零码退出，不再让子进程静默失败

**服务端（server）**
- style(main): 移除启动横幅中的 `HTTPS: 由 Cloudflare 隧道边缘自动配置，本地监听 HTTP` 输出行
- docs(main): `start_server()` docstring 改写为中性描述「本地监听 HTTP；对外访问方式由 setup.sh / setup.ps1 配置」

**家属端（family_monitor）**
- style(main): 移除 `lifespan()` 启动日志中的 `HTTPS: 由 Cloudflare 隧道边缘自动配置，本地监听 HTTP` 输出行
- docs(main): 模块顶部 docstring 与 `uvicorn.run` 前的行内注释改写为中性描述，路径前缀说明由「Cloudflare 隧道按子路径转发」泛化为「反向代理按子路径转发」
- docs(README): 注意事项中同名表述同步改写

**缺陷修复：根目录 main.py 引发的模块名遮蔽（致命）**

新增根目录 `main.py` 后，`server` 与 `family_monitor` 的模块级代码把仓库根目录以
`sys.path.insert(0, ...)` 插到搜索路径最前，导致 uvicorn 以 `"main:app"` 字符串重新
导入 ASGI 应用时解析到根目录的 `main.py`（其中没有 `app` 属性），启动直接失败：

```
ERROR:    Error loading ASGI app. Attribute "app" not found in module "main".
```

该问题在 README 记载的标准启动方式 `cd family_monitor && python main.py` 下即可稳定复现，
属于新增入口文件与既有同名模块的命名冲突，影响服务端与子女端全部启动路径。

- fix(family_monitor/main): 仓库根目录改用 `sys.path.append` 追加到末尾，保证同名模块优先解析到脚本自身目录
- fix(server/main): 同上，`_REPO_ROOT` 由 `insert(0)` 改为 `append`
- fix(elderly_assistant/main): 同上，`PROJECT_ROOT` 由 `insert(0)` 改为 `append`（预防性修复，避免后续同类遮蔽）
- 三处均补充注释说明「为何必须 append 而非 insert(0)」，防止后续维护者改回
- feat(main): 后台启动子进程时显式将子程序目录置于 `PYTHONPATH` 首位，并以相对文件名而非绝对路径启动，双重保证 `server` / `family_monitor` 各自的同名 `main` 模块互不串味

> 影响评估：`updater`、`common.*` 等跨端共享模块仍可正常导入（根目录仍在 `sys.path` 中，
> 仅优先级后移），全量测试 523 passed / 10 skipped 无回归。

**文档与版本**
- docs(README): 快速开始新增「根目录一键启动」小节，说明自动识别规则、后台运行行为与日志位置
- chore(version): `VERSION` 2.33.6 -> 2.33.7；同步修正 README 顶部滞后的版本号标注

### 涉及文件

- `main.py`（新增）
- `server/main.py`（修改：文案清理 + sys.path 遮蔽修复）
- `family_monitor/main.py`（修改：文案清理 + sys.path 遮蔽修复）
- `elderly_assistant/main.py`（修改：sys.path 遮蔽预防性修复）
- `family_monitor/README.md`（修改）
- `README.md`（修改）
- `.gitignore`（新增 `logs/` 忽略规则）
- `VERSION` — 2.33.6 -> 2.33.7
- `history.md`

---

## v2.30.0 (2026-08-07) — 新增药品编号（product_code）与老人端扫码播报、用药计划离线回退

### 概述

打通「家属端录入药品编号 → 服务端存储下发 → 老人端扫码播报用量」的完整链路：家属在网页端添加/编辑用药计划时可手输或用摄像头扫描药品条码填入药品编号（非必填）；老人点击主界面「扫码查药」触摸按钮打开摄像头扫描药盒条码，系统按编号匹配用药计划后 TTS 播报药品名与用量。同时将用药计划轮询改为 20 分钟一次，并引入「有网优先、失败回退本地、无网走本地」的离线缓存策略。

### 主要变更

**服务端（server）**
- feat(model): `medication_plans` 表新增可选字段 `product_code`（`String(64)`，可空，带索引），药品名称/剂量复用既有 `drug_name`/`dosage`，不引入独立药品主数据表
- feat(schema): `MedicationPlanCreate` / `MedicationPlanOut` 增加 `product_code` 字段
- feat(api): 公开接口 `FamilyMedicationPlan` 增加 `product_code`，设置/更新设备用药计划时透传落库
- feat(service): `medication_service.create_plan` / `update_plan` 写入 `product_code`；`device_service.get_schedule` / `get_plans` 在下发数据中返回 `product_code`
- feat(migration): 新增 Alembic 迁移 `20260807_001`，为 `medication_plans` 增加 `product_code` 列与索引

**家属端（family_monitor）**
- feat(ui): 「添加用药计划」表单新增「药品编号/条形码」可选字段与 📷 扫描按钮，扫码弹窗基于浏览器原生 `BarcodeDetector`（支持 EAN/UPC/Code39/Code128/ITF/Codabar/QR/DataMatrix/PDF417），不支持的浏览器降级为手动输入
- feat(ui): 计划列表项展示 🔖 药品编号徽标
- feat(api): `api_client.set_medication_plan` / `update_medication_plan` 透传 `product_code`；`medication_service.validate_and_build` 解析并规范化该字段

**老人端（elderly_assistant）**
- feat(barcode): 新增 `core/barcode.py`，提供统一扫码入口 `BarcodeScanner`，含两条互补通路——HuskyLens 板载条码（算法 17）/二维码（算法 18）识别，以及 USB 摄像头 + OpenCV/pyzbar 本地解码；依赖全部懒加载，任一通路不可用时自动降级
- feat(ports): 新增 `BarcodeScannerPort` 协议
- feat(workflow): 新增 `handle_scan_medication` 与 `find_plan_by_product_code`，扫码后按编号匹配计划并 TTS 播报「药品名 + 用量 + 服药时间」，未识别/未匹配均有语音提示
- feat(display): 主界面新增「扫码查药」触摸按钮，通过 `Display.set_scan_handler()` 注入回调（界面层不依赖扫码实现），点击后台线程执行且异常隔离；清屏/提醒界面/配网界面均正确重置按钮引用，旧版 unihiker 无 `add_button` 时静默跳过
- feat(offline): 新增 `services/schedule_cache.py`（临时文件 + 原子替换写入、读取做结构校验），`HTTPClient.get_medication_schedule` 网络成功即刷新本地缓存、失败回退本地缓存，无缓存时返回 `None` 表示结果未知
- fix(poller): `MedicationPoller` 拉取失败不再清空内存中的用药计划（原实现会因断网返回空列表而清空，导致漏提醒）；新增 `cache_loader` 注入项，启动即载入本地缓存；抽出 `_poll_once()` 便于单测
- feat(config): 轮询间隔默认由 60 秒改为 1200 秒（20 分钟）；新增 `SCAN_SOURCE` / `SCAN_USB_INDEX` / `SCAN_TIMEOUT_SEC` 配置项
- fix(config): 修复 `_ensure_env_template()` 因 `ensure_env_template` 未导入而始终抛 `NameError`、导致首次运行无法自动生成 `.env` 模板的缺陷
- feat(main): 装配条码扫描器并向 Display 注册扫码回调，退出清理时释放摄像头句柄
- feat(ports): `DisplayPort` 增加 `set_scan_handler`，`FakeDisplay` 同步实现

**测试与文档**
- test: 新增 `tests/test_elderly_barcode.py`（26 个用例），覆盖编号匹配、扫码播报各分支、屏幕扫码按钮回调装配与异常隔离、轮询离线回退与本地缓存读写异常
- test: `tests/test_elderly_config_loader.py` 同步断言新的轮询默认值与 `scan` 配置段
- docs: 更新根 `README.md` 功能概览、`elderly_assistant/README.md`（功能列表、按键说明表、扫码流程、离线策略、配置表）与 `requirements.txt` 可选依赖说明

### 涉及文件

- `server/app/models/medication_plan.py`、`server/app/schemas/medication.py`、`server/app/api/v1/endpoints/public.py`、`server/app/services/medication_service.py`、`server/app/services/device_service.py`
- `server/app/migrations/versions/20260807_001_add_product_code_to_medication_plans.py`（新增）
- `family_monitor/core/api_client.py`、`family_monitor/services/medication_service.py`、`family_monitor/templates/medication_settings.html`
- `elderly_assistant/core/barcode.py`（新增）、`elderly_assistant/services/schedule_cache.py`（新增）
- `elderly_assistant/ports.py`、`elderly_assistant/main.py`、`elderly_assistant/core/display.py`、`elderly_assistant/services/http_client.py`、`elderly_assistant/workflow/actions.py`、`elderly_assistant/workflow/reminder.py`、`elderly_assistant/utils/config_loader.py`、`elderly_assistant/hardware/fakes.py`、`elderly_assistant/requirements.txt`
- `tests/test_elderly_barcode.py`（新增）、`tests/test_elderly_config_loader.py`
- `README.md`、`elderly_assistant/README.md`
- `VERSION` — 2.29.24 → 2.30.0
- `history.md`

---

## v2.29.18 (2026-08-05) — 修复自动更新后 __pycache__ 残留导致旧代码未生效

### 概述
v2.29.17 的 Release 发布后，服务器通过自动更新升级到 v2.29.17（VERSION 文件已更新），但 `/chat` 仍返回 500 Internal Server Error。服务器日志显示 `NameError: name 'config' is not defined`，即 `chat.py` 的 `from core import config, elderly_client` 导入未生效。

### 根因分析
- 自动更新覆盖 `.py` 文件后，旧的 `__pycache__/*.pyc` 字节码缓存未被清除
- `__pycache__` 在 `runtime_protection.py` 的保护列表中（更新时不覆盖），但更新后也未主动删除
- Python 在某些时序条件下（如文件系统 mtime 精度不足、NTP 时钟漂移）可能优先加载旧 `.pyc` 而非重新编译 `.py`
- 导致 `chat.py` 源码已更新但进程仍运行旧字节码，`config` 导入缺失

### 主要变更
- fix(updater): 新增 `_purge_pycache()` 函数，在自动更新复制文件完成后、重启服务前，递归删除项目目录下所有 `__pycache__` 目录（跳过 `.venv`/`venv`/`.git` 内的缓存），确保 Python 重新编译所有 `.py` 文件
- feat(reset_runtime): 新增 `_print_diagnostics()` 诊断函数，在 `--reset` 重置完成后输出诊断报告，包含版本号、关键路由文件导入完整性检查、`__pycache__` 残留检测、`.env` 保留状态、重置统计和综合结论
- chore: VERSION 升级至 2.29.18，触发自动更新流程重新拉取完整代码并清除缓存

### 涉及文件
- `updater.py` — 新增 `_purge_pycache()` 函数；`_perform_update()` 在文件复制完成后调用该函数
- `reset_runtime.py` — 新增 `_print_diagnostics()` 函数和 `_CRITICAL_FILES` 检查表；`__main__` 入口调用诊断输出
- `family_monitor/main.py` — `--reset` 模式调用 `_print_diagnostics()` 输出诊断报告
- `VERSION` — 2.29.17 → 2.29.18
- `history.md`

---

## v2.29.17 (2026-08-05) — 修复全站 TemplateResponse API 不兼容导致 500

### 概述
v2.29.13 修复了 `chat.py` 缺少 `config` 导入的问题，但 `/chat` 仍返回 500 Internal Server Error。经深入排查，发现根因是 Starlette 0.27.0（FastAPI 0.104.1 自带）的 `TemplateResponse` 签名为 `(name, context, ...)`，而所有路由都使用了 Starlette 0.28.0+ 才支持的 `TemplateResponse(request, name, context)` 新 API，导致 `ValueError: context must include a "request" key`。此问题影响全站所有页面（首页、提醒、记录、仪表板、设置、消息、登录、注册、安全设置），不只是 /chat。

### 根因分析
- `requirements.txt` 固定 `fastapi==0.104.1`，自带 `starlette==0.27.0`
- Starlette 0.27.0 的 `TemplateResponse(self, name, context, ...)` 不接受 `request` 作为第一个位置参数
- 代码中 10 处调用均使用 `TemplateResponse(request, "name.html", {...})` 新 API（Starlette 0.28.0+）
- Starlette 0.27.0 将 `request` 对象解释为模板名，将 `"name.html"` 解释为 context（字符串），触发 `ValueError`
- auth.py 中 3 处调用的 context 还缺少 `"request": request` 键

### 主要变更
- fix(routes): `routes/chat.py` — `TemplateResponse` 调用从 `(request, name, context)` 改为 `(name, context)`（context 已包含 `"request": request`）
- fix(routes): `routes/home.py` — 6 处 `TemplateResponse` 调用同样修复（index/reminders/records/dashboard/settings/medication_settings）
- fix(routes): `routes/auth.py` — 3 处 `TemplateResponse` 调用修复（login/register/security_setup），并为 login、register、security_setup 的 context 补充缺失的 `"request": request` 键

### 涉及文件
- `family_monitor/routes/chat.py` — 1 处 TemplateResponse 调用修复
- `family_monitor/routes/home.py` — 6 处 TemplateResponse 调用修复
- `family_monitor/routes/auth.py` — 3 处 TemplateResponse 调用修复 + 3 处 context 补充 `"request"` 键
- `VERSION` — 2.29.16 → 2.29.17
- `history.md`

---

## v2.29.16 (2026-08-05) — 修复 GitHub 登录授权阶段 ConnectTimeout 未捕获导致 500

### 概述
用户点击「GitHub 登录」时，服务器在 OAuth 授权阶段（`_authorize` 函数构造授权地址）抛出 `httpx.ConnectTimeout`，该异常未被 try/except 捕获，直接 bubbling up 返回 500 Internal Server Error。此问题是 v2.29.9 修复回调阶段超时的遗留：当时仅给 `_callback` 添加了 `httpx.HTTPError` 捕获，但 `_authorize` 函数中的 `get_authorization_url` 调用同样可能触发网络超时（服务器访问 GitHub 受限），却完全没有异常处理。

### 根因分析
- `_authorize` 函数调用 `await cfg["client"].get_authorization_url(...)` 时未包裹 try/except
- `ConnectTimeout` 属于 `httpx.HTTPError` 子类，但该函数无任何异常捕获
- 异常直接传播到 FastAPI 路由处理器，返回 500 错误
- `_bind_authorize` 函数通过调用 `_authorize` 间接继承同一问题

### 主要变更
- fix(oauth): `_authorize` 函数新增 `error_url` 参数，`get_authorization_url` 调用包裹 try/except，捕获 `httpx.HTTPError`（含 `ConnectTimeout`）后优雅跳转登录页并携带 `?error=oauth_timeout`；捕获 `Exception` 后跳转 `?error=oauth_fail`
- fix(oauth): `_bind_authorize` 调用 `_authorize` 时传入 `error_url` 指向设置页（`?error=oauth_timeout`），绑定模式异常跳转设置页而非登录页
- fix(frontend): `settings.html` URL 参数检测新增 `oauth_timeout` 分支，显示「网络连接超时，服务器访问第三方可能受限，请稍后重试」

### 涉及文件
- `server/app/api/v1/endpoints/oauth.py` — `_authorize` 新增 try/except 与 `error_url` 参数；`_bind_authorize` 传入 `error_url`
- `family_monitor/templates/settings.html` — 新增 `oauth_timeout` 错误提示
- `VERSION` — 2.29.15 → 2.29.16
- `history.md`

---

## v2.29.15 (2026-08-05) — 仪表盘数据可视化消除虚假数据

### 概述
仪表盘数据可视化模块存在大量虚假数据：7天用药趋势为硬编码数组、药品名有固定 fallback 列表、散点/气泡/热力图使用 `Math.random()`、箱线图含虚构血压心率数据、地图类图表含硬编码城市坐标、相关性矩阵含虚构相关系数等。本次彻底重构后端数据计算和前端图表渲染，确保所有图表数据来自真实的用药计划和服药记录。

### 主要变更

#### 后端 `family_monitor/core/api_client.py`
- `get_dashboard_data()` 全面重写，从真实 reminders（用药计划）和 records（服药记录）计算：
  - 7天趋势：按 `scheduled_time` 日期分组统计 taken/missed/scheduled
  - 按药品统计：通过 `plan_id → drug_name` 映射统计各药品服药次数
  - 日历热力图：按日期统计已服药次数
  - 药品×星期热力矩阵：各药品在一周中每天的服药次数
  - 甘特图：从 `schedule_times` 提取各药品服药时段
  - 漏斗图：总记录 → 已服药 → 未服药
  - `medications` 字段从 `[]` 改为从 plans 提取完整药品信息
  - `adherence_rate` 改为基于 `status=='taken'` 计算（原 `confirmed` 字段不存在于实际记录中）

#### 前端 `family_monitor/templates/dashboard.html`
- `buildData()` 从 `DASHBOARD_DATA.chart_data` 读取真实数据，移除所有硬编码数组
- 图表类型从 34 种精简到 14 种（保留有真实数据源的图表）：
  - 保留：柱状图、条形图、折线图、面积图、甘特图、漏斗图、仪表盘、饼图、环形图、堆叠柱状图、百分比堆叠条形图、矩形树图、直方图、热力图、日历热力图、水球图
  - 移除：雷达图、词云图、烛台图、瀑布图、箱线图、密度图、小提琴图、山脊线图、旭日图、马赛克图、散点图、气泡图、相关性矩阵图、网络关系图、和弦图、桑基图、点地图、等值线地图、热力地图、路径地图、平行坐标图
- 所有 `Math.random()` 调用已移除
- 所有硬编码药品名（阿司匹林、二甲双胍等）已移除
- 所有虚构健康数据（血压、心率、血糖等）已移除
- 所有硬编码城市坐标已移除
- 移除不再需要的 CDN 引用：echarts-wordcloud、china.js
- 添加空数据占位：当无数据时显示"暂无数据"而非虚构数据

### 涉及文件
- `family_monitor/core/api_client.py` — 重写 `get_dashboard_data()`，计算真实图表数据
- `family_monitor/templates/dashboard.html` — 重写 `buildData()` 和 `buildOption()`，精简图表类型

## v2.29.14 (2026-08-05) — 统一全站设备状态栏样式

### 概述
首页（dashboard）与其他页面的设备状态栏存在视觉不一致：左侧 status-icon 使用了多种不同元素（Unicode 圆点、SVG 图标、emoji、CSS 圆点指示器），右侧 status-badge 文字风格也各不相同（Unicode 符号、纯文字、emoji、CSS 圆点）。此外 reminders 和 records 页面缺少 status-subtitle（设备ID），且标题文字使用"老人端在线/离线"而非设备名。本次统一全站 6 个页面的状态栏。

### 统一方案
- 左侧 status-icon：统一为主页风格（Unicode 实心圆 `●` / 空心圆 `○`）
- 右侧 status-badge：统一为 CSS 圆点 + 文字风格（`<span class="status-badge-dot"></span> 设备在线/离线`）
- 标题/副标题：统一为主页风格（设备名 + 设备ID/未绑定设备）
- JS 轮询：所有页面的 `refreshDeviceStatus` 函数统一使用 `innerHTML` 更新 badge，并同步更新 subtitle

### 主要变更
- style(css): 添加通用 `.status-card.online/offline .status-badge-dot` 颜色规则，确保非 page-home 页面圆点也有颜色
- fix(dashboard): 右侧 badge 从 Unicode 符号改为 CSS 圆点 + 文字
- fix(reminders): 右侧 badge 改为 CSS 圆点；标题从"老人端在线/离线"改为设备名；新增 status-subtitle 显示设备ID
- fix(records): 左侧 SVG 图标改为 Unicode 圆点；右侧 badge 改为 CSS 圆点；标题从"老人端在线/离线"改为设备名；新增 status-subtitle
- fix(settings): 右侧 badge 从 Unicode 符号改为 CSS 圆点 + 文字
- fix(medication_settings): 左侧 emoji 改为 Unicode 圆点；右侧 badge 从 emoji 改为 CSS 圆点 + 文字
- fix(index): 左侧 `status-indicator`（CSS 圆点指示器）改为 `status-icon`（Unicode 圆点）；JS 从 class 操作改为 innerHTML 更新

### 涉及文件
- `family_monitor/static/css/style.css` — 添加通用 status-badge-dot 颜色规则
- `family_monitor/templates/dashboard.html` — badge HTML + JS 更新
- `family_monitor/templates/reminders.html` — badge + 标题/副标题 + JS 更新
- `family_monitor/templates/records.html` — 左侧图标 + badge + 标题/副标题 + JS 更新
- `family_monitor/templates/settings.html` — badge HTML + JS 更新
- `family_monitor/templates/medication_settings.html` — 左侧图标 + badge + JS 更新
- `family_monitor/templates/index.html` — 左侧 status-indicator 改为 status-icon + JS 更新

## v2.29.13 (2026-08-05) — 修复消息页面 Internal Server Error

### 概述
family_monitor 消息页面（`/chat`）访问时返回 500 Internal Server Error。根因是 `routes/chat.py` 中使用了 `config.APP_NAME`、`config.ELDERLY_SERVER_URL`、`config.PATH_PREFIX`，但从未导入 `config` 模块，导致 `NameError`。

### 主要变更
- fix(chat): `routes/chat.py` 导入行从 `from core import elderly_client` 改为 `from core import config, elderly_client`

### 涉及文件
- `family_monitor/routes/chat.py` — 补充 `config` 模块导入
- `VERSION` — 2.29.12 → 2.29.13
- `history.md`

---

## v2.29.12 (2026-08-05) — 修复设置页 OAuth 绑定成功却提示失败 & 手机/邮箱绑定弹窗不可见

### 概述
设置页「登录方式管理」存在两个缺陷：
1. GitHub/Gitee 绑定实际已成功（数据库已写入），但用户看到"第三方绑定失败，请重试"——根因是 `oauth.py` 绑定成功日志中引用了未定义的 `oauth_email` 变量，触发 `NameError` 被 `except Exception` 捕获后走入了 `?error=bind_fail` 分支。
2. 手机号/邮箱绑定按钮点击后弹窗不可见——根因是 CSS `.modal-overlay` 默认 `visibility: hidden; opacity: 0`，需添加 `.show` 类才可见，但 `openModal()` 仅设置 `display: flex` 未添加 `.show` 类。

### 主要变更
- fix(oauth): `_callback` 绑定模式成功分支中，`logger.info` 的 `oauth_email` 改为 `info.get("email")`，消除 `NameError`
- fix(settings): `openModal()` 增加 `classList.add('show')` 使弹窗可见（配合 CSS transition 动画）
- fix(settings): `closeModal()` 改为先移除 `.show` 类触发淡出动画，200ms 后再设 `display: none`
- fix(settings): `openModal/closeModal` 增加元素存在性校验（`if (!el) return`）

### 涉及文件
- `server/app/api/v1/endpoints/oauth.py` — 绑定成功日志变量修复
- `family_monitor/templates/settings.html` — `openModal/closeModal` 添加 `.show` 类逻辑
- `VERSION` — 2.29.11 → 2.29.12
- `history.md`

---

## v2.29.11 (2026-08-04) — 修复新增用药提醒始终报"会话可能已过期"的错误提示

### 概述
family_monitor 的 `reminders.html` 在保存用药提醒时，前端 fetch 错误处理逻辑有缺陷：当后端返回 HTTP 400（如未绑定设备、设备令牌无效等业务错误）时，前端不解析 JSON 响应体中的实际错误信息，而是统一抛出"会话可能已过期，请重新登录 (HTTP 400)"，导致用户无法看到真实失败原因。同时 `api_client.py` 在服务端返回非 200 时仅透传"状态码: 403"等无意义信息，未提取响应体中的 `detail` 字段。

### 根因分析
错误链路：前端 POST → BFF `add_medication_plan` → `elderly_client.set_medication_plan` → 服务端 `POST /public/device/medication_plan`

1. **未绑定 M10 设备**：`set_medication_plan` 检测 `self._device_id` 为 None，返回 `{"success": False, "error": "未绑定设备"}`
2. **BFF 包装错误**：`home.py` 将其包装为 HTTP 400 JSON 响应 `{"success": False, "message": "添加失败: 未绑定设备..."}`
3. **前端错误**：`reminders.html` 检查 `r.redirected || !r.ok`，遇到 400 直接抛出"会话可能已过期"，**不读取 JSON 响应体**

### 主要变更
- fix(reminders): `reminders.html` 的 `saveRow` fetch 错误处理重构——302 重定向时才提示"会话过期"，非 200 状态码时解析 JSON 响应体获取后端返回的实际错误信息
- fix(reminders): `reminders.html` 的 `deletePlan` 同步修复 302 重定向检测
- fix(medication_settings): `medication_settings.html` 的添加/删除操作增加 302 重定向检测，避免会话过期时 JSON 解析失败
- fix(api_client): 新增 `_extract_error` 方法，从服务端非 200 响应中提取 `detail`（FastAPI HTTPException）或 `message`（BFF JSONResponse）字段，替代无意义的"状态码: xxx"
- fix(api_client): `set_medication_plan` / `update_medication_plan` / `delete_medication_plan` 三个方法均接入 `_extract_error`
- fix(api_client): 未绑定设备时的错误提示从"未绑定设备，请先绑定设备"改为"未绑定 M10 设备，请先在设置页面绑定设备后再添加用药计划"，更明确地引导用户

### 涉及文件
- `family_monitor/templates/reminders.html` — `saveRow` 和 `deletePlan` 的 fetch 错误处理重构
- `family_monitor/templates/medication_settings.html` — 添加/删除操作增加 302 重定向检测
- `family_monitor/core/api_client.py` — 新增 `_extract_error` 方法，三个用药计划方法接入，未绑定设备提示优化
- `VERSION` — 2.29.10 → 2.29.11
- `history.md`

---

## v2.29.10 (2026-08-04) — 登录/注册/安全设置页面 logo 由文字替换为图片

### 概述
family_monitor 三端认证页面（登录、注册、安全设置）的 `.auth-logo` 原为纯文字"子女守护中心"（`<div>` + CSS `font-size`），在有限宽度的 auth-card 中容易换行且视觉效果单调。本版本将其统一替换为用户提供的应用图标图片（`auth-logo.png`），保留原有上下浮动（bounce）动画，图片尺寸 80×80px 居中圆角显示。

### 主要变更
- feat(family): `login.html` / `register.html` / `security_setup.html` 三端认证页面的 `.auth-logo` 从 `<div>子女守护中心</div>` 替换为 `<img src=".../static/img/auth-logo.png" alt="子女守护中心">`
- feat(family): 新增 `family_monitor/static/img/auth-logo.png` 应用图标资源
- style(css): `.auth-logo` 样式从文本属性（`font-size` / `font-weight` / `white-space`）改为图片属性（`width: 80px` / `height: 80px` / `border-radius: 18px` / `display: block` / `margin: 0 auto`），保留 `bounce` 上下浮动动画

### 涉及文件
- `family_monitor/templates/login.html` — auth-logo 替换为 img 标签
- `family_monitor/templates/register.html` — auth-logo 替换为 img 标签
- `family_monitor/templates/security_setup.html` — auth-logo 替换为 img 标签
- `family_monitor/static/css/style.css` — `.auth-logo` 样式适配图片
- `family_monitor/static/img/auth-logo.png` — 新增应用图标
- `VERSION` — 2.29.9 → 2.29.10
- `history.md`

---

## v2.29.9 (2026-08-04) — 修复 GitHub OAuth 回调网络超时导致 500 崩溃

### 概述
服务器在中国大陆访问 `github.com:443` 响应极慢，OAuth 回调换取 access_token 时触发 `httpx.ReadTimeout`（30 秒超时）。`_callback` 中仅捕获 `OAuth20AuthorizeCallbackError`，未捕获 `httpx.HTTPError`，导致未处理异常 bubbling up 返回 500 错误。同时 family_monitor 登录页未读取 `?error=` 查询参数，用户看不到任何错误提示。

### 主要变更
- fix(oauth): `_callback` 换 token 的 `try/except` 新增 `httpx.HTTPError` 捕获，网络超时时优雅跳转登录页并携带 `?error=oauth_timeout`
- fix(oauth): `_callback` 拉取用户信息的 `try/except` 新增 `httpx.HTTPError` 捕获，区分网络超时与其他异常
- feat(family): `login_page` 读取 `?error=` 查询参数，映射为用户可读的中文提示（`oauth_timeout` / `oauth_fail` / `oauth_state` / `oauth_code` / `oauth_token` / `oauth_user`）

### 涉及文件
- `server/app/api/v1/endpoints/oauth.py` — `_callback` 新增 `httpx.HTTPError` 异常捕获
- `family_monitor/routes/auth.py` — `login_page` 读取 error 查询参数并映射为中文提示
- `VERSION` — 2.29.8 → 2.29.9
- `history.md`

---

## v2.29.8 (2026-08-04) — 修复 security_headers 中间件 pop 方法不存在导致 500 崩溃

### 概述
`SecurityHeadersMiddleware` 中使用 `response.headers.pop(h, None)` 移除废弃响应头，但 Starlette 的 `MutableHeaders` 对象没有 `pop` 方法，导致每个请求在安全头处理阶段抛出 `AttributeError: 'MutableHeaders' object has no attribute 'pop'`，返回 500 错误。

### 主要变更
- fix(middleware): `security_headers.py` 中 `response.headers.pop(h, None)` 改为 `del response.headers[h]` + `try/except KeyError` 容错

### 涉及文件
- `server/app/middleware/security_headers.py` — 用 `del` 替代不存在的 `pop` 方法
- `VERSION` — 2.29.7 → 2.29.8
- `history.md`

---

## v2.29.7 (2026-08-04) — 修复 family 端登录页标题"子女守护中心"错误换行

### 概述
family_monitor 登录/注册/安全设置页面的 `.auth-logo` CSS 样式原为 emoji logo 设计（`font-size: 4rem`），但实际内容为 6 个汉字"子女守护中心"，在 auth-card 有限宽度（max-width: 420px, padding: 40px）下超出可用宽度导致换行（从"中"和"心"之间断开）。

### 主要变更
- fix(css): `.auth-logo` 的 `font-size` 从 `4rem` 降至 `2rem`，适配纯文本标题
- fix(css): 添加 `white-space: nowrap` 防止标题在任何设备宽度下换行
- fix(css): 添加 `font-weight: bold` 保持视觉层级

### 涉及文件
- `family_monitor/static/css/style.css` — `.auth-logo` 样式修正
- `VERSION` — 2.29.6 → 2.29.7
- `history.md`

---

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

### 设备ID获取优化 - 使用pinpong库获取设备UUID
- 修改`elderly_assistant/services/device_id.py`：
  - 行空板M10设备标识改为通过pinpong库获取设备UUID（Board.uuid）
  - 移除Linux和Windows兼容代码，老人端仅用于M10平台
  - 添加详细的日志输出，便于调试
  - 兜底：生成标准UUID并持久化到本地文件
- 修改`elderly_assistant/tui/tui_app.py`：
  - 系统设置菜单新增"设备UUID"显示项
  - 选择后可语音播报设备UUID，提示用户在子女端输入此ID完成绑定
- 修改`family_monitor/templates/settings.html`：
  - 设备绑定表单标签改为"设备UUID"
  - 更新placeholder和提示信息，明确格式为标准UUID（8-4-4-4-12 十六进制，含连字符）

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

## 变更记录

### v2.30.3 (2026-08-08)
- 修复 `elderly_assistant` 设备唯一标识来源：经行空板官方文档与真实 M10 日志双重确认，
  pinpong 的 `Board` 类未暴露 `uuid` 属性（仅作硬件初始化入口），原 `board.uuid` 取值恒为 None。
- 改用网卡 MAC 地址（`uuid.getnode()`）经标准 `uuid5` 确定性派生设备 UUID 作为主硬件来源：
  每设备唯一、重启不变、删除本地 `data/device_id.txt` 也能从 MAC 重生，彻底消除
  `pinpong Board 未提供 uuid 属性，降级到持久化 UUID` 告警。
- pinpong 取 uuid 仅保留为未来版本兼容的兜底尝试；随机持久化 UUID 为最后兜底。
- 同步更新 `tests/test_elderly_device_id.py` 覆盖 MAC 派生/确定性/降级路径，6 项测试通过。

### v2.31.0 (2026-08-09)
- 依赖自动安装补全：老人端 `main.py` 依赖检测新增 `pyzbar`（USB 摄像头扫码通路所需）；
  缺失依赖时除调用 `common/install.py` 安装 Python 包外，额外最佳努力 `apt-get install`
  M10 系统级原生库 `espeak`（pyttsx3 离线 TTS 后端）、`libzbar0`（pyzbar 解码后端），
  避免运行时 `No module named 'pyzbar'` / 语音初始化失败（失败不影响主流程，对应功能已降级）。
- 配网热点改为「检测是否已联网」：启动时调用 `HotspotManager.is_online()`（探测公共 DNS
  8.8.8.8 / 1.1.1.1 / 114.114.114.114）判断是否联网；已联网则跳过热点与配网 Web 服务，
  仅离线/首启时才启动热点供手机配网（WiFi 配网入口仍在热点页面，逻辑不变）。`finally`
  清理增加空值保护。
- 默认服务端地址改为部署域名固定路径 `https://my-website.ccwu.cc/eating-medication/server`
  （原 `http://localhost:1059`），同步更新 `config_loader.DEFAULT_CONFIG` 与 `.env` 模板。
- 新增 `tests/test_elderly_hotspot_online.py` 覆盖联网检测（在线/离线/返回布尔）；
  `tests/test_elderly_config_loader.py` 默认地址断言同步更新。

### v2.32.0 (2026-08-09)
- TTS 引擎改为「联网优先 edge-tts，失败/无网走 pyttsx3」双引擎架构（`services/speech.py` 重写）：
  - edge-tts（中文神经语音 zh-CN-XiaoxiaoNeural）联网时优先播报，产出 MP3 由系统播放器
    （mpg123/ffplay/mpv/play，按序探测）播放；无网或请求失败自动降级。
  - pyttsx3 作为离线兜底，优先选用 `mbrola-cn1` 中文语音（缺失则退回默认语音）。
  - 两引擎初始化期均尝试加载，运行时按优先级选择；全部不可用仅禁用语音，不影响主流程。
- 依赖/系统包自动安装补全（`main.py` + `requirements.txt`）：
  - Python 包新增 `edge-tts`（加入依赖检测与 requirements.txt）。
  - 修正此前 pyzbar 自动安装无效的问题：`pyzbar` / `opencv-python-headless` 实际写入
    requirements.txt，确保缺失时能被 `common/install.py` 真正安装（此前仅为注释）。
  - 系统级原生包 `apt-get install` 列表新增 `mbrola mbrola-cn1`（pyttsx3 中文语音）
    与 `mpg123`（edge-tts 的 MP3 播放器），与既有安装逻辑一致、失败不影响主流程。



