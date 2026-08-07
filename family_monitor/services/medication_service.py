# -*- coding: utf-8 -*-
"""用药计划参数校验与组装（纯逻辑，无 IO）。

从 routes/home.py 抽出的重复校验逻辑，集中维护药品名/剂量/服药时间/数量等校验，
避免 add 与 update 两处重复且易漂移。返回清洗后的字段 dict；校验失败返回错误文案。
"""
import logging

logger = logging.getLogger(__name__)


def validate_and_build(payload):
    """校验并清洗用药计划表单。

    :param payload: 请求体解析出的 dict
    :return: (cleaned_fields, error_message)
        - 校验通过时 error_message 为 None，cleaned_fields 为可直传给
          elderly_client.set/update_medication_plan 的关键字参数
        - 校验失败时 cleaned_fields 为 {}，error_message 为可直返前端的错误文案
    """
    drug_name = (payload.get("drug_name") or "").strip()
    dosage = (payload.get("dosage") or "").strip()
    # 药品编号/条形码（可选，非必填）：供老人端扫码识别
    product_code = (payload.get("product_code") or "").strip() or None
    schedule_times = payload.get("schedule_times") or []
    frequency = (payload.get("frequency") or "daily").strip()
    total_quantity = payload.get("total_quantity", 0)
    remaining_quantity = payload.get("remaining_quantity")
    unit = (payload.get("unit") or "片").strip()
    low_stock_threshold = payload.get("low_stock_threshold", 5)

    if not drug_name:
        return {}, "请填写药品名称"
    if not dosage:
        return {}, "请填写剂量"
    if not schedule_times or not isinstance(schedule_times, list):
        return {}, "请至少添加一个服药时间"

    # 过滤空字符串时间并校验格式
    schedule_times = [t.strip() for t in schedule_times if isinstance(t, str) and t.strip()]
    if not schedule_times:
        return {}, "请至少添加一个服药时间"

    # 数量转换与校验（失败回退为 0 / total）
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

    fields = {
        "drug_name": drug_name,
        "dosage": dosage,
        "product_code": product_code,
        "schedule_times": schedule_times,
        "frequency": frequency,
        "total_quantity": total_quantity,
        "remaining_quantity": remaining_quantity,
        "unit": unit,
        "low_stock_threshold": low_stock_threshold,
    }
    return fields, None
