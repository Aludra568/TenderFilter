"""Журнал событий в PostgreSQL. Пишется в отдельной сессии, чтобы ошибка записи лога не ломала основной запрос."""

import logging

from app.db import SessionLocal
from app.models import AuditLog

log = logging.getLogger(__name__)

EVENT_NAMES = {
    "tender_uploaded": "Загрузка извещения",
    "quick_score": "Быстрая оценка",
    "egrul_lookup": "Запрос ЕГРЮЛ",
    "criteria_parsed": "Разбор критериев",
    "profile_saved": "Сохранение профиля",
    "batch_created": "Пакет поставлен в очередь",
    "batch_done": "Пакет обработан",
    "feedback": "Отметка пользователя",
    "llm_review": "Проверка ИИ",
    "documents": "Разбор документов",
    "customer_check": "Проверка закупки заказчиком",
    "bid": "Участие в закупке",
    "error": "Ошибка",
}


def audit(event: str, message: str, *, level: str = "info", duration_ms: float | None = None, **detail) -> None:
    try:
        with SessionLocal() as db:
            db.add(AuditLog(event=event, level=level, message=message[:2000],
                            duration_ms=round(duration_ms, 2) if duration_ms is not None else None,
                            detail={k: v for k, v in detail.items() if v is not None}))
            db.commit()
    except Exception:  # журнал не должен ронять бизнес-логику
        log.exception("Не удалось записать событие %s", event)
