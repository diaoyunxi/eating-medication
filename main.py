#!/usr/bin/env python3
"""
吃药提醒 - Eating Medication Reminder
轻量级的用药提醒工具，支持定时提醒和用药记录
"""

import sys
import os
import json
import time
import threading
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

__version__ = "1.0.0"

GITHUB_REPO = "diaoyunxi/eating-medication"

# 配置文件路径
CONFIG_DIR = Path.home() / '.config' / 'eating-medication'
CONFIG_FILE = CONFIG_DIR / 'config.json'
RECORDS_FILE = CONFIG_DIR / 'records.json'


def _fetch_latest_version_github():
    """从 GitHub 获取最新版本号（优先 Releases，回退 Tags）"""
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": "eating-medication"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("tag_name"), data.get("html_url")
    except Exception:
        pass
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/tags"
        req = urllib.request.Request(url, headers={"User-Agent": "eating-medication"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data:
                tag = data[0].get("name")
                return tag, f"https://github.com/{GITHUB_REPO}/releases/tag/{tag}"
    except Exception:
        pass
    return None, None


def _compare_versions(v1, v2):
    """比较两个版本号"""
    parts1 = v1.lstrip('v').split('.')
    parts2 = v2.lstrip('v').split('.')
    for i in range(max(len(parts1), len(parts2))):
        try:
            a = int(parts1[i]) if i < len(parts1) else 0
            b = int(parts2[i]) if i < len(parts2) else 0
            if a > b:
                return 1
            if a < b:
                return -1
        except ValueError:
            return 0
    return 0


def check_for_update():
    """检查 GitHub 上是否有新版本"""
    try:
        latest, release_url = _fetch_latest_version_github()
        if not latest:
            return
        if _compare_versions(latest, __version__) <= 0:
            return
        print(f"\n{'='*50}")
        print(f"  发现新版本！")
        print(f"  当前版本: v{__version__}")
        print(f"  最新版本: {latest}")
        print(f"{'='*50}")
        try:
            choice = input("是否立即更新？(y/N): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if choice == 'y':
            print("正在更新...")
            script_dir = os.path.dirname(os.path.abspath(__file__))
            if os.path.isdir(os.path.join(script_dir, '.git')):
                result = subprocess.run(['git', 'pull'], cwd=script_dir, capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    print("更新成功！请重新运行程序。")
                    sys.exit(0)
            try:
                raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/main.py"
                req = urllib.request.Request(raw_url, headers={"User-Agent": "eating-medication"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    content = resp.read()
                with open(__file__, 'wb') as f:
                    f.write(content)
                print("更新成功！请重新运行程序。")
                sys.exit(0)
            except Exception as e:
                print(f"自动更新失败: {e}")
                print(f"请手动访问 {release_url} 下载最新版本")
    except Exception:
        pass


def load_config():
    """加载配置"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"medications": [], "reminders": []}


def save_config(config):
    """保存配置"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def load_records():
    """加载用药记录"""
    if RECORDS_FILE.exists():
        with open(RECORDS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def save_record(medication_name, notes=""):
    """记录用药"""
    records = load_records()
    records.append({
        "time": datetime.now().isoformat(),
        "medication": medication_name,
        "notes": notes
    })
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(RECORDS_FILE, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def add_medication(config):
    """添加药物"""
    name = input("药物名称: ").strip()
    if not name:
        print("名称不能为空")
        return
    time_str = input("提醒时间 (HH:MM, 多个用逗号分隔): ").strip()
    config["medications"].append({"name": name, "times": [t.strip() for t in time_str.split(",")]})
    save_config(config)
    print(f"已添加: {name}")


def list_medications(config):
    """列出所有药物"""
    if not config["medications"]:
        print("暂无药物")
        return
    for i, med in enumerate(config["medications"]):
        times = ", ".join(med.get("times", []))
        print(f"  {i+1}. {med['name']} - 提醒时间: {times}")


def list_records():
    """查看用药记录"""
    records = load_records()
    if not records:
        print("暂无记录")
        return
    for r in records[-20:]:
        dt = datetime.fromisoformat(r["time"])
        print(f"  {dt.strftime('%Y-%m-%d %H:%M')} - {r['medication']} {r.get('notes', '')}")


def take_medication(config):
    """记录服药"""
    if not config["medications"]:
        print("请先添加药物")
        return
    list_medications(config)
    try:
        idx = int(input("选择药物编号: ")) - 1
        if 0 <= idx < len(config["medications"]):
            name = config["medications"][idx]["name"]
            notes = input("备注 (可选): ").strip()
            save_record(name, notes)
            print(f"已记录服用: {name}")
        else:
            print("无效编号")
    except ValueError:
        print("请输入数字")


def start_reminder(config):
    """启动提醒线程"""
    print("提醒服务已启动 (Ctrl+C 退出)")
    try:
        while True:
            now = datetime.now()
            current_time = now.strftime("%H:%M")
            for med in config["medications"]:
                if current_time in med.get("times", []):
                    print(f"\n⏰ 该吃药了: {med['name']}")
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n提醒服务已停止")


def show_help():
    """显示帮助"""
    print(f"""
{'='*50}
  吃药提醒 v{__version__}
{'='*50}

用法:
  python main.py [命令]

命令:
  add         添加药物
  list        列出所有药物
  take        记录服药
  records     查看用药记录
  remind      启动提醒服务
  help        显示帮助

示例:
  python main.py add
  python main.py remind
""")


def main():
    check_for_update()

    if len(sys.argv) < 2:
        show_help()
        return

    cmd = sys.argv[1]
    config = load_config()

    if cmd == "add":
        add_medication(config)
    elif cmd == "list":
        list_medications(config)
    elif cmd == "take":
        take_medication(config)
    elif cmd == "records":
        list_records()
    elif cmd == "remind":
        start_reminder(config)
    elif cmd == "help":
        show_help()
    else:
        print(f"未知命令: {cmd}")
        show_help()


if __name__ == "__main__":
    main()
