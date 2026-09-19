# -*- coding: utf-8 -*-
"""跨端共享公共包（common）。

集中存放三端（server / elderly_assistant / family_monitor）重复实现的能力，
避免「几个文件实现一个功能」的反模式：

- envfile: 扁平 .env 文件的读取与就地更新（保留注释与其它字段）
- config:  配置基类 BaseAppConfig（生成密钥 / 必填校验 / 模板生成）
- security: 密码哈希 / 令牌生成（统一 bcrypt 轮次与 secret 派生）
- server_client: 设备端 -> 服务端 API 客户端基类（header / 端点 / 令牌持久化）
- runtime_protection: 运行时受保护文件规则（更新 / 重置逻辑共用）

约束：common 仅依赖标准库与少量被广泛使用的第三方库，不反向依赖任何一端。
三端入口（main.py）须将仓库根加入 sys.path 才能 `import common`
（elderly_assistant / family_monitor 已注入；server/main.py 待注入）。
"""

__version__ = "1.0.0"
