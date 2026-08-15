# -*- coding: utf-8 -*-
"""老人端药品扫码与离线回退纯逻辑测试（无硬件/网络依赖，使用 Fake 替身）。"""
import json
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

# 将 elderly_assistant 加入 sys.path，使其顶层包 workflow / hardware / core 可导入
EA = Path(__file__).resolve().parent.parent / "elderly_assistant"
if str(EA) not in sys.path:
    sys.path.insert(0, str(EA))

from tests._helpers import load_module  # noqa: E402

from workflow.actions import find_plan_by_product_code, handle_scan_medication  # noqa: E402
from workflow.reminder import MedicationPoller  # noqa: E402
from hardware.fakes import FakeBarcodeScanner, FakeSpeech  # noqa: E402
from services.http_client import HTTPClient  # noqa: E402
from services.schedule_cache import CACHE_PATH  # noqa: E402

# 模块加载时即保存 schedule_cache 模块对象：pytest 的 prepend 导入模式可能使
# 测试在运行期的 sys.modules 中找不到 "services.schedule_cache"（命名空间包歧义），
# 故在导入期固化引用，供 setUp 打桩使用
import services.schedule_cache as _schedule_cache_module  # noqa: E402

# 以唯一名加载 elderly_assistant/core/barcode.py，规避与 family_monitor 同名顶层包冲突
# （test_elderly_camera 采用相同做法；直接 `from core.barcode import ...` 在 CI 中
#  可能因 sys.path 顺序导致 `core` 绑定到 family_monitor/core 而报 ModuleNotFoundError）
barcode_mod = load_module("elderly_test_barcode", "elderly_assistant/core/barcode.py")

LOG = __import__("logging").getLogger("t")


def _safe_unlink(p):
    """Windows 上删除刚写入的临时令牌文件可能因防病毒/索引瞬时锁失败，重试忽略。"""
    import time
    for _ in range(10):
        try:
            if os.path.exists(p):
                os.unlink(p)
            return
        except OSError:
            time.sleep(0.05)

PLANS = [
    {"plan_id": 1, "drug_name": "阿司匹林", "dosage": "1片", "time": "08:00", "product_code": "6901234567890"},
    {"plan_id": 2, "drug_name": "降压药", "dosage": "2片", "time": "20:00", "product_code": None},
]


class FakePoller:
    """最小轮询替身：固定返回预设的用药计划列表。"""

    def __init__(self, schedules):
        self._schedules = schedules

    @property
    def schedules(self):
        return self._schedules


class TestFindPlanByProductCode(unittest.TestCase):
    def test_match_exact(self):
        plan = find_plan_by_product_code(PLANS, "6901234567890")
        self.assertIsNotNone(plan)
        self.assertEqual(plan["drug_name"], "阿司匹林")

    def test_match_ignores_space(self):
        # 仅清理首尾空白，大小写保持原始语义
        plans = [{"drug_name": "药", "dosage": "1片", "product_code": " AbC123 "}]
        self.assertIsNotNone(find_plan_by_product_code(plans, "AbC123"))

    def test_match_distinguishes_case(self):
        # 大小写不同的真实药品编号必须不匹配，避免误服
        plans = [{"drug_name": "药", "dosage": "1片", "product_code": "AbC123"}]
        self.assertIsNone(find_plan_by_product_code(plans, "abc123"))

    def test_no_match_returns_none(self):
        self.assertIsNone(find_plan_by_product_code(PLANS, "0000000000000"))

    def test_empty_code_returns_none(self):
        # 空编号不得与 product_code 为空的计划误匹配
        self.assertIsNone(find_plan_by_product_code(PLANS, ""))
        self.assertIsNone(find_plan_by_product_code(PLANS, None))
        self.assertIsNone(find_plan_by_product_code(PLANS, "   "))

    def test_tolerates_dirty_items(self):
        self.assertIsNone(find_plan_by_product_code([None, "x", 1], "abc"))


