# -*- coding: utf-8 -*-
"""跨端统一的服务端 HTTP 客户端基类。

设计约束：
- 仅依赖标准库；``httpx`` 在方法内懒加载，避免 common 包在导入期依赖第三方库
  （elderly_assistant / family_monitor 各自有不同的第三方依赖环境）。
- 统一了 SSL 上下文构建、认证头合并、URL 拼接与请求执行，
  消除各端散落的 ``httpx.AsyncClient`` 重复代码。

子类约定：
- 重写 ``_auth_headers()`` 返回认证请求头（如 X-Device-ID / Authorization）。
- 通过 ``base_url`` 设定服务端根地址；``_execute(method, path, ...)`` 的 path
  以 ``/`` 开头时直接拼接在 base_url（自动去除末尾斜杠）之后。
"""
import json
import ssl
from typing import Any, Dict, Optional
from urllib.parse import quote


def encode_device_id(device_id: str) -> str:
    """对 device_id 进行 URL 编码，防止特殊字符破坏 URL 结构。

    与历史实现保持一致：使用 ``urllib.parse.quote``，``safe=''`` 编码所有特殊字符。
    """
    return quote(str(device_id), safe='')


class _ResponseAdapter:
    """对 httpx.Response 的轻量适配，使调用方在客户端关闭后仍可读取状态码/正文。

    - ``status_code``：HTTP 状态码。
    - ``text``：响应正文文本。
    - ``json()``：解析 JSON；解析失败时抛出原始异常（与原 httpx.Response.json() 行为一致）。
    """

    __slots__ = ("status_code", "text", "_parsed", "_parse_exc")

    def __init__(self, status_code: int, text: str, parsed: Any, parse_exc: Optional[Exception]):
        self.status_code = status_code
        self.text = text
        self._parsed = parsed
        self._parse_exc = parse_exc

    def json(self) -> Any:
        if self._parse_exc is not None:
            raise self._parse_exc
        return self._parsed


class BaseServerClient:
    """服务端 HTTP 客户端基类（异步，基于 httpx）。"""

    def __init__(self, base_url: str = "", timeout: float = 10.0):
        # 保留原始 base_url（部分调用方会读取该字段用于展示），URL 拼接时在 _url 内统一去尾斜杠
        self.base_url = base_url or ""
        self.timeout = timeout
        self._ssl_context = self._create_ssl_context()

    def _create_ssl_context(self) -> Optional[ssl.SSLContext]:
        """创建 SSL 上下文（HTTPS 连接验证，使用系统默认信任库）。"""
        if self.base_url.startswith('https://'):
            try:
                return ssl.create_default_context()
            except Exception as e:  # pragma: no cover - 系统信任库异常极罕见
                print(f"创建SSL上下文失败: {e}")
                return None
        return None

    def _auth_headers(self) -> Dict[str, str]:
        """返回认证请求头，子类按需重写（如 X-Device-ID / Authorization）。"""
        return {}

    def _url(self, path: str) -> str:
        """拼接完整请求 URL。

        - 若 path 已是绝对 URL（含协议，如 http://、https://），直接返回，
          避免与 base_url 重复拼接（例如 ``_server_url`` 返回完整地址后又被追加到
          base_url 之后，导致请求路径里嵌入整串 URL，服务端 404）。
        - 否则自动去除 base_url 末尾斜杠，path 以 '/' 开头时直接追加。
        """
        if '://' in path:
            return path
        base = self.base_url.rstrip('/')
        if path.startswith('/'):
            return f"{base}{path}"
        return f"{base}/{path}"

    async def _execute(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> _ResponseAdapter:
        """统一执行 HTTP 请求，返回 ``_ResponseAdapter``。

        - 网络/传输层异常（httpx.RequestError 等）会向上抛出，由调用方决定降级策略。
        - HTTP 错误状态码不会抛异常，仅体现在 ``status_code`` 上，便于调用方按业务处理。

        :param method: HTTP 方法（GET/POST/PUT/DELETE...）
        :param path: 相对于 base_url 的路径（建议以 '/' 开头）
        :param params: 查询参数
        :param json_body: JSON 请求体
        :param headers: 额外请求头（会与 ``_auth_headers()`` 合并，后者优先）
        """
        import httpx  # 懒加载：仅在发起请求时导入，遵守 common 仅标准库的约定

        merged_headers = dict(self._auth_headers())
        if headers:
            merged_headers.update(headers)

        verify = self._ssl_context if self._ssl_context else True
        async with httpx.AsyncClient(timeout=self.timeout, verify=verify) as client:
            response = await client.request(
                method,
                self._url(path),
                params=params,
                json=json_body,
                headers=merged_headers,
            )
            # 客户端退出上下文后会关闭连接，必须在这里读尽正文
            await response.aread()
            text = response.text
            try:
                parsed: Any = json.loads(text) if text else None
                parse_exc: Optional[Exception] = None
            except Exception as e:  # JSON 解析失败时保留异常，供 json() 复抛
                parsed = None
                parse_exc = e
            return _ResponseAdapter(response.status_code, text, parsed, parse_exc)

    async def check_connection(self, health_path: str = "/health") -> bool:
        """检查服务端连通性（默认请求 /health）。"""
        try:
            resp = await self._execute("GET", health_path)
            return resp.status_code == 200
        except Exception:
            return False
