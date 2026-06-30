# -*- coding: utf-8 -*-
"""
WebSocket 模块测试
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.security import create_access_token

def test_websocket_connection():
    """测试 WebSocket 连接"""
    token = create_access_token(data={"sub": 1})
    client = TestClient(app)
    
    with client.websocket_connect(f"/ws/ws?token={token}") as websocket:
        # 发送心跳
        websocket.send_text("ping")
        # 接收响应
        data = websocket.receive_text()
        assert data == "pong"

def test_websocket_invalid_token():
    """测试无效 token 连接失败"""
    client = TestClient(app)
    
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/ws?token=invalid_token"):
            pass