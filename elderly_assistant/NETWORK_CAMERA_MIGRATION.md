# 二哈实时图传改造说明（v2.43.0）

## 一、改造目标

将 M10 老人端获取二哈（HuskyLens V2）图片的方式，从「I2C 拍照 + SD 卡 U 盘取回」改为**通过网络（HTTP/RTSP）实时拉取**。

同时保留 I2C/UART 总线用于条码识别和人脸识别功能。

---

## 二、涉及文件

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `elderly_assistant/core/network_camera.py` | **新增** | 网络图传核心模块（HTTP 快照 + RTSP 拉流） |
| `elderly_assistant/core/camera.py` | **重写** | 主入口改为网络图传，I2C 仅用于识别，保留兼容回退 |
| `elderly_assistant/utils/config_loader.py` | **修改** | 新增 7 个网络图传配置项 |
| `elderly_assistant/requirements.txt` | **修改** | 添加网络图传注释说明 |
| `elderly_assistant/.env.sample` | **新增** | 带网络图传配置的示例文件 |
| `VERSION` | **修改** | 2.42.1 → 2.43.0 |

**未修改的文件（保持原样）：**
- `workflow/actions.py` — 调用 `capture_image(config)` 接口不变
- `core/barcode.py` — 仍通过 `get_huskylens()` 使用 I2C 读取条码
- `core/face.py` — 仍通过 `get_huskylens()` 使用 I2C 读取人脸
- `services/http_client.py` — 上传逻辑不变

---

## 三、新增配置项（elderly_assistant/.env）

```bash
# ===== 网络图传（v2.43.0 新增）=====
# 二哈 V2 的局域网 IP（必填）
HUSKYLENS_IP=192.168.1.100
# 图传模式：auto(推荐) / http / rtsp
HUSKYLENS_NETWORK_MODE=auto
# 二哈 HTTP 端口
HUSKYLENS_HTTP_PORT=80
# HTTP 快照路径
HUSKYLENS_SNAPSHOT_PATH=/snapshot
# HTTP 流路径
HUSKYLENS_STREAM_PATH=/stream
# RTSP 端口
HUSKYLENS_RTSP_PORT=554
# HTTP 超时（秒）
HUSKYLENS_REQUEST_TIMEOUT=5
```

---

## 四、使用方式

### 4.1 首次部署

1. 将二哈 V2 连接到与 M10 相同的 WiFi 网络
2. 获取二哈的 IP 地址（查看路由器 DHCP 客户端列表或二哈 Web 管理页）
3. 复制 `.env.sample` 为 `.env`，填写 `HUSKYLENS_IP`
4. 确保 `opencv-python-headless` 已安装（用于 RTSP 模式）

### 4.2 自动探测（可选）

若未配置 `HUSKYLENS_IP`，可在代码中调用：
```python
from core.network_camera import discover_huskylens_on_network
ip = discover_huskylens_on_network(subnet="192.168.1")
```

---

## 五、协议优先级（auto 模式）

```
1. HTTP 快照（最快，~200ms）
   GET http://<HUSKYLENS_IP>:80/snapshot
   → 直接返回 JPEG 字节

2. RTSP 拉流（兼容性强，~500ms）
   cv2.VideoCapture("rtsp://<HUSKYLENS_IP>:554/live")
   → 读取一帧后释放

3. 兼容回退（仅当 HUSKYLENS_IP 未配置时）
   I2C takePhoto() + SD 卡 U 盘取回
```

---

## 六、I2C/UART 保留功能

| 功能 | 模块 | 说明 |
|------|------|------|
| 条码识别 | `core/barcode.py` | 通过 `get_huskylens()` 读取识别结果 |
| 人脸识别 | `core/face.py` | 通过 `get_huskylens()` 读取人脸 ID |
| 算法切换 | `core/barcode.py` | `switchAlgorithm(17)` 条码识别 |
| 人脸学习 | `core/face.py` | `learnFace(face_id)` 录入人脸 |

---

## 七、注意事项

1. **连接方式**：二哈 V2 通过 USB 连接到 M10，被识别为**网络摄像头**（USB 以太网/RNDIS 模式），M10 自动分配 IP
2. **配置 IP 地址**：在 `elderly_assistant/.env` 中填写 `HUSKYLENS_IP`（二哈的 USB 网卡 IP）
3. **RTSP 模式需要 OpenCV 支持**（`opencv-python-headless` 已包含 ffmpeg）
4. **防火墙需放行**二哈的 HTTP/RTSP 端口
5. **IP 可能变化**：每次 USB 重插后 IP 可能变动，需重新配置 `.env`

---

## 八、向后兼容性

- 未配置 `HUSKYLENS_IP` 时，自动回退到原有 I2C 拍照方案（日志标记「兼容模式」）
- `workflow/actions.py` 调用方式无需修改
- 单元测试可用 `FakeCamera` 替身注入（ports.py 已有 `CameraPort` Protocol）

---

**编制日期**：2026-08-20  
**版本**：v2.43.0-alpha
