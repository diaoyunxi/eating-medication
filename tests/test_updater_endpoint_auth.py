# -*- coding: utf-8 -*-
"""server updater 端点鉴权回归测试。

守护 /api/v1/updater POST 的 X-Update-Token 校验：
- 未配置 UPDATE_TOKEN 时拒绝触发（403）
- 令牌不匹配时拒绝触发（403）
- 令牌匹配时正常触发 check_for_update(auto_pull=True)
- GET 保持只读（auto_pull=False，不下载不安装）
"""
import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("SECRET_KEY", "unit-test-secret-key-not-for-production-0123456789")
os.environ.setdefault("DEBUG", "true")

try:
    from fastapi import HTTPException
    from app.api.v1.endpoints.updater import updater_status, updater_trigger
    _HAVE = True
except Exception:  # pragma: no cover
    _HAVE = False


@unittest.skipUnless(_HAVE, "需要 app 环境（当前环境未安装依赖）")
class UpdaterEndpointAuthTest(unittest.TestCase):
    def test_missing_token_config_rejected(self):
        with mock.patch("app.api.v1.endpoints.updater._load_update_token", return_value=None), \
             mock.patch("app.api.v1.endpoints.updater.check_for_update") as m_check:
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(updater_trigger(x_update_token="anything"))
            self.assertEqual(ctx.exception.status_code, 403)
            m_check.assert_not_called()

    def test_wrong_token_rejected(self):
        with mock.patch("app.api.v1.endpoints.updater._load_update_token", return_value="secret-token"), \
             mock.patch("app.api.v1.endpoints.updater.check_for_update") as m_check:
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(updater_trigger(x_update_token="wrong-token"))
            self.assertEqual(ctx.exception.status_code, 403)
            m_check.assert_not_called()

    def test_correct_token_triggers_update(self):
        with mock.patch("app.api.v1.endpoints.updater._load_update_token", return_value="secret-token"), \
             mock.patch("app.api.v1.endpoints.updater.check_for_update") as m_check:
            m_check.return_value = {"update_available": False}
            result = asyncio.run(updater_trigger(x_update_token="secret-token"))
            self.assertEqual(result, {"update_available": False})
            m_check.assert_called_once_with(auto_pull=True)

    def test_get_is_readonly(self):
        # GET 只读检查：auto_pull=False，不下载不安装
        with mock.patch("app.api.v1.endpoints.updater.check_for_update") as m_check:
            m_check.return_value = {"update_available": True}
            result = asyncio.run(updater_status())
            self.assertEqual(result, {"update_available": True})
            m_check.assert_called_once_with(auto_pull=False)


if __name__ == "__main__":
    unittest.main()