class TestHandleScanMedication(unittest.TestCase):
    def test_speaks_name_and_dosage_when_matched(self):
        scanner = FakeBarcodeScanner(["6901234567890"])
        speech = FakeSpeech()
        plan = handle_scan_medication(scanner, FakePoller(PLANS), speech, LOG, timeout=1)
        self.assertIsNotNone(plan)
        self.assertEqual(plan["plan_id"], 1)
        self.assertTrue(any("阿司匹林" in t and "1片" in t for t in speech.spoken))

    def test_speaks_hint_when_not_matched(self):
        scanner = FakeBarcodeScanner(["1111111111111"])
        speech = FakeSpeech()
        plan = handle_scan_medication(scanner, FakePoller(PLANS), speech, LOG, timeout=1)
        self.assertIsNone(plan)
        self.assertTrue(any("没有找到" in t for t in speech.spoken))

    def test_speaks_hint_when_no_code(self):
        scanner = FakeBarcodeScanner([])  # 模拟超时未识别
        speech = FakeSpeech()
        plan = handle_scan_medication(scanner, FakePoller(PLANS), speech, LOG, timeout=1)
        self.assertIsNone(plan)
        self.assertTrue(any("没有识别到" in t for t in speech.spoken))

    def test_scanner_missing_degrades(self):
        speech = FakeSpeech()
        plan = handle_scan_medication(None, FakePoller(PLANS), speech, LOG)
        self.assertIsNone(plan)
        self.assertTrue(any("不可用" in t for t in speech.spoken))

    def test_scanner_exception_does_not_propagate(self):
        class BrokenScanner:
            def scan(self, timeout=None):
                raise RuntimeError("摄像头掉线")

        speech = FakeSpeech()
        plan = handle_scan_medication(BrokenScanner(), FakePoller(PLANS), speech, LOG)
        self.assertIsNone(plan)
        self.assertTrue(any("出错" in t for t in speech.spoken))

    def test_works_without_speech(self):
        scanner = FakeBarcodeScanner(["6901234567890"])
        plan = handle_scan_medication(scanner, FakePoller(PLANS), None, LOG)
        self.assertIsNotNone(plan)


display_mod = load_module("elderly_core_display", "elderly_assistant/core/display.py")


class TestDisplayScanButton(unittest.TestCase):
    """屏幕「扫码查药」触摸按钮（非 M10 环境 gui=None，仅验证回调装配逻辑）。"""

    def _display(self):
        # 非 M10 环境下 unihiker 缺失，Display 自动降级为 gui=None
        return display_mod.Display()

    def test_handler_not_registered_by_default(self):
        d = self._display()
        self.assertIsNone(d._scan_handler)
        self.assertFalse(d._on_scan_clicked())

    def test_click_invokes_registered_handler(self):
        d = self._display()
        clicks = []
        d.set_scan_handler(lambda: clicks.append(1))
        self.assertTrue(d._on_scan_clicked())
        self.assertEqual(clicks, [1])

    def test_non_callable_handler_rejected(self):
        d = self._display()
        d.set_scan_handler("not-callable")
        self.assertIsNone(d._scan_handler)
        self.assertFalse(d._on_scan_clicked())

    def test_handler_exception_is_isolated(self):
        # 回调异常不得向上抛出，避免 GUI 事件线程中断
        d = self._display()

        def boom():
            raise RuntimeError("扫码线程启动失败")

        d.set_scan_handler(boom)
        self.assertFalse(d._on_scan_clicked())

    def test_draw_scan_button_noop_without_gui(self):
        # 无 GUI 时绘制按钮应静默跳过，不抛异常
        d = self._display()
        d.set_scan_handler(lambda: None)
        d._draw_scan_button()
        self.assertIsNone(d._scan_button)


class FakeOfflineClient:
    """按预设序列返回拉取结果的 HTTP 替身（None 表示本次拉取结果未知）。"""

    def __init__(self, results):
        self.results = list(results)

    def get_medication_schedule(self):
        return self.results.pop(0) if self.results else None


