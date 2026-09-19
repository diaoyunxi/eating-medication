# -*- coding: utf-8 -*-
"""硬件访问层：集中封装 M10 板级硬件（Board / 按钮 / LED / 光线传感器）与测试替身。

本层仅依赖标准库与 typing，不反向依赖任何业务逻辑，可被单测以 Fake 注入。
所有 pinpong 依赖均为懒加载，非 M10 环境（无 pinpong）下全部安全降级为 None / False。
"""
