#!/usr/bin/env python3
"""使用 Playwright 截图检查 UI"""

from playwright.sync_api import sync_playwright
import time

def take_screenshots():
    with sync_playwright() as p:
        # 启动浏览器
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1920, 'height': 1080})
        
        # 家属端页面
        family_pages = [
            ('http://localhost:4430/login', '/workspace/family_login.png'),
            ('http://localhost:4430/register', '/workspace/family_register.png'),
        ]
        
        for url, path in family_pages:
            try:
                print(f"正在截图: {url}")
                page.goto(url, wait_until='networkidle')
                time.sleep(2)  # 等待动画完成
                page.screenshot(path=path, full_page=True)
                print(f"✓ 已保存: {path}")
            except Exception as e:
                print(f"✗ 截图失败 {url}: {e}")
        
        # 服务端页面
        server_pages = [
            ('http://localhost:1059/login', '/workspace/server_login.png'),
        ]
        
        for url, path in server_pages:
            try:
                print(f"正在截图: {url}")
                page.goto(url, wait_until='networkidle')
                time.sleep(2)
                page.screenshot(path=path, full_page=True)
                print(f"✓ 已保存: {path}")
            except Exception as e:
                print(f"✗ 截图失败 {url}: {e}")
        
        browser.close()
        print("\n截图完成!")

if __name__ == '__main__':
    take_screenshots()
