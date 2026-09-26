# 安全审计报告：错误信息泄露检查

**检查项**：堆栈跟踪直接返回给客户端  
**检查时间**：2026-08-23  
**审计范围**：server/、family_monitor/、elderly_assistant/

---

## 一、检查结果摘要

| 风险等级 | 数量 | 说明 |
|---------|------|------|
| 无风险 | 主要路径 | 全局异常处理器正确配置 |
| 低风险 | 8处 | detail=str(e) 模式，当前为业务错误 |
| 中风险 | 13处 | api_client 返回网络异常给前端 |

---

## 二、已正确实现的安全措施

### 2.1 全局异常处理器（server/app/middleware/exception_handler.py）

```python
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """处理所有未捕获的异常"""
    logger.exception(f"未捕获的异常: {exc} | 请求体: {body_text}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "服务器内部错误，请稍后重试"},
    )
```

**评估**：✅ 安全  
- 所有未捕获异常均返回通用消息"服务器内部错误，请稍后重试"
- 详细堆栈仅记录到日志，不返回客户端

### 2.2 请求验证异常处理

```python
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(f"请求参数校验失败: path={request.url.path}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "请求参数格式不正确"},
    )
```

**评估**：✅ 安全  
- 不返回用户输入内容（防SQL注入信息泄露）
- 不返回字段类型细节

### 2.3 Vision 端点异常处理（server/app/api/v1/endpoints/vision.py）

```python
except Exception:
    # 异常细节不返回客户端，仅记录详细日志
    logger.exception("识别失败")
    raise HTTPException(status_code=500, detail="识别失败，请稍后重试")
```

**评估**：✅ 安全  
- 使用 `logger.exception` 记录完整堆栈
- 客户端仅收到通用错误消息

---

## 三、发现的问题

### 问题1：server端使用 `detail=str(e)` 模式（低风险）

**位置**：
- `server/app/api/v1/endpoints/auth.py` (7处)
- `server/app/api/v1/endpoints/medication.py` (1处)
- `server/app/api/v1/endpoints/family_device.py` (1处)
- `server/app/api/v1/endpoints/public.py` (1处)

**代码示例**：
```python
except ValueError as e:
    raise HTTPException(status_code=400, detail=str(e))
```

**风险分析**：
- 当前ValueError消息均为业务逻辑错误（如"手机号格式不正确"、"该手机号已注册"）
- 不存在堆栈跟踪泄露风险
- **潜在风险**：若未来新增未捕获的异常类型（如数据库异常），可能泄露内部信息

**整改建议**：
```python
# 建议改为统一错误消息，或建立错误码映射
except ValueError as e:
    error_msg = str(e)
    # 可根据需要添加错误码映射
    raise HTTPException(status_code=400, detail=error_msg)
```

---

### 问题2：family_monitor/api_client.py 将网络异常返回给前端（中风险）

**位置**：`family_monitor/core/api_client.py` (13处)

**代码示例**：
```python
except Exception as e:
    return {"success": False, "error": str(e)}
```

**风险分析**：
- 会将网络请求异常（连接失败、超时等）返回给最终用户
- 可能包含服务端地址、端口等信息
- 但不会泄露服务端堆栈跟踪

**影响范围**：
- 绑定/解绑设备
- 用药计划CRUD操作
- 设备检查操作

**整改建议**：
```python
except Exception as e:
    # 记录详细错误到日志
    logger.error(f"API请求失败: {e}")
    # 返回通用错误消息
    return {"success": False, "error": "网络连接失败，请稍后重试"}
```

---

## 四、安全设计亮点

### 4.1 敏感字段脱敏

`server/app/middleware/exception_handler.py` 中的请求体脱敏：

```python
_SENSITIVE_FIELDS = ("password", "token", "authorization")

def _redact_request_body(body_bytes: bytes) -> str:
    # 脱敏后记录到日志
```

**评估**：✅ 优秀实践

### 4.2 业务异常分类处理

```python
@app.exception_handler(BusinessError)
async def business_exception_handler(request: Request, exc: BusinessError):
    logger.warning(f"业务异常: {exc.message} (code={exc.code})")
    return JSONResponse(
        status_code=exc.code,
        content={"detail": exc.message},
    )
```

**评估**：✅ 良好设计，业务异常与系统异常分离

---

## 五、结论

### 总体评价：**良好** ✅

**未发现严重的堆栈跟踪泄露问题**。项目已建立以下安全防护：

1. 全局异常处理器正确拦截所有未捕获异常
2. 请求验证异常不返回用户输入内容
3. 关键端点使用logger.exception记录详细错误
4. 敏感字段在日志中自动脱敏

### 建议整改项（非紧急）

| 优先级 | 文件 | 问题 | 建议 |
|--------|------|------|------|
| 中 | family_monitor/core/api_client.py | 网络异常直接返回前端 | 改用通用错误消息 |
| 低 | server/app/api/v1/endpoints/*.py | detail=str(e) 模式 | 建立错误码映射表 |

---

## 六、检查方法说明

本次审计采用以下方法：

1. **静态扫描**：使用grep搜索异常处理模式
2. **代码审查**：检查异常消息内容和返回方式
3. **动态验证**：运行测试确认异常处理逻辑
4. **架构分析**：检查全局异常处理器配置

---

**报告完成时间**：2026-08-23  
**审计人员**：Agnes AI Security Audit
