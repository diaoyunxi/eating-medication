#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 Playwright 截图家属端页面"""
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 800})
        
        # 登录页
        await page.goto("http://localhost:4430/login")
        await page.wait_for_load_state("networkidle")
        await page.screenshot(path="/tmp/login.png", full_page=True)
        print("截图: /tmp/login.png")
        
        # 注册页
        await page.goto("http://localhost:4430/register")
        await page.wait_for_load_state("networkidle")
        await page.screenshot(path="/tmp/register.png", full_page=True)
        print("截图: /tmp/register.png")
        
        await browser.close()

asyncio.run(main())
