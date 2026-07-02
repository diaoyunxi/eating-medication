#!/usr/bin/env python3
"""批量更新所有页面使用统一导航栏"""

import re

pages = {
    'index.html': 'index',
    'dashboard.html': 'dashboard',
    'reminders.html': 'reminders',
    'records.html': 'records',
    'medication_settings.html': 'medication_settings',
    'chat.html': 'chat',
    'settings.html': 'settings',
}

for filename, active in pages.items():
    filepath = f'/workspace/family_monitor/templates/{filename}'
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 1. 在浮动装饰形状后添加 active_page 变量设置
    # 查找浮动装饰形状结束位置
    floating_pattern = r'(</div>\s*</div>\s*<div class="shape shape-3"></div>\s*</div>)'
    if re.search(floating_pattern, content):
        content = re.sub(
            floating_pattern,
            r'\1\n    {% set active_page = "' + active + r'" %}',
            content,
            count=1
        )
    
    # 2. 替换导航栏为 include
    # 查找导航栏开始和结束
    navbar_pattern = r'<!-- 导航栏 -->\s*<nav class="navbar">.*?</nav>'
    navbar_replacement = "{% include '_navbar.html' %}"
    
    content = re.sub(navbar_pattern, navbar_replacement, content, flags=re.DOTALL)
    
    # 写回文件
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f'✓ 已更新 {filename}')

print('\n所有页面导航栏已统一！')
