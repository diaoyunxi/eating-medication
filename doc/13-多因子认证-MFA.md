> [← 返回文档目录](../README.md) ｜ 本分册由 `README.md` 的「多因子认证（MFA）」章节拆分而来。

## 多因子认证（MFA）

服务端已内置双因子认证，登录与敏感操作需二次验证：

- **TOTP**：基于时间的一次性密码（`pyotp`），绑定二维码以 SVG 渲染（`qrcode`，无需 Pillow）。
- **WebAuthn / Passkey**：基于 `webauthn` 库的生物识别 / 硬件密钥登记与断言校验。
- **登录限流与弱密钥防护**：生产环境弱 `SECRET_KEY` 拒绝启动（`server/app/core/config.py` 维护 `_WEAK_SECRET_KEYS` 黑名单）；JWT 解码固定算法白名单，防 `alg=none` 降级。
- **设备令牌时序安全比较**：`server/app/services/device_service.py` 使用 `secrets.compare_digest` 比较设备令牌，防时序侧信道。

> 家庭成员（family 角色）可在账户设置中绑定 TOTP 与 Passkey；老人端（elderly）由家属代为管理。

---
