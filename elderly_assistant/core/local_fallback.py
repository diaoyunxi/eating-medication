# -*- coding: utf-8 -*-
class LocalFallback:
    @staticmethod
    def run_basic_reminder(reminder_item, speech, buzzer, config):
        if not speech and not buzzer:
            return

        name = reminder_item.get('name', '您')
        med_name = reminder_item.get('medication', '')
        msg = f"{name}，该吃 {med_name} 了"

        if speech:
            try:
                volume = config.get('buzzer', {}).get('base_volume', 0.5) if config else 0.5
                speech.speak(msg, volume)
            except Exception:
                pass

        if buzzer:
            try:
                buzzer.beep()
            except Exception:
                pass