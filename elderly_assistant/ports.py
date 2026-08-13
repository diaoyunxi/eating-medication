# -*- coding: utf-8 -*-
"""硬件与网络端口抽象（Protocol）。

定义老人端与具体硬件/网络实现之间的接口边界，使业务工作流（workflow/）
只依赖接口而非具体硬件，从而可在无 M10 硬件的环境下注入 Fake 替身做单元测试。

采用结构化子类型（structural typing）：具体类无需显式继承这些 Protocol，
只要方法签名匹配即满足接口；@runtime_checkable 仅用于可选的运行时校验。
"""

from typing import List, Optional, Protocol, runtime_checkable


@runtime_checkable
class ButtonPort(Protocol):
    """按钮句柄：查询式读取按下状态。"""

    def is_pressed(self) -> bool:
        ...


@runtime_checkable
class BuzzerPort(Protocol):
    """蜂鸣器：提醒音乐播放/停止/成功提示。"""

    def play_reminder(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def play_success(self) -> None:
        ...

    def is_reminding(self) -> bool:
        ...


@runtime_checkable
class DisplayPort(Protocol):
    """显示屏（unihiker GUI）：时间、状态、提醒等界面渲染。"""

    def show_time(self, now) -> None:
        ...

    def show_status(self, url: str, connected: bool) -> None:
        ...

    def show_device_uuid(self, device_uuid: str) -> None:
        ...

    def show_next_reminder(self, reminder) -> None:
        ...

    def show_main_screen(self, device_uuid: str, server_url: str, connected: bool) -> None:
        ...

    def show_reminder(self, drug: str, dosage: str) -> None:
        ...

    def clear_reminder(self) -> None:
        ...

    def set_scan_handler(self, handler) -> None:
        ...


@runtime_checkable
class LedPort(Protocol):
    """LED 指示灯（P25）。"""

    def write_digital(self, value: int) -> None:
        ...


@runtime_checkable
class CameraPort(Protocol):
    """摄像头（HuskyLens）：拍照并返回本地路径。"""

    def capture_image(self, config) -> Optional[str]:
        ...


@runtime_checkable
class BarcodeScannerPort(Protocol):
    """药品条码扫描器：在超时时间内返回识别到的编码文本。

    实现方可为 HuskyLens 板载条码识别算法，或 USB 摄像头 + 本地解码库；
    识别失败/超时统一返回 None，调用方据此播报提示。
    """

    def scan(self, timeout: Optional[float] = None) -> Optional[str]:
        ...

    def close(self) -> None:
        ...


@runtime_checkable
class HttpClientPort(Protocol):
    """设备端 -> 服务端 HTTP 客户端接口。"""

    def get_medication_schedule(self):
        ...

    def send_heartbeat(self) -> None:
        ...

    def check_connection(self) -> bool:
        ...

    def confirm_medication(self, drug: str, dosage: str, items=None) -> None:
        ...

    def upload_image(self, path: str, plan_id=None, scheduled_time=None, elderly_id=None) -> None:
        ...

    def ask_ai(self, question: str) -> str:
        ...

    def unregister_device(self) -> None:
        ...


@runtime_checkable
class FaceRecognizerPort(Protocol):
    """人脸识别（设备端身份核验/录入）抽象接口。

    拍照确认服药前调用 recognize() 核验当前人脸是否为预期老人；
    家属在网页触发录入时调用 learn(face_id) 学习人脸。
    无硬件环境由 FakeFaceRecognizer 注入，便于单元测试。
    """

    def is_available(self) -> bool:
        ...

    def recognize(self) -> List[int]:
        """识别当前帧人脸，返回已学习的人脸 ID 列表（空表示未检测到）。"""
        ...

    def learn(self, face_id: int) -> bool:
        """学习当前帧人脸为指定 face_id，成功返回 True。"""
        ...