class TestPollerOfflineFallback(unittest.TestCase):
    def test_seeds_from_cache_loader(self):
        poller = MedicationPoller(None, poll_interval=1, cache_loader=lambda: PLANS)
        self.assertEqual(len(poller.schedules), 2)

    def test_cache_loader_exception_is_tolerated(self):
        def boom():
            raise IOError("磁盘错误")

        poller = MedicationPoller(None, poll_interval=1, cache_loader=boom)
        self.assertEqual(poller.schedules, [])

    def test_none_result_keeps_existing_schedules(self):
        client = FakeOfflineClient([PLANS, None])
        poller = MedicationPoller(client, poll_interval=1)
        poller._poll_once()
        self.assertEqual(len(poller.schedules), 2)
        self.assertTrue(poller.last_success)
        # 第二轮返回 None（断网且无本地缓存）：保留既有计划，不清空
        poller._poll_once()
        self.assertEqual(len(poller.schedules), 2)
        self.assertFalse(poller.last_success)

    def test_empty_list_result_clears_schedules(self):
        # 服务端明确返回空列表（家人删光了计划）时应清空
        client = FakeOfflineClient([PLANS, []])
        poller = MedicationPoller(client, poll_interval=1)
        poller._poll_once()
        poller._poll_once()
        self.assertEqual(poller.schedules, [])

    def test_client_exception_keeps_existing_schedules(self):
        class BrokenClient:
            def __init__(self):
                self.calls = 0

            def get_medication_schedule(self):
                self.calls += 1
                if self.calls == 1:
                    return PLANS
                raise RuntimeError("连接被重置")

        poller = MedicationPoller(BrokenClient(), poll_interval=1)
        poller._poll_once()
        poller._poll_once()
        self.assertEqual(len(poller.schedules), 2)
        self.assertFalse(poller.last_success)


schedule_cache = load_module(
    "elderly_services_schedule_cache", "elderly_assistant/services/schedule_cache.py"
)


class TestScheduleCache(unittest.TestCase):
    def _tmp(self):
        return Path(tempfile.mkdtemp()) / "schedules.json"

    def test_save_and_load_roundtrip(self):
        p = self._tmp()
        self.assertTrue(schedule_cache.save_schedules(PLANS, p))
        loaded = schedule_cache.load_schedules(p)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]["drug_name"], "阿司匹林")

    def test_load_missing_file_returns_empty(self):
        self.assertEqual(schedule_cache.load_schedules(self._tmp()), [])

    def test_load_corrupted_file_returns_empty(self):
        p = self._tmp()
        p.write_text("{ 半截 json", encoding="utf-8")
        self.assertEqual(schedule_cache.load_schedules(p), [])

    def test_load_non_list_returns_empty(self):
        p = self._tmp()
        p.write_text(json.dumps({"schedules": []}), encoding="utf-8")
        self.assertEqual(schedule_cache.load_schedules(p), [])

    def test_save_rejects_non_list(self):
        self.assertFalse(schedule_cache.save_schedules({"a": 1}, self._tmp()))

    def test_save_filters_dirty_items(self):
        p = self._tmp()
        self.assertTrue(schedule_cache.save_schedules([{"a": 1}, None, "x"], p))
        self.assertEqual(schedule_cache.load_schedules(p), [{"a": 1}])


class _FakeResp:
    """最小 HTTP 响应替身：携带状态码与可解析 JSON 负载。"""

    def __init__(self, status_code, data):
        self.status_code = status_code
        self._data = data

    def json(self):
        return self._data


class _ValidationClient(HTTPClient):
    """测试替身：跳过 get_device_id（避免无开发板时 pinpong Board().begin() 退出），
    仅用于验证 get_medication_schedule 的 schedules 内部类型校验逻辑。"""

    def __init__(self, base_url="http://t", timeout=5):
        self.config = {"base_url": base_url, "timeout": timeout}
        self.base_url = base_url
        self.timeout = timeout
        self.device_id = "test-device"
        self.device_token = None


