# -*- coding: utf-8 -*-
"""
pytest 配置和共享夹具
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base
# M17：get_db 统一从 dependencies 导入（与路由中使用同一函数对象）
from app.core.dependencies import get_db
from app.core.security import create_access_token, hash_password
from app.models.user import User

# 测试数据库（使用内存 SQLite）
TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    """覆盖数据库依赖，使用测试数据库"""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


# 覆盖依赖
app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="function")
def db():
    """提供测试数据库会话"""
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db):
    """提供测试客户端"""
    def _get_db_override():
        return db
    app.dependency_overrides[get_db] = _get_db_override
    return TestClient(app)


@pytest.fixture(scope="function")
def test_elderly_user(db):
    """创建测试老人用户"""
    user = User(
        username="test_elderly",
        hashed_password=hash_password("password"),  # 动态生成有效哈希
        full_name="测试老人",
        role="elderly",
        phone="13800138000",
        group_id=None
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture(scope="function")
def test_family_user(db):
    """创建测试家属用户"""
    user = User(
        username="test_family",
        hashed_password=hash_password("password"),  # 动态生成有效哈希
        full_name="测试家属",
        role="family",
        phone="13900139000",
        group_id=None
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture(scope="function")
def test_token(test_elderly_user):
    """生成测试用户的 JWT token"""
    return create_access_token(data={"sub": test_elderly_user.id})


@pytest.fixture(scope="function")
def auth_headers(test_token):
    """认证请求头"""
    return {"Authorization": f"Bearer {test_token}"}