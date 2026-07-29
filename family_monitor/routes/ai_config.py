# -*- coding: utf-8 -*-
"""子女端 AI 助手配置代理路由

将子女端的 AI 配置请求转发到服务端（server），并以当前登录用户的 JWT 进行鉴权。
配置实际存储在服务端的 user_ai_configs 表中（每用户各自配置），不在 .env 中。
"""
import logging
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core import elderly_client
from routes.web_helpers import require_login, unauthorized_json, user_api_request

logger = logging.getLogger(__name__)

router = APIRouter()


def _bound_device_id() -> Optional[str]:
    """获取当前账号已绑定的老人端设备ID（用于按设备指定被照护老人的 AI 配置）"""
    bound = elderly_client.get_bound_device()
    if bound:
        return bound.get("device_id")
    return None





@router.get("/settings/ai-providers")
async def ai_providers(request: Request):
    """获取 AI 厂商预设列表（供前端下拉）"""
    if not require_login(request):
        return unauthorized_json()
    token = request.cookies.get("access_token") or ""
    status, data = await user_api_request("GET", "/ai/providers", token=token)
    if status == 200:
        return JSONResponse(content={"success": True, "providers": data})
    return JSONResponse(content={"success": False, "message": "获取厂商列表失败"}, status_code=status)


@router.get("/settings/ai-config")
async def get_ai_config(request: Request):
    """读取当前用户（或所绑定老人设备）的 AI 配置"""
    if not require_login(request):
        return unauthorized_json()
    token = request.cookies.get("access_token") or ""
    device_id = _bound_device_id()
    params = {"device_id": device_id} if device_id else {}
    status, data = await user_api_request("GET", "/user/ai-config", token=token, params=params)
    if status == 200:
        data["success"] = True
        return JSONResponse(content=data)
    return JSONResponse(content={"success": False, "message": "读取 AI 配置失败"}, status_code=status)


@router.post("/settings/ai-config")
async def save_ai_config(request: Request):
    """保存当前用户（或所绑定老人设备）的 AI 配置"""
    if not require_login(request):
        return unauthorized_json()
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(content={"success": False, "message": "请求体格式错误"}, status_code=400)

    # 基础校验
    provider = (payload.get("provider") or "").strip()
    if not provider:
        return JSONResponse(content={"success": False, "message": "请选择 AI 厂商"}, status_code=400)

    token = request.cookies.get("access_token") or ""
    device_id = _bound_device_id()
    params = {"device_id": device_id} if device_id else {}
    body = {
        "provider": provider,
        "api_key": payload.get("api_key", ""),
        "model": payload.get("model", ""),
        "base_url": payload.get("base_url", ""),
        "enabled": bool(payload.get("enabled", True)),
    }
    status, data = await user_api_request("PUT", "/user/ai-config", token=token, params=params, json_body=body)
    if status == 200:
        # 不回传 api_key 明文
        data.pop("api_key", None)
        data["success"] = True
        return JSONResponse(content=data)
    msg = (data or {}).get("detail") or "保存失败"
    return JSONResponse(content={"success": False, "message": str(msg)}, status_code=status)
