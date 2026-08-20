# -*- coding: utf-8 -*-
"""
二哈网络图传模块（HTTP / RTSP 拉流）

M10 与二哈 V2 连接在同一个 WiFi 网络上，通过 HTTP 请求或 RTSP 拉流获取实时画面。
此模块替代原有的「二哈 I2C 拍照 + SD 卡取回」方案，图传全部走网络。

支持的图传协议（按优先级）：
  1. HTTP 快照：GET http://<IP>:<PORT>/snapshot → 返回 JPEG 字节
  2. HTTP MJPEG：GET http://<IP>:<PORT>/stream → multipart/x-mixed-replace 流
  3. RTSP 拉流：cv2.VideoCapture("rtsp://<IP>:554/live") → 逐帧读取

配置项（elderly_assistant/.env）：
  HUSKYLENS_NETWORK_MODE    auto | http | rtsp   默认 auto（自动探测）
  HUSKYLENS_IP              二哈的局域网 IP 地址（如 192.168.1.100）
  HUSKYLENS_HTTP_PORT       HTTP 服务端口，默认 80
  HUSKYLENS_SNAPSHOT_PATH   快照接口路径，默认 /snapshot
  HUSKYLENS_STREAM_PATH     流媒体接口路径，默认 /stream
  HUSKYLENS_RTSP_PORT       RTSP 端口，默认 554
  HUSKYLENS_REQUEST_TIMEOUT  HTTP 请求超时（秒），默认 5
  CAMERA_SAVE_PATH          保存路径（同原来），默认 data/captures

I2C/UART 总线保留用途：
  - 条码识别（core/barcode.py）：仍通过 I2C 下发算法命令、读取识别结果
  - 人脸识别（core/face.py）：仍通过 I2C 下发算法命令、读取人脸 ID
  以上功能不依赖网络图传，保持原逻辑不变。
"""

import io
import logging
import socket
import threading
import time
from typing import Optional

logger = logging.getLogger("ElderlyAssistant")

# 模块级锁：保护 HTTP 请求与 RTSP 拉流的并发访问
_network_lock = threading.Lock()


# ------------------------------------------------------------------
# 配置读取
# ------------------------------------------------------------------

def _load_network_config(config: dict) -> dict:
    """从 config 中提取网络图传配置项，缺失时用内置默认值。"""
    cam = config.get("camera", {})
    return {
        "network_mode": cam.get("network_mode", "auto"),
        "ip": cam.get("huskylens_ip", ""),
        "http_port": int(cam.get("http_port", 80)),
        "snapshot_path": cam.get("snapshot_path", "/snapshot"),
        "stream_path": cam.get("stream_path", "/stream"),
        "rtsp_port": int(cam.get("rtsp_port", 554)),
        "request_timeout": float(cam.get("request_timeout", 5)),
        "save_path": cam.get("save_path", "data/captures"),
    }


# ------------------------------------------------------------------
# 网络可达性探测
# ------------------------------------------------------------------

def _is_host_reachable(ip: str, port: int, timeout: float = 2.0) -> bool:
    """尝试 TCP 连接到指定 IP:port，返回是否可达。"""
    try:
        sock = socket.create_connection((ip, port), timeout=timeout)
        sock.close()
        return True
    except (socket.timeout, socket.error, OSError):
        return False


def discover_huskylens_on_network(subnet: str = "192.168.1", timeout: float = 3.0) -> Optional[str]:
    """
    在指定子网内扫描可能运行二哈 HTTP 服务的设备。

    通过向常见端口（80、8080、8088）发送简短 HTTP 请求判断是否为二哈。
    返回找到的 IP 地址字符串，未找到返回 None。

    :param subnet: 子网前缀，如 "192.168.1"
    :param timeout: 每个地址的探测超时（秒）
    :return: 二哈 IP 地址或 None
    """
    import requests  # 懒加载

    logger.info("开始在网络中扫描二哈设备（子网 %s）...", subnet)
    for i in range(1, 255):
        ip = f"{subnet}.{i}"
        for port in (80, 8080, 8088):
            if _is_host_reachable(ip, port, timeout=0.5):
                try:
                    resp = requests.get(
                        f"http://{ip}:{port}/",
                        timeout=timeout,
                        allow_redirects=False,
                    )
                    # 二哈的 Web 服务器通常返回特定内容
                    # 这里通过响应头或状态码做初步判断
                    if resp.status_code in (200, 301, 302):
                        logger.info("发现可能的二哈设备: %s:%d", ip, port)
                        return ip
                except Exception:
                    continue
    logger.warning("未在网络中检测到二哈设备")
    return None


