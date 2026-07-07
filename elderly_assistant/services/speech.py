# -*- coding: utf-8 -*-
import queue
import threading
import time
from utils.logger import setup_logger


class Speech:
    def __init__(self, config=None):
        self.logger = setup_logger()
        self.config = config.get('speech', {}) if (config and 'speech' in config) else {}
        self._speak_queue = queue.Queue()
        self._stop_event = threading.Event()
        self._engine = None

        self._init_engine()

        if self._engine:
            self._worker_thread = threading.Thread(target=self._speak_worker, daemon=True)
            self._worker_thread.start()

    def _init_engine(self):
        try:
            import pyttsx3
            self._engine = pyttsx3.init()
            self._engine.setProperty('volume', 50 / 100)
            self._engine.setProperty('rate', 200)
            self.logger.info("pyttsx3 TTS engine initialized")
            return True
        except Exception as e:
            self.logger.error(f"pyttsx3 init failed: {e}")
            self._engine = None
            return False

    def _speak_worker(self):
        while not self._stop_event.is_set():
            try:
                text = self._speak_queue.get(timeout=1)
                if text is None:
                    break

                try:
                    self._engine.say(text)
                    self._engine.runAndWait()
                except Exception as e:
                    self.logger.error(f"Speech failed '{text[:50]}...': {e}")
                    try:
                        self._init_engine()
                    except Exception:
                        pass

            except queue.Empty:
                continue
            except Exception as e:
                self.logger.error(f"Speech worker error: {e}")
                time.sleep(1)

    def speak(self, text, volume=None):
        if not self._engine:
            if not self._init_engine():
                self.logger.warning("Speech synthesis unavailable")
                return

        self._speak_queue.put(text)

    def stop(self):
        self._stop_event.set()
        self._speak_queue.put(None)

        if hasattr(self, '_worker_thread') and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2)

        if self._engine:
            try:
                self._engine.stop()
            except Exception:
                pass
            self._engine = None

        self.logger.info("Speech service stopped")
