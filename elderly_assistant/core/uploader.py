# -*- coding: utf-8 -*-
def upload_medication_image(image_path, http_client):
    try:
        http_client.upload_image(image_path)
    except Exception as e:
        pass