# -*- coding: utf-8 -*-
from services.speech import Speech
from services.ai_client import AIClient
class AIAssistant:
    def __init__(self, config, speech: Speech, ai_client: AIClient):
        self.speech = speech
        self.ai = ai_client

    def interact(self, question):
        if not question or not self.ai:
            return

        try:
            answer = self.ai.ask(question)
            if answer:
                if self.speech:
                    self.speech.speak(answer)
            else:
                if self.speech:
                    self.speech.speak("没有收到回复，请稍后再试")
        except Exception as e:
            if self.speech:
                self.speech.speak("抱歉，服务出现问题，请稍后再试")