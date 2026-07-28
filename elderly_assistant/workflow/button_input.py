# -*- coding: utf-8 -*-
"""按钮输入控制：从主循环中提取按钮 A/B 的边沿检测与长按逻辑，便于单测。

设计：ButtonController 持有按下起始时间戳与长按已触发标志，主循环每帧调用
process()，由回调 on_confirm / on_ai / on_snooze 注入具体动作。
按钮 A 短按=确认服药；长按(>long_press_sec)=问 AI 注意事项（仅提醒激活时）。
按钮 B=暂缓提醒（仅提醒激活时）。
"""
import logging

logger = logging.getLogger("ElderlyAssistant")


class ButtonController:
    def __init__(self, long_press_sec=1.5):
        self.long_press_sec = float(long_press_sec)
        self._btn_a_down_since = 0.0
        self._btn_a_long_fired = False
        # 非阻塞防抖屏蔽截止时间戳（按钮 B 暂缓后短暂屏蔽，避免重复触发）
        self.button_block_until = 0.0

    def process(self, now, button_a, button_b, reminder_state, on_confirm, on_ai, on_snooze):
        """每帧处理按钮状态。

        :param now: 当前时间戳（秒，float）
        :param button_a: 具有 is_pressed() 的对象或 None
        :param button_b: 具有 is_pressed() 的对象或 None
        :param reminder_state: ReminderState 实例
        :param on_confirm/on_ai/on_snooze: 触发对应动作的回调（无参）
        """
        if button_a is not None:
            pressed = button_a.is_pressed()
            if pressed:
                if self._btn_a_down_since == 0.0:
                    self._btn_a_down_since = now
                    self._btn_a_long_fired = False
                elif not self._btn_a_long_fired and (now - self._btn_a_down_since) >= self.long_press_sec:
                    self._btn_a_long_fired = True
                    if reminder_state.active:
                        on_ai()
            else:
                if self._btn_a_down_since != 0.0:
                    if not self._btn_a_long_fired and (now - self._btn_a_down_since) < self.long_press_sec:
                        if reminder_state.active:
                            on_confirm()
                    self._btn_a_down_since = 0.0
                    self._btn_a_long_fired = False
        if button_b is not None and button_b.is_pressed():
            if reminder_state.active:
                on_snooze()
                self.button_block_until = now + 0.3
