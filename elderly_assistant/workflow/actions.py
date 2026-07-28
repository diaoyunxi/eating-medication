# -*- coding: utf-8 -*-
"""用药确认/暂缓/AI问答/拍照上传等工作流动作（纯逻辑，硬件以参数注入）。"""
import logging

logger = logging.getLogger("ElderlyAssistant")


def _capture_and_upload(config, http_client, logger):
    """拍照并上传服药照片（HuskyLens；无摄像头时静默降级）。"""
    try:
        from core.camera import capture_image
        path = capture_image(config)
        if not path:
            return
        http_client.upload_image(path)
    except Exception as e:
        logger.warning(f"拍照上传失败: {e}")


def _ask_ai_and_speak(reminder_state, http_client, speech, logger, config):
    """向 AI 询问当前药品的服用注意事项并语音播报（缺失环境静默降级，异步线程调用）。"""
    try:
        drug = reminder_state.drug_name or "当前药物"
        question = f"请简要说明 {drug} 的服用注意事项，用通俗易懂的话，不超过3句。"
        answer = http_client.ask_ai(question) if http_client else "抱歉，网络不可用"
        logger.info(f"AI 问答: {question} -> {answer}")
        if speech is not None:
            try:
                speech.speak(answer)
            except Exception:
                pass
    except Exception as e:
        logger.error(f"AI 问答异常: {e}")


def handle_confirm(reminder_state, buzzer, display, http_client, logger, speech=None, config=None):
    """按钮 A：确认服药。"""
    try:
        drug = reminder_state.drug_name
        dosage = reminder_state.dosage
        logger.info(f"用户确认服药: {drug} {dosage}")
        buzzer.stop()
        # 上报服药确认（可选，失败不影响），回传精确计划项供服务端落库
        if http_client:
            try:
                items = getattr(reminder_state, "items", [])
                http_client.confirm_medication(drug, dosage, items=items)
            except Exception as e:
                logger.error(f"上报服药确认失败: {e}")
        reminder_state.confirm()
        display.clear_reminder()
        # 播放成功提示音
        try:
            buzzer.play_success()
        except Exception:
            pass
        # 语音播报确认（TTS，缺失时静默降级）
        if speech:
            try:
                speech.speak(f"已记录，{drug}")
            except Exception:
                pass
        # 拍照上传服药照片（HuskyLens，无摄像头时静默降级，异步不阻塞主循环）
        if config is not None and http_client is not None:
            try:
                import threading as _th
                _th.Thread(
                    target=_capture_and_upload, args=(config, http_client, logger), daemon=True
                ).start()
            except Exception:
                pass
    except Exception as e:
        logger.error(f"处理确认服药异常: {e}")


def handle_snooze(reminder_state, buzzer, display, snooze_minutes, logger):
    """按钮 B：暂不提醒（5分钟后再提醒）。"""
    try:
        logger.info(f"用户暂缓提醒，{snooze_minutes} 分钟后再提醒")
        buzzer.stop()
        reminder_state.snooze(snooze_minutes)
        # 返回主界面，等待 snooze_until 到期再响铃
        display.clear_reminder()
    except Exception as e:
        logger.error(f"处理暂缓提醒异常: {e}")
