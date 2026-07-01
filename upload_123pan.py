# -*- coding: utf-8 -*-
"""
123云盘上传脚本
将本地文件上传到 123云盘指定路径
"""
import requests
import hashlib
import os
import time
import sys

# 123云盘账号配置
ACCOUNT = "17345783878"
PASSWORD = "Hy123456"

# 123云盘 API 端点
LOGIN_URL = "https://login.123pan.com/api/user/sign_in"
USER_INFO_URL = "https://123pan.com/b/api/user/info"
FILE_LIST_URL = "https://123pan.com/b/api/file/list/new"
UPLOAD_REQUEST_URL = "https://123pan.com/b/api/file/upload_request"
S3_REPARE_PARTS_URL = "https://123pan.com/b/api/file/s3_repare_upload_parts_batch"
S3_COMPLETE_URL = "https://123pan.com/b/api/file/s3_complete_multipart_upload"
UPLOAD_COMPLETE_URL = "https://123pan.com/b/api/file/upload_complete"

# 分块大小：5MB
CHUNK_SIZE = 5 * 1024 * 1024

# Android 客户端 Header
def get_headers(token=None):
    headers = {
        "user-agent": "123pan/v2.4.0(Android_11;Xiaomi)",
        "content-type": "application/json",
        "platform": "android",
        "devicetype": "M2004J19C",
        "osversion": "Android_11",
        "app-version": "61",
        "x-app-version": "2.4.0",
    }
    if token:
        headers["authorization"] = f"Bearer {token}"
    return headers


def login():
    """登录 123云盘，返回 token"""
    headers = get_headers()
    payload = {
        "passport": ACCOUNT,
        "password": PASSWORD,
        "remember": True,
    }
    resp = requests.post(LOGIN_URL, headers=headers, json=payload, timeout=30)
    result = resp.json()
    if result.get("code") not in (0, 200):
        raise RuntimeError(f"登录失败: {result}")
    token = result["data"]["token"]
    print(f"[登录] 成功，token 已获取")
    return token


def get_drive_id(token):
    """获取用户信息中的 driveId"""
    headers = get_headers(token)
    resp = requests.get(USER_INFO_URL, headers=headers, timeout=30)
    result = resp.json()
    if result.get("code") not in (0, 200):
        raise RuntimeError(f"获取用户信息失败: {result}")
    data = result.get("data", {})
    drive_id = data.get("driveId") or data.get("DriveId")
    print(f"[用户] driveId={drive_id}")
    return drive_id


def list_files(token, drive_id, parent_id=0):
    """列出指定目录下的文件，返回文件列表"""
    headers = get_headers(token)
    params = {
        "driveId": drive_id,
        "parentFileId": parent_id,
        "page": 1,
        "limit": 100,
        "orderBy": "file_id",
        "orderDirection": "desc",
        "trashed": "false",
        "SearchData": "",
    }
    resp = requests.get(FILE_LIST_URL, headers=headers, params=params, timeout=30)
    result = resp.json()
    if result.get("code") not in (0, 200):
        raise RuntimeError(f"获取文件列表失败: {result}")
    return result.get("data", {}).get("InfoList", [])


def find_or_create_folder(token, drive_id, parent_id, folder_name):
    """查找或创建文件夹，返回 folder_id"""
    files = list_files(token, drive_id, parent_id)
    for f in files:
        if f.get("filename") == folder_name and f.get("Type") == 1:
            print(f"[文件夹] 找到已存在: {folder_name} (id={f['file_id']})")
            return f["file_id"]
    print(f"[文件夹] 创建: {folder_name}")
    headers = get_headers(token)
    payload = {
        "driveId": drive_id,
        "parentFileId": parent_id,
        "filename": folder_name,
        "etag": "",
        "size": 0,
        "duplicate": 2,
    }
    resp = requests.post(UPLOAD_REQUEST_URL, headers=headers, json=payload, timeout=30)
    result = resp.json()
    if result.get("code") not in (0, 200):
        raise RuntimeError(f"创建文件夹失败: {result}")
    data = result.get("data", {})
    folder_id = data.get("fileId") or data.get("file_id") or data.get("FileID")
    if not folder_id:
        files = list_files(token, drive_id, parent_id)
        for f in files:
            if f.get("filename") == folder_name and f.get("Type") == 1:
                folder_id = f["file_id"]
                break
    print(f"[文件夹] 创建成功: {folder_name} (id={folder_id})")
    return folder_id


def calculate_md5(filepath):
    """计算文件 MD5"""
    md5 = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            md5.update(chunk)
    return md5.hexdigest()


