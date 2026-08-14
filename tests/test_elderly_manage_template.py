# -*- coding: utf-8 -*-
"""elderly_manage.html 模板渲染测试（回归 issue #35）。

聚焦「人脸 ID 编辑框是否对所有老人渲染」：
设备主体老人（has_device=True）同样需要 husky_face_id 才能通过服药前身份核验
（见 elderly_assistant/workflow/actions.py 中 husky_face_id 为 None 时拒绝确认），
因此人脸 ID 输入框不能因 has_device 被隐藏，否则该老人的人脸 ID 永远无法保存。
"""
import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = REPO_ROOT / "family_monitor" / "templates"

_HAS_JINJA = importlib.util.find_spec("jinja2") is not None


class _FakeURL:
    """base.html 依赖 request.url.path 做导航高亮，这里提供最小实现。"""

    path = "/elderly_manage"


class _FakeState:
    """base.html 依赖 request.state.user 展示登录用户信息。"""

    user = {"username": "家属测试", "role": "family"}


class _FakeRequest:
    url = _FakeURL()
    state = _FakeState()


@unittest.skipUnless(_HAS_JINJA, "缺少 jinja2，跳过模板渲染测试")
class TestElderlyManageTemplate(unittest.TestCase):
    """渲染真实模板，校验人脸 ID 编辑区与删除按钮的显示条件。"""

    def _render(self, elderly_list):
        from jinja2 import Environment, FileSystemLoader

        env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
        # base.html 可能引用 url_for 等 Starlette 注入的全局量，这里做无害占位
        env.globals.setdefault("url_for", lambda *a, **k: "#")
        template = env.get_template("elderly_manage.html")
        return template.render(
            elderly_list=elderly_list,
            prefix="",
            request=_FakeRequest(),
            status={"online": True},
            device_info={"connected": True},
        )

    def test_face_id_input_rendered_for_device_owner(self):
        """设备主体老人也必须有人脸 ID 输入框与保存按钮（issue #35 核心回归点）。"""
        html = self._render([
            {"id": 7, "name": "设备主体老人", "husky_face_id": None, "has_device": True},
        ])
        self.assertIn('id="faceId-7"', html)
        self.assertIn("saveFaceId(7)", html)

    def test_face_id_input_rendered_for_plain_elderly(self):
        """普通老人（未绑定设备）原有行为保持不变。"""
        html = self._render([
            {"id": 3, "name": "普通老人", "husky_face_id": 2, "has_device": False},
        ])
        self.assertIn('id="faceId-3"', html)
        self.assertIn("saveFaceId(3)", html)
        # 已有人脸 ID 应回填到输入框
        self.assertIn('value="2"', html)

    def test_delete_button_still_hidden_for_device_owner(self):
        """设备主体老人仍然不可删除（此限制与人脸 ID 无关，不应被本次修复破坏）。"""
        html = self._render([
            {"id": 7, "name": "设备主体老人", "husky_face_id": None, "has_device": True},
        ])
        # 不应为该老人渲染删除按钮（以 data-elderly-id 精确判定，避免误匹配 JS 函数定义）
        self.assertNotIn('data-elderly-id="7"', html)
        self.assertIn("设备主体不可删除", html)

    def test_delete_button_present_for_plain_elderly(self):
        """普通老人应保留删除按钮。"""
        html = self._render([
            {"id": 3, "name": "普通老人", "husky_face_id": None, "has_device": False},
        ])
        self.assertIn('data-elderly-id="3"', html)


if __name__ == "__main__":
    unittest.main()
