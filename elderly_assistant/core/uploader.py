# -*- coding: utf-8 -*-
import logging

logger = logging.getLogger("ElderlyAssistant")


def upload_medication_image(image_path, http_client):
    try:
        http_client.upload_image(image_path)
    except Exception as e:
        logger.warning(f"上传失败: {e}")