# 老人用药管理智能助手

一套面向独居老人的智能用药管理系统。

> **当前版本**：v2.30.0 | **仓库**：[diaoyunxi/eating-medication](https://github.com/diaoyunxi/eating-medication)

## 功能概览

| 模块 | 定位 | 主要功能 |
|------|------|----------|
| elderly_assistant | 老人端 | 用药提醒、药品条码扫描播报、AI 语音问答、紧急呼叫、计划离线可用 |
| server | 服务端 | 用户认证、用药计划管理（含药品编号）、AI 服务、WebSocket 通信 |
| family_monitor | 家属端 | 远程查看记录、用药计划与药品编号维护（支持扫码）、实时聊天、健康仪表板 |

## 快速开始

```bash
cd elderly_assistant && python ../install.py requirements.txt && python main.py
cd server && python ../install.py requirements.txt && python main.py
cd family_monitor && python ../install.py requirements.txt && python main.py
```

## 配置说明

三模块均使用 .env 配置文件，敏感信息请勿提交到仓库。

## API 文档

服务端启动后访问 /docs 查看完整 OpenAPI 文档。

## 部署与运维

支持 Linux/macOS/Windows 一键部署脚本，详见 deploy/README.md。

## 感谢贡献

Cloudflare, GitHub, Gitee, Tesseract OCR, pyttsx3, DFRobot 行空板 M10

## 许可

本项目仅供学习和个人使用。
