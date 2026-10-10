# 代码审查报告

**仓库：** [diaoyunxi/eating-medication](https://github.com/diaoyunxi/eating-medication)
**审查日期：** 2026-09-18
**审查范围：** 全仓库 Python 源码（约 50,436 行）、配置文件、项目结构
**审查工具：** ruff 0.16.8、人工审查

---

## 一、仓库概况

| 维度 | 描述 |
|------|------|
| 项目定位 | 面向独居老人的智能用药管理系统 |
| 架构 | 三端架构：老人端（行空板 M10）+ 服务端（FastAPI）+ 家属看护端（FastAPI Web） |
| 技术栈 | Python / FastAPI / SQLAlchemy / WebSocket / Cloudflare Tunnel / SQLite/MySQL/PostgreSQL |
| 代码量 | ~50,436 行（含测试），Python 源文件 ~160 个 |
| CI/CD | GitHub Actions（CodeQL + pytest + 自动发布） |
| 现有 PR | 30 个 OPEN 状态的 PR（#73–#102），已覆盖大量 ruff 规则修复与安全改进 |

---

## 二、审查维度与结论

| 维度 | 评级 | 说明 |
|------|------|------|
| **代码质量** | B+ | 整体代码质量较高，注释详尽、文档齐全，但存在 ruff 报告的 1,447 项风格/规范问题 |
| **安全性** | B | 核心认证/加密逻辑设计合理，但发现 JWT token 类型未校验（Critical）和邮箱验证码暴力破解（High）等新问题 |
| **潜在缺陷** | B+ | 大部分逻辑健壮，少数内存泄漏和边界条件需修复 |
| **项目结构** | A- | 三端分离、模块职责清晰，common 层抽象合理 |
| **文档完整性** | A | README 详尽，各模块均有独立 README，代码注释充分 |

---

## 三、问题列表（按严重程度分级）

### 🔴 Critical（严重）

#### C-1：JWT Token 类型未校验，任意令牌可冒充 Access Token

- **文件：** `server/app/core/dependencies.py`（`get_current_user`、`get_current_user_optional`）
- **文件：** `server/app/api/v1/endpoints/chat.py`（`ws_chat` WebSocket 认证）
- **描述：** `decode_token()` 解码 JWT 后仅检查 `sub` 字段存在性，未校验 `type` 字段是否为 `"access"`。系统中签发了多种类型的短期令牌（`mfa`、`oauth_state`、`oauth_pending`、`webauthn_challenge`），它们都通过 `decode_token()` 解码且 `sub` 字段格式一致。攻击者可截获任意短期令牌（如 5 分钟有效的 MFA 令牌），将其作为 Access Token 使用，获得完整 API 访问权限。
- **影响：** 认证绕过，短期令牌可被滥用为长期 Access Token
- **修复方案：** 在 `get_current_user` 和 `get_current_user_optional` 中添加 `payload.get("type") == "access"` 校验；WebSocket 认证同理。

---

### 🟠 High（高）

#### H-1：邮箱验证码无尝试次数限制，存在暴力破解风险

- **文件：** `server/app/utils/email_code.py`（`verify_code`）
- **描述：** 验证码为 6 位数字（100 万种组合），有效期 5 分钟。`verify_code()` 仅校验匹配性，不限制尝试次数。攻击者可在 5 分钟内暴力穷举全部组合（约 3,333 次/秒），成功概率极高。
- **影响：** 账号接管（通过邮箱验证码登录/自动注册）
- **修复方案：** 为每个邮箱添加尝试次数计数器，超过 5 次错误即失效并清除验证码。

#### H-2：速率限制中间件内存泄漏

- **文件：** `server/app/middleware/rate_limit.py`
- **描述：** `_store` 是一个 `defaultdict(lambda: defaultdict(deque))`，每个新的 IP+路径组合都会创建条目。虽然 deque 内的过期时间戳会被弹出，但空的 deque 和外层 dict 键永远不会被清理，导致长期运行后内存持续增长。
- **影响：** 长期运行的生产环境中内存持续膨胀
- **修复方案：** 在清理过期条目后，若 deque 为空则从 dict 中删除该键；定期清理空的外层键。

---

### 🟡 Medium（中）

#### M-1：53 处未使用的导入（F401）

- **描述：** ruff 检测到 53 处 `imported but unused` 警告，增加包体积和启动时间，降低代码可读性。
- **影响：** 代码整洁度、维护成本
- **修复方案：** 移除所有未使用的导入。

#### M-2：User.email 字段缺少数据库索引

- **文件：** `server/app/models/user.py`
- **描述：** `User.email` 被用于登录查询（`db.query(User).filter(User.email == email)`）和 OAuth 绑定查询，但该字段未添加 `index=True`。当用户量增长时，邮箱查询会退化为全表扫描。
- **影响：** 登录/OAuth 性能退化
- **修复方案：** 为 `email` 字段添加 `index=True`。

#### M-3：MedicationRecord 缺少 plan_id + scheduled_time 复合索引

- **文件：** `server/app/models/medication_record.py`
- **描述：** `take_medication()` 和 `check_missed_medication_job()` 频繁按 `plan_id + scheduled_time` 组合查询服药记录，但缺少复合索引。
- **影响：** 服药记录和漏服检查性能退化
- **修复方案：** 添加 `Index('ix_medication_record_plan_sched', 'plan_id', 'scheduled_time')`。

#### M-4：13 处无占位符的 f-string（F541）

- **描述：** 代码中存在 13 处 `f"..."` 字符串但内部无 `{}` 占位符，属于误用。
- **影响：** 代码整洁度、微小性能开销
- **修复方案：** 去除多余的 `f` 前缀。

---

### 🟢 Low（低）

#### L-1：8 处未使用的局部变量（F841）

- **描述：** ruff 检测到 8 处局部变量赋值后从未被读取。
- **影响：** 代码整洁度

#### L-2：123 处导入排序问题（I001）

- **描述：** ruff 检测到大量导入块未按 isort 规则排序。
- **影响：** 代码一致性

#### L-3：16 处模块级导入不在文件顶部（E402）

- **描述：** 部分模块级 import 语句位于函数定义或条件判断之后。
- **影响：** 代码可读性

---

## 四、改进建议

### 短期优先（本报告修复范围）
1. ✅ 修复 JWT token 类型校验（C-1）
2. ✅ 修复邮箱验证码暴力破解（H-1）
3. ✅ 修复速率限制中间件内存泄漏（H-2）
4. ✅ 清理未使用的导入（M-1）
5. ✅ 添加数据库索引（M-2、M-3）
6. ✅ 清理无占位符的 f-string（M-4）

### 中期建议
- 将限流存储从进程内存迁移到 Redis，支持多 worker / 多实例部署
- 为验证码存储和邮箱发送增加 Redis 持久化，支持多进程共享
- 引入 `pyproject.toml` 统一管理 ruff/pytest/coverage 配置（PR #93 已提出）

### 长期建议
- 将 JWT 算法从 HS256 升级为 RS256（非对称加密），支持微服务场景
- 引入结构化日志（JSON 格式），便于日志采集和分析
- 添加 API 版本管理策略文档

---

*报告生成工具：ruff 0.16.8 + 人工审查*
*审查者：Code Review Bot*