class TestScheduleTypeValidation(unittest.TestCase):
    """#6 校验服务端返回 schedules 的内部类型，避免下游因非预期结构崩溃。"""

    def setUp(self):
        # 使用临时目录隔离缓存路径，避免测试间相互影响或污染真实缓存
        self._cache_dir = tempfile.TemporaryDirectory()
        cache_path = os.path.join(self._cache_dir.name, "schedules.json")
        # 直接对加载期固化的 schedule_cache 模块对象打桩，隔离缓存路径，
        # 避免测试间相互影响或污染真实运行时缓存
        patcher = mock.patch.object(_schedule_cache_module, "CACHE_PATH", cache_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._cache_dir.cleanup)
        # CodeRabbit 修复：将设备令牌文件隔离到临时目录，避免 register 验证测试
        # 触及真实令牌文件（elderly_assistant/data/device_token.txt）造成跨测试污染
        fd, token_path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        self._token_file = token_path
        token_patcher = mock.patch("services.http_client._TOKEN_FILE", token_path)
        token_patcher.start()
        self.addCleanup(token_patcher.stop)
        self.addCleanup(lambda: _safe_unlink(token_path))

    def _client(self):
        return _ValidationClient()

    def _patch_get(self, status_code, data):
        # HTTPClient._request 统一走 requests.request，故打桩 requests.request
        # （避免替换模块属性引发的串扰）
        patcher = mock.patch("requests.request", return_value=_FakeResp(status_code, data))
        patcher.start()
        self.addCleanup(patcher.stop)
        return patcher

    def test_malformed_string_falls_back(self):
        client = self._client()
        self._patch_get(200, {"schedules": "invalid"})
        # 内部类型非法时回退本地缓存；无缓存返回 None（结果未知），而非崩溃
        self.assertIsNone(client.get_medication_schedule())

    def test_malformed_object_falls_back(self):
        client = self._client()
        self._patch_get(200, {"schedules": {"a": 1}})
        self.assertIsNone(client.get_medication_schedule())

    def test_valid_list_of_dicts_returned(self):
        client = self._client()
        plans = [{"drug_name": "x", "product_code": "1"}]
        self._patch_get(200, {"schedules": plans})
        self.assertEqual(client.get_medication_schedule(), plans)

    def test_top_level_list_response_returned(self):
        client = self._client()
        plans = [{"drug_name": "y"}]
        self._patch_get(200, plans)
        self.assertEqual(client.get_medication_schedule(), plans)


class TestSchedule403SelfHeal(unittest.TestCase):
    """#36 拉取用药计划返回 HTTP 403 的自愈验证。

    设备本地令牌缺失/过期但 WiFi 正常时，服务端鉴权端点返回 403。
    客户端应在收到 403 后重新注册以刷新 device_token，并重试一次，
    而非永久卡在 403。
    """

    def setUp(self):
        self._cache_dir = tempfile.TemporaryDirectory()
        cache_path = os.path.join(self._cache_dir.name, "schedules.json")
        patcher = mock.patch.object(_schedule_cache_module, "CACHE_PATH", cache_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._cache_dir.cleanup)
        # CodeRabbit 修复：将设备令牌文件隔离到临时目录，避免 register 验证测试
        # 触及真实令牌文件（elderly_assistant/data/device_token.txt）造成跨测试污染
        fd, token_path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        self._token_file = token_path
        token_patcher = mock.patch("services.http_client._TOKEN_FILE", token_path)
        token_patcher.start()
        self.addCleanup(token_patcher.stop)
        self.addCleanup(lambda: _safe_unlink(token_path))

    def _client(self):
        return _ValidationClient()

    def _patch_sequence(self, responses):
        """按调用顺序依次返回响应（首个给拉计划，其后是重注册/重试）。

        :param responses: list[(_FakeResp, dict|None)]，None 表示不解析 JSON（如心跳响应）
        """
        calls = {"i": 0}

        def _side_effect(method, url, **kwargs):
            idx = calls["i"]
            calls["i"] += 1
            status, data = responses[idx]
            return _FakeResp(status, data)

        patcher = mock.patch("requests.request", side_effect=_side_effect)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_403_triggers_reregister_then_retry_success(self):
        client = self._client()
        self.assertIsNone(client.device_token)  # 初始令牌缺失
        plans = [{"drug_name": "阿司匹林", "product_code": "6901234567890"}]
        # 顺序：拉计划(403) -> 重新注册(200, 返回令牌) -> 重试拉计划(200)
        self._patch_sequence([
            (403, None),
            (200, {"status": "ok", "device_token": "new-token-123"}),
            (200, {"schedules": plans}),
        ])
        result = client.get_medication_schedule()
        self.assertEqual(result, plans)
        # 重新注册后内存令牌应被刷新，重试请求才会携带有效令牌并成功
        self.assertEqual(client.device_token, "new-token-123")

    def test_403_reregister_fails_falls_back(self):
        client = self._client()
        self._patch_sequence([
            (403, None),
            (500, None),  # 重新注册失败
        ])
        # 无本地缓存时应回退返回 None（结果未知），且不崩溃
        self.assertIsNone(client.get_medication_schedule())


