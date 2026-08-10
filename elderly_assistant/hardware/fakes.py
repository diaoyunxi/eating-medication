# -*- coding: utf-8 -*-
"""硬件测试替身（Fake）。

在无真实 M10 硬件时，供工作流单元测试注入，验证提醒状态机、确认/暂缓逻辑的正确性。
"""


class FakeLed:
    """LED 替身，记录最近一次写入的电平。"""

    def __init__(self):
        self.state = 0

    def write_digital(self, value: int) -> None:
        self.state = value


class FakeBuzzer:
    """蜂鸣器替身，记录播放/停止/成功提示状态，满足 BuzzerPort 接口。"""

    def __init__(self):
        self.playing = False
        self.stopped = False
        self.success_played = False

    def play_reminder(self) -> None:
        self.playing = True

    def stop(self) -> None:
        self.playing = False
        self.stopped = True

    def play_success(self) -> None:
        self.success_played = True

    def is_reminding(self) -> bool:
        return self.playing


class FakeDisplay:
    """显示屏替身，记录最近一次提醒内容与调用次数，满足 DisplayPort 接口。"""

    def __init__(self):
        self.reminder_shown = None
        self.reminder_count = 0
        self.scan_handler = None

    def show_time(self, now) -> None:
        pass

    def show_status(self, url: str, connected: bool) -> None:
        pass

    def show_device_uuid(self, device_uuid: str) -> None:
        pass

    def show_next_reminder(self, reminder) -> None:
        pass

    def show_main_screen(self, device_uuid: str, server_url: str, connected: bool) -> None:
        pass

    def show_reminder(self, drug: str, dosage: str) -> None:
        self.reminder_shown = (drug, dosage)
        self.reminder_count += 1

    def clear_reminder(self) -> None:
        self.reminder_shown = None

    def set_scan_handler(self, handler) -> None:
        self.scan_handler = handler


class FakeBarcodeScanner:
    """条码扫描器替身，按预设队列依次返回扫码结果，满足 BarcodeScannerPort 接口。"""

    def __init__(self, codes=None):
        # 预设的扫码结果队列，耗尽后返回 None（模拟超时未识别）
        self.codes = list(codes or [])
        self.scan_calls = 0
        self.closed = False

    def scan(self, timeout=None):
        self.scan_calls += 1
        return self.codes.pop(0) if self.codes else None

    def close(self) -> None:
        self.closed = True


class FakeSpeech:
    """TTS 替身，记录全部播报文本，便于断言播报内容。"""

    def __init__(self):
        self.spoken = []

    def speak(self, text, volume=None) -> None:
        self.spoken.append(text)


class FakeHttpClient:
    """HTTP 客户端替身，记录确认上报内容，满足 HttpClientPort 接口。"""

    def __init__(self):
        self.confirmed = None

    def confirm_medication(self, drug: str, dosage: str, items=None) -> None:
        self.confirmed = (drug, dosage)

    def get_medication_schedule(self):
        return []

    def send_heartbeat(self) -> None:
        pass

    def check_connection(self) -> bool:
        return True

    def upload_image(self, path: str) -> None:
        pass

    def ask_ai(self, question: str) -> str:
        return "ok"

    def unregister_device(self) -> None:
        pass
