# -*- coding: utf-8 -*-
import sys
import os
import time
import threading
import json
import yaml
from services.ws_client import WebSocketClient
from datetime import datetime, timedelta
from utils.config_loader import save_config


class TUIApplication:
    """TUI应用主类"""

    def __init__(self, config, schedules, med_manager, speech, buzzer,
                 http_client, ai_client, reminder_manager):
        self.config = config
        self.config_data = config.copy()  # 用于编辑的配置副本
        self.schedules = schedules
        self.med_manager = med_manager
        self.speech = speech
        self.buzzer = buzzer
        self.http_client = http_client
        self.ai_client = ai_client
        self.reminder_manager = reminder_manager
        self.ws_client = None
        self.message_manager = None

        self.running = False
        self.current_menu = 'main'
        self.selected_index = 0
        self.message = ''
        self.message_timer = 0

        # 主菜单
        self.main_menu = [
            ('💊', '确认本次用药', 'confirm'),
            ('📷', '拍照识别药品', 'scan'),
            ('💬', '询问助手', 'ask'),
            ('📨', '查看消息', 'messages'),
            ('⏰', '提醒设置', 'reminder'),
            ('💊', '药品存量', 'inventory'),
            ('🔗', '检查服务器连接', 'check_conn'),
            ('⚙️', '系统设置', 'settings'),
        ]

        # 状态跟踪
        self.screen = 'menu'  # menu, input, time_select, days_select, yesno
        self.input_buffer = ''
        self.input_prompt = ''
        self.input_callback = None
        self.yesno_question = ''
        self.yesno_callback = None

        # 时间选择
        self.time_hour = 8
        self.time_min = 0
        self.time_select_mode = 'hour'

        # 提醒编辑
        self.editing_reminder = None
        self.new_reminder = {
            'name': '',
            'medication': '',
            'time': '08:00',
            'dosage': '1片',
            'days': [1, 2, 3, 4, 5],
            'enabled': True
        }
        self.days_select_index = 0
        self.reminder_step = 'name'

        # A/B键同时按下处理
        self.a_pressed = False
        self.a_time = 0
        self.b_pressed = False
        self.b_time = 0
        self.COOLDOWN = 0.3
        
        # 启动欢迎
        self._speak_text('老人用药助手已启动，请使用A键选择，B键确认')

    def save_config(self):
        """保存配置到文件"""
        save_config(self.config_data)


    def sync_data_from_server(self):
        """从服务端同步用药计划和药品数据"""
        self.show_message('正在从服务端同步数据...')
        
        if not self.http_client:
            self.show_message('HTTP客户端未初始化')
            return
        
        try:
            plans = self.http_client.get_medication_plans()
            if plans:
                self.schedules = []
                for plan in plans:
                    drug_name = plan.get('drug_name', '')
                    dosage = plan.get('dosage', '1片')
                    schedule_times = plan.get('schedule_times', [])
                    frequency = plan.get('frequency', 'daily')
                    
                    for time_str in schedule_times:
                        self.schedules.append({
                            'id': plan.get('id'),
                            'name': '老人',
                            'medication': drug_name,
                            'time': time_str,
                            'dosage': dosage,
                            'days': [1, 2, 3, 4, 5, 6, 7] if frequency == 'daily' else [1, 3, 5, 7],
                            'enabled': True
                        })
                
                if self.med_manager:
                    self.med_manager.sync_from_server()
                
                self.show_message(f'同步成功！{len(self.schedules)}条提醒计划')
            else:
                self.show_message('服务端暂无数据')
        except Exception as e:
            self.show_message(f'同步失败: {e}')

    def save_schedules(self):
        """保存提醒计划"""
        schedules_path = os.path.join("data", "schedules.json")
        with open(schedules_path, 'w', encoding='utf-8') as f:
            json.dump(self.schedules, f, indent=2, ensure_ascii=False)

    def show_message(self, msg, duration=3):
        """显示消息"""
        self.message = msg
        self.message_timer = time.time() + duration
        if self.speech:
            try:
                self.speech.speak(msg)
            except:
                pass

    def draw(self):
        """绘制界面"""
        os.system('cls' if os.name == 'nt' else 'clear')

        print('=' * 60)
        print(f"{'老人用药助手':^60}")
        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S'):^60}")
        print('=' * 60)
        print()

        if self.screen == 'menu':
            self.draw_menu()
        elif self.screen == 'input':
            self.draw_input()
        elif self.screen == 'time_select':
            self.draw_time_select()
        elif self.screen == 'days_select':
            self.draw_days_select()
        elif self.screen == 'yesno':
            self.draw_yesno()
        elif self.screen == 'reminder_add':
            self.draw_reminder_add()

        print()
        print('=' * 60)
        if self.screen == 'menu' and self.current_menu == 'settings':
            print(f"{'A键: 下一个  B键: 编辑  A+B: 保存并退出':^60}")
        elif self.screen == 'yesno':
            print(f"{'A键: 是  B键: 否':^60}")
        elif self.screen == 'time_select':
            print(f"{'A键: +1  B键: 切换/确定':^60}")
        elif self.screen == 'days_select':
            print(f"{'A键: 切换  B键: 选择/确定':^60}")
        elif self.screen == 'reminder_add':
            print(f"{'A键: 下一选项  B键: 编辑/确定':^60}")
        else:
            print(f"{'A键: 下一个选项  B键: 确定':^60}")

        if self.message and time.time() < self.message_timer:
            print()
            print(f"{'★ ' + self.message + ' ★':^60}")

    def draw_menu(self):
        """绘制菜单"""
        menu = self.get_current_menu()
        for i, (icon, text, action) in enumerate(menu):
            prefix = '> ' if i == self.selected_index else '  '
            print(f"{prefix}{icon} {text}")

    def draw_input(self):
        """绘制输入界面"""
        print(self.input_prompt)
        print()
        print(f"> {self.input_buffer}_")
        print()
        print("提示: A键删除, B键确认")

    def draw_time_select(self):
        """绘制时间选择界面"""
        print("选择时间:")
        print()
        hour_text = f"[{self.time_hour:02d}]" if self.time_select_mode == 'hour' else f" {self.time_hour:02d} "
        min_text = f"[{self.time_min:02d}]" if self.time_select_mode == 'minute' else f" {self.time_min:02d} "
        print(f"时间: {hour_text}:{min_text}")
        print()
        print("提示: A键+1, B键切换/确认")

    def draw_days_select(self):
        """绘制重复日期选择界面"""
        print("选择重复日期:")
        print()
        days = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        for i, day in enumerate(days):
            prefix = '> ' if i == self.days_select_index else '  '
            selected = '✓' if (i + 1) in self.new_reminder['days'] else ' '
            print(f"{prefix}{selected} {day}")
        print()
        print("提示: A键切换, B键选择, A+B完成")

    def draw_yesno(self):
        """绘制是/否选择界面"""
        print(self.yesno_question)
        print()
        print(f"{'> 是' if self.selected_index == 0 else '  是'}")
        print(f"{'> 否' if self.selected_index == 1 else '  否'}")

    def draw_reminder_add(self):
        """绘制添加提醒界面"""
        steps = [
            ('姓名', self.new_reminder['name']),
            ('药品', self.new_reminder['medication']),
            ('时间', self.new_reminder['time']),
            ('用量', self.new_reminder['dosage']),
            ('重复', self._format_days()),
            ('完成', '')
        ]
        print("添加提醒:")
        print()
        for i, (label, value) in enumerate(steps):
            prefix = '> ' if i == self.selected_index else '  '
            display = value if value else '(未设置)'
            print(f"{prefix}{label}: {display}")

    def _format_days(self):
        """格式化重复天数显示"""
        days = self.new_reminder.get('days', [])
        if not days:
            return '无'
        days_text = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        selected = [days_text[d - 1] for d in sorted(days)]
        return ','.join(selected) if len(selected) <= 3 else f'{len(selected)}天'

    def get_current_menu(self):
        """获取当前菜单"""
        if self.current_menu == 'main':
            return self.main_menu
        elif self.current_menu == 'reminder':
            return self.get_reminder_menu()
        elif self.current_menu == 'inventory':
            return self.get_inventory_menu()
        elif self.current_menu == 'settings':
            return self.get_settings_menu()
        return self.main_menu

    def get_reminder_menu(self):
        """获取提醒菜单"""
        menu = [('←', '返回主菜单', 'back'), ('➕', '添加提醒', 'add')]
        if self.schedules:
            for idx, s in enumerate(self.schedules):
                time_val = s.get('time', '??:??')
                name = s.get('name', '提醒')
                enabled = s.get('enabled', True)
                status = '✓' if enabled else '✗'
                menu.append((f"{status} {time_val}", name, f'view_{idx}'))
        else:
            menu.append(('📝', '暂无提醒', 'none'))
        return menu

    def get_inventory_menu(self):
        """获取药品库存菜单"""
        menu = [('←', '返回主菜单', 'back')]
        meds = self.med_manager.get_all() if self.med_manager else []
        if meds:
            for med in meds:
                name = med.get('name', '未知')
                remaining = med.get('remaining', 0)
                total = med.get('total', 0)
                menu.append((f"💊 {remaining}/{total}", name, 'view'))
        else:
            menu.append(('📦', '暂无药品', 'none'))
        return menu

    def get_settings_menu(self):
        """获取系统设置菜单"""
        server_url = self.config_data.get('server', {}).get('base_url', '')
        device_id = self.http_client.get_device_id() if self.http_client else '未知'
        return [
            ('←', '返回主菜单', 'back'),
            ('📱', f'设备FCC ID: {device_id}', 'device_id'),
            ('🌐', f'服务器地址: {server_url or "未设置"}', 'server_url'),
        ]

    def handle_a(self):
        """处理A键"""
        if self.screen == 'menu':
            menu = self.get_current_menu()
            self.selected_index = (self.selected_index + 1) % len(menu)
            # 语音播报当前选中项
            if menu and self.selected_index < len(menu):
                self._speak_menu_item(menu[self.selected_index])
        elif self.screen == 'yesno':
            self.selected_index = 1 - self.selected_index
            # 语音播报当前选择
            if self.selected_index == 0:
                self._speak_text('是')
            else:
                self._speak_text('否')
        elif self.screen == 'time_select':
            if self.time_select_mode == 'hour':
                self.time_hour = (self.time_hour + 1) % 24
                self._speak_text(f'{self.time_hour}点')
            else:
                self.time_min = (self.time_min + 1) % 60
                self._speak_text(f'{self.time_min}分')
        elif self.screen == 'days_select':
            self.days_select_index = (self.days_select_index + 1) % 7
            day_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
            self._speak_text(day_names[self.days_select_index])
        elif self.screen == 'reminder_add':
            self.selected_index = (self.selected_index + 1) % 6
            steps = ['姓名', '药品', '时间', '用量', '重复日期', '完成']
            self._speak_text(f'{steps[self.selected_index]}')
        elif self.screen == 'input':
            if self.input_buffer:
                self.input_buffer = self.input_buffer[:-1]
                self._speak_text('删除')

    def _speak_menu_item(self, menu_item):
        """语音播报菜单项"""
        if self.speech and menu_item:
            text = menu_item[1]
            self.speech.speak(text)

    def _speak_text(self, text):
        """语音播报文字"""
        if self.speech:
            self.speech.speak(text)

    def handle_b(self):
        """处理B键"""
        self._speak_text('确认')
        if self.screen == 'menu':
            menu = self.get_current_menu()
            if self.selected_index < len(menu):
                action = menu[self.selected_index][2]
                self.handle_action(action)
        elif self.screen == 'yesno':
            if self.yesno_callback:
                self.yesno_callback(self.selected_index == 0)
            self.screen = 'menu'
            self.current_menu = 'main'
            self.selected_index = 0
        elif self.screen == 'time_select':
            if self.time_select_mode == 'hour':
                self.time_select_mode = 'minute'
                self._speak_text('设置分钟')
            else:
                self.new_reminder['time'] = f"{self.time_hour:02d}:{self.time_min:02d}"
                self.screen = 'reminder_add'
                self.selected_index = 3
                self._speak_text('时间已设置')
        elif self.screen == 'days_select':
            day_num = self.days_select_index + 1
            day_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
            if day_num in self.new_reminder['days']:
                self.new_reminder['days'].remove(day_num)
                self._speak_text(f'取消{day_names[day_num-1]}')
            else:
                self.new_reminder['days'].append(day_num)
                self._speak_text(f'选中{day_names[day_num-1]}')
        elif self.screen == 'reminder_add':
            self.handle_reminder_step()
        elif self.screen == 'input':
            if self.input_callback:
                self.input_callback(self.input_buffer)
            self.screen = 'menu'
            self.input_buffer = ''

    def handle_both(self):
        """处理A+B同时按下"""
        self._speak_text('保存并返回')
        if self.current_menu == 'settings':
            self.save_config()
            self.show_message('设置已保存')
            self.current_menu = 'main'
            self.selected_index = 0
        elif self.screen == 'days_select':
            self.new_reminder['days'] = sorted(self.new_reminder['days'])
            self.screen = 'reminder_add'
            self.selected_index = 5
            self._speak_text('重复日期已设置')

    def handle_reminder_step(self):
        """处理添加提醒的各步骤"""
        step = self.selected_index
        if step == 0:
            self.screen = 'input'
            self.input_buffer = self.new_reminder['name']
            self.input_prompt = '请输入姓名:'

            def callback(text):
                self.new_reminder['name'] = text
                self.screen = 'reminder_add'
                self.selected_index = 1
            self.input_callback = callback
        elif step == 1:
            self.screen = 'input'
            self.input_buffer = self.new_reminder['medication']
            self.input_prompt = '请输入药品名称:'

            def callback(text):
                self.new_reminder['medication'] = text
                self.screen = 'reminder_add'
                self.selected_index = 2
            self.input_callback = callback
        elif step == 2:
            t = self.new_reminder['time'].split(':')
            self.time_hour = int(t[0])
            self.time_min = int(t[1])
            self.time_select_mode = 'hour'
            self.screen = 'time_select'
        elif step == 3:
            self.screen = 'input'
            self.input_buffer = self.new_reminder['dosage']
            self.input_prompt = '请输入用量(如1片):'

            def callback(text):
                self.new_reminder['dosage'] = text
                self.screen = 'reminder_add'
                self.selected_index = 4
            self.input_callback = callback
        elif step == 4:
            self.days_select_index = 0
            self.screen = 'days_select'
        elif step == 5:
            self.save_new_reminder()

    def save_new_reminder(self):
        """保存新提醒"""
        if not self.new_reminder['name']:
            self.show_message('请先输入姓名')
            self.selected_index = 0
            return
        self.schedules.append(dict(self.new_reminder))
        self.save_schedules()
        self.show_message(f'已添加提醒: {self.new_reminder["name"]}')
        self.new_reminder = {
            'name': '',
            'medication': '',
            'time': '08:00',
            'dosage': '1片',
            'days': [1, 2, 3, 4, 5],
            'enabled': True
        }
        self.current_menu = 'reminder'
        self.screen = 'menu'
        self.selected_index = 0

    def handle_action(self, action):
        """处理菜单动作"""
        if action == 'back':
            self.current_menu = 'main'
            self.selected_index = 0
        elif action == 'confirm':
            self.do_confirm_medication()
        elif action == 'scan':
            self.do_scan_medicine()
        elif action == 'ask':
            self.do_ask_assistant()
        elif action == 'messages':
            self.view_messages()
        elif action == 'reminder':
            self.current_menu = 'reminder'
            self.selected_index = 0
        elif action == 'add':
            self.new_reminder = {
                'name': '',
                'medication': '',
                'time': '08:00',
                'dosage': '1片',
                'days': [1, 2, 3, 4, 5],
                'enabled': True
            }
            self.selected_index = 0
            self.screen = 'reminder_add'
        elif action == 'inventory':
            self.current_menu = 'inventory'
            self.selected_index = 0
        elif action == 'sync_data':
            self.sync_data_from_server()
        elif action == 'check_conn':
            self.do_check_connection()
        elif action == 'settings':
            self.current_menu = 'settings'
            self.selected_index = 0
        elif action == 'device_id':
            device_id = self.http_client.get_device_id() if self.http_client else '未知'
            self.show_message(f'设备FCC ID: {device_id}，请在子女端输入此ID完成绑定', 5)
        elif action == 'server_url':
            self.screen = 'input'
            current_url = self.config_data.get('server', {}).get('base_url', '')
            self.input_buffer = current_url
            self.input_prompt = '请输入服务器地址:'

            def callback(url):
                if 'server' not in self.config_data:
                    self.config_data['server'] = {}
                self.config_data['server']['base_url'] = url
                self.save_config()
                self.show_message(f'服务器地址已保存: {url}')
                self.screen = 'menu'
                self.current_menu = 'settings'
                self.selected_index = 1
            self.input_callback = callback
        elif action.startswith('view_'):
            idx = int(action.split('_')[1])
            self.screen = 'yesno'
            self.selected_index = 0
            self.yesno_question = f"确定删除提醒: {self.schedules[idx].get('name', '')}"

            def callback(yes):
                if yes:
                    del self.schedules[idx]
                    self.save_schedules()
                    self.show_message('已删除提醒')
                self.screen = 'menu'
                self.current_menu = 'reminder'
                self.selected_index = 0
            self.yesno_callback = callback
        elif action == 'none':
            pass

    def do_confirm_medication(self):
        """确认用药"""
        self.show_message('检查提醒时间...')
        now = datetime.now()
        in_time = False
        current_reminder = None

        if self.reminder_manager and hasattr(self.reminder_manager, 'active_reminders'):
            for rid, info in list(self.reminder_manager.active_reminders.items()):
                if not info.get('confirmed', False):
                    current_reminder = info
                    in_time = True

        if not in_time:
            # 检查是否在最近的提醒时间前后30分钟内
            for s in self.schedules:
                reminder_time = datetime.strptime(s.get('time', '00:00'), '%H:%M').time()
                reminder_dt = datetime.combine(now.date(), reminder_time)
                diff = abs((now - reminder_dt).total_seconds())
                if diff <= 30 * 60:
                    in_time = True
                    current_reminder = s
                    break

        if in_time:
            self.screen = 'yesno'
            self.selected_index = 0
            self.yesno_question = f"确认现在服用{current_reminder.get('medication', '药品')}?"

            def callback(yes):
                if yes:
                    self.capture_and_upload(confirm=True, reminder_info=current_reminder)
                else:
                    self.screen = 'menu'
                    self.current_menu = 'main'
                    self.selected_index = 0
            self.yesno_callback = callback
        else:
            self.show_message('现在不是用药时间')
            if self.speech:
                try:
                    self.speech.speak('现在不是用药时间，请确认')
                except:
                    pass

    def do_scan_medicine(self):
        """拍照识别药品"""
        self.show_message('准备拍照...')
        self.capture_and_upload(confirm=False)

    def do_check_connection(self):
        """检查服务器连接状态"""
        self.show_message('正在检查服务器连接...')
        server_url = self.config_data.get('server', {}).get('base_url', '')
        
        if not server_url:
            self.show_message('请先在系统设置中配置服务器地址')
            return
        
        if not self.http_client:
            self.show_message('HTTP客户端未初始化')
            return
        
        is_connected = self.http_client.check_connection()
        if is_connected:
            self.show_message(f'✅ 服务器连接成功！地址: {server_url}')
        else:
            self.show_message(f'❌ 服务器连接失败！地址: {server_url}')


    def view_messages(self):
        """查看消息"""
        if not self.ws_client:
            self.show_message('消息服务未启动')
            return
            
        messages = self.ws_client.get_messages(20)
        if not messages:
            self.show_message('暂无消息')
            return
            
        msg_list = []
        for i, msg in enumerate(messages[-10:], 1):
            msg_type = msg.get('type', '未知')
            msg_content = msg.get('content', '')
            msg_list.append(f"{i}. [{msg_type}] {msg_content}")
            
        self.show_message('\n'.join(msg_list), 10)
        
        self.screen = 'yesno'
        self.selected_index = 0
        self.yesno_question = '是否发送消息？'
        
        def callback(send):
            if send:
                self.send_message()
            else:
                self.screen = 'menu'
                self.current_menu = 'main'
                self.selected_index = 0
        self.yesno_callback = callback
        
    def send_message(self):
        """发送消息"""
        if not self.ws_client or not self.ws_client.connected:
            self.show_message('消息服务未连接')
            self.screen = 'menu'
            self.current_menu = 'main'
            return
            
        self.screen = 'input'
        self.input_buffer = ''
        self.input_prompt = '请输入消息内容:'
        
        def callback(message):
            if message.strip():
                success = self.ws_client.send_message('chat', message)
                if success:
                    self.show_message('消息已发送')
                else:
                    self.show_message('消息发送失败')
            else:
                self.show_message('未输入消息')
            self.screen = 'menu'
            self.current_menu = 'main'
            self.selected_index = 0
        self.input_callback = callback

    def do_ask_assistant(self):
        """询问助手（支持语音和打字两种方式）"""
        if not self.http_client:
            self.show_message('AI助手未启用')
            return

        # 检查是否有语音功能
        has_voice = self.speech is not None and self.speech._recognizer is not None

        if has_voice:
            # 有语音功能，询问用户选择输入方式
            self.screen = 'yesno'
            self.selected_index = 0
            self.yesno_question = '使用语音输入？[是=语音 否=打字]'

            def callback(use_voice):
                if use_voice:
                    self._ask_assistant_voice()
                else:
                    self._ask_assistant_text()
            self.yesno_callback = callback
        else:
            # 没有语音功能，直接使用打字输入
            self._speak_text('语音功能不可用，请使用打字输入')
            self._ask_assistant_text()

    def _ask_assistant_voice(self):
        """语音询问助手，语音识别不可用时回退到打字输入"""
        self.show_message('语音识别不可用，请使用打字输入')
        self._ask_assistant_text()
    def _ask_assistant_text(self):
        """打字询问助手"""
        self.screen = 'input'
        self.input_buffer = ''
        self.input_prompt = '请输入你的问题:'

        def callback(question):
            if question.strip():
                self.show_message(f'你问: {question}')
                try:
                    answer = self.http_client.ask_ai(question)
                    self.show_message(f'回答: {answer}')
                    if self.speech:
                        self.speech.speak(answer)
                except Exception as e:
                    self.show_message(f'AI错误: {e}')
            else:
                self.show_message('未输入问题')
            self.screen = 'menu'
            self.current_menu = 'main'
            self.selected_index = 0
        self.input_callback = callback

    def capture_and_upload(self, confirm=False, reminder_info=None):
        """使用 HuskyLens 拍照并上传"""
        try:
            from core.camera import get_huskylens

            self.show_message('正在连接 HuskyLens...')
            try:
                hl = get_huskylens(self.config)
                self.show_message('请对准药品...')
                time.sleep(2)

                hl.takePhoto()
                self.show_message('拍照完成')

                save_dir = self.config.get('camera', {}).get('save_path', 'data/captures')
                os.makedirs(save_dir, exist_ok=True)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"capture_{timestamp}.jpg"
                filepath = os.path.join(save_dir, filename)

                if self.http_client:
                    success = self.http_client.upload_medicine_photo(filepath)
                    if success:
                        self.show_message('照片已上传')
                    else:
                        self.show_message('照片上传失败')
            except Exception as e:
                self.show_message(f'拍照出错: {e}')
        except ImportError:
            self.show_message('未安装 dfrobot_huskylensv2 库')
    def get_key(self):
        """获取按键（非阻塞）"""
        if os.name == 'nt':
            import msvcrt
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                if ch == b'\r':
                    return '\n'
                return ch.decode('utf-8', errors='ignore')
            return None
        else:
            import termios
            import tty
            import select

            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setraw(sys.stdin.fileno())
                rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
                if rlist:
                    ch = sys.stdin.read(1)
                    return ch
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            return None


    def _start_websocket(self):
        """启动 WebSocket 连接"""
        try:
            server_url = self.config_data.get('server', {}).get('base_url', '')
            if not server_url:
                return
                
            device_id = self.http_client.get_device_id() if self.http_client else 'unknown'
            
            def on_message(msg):
                msg_type = msg.get('type', '')
                msg_content = msg.get('content', '')
                self.show_message(f'新消息: [{msg_type}] {msg_content}', 5)
                
            self.ws_client = WebSocketClient(server_url, device_id, on_message)
            self.ws_client.connect()
            
        except Exception as e:
            logger.error(f"启动 WebSocket 失败: {e}")

    def run(self):
        """运行TUI主循环"""
        self.running = True
        self._start_websocket()
        self.draw()

        try:
            while self.running:
                key = self.get_key()

                if key:
                    needs_refresh = True

                    if key.lower() == 'q':
                        if self.current_menu != 'settings':
                            if self.screen != 'menu':
                                self.screen = 'menu'
                                self.current_menu = 'main'
                            else:
                                self.running = False
                                break
                        else:
                            self.show_message('请A+B保存并退出')
                    elif key.lower() == 'a':
                        self.a_pressed = True
                        self.a_time = time.time()
                        if self.b_pressed and (time.time() - self.b_time < self.COOLDOWN):
                            self.handle_both()
                            self.b_pressed = False
                        else:
                            self.handle_a()
                    elif key.lower() == 'b':
                        self.b_pressed = True
                        self.b_time = time.time()
                        if self.a_pressed and (time.time() - self.a_time < self.COOLDOWN):
                            self.handle_both()
                            self.a_pressed = False
                        else:
                            self.handle_b()
                    elif self.screen == 'input' and key.isprintable():
                        self.input_buffer += key
                        self._speak_text(key)
                    elif self.screen == 'input' and key in ('\x7f', '\b'):
                        self.input_buffer = self.input_buffer[:-1]
                        self._speak_text('删除')
                    elif self.screen == 'input' and key in ('\n', '\r'):
                        self._speak_text('确认输入')
                        if self.input_callback:
                            self.input_callback(self.input_buffer)
                        self.screen = 'menu'
                        self.input_buffer = ''
                    else:
                        needs_refresh = False

                    if needs_refresh:
                        self.draw()

                # 清理过期按键状态
                now = time.time()
                if self.a_pressed and now - self.a_time > self.COOLDOWN:
                    self.a_pressed = False
                if self.b_pressed and now - self.b_time > self.COOLDOWN:
                    self.b_pressed = False

                time.sleep(0.01)
        except KeyboardInterrupt:
            pass
        finally:
            print('\n再见!\n')
