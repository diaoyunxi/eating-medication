# -*- coding: utf-8 -*-
import requests
from utils.logger import setup_logger

class AIClient:
    def __init__(self, config):
        self.logger = setup_logger()
        # 容错处理：config 或 'ai' 段缺失时不崩溃，降级为空字典
        if not isinstance(config, dict):
            self.logger.warning("AI 客户端收到非字典配置，已降级为空配置")
            config = {}
        ai_config = config.get('ai', {})
        if not ai_config:
            self.logger.warning(
                "配置中未找到 'ai' 段，AI 客户端将以未配置状态降级"
                "（请在 config.yaml 中补充 ai 配置）"
            )
        self.config = ai_config
        self.api_key = self.config.get('api_key')
        self.base_url = self.config.get('base_url')
        self.model = self.config.get('model')

    def ask(self, question):
        if not self.api_key:
            self.logger.warning("AI API key 未配置")
            return "AI 未配置，请在设置中添加API密钥"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": question}],
            "temperature": 0.7
        }
        try:
            resp = requests.post(f"{self.base_url}/chat/completions", json=payload, headers=headers, timeout=10)
            if resp.status_code == 200:
                return resp.json()['choices'][0]['message']['content'].strip()
            else:
                self.logger.error(f"AI请求失败: {resp.status_code} {resp.text}")
                return f"AI服务返回错误({resp.status_code})，请稍后重试"
        except requests.exceptions.RequestException as e:
            self.logger.error(f"AI请求网络异常: {e}")
            return "无法连接AI服务，请检查网络"
        except Exception as e:
            self.logger.error(f"AI客户端未知错误: {e}")
            return "AI回复出错，请稍后再试"