# ------------------------------------------------------------------
# HTTP 快照获取
# ------------------------------------------------------------------

def _get_http_snapshot(cfg: dict) -> Optional[bytes]:
    """
    通过 HTTP GET 请求获取二哈快照（JPEG 字节）。

    尝试多种可能的路径：
      1. /snapshot
      2. /stream（尝试读取第一帧）
      3. /jpg（某些固件使用）

    :param cfg: _load_network_config 返回的配置字典
    :return: JPEG 字节或 None
    """
    import requests  # 懒加载

    base = f"http://{cfg['ip']}:{cfg['http_port']}"
    paths_to_try = [
        cfg["snapshot_path"],
        "/snapshot",
        "/stream",
        "/jpg",
        "/image",
    ]

    for path in paths_to_try:
        url = f"{base}{path}"
        try:
            resp = requests.get(url, timeout=cfg["request_timeout"], stream=True)
            if resp.status_code == 200 and resp.content:
                content_type = resp.headers.get("Content-Type", "")
                # 如果是 MJPEG 流，只取第一帧
                if "multipart" in content_type:
                    # 解析 multipart 响应，取第一个 boundary 前的 JPEG 数据
                    frame = _extract_first_mjpeg_frame(resp.raw, resp.headers)
                    if frame:
                        logger.debug("HTTP 快照成功（MJPEG 第一帧）: %s", url)
                        return frame
                elif "image" in content_type or resp.content[:3] == b"\xff\xd8\xff":
                    logger.debug("HTTP 快照成功: %s", url)
                    return resp.content
        except Exception as e:
            logger.debug("尝试 %s 失败: %s", url, e)
            continue
    return None


def _extract_first_mjpeg_frame(raw, headers: dict) -> Optional[bytes]:
    """从 MJPEG 流中解析出第一帧 JPEG 数据。"""
    boundary = None
    ct = headers.get("Content-Type", "")
    if "boundary=" in ct:
        boundary = ct.split("boundary=")[1].split(";")[0].strip()

    if not boundary:
        return None

    buffer = io.BytesIO()
    found_start = False
    found_end = False

    while True:
        line = raw.readline()
        if not line:
            break
        line_str = line.decode("utf-8", errors="ignore").strip()
        if line_str == f"--{boundary}":
            if found_start and found_end:
                break
            found_start = True
            found_end = False
            buffer = io.BytesIO()
            continue
        if found_start and not found_end:
            if line.strip() == b"":
                found_end = True
                continue
            # 跳过头部信息
            continue
        if found_start and found_end:
            buffer.write(line)
            # 检测 JPEG 结束标记
            if b"\xff\xd9" in line:
                result = buffer.getvalue()
                if len(result) > 1000:  # 有效 JPEG 至少 1KB
                    return result

    return None


# ------------------------------------------------------------------
# RTSP 拉流
# ------------------------------------------------------------------

def _get_rtsp_frame(cfg: dict) -> Optional[bytes]:
    """
    通过 RTSP 拉取一帧图像（JPEG 字节）。

    使用 OpenCV 打开 RTSP 流，读取一帧后释放。
    注意：RTSP 首次连接可能有 1-2 秒延迟。

    :param cfg: _load_network_config 返回的配置字典
    :return: JPEG 字节或 None
    """
    try:
        import cv2
    except ImportError:
        logger.warning("OpenCV 未安装，无法使用 RTSP 拉流")
        return None

    rtsp_url = f"rtsp://{cfg['ip']}:{cfg['rtsp_port']}/live"
    cap = None
    try:
        cap = cv2.VideoCapture(rtsp_url)
        if not cap.isOpened():
            logger.warning("RTSP 连接失败: %s", rtsp_url)
            return None
        ret, frame = cap.read()
        if not ret or frame is None:
            logger.warning("RTSP 读帧失败")
            return None
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return buf.tobytes()
    except Exception as e:
        logger.warning("RTSP 拉流异常: %s", e)
        return None
    finally:
        if cap is not None:
            cap.release()


# ------------------------------------------------------------------
# 统一接口：capture_frame
# ------------------------------------------------------------------

