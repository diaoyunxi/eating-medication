# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from app.core.dependencies import get_db
from app.schemas.auth import RegisterReq, LoginReq, TokenResp
from app.services.auth_service import AuthService
# L8：注册端点限流
from app.utils.rate_limit import check_rate_limit

router = APIRouter(prefix="/auth", tags=["认证"])

# L8：注册限流——每分钟每 IP 最多 5 次注册
_REGISTER_RATE_LIMIT = 5
# 登录限流——每分钟每 IP 最多 10 次登录
_LOGIN_RATE_LIMIT = 10

@router.post("/register", response_model=TokenResp, status_code=status.HTTP_201_CREATED)
def register(
    req: RegisterReq,
    request: Request,
    db: Session = Depends(get_db),
):
    """用户注册（老人或家属，L8：基于 IP 限流）"""
    # L8：限流
    client_ip = request.client.host if request.client else "unknown"
    if not check_rate_limit(f"register:{client_ip}", _REGISTER_RATE_LIMIT):
        raise HTTPException(status_code=429, detail="注册请求过于频繁，请稍后再试")

    try:
        token = AuthService.register(db, req)
        return TokenResp(access_token=token, token_type="bearer")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/login", response_model=TokenResp)
def login(req: LoginReq, request: Request, db: Session = Depends(get_db)):
    """用户登录"""
    # 限流：每分钟每 IP 最多 10 次登录
    client_ip = request.client.host if request.client else "unknown"
    if not check_rate_limit(f"login:{client_ip}", _LOGIN_RATE_LIMIT):
        raise HTTPException(status_code=429, detail="登录请求过于频繁，请稍后再试")
    token = AuthService.login(db, req.username, req.password)
    if token is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return TokenResp(access_token=token, token_type="bearer")
