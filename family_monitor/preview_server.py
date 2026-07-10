# -*- coding: utf-8 -*-
"""reminders 页面预览服务器（独立运行，注入模拟数据，无需服务端和设备）"""

import uvicorn
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import RedirectResponse

BASE_DIR = Path(__file__).parent
app = FastAPI()

# 挂载静态文件
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# 模板
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
# 禁用 Jinja2 模板缓存（避免 starlette 新版 tuple key 缓存报错）
templates.env.cache = None
templates.env.globals["prefix"] = ""
templates.env.globals["current_year"] = __import__("datetime").datetime.now().year

# 模拟用药提醒数据
MOCK_REMINDERS = [
    {
        "id": 1,
        "drug_name": "阿司匹林肠溶片",
        "dosage": "1片",
        "frequency": "daily",
        "schedule_times": ["08:00", "20:00"],
        "total_quantity": 30,
        "remaining_quantity": 12,
        "unit": "片",
        "low_stock_threshold": 5,
    },
    {
        "id": 2,
        "drug_name": "二甲双胍缓释片",
        "dosage": "0.5g",
        "frequency": "daily",
        "schedule_times": ["07:30", "12:30", "18:30"],
        "total_quantity": 60,
        "remaining_quantity": 45,
        "unit": "片",
        "low_stock_threshold": 10,
    },
    {
        "id": 3,
        "drug_name": "硝苯地平控释片",
        "dosage": "1片",
        "frequency": "daily",
        "schedule_times": ["07:00"],
        "total_quantity": 28,
        "remaining_quantity": 3,
        "unit": "片",
        "low_stock_threshold": 5,
    },
    {
        "id": 4,
        "drug_name": "维生素D3",
        "dosage": "1粒",
        "frequency": "daily",
        "schedule_times": ["09:00"],
        "total_quantity": 90,
        "remaining_quantity": 78,
        "unit": "粒",
        "low_stock_threshold": 10,
    },
]

MOCK_DEVICE_INFO = {
    "connected": True,
    "device_id": "elderly_001",
    "device_name": "爷爷的设备",
}

# 模拟仪表板数据
MOCK_DASHBOARD = {
    "summary": {
        "total_reminders": 5,
        "active_reminders": 4,
        "taken_today": 3,
        "pending_today": 1,
        "adherence_rate": 85,
        "last_updated": "2026-07-10 14:30:00",
    },
    "upcoming_reminders": [
        {"id": 1, "name": "阿司匹林肠溶片", "time": "20:00", "status": "pending"},
        {"id": 2, "name": "维生素D3", "time": "21:00", "status": "pending"},
    ],
    "recent_activities": [
        {"id": 1, "type": "medication", "action": "已服用", "name": "二甲双胍缓释片", "time": "12:30", "icon": "💊"},
        {"id": 2, "type": "medication", "action": "已服用", "name": "硝苯地平控释片", "time": "07:00", "icon": "💊"},
    ],
    "chart_data": [
        {"date": "2026-07-04", "taken": 3, "scheduled": 4},
        {"date": "2026-07-05", "taken": 4, "scheduled": 4},
        {"date": "2026-07-06", "taken": 2, "scheduled": 4},
        {"date": "2026-07-07", "taken": 5, "scheduled": 5},
        {"date": "2026-07-08", "taken": 4, "scheduled": 5},
        {"date": "2026-07-09", "taken": 3, "scheduled": 4},
        {"date": "2026-07-10", "taken": 4, "scheduled": 4},
    ],
    "medications": [
        {"name": "阿司匹林肠溶片", "remaining": 12, "total": 30, "status": "ok"},
        {"name": "二甲双胍缓释片", "remaining": 45, "total": 60, "status": "ok"},
        {"name": "硝苯地平控释片", "remaining": 3, "total": 28, "status": "low"},
        {"name": "维生素D3", "remaining": 78, "total": 90, "status": "ok"},
    ],
}


@app.get("/")
async def root():
    return RedirectResponse(url="/dashboard", status_code=302)


@app.get("/dashboard")
async def dashboard(request: Request):
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "app_name": "用药看护系统",
            "dashboard": MOCK_DASHBOARD,
            "status": {"connected": True},
            "device_info": MOCK_DEVICE_INFO,
        },
    )


@app.get("/reminders")
async def reminders(request: Request):
    return templates.TemplateResponse(
        request,
        "reminders.html",
        {
            "app_name": "用药看护系统",
            "reminders": MOCK_REMINDERS,
            "status": {"connected": True},
            "device_info": MOCK_DEVICE_INFO,
        },
    )


@app.get("/status")
async def status():
    return {"connected": True, "device_id": "elderly_001", "device_name": "爷爷的设备"}


# 模拟后端接口（添加/更新/删除，返回成功但不真实写入）
from fastapi.responses import JSONResponse


@app.post("/medication_settings/add")
async def mock_add(request: Request):
    return JSONResponse({"success": True, "message": "模拟：用药计划添加成功（预览模式不真实写入）"})


@app.post("/medication_settings/update/{plan_id}")
async def mock_update(plan_id: int, request: Request):
    return JSONResponse({"success": True, "message": f"模拟：用药计划 {plan_id} 更新成功（预览模式不真实写入）"})


@app.post("/medication_settings/delete/{plan_id}")
async def mock_delete(plan_id: int):
    return JSONResponse({"success": True, "message": f"模拟：用药计划 {plan_id} 已删除（预览模式不真实写入）"})


if __name__ == "__main__":
    print("=" * 50)
    print("  reminders 页面预览服务器")
    print("  访问地址: http://localhost:4480/reminders")
    print("  按 Ctrl+C 退出")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=4480, log_level="info")
