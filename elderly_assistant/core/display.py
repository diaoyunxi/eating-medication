# -*- coding: utf-8 -*-
"""
屏幕显示模块
行空板M10专用：使用 unihiker 库的 GUI 类控制屏幕显示
所有 pinpong / unihiker 库的导入放在 try-except 中，在非 M10 环境下优雅降级
"""
import logging
import time
from datetime import datetime

logger = logging.getLogger("ElderlyAssistant")


class Display:
    """屏幕显示管理类（基于 unihiker GUI）"""

    # 屏幕中心坐标（行空板 M10 屏幕分辨率 240x320，按横屏常用 240 宽度计算）
    SCREEN_W = 240
    SCREEN_H = 320
    CENTER_X = SCREEN_W // 2
    CENTER_Y = SCREEN_H // 2

    # ---- 主界面底部两行小字布局 ----
    # 设备 ID 与服务器状态原先同处 y=SCREEN_H-30 一行左右分列，横向必然叠压，
    # 故拆为上下两行：状态在上、设备 ID 在下，各占一行互不干扰。
    # 设备 ID 现为 uuid.getnode() 的十进制整数（约 15 位，如 218356669348204），
    # font_size=9 下宽约 75px，单行居中显示绰绰有余，无需截断。
    STATUS_TEXT_Y = SCREEN_H - 34         # 服务器状态行
    UUID_TEXT_Y = SCREEN_H - 20           # 设备 ID 行（下移 14px，与状态行分离）
    BOTTOM_TEXT_SIZE = 9                  # 底部小字字号

    def __init__(self):
        self.gui = None
        # 控件引用
        self._time_text = None          # 主时间显示
        self._date_text = None          # 日期显示
        self._uuid_text = None          # 设备ID 底部小字
        self._status_text = None        # 服务器连接状态底部小字
        self._next_reminder_text = None # 下一个用药提醒
        self._reminder_text = None      # 当前用药提醒（大字）
        self._reminder_dosage_text = None  # 当前用药剂量
        self._hint_text = None          # 提示信息（如配网模式）
        self._scan_button = None        # 「扫码查药」触摸按钮
        self._barcode_text = None        # 扫码结果临时展示文本控件
        self._barcode_content = ""       # 待展示的条码内容
        self._barcode_expire = 0.0       # 条码内容自动清除的过期时刻（monotonic 秒）
        # 提醒界面「确认服药 / 问AI注意事项」两个屏幕触摸按钮（替代原物理按键 A/B）
        self._confirm_button = None
        self._ai_button = None
        # 状态
        self._in_reminder = False       # 是否处于用药提醒界面
        self._scan_handler = None       # 扫码回调（由 main 注入，Display 不依赖扫码实现）
        self._action_handlers = None    # 提醒界面屏幕按钮回调（dict: confirm/ask_ai）
        self._init_gui()

    def _init_gui(self):
        """初始化 unihiker GUI（非 M10 环境降级）"""
        try:
            from unihiker import GUI
            self.gui = GUI()
            logger.info("unihiker GUI 初始化成功")
        except ImportError:
            logger.warning("unihiker 库未安装，屏幕显示不可用（非 M10 环境降级）")
        except Exception as e:
            logger.error(f"GUI 初始化失败: {e}")
            self.gui = None

    # ---------------- 扫码按钮 ----------------

    def set_scan_handler(self, handler):
        """注册「扫码查药」按钮的点击回调。

        由 main 在装配阶段注入（内部启动后台扫码线程），Display 不直接依赖
        摄像头与扫码实现，保持界面层与业务层解耦。传 None 表示不显示该按钮。

        :param handler: 无参可调用对象；注册后主界面重绘时会生成触摸按钮
        """
        self._scan_handler = handler if callable(handler) else None

    def set_action_handlers(self, handlers):
        """注入提醒界面屏幕按钮回调，替代原物理按键 A/B。

        :param handlers: dict，可选键 confirm / ask_ai，
                         对应可调用对象；缺失的键视为空操作。
        """
        if not isinstance(handlers, dict):
            handlers = {}
        self._action_handlers = {
            "confirm": handlers.get("confirm"),
            "ask_ai": handlers.get("ask_ai"),
        }

    def _on_action_clicked(self, key):
        """屏幕动作按钮点击处理：异常隔离，避免回调报错导致 GUI 线程中断。

        :param key: 动作键名（confirm / ask_ai）
        :return: True 表示回调已成功触发
        """
        if not isinstance(self._action_handlers, dict):
            return False
        handler = self._action_handlers.get(key)
        if not callable(handler):
            return False
        try:
            handler()
            return True
        except Exception as e:
            logger.error(f"屏幕按钮[{key}]回调异常: {e}")
            return False

    def _on_scan_clicked(self):
        """扫码按钮点击处理：异常隔离，避免回调报错导致 GUI 线程中断。

        :return: True 表示回调已成功触发
        """
        if self._scan_handler is None:
            return False
        try:
            self._scan_handler()
            return True
        except Exception as e:
            logger.error(f"扫码按钮回调异常: {e}")
            return False

    def _draw_scan_button(self):
        """在主界面底部绘制「扫码查药」触摸按钮（未注册回调或无 GUI 时跳过）。"""
        if not self.gui or self._scan_handler is None:
            return
        add_button = getattr(self.gui, "add_button", None)
        if not callable(add_button):
            # 旧版 unihiker 无 add_button，静默跳过（不影响其它功能）
            logger.warning("当前 unihiker 版本不支持 add_button，扫码按钮不可用")
            return
        try:
            self._scan_button = add_button(
                x=self.CENTER_X, y=258, w=160, h=44,
                text='扫码查药', origin='center',
                onclick=self._on_scan_clicked,
            )
        except Exception as e:
            logger.error(f"绘制扫码按钮失败: {e}")
            self._scan_button = None

    # ---------------- 基础界面 ----------------

    def show_main_screen(self, device_uuid="", server_url="", connected=False):
        """
        绘制主界面框架：
        - 顶部：当前时间（大字体居中）
        - 中部：下一个用药提醒（如有）
        - 底部：服务器连接状态、设备ID（上下两行小字）
        """
        if not self.gui:
            return
        try:
            self.gui.clear()
            self._in_reminder = False
            self._barcode_text = None

            now = datetime.now()
            time_str = now.strftime("%H:%M")
            date_str = now.strftime("%Y-%m-%d")

            # 主时间显示（大字体居中偏上）
            self._time_text = self.gui.draw_digit(
                x=self.CENTER_X, y=110,
                text=time_str, color='#0000FF',
                origin='center', font_size=40
            )
            # 日期显示
            self._date_text = self.gui.draw_text(
                x=self.CENTER_X, y=160,
                text=date_str, font_size=14, color='#666666',
                origin='center'
            )

            # 下一个用药提醒（初始为空）
            self._next_reminder_text = self.gui.draw_text(
                x=self.CENTER_X, y=210,
                text='', font_size=14, color='#2E8B57',
                origin='center'
            )

            # 「扫码查药」触摸按钮（已注册回调时才绘制）
            self._draw_scan_button()

            # 底部第一行：服务器连接状态（居中）
            status_str = self._format_status(server_url, connected)
            self._status_text = self.gui.draw_text(
                x=self.CENTER_X, y=self.STATUS_TEXT_Y,
                text=status_str, font_size=self.BOTTOM_TEXT_SIZE,
                color='#999999', origin='center'
            )
            # 底部第二行：设备 ID（居中，截断显示避免横向溢出）
            self._uuid_text = self.gui.draw_text(
                x=self.CENTER_X, y=self.UUID_TEXT_Y,
                text=self._format_uuid(device_uuid),
                font_size=self.BOTTOM_TEXT_SIZE, color='#999999',
                origin='center'
            )
        except Exception as e:
            logger.error(f"绘制主界面失败: {e}")

    def _format_status(self, server_url, connected):
        """格式化服务器连接状态文本"""
        if connected:
            return f'服务器: 已连接'
        else:
            return f'服务器: 未连接'

    def _format_uuid(self, device_uuid):
        """格式化底部设备 ID 文本。

        设备 ID 为 uuid.getnode() 的十进制整数（约 15 位），完整显示即可，
        家属需据此在子女端绑定设备，故不作截断。

        :param device_uuid: 设备 ID，空值返回占位符
        :return: 形如 'ID: 218356669348204' 的文本
        """
        if not device_uuid:
            return 'ID: --'
        return f'ID: {device_uuid}'

    # ---------------- 时间更新 ----------------

    def show_time(self, dt=None):
        """
        显示/更新当前时间（每秒调用）
        :param dt: datetime 对象，默认 datetime.now()
        """
        if not self.gui:
            return
        if dt is None:
            dt = datetime.now()
        try:
            time_str = dt.strftime("%H:%M")
            date_str = dt.strftime("%Y-%m-%d")
            if self._time_text is None or self._in_reminder:
                # 切回主界面重绘
                self.show_main_screen()
            if self._time_text is not None:
                try:
                    self._time_text.config(text=time_str)
                except Exception:
                    pass
            if self._date_text is not None:
                try:
                    self._date_text.config(text=date_str)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"更新时间显示失败: {e}")

    # ---------------- 用药提醒 ----------------

    def show_reminder(self, drug_name, dosage):
        """
        显示用药提醒（覆盖主界面中部，大字提示）
        屏幕显示"该用药了：XX药，剂量：X片"
        """
        if not self.gui:
            return
        try:
            # 首次进入提醒界面时清屏并重绘框架
            if not self._in_reminder:
                self.gui.clear()
                self._in_reminder = True
                # 清屏会销毁主界面控件，重置扫码按钮引用避免悬空
                self._scan_button = None
                # 切到提醒界面时清除临时条码展示
                self._barcode_text = None
                # 保留时间在顶部小字
                now = datetime.now()
                self._time_text = self.gui.draw_text(
                    x=self.CENTER_X, y=30,
                    text=now.strftime("%H:%M"), font_size=18, color='#666666',
                    origin='center'
                )

            # 提醒标题
            if self._reminder_text is None:
                self._reminder_text = self.gui.draw_text(
                    x=self.CENTER_X, y=120,
                    text=f'该用药了：{drug_name}',
                    font_size=22, color='#FF0000', origin='center'
                )
            else:
                try:
                    self._reminder_text.config(text=f'该用药了：{drug_name}')
                except Exception:
                    pass

            # 剂量
            if self._reminder_dosage_text is None:
                self._reminder_dosage_text = self.gui.draw_text(
                    x=self.CENTER_X, y=170,
                    text=f'剂量：{dosage}',
                    font_size=20, color='#FF8C00', origin='center'
                )
            else:
                try:
                    self._reminder_dosage_text.config(text=f'剂量：{dosage}')
                except Exception:
                    pass

            # 操作提示
            if self._hint_text is None:
                self._hint_text = self.gui.draw_text(
                    x=self.CENTER_X, y=200,
                    text='请点击下方按钮操作',
                    font_size=14, color='#333333', origin='center'
                )

            # 用屏幕触摸按钮替代原物理按键 A/B：确认服药 / 问AI注意事项
            self._draw_action_buttons()
        except Exception as e:
            logger.error(f"显示用药提醒失败: {e}")

    def _draw_action_buttons(self):
        """绘制提醒界面的屏幕触摸按钮（替代物理按键 A/B）。

        横屏 240x320，下方纵向紧凑排列大按钮，便于老人在屏幕上点按。
        注意：unihiker GUI 的按钮方法为 add_button（而非 draw_button，后者不存在），
        旧版本 unihiker 无该方法时静默跳过，避免 AttributeError 导致整页绘制失败。
        """
        if not self.gui:
            return
        # 已绘制则跳过，避免重复叠加（show_reminder 在提醒态可能被多次调用）
        if self._confirm_button is not None:
            return
        add_button = getattr(self.gui, "add_button", None)
        if not callable(add_button):
            # 旧版 unihiker 无 add_button，静默跳过（不影响其它功能）
            logger.warning("当前 unihiker 版本不支持 add_button，提醒按钮不可用")
            return
        try:
            # 按钮尺寸：宽 200 居中，高 22、间隔 4，起始 y=216
            btn_w, btn_h, gap = 200, 22, 4
            start_y = 216
            specs = [
                ("confirm", "确认服药"),
                ("ask_ai", "问AI注意事项"),
            ]
            for idx, (key, label) in enumerate(specs):
                y = start_y + idx * (btn_h + gap)
                btn = add_button(
                    x=self.CENTER_X, y=y, w=btn_w, h=btn_h,
                    text=label, origin='center',
                    onclick=self._make_action_callback(key),
                )
                if key == "confirm":
                    self._confirm_button = btn
                elif key == "ask_ai":
                    self._ai_button = btn
        except Exception as e:
            logger.error(f"绘制提醒按钮失败: {e}")

    def _make_action_callback(self, key):
        """生成绑定到指定动作键的按钮回调（闭包捕获 key）。"""
        return lambda: self._on_action_clicked(key)

    def clear_reminder(self):
        """清除用药提醒界面，返回主界面"""
        if not self.gui:
            return
        try:
            # 重置控件引用，下次 show_time 会重绘主界面
            self._reminder_text = None
            self._reminder_dosage_text = None
            self._hint_text = None
            self._scan_button = None
            self._confirm_button = None
            self._ai_button = None
            self._barcode_text = None
            self._in_reminder = False
            self.show_main_screen()
        except Exception as e:
            logger.error(f"清除用药提醒失败: {e}")

    # ---------------- 配网模式 ----------------

    def show_config_mode(self, hotspot_ssid="M10-Config", ip="10.0.0.1", port=8088):
        """显示配网模式提示（启动初期或配网失败时）"""
        if not self.gui:
            return
        try:
            self.gui.clear()
            self._in_reminder = False
            self._reminder_text = None
            self._reminder_dosage_text = None
            self._hint_text = None
            self._scan_button = None
            self._confirm_button = None
            self._ai_button = None
            self._barcode_text = None

            self.gui.draw_text(
                x=self.CENTER_X, y=100,
                text='配网模式', font_size=28, color='#0000FF',
                origin='center'
            )
            self.gui.draw_text(
                x=self.CENTER_X, y=160,
                text=f'请连接 WiFi: {hotspot_ssid}',
                font_size=16, color='#333333', origin='center'
            )
            self.gui.draw_text(
                x=self.CENTER_X, y=200,
                text=f'浏览器访问 http://{ip}:{port}',
                font_size=14, color='#666666', origin='center'
            )
            self.gui.draw_text(
                x=self.CENTER_X, y=240,
                text='配置 WiFi 与服务器地址',
                font_size=14, color='#666666', origin='center'
            )
            # 重新初始化主界面控件引用（避免更新时间时控件残留）
            self._time_text = None
            self._date_text = None
            self._next_reminder_text = None
        except Exception as e:
            logger.error(f"显示配网模式失败: {e}")

    # ---------------- 连接状态 ----------------

    def show_status(self, server_url, connected):
        """更新服务器连接状态（底部小字）"""
        if not self.gui:
            return
        try:
            status_str = self._format_status(server_url, connected)
            if self._status_text is not None:
                try:
                    self._status_text.config(text=status_str)
                except Exception:
                    pass
            else:
                self._status_text = self.gui.draw_text(
                    x=self.CENTER_X, y=self.STATUS_TEXT_Y,
                    text=status_str, font_size=self.BOTTOM_TEXT_SIZE,
                    color='#999999', origin='center'
                )
        except Exception as e:
            logger.error(f"更新连接状态失败: {e}")

    def show_device_uuid(self, device_uuid):
        """更新底部设备ID显示"""
        if not self.gui:
            return
        try:
            text = self._format_uuid(device_uuid)
            if self._uuid_text is not None:
                try:
                    self._uuid_text.config(text=text)
                except Exception:
                    pass
            else:
                self._uuid_text = self.gui.draw_text(
                    x=self.CENTER_X, y=self.UUID_TEXT_Y,
                    text=text, font_size=self.BOTTOM_TEXT_SIZE,
                    color='#999999', origin='center'
                )
        except Exception as e:
            logger.error(f"更新设备ID显示失败: {e}")

    def show_next_reminder(self, schedule):
        """
        显示下一个用药提醒（如果有）
        :param schedule: 单条提醒 dict（含 drug_name, dosage, time, frequency）或 None
        """
        if not self.gui:
            return
        try:
            if not schedule:
                text = ''
            else:
                drug = schedule.get('drug_name', '')
                dosage = schedule.get('dosage', '')
                t = schedule.get('time', '')
                text = f'下次提醒: {t} {drug} {dosage}'
            if self._next_reminder_text is not None:
                try:
                    self._next_reminder_text.config(text=text)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"更新下次提醒显示失败: {e}")

    # ---------------- 通用 ----------------

    def clear(self):
        """清空屏幕"""
        if not self.gui:
            return
        try:
            self.gui.clear()
            self._time_text = None
            self._date_text = None
            self._uuid_text = None
            self._status_text = None
            self._next_reminder_text = None
            self._reminder_text = None
            self._reminder_dosage_text = None
            self._hint_text = None
            self._scan_button = None
            self._confirm_button = None
            self._ai_button = None
            self._barcode_text = None
            self._in_reminder = False
        except Exception as e:
            logger.error(f"清空屏幕失败: {e}")

    # ---------------- 条码识别结果临时展示 ----------------

    # 主界面中部用于展示扫码结果的区域（避开时间 110、日期 160、下次提醒 210）
    BARCODE_TEXT_Y = 185
    BARCODE_TEXT_SIZE = 16
    BARCODE_TEXT_COLOR = '#2E8B57'     # 醒目绿色，区别于时间蓝色与提醒红色
    BARCODE_MAX_LEN = 22               # 单行最大字符数，超出截断避免横向溢出

    def show_barcode(self, code, duration=10.0):
        """请求在屏幕上临时展示条码识别内容。

        本方法仅记录待展示内容与过期时刻，真正绘制由主循环调用 :meth:`update_barcode`
        在主线程完成（unihiker GUI 控件禁止跨线程操作）。

        :param code: 识别到的条码内容（字符串）
        :param duration: 展示时长（秒），默认 10 秒后自动清除
        """
        if not code:
            return
        self._barcode_content = str(code)[: self.BARCODE_MAX_LEN]
        self._barcode_expire = time.monotonic() + float(duration)
        logger.info(f"请求展示条码: {self._barcode_content}（{duration}s 后清除）")

    def update_barcode(self):
        """主循环每秒调用：绘制未过期的条码内容，过期则清除。

        仅主界面（非提醒界面）展示，避免遮挡用药提醒。
        """
        if not self.gui:
            return
        now = time.monotonic()
        # 已过期：清除残留展示
        if self._barcode_expire and now >= self._barcode_expire:
            if self._barcode_text is not None:
                try:
                    self._barcode_text.config(text='')
                except Exception:
                    pass
                self._barcode_text = None
            self._barcode_content = ''
            self._barcode_expire = 0.0
            return
        # 有未过期内容且处于主界面：绘制（提醒界面由 show_reminder 已清引用，不展示）
        if self._barcode_content and not self._in_reminder:
            if self._barcode_text is None:
                self._barcode_text = self.gui.draw_text(
                    x=self.CENTER_X, y=self.BARCODE_TEXT_Y,
                    text=self._barcode_content, font_size=self.BARCODE_TEXT_SIZE,
                    color=self.BARCODE_TEXT_COLOR, origin='center'
                )
            else:
                try:
                    self._barcode_text.config(text=self._barcode_content)
                except Exception:
                    pass
