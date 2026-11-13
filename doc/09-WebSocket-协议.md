> [← 返回文档目录](../README.md) ｜ 本分册由 `README.md` 的「WebSocket 协议」章节拆分而来。

## WebSocket 协议

服务端提供两个独立的 WebSocket 入口：

### 1. 通用 WebSocket `/ws/ws`

- **完整路径**：`{PATH_PREFIX}/ws/ws?token=<JWT>`
- **认证**：Query 参数 `token`（JWT，长度上限 2048）；无效则 close code=1008
- **消息**：客户端发 `"ping"`，服务端回 `"pong"`；用于接收服务端主动推送通知

### 2. 聊天 WebSocket `/api/v1/chat/ws/{user_id}`

- **完整路径**：`{PATH_PREFIX}/api/v1/chat/ws/{user_id}?token=<JWT>`
- **认证**：Query 参数 `token`，以 token 中 `sub` 覆盖 URL 中的 user_id
- **客户端 → 服务端**（JSON）：
  - `{"type":"chat","content":"...","receiver_id":N,"sender_name":"..."}` —— 发送聊天消息（落库 + 推送接收者）
  - `{"type":"ping"}` —— 心跳
- **服务端 → 客户端**（JSON）：
  - `{"type":"chat_message","id":..,"sender_id":..,"sender_name":"..","content":"..","timestamp":".."}` —— 推送给接收者
  - `{"type":"message_sent","id":..}` —— 回执给发送者
  - `{"type":"pong"}` —— 心跳响应

### 服务端主动推送消息类型（经 `ConnectionManager` + `Notifier`）

| `type`              | 触发场景                                |
| ------------------- | --------------------------------------- |
| `medication_taken`  | 老人已服药                              |
| `medication_missed` | 老人漏服药品                            |
| `low_stock`         | 药品库存不足（定时任务每天 02:00 触发） |
| `family_message`    | 家庭消息                                |
| `chat_message`      | 聊天消息（chat 端点直接调用）           |

---