def capture_frame(config: dict) -> Optional[bytes]:
    """
    从二哈网络图传获取一帧 JPEG 图像。

    根据配置的网络模式自动选择最佳方式（优先级从高到低）：
    - webrtc：仅使用 WebRTC（超低延迟 ~200ms）
    - http：仅使用 HTTP 快照
    - rtsp：仅使用 RTSP 拉流
    - auto（默认）：HTTP → WebRTC → RTSP，逐级降级

    WebRTC 拉单帧特点：
      - 延迟最低（端到端 ~200ms），适合实时性要求高的场景
      - 需要 aiortc 库（可选依赖，未安装时自动跳过）
      - 信令接口通过 HTTP POST /webrtc/offer 完成 SDP 交换

    :param config: 完整配置字典（同 elderly_assistant/main.py 传入的 config）
    :return: JPEG 字节；全部失败返回 None
    """
    cfg = _load_network_config(config)
    ip = cfg["ip"].strip()

    if not ip:
        logger.error("未配置 HUSKYLENS_IP，请检查 elderly_assistant/.env")
        return None

    # 检查网络可达性
    if not _is_host_reachable(ip, cfg["http_port"], timeout=2.0):
        logger.error("二哈设备不可达: %s:%d", ip, cfg["http_port"])
        return None

    mode = cfg["network_mode"].lower()
    logger.info("网络图传模式: %s，目标: %s", mode, ip)

    with _network_lock:
        if mode == "webrtc":
            frame = _get_webrtc_frame(cfg)
        elif mode == "rtsp":
            frame = _get_rtsp_frame(cfg)
        elif mode == "http":
            frame = _get_http_snapshot(cfg)
        else:  # auto：HTTP → WebRTC → RTSP，逐级降级
            frame = _get_http_snapshot(cfg)
            if frame is None:
                logger.info("HTTP 快照失败，尝试 WebRTC")
                frame = _get_webrtc_frame(cfg)
            if frame is None:
                logger.info("WebRTC 失败，降级到 RTSP")
                frame = _get_rtsp_frame(cfg)

    if frame is None:
        logger.error("网络图传失败：HTTP / WebRTC / RTSP 均不可用")
    else:
        logger.info("网络图传成功，获取到 %d 字节的 JPEG 数据", len(frame))
    return frame


# ------------------------------------------------------------------
# 向后兼容：capture_image
# ------------------------------------------------------------------

def capture_image(config: dict) -> Optional[str]:
    """
    向后兼容接口：获取图片并保存到本地文件，返回本地路径。

    替代原 camera.py 中的 takePhoto() + SD卡取回 方案，
    改为通过网络从二哈获取实时图片。

    :param config: 完整配置字典
    :return: 本地保存的 .jpg 文件路径；失败返回 None
    """
    import os
    from datetime import datetime
    from uuid import uuid4

    frame = capture_frame(config)
    if not frame:
        return None

    save_path = config.get("camera", {}).get("save_path", "data/captures")
    os.makedirs(save_path, exist_ok=True)

    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{uuid4().hex}.jpg"
    local_path = os.path.join(save_path, filename)

    try:
        with open(local_path, "wb") as f:
            f.write(frame)
        logger.info("网络图传快照已保存: %s", local_path)
        return local_path
    except Exception as e:
        logger.error("保存图片失败: %s", e)
        return None


# ------------------------------------------------------------------
# 实时流订阅（供 Web 页面展示用）
# ------------------------------------------------------------------

def stream_frames(config: dict, callback=None):
    """
    持续从二哈拉取帧并回调。

    :param config: 配置字典
    :param callback: 每帧调用 callback(frame_bytes)，None 表示不回调
    :yields: 每帧 JPEG 字节
    """
    while True:
        frame = capture_frame(config)
        if frame:
            if callback:
                try:
                    callback(frame)
                except Exception as e:
                    logger.warning("帧回调异常: %s", e)
            yield frame
        else:
            logger.warning("图传帧获取失败，1s 后重试")
            time.sleep(1)


# ------------------------------------------------------------------
# 重置连接（不清除 I2C 单例，仅重置网络状态）
# ------------------------------------------------------------------

def reset_network_connection():
    """重置网络图传状态（下次调用会重新探测）。"""
    logger.info("网络图传连接已重置")


# ------------------------------------------------------------------
# WebRTC 拉流支持（aiortc）
# ------------------------------------------------------------------

