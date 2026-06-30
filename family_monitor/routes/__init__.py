# -*- coding: utf-8 -*-
"""
璺敱妯″潡
"""

from .home import router as home_router
from .auth import router as auth_router
from .chat import router as chat_router

__all__ = ['home_router', 'auth_router', 'chat_router']
