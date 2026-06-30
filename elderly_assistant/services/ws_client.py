# -*- coding: utf-8 -*-
import json
import threading
import time
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class WebSocketClient:
    """WebSocket 客户端，用于与服务端保持长连接并接收消息"""
    
    def __init__(self, base_url, device_id, on_message_callback=None):
        self.base_url = base_url.replace('http://', 'ws://').replace('https://', 'wss://')
        self.device_id = device_id
        self.on_message_callback = on_message_callback
        self.ws = None
        self.connected = False
        self.running = False
        self.thread = None
        self.messages = []
        self.max_messages = 100
        
    def connect(self):
        if self.connected:
            return
        try:
            import websocket
            ws_url = f"{self.base_url}/ws/device/{self.device_id}"
            self.ws = websocket.WebSocketApp(
                ws_url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close
            )
            self.running = True
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()
        except ImportError:
            logger.error("未安装 websocket-client 库")
            self.connected = False
        except Exception as e:
            logger.error(f"WebSocket 连接失败: {e}")
            self.connected = False
            
    def _run_loop(self):
        while self.running:
            try:
                self.ws.run_forever()
            except Exception as e:
                logger.error(f"WebSocket 运行错误: {e}")
            if self.running:
                time.sleep(5)
                
    def _on_open(self, ws):
        self.connected = True
        
    def _on_message(self, ws, message):
        try:
            msg_data = json.loads(message)
            self.messages.append(msg_data)
            if len(self.messages) > self.max_messages:
                self.messages = self.messages[-self.max_messages:]
            if self.on_message_callback:
                self.on_message_callback(msg_data)
        except json.JSONDecodeError:
            pass
            
    def _on_error(self, ws, error):
        logger.error(f"WebSocket 错误: {error}")
        
    def _on_close(self, ws, close_status_code, close_msg):
        self.connected = False
        
    def disconnect(self):
        self.running = False
        if self.ws:
            self.ws.close()
        self.connected = False
        
    def send_message(self, message_type, content, data=None):
        if not self.connected:
            return False
        try:
            msg = {
                'type': message_type,
                'content': content,
                'timestamp': datetime.now().isoformat()
            }
            if data:
                msg['data'] = data
            self.ws.send(json.dumps(msg))
            return True
        except Exception:
            return False
            
    def get_messages(self, limit=20):
        return self.messages[-limit:] if self.messages else []
        
    def clear_messages(self):
        self.messages = []
