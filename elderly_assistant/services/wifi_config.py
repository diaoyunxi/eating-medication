#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WiFi 配网 Web 服务模块
用于 M10 设备：在热点上运行 HTTP 服务器（端口 8088），提供配网页面。
用户提交后：
  1. 保存服务器地址到 config.yaml
  2. 使用 nmcli 命令连接指定 WiFi
  3. 调用 device_id 获取 FCC ID，POST 注册到服务器
  4. 返回成功/失败状态
"""

import os
import json
import subprocess
import threading
import time
import re
import secrets
import html
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import logging
from utils.config_loader import load_config, save_config

logger = logging.getLogger("ElderlyAssistant")

# 配网 Web 服务端口（与热点管理器保持一致）
CONFIG_PORT = 8088
HOTSPOT_SSID = "M10-Config"
# CORS 允许来源：仅限本地热点网关，避免任意来源跨域请求
CONFIG_CORS_ORIGIN = "http://10.0.0.1:8088"

# 设备主程序所在目录（用于读取/写入 config.yaml）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sanitize_ssid(ssid: str) -> str:
    """清理 SSID，移除非法字符（防止命令注入）"""
    return re.sub(r'[\"\\\'`$\n\r]', '', ssid)[:32]


def sanitize_password(password: str) -> str:
    """清理密码，移除非法字符（防止命令注入）"""
    return re.sub(r'[\"\\\'`$\n\r]', '', password)


class WiFiConfigManager:
    """配网业务管理器"""

    def __init__(self):
        # idle / scanning / connecting / success / failed
        self.status = "idle"
        self.status_message = ""
        self.scanned_networks = []
        self.current_ssid = ""
        self._scan_lock = threading.Lock()

    def load_server_url(self):
        """从 config.yaml 读取当前服务器地址"""
        try:
            config = load_config()
            return config.get('server', {}).get('base_url', '')
        except Exception as e:
            logger.error(f"读取服务器地址失败: {e}")
            return ''

    def save_server_url(self, server_url):
        """保存服务器地址到 config.yaml"""
        try:
            config = load_config()
            config.setdefault('server', {})['base_url'] = server_url
            save_config(config)
            logger.info(f"已保存服务器地址: {server_url}")
            return True
        except Exception as e:
            logger.error(f"保存服务器地址失败: {e}")
            return False

    def scan_wifi(self):
        """扫描可用 WiFi 网络（使用 nmcli）"""
        with self._scan_lock:
            self.status = "scanning"
            self.status_message = "正在扫描 WiFi..."
            self.scanned_networks = []

        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                seen = set()
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    parts = line.split(':')
                    if len(parts) >= 3:
                        ssid = parts[0]
                        signal = int(parts[1]) if parts[1].isdigit() else 0
                        security = parts[2] if len(parts) > 2 else "open"
                        if ssid and ssid not in seen:
                            seen.add(ssid)
                            self.scanned_networks.append({
                                "ssid": ssid,
                                "signal": signal,
                                "security": security
                            })

            self.scanned_networks = sorted(
                self.scanned_networks, key=lambda x: x["signal"], reverse=True
            )
            self.status = "idle"
            self.status_message = "找到 %d 个 WiFi 网络" % len(self.scanned_networks)
        except Exception as e:
            logger.error(f"扫描 WiFi 失败: {e}")
            self.status = "failed"
            self.status_message = "扫描失败: %s" % str(e)

        return self.scanned_networks

    def connect_wifi(self, ssid, password):
        """使用 nmcli 连接到指定 WiFi"""
        safe_ssid = sanitize_ssid(ssid)
        safe_password = sanitize_password(password)

        self.status = "connecting"
        self.status_message = "正在连接 %s..." % safe_ssid
        self.current_ssid = safe_ssid

        try:
            # 使用列表形式传递参数，避免 shell 注入
            result = subprocess.run(
                ["nmcli", "dev", "wifi", "connect", safe_ssid, "password", safe_password],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                self.status = "success"
                self.status_message = "成功连接到 %s" % safe_ssid
                return True
            else:
                raise Exception(result.stderr or "连接失败")
        except Exception as e:
            logger.error(f"连接 WiFi 失败: {e}")
            self.status = "failed"
            self.status_message = "连接失败: %s" % str(e)
            return False

    def register_device_to_server(self, server_url):
        """
        获取设备 FCC ID 并注册到服务器
        :return: (success: bool, message: str, device_id: str)
        """
        try:
            # 延迟导入，避免在模块加载时就触发 pinpong 初始化
            from services.device_id import get_device_id
            from services.http_client import HTTPClient

            device_id = get_device_id()
            logger.info(f"获取设备 FCC ID: {device_id}")

            # 构造临时 config，使用用户配置的 server_url
            tmp_config = load_config()
            tmp_config.setdefault('server', {})['base_url'] = server_url

            http_client = HTTPClient(tmp_config)
            ok = http_client.register_device(device_name="M10-老人端")
            if ok:
                return True, "设备注册成功", device_id
            else:
                return False, "设备注册失败（服务器无响应或地址错误）", device_id
        except Exception as e:
            logger.error(f"设备注册异常: {e}")
            return False, f"设备注册异常: {e}", ""


# 单例管理器（HTTP 处理器共享）
_WIFI_MANAGER = WiFiConfigManager()


class WiFiConfigHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器"""

    # 通过类属性共享 manager，避免每次请求新建
    wifi_manager = _WIFI_MANAGER
    # 配网 Token（由 WiFiConfigServer 启动时生成并设置），用于校验 POST 请求
    config_token = None

    def do_GET(self):
        """处理 GET 请求"""
        parsed_path = urlparse(self.path)

        if parsed_path.path == '/' or parsed_path.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(self._get_html_page().encode('utf-8'))
        elif parsed_path.path == '/api/scan':
            # /api/scan 同样校验 config_token，防止未授权扫描
            if not self._verify_config_token():
                self._send_json({"status": "error", "message": "未授权"}, 403)
                return
            networks = self.wifi_manager.scan_wifi()
            self._send_json({"status": "ok", "networks": networks})
        elif parsed_path.path == '/api/status':
            self._send_json({
                "status": self.wifi_manager.status,
                "message": self.wifi_manager.status_message
            })
        elif parsed_path.path == '/api/config':
            # /api/config 返回服务器地址属于敏感信息，需校验 config_token
            if not self._verify_config_token():
                self._send_json({"status": "error", "message": "未授权"}, 403)
                return
            self._send_json({
                "server_url": self.wifi_manager.load_server_url()
            })
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        """处理 POST 请求"""
        # 校验配网 Token，防止未授权的 POST 请求（校验不通过返回 403）
        if not self._verify_config_token():
            self._send_json(
                {"status": "error", "message": "未授权：缺少或错误的 X-Config-Token"},
                403
            )
            return

        parsed_path = urlparse(self.path)

        if parsed_path.path == '/api/connect':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            try:
                # 兼容 JSON 与表单提交
                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    data = {k: v[0] for k, v in parse_qs(body).items()}

                ssid = data.get('ssid', '').strip()
                password = data.get('password', '')
                server_url = data.get('server_url', '').strip()

                if not ssid:
                    self._send_json({"status": "error", "message": "请填写 WiFi 名称"}, 400)
                    return
                if not server_url:
                    self._send_json({"status": "error", "message": "请填写服务器地址"}, 400)
                    return

                # 1. 保存服务器地址到 config.yaml
                self.wifi_manager.save_server_url(server_url)

                # 2. 连接 WiFi
                wifi_ok = self.wifi_manager.connect_wifi(ssid, password)
                if not wifi_ok:
                    self._send_json({
                        "status": "error",
                        "message": self.wifi_manager.status_message,
                        "device_id": ""
                    })
                    return

                # 3. 获取 FCC ID 并注册到服务器
                reg_ok, reg_msg, device_id = self.wifi_manager.register_device_to_server(server_url)

                self._send_json({
                    "status": "success" if reg_ok else "error",
                    "message": reg_msg,
                    "device_id": device_id,
                    "wifi_ssid": ssid
                })
            except Exception as e:
                logger.error(f"配网处理异常: {e}")
                self._send_json({"status": "error", "message": str(e)}, 500)
        else:
            self.send_error(404, "Not Found")

    def _verify_config_token(self):
        """校验 POST 请求中的 X-Config-Token（Header 或 Form 字段）

        服务启动时生成随机 token，所有 POST 请求需在 Header 中携带
        X-Config-Token，校验不通过返回 403。
        token 未设置时拒绝所有 POST 请求（fail-closed），防止认证绕过。
        """
        token = self.config_token
        if not token:
            # token 未设置时拒绝（fail-closed），不放过任何未授权请求
            logger.error("配网 token 未初始化，拒绝 POST 请求")
            return False
        # 优先从 Header 读取 X-Config-Token
        req_token = self.headers.get('X-Config-Token', '')
        # 使用常量时间比较防止时序攻击
        return secrets.compare_digest(req_token, token)

    def _send_json(self, data, status_code=200):
        """发送 JSON 响应"""
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        # CORS 限制为本地热点网关，避免任意来源跨域请求
        self.send_header('Access-Control-Allow-Origin', CONFIG_CORS_ORIGIN)
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def _get_html_page(self):
        """生成配置页面 HTML"""
        server_url = self.wifi_manager.load_server_url()
        # 对 server_url 进行 HTML 转义后再插入 HTML，防止 XSS
        safe_server_url = html.escape(server_url or '', quote=True)
        # config_token 嵌入前端供 fetch 携带。
        # 安全性依赖网络隔离：配网服务已绑定热点接口 10.0.0.1，仅连接热点的设备可访问。
        # 彻底修复应改为前端不持有 token、使用 session cookie，此处为最小改动保留实现。
        safe_config_token = html.escape(self.config_token or '', quote=True)
        html_content = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>M10 设备配网</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; padding: 20px; }
        .container { max-width: 420px; margin: 0 auto; background: white; border-radius: 16px; padding: 30px; box-shadow: 0 10px 40px rgba(0,0,0,0.2); }
        h1 { text-align: center; color: #333; margin-bottom: 8px; font-size: 22px; }
        p.subtitle { text-align: center; color: #666; margin-bottom: 25px; font-size: 14px; }
        .form-group { margin-bottom: 18px; }
        label { display: block; margin-bottom: 8px; color: #333; font-weight: 500; font-size: 14px; }
        input, select { width: 100%; padding: 12px; border: 2px solid #e0e0e0; border-radius: 8px; font-size: 16px; transition: border-color 0.3s; }
        input:focus, select:focus { border-color: #667eea; outline: none; }
        button { width: 100%; padding: 14px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; transition: transform 0.2s; }
        button:hover { transform: translateY(-2px); }
        button:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
        #status { margin-top: 20px; padding: 15px; border-radius: 8px; display: none; font-size: 14px; }
        #status.success { background: #d4edda; color: #155724; }
        #status.error { background: #f8d7da; color: #721c24; }
        #status.info { background: #d1ecf1; color: #0c5460; }
        .wifi-list { max-height: 180px; overflow-y: auto; margin-bottom: 15px; border: 1px solid #e0e0e0; border-radius: 8px; padding: 8px; }
        .wifi-item { padding: 10px; border-radius: 6px; margin-bottom: 4px; cursor: pointer; transition: all 0.2s; }
        .wifi-item:hover { background: #f8f9ff; }
        .wifi-item.selected { background: #eef2ff; border: 1px solid #667eea; }
        .wifi-name { font-weight: 500; }
        .wifi-signal { float: right; color: #888; font-size: 12px; }
        .scan-btn { background: #6c757d; margin-bottom: 10px; }
        .hint { font-size: 12px; color: #999; margin-top: 4px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>M10 设备配网</h1>
        <p class="subtitle">配置 WiFi 与服务器地址</p>

        <button onclick="scanWiFi()" id="scanBtn" class="scan-btn">扫描 WiFi</button>

        <div class="wifi-list" id="wifiList">
            <p style="text-align: center; color: #999; padding: 20px 0;">点击上方按钮扫描 WiFi</p>
        </div>

        <div class="form-group">
            <label for="ssid">WiFi 名称</label>
            <input type="text" id="ssid" placeholder="可手动输入或点击上方列表选择">
        </div>

        <div class="form-group">
            <label for="password">WiFi 密码</label>
            <input type="password" id="password" placeholder="请输入 WiFi 密码">
        </div>

        <div class="form-group">
            <label for="serverUrl">服务器地址</label>
            <input type="text" id="serverUrl" placeholder="如 https://my-website.ccwu.cc/eating-medication/server" value="__SERVER_URL__">
            <div class="hint">提交后将保存地址、连接 WiFi 并注册设备到服务器</div>
        </div>

        <button onclick="submitConfig()" id="connectBtn">提交并连接</button>

        <div id="status"></div>
    </div>

    <script>
        // 配网 Token，由服务端生成并嵌入；所有 POST 请求需携带以防未授权请求
        const CONFIG_TOKEN = "__CONFIG_TOKEN__";

        function scanWiFi() {
            const btn = document.getElementById('scanBtn');
            btn.disabled = true;
            btn.textContent = '扫描中...';
            fetch('/api/scan')
                .then(res => res.json())
                .then(data => {
                    if (data.status === 'ok') displayWiFiList(data.networks);
                    else showStatus('扫描失败', 'error');
                    btn.disabled = false;
                    btn.textContent = '扫描 WiFi';
                })
                .catch(err => {
                    showStatus('扫描失败: ' + err, 'error');
                    btn.disabled = false;
                    btn.textContent = '扫描 WiFi';
                });
        }

        function displayWiFiList(networks) {
            const list = document.getElementById('wifiList');
            if (!networks || networks.length === 0) {
                list.innerHTML = '<p style="text-align: center; color: #999; padding: 20px 0;">未找到 WiFi 网络</p>';
                return;
            }
            list.innerHTML = networks.map(n => {
                const sig = Math.min(n.signal, 100);
                return '<div class="wifi-item" onclick="selectWiFi(this, \\'' + escapeHtml(n.ssid) + '\\')">' +
                    '<span class="wifi-name">' + escapeHtml(n.ssid) + '</span>' +
                    '<span class="wifi-signal">信号 ' + sig + '% · ' + escapeHtml(n.security || '') + '</span>' +
                    '</div>';
            }).join('');
        }

        function selectWiFi(el, ssid) {
            document.querySelectorAll('.wifi-item').forEach(i => i.classList.remove('selected'));
            el.classList.add('selected');
            document.getElementById('ssid').value = ssid;
        }

        function submitConfig() {
            const ssid = document.getElementById('ssid').value.trim();
            const password = document.getElementById('password').value;
            const serverUrl = document.getElementById('serverUrl').value.trim();

            if (!ssid) { showStatus('请填写或选择 WiFi 名称', 'error'); return; }
            if (!serverUrl) { showStatus('请填写服务器地址', 'error'); return; }

            const btn = document.getElementById('connectBtn');
            btn.disabled = true;
            btn.textContent = '配置中...';
            showStatus('正在保存地址、连接 WiFi 并注册设备，请稍候...', 'info');

            fetch('/api/connect', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Config-Token': CONFIG_TOKEN },
                body: JSON.stringify({ ssid: ssid, password: password, server_url: serverUrl })
            })
            .then(res => res.json())
            .then(data => {
                if (data.status === 'success') {
                    showStatus('配置成功！设备ID: ' + (data.device_id || '') + '，即将重启服务', 'success');
                } else {
                    showStatus(data.message || '配置失败', 'error');
                }
                btn.disabled = false;
                btn.textContent = '提交并连接';
            })
            .catch(err => {
                showStatus('请求失败: ' + err, 'error');
                btn.disabled = false;
                btn.textContent = '提交并连接';
            });
        }

        function showStatus(message, type) {
            const s = document.getElementById('status');
            s.textContent = message;
            s.className = type;
            s.style.display = 'block';
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text == null ? '' : text;
            return div.innerHTML;
        }
    </script>
</body>
</html>
""".replace("__SERVER_URL__", safe_server_url) \
         .replace("__CONFIG_TOKEN__", safe_config_token)
        return html_content

    def log_message(self, format, *args):
        """自定义日志格式"""
        logger.info("HTTP %s - %s" % (self.address_string(), format % args))


class WiFiConfigServer:
    """WiFi 配网 Web 服务器"""

    def __init__(self, port=CONFIG_PORT):
        self.port = port
        self.server = None
        self.server_thread = None
        self.running = False
        # 配网 Token，启动时生成
        self.config_token = None

    def start(self):
        """启动服务器（在独立线程中运行）"""
        try:
            # 生成随机配网 token，所有 POST 请求需携带 X-Config-Token 校验
            self.config_token = secrets.token_urlsafe(16)
            WiFiConfigHandler.config_token = self.config_token
            logger.info(f"配网服务 Token: {self.config_token}")
            print(f"[配网] X-Config-Token: {self.config_token}")

            # 绑定热点接口 IP 10.0.0.1，避免暴露到所有网卡（0.0.0.0）
            server_address = ('10.0.0.1', self.port)
            self.server = HTTPServer(server_address, WiFiConfigHandler)
            self.running = True

            self.server_thread = threading.Thread(target=self._run_server, daemon=True)
            self.server_thread.start()

            logger.info(f"WiFi 配网服务已启动，端口: {self.port}")
            logger.info(f"请连接热点 {HOTSPOT_SSID} 后访问 http://10.0.0.1:{self.port}")
            return True
        except Exception as e:
            logger.error(f"启动 WiFi 配网服务失败: {e}")
            return False

    def _run_server(self):
        """服务器主循环"""
        while self.running:
            try:
                self.server.handle_request()
            except Exception as e:
                if self.running:
                    logger.error(f"服务器错误: {e}")

    def stop(self):
        """停止服务器"""
        self.running = False
        if self.server:
            try:
                self.server.socket.close()
            except Exception:
                pass
        logger.info("WiFi 配网服务已停止")


def main():
    """独立运行入口（测试用）"""
    server = WiFiConfigServer()
    if server.start():
        print(f"WiFi 配网服务已启动，访问 http://localhost:{CONFIG_PORT}")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            server.stop()
            print("服务已停止")


if __name__ == "__main__":
    main()
