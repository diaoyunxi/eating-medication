# -*- coding: utf-8 -*-
"""
屏幕显示模块
行空板M10专用：使用 unihiker 库的 GUI 类控制屏幕显示
所有 pinpong / unihiker 库的导入放在 try-except 中，在非 M10 环境下优雅降级
"""
import logging
from datetime import datetime

logger = logging.getLogger("ElderlyAssistant")


class Display:
    """屏幕显示管理类（基于 unihiker GUI）"""

    # 屏幕中心坐标（行空板 M10 屏幕分辨率 240x320，按横屏常用 240 宽度计算）
    SCREEN_W = 240
    SCREEN_H = 320
    CENTER_X = SCREEN_W // 2
    CENTER_Y = SCREEN_H // 2

    def __init__(self):
        self.gui = None
        # 控件引用
        self._time_text = None          # 主时间显示
        self._date_text = None          # 日期显示
        self._fcc_text = None           # FCC ID 底部小字
        self._status_text = None        # 服务器连接状态底部小字
        self._next_reminder_text = None # 下一个用药提醒
        self._reminder_text = None      # 当前用药提醒（大字）
        self._reminder_dosage_text = None  # 当前用药剂量
        self._hint_text = None          # 提示信息（如配网模式）
        # 状态
        self._in_reminder = False       # 是否处于用药提醒界面
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

    # ---------------- 基础界面 ----------------

    def show_main_screen(self, fcc_id="", server_url="", connected=False):
        """
        绘制主界面框架：
        - 顶部：当前时间（大字体居中）
        - 中部：下一个用药提醒（如有）
        - 底部：FCC ID、服务器连接状态（小字）
        """
        if not self.gui:
            return
        try:
            self.gui.clear()
            self._in_reminder = False

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

            # 底部 FCC ID（小字）
            self._fcc_text = self.gui.draw_text(
                x=10, y=self.SCREEN_H - 30,
                text=f'FCC: {fcc_id}' if fcc_id else 'FCC: --',
                font_size=10, color='#999999'
            )
            # 底部服务器连接状态
            status_str = self._format_status(server_url, connected)
            self._status_text = self.gui.draw_text(
                x=self.SCREEN_W - 10, y=self.SCREEN_H - 30,
                text=status_str, font_size=10, color='#999999',
                origin='top right'
            )
        except Exception as e:
            logger.error(f"绘制主界面失败: {e}")

    def _format_status(self, server_url, connected):
        """格式化服务器连接状态文本"""
        if connected:
            return f'服务器: 已连接'
        else:
            return f'服务器: 未连接'

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
        屏幕显示"该吃XX药了，剂量：X片"
        """
        if not self.gui:
            return
        try:
            # 首次进入提醒界面时清屏并重绘框架
            if not self._in_reminder:
                self.gui.clear()
                self._in_reminder = True
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
                    text=f'该吃 {drug_name} 了',
                    font_size=22, color='#FF0000', origin='center'
                )
            else:
                try:
                    self._reminder_text.config(text=f'该吃 {drug_name} 了')
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
                    x=self.CENTER_X, y=230,
                    text='按A确认服药  按B稍后提醒',
                    font_size=14, color='#333333', origin='center'
                )
        except Exception as e:
            logger.error(f"显示用药提醒失败: {e}")

    def clear_reminder(self):
        """清除用药提醒界面，返回主界面"""
        if not self.gui:
            return
        try:
            # 重置控件引用，下次 show_time 会重绘主界面
            self._reminder_text = None
            self._reminder_dosage_text = None
            self._hint_text = None
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
                    x=self.SCREEN_W - 10, y=self.SCREEN_H - 30,
                    text=status_str, font_size=10, color='#999999',
                    origin='top right'
                )
        except Exception as e:
            logger.error(f"更新连接状态失败: {e}")

    def show_fcc_id(self, fcc_id):
        """更新底部 FCC ID 显示"""
        if not self.gui:
            return
        try:
            text = f'FCC: {fcc_id}' if fcc_id else 'FCC: --'
            if self._fcc_text is not None:
                try:
                    self._fcc_text.config(text=text)
                except Exception:
                    pass
            else:
                self._fcc_text = self.gui.draw_text(
                    x=10, y=self.SCREEN_H - 30,
                    text=text, font_size=10, color='#999999'
                )
        except Exception as e:
            logger.error(f"更新 FCC ID 显示失败: {e}")

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
            self._fcc_text = None
            self._status_text = None
            self._next_reminder_text = None
            self._reminder_text = None
            self._reminder_dosage_text = None
            self._hint_text = None
            self._in_reminder = False
        except Exception as e:
            logger.error(f"清空屏幕失败: {e}")