def _get_webrtc_frame(cfg: dict) -> Optional[bytes]:
    """
    通过 WebRTC 从二哈获取一帧 JPEG 图像。

    WebRTC 流程：
    1. 创建 RTCPeerConnection
    2. 生成 SDP offer 并通过 HTTP POST 发送到二哈的信令接口
    3. 接收二哈返回的 SDP answer
    4. 完成握手，从 media track 读取第一帧
    5. 编码为 JPEG 返回

    信令接口（可配置）：
      HUSKYLENS_WEBRTC_SIGNALLING_URL: WebSocket 或 HTTP 信令地址
      HUSKYLENS_WEBRTC_OFFER_PATH: HTTP POST offer 路径

    :param cfg: _load_network_config 返回的配置字典
    :return: JPEG 字节或 None
    """
    try:
        from aiortc import RTCPeerConnection, RTCSessionDescription
        from aiortc.contrib.media import MediaPlayer
    except ImportError:
        logger.warning("aiortc 未安装，跳过 WebRTC 图传（pip install aiortc）")
        return None

    ip = cfg["ip"]
    http_port = cfg["http_port"]
    signaling_url = cfg.get("webrtc_signalling_url", f"http://{ip}:{http_port}/webrtc")
    offer_path = cfg.get("webrtc_offer_path", "/webrtc/offer")

    logger.info("WebRTC 尝试连接: %s", signaling_url)

    try:
        import asyncio

        async def _pull_one_frame() -> Optional[bytes]:
            pc = RTCPeerConnection()
            received_frame = None

            @pc.on("track")
            def on_track(track):
                nonlocal received_frame
                if track.kind == "video":
                    # 读取第一帧
                    try:
                        frame = asyncio.get_event_loop().run_until_complete(
                            asyncio.wait_for(track.recv(), timeout=5.0)
                        )
                        received_frame = frame
                    except Exception as e:
                        logger.warning("WebRTC 收帧异常: %s", e)

            # 生成 offer
            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)

            # 发送 offer 到信令接口（HTTP POST）
            import requests
            try:
                resp = requests.post(
                    f"http://{ip}:{http_port}{offer_path}",
                    json={"sdp": offer.sdp},
                    timeout=cfg["request_timeout"],
                )
                if resp.status_code != 200:
                    logger.warning("WebRTC offer 请求失败: HTTP %d", resp.status_code)
                    return None
                answer_data = resp.json()
                answer = RTCSessionDescription(sdp=answer_data["sdp"], type="answer")
            except Exception as e:
                logger.warning("WebRTC 信令交换失败: %s", e)
                return None

            await pc.setRemoteDescription(answer)

            # 等待第一帧（最多 5 秒）
            await asyncio.sleep(3)

            if received_frame is None:
                logger.warning("WebRTC 未在 3 秒内收到视频帧")
                await pc.close()
                return None

            # 转换为 JPEG
            try:
                import cv2
                img = received_frame.to_ndarray(format="bgr24")
                _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
                await pc.close()
                return buf.tobytes()
            except Exception as e:
                logger.warning("WebRTC 帧编码失败: %s", e)
                await pc.close()
                return None

        return asyncio.run(_pull_one_frame())

    except Exception as e:
        logger.warning("WebRTC 图传异常: %s", e)
        return None


# ------------------------------------------------------------------
# 配置扩展（新增 WebRTC 相关项）
# ------------------------------------------------------------------

def _load_network_config(config: dict) -> dict:
    """从 config 中提取网络图传配置项，缺失时用内置默认值。"""
    cam = config.get("camera", {})
    return {
        "network_mode": cam.get("network_mode", "auto"),
        "ip": cam.get("huskylens_ip", ""),
        "http_port": int(cam.get("http_port", 80)),
        "snapshot_path": cam.get("snapshot_path", "/snapshot"),
        "stream_path": cam.get("stream_path", "/stream"),
        "rtsp_port": int(cam.get("rtsp_port", 554)),
        "request_timeout": float(cam.get("request_timeout", 5)),
        "save_path": cam.get("save_path", "data/captures"),
        # WebRTC 配置（可选）
        "webrtc_signalling_url": cam.get("webrtc_signalling_url", ""),
        "webrtc_offer_path": cam.get("webrtc_offer_path", "/webrtc/offer"),
    }
