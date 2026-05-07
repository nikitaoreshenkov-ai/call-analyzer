from __future__ import annotations

from models_v1 import CallStatus


REVIEW_LABEL = "Требует экспертной верификации"

CALL_STATUS_LABELS_UI = {
    CallStatus.IN_FUNNEL.value: "В воронке",
    CallStatus.OUT_OF_FUNNEL_INTERRUPTED.value: "Вне воронки: прерван до диалога",
    CallStatus.OUT_OF_FUNNEL_INTERRUPTED_AFTER_DIALOG.value: "Вне воронки: обрыв после предметного диалога",
    CallStatus.OUT_OF_FUNNEL_CALLBACK_LATER_NO_DIALOG.value: "Вне воронки: перезвонить позже без диалога",
    CallStatus.OUT_OF_FUNNEL_NON_TARGET.value: "Вне воронки: нецелевой звонок",
}

CALL_STATUS_LABELS_REPORT = {
    CallStatus.IN_FUNNEL.value: "в воронке",
    CallStatus.OUT_OF_FUNNEL_INTERRUPTED.value: "прерван до предметного диалога",
    CallStatus.OUT_OF_FUNNEL_INTERRUPTED_AFTER_DIALOG.value: "обрыв после предметного диалога",
    CallStatus.OUT_OF_FUNNEL_CALLBACK_LATER_NO_DIALOG.value: "перезвонить позже без предметного диалога",
    CallStatus.OUT_OF_FUNNEL_NON_TARGET.value: "нецелевой звонок",
}


def call_status_label(status: str | CallStatus, style: str = "ui") -> str:
    key = status.value if isinstance(status, CallStatus) else str(status)
    labels = CALL_STATUS_LABELS_REPORT if style == "report" else CALL_STATUS_LABELS_UI
    return labels.get(key, key)
