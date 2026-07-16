# -*- coding: utf-8 -*-
from app.schemas.user import UserOut, UserUpdate
from app.schemas.auth import RegisterReq, LoginReq, TokenResp
from app.schemas.medication import MedicationPlanCreate, MedicationPlanOut, TakeMedicationRequest, MedicationRecordOut
from app.schemas.ai import AIQuestion, AIAnswer
from app.schemas.vision import ImageRecognitionResp
from app.schemas.chat import ChatMessageCreate, ChatMessageOut

__all__ = [
    "UserOut",
    "UserUpdate",
    "RegisterReq",
    "LoginReq",
    "TokenResp",
    "MedicationPlanCreate",
    "MedicationPlanOut",
    "TakeMedicationRequest",
    "MedicationRecordOut",
    "AIQuestion",
    "AIAnswer",
    "ImageRecognitionResp",
    "ChatMessageCreate",
    "ChatMessageOut",
]
