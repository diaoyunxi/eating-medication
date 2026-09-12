# -*- coding: utf-8 -*-
"""设备绑定码模块

老人端本地生成并持久化一个 6 位数字绑定码（data/device_bind_code.txt），
显示在设备屏幕上供家属绑定设备时填写，作为「家属实际占有设备」的所有权证明。

安全背景：device_id 由网卡 MAC 派生（同局域网可枚举、日志/照片易泄露），
仅凭 device_id 即可绑定设备是弱保护；引入屏幕绑定码后，攻击者必须同时
接触设备屏幕才能完成绑定。
"""
import logging
import os
import secrets

logger = logging.getLogger("ElderlyAssistant")

# 绑定码文件：elderly_assistant/data/device_bind_code.txt
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_BIND_CODE_FILE = os.path.join(_BASE_DIR, "data", "device_bind_code.txt")

_BIND_CODE_LEN = 6


def _generate_bind_code() -> str:
    """生成 6 位数字绑定码（密码学安全随机源）。"""
    return "".join(secrets.choice("0123456789") for _ in range(_BIND_CODE_LEN))


def load_or_create_bind_code() -> str:
    """读取本地持久化的绑定码；不存在/损坏则生成新的并落盘。

    绑定码首次生成后保持不变（与 device_id 一一对应），家属绑定、
    服务端记录均以屏幕当前显示的值为准。

    :return: 6 位数字绑定码
    """
    try:
        os.makedirs(os.path.dirname(_BIND_CODE_FILE), exist_ok=True)
        if os.path.exists(_BIND_CODE_FILE):
            with open(_BIND_CODE_FILE, "r", encoding="utf-8") as f:
                code = (f.read() or "").strip()
            if code and len(code) == _BIND_CODE_LEN and code.isdigit():
                return code
            logger.warning("绑定码文件内容非法，重新生成")
        code = _generate_bind_code()
        with open(_BIND_CODE_FILE, "w", encoding="utf-8") as f:
            f.write(code)
        logger.info("已生成设备绑定码并持久化")
        return code
    except Exception as e:
        # 落盘失败不阻断启动：返回本次会话有效的一次性绑定码
        logger.warning(f"读取/生成绑定码失败，使用一次性绑定码: {e}")
        return _generate_bind_code()
