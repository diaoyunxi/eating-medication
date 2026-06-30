# -*- coding: utf-8 -*-
"""
AI 助手模块测试
"""
import pytest

def test_ai_chat(client, auth_headers):
    """测试 AI 问答"""
    response = client.post("/api/v1/ai/chat", headers=auth_headers, json={
        "question": "高血压患者应该注意什么？"
    })
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert isinstance(data["answer"], str)

def test_ai_chat_empty_question(client, auth_headers):
    """测试空问题"""
    response = client.post("/api/v1/ai/chat", headers=auth_headers, json={
        "question": ""
    })
    assert response.status_code == 422

def test_ai_chat_unauthorized(client):
    """测试未认证不能访问 AI"""
    response = client.post("/api/v1/ai/chat", json={
        "question": "测试问题"
    })
    assert response.status_code == 401