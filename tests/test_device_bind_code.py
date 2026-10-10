# -*- coding: utf-8 -*-
"""设备绑定码（所有权证明）回归测试。

守护 bind_device 的绑定码校验：
- 设备已上报绑定码时，家属必须提供与屏幕一致的绑定码，否则拒绝；
- 未提供/错误绑定码分别返回 400/403；
- 设备未上报绑定码（旧设备）时拒绝绑定并提示升级。
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
    from app.api.v1.endpoints.family_device import FamilyBindReq, bind_device
    from app.services.device_service import DeviceService
    _HAVE = True
except Exception:  # pragma: no cover
    _HAVE = False


class _FakeUser:
    def __init__(self, device_bind_code=None):
        self.device_bind_code = device_bind_code
        self.last_heartbeat_at = object()  # 非 None：视为已联机
        self.username = None
        self.id = 1
        self.device_token = "fake-device-token"


class _FakeDB:
    def commit(self):
        pass


@unittest.skipUnless(_HAVE, "需要 app 环境（当前环境未安装依赖）")
class DeviceBindCodeTest(unittest.TestCase):
    def _call(self, device_bind_code, req_bind_code):
        user = _FakeUser(device_bind_code)
        with mock.patch.object(DeviceService, "get_device_user", return_value=user), \
             mock.patch("app.api.v1.endpoints.family_device.UserService.bind_family") as m_bind, \
             mock.patch("app.api.v1.endpoints.family_device.logger"):
            m_bind.return_value = None
            req = FamilyBindReq(device_id="218356669348204", bind_code=req_bind_code)
            try:
                result = asyncio.run(bind_device(req, current_user=_FakeUser(), db=_FakeDB()))
                return result, m_bind
            except HTTPException as e:
                return e, m_bind

    def test_missing_bind_code_rejected(self):
        e, m = self._call("482913", None)
        self.assertIsInstance(e, HTTPException)
        self.assertEqual(e.status_code, 400)
        m.assert_not_called()

    def test_wrong_bind_code_rejected(self):
        e, m = self._call("482913", "000000")
        self.assertIsInstance(e, HTTPException)
        self.assertEqual(e.status_code, 403)
        m.assert_not_called()

    def test_correct_bind_code_allowed(self):
        result, m = self._call("482913", "482913")
        self.assertIsNotNone(result)
        m.assert_called_once()

    def test_legacy_device_without_bind_code_rejected(self):
        # 旧设备未上报绑定码：拒绝绑定，防弱保护延续
        e, m = self._call(None, "482913")
        self.assertIsInstance(e, HTTPException)
        self.assertEqual(e.status_code, 409)
        m.assert_not_called()

    def test_register_or_heartbeat_stores_bind_code(self):
        # 注册/心跳上报同步绑定码到用户记录
        user = _FakeUser()
        fake_db = mock.MagicMock()
        with mock.patch.object(DeviceService, "find_device_accounts", return_value=(user, None)), \
             mock.patch("app.services.device_service.User") as m_user, \
             mock.patch("app.services.device_service.secrets.token_urlsafe", return_value="t"):
            m_user.return_value = user
            result_user, _ = DeviceService.register_or_heartbeat(
                fake_db, "218356669348204", bind_code="482913"
            )
            self.assertEqual(result_user.device_bind_code, "482913")


if __name__ == "__main__":
    unittest.main()
