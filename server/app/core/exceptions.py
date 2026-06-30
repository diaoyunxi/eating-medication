# -*- coding: utf-8 -*-
from fastapi import HTTPException, status

class BusinessError(Exception):
    """业务逻辑异常基类"""
    def __init__(self, message: str, code: int = status.HTTP_400_BAD_REQUEST):
        self.message = message
        self.code = code
        super().__init__(message)

class NotFoundError(BusinessError):
    """资源未找到"""
    def __init__(self, message: str = "资源不存在"):
        super().__init__(message, status.HTTP_404_NOT_FOUND)

class UnauthorizedError(BusinessError):
    """未授权"""
    def __init__(self, message: str = "认证失败"):
        super().__init__(message, status.HTTP_401_UNAUTHORIZED)

class ForbiddenError(BusinessError):
    """权限不足"""
    def __init__(self, message: str = "权限不足"):
        super().__init__(message, status.HTTP_403_FORBIDDEN)