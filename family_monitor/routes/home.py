# -*- coding: utf-8 -*-
"""
首页路由 - 完善版
"""

import logging
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import JSONResponse
from core import config, elderly_client
from services.medication_service import validate_and_build
from routes.web_helpers import templates, require_login, login_redirect, unauthorized_json, family_client

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/")
async def index(request: Request):
    """首页"""
    if not require_login(request):
        return login_redirect()
    fc = family_client(request) or elderly_client
    status = await elderly_client.get_server_status()
    device_info = await fc.get_device_info()
    # 获取仪表板数据，用于首页 Hero 统计与最近活动展示（替换原硬编码虚拟数据）
    dashboard_data = await fc.get_dashboard_data()

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "app_name": config.APP_NAME,
            "status": status,
            "device_info": device_info,
            "dashboard": dashboard_data
        }
    )


@router.get("/status")
async def get_status(request: Request):
    """获取设备真实在线状态（供前端轮询）

    原实现返回 get_server_status()（仅服务器健康检查 GET /health），
    导致设备离线但服务器存活时前端仍显示"设备在线"。
    现改用 get_device_info() 返回真实设备在线状态（基于服务端心跳超时判断）。
    """
    if not require_login(request):
        return unauthorized_json()
    fc = family_client(request) or elderly_client
    device_info = await fc.get_device_info()
    return {
        'connected': device_info.get('connected', False),
        'device_id': device_info.get('device_id'),
        'device_name': device_info.get('device_name'),
        'status': device_info.get('status', 'offline'),
        'last_heartbeat': device_info.get('last_heartbeat'),
        'last_check': device_info.get('last_check')
    }


@router.get("/reminders")
async def get_reminders(request: Request):
    """提醒页面"""
    if not require_login(request):
        return login_redirect()
    fc = family_client(request) or elderly_client
    reminders = await fc.get_reminders()
    status = await elderly_client.get_server_status()
    device_info = await fc.get_device_info()

    return templates.TemplateResponse(
        "reminders.html",
        {
            "request": request,
            "app_name": config.APP_NAME,
            "reminders": reminders,
            "status": status,
            "device_info": device_info
        }
    )


@router.get("/records")
async def get_records(request: Request):
    """用药记录页面"""
    if not require_login(request):
        return login_redirect()
    fc = family_client(request) or elderly_client
    records = await fc.get_medication_records()
    status = await elderly_client.get_server_status()
    device_info = await fc.get_device_info()

    return templates.TemplateResponse(
        "records.html",
        {
            "request": request,
            "app_name": config.APP_NAME,
            "records": records,
            "status": status,
            "device_info": device_info
        }
    )


@router.get("/dashboard")
async def get_dashboard(request: Request):
    """仪表板页面"""
    if not require_login(request):
        return login_redirect()
    fc = family_client(request) or elderly_client
    status = await elderly_client.get_server_status()
    device_info = await fc.get_device_info()
    dashboard_data = await fc.get_dashboard_data()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "app_name": config.APP_NAME,
            "status": status,
            "device_info": device_info,
            "dashboard": dashboard_data
        }
    )


@router.get("/settings")
async def get_settings(request: Request):
    """设置页面"""
    if not require_login(request):
        return login_redirect()
    fc = family_client(request) or elderly_client
    status = await elderly_client.get_server_status()
    device_info = await fc.get_device_info()
    bound_device = elderly_client.get_bound_device()

    return templates.TemplateResponse("settings.html", {
            "request": request,
            "app_name": config.APP_NAME,
            "status": status,
            "device_info": device_info,
            "bound_device": bound_device,})


@router.post("/settings/bind_device")
async def bind_device(request: Request, device_id: str = Form(...), device_name: str = Form("")):
    """绑定设备（通过device_id）

    绑定前先调用服务端的 check_device 接口校验设备是否已注册，
    若设备未注册则返回明确错误，避免绑定到不存在的设备。
    """
    # G11：显式校验登录
    if not require_login(request):
        return JSONResponse(content={"success": False, "message": "请先登录"}, status_code=401)
    fc = family_client(request) or elderly_client
    try:
        # 1. 先校验设备是否已在服务端注册
        check_result = await elderly_client.check_device(device_id)
        if not check_result.get("success"):
            return JSONResponse(content={
                "success": False,
                "message": f"设备校验失败: {check_result.get('error', '服务端不可达')}"
            }, status_code=400)

        device_data = check_result.get("data") or {}
        if not device_data.get("exists", False):
            return JSONResponse(content={
                "success": False,
                "message": "设备未注册，请先在老人端完成配网"
            }, status_code=400)

        # 2. 校验通过后，通过家属授权接口绑定设备并合法获取设备令牌。
        #    此前复用设备令牌接口（已注册设备不再下发令牌）导致子女端拿到
        #    空令牌、/device/status 返回 403、状态显示离线。改用 family_client
        #    的 bind_device_family，server 端校验设备已注册后将当前账号绑定该
        #    设备并返回设备令牌，从根本上解决空令牌问题。
        result = await fc.bind_device_family(device_id, device_name)
        if result.get("status") == "ok":
            token = result.get("device_token", "")
            elderly_client.save_bound_device(device_id, device_name, token)
            return JSONResponse(content={
                "success": True,
                "message": f"设备 {device_name or device_id} 绑定成功"
            })
        else:
            return JSONResponse(content={
                "success": False,
                "message": f"绑定失败: {result.get('msg', '未知错误')}"
            }, status_code=400)
    except Exception as e:
        logger.exception("绑定设备失败")
        raise HTTPException(status_code=500, detail="服务器内部错误，请稍后重试")


