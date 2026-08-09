# feat: 邮箱验证码登录支持 TOTP 第二因子认证

## 变更内容

- auth_service.py: login_or_register_by_email() 在用户已开启 TOTP 时返回 MFA 令牌
- auth_service.py: get_login_methods() 添加 TOTP 绑定状态条目
- routes/auth.py: 邮箱验证码登录端点处理 MFA 响应
- login.html: 邮箱登录流程添加 TOTP 第二因子步骤
- settings.html: 登录方式管理添加 TOTP 绑定条目和弹窗
- openapi.json: 重新生成 API 文档

## TOTP 支持情况

| 登录方式 | TOTP 第二因子 |
|---------|--------------|
| 手机密码登录 | 已支持 |
| 邮箱验证码登录 | 现已支持 |
| GitHub OAuth | 不支持 |
| Gitee OAuth | 不支持 |

## 登录流程

- 手机密码登录：密码 → TOTP 动态码 → JWT
- 邮箱验证码登录：验证码 → TOTP 动态码 → JWT（已开启 TOTP 时）
- 设置页绑定：点击"绑定" → 扫码/输入密钥 → 输入动态码验证 → 启用
