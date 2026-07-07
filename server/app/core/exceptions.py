# -*- coding: utf-8 -*-
from fastapi import HTTPException, status

class BusinessError(Exception):
    """业务逻辑异常基类"""
    def __init__(self, message: str, code: int = status.HTTP_400_BAD_REQUEST):
        self.message = message
        self.code = code
        super().__init__(message)