def upload_file(token, drive_id, parent_id, filepath):
    """上传文件到指定目录（分块模式）"""
    filename = os.path.basename(filepath)
    filesize = os.path.getsize(filepath)
    filemd5 = calculate_md5(filepath)

    print(f"[上传] 文件: {filename}, 大小: {filesize} bytes, MD5: {filemd5}")

    headers = get_headers(token)

    # 步骤1：请求上传
    payload = {
        "driveId": drive_id,
        "parentFileId": parent_id,
        "filename": filename,
        "etag": filemd5,
        "size": filesize,
        "duplicate": 2,
    }
    resp = requests.post(UPLOAD_REQUEST_URL, headers=headers, json=payload, timeout=30)
    result = resp.json()
    if result.get("code") not in (0, 200):
        raise RuntimeError(f"上传请求失败: {result}")
    data = result["data"]
    print(f"[上传] 请求成功，准备分块上传")

    bucket = data["bucket"]
    key = data["key"]
    upload_id = data["uploadId"]
    file_id = data.get("fileId") or data.get("file_id")

    # 步骤2：分块上传
    with open(filepath, "rb") as f:
        part_number = 1
        parts_info = []
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            chunk_md5 = hashlib.md5(chunk).hexdigest()
            print(f"  [分块 {part_number}] 大小: {len(chunk)} bytes")

            resp = requests.post(
                S3_REPARE_PARTS_URL,
                headers=headers,
                json={
                    "bucket": bucket,
                    "key": key,
                    "uploadId": upload_id,
                    "partNumberList": [part_number],
                },
                timeout=30,
            )
            parts_result = resp.json()
            if parts_result.get("code") not in (0, 200):
                raise RuntimeError(f"获取分块URL失败: {parts_result}")
            part_urls = parts_result["data"]["presignedUrls"]
            upload_url = part_urls[str(part_number)]

            put_resp = requests.put(
                upload_url,
                data=chunk,
                headers={"Content-MD5": chunk_md5, "Content-Type": "application/octet-stream"},
                timeout=120,
            )
            if put_resp.status_code not in (200, 204):
                raise RuntimeError(f"分块 {part_number} 上传失败: HTTP {put_resp.status_code} - {put_resp.text[:200]}")
            etag = put_resp.headers.get("ETag", "").strip('"')
            parts_info.append({"partNumber": part_number, "etag": etag})
            print(f"  [分块 {part_number}] 上传成功, ETag: {etag}")
            part_number += 1

    # 步骤3：完成分块上传
    print(f"[上传] 完成 {part_number - 1} 个分块，合并中...")
    resp = requests.post(
        S3_COMPLETE_URL,
        headers=headers,
        json={
            "bucket": bucket,
            "key": key,
            "uploadId": upload_id,
            "parts": parts_info,
        },
        timeout=60,
    )
    complete_result = resp.json()
    if complete_result.get("code") not in (0, 200):
        raise RuntimeError(f"完成分块上传失败: {complete_result}")
    print(f"[上传] 分块合并成功")

    # 步骤4：完成上传会话
    resp = requests.post(
        UPLOAD_COMPLETE_URL,
        headers=headers,
        json={
            "fileId": file_id,
            "bucket": bucket,
            "key": key,
            "uploadId": upload_id,
            "parentFileId": parent_id,
            "filename": filename,
            "size": filesize,
            "etag": filemd5,
            "duplicate": 2,
        },
        timeout=30,
    )
    final_result = resp.json()
    if final_result.get("code") not in (0, 200):
        raise RuntimeError(f"完成上传会话失败: {final_result}")
    print(f"[上传] 文件 {filename} 上传完成！ (file_id={file_id})")
    return file_id


def main():
    if len(sys.argv) < 3:
        print("用法: python upload_123pan.py <本地文件路径> <云盘目标路径>")
        print("示例: python upload_123pan.py /tmp/file.zip /github/eating-medication/2.2.0.zip")
        sys.exit(1)

    filepath = sys.argv[1]
    target_path = sys.argv[2]

    if not os.path.exists(filepath):
        print(f"错误: 文件不存在: {filepath}")
        sys.exit(1)

    token = login()
    drive_id = get_drive_id(token)

    path_parts = [p for p in target_path.replace("\\", "/").split("/") if p]
    filename = path_parts[-1]
    folder_parts = path_parts[:-1]

    parent_id = 0
    for part in folder_parts:
        parent_id = find_or_create_folder(token, drive_id, parent_id, part)

    upload_file(token, drive_id, parent_id, filepath)
    print(f"\n✅ 上传完成: {filepath} -> {target_path}")


if __name__ == "__main__":
    main()
