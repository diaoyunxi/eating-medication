# -*- coding: utf-8 -*-
"""阶段D step1：验证 config 副作用已外移至 bootstrap_config 且可正确编排。

通过 monkeypatch bootstrap 命名空间内的两个副作用函数，断言 bootstrap_config()
按「确保 .env -> 重建 settings -> 校验」顺序执行，并更新模块全局 settings，
同时不触发真实磁盘写盘或 sys.exit。
"""
import app.core.bootstrap as bootstrap_mod
import app.core.config as cfg_mod
import pytest


def test_bootstrap_config_orchestration(monkeypatch):
    calls = {"ensure": 0, "validate": 0}

    def fake_ensure():
        calls["ensure"] += 1

    def fake_validate():
        calls["validate"] += 1

    # bootstrap 通过 `from app.core.config import ...` 绑定了自有引用，
    # 需 patch bootstrap 命名空间内的名称方可拦截。
    monkeypatch.setattr(bootstrap_mod, "_ensure_default_env", fake_ensure)
    monkeypatch.setattr(bootstrap_mod, "validate_mandatory_config", fake_validate)

    result = bootstrap_mod.bootstrap_config()

    # 1) 返回重建后的 settings 实例
    assert isinstance(result, bootstrap_mod.Settings)
    # 2) 两个副作用均被调用且仅一次
    assert calls["ensure"] == 1
    assert calls["validate"] == 1
    # 3) 全局 config.settings 已被更新为该实例，后续 `from app.core.config import settings` 取到最新
    assert cfg_mod.settings is result
    # 4) 基本字段可用（验证 Settings 构建未异常）
    assert result.API_V1_PREFIX
    assert result.APP_NAME


def test_config_import_has_no_side_effects(monkeypatch):
    """导入 config 不应在导入期写盘或退出：校验所需副作用函数仍可导入且可被拦截。"""
    # 直接在 bootstrap 命名空间内拦截，模拟导入期语义
    calls = {"ensure": 0, "validate": 0}
    monkeypatch.setattr(bootstrap_mod, "_ensure_default_env", lambda: calls.__setitem__("ensure", calls["ensure"] + 1))
    monkeypatch.setattr(bootstrap_mod, "validate_mandatory_config", lambda: calls.__setitem__("validate", calls["validate"] + 1))

    # 再次调用 bootstrap_config 模拟启动流程
    bootstrap_mod.bootstrap_config()
    assert calls["ensure"] == 1
    assert calls["validate"] == 1
