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


def find_plan_by_product_code(schedules, code):
    """在用药计划中按药品编号（product_code）查找匹配项。

    比对时仅忽略首尾空白，保留药品编号的原始大小写语义，避免大小写不同的
    真实药品被误判为同一计划（误服风险）。

    :param schedules: 用药计划列表（每项为 dict）
    :param code: 扫码/手输得到的药品编号
    :return: 匹配到的计划 dict；无匹配返回 None
    """
    if not code:
        return None
    target = str(code).strip()
    if not target:
        return None
    for item in schedules or []:
        if not isinstance(item, dict):
            continue
        product_code = str(item.get("product_code") or "").strip()
        if product_code and product_code == target:
            return item
    return None


def handle_scan_medication(scanner, poller, speech, logger, timeout=None):
    """扫描药品条码并语音播报药品名称与用量。

    流程：扫码取得药品编号 -> 在当前用药计划（有网走网络、断网走本地缓存，
    均由 MedicationPoller 统一维护）中按 product_code 匹配 -> TTS 播报
    「药品名 + 用量 + 服药时间」；未识别或未匹配时播报对应提示。

    scanner / poller / speech 均由调用方注入，本函数不直接依赖硬件，便于单测。

    :param scanner: 满足 ports.BarcodeScannerPort 的扫码器，可为 None（降级提示）
    :param poller: 提供 schedules 属性的用药计划持有者
    :param speech: TTS 服务，可为 None（仅记录日志）
    :param timeout: 单次扫码超时秒数，None 表示使用扫码器默认值
    :return: 匹配到的计划 dict；未识别/未匹配返回 None
    """

    def _speak(text):
        logger.info(f"扫码播报: {text}")
        if speech is not None:
            try:
                speech.speak(text)
            except Exception as e:
                logger.warning(f"语音播报失败: {e}")

    try:
        if scanner is None:
            _speak("扫码功能不可用，请检查摄像头")
            return None

        _speak("请把药盒上的条码对准摄像头")
        try:
            code = scanner.scan(timeout=timeout)
        except Exception as e:
            logger.error(f"扫码失败: {e}")
            _speak("扫码出错了，请稍后再试")
            return None

        if not code:
            _speak("没有识别到药品条码，请再试一次")
            return None
        logger.info(f"扫码识别到药品编号: {code}")

        plan = find_plan_by_product_code(getattr(poller, "schedules", None), code)
        if plan is None:
            _speak("没有找到这个药品的用药信息，请让家人在手机上添加")
            return None

        drug_name = plan.get("drug_name") or "该药品"
        dosage = plan.get("dosage") or ""
        scheduled_time = plan.get("time") or ""
        text = f"{drug_name}，每次{dosage}" if dosage else f"{drug_name}"
        if scheduled_time:
            text += f"，服药时间{scheduled_time}"
        _speak(text)
        return plan
    except Exception as e:
        logger.error(f"扫码查询药品异常: {e}")
        return None


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