class _FakeBlock:
    """模拟 HuskyLens 识别块，content 为条码/二维码文本。"""
    def __init__(self, content):
        self.content = content


class _ResidualCacheHuskyLens:
    """模拟有「缓存残留」缺陷的 HuskyLens 驱动：

    - 第一次识别到码 A 后，``result`` 字典残留旧 block；
    - 后续镜头前无条码时，``getResult`` 返回 0，且 ``getCachedResultByID`` 返回 None。
    修复前 ``_read_contents`` 会直接信任 ``result`` 字典而返回旧码 A。
    """

    def __init__(self, total_per_call):
        self._total = total_per_call
        # 残留的旧 block（模拟上一帧识别到的码）
        self.result = {1: {"blocks": [_FakeBlock("6901234567890")]}}

    def getResult(self, algo):
        # 仅返回当前帧目标数，不刷新/清空 result 字典（模拟残驱缺陷）
        return self._total

    def getCachedResultByID(self, algo, idx):
        # 实时拉取：当前帧无目标时返回 None（不残留）
        return None if self._total <= 0 else _FakeBlock("6901234567890")


class _ResidualGetResultHuskyLens:
    """更隐蔽的残驱：getResult 返回 >0 但 getCachedResultByID 实时返回空，
    且 result 字典也残留旧 block——必须完全依赖实时读取，不得信任 result。"""

    def __init__(self):
        self.result = {1: {"blocks": [_FakeBlock("6901234567890")]}}

    def getResult(self, algo):
        return 1  # 驱动误报当前帧有目标

    def getCachedResultByID(self, algo, idx):
        return None  # 实时检查：实际并无目标


class TestHuskyLensResidualCache(unittest.TestCase):
    """回归测试：镜头无条码时不得返回第一次识别的旧结果。"""

    def test_no_residual_when_getresult_zero(self):
        HuskyLensScanner = barcode_mod.HuskyLensScanner
        hl = _ResidualCacheHuskyLens(total_per_call=0)
        codes = HuskyLensScanner._read_contents(hl, 1)
        self.assertEqual(codes, [])  # 关键：不返回残留的旧码

    def test_no_residual_when_getcached_returns_none(self):
        HuskyLensScanner = barcode_mod.HuskyLensScanner
        hl = _ResidualGetResultHuskyLens()
        codes = HuskyLensScanner._read_contents(hl, 1)
        self.assertEqual(codes, [])  # 关键：getResult>0 但实时为空，不返回旧码

    def test_returns_code_when_real_target_present(self):
        HuskyLensScanner = barcode_mod.HuskyLensScanner
        hl = _ResidualCacheHuskyLens(total_per_call=1)
        codes = HuskyLensScanner._read_contents(hl, 1)
        self.assertEqual(codes, ["6901234567890"])


if __name__ == "__main__":
    unittest.main()
