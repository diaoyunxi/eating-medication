# Security Advisory - Dependency CVE Notice

**Date:** 2026-10-12  
**Severity:** High

## Affected Dependencies

| Package | Current Version | CVE ID | Fix Version |
|---------|----------------|--------|-------------|
| python-jose | 3.5.0 | CVE-2026-85394 | None available |
| ecdsa | 0.19.2 | PYSEC-2026-1325 | None available |

## Details

### python-jose (CVE-2026-85394)

python-jose 3.5.0（当前最新版本）存在已知安全漏洞 CVE-2026-85394。该库维护活跃度降低，尚未发布修复版本。

**风险等级：** 高  
**影响范围：** JWT token 签名与验证

**缓解建议：**
1. 中期：迁移至 [PyJWT](https://github.com/jpadilla/pyjwt)（`pip install PyJWT[crypto]`）或 [authlib](https://github.com/lepture/authlib)
2. 短期：确保 JWT secret 足够长（≥256 位），限制 token 有效期

### ecdsa (PYSEC-2026-1325)

ecdsa 0.19.2（当前最新版本）存在已知安全漏洞 PYSEC-2026-1325。该库为 python-jose 的间接依赖。

**风险等级：** 中  
**影响范围：** ECDSA 签名操作

**缓解建议：**
1. 监控 ecdsa 上游发布修复版本后及时升级
2. 迁移至 cryptography 库的 ECDSA 实现

## Monitoring

- 定期运行 `pip-audit -r requirements.txt` 检查新漏洞
- 关注 python-jose 和 ecdsa 的 GitHub 仓库安全公告