@router.get("/medication_settings")
async def medication_settings(request: Request):
    """用药设置页面"""
    if not require_login(request):
        return login_redirect()
    fc = family_client(request) or elderly_client
    status = await elderly_client.get_server_status()
    device_info = await fc.get_device_info()
    plans = await fc.get_device_plans()

    return templates.TemplateResponse("medication_settings.html", {
        "request": request,
        "app_name": config.APP_NAME,
        "status": status,
        "device_info": device_info,
        "plans": plans,
    })


@router.post("/medication_settings/add")
async def add_medication_plan(request: Request):
    """添加用药计划

    接收 JSON 表单数据并调用服务端设置用药计划。
    """
    if not require_login(request):
        return unauthorized_json()
    fc = family_client(request) or elderly_client
    try:
        # 解析 JSON 请求体
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse(content={
                "success": False,
                "message": "请求体格式错误，需要 JSON 数据"
            }, status_code=400)

        fields, error = validate_and_build(payload)
        if error:
            return JSONResponse(content={"success": False, "message": error}, status_code=400)

        result = await fc.set_medication_plan(**fields)

        if result.get("success"):
            drug_name = fields.get('drug_name', '药品')
            return JSONResponse(content={
                "success": True,
                "message": f"用药计划 {drug_name} 添加成功"
            })
        else:
            return JSONResponse(content={
                "success": False,
                "message": f"添加失败: {result.get('error', '未知错误')}"
            }, status_code=400)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("添加用药计划失败")
        raise HTTPException(status_code=500, detail="服务器内部错误，请稍后重试")


@router.post("/medication_settings/delete/{plan_id}")
async def delete_medication_plan(request: Request, plan_id: int):
    """删除用药计划"""
    if not require_login(request):
        return unauthorized_json()
    fc = family_client(request) or elderly_client
    try:
        result = await fc.delete_medication_plan(plan_id)
        if result.get("success"):
            return JSONResponse(content={
                "success": True,
                "message": "用药计划已删除"
            })
        else:
            return JSONResponse(content={
                "success": False,
                "message": f"删除失败: {result.get('error', '未知错误')}"
            }, status_code=400)
    except Exception as e:
        logger.exception("删除用药计划失败")
        raise HTTPException(status_code=500, detail="服务器内部错误，请稍后重试")


@router.post("/medication_settings/update/{plan_id}")
async def update_medication_plan(request: Request, plan_id: int):
    """更新用药计划

    接收 JSON 表单数据并调用服务端更新用药计划。
    """
    if not require_login(request):
        return unauthorized_json()
    fc = family_client(request) or elderly_client
    try:
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse(content={
                "success": False,
                "message": "请求体格式错误，需要 JSON 数据"
            }, status_code=400)

        fields, error = validate_and_build(payload)
        if error:
            return JSONResponse(content={"success": False, "message": error}, status_code=400)

        result = await fc.update_medication_plan(plan_id=plan_id, **fields)

        if result.get("success"):
            drug_name = fields.get('drug_name', '药品')
            return JSONResponse(content={
                "success": True,
                "message": f"用药计划 {drug_name} 更新成功"
            })
        else:
            return JSONResponse(content={
                "success": False,
                "message": f"更新失败: {result.get('error', '未知错误')}"
            }, status_code=400)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("更新用药计划失败")
        raise HTTPException(status_code=500, detail="服务器内部错误，请稍后重试")


@router.post("/settings/unbind_device")
async def unbind_device(request: Request):
    """解绑设备"""
    if not require_login(request):
        return unauthorized_json()
    fc = family_client(request) or elderly_client
    try:
        elderly_client.clear_bound_device()
        return JSONResponse(content={
            "success": True,
            "message": "设备已解绑"
        })
    except Exception as e:
        logger.exception("解绑设备失败")
        raise HTTPException(status_code=500, detail="服务器内部错误，请稍后重试")
