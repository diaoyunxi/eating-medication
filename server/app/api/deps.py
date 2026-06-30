# -*- coding: utf-8 -*-
"""
API 层专用依赖项（如分页参数、通用查询参数等）
"""
from fastapi import Query
from typing import Optional

class PaginationParams:
    def __init__(
        self,
        page: int = Query(1, ge=1, description="页码"),
        size: int = Query(20, ge=1, le=100, description="每页数量"),
    ):
        self.page = page
        self.size = size
        self.offset = (page - 1) * size