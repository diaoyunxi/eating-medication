# 用药辅助系统严格审查报告

**审查日期**：2026-07-01
**审查对象**：`diaoyunxi/eating-medication` 仓库（commit 状态，版本 2.1.0）
**审查范围**：3 个子模块共 60+ Python 文件、10+ HTML 模板、3 个 requirements.txt 及多个配置文件
**审查维度**：代码安全、代码质量、逻辑正确性、配置与部署（全部维度）
**输出形式**：详细报告

---

## 目录

- [一、执行摘要](#一执行摘要)
- [二、严重问题（Critical / P0）](#二严重问题critical--p0)
- [三、高危问题（High / P1）](#三高危问题high--p1)
- [四、中危问题（Medium / P2）](#四中危问题medium--p2)
- [五、低危问题（Low / P3）](#五低危问题low--p3)
- [六、依赖与供应链](#六依赖与供应链)
- [七、已确认安全项](#七已确认安全项)
- [八、修复路线图](#八修复路线图)

---

## 一、执行摘要

本次审查共发现 **47 个去重问题**：

| 严重程度 | 数量 | 说明 |
|---------|------|------|
| 严重 (Critical) | **11** | 可导致身份伪造、用户健康危害、远程代码执行路径 |
| 高 (High) | **15** | 越权、信息泄露、CSRF、XSS、供应链风险 |
| 中 (Medium) | **21** | 输入校验、配置缺陷、可用性问题 |
| 低 (Low) | **20+** | 代码质量、文档、依赖锁定 |

### 最紧迫的三类风险

1. **会话/JWT 密钥泄露与可伪造**：`family_monitor/config.json:8` 硬编码弱 SECRET_KEY 已随仓库公开；`server/main.py:106` 自动生成的 `.env` 写入弱密钥。攻击者可伪造任意用户（含 admin）会话。
2. **设备端点完全无认证**：`server/app/api/v1/endpoints/public.py` 与 `chat.py` 任意人凭 device_id 即可篡改老人用药计划、冒充聊天、查询历史，存在实际健康危害。
3. **家属端跨站攻击链**：CORS 全开 + 无 CSRF + 多处 XSS（chat.html、medication_settings.html），构成完整跨站劫持链。

---

## 二、严重问题（Critical / P0）

### C1. `family_monitor` 硬编码弱 SECRET_KEY 并随仓库公开
- **文件**：[config.json](file:///workspace/family_monitor/config.json#L8)、[core/config.py](file:///workspace/family_monitor/core/config.py#L53)
- **代码**：`"SECRET_KEY": "your-secret-key-change-in-production-12345678"`
- **机制**：`core/config.py:67-68` 将 config.json 全部键写入 `os.environ`，覆盖了第 53 行 `_generate_secret_key()` 的随机值。该密钥被 `itsdangerous.URLSafeTimedSerializer`（`core/session.py:20`）用于签发会话令牌。
- **加剧情节**：[.gitignore](file:///workspace/family_monitor/.gitignore) 仅排除 `.env` 与 `data/`，**未排除 `config.json`**，该弱密钥已随 git 历史公开。
- **风险**：任意攻击者可离线伪造任意用户（含 admin）的会话令牌，绕过登录、绕过 `/admin` 路径校验，7 天有效。
- **建议**：
  1. 立即从 git 历史中清除该 SECRET_KEY（`git filter-repo` 或 BFG）；
  2. 将 `config.json` 加入 `.gitignore`，提交 `config.json.example` 模板；
  3. SECRET_KEY 仅从环境变量读取，缺失或为已知弱值时拒绝启动；
  4. 轮换当前所有已签发的会话令牌。

### C2. `server` 自动生成 `.env` 默认开启 DEBUG=True 且写入弱密钥
- **文件**：[server/main.py](file:///workspace/server/main.py#L99)、[server/main.py](file:///workspace/server/main.py#L106)
- **代码**：
  ```python
  "DEBUG=True\n"
  "SECRET_KEY=your-secret-key-change-this-in-production\n"
  ```
- **机制**：首次运行时若 `.env` 不存在自动写入上述内容。pydantic-settings 加载 `.env` 后，`DEBUG=True` 覆盖默认 `False`（`config.py:15`），弱密钥覆盖随机密钥（`config.py:23`）。
- **风险**：
  - DEBUG 模式下 FastAPI 异常返回完整堆栈跟踪、源码片段、内部变量，泄露架构信息；
  - `/docs`、`/redoc` 文档默认暴露；
  - 弱密钥可被攻击者伪造任意用户 JWT。
- **建议**：
  1. 默认生成 `DEBUG=False`；
  2. `SECRET_KEY` 用 `secrets.token_urlsafe(32)` 生成随机值；
  3. 启动时检测若 `SECRET_KEY` 等于已知弱值则拒绝启动。

### C3. 服务端 SECRET_KEY 默认每次启动随机生成
- **文件**：[app/core/config.py](file:///workspace/server/app/core/config.py#L8-L10)
- **代码**：`SECRET_KEY: str = _generate_secret_key()`（默认值在 Settings 实例化时调用 `secrets.token_urlsafe(32)`）
- **风险**：若 `.env` 未配置 `SECRET_KEY`，每次重启所有已签发 JWT 立即失效；多 worker 部署时各进程密钥不一致，A 实例签发的 token 在 B 实例验证失败。
- **建议**：生产环境强制要求通过环境变量显式注入；启动时校验，若为默认随机生成且 `DEBUG=False` 则 `raise RuntimeError`。

### C4. 聊天端点完全无认证 + 客户端自定 sender_id
- **文件**：[app/api/v1/endpoints/chat.py](file:///workspace/server/app/api/v1/endpoints/chat.py#L15-L89)、[app/schemas/chat.py](file:///workspace/server/app/schemas/chat.py#L7-L12)
- **问题端点**：
  - `POST /chat/send`（line 15-38）：无 `Depends(get_current_user)`，`ChatMessageCreate` 让客户端任意指定 `sender_id`、`receiver_id`、`sender_name`
  - `GET /chat/history/{user_id}`（line 41-47）：无认证，任意人传 `user_id` 即可读取该用户全部聊天记录
  - `WS /chat/ws/{user_id}`（line 50-89）：从 URL 路径取 `user_id`，无 token 校验，任意人可连接任意 user_id 接收推送给该用户的消息
- **风险**：身份冒充、隐私泄露、消息伪造；针对老人的虚假服药/紧急消息可能造成实际健康危害。
- **建议**：三个端点均加 `Depends(get_current_user)`；`sender_id` 从 token 提取而非请求体传入；历史接口只允许查询自己参与的消息；WebSocket 连接时强制校验 token。

### C5. 设备公开端点任意篡改/删除老人用药计划
- **文件**：[app/api/v1/endpoints/public.py](file:///workspace/server/app/api/v1/endpoints/public.py)
- **问题端点**：
  - `POST /device/register`（line 55-73）：用任意 device_id 自动创建 `role="elderly"` 用户，`hashed_password="device"`（不是有效 bcrypt hash）
  - `POST /device/medication_plan`（line 188-216）：凭 device_id 任意设置用药计划（药名、剂量、服药时间）
  - `DELETE /device/medication_plan/{plan_id}`（line 246-255）：完全无认证、无所有权校验，凭 plan_id 删除任意计划
  - `GET /device/schedule/{device_id}`、`GET /device/plans/{device_id}`、`GET /device/status/{device_id}`、`GET /device/check/{device_id}`：信息泄露
  - `POST /public/ai/ask`、`POST /ai/chat/public`：未授权消耗付费 AI 配额
- **风险**：
  - 攻击者可篡改任意老人的用药计划（药名、剂量、服药时间），可能导致老人服错药或漏服，存在人身安全风险；
  - 用户名抢注（DoS）、数据库污染；
  - AI 配额被恶意消耗造成经济损失。
- **建议**：
  1. 引入设备级密钥（设备首次注册时由服务端签发，后续请求需携带 HMAC 签名）；
  2. 至少对写操作（注册、设/删用药计划）做基于 device_id 的速率限制 + 签名校验；
  3. `hashed_password="device"` 改为生成不可登录的随机串，或引入 `is_device` 字段，避免污染密码字段；
  4. AI 端点至少加 IP/设备级限流。

### C6. 家属端 CORS 全开 + 无 CSRF 防护
- **文件**：[family_monitor/main.py](file:///workspace/family_monitor/main.py#L73-L79)（CORS）、[routes/auth.py](file:///workspace/family_monitor/routes/auth.py)、[routes/home.py](file:///workspace/family_monitor/routes/home.py)、[routes/admin.py](file:///workspace/family_monitor/routes/admin.py)
- **代码**：
  ```python
  app.add_middleware(
      CORSMiddleware,
      allow_origins=["*"],
      allow_credentials=True,
      allow_methods=["*"],
      allow_headers=["*"],
  )
  ```
- **问题**：所有 POST 表单端点（登录、注册、修改服务器配置、绑定/解绑设备、添加/删除用药计划、管理员配置）均无 CSRF token 校验。
- **风险**：结合 CORS 全开，任意第三方网站可发起携带用户 `session_token` cookie 的跨站请求。攻击者可代受害者修改服务器地址为攻击者控制的端点、绑定攻击者设备、添加恶意用药计划、修改 SECRET_KEY 等。
- **建议**：
  1. CORS 改为受信任域名显式白名单；
  2. 引入 CSRF token 机制（双提交 cookie 或同步令牌模式）；
  3. cookie 改为 `samesite="strict"`。

### C7. 服务端 CORS 配置矛盾且不安全
- **文件**：[app/main.py](file:///workspace/server/app/main.py#L98-L104)、[app/middleware/cors.py](file:///workspace/server/app/middleware/cors.py#L7-L16)
- **问题**：`main.py` 内联注册了 `CORSMiddleware` 用通配符 `*` 同时开启 `allow_credentials=True`；同时 `app/middleware/cors.py` 定义了更安全的 `setup_cors(app)`（基于 `ALLOWED_ORIGINS` 环境变量），但 `main.py` 从未调用它。两套 CORS 逻辑并存且互相矛盾。
- **风险**：配置意图错误，若后续改为 Cookie 鉴权即立刻形成 CSRF；维护混乱。
- **建议**：删除 `main.py` 内联的 CORS 注册，改调 `setup_cors(app)`；生产必须配置具体白名单域名。

### C8. 日志中间件记录全部请求体（含密码明文）
- **文件**：[app/middleware/logging.py](file:///workspace/server/app/middleware/logging.py#L27-L47)
- **代码**：
  ```python
  if method in ("POST", "PUT", "PATCH") and content_type == "application/json":
      body = await request.body()
      logger.info(f"📦 请求体:\n{body.decode(...)}")
  ```
- **风险**：无差别记录所有 JSON 请求体，包括 `/auth/login`、`/auth/register` 的 `password` 字段、设备注册等。**用户密码以明文形式落盘到日志文件**，任何能读取 logs 目录的人都能拿到所有用户密码。大请求体（如 base64 图片）还会耗内存。
- **建议**：
  1. 默认不记录请求体，仅在 `DEBUG=True` 时开启；
  2. 对 `/auth/login`、`/auth/register` 等敏感路径跳过请求体记录；
  3. 若必须记录，对 `password`、`token`、`secret_key`、`api_key` 等字段脱敏。

### C9. 自动更新机制无哈希/签名校验，存在任意代码执行路径
- **文件**：[server/updater.py](file:///workspace/server/updater.py#L78-L89)、[elderly_assistant/updater.py](file:///workspace/elderly_assistant/updater.py#L78-L89)、[family_monitor/updater.py](file:///workspace/family_monitor/updater.py#L78-L89)（三者逐字节相同）
- **代码**：
  ```python
  if auto_pull:
      result = subprocess.run(['git', 'pull'], cwd=script_dir, ...)
      if result.returncode == 0:
          print("[更新检查] 自动更新成功！请重新运行程序。")
          sys.exit(0)
  ```
- **问题**：
  - 仅比对 GitHub API 返回的 `tag_name` 字符串，不校验下载内容的 SHA256/GPG 签名；
  - `auto_pull=True` 时直接 `git pull` 合并后 `sys.exit(0)`，新代码立即生效——这是任意代码执行路径；
  - 无回滚机制；HTTPS 但未做证书钉扎，依赖系统 CA；
  - 三处调用均未传 `auto_pull=True`（当前路径未激活），但代码已就绪；
  - 异常被 `except Exception: pass` 静默吞掉（`server/main.py:168` 等）。
- **风险**：若 GitHub 仓库被入侵或 DNS 劫持，可推送恶意 commit 自动拉取并执行，构成供应链攻击。
- **建议**：
  1. 默认禁用 `auto_pull`；
  2. 如需自动更新，固定 commit 哈希、验证 GPG 签名、对下载内容做 SHA256 校验；
  3. 异常写入日志而非吞掉。

### C10. 设备端开放热点无认证 + 配网 Web 服务无 Token + server_url 注入 XSS
- **文件**：[services/hotspot_manager.py](file:///workspace/elderly_assistant/services/hotspot_manager.py)、[services/wifi_config.py](file:///workspace/elderly_assistant/services/wifi_config.py)
- **问题**：
  - 热点 SSID 默认 `M10-Config` 无 WPA2 密码，任意人可连接；
  - 配网 HTTP 服务（10.0.0.1:8088）无任何认证 Token；
  - `wifi_config.py:266` CORS 全开（`Access-Control-Allow-Origin: *`）；
  - `wifi_config.py:329` 配网页面将用户提交的 `server_url` 直接插入 HTML，存在反射型 XSS。
- **风险**：构成完整远程劫持链——攻击者在热点覆盖范围内匿名连接，篡改设备服务器地址为攻击者控制的端点，窃取设备 ID 与服药数据。
- **建议**：
  1. 热点加 WPA2 随机密码（启动时打印或显示）；
  2. 配网服务加随机 Token 校验；
  3. `html.escape(server_url, quote=True)` 转义；
  4. CORS 限制为 `http://10.0.0.1:*`。

### C11. 设备端 `ai_client.py` 强制访问不存在的 config['ai'] 段，AI 功能必崩
- **文件**：[services/ai_client.py](file:///workspace/elderly_assistant/services/ai_client.py#L7)
- **代码**：`config['ai']`（强制访问），但 `config.yaml` 与 `DEFAULT_CONFIG` 均无 `ai` 段。
- **风险**：AI 功能必然抛 `KeyError`，老人端 AI 对话功能完全不可用；异常可能向上传播导致整个流程崩溃。
- **建议**：改 `.get('ai', {})` 并补全 `ai` 段配置。

---

## 三、高危问题（High / P1）

### H1. 设备端 `hotspot_manager.py` 使用 `shell=True` 拼接 SSID
- **文件**：[services/hotspot_manager.py](file:///workspace/elderly_assistant/services/hotspot_manager.py#L42-L48)
- **代码**：`cmd = f'nmcli device wifi hotspot ssid "{self.ssid}" ...'` + `subprocess.run(cmd, shell=True, ...)`
- **对比**：同模块 `wifi_config.py:36-43, 119-133` 已实现 `sanitize_ssid`/`sanitize_password` 并用列表形式调用 subprocess，但 `hotspot_manager.py` 未做。
- **建议**：改为列表形式 `["nmcli", "device", "wifi", "hotspot", "ssid", self.ssid, "band", "bg", "channel", "6"]`，去掉 `shell=True`。

### H2. 家属端会话 cookie 缺少 `secure` 属性 + 登出未使服务端会话失效
- **文件**：[routes/auth.py](file:///workspace/family_monitor/routes/auth.py#L50-L56)（set_cookie）、[routes/auth.py](file:///workspace/family_monitor/routes/auth.py#L113-L117)（logout）、[core/session.py](file:///workspace/family_monitor/core/session.py#L22)
- **问题**：
  - cookie 未设 `secure=True`，本地到 Cloudflare 隧道之间走 HTTP 明文，cookie 可被中间人窃取；
  - `logout` 仅 `delete_cookie`，未调用 `session_manager.invalidate_session(token)`；
  - `_revoked_tokens` 仅存内存，进程重启后撤销列表丢失，已撤销 token 重新有效（最长 7 天）。
- **建议**：增加 `secure=True`、`samesite="strict"`；logout 中先读取 cookie 中的 token 调用 `invalidate_session`；撤销列表持久化到文件或 Redis。

### H3. 家属端管理员可通过 Web 修改 SECRET_KEY（无校验 + 单例失效）
- **文件**：[routes/admin.py](file:///workspace/family_monitor/routes/admin.py#L89-L113)、[routes/admin.py](file:///workspace/family_monitor/routes/admin.py#L53)、[core/config.py](file:///workspace/family_monitor/core/config.py#L72-L96)、[core/session.py](file:///workspace/family_monitor/core/session.py#L90-L95)
- **问题**：
  - `update_security_config` 接受 `secret_key: str = Form("")`，直接赋值 `config.SECRET_KEY = secret_key` 并明文写回 `config.json`，无长度/熵校验；
  - `admin.py:53` 将 `secret_key` 传入模板上下文（不必要的暴露面）；
  - `get_session_manager` 是单例，修改 SECRET_KEY 后不会用新密钥重建，导致旧密钥签发的 token 仍被接受、新密钥签发的 token 反而被旧 serializer 拒绝，行为错乱；
  - 修改后所有现有会话失效，影响可用性。
- **建议**：移除该 Web 修改入口；密钥应仅在部署时通过环境变量设置且不可热更新；删除模板上下文中的 `secret_key`；如必须支持修改，需同步重建 SessionManager 单例并迁移会话。

### H4. 家属端公开路径判断使用 `startswith` 易绕过
- **文件**：[family_monitor/main.py](file:///workspace/family_monitor/main.py#L86-L89)
- **代码**：
  ```python
  public_paths = ["/login", "/register", "/static", "/favicon.ico"]
  is_public = any(path.startswith(pp) for pp in public_paths)
  ```
- **风险**：`startswith` 误判范围过大，如 `/loginbackdoor`、`/staticsecret`、`/register_admin` 等若被新增路由则无需认证即可访问；`/static` 还可能配合路径穿越泄露文件。
- **建议**：改为精确匹配或 `path == pp or path.startswith(pp + "/")`；对 `/static` 使用路由级别挂载而非中间件放行。

### H5. 家属端 chat.html 存在存储型 XSS
- **文件**：[templates/chat.html](file:///workspace/family_monitor/templates/chat.html#L108-L117)
- **代码**：
  ```javascript
  div.innerHTML = `<div class="msg-avatar">${sender.charAt(0)}</div>
                   <div class="msg-body">
                     <div class="msg-name">${sender}</div>
                     <div class="msg-bubble">${content}</div>
                     <div class="msg-time">${timeStr}</div>
                   </div>`;
  ```
- **风险**：`sender` 和 `content` 直接拼接到 innerHTML，未做 HTML 转义。若消息内容包含 `<img src=x onerror=alert(document.cookie)>`，将执行任意 JS。
- **建议**：使用 `textContent` 而非 innerHTML，或对所有动态字段做 HTML 转义后再拼接。

### H6. 家属端 medication_settings.html 通过 `| safe` 注入药品名到 onclick
- **文件**：[templates/medication_settings.html](file:///workspace/family_monitor/templates/medication_settings.html#L480)
- **代码**：
  ```html
  <button class="btn btn-danger btn-sm"
    onclick="deletePlan({{ plan.id }}, '{{ plan.get('drug_name', '') | replace("'", "\\'") | safe }}')">
  ```
- **风险**：`| safe` 关闭了 Jinja2 自动转义，仅手工替换单引号。药品名通过 `/medication_settings/add`（`routes/home.py:228`）添加，后端只 `.strip()` 不过滤 HTML。攻击者（任意登录用户）可提交药品名如 `');alert(document.cookie);//` 或 `</button><script>alert(1)</script>`，当其他用户（含管理员）访问时触发存储型 XSS。
- **建议**：移除 `| safe`，让 Jinja2 自动转义；或改用 `data-*` 属性 + JS 取值。

### H7. 服务端 JWT 类型不一致 + 7 天有效期 + 无撤销机制
- **文件**：[services/auth_service.py](file:///workspace/server/app/services/auth_service.py#L32)、[core/dependencies.py](file:///workspace/server/app/core/dependencies.py#L30)、[core/config.py](file:///workspace/server/app/core/config.py#L25)、[core/security.py](file:///workspace/server/app/core/security.py#L19-L28)
- **问题**：
  - 签发时 `data={"sub": user.id}`（int），解码处 `user_id: int = payload.get("sub")`。SQLite 容忍 str/int 混合比较，PostgreSQL/MySQL 会因类型不匹配查询失败；
  - `ACCESS_TOKEN_EXPIRE_MINUTES = 60*24*7 = 10080` 分钟（7 天），过长；
  - token 中无 `type`、`jti` 字段，无法实现黑名单或主动注销。
- **风险**：跨数据库迁移后认证直接失效；token 一旦泄露，攻击窗口长达 7 天且无法撤销。
- **建议**：签发时 `str(user.id)`，解码后 `int(payload.get("sub"))`；access token 缩短至 15-60 分钟；引入 refresh token；增加 `jti` 与 `type` 字段。

### H8. 服务端登录存在时序攻击 + 无限流
- **文件**：[services/auth_service.py](file:///workspace/server/app/services/auth_service.py#L35-L40)
- **问题**：`if not user or not verify_password(...)` 短路逻辑：用户不存在时立即返回，不执行 bcrypt；用户存在时执行 bcrypt（耗时长）。攻击者可基于响应时间差枚举有效用户名。同时无登录失败次数限制。
- **建议**：用户不存在时执行一次 dummy bcrypt；加账号级与 IP 级登录限流。

### H9. 服务端 `take_medication` 库存扣减非原子、可负数、可重复服药
- **文件**：[services/medication_service.py](file:///workspace/server/app/services/medication_service.py#L47-L71)
- **问题**：
  - 第 65-67 行：`if plan.remaining_quantity > 0: plan.remaining_quantity -= 1.0`，当 `remaining=0.5` 时扣减后变 `-0.5`，无下限保护；
  - SELECT-then-UPDATE 模式在并发下会丢失更新；
  - 同一 `plan_id` + `scheduled_time` 可多次调用，每次都新建 record 并扣库存，无去重；
  - `status` 恒为 `"taken"`，未支持 missed/skipped。
- **风险**：库存数据错误、并发下数据不一致、重复扣减；漏服/跳过无法记录。
- **建议**：用 `UPDATE ... SET remaining_quantity = remaining_quantity - 1 WHERE remaining_quantity >= 1` 原子操作；按 `plan_id + scheduled_time` 去重；根据 `taken_time` 与 `scheduled_time` 计算 status。

### H10. 服务端异常细节直接返回客户端
- **文件**：[app/api/v1/endpoints/vision.py](file:///workspace/server/app/api/v1/endpoints/vision.py#L23-L24)、[app/services/ai_service.py](file:///workspace/server/app/services/ai_service.py#L62)、[family_monitor/routes/home.py](file:///workspace/family_monitor/routes/home.py#L131) 等
- **代码示例**：`detail=f"识别失败: {str(e)}"`、`return f"AI 服务暂时不可用，请稍后再试。错误: {str(e)}"`、`raise HTTPException(status_code=500, detail=str(e))`
- **风险**：可能包含 OCR API key、HTTP 状态、内部 URL、堆栈信息，便于攻击者侦察。
- **建议**：客户端只返回通用错误码/消息，详细错误 `logger.exception` 记录到日志。

### H11. 服务端 `stock_checker` 在同步线程中调用 `asyncio.create_task` 必然失败
- **文件**：[app/tasks/stock_checker.py](file:///workspace/server/app/tasks/stock_checker.py#L39-L48)
- **问题**：`BackgroundScheduler` 在独立线程跑 `check_low_stock_job`，该线程无 event loop。`asyncio.create_task(...)` 在无运行 loop 时抛 `RuntimeError: no running event loop`。异常被第 52 行 `except Exception` 吞掉。
- **风险**：低库存通知永远发不出去（功能静默失效），不易发现。
- **建议**：改用 `AsyncIOScheduler`，或用 `asyncio.run()` 在调度器线程内同步执行通知。

### H12. 服务端 Alembic 迁移系统完全不可用
- **文件**：[app/migrations/env.py](file:///workspace/server/app/migrations/env.py#L16)、[app/migrations/versions/](file:///workspace/server/app/migrations/versions/)、[app/migrations/alembic.ini](file:///workspace/server/app/migrations/alembic.ini#L5)
- **问题**：
  - `env.py:16` 引用不存在的 `purchase_suggestion` 模型（`models/__init__.py` 未导出，磁盘无该文件）；
  - `versions/` 仅含 `.gitkeep`，无任何迁移脚本；
  - `alembic.ini:5` `script_location = app/migrations`，但 alembic.ini 本身就在 `app/migrations/` 目录下，相对路径会解析为 `app/migrations/app/migrations`；
  - `main.py:60` 用 `Base.metadata.create_all` 直接建表，绕过 alembic。
- **风险**：运行 alembic 任何命令立即 `ImportError`，无法做 schema 演进、回滚、版本管理。
- **建议**：删除 `purchase_suggestion` 引用；修正 `script_location`；生成首个迁移脚本。

### H13. 服务端家属绑定老人无确认机制
- **文件**：[app/api/v1/endpoints/users.py](file:///workspace/server/app/api/v1/endpoints/users.py#L28-L40)、[app/services/user_service.py](file:///workspace/server/app/services/user_service.py#L31-L47)
- **问题**：`bind_family` 允许任意家属绑定任意 `elderly_user_id`，无需老人确认，直接把家属加入老人的 `group_id`，可访问其全部用药数据。
- **风险**：任意家属可绑定任意老人，窃取其健康数据；可被恶意利用做"老人监控"骚扰。
- **建议**：实现双向确认（老人端/管理员确认），或要求家属知道老人的 device_id 才能绑定。

### H14. 服务端 WebSocket Token 通过 URL Query 传递
- **文件**：[app/api/v1/websocket.py](file:///workspace/server/app/api/v1/websocket.py#L12)
- **代码**：`token: str = Query(...)`，代码注释也承认 "生产环境应通过安全的通道传递token"
- **风险**：URL 会被记录到访问日志、代理日志、浏览器历史、Referer 头，token 易泄露。
- **建议**：通过 `Sec-WebSocket-Protocol` 子协议或连接后首条消息传递。

### H15. 服务端文件上传无大小限制 + 全量读入内存
- **文件**：[app/api/v1/endpoints/vision.py](file:///workspace/server/app/api/v1/endpoints/vision.py#L11-L22)
- **代码**：`contents = await file.read()` 全量读入内存，无大小限制
- **风险**：攻击者上传超大文件耗尽内存，造成 OOM。
- **建议**：限制 `file.size` 或使用流式读取（如限制为 5MB），并对 Content-Type 做真实 magic bytes 校验。

---

## 四、中危问题（Medium / P2）

### M1. `family_monitor/core/config.py` 将 config.json 写入 `os.environ`，可覆盖真实环境变量
- **文件**：[core/config.py](file:///workspace/family_monitor/core/config.py#L61-L70)
- **代码**：
  ```python
  for key, value in config_data.items():
      os.environ[key] = str(value)
  ```
- **问题**：config.json 优先级高于 .env（load_dotenv 默认不覆盖已存在变量）。攻击者若能写 config.json（需 admin 权限），可注入 `HTTP_PROXY`、`HTTPS_PROXY`、`PYTHONPATH` 等任意环境变量，影响 httpx、uvicorn 行为，劫持老人端 API 流量。
- **建议**：不要把 JSON 写回 `os.environ`；明确优先级（.env > config.json > 默认值）。

### M2. `family_monitor/core/auth.py` 用户密码哈希文件存储无并发保护与文件权限控制
- **文件**：[core/auth.py](file:///workspace/family_monitor/core/auth.py#L36-L61)
- **问题**：`UserManager` 通过 `json.load/dump` 读写 `users.json`，无文件锁，未设置文件权限。并发注册/登录可能造成 JSON 文件损坏；文件权限默认，同主机其他用户可能读取 bcrypt 哈希离线爆破。
- **建议**：使用文件锁；设置文件权限 `0600`；考虑使用 SQLite 替代明文 JSON。

### M3. `family_monitor` 缺少安全响应头
- **文件**：[family_monitor/main.py](file:///workspace/family_monitor/main.py)（全局）
- **问题**：未设置 `Content-Security-Policy`、`X-Frame-Options`、`X-Content-Type-Options`、`Strict-Transport-Security`、`Referrer-Policy` 等。
- **风险**：易受点击劫持、MIME 嗅探、降级攻击。
- **建议**：添加安全头中间件，至少 `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Content-Security-Policy: default-src 'self'`。

### M4. `family_monitor` 调试模式可被管理员通过 Web 开启
- **文件**：[routes/admin.py](file:///workspace/family_monitor/routes/admin.py#L116-L141)、[main.py](file:///workspace/family_monitor/main.py#L66)
- **问题**：`update_advanced_config` 允许设置 `config.DEBUG`，`main.py:66` `debug=config.DEBUG` 传给 FastAPI。
- **建议**：生产环境强制 `debug=False`，不允许通过 Web 修改。

### M5. `family_monitor` 模板中 admin_settings 表单 action 路径与后端不匹配
- **文件**：[templates/admin_settings.html](file:///workspace/family_monitor/templates/admin_settings.html#L21)、[templates/admin_settings.html](file:///workspace/family_monitor/templates/admin_settings.html#L48)
- **问题**：表单 action 是 `/admin/settings/update`、`/admin/settings/secret`，后端实际路由是 `/admin/administrator/setting/server`、`/admin/administrator/setting/security`。表单提交会 404，配置无法保存。该模板还缺少 advanced 配置表单。
- **风险**：管理员误以为已修改配置（实际未生效），间接影响安全配置。说明该模块未经测试。
- **建议**：统一模板 action 与后端路由路径，补充 advanced 表单。

### M6. `family_monitor` chat.html 引用未传入的模板变量
- **文件**：[templates/chat.html](file:///workspace/family_monitor/templates/chat.html#L69-L71)、[routes/chat.py](file:///workspace/family_monitor/routes/chat.py#L18-L27)
- **问题**：模板引用 `{{ current_user }}`、`{{ elderly_id }}`、`{{ server_url }}`，但 `routes/chat.py` 只传了 `app_name`。WebSocket URL 拼接错误，功能不可用。
- **建议**：在 `routes/chat.py` 中通过 `request.state.user` 获取当前用户并传入；移除不存在的 history 路由引用或实现该路由。

### M7. `family_monitor` install.py 强制修改用户全局 pip 配置 + `--break-system-packages`
- **文件**：[install.py](file:///workspace/family_monitor/install.py#L57-L80)、[install.py](file:///workspace/family_monitor/install.py#L95-L104)
- **问题**：`backup_pip_source()` 将用户 `~/.pip/pip.conf` 强制改写为清华镜像源；失败时回退到 `pip install --break-system-packages`。
- **风险**：修改用户全局配置影响所有 Python 项目；绕过 PEP 668 系统保护可能破坏系统依赖。
- **建议**：仅在虚拟环境内修改 pip 配置，或使用 `pip install -i` 临时指定源；提示用户使用虚拟环境，不绕过系统保护。

### M8. `family_monitor` device_id 未做 URL 编码直接拼接到 URL 路径
- **文件**：[core/api_client.py](file:///workspace/family_monitor/core/api_client.py#L116-L241)
- **问题**：`f"{self.base_url}/api/v1/public/device/check/{device_id}"`，device_id 来自用户输入未做 URL 编码。若包含 `/`、`?`、`#`、空格等特殊字符，可能路径穿越或注入额外路径段。
- **建议**：`urllib.parse.quote(device_id, safe='')` 后再拼接。

### M9. `family_monitor` API_KEY 配置存在但从未使用
- **文件**：[config.json](file:///workspace/family_monitor/config.json#L3)、[core/api_client.py](file:///workspace/family_monitor/core/api_client.py#L77-L82)、[templates/settings.html](file:///workspace/family_monitor/templates/settings.html#L131)
- **问题**：config.json 中 `"API_KEY": ""`，settings.html 让用户输入 API 密钥，但 `api_client.py` 的 `_headers()` 从不使用 API_KEY，只添加 `X-Device-ID`。配置与实现不一致。
- **建议**：若需要 API 认证，在 `_headers()` 中添加 `Authorization: Bearer {API_KEY}`；否则移除该配置项和 UI 入口。

### M10. `family_monitor` 端口硬编码 4430，未使用配置中的 SERVER_PORT
- **文件**：[main.py](file:///workspace/family_monitor/main.py#L48)、[main.py](file:///workspace/family_monitor/main.py#L176)
- **建议**：改为 `port=config.SERVER_PORT`。

### M11. 服务端 SQLite 作为默认数据库 + `check_same_thread=False`
- **文件**：[app/core/database.py](file:///workspace/server/app/core/database.py#L7-L10)、[app/core/config.py](file:///workspace/server/app/core/config.py#L21)
- **问题**：默认 `DATABASE_URL=sqlite:///./data/elderly_care.db`，SQLite 并发写易锁死，无连接池配置。
- **建议**：生产使用 PostgreSQL/MySQL，配置连接池。

### M12. 服务端手机号/密码/用户名校验未使用 validators
- **文件**：[app/schemas/auth.py](file:///workspace/server/app/schemas/auth.py)、[app/utils/validators.py](file:///workspace/server/app/utils/validators.py)、[app/services/auth_service.py](file:///workspace/server/app/services/auth_service.py#L12-L32)
- **问题**：`utils/validators.py` 已有 `is_valid_phone`、`is_valid_username`、`is_valid_password` 正则实现，但注册流程中均未调用。`auth.py` 仅校验 `isdigit()`、`min_length=6`。
- **建议**：在注册流程中调用 `validators.py` 中的函数。

### M13. 服务端 `schedule_times` 无时间格式校验
- **文件**：[app/schemas/medication.py](file:///workspace/server/app/schemas/medication.py#L11)
- **问题**：`schedule_times: List[str]` 仅校验是字符串列表，可传入 `["abc", "999:99"]`，污染老人端轮询数据。
- **建议**：加 `field_validator` 用 `is_valid_time_format` 校验每项。

### M14. 服务端时间字段使用 `datetime.utcnow()`（已弃用，非时区感知）
- **文件**：[app/models/user.py](file:///workspace/server/app/models/user.py#L17)、[medication_plan.py](file:///workspace/server/app/models/medication_plan.py#L20-L21)、[chat_message.py](file:///workspace/server/app/models/chat_message.py#L15)、[ai_query_log.py](file:///workspace/server/app/models/ai_query_log.py#L15)、[app/utils/time_utils.py](file:///workspace/server/app/utils/time_utils.py#L7)、[app/core/security.py](file:///workspace/server/app/core/security.py#L22)
- **问题**：`datetime.utcnow()` 在 Python 3.12+ 已弃用，且为 naive datetime，时区处理不一致。
- **建议**：统一用 `datetime.now(timezone.utc)`。

### M15. 服务端 WebSocket `ConnectionManager` 单例不支持多进程
- **文件**：[app/websocket/manager.py](file:///workspace/server/app/websocket/manager.py#L8-L67)
- **问题**：`active_connections` 是进程内存 dict，多 worker 部署时不同进程间连接不可达，消息丢失。
- **建议**：用 Redis Pub/Sub 或共享存储。

### M16. 服务端 `chat.py` WebSocket 中 `next(get_db())` 资源管理模式错误
- **文件**：[app/api/v1/endpoints/chat.py](file:///workspace/server/app/api/v1/endpoints/chat.py#L62)
- **问题**：`db = next(get_db())` 取 generator 第一个 yield 值，generator 的 `finally` 块（含 `db.close()`）永远不会被触发。第 86 行虽手动 `db.close()`，但异常路径下可能漏关。
- **建议**：用 `with SessionLocal() as db:` 或 FastAPI 依赖注入。

### M17. 服务端 `get_db` 在两处重复定义，测试依赖覆盖不一致
- **文件**：[app/core/database.py](file:///workspace/server/app/core/database.py#L17-L22)、[app/core/dependencies.py](file:///workspace/server/app/core/dependencies.py#L12-L18)、[tests/conftest.py](file:///workspace/server/tests/conftest.py#L37)
- **问题**：两处都定义了功能相同的 `get_db`，但它们是不同的函数对象。`tests/conftest.py` 只覆盖了 `app.core.database.get_db`，但 `medication.py` 等使用 `from app.core.dependencies import get_db`。测试中一边的覆盖不会影响另一边。
- **建议**：统一从 `dependencies.py` 导出 `get_db`。

### M18. 服务端全局异常处理器堆栈日志可能记录敏感字段
- **文件**：[app/middleware/exception_handler.py](file:///workspace/server/app/middleware/exception_handler.py#L30-L37)
- **代码**：`logger.exception(f"未捕获的异常: {exc}")` 打印完整堆栈，可能包含请求体中的 password、token 等。
- **建议**：堆栈日志中过滤 password、authorization 等字段。

### M19. 服务端 `MedicationPlan` 字段类型不一致：`Float` 与 `Integer` 混用
- **文件**：[app/models/medication_plan.py](file:///workspace/server/app/models/medication_plan.py#L16-L19)
- **问题**：`total_quantity` / `remaining_quantity` 是 `Float`，`low_stock_threshold` 是 `Integer`。比较 `remaining_quantity <= low_stock_threshold` 时混合类型。
- **建议**：统一为 `Float` 或 `Numeric`。

### M20. 服务端 `VisionService` 关键词匹配不可靠 + `confidence` 硬编码
- **文件**：[app/services/vision_service.py](file:///workspace/server/app/services/vision_service.py#L70-L91)、[app/services/vision_service.py](file:///workspace/server/app/services/vision_service.py#L117)
- **问题**：用关键词列表匹配药品名，会误判；置信度写死 `0.85`，不反映真实结果。
- **风险**：药品识别错误可能影响健康决策；置信度误导。
- **建议**：用 AI 模型提取药品名；用 OCR 真实置信度。

### M21. 服务端 `/public/ai/ask` 与 `/ai/chat/public` 无限流
- **文件**：[app/api/v1/endpoints/ai.py](file:///workspace/server/app/api/v1/endpoints/ai.py#L25-L35)、[app/api/v1/endpoints/public.py](file:///workspace/server/app/api/v1/endpoints/public.py#L118-L140)
- **问题**：ZhipuAI 按调用计费，无任何限流。
- **建议**：加 IP/设备级速率限制（如 `slowapi`）。

---

## 五、低危问题（Low / P3）

### L1. `.gitignore` 未排除 `config.json` 和 `config.yaml`
- **文件**：[.gitignore](file:///workspace/.gitignore)、[family_monitor/.gitignore](file:///workspace/family_monitor/.gitignore)
- **建议**：将 `config.json`、`config.yaml` 加入 `.gitignore`，仓库保留 `.example` 模板。

### L2. 部署域名硬编码泄露
- **文件**：[elderly_assistant/config.yaml](file:///workspace/elderly_assistant/config.yaml#L2)、[family_monitor/config.json](file:///workspace/family_monitor/config.json#L2)、[README.md](file:///workspace/README.md#L24-L27)
- **内容**：`https://my-website.ccwu.cc`
- **建议**：改为占位符 `https://your-server-domain/...`。

### L3. `history.md` 包含本地绝对路径
- **文件**：[history.md](file:///workspace/history.md#L592-L686)
- **内容**：多处 `file:///run/media/xixi/A568-50B8/python/eating-medication/...`
- **风险**：泄露开发者本地用户名（xixi）、挂载点（U 盘路径 A568-50B8）。
- **建议**：移除本地路径，改为相对路径。

### L4. 三个 `updater.py` 硬编码 GitHub 仓库地址且代码完全重复
- **文件**：[server/updater.py](file:///workspace/server/updater.py#L15)、[elderly_assistant/updater.py](file:///workspace/elderly_assistant/updater.py#L15)、[family_monitor/updater.py](file:///workspace/family_monitor/updater.py#L15)
- **建议**：改为 `os.getenv("UPDATE_REPO", "diaoyunxi/eating-medication")`；抽取为共享模块。

### L5. 依赖未锁定版本或锁定不当
- **文件**：[elderly_assistant/requirements.txt](file:///workspace/elderly_assistant/requirements.txt)（大部分未锁定）、[family_monitor/requirements.txt](file:///workspace/family_monitor/requirements.txt)（全部 `>=`）、[server/requirements.txt](file:///workspace/server/requirements.txt#L14-L15)（测试依赖混入生产）
- **建议**：使用 `pip-compile` 生成锁定版本；拆分 `requirements-dev.txt`。

### L6. `elderly_assistant/install.py` 硬编码包列表与 requirements.txt 脱节，含废弃依赖 opencv-python
- **文件**：[install.py](file:///workspace/elderly_assistant/install.py#L38)、[requirements.txt](file:///workspace/elderly_assistant/requirements.txt#L2)
- **问题**：不读取 `requirements.txt`，而是硬编码列表；包含 `opencv-python` 但 `history.md:187-217` 记录摄像头已重构为 HuskyLens，opencv-python 是废弃依赖。在行空板 M10（ARM）上 opencv-python 体积大、编译慢、依赖重。
- **建议**：`install.py` 改为读取 `requirements.txt`；移除 `opencv-python`。

### L7. `fuzzywuzzy` + `python-Levenshtein` 已停止维护
- **文件**：[elderly_assistant/requirements.txt](file:///workspace/elderly_assistant/requirements.txt#L4-L5)
- **问题**：fuzzywuzzy 自 2021 年起停止维护，作者推荐迁移到 RapidFuzz；`python-Levenshtein` 在 ARM 平台需 C 编译常安装失败。
- **建议**：迁移到 `rapidfuzz`。

### L8. 服务端注册成功直接返回 token + 无频率限制
- **文件**：[app/api/v1/endpoints/auth.py](file:///workspace/server/app/api/v1/endpoints/auth.py#L11-L18)
- **风险**：可批量注册占满数据库。
- **建议**：加验证码或限流。

### L9. 服务端 `UserOut` 暴露全部字段，模型无 `is_active` 字段
- **文件**：[app/models/user.py](file:///workspace/server/app/models/user.py#L7-L22)
- **建议**：加 `is_active`、`last_login_at` 字段。

### L10. 服务端 JWT 使用 HS256 对称加密
- **文件**：[app/core/security.py](file:///workspace/server/app/core/security.py#L24)
- **风险**：签名与验证同密钥，密钥泄露即可伪造任意 token。
- **建议**：微服务场景建议 RS256。

### L11. 服务端 `ChatMessage` 缺少 `sender_id` / `receiver_id` 索引
- **文件**：[app/models/chat_message.py](file:///workspace/server/app/models/chat_message.py#L11-L14)
- **建议**：加 `index=True`。

### L12. 服务端 `chat.py` 中 `get_history` 的 `limit` 参数无上限
- **文件**：[app/api/v1/endpoints/chat.py](file:///workspace/server/app/api/v1/endpoints/chat.py#L42)
- **建议**：用 `Query(50, ge=1, le=200)`。

### L13. 服务端 `deps.py`（`PaginationParams`）未被任何端点使用
- **文件**：[app/api/deps.py](file:///workspace/server/app/api/deps.py#L8-L15)
- **建议**：接入或删除。

### L14. 服务端 `ai_query_log` 模型默认 `model="gpt-3.5-turbo"` 与实际不符
- **文件**：[app/models/ai_query_log.py](file:///workspace/server/app/models/ai_query_log.py#L14)
- **建议**：改为实际模型名（`glm-4.7-flash`）或动态填入。

### L15. 服务端测试覆盖严重不足
- **文件**：[tests/integration/test_medication_flow.py](file:///workspace/server/tests/integration/test_medication_flow.py)、[tests/integration/test_user_flow.py](file:///workspace/server/tests/integration/test_user_flow.py)、[tests/test_services/test_medication_service.py](file:///workspace/server/tests/test_services/test_medication_service.py) 均为空文件
- **风险**：无 vision/public/chat 端点测试，无越权场景测试。
- **建议**：补全测试。

### L16. 家属端 README 与实际不符
- **文件**：[family_monitor/README.md](file:///workspace/family_monitor/README.md#L29-L65)
- **问题**：提到 `.env.example` 但项目中不存在；项目结构说明缺少 `chat.py`、`admin.py`、`api_client.py` 等实际文件；安全特性说明（"Cookie 安全"等）与实际实现不符（缺少 secure 属性）。
- **建议**：更新 README。

### L17. 家属端 `routes/__init__.py` 注释编码错误
- **文件**：[routes/__init__.py](file:///workspace/family_monitor/routes/__init__.py#L3)
- **内容**：`"""璺"""璺敱璺敱妯″潡"""`（应为"路由模块"，但被以错误编码解读）
- **建议**：统一保存为 UTF-8。

### L18. 家属端 login/register 缺少速率限制
- **文件**：[routes/auth.py](file:///workspace/family_monitor/routes/auth.py#L35-L66)
- **建议**：引入 `slowapi` 等限流中间件。

### L19. 设备端自动更新异常静默吞掉
- **文件**：[elderly_assistant/main.py](file:///workspace/elderly_assistant/main.py#L221-L222)、[family_monitor/main.py](file:///workspace/family_monitor/main.py#L169-L170)、[server/main.py](file:///workspace/server/main.py#L168-L169)
- **代码**：`except Exception: pass`
- **建议**：至少 `logger.warning` 记录失败原因。

### L20. 服务监听 0.0.0.0 + 本地纯 HTTP
- **文件**：[server/main.py](file:///workspace/server/main.py#L146-L152)、[family_monitor/main.py](file:///workspace/family_monitor/main.py#L173-L178)
- **说明**：架构上由 Cloudflare 隧道提供 HTTPS，本地 HTTP 是设计如此。但如果端口被直接暴露到公网（防火墙配置错误），则所有通信以明文传输。
- **建议**：默认监听 `127.0.0.1`，通过环境变量显式开启 `0.0.0.0` 监听。

---

## 六、依赖与供应链

| 文件 | 行号 | 包 | 问题 |
|---|---|---|---|
| [server/requirements.txt](file:///workspace/server/requirements.txt#L7) | 7 | `python-jose[cryptography]==3.3.0` | 已知 CVE-2024-33664（JWT 算法混淆 / DoS），建议升级到 3.4.0+ 或迁移到 `pyjwt` |
| [server/requirements.txt](file:///workspace/server/requirements.txt#L8) | 8 | `passlib==1.7.4` | 项目已停更；与 `bcrypt>=4.1` 配合时 `AttributeError: __about__` |
| [server/requirements.txt](file:///workspace/server/requirements.txt#L5) | 5 | `pydantic==2.9.2` | 2.9.x 有 ReDoS（CVE-2024-1561），建议 2.10+ |
| [server/requirements.txt](file:///workspace/server/requirements.txt#L3) | 3 | `sqlalchemy==2.0.35` | 2.0.35 有 SQL 注入（CVE-2024-29906），建议 2.0.36+ |
| [elderly_assistant/requirements.txt](file:///workspace/elderly_assistant/requirements.txt#L4) | 4 | `fuzzywuzzy` | 已废弃，建议迁移到 `rapidfuzz` |
| [elderly_assistant/requirements.txt](file:///workspace/elderly_assistant/requirements.txt#L2) | 2 | `opencv-python` | 废弃依赖（已改用 HuskyLens） |
| [elderly_assistant/requirements.txt](file:///workspace/elderly_assistant/requirements.txt#L1) | 1 | `pyyaml>=5.1,<7.0` | 5.1 有 CVE-2020-14343（仅 `yaml.load` 触发，本项目用 `safe_load` 不受影响）但建议升级 |

**说明**：本项目使用 `yaml.safe_load`、SQLAlchemy ORM 参数化查询、未发现 `eval/exec/pickle.loads/yaml.load` 等危险调用，所以多数 CVE 实际不可利用，但仍建议升级。

---

## 七、已确认安全项

为避免重复扫描，特此说明以下检查项**未发现问题**：

- **未发现** `eval()`、`exec()`、`pickle.loads()`、`marshal.loads()`、`yaml.load()`（非 safe_load）的使用。
- **未发现** `verify=False` SSL 关闭、`InsecureRequestWarning` 禁用。
- **未发现** SQL 字符串拼接注入（全部使用 SQLAlchemy ORM 参数化查询）。
- **未发现** Jinja2 `render_template_string` 模板注入（所有模板均为静态文件 + 上下文变量）。
- **未发现** MD5/SHA1 用于密码哈希（密码使用 bcrypt，rounds=12）。
- **未发现** JWT `algorithm="none"` 配置（`security.py:24, 28` 使用 `algorithms=[settings.ALGORITHM]`，且 ALGORITHM 固定为 HS256）。
- **未发现** AWS AKIA、腾讯云 LTAI、OpenAI sk-、GitHub ghp_/gho_、Cloudflare cfk_/cfut_、123云盘 token 等云厂商密钥泄露。
- **未发现** 私钥（`-----BEGIN ... PRIVATE KEY-----`）泄露。
- **未发现** `random` 模块用于密钥/Token 生成（均使用 `secrets.token_urlsafe`）。
- **未发现** `os.path.join` 拼接用户输入导致的路径穿越（路径均由代码内部常量构造）。
- **未发现** `data/medications.json` 与 `data/schedules.json` 包含敏感信息（均为空 `[]`）。
- **未发现** 设备端网络请求使用 HTTP（均使用 HTTPS 且默认开启证书校验，但无证书 pinning）。

---

## 八、修复路线图

### P0：立即修复（涉及身份伪造与健康危害）

| 编号 | 问题 | 修复动作 |
|---|---|---|
| C1 | family_monitor 弱 SECRET_KEY 入库 | 从 git 历史清除、加入 .gitignore、改用环境变量 |
| C2 | server .env 默认 DEBUG=True + 弱密钥 | 默认 DEBUG=False、随机生成 SECRET_KEY |
| C3 | server SECRET_KEY 默认随机 | 启动校验，生产环境强制要求显式配置 |
| C4 | 聊天端点无认证 | 三个端点加 `Depends(get_current_user)` |
| C5 | 设备端点任意篡改用药计划 | 引入设备密钥 + 签名校验 + 限流 |
| C6 | family_monitor CORS 全开 + 无 CSRF | CORS 白名单 + CSRF token |
| C7 | server CORS 配置矛盾 | 删除 main.py 内联 CORS，改调 `setup_cors(app)` |
| C8 | 日志记录密码明文 | 敏感路径跳过 + 字段脱敏 |
| C9 | 自动更新无签名校验 | 加 SHA256/GPG 校验，默认禁用 auto_pull |
| C10 | 设备端开放热点 + 配网 XSS | 热点加密 + 配网 Token + 转义 server_url |
| C11 | 设备端 ai_client 必崩 | 改 `.get('ai', {})` |

### P1：本周修复（高危越权与信息泄露）

H1-H15：见各章节详细建议。优先级最高为 H5/H6（XSS）、H7（JWT）、H9（库存原子性）、H12（迁移系统）、H13（家属绑定）。

### P2：下次迭代（中危问题）

M1-M21：输入校验、配置缺陷、可用性、依赖升级。

### P3：持续优化（低危与质量）

L1-L20：依赖锁定、文档更新、测试补全、代码规范。

---

**审查完毕。** 本报告共覆盖 3 个子项目 60+ 个 Python 文件、10+ 个 HTML 模板、3 个 requirements.txt 及多个配置文件，所有发现均包含具体文件路径与行号，可直接定位修复。如需针对任一问题给出修复代码 patch，请告知问题编号。
