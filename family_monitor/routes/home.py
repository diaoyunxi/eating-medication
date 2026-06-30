# -*- coding: utf-8 -*-
"""
首页路由 - 完善版
"""

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from core import config, elderly_client
from core.session import get_session_manager

router = APIRouter()
templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))
# 禁用 Jinja2 缓存以避免网络驱动器上的缓存问题
templates.env.cache = {}
# 注入路径前缀变量，供模板链接加前缀
templates.env.globals["prefix"] = config.PATH_PREFIX


@router.get("/")
async def index(request: Request):
    """首页"""
    status = await elderly_client.get_server_status()
    device_info = await elderly_client.get_device_info()
    
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "app_name": config.APP_NAME,
            "status": status,
            "device_info": device_info
        }
    )


@router.get("/status")
async def get_status():
    """获取服务器状态"""
    status = await elderly_client.get_server_status()
    return status


@router.get("/reminders")
async def get_reminders(request: Request):
    """提醒页面"""
    reminders = await elderly_client.get_reminders()
    status = await elderly_client.get_server_status()
    device_info = await elderly_client.get_device_info()
    
    return templates.TemplateResponse(
        request,
        "reminders.html",
        {
            "app_name": config.APP_NAME,
            "reminders": reminders,
            "status": status,
            "device_info": device_info
        }
    )


@router.get("/records")
async def get_records(request: Request):
    """用药记录页面"""
    records = await elderly_client.get_medication_records()
    status = await elderly_client.get_server_status()
    device_info = await elderly_client.get_device_info()
    
    return templates.TemplateResponse(
        request,
        "records.html",
        {
            "app_name": config.APP_NAME,
            "records": records,
            "status": status,
            "device_info": device_info
        }
    )


@router.get("/dashboard")
async def get_dashboard(request: Request):
    """仪表板页面"""
    status = await elderly_client.get_server_status()
    device_info = await elderly_client.get_device_info()
    dashboard_data = await elderly_client.get_dashboard_data()
    
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "app_name": config.APP_NAME,
            "status": status,
            "device_info": device_info,
            "dashboard": dashboard_data
        }
    )


@router.get("/settings")
async def get_settings(request: Request):
    """设置页面"""
    status = await elderly_client.get_server_status()
    device_info = await elderly_client.get_device_info()
    bound_device = elderly_client.get_bound_device()

    return templates.TemplateResponse(request, "settings.html", {
            "app_name": config.APP_NAME,
            "status": status,
            "device_info": device_info,
            "current_server_url": config.ELDERLY_SERVER_URL,
            "current_api_key": config.API_KEY,
            "bound_device": bound_device,
            'display_settings': config.DISPLAY_SETTINGS,})


@router.post("/settings/server")
async def update_server_settings(request: Request, server_url: str = Form(...), api_key: str = Form("")):
    """更新服务器设置"""
    try:
        config.ELDERLY_SERVER_URL = server_url
        config.API_KEY = api_key
        config.save_config()
        elderly_client.base_url = server_url
        return JSONResponse(content={
            "success": True,
            "message": "服务器设置已更新"
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/settings/display")
async def update_display_settings(
    request: Request,
    theme: str = Form("light"),
    color: str = Form("purple"),
    language: str = Form("zh-CN"),
    animations: bool = Form(True),
    compact: bool = Form(False),
):
    """更新显示设置"""
    try:
        config.DISPLAY_SETTINGS = {
            'theme': theme,
            'color': color,
            'language': language,
            'animations': animations,
            'compact': compact,
        }
        config.save_config()
        return JSONResponse(content={"success": True, "message": "显示设置已更新"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/settings/bind_device")
async def bind_device(request: Request, device_id: str = Form(...), device_name: str = Form("")):
    """绑定设备（通过device_id）

    绑定前先调用服务端的 check_device 接口校验设备是否已注册，
    若设备未注册则返回明确错误，避免绑定到不存在的设备。
    """
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

        # 2. 校验通过后再向服务端注册/绑定
        result = await elderly_client.register_device(device_id, device_name)
        if result.get("success"):
            return JSONResponse(content={
                "success": True,
                "message": f"设备 {device_name or device_id} 绑定成功"
            })
        else:
            return JSONResponse(content={
                "success": False,
                "message": f"绑定失败: {result.get('error', '未知错误')}"
            }, status_code=400)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/medication_settings")
async def medication_settings(request: Request):
    """用药设置页面"""
    status = await elderly_client.get_server_status()
    device_info = await elderly_client.get_device_info()
    plans = await elderly_client.get_device_plans()

    return templates.TemplateResponse(request, "medication_settings.html", {
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
    try:
        # 解析 JSON 请求体
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse(content={
                "success": False,
                "message": "请求体格式错误，需要 JSON 数据"
            }, status_code=400)

        drug_name = (payload.get("drug_name") or "").strip()
        dosage = (payload.get("dosage") or "").strip()
        schedule_times = payload.get("schedule_times") or []
        frequency = (payload.get("frequency") or "daily").strip()
        total_quantity = payload.get("total_quantity", 0)
        remaining_quantity = payload.get("remaining_quantity")
        unit = (payload.get("unit") or "片").strip()
        low_stock_threshold = payload.get("low_stock_threshold", 5)

        # 基础参数校验
        if not drug_name:
            return JSONResponse(content={
                "success": False,
                "message": "请填写药品名称"
            }, status_code=400)
        if not dosage:
            return JSONResponse(content={
                "success": False,
                "message": "请填写剂量"
            }, status_code=400)
        if not schedule_times or not isinstance(schedule_times, list):
            return JSONResponse(content={
                "success": False,
                "message": "请至少添加一个服药时间"
            }, status_code=400)
        # 过滤空字符串时间并校验格式
        schedule_times = [t.strip() for t in schedule_times if isinstance(t, str) and t.strip()]
        if not schedule_times:
            return JSONResponse(content={
                "success": False,
                "message": "请至少添加一个服药时间"
            }, status_code=400)

        # 数量转换与校验
        try:
            total_quantity = int(total_quantity)
        except (TypeError, ValueError):
            total_quantity = 0
        if remaining_quantity is None:
            remaining_quantity = total_quantity
        else:
            try:
                remaining_quantity = int(remaining_quantity)
            except (TypeError, ValueError):
                remaining_quantity = total_quantity
        try:
            low_stock_threshold = int(low_stock_threshold)
        except (TypeError, ValueError):
            low_stock_threshold = 5

        result = await elderly_client.set_medication_plan(
            drug_name=drug_name,
            dosage=dosage,
            schedule_times=schedule_times,
            frequency=frequency,
            total_quantity=total_quantity,
            remaining_quantity=remaining_quantity,
            unit=unit,
            low_stock_threshold=low_stock_threshold,
        )

        if result.get("success"):
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
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/medication_settings/delete/{plan_id}")
async def delete_medication_plan(request: Request, plan_id: int):
    """删除用药计划"""
    try:
        result = await elderly_client.delete_medication_plan(plan_id)
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
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/settings/unbind_device")
async def unbind_device(request: Request):
    """解绑设备"""
    try:
        elderly_client.clear_bound_device()
        return JSONResponse(content={
            "success": True,
            "message": "设备已解绑"
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
