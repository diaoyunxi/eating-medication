# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional
from app.core.dependencies import get_db
from app.schemas.auth import RegisterReq, LoginReq, TokenResp
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["认证"])

@router.post("/register", response_model=TokenResp, status_code=status.HTTP_201_CREATED)
def register(req: RegisterReq, db: Session = Depends(get_db)):
    """用户注册（老人或家属）"""
    try:
        token = AuthService.register(db, req)
        return TokenResp(access_token=token, token_type="bearer")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/login", response_model=TokenResp)
def login(req: LoginReq, db: Session = Depends(get_db)):
    """用户登录"""
    token = AuthService.login(db, req.username, req.password)
    if token is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return TokenResp(access_token=token, token_type="bearer")