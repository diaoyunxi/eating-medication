# -*- coding: utf-8 -*-
import base64
import httpx
import hashlib
import time
from typing import Dict, Any
from app.core.config import settings


class VisionService:
    """药品图片识别服务"""

    @staticmethod
    async def _recognize_baidu(image_data: bytes) -> Dict[str, Any]:
        """调用百度OCR识别

        :return: {"configured": True, "text": "..."} 或配置缺失时 {"configured": False, "reason": "..."}
        """
        if not settings.OCR_API_KEY or not settings.OCR_SECRET_KEY:
            return {
                "configured": False,
                "reason": "百度OCR配置不完整，请配置 OCR_API_KEY 和 OCR_SECRET_KEY",
            }

        try:
            token_url = "https://aip.baidubce.com/oauth/2.0/token"
            token_params = {
                'grant_type': 'client_credentials',
                'client_id': settings.OCR_API_KEY,
                'client_secret': settings.OCR_SECRET_KEY
            }
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                token_resp = await client.get(token_url, params=token_params)
                if token_resp.status_code != 200:
                    raise Exception(f"获取百度访问令牌失败，状态码: {token_resp.status_code}")
                access_token = token_resp.json().get('access_token')
                if not access_token:
                    raise Exception(f"获取百度访问令牌失败: {token_resp.text}")

                ocr_url = f"https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic?access_token={access_token}"
                image_base64 = base64.b64encode(image_data).decode('utf-8')
                
                headers = {'Content-Type': 'application/x-www-form-urlencoded'}
                data = {'image': image_base64}
                
                ocr_resp = await client.post(ocr_url, headers=headers, data=data)
                if ocr_resp.status_code == 200:
                    result = ocr_resp.json()
                    if result.get('error_code'):
                        raise Exception(f"百度OCR识别失败: {result.get('error_msg')}")
                    if result.get('words_result'):
                        text = '\n'.join([word['words'] for word in result['words_result']])
                        return {
                            'configured': True,
                            'text': text,
                            'words': [word['words'] for word in result['words_result']]
                        }
                    raise Exception("未识别到任何文字")
                raise Exception(f"百度OCR请求失败，状态码: {ocr_resp.status_code}")
        except Exception as e:
            if str(e).startswith("百度"):
                raise
            raise Exception(f"百度OCR调用失败: {str(e)}")

    @staticmethod
    async def _recognize_tencent(image_data: bytes) -> Dict[str, Any]:
        """调用腾讯OCR识别"""
        return {"configured": False, "reason": "腾讯云 OCR 功能尚未实现"}

    @staticmethod
    async def _recognize_aliyun(image_data: bytes) -> Dict[str, Any]:
        """调用阿里云OCR识别"""
        return {"configured": False, "reason": "阿里云 OCR 功能尚未实现"}

    @staticmethod
    async def _extract_drug_name(text: str) -> str:
        """从识别的文本中提取药品名称"""
        import re
        
        drug_keywords = [
            '片', '胶囊', '颗粒', '丸', '散', '膏', '贴', '气雾剂',
            'mg', 'g', 'ml', '毫克', '克', '毫升',
            '口服', '外用', '注射',
            '阿司匹林', '布洛芬', '对乙酰氨基酚', '阿莫西林', '头孢',
            '维生素', '钙片', '降压', '降糖', '感冒', '消炎'
        ]
        
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if len(line) < 3:
                continue
            for keyword in drug_keywords:
                if keyword in line:
                    return line
        
        return lines[0] if lines else '识别失败'

    @staticmethod
    async def recognize(image_data: bytes) -> Dict[str, Any]:
        """识别药品图片，返回药名和置信度

        OCR 未配置或不可用时返回 {"configured": False, "reason": "..."}（降级，不抛异常），
        由调用方返回友好提示，避免返回 500。
        """
        # OCR 未配置：优雅降级
        if not settings.OCR_PROVIDER:
            return {
                "configured": False,
                "reason": "OCR 服务未配置，请设置 OCR_PROVIDER 为 'baidu'/'tencent'/'aliyun'",
            }
        if not settings.OCR_API_KEY:
            return {
                "configured": False,
                "reason": "OCR 服务 API 密钥未配置，请设置 OCR_API_KEY",
            }

        ocr_result = None
        if settings.OCR_PROVIDER == 'baidu':
            ocr_result = await VisionService._recognize_baidu(image_data)
        elif settings.OCR_PROVIDER == 'tencent':
            ocr_result = await VisionService._recognize_tencent(image_data)
        elif settings.OCR_PROVIDER == 'aliyun':
            ocr_result = await VisionService._recognize_aliyun(image_data)
        else:
            return {
                "configured": False,
                "reason": f"不支持的 OCR 服务商: {settings.OCR_PROVIDER}",
            }

        # 子服务未配置/未实现：直接返回降级提示
        if ocr_result and ocr_result.get("configured") is False:
            return ocr_result

        if ocr_result and ocr_result.get('text'):
            drug_name = await VisionService._extract_drug_name(ocr_result['text'])
            confidence = ocr_result.get('confidence')
            return {
                "configured": True,
                'name': drug_name,
                'confidence': confidence,
                'raw_text': ocr_result['text']
            }

        return {
            "configured": False,
            "reason": "OCR 识别未返回有效结果",
        }