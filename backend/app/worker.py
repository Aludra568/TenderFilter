"""Очередь задач. С Redis — Celery-воркер в отдельном контейнере; без Redis — фоновые потоки в процессе API."""

import io
import logging
import threading
import time
import zipfile
from datetime import datetime, timezone

from celery import Celery

from app.audit import audit
from app.config import get_settings
from app.db import SessionLocal
from app.eis.parser import ParseError
from app.models import Batch, BatchFile, Profile
from app.services import current_version, ingest, profile_company, score_row

log = logging.getLogger(__name__)
settings = get_settings()

celery_app = Celery("tender_filter", broker=settings.redis_url or "memory://", backend=None)
celery_app.conf.update(task_acks_late=True, worker_prefetch_multiplier=1, task_serializer="json")

ALLOWED = (".xml", ".json")


def unpack(filename: str, content: bytes) -> list[tuple[str, bytes]]:
    """ZIP с извещениями (в том числе вложенные папки) или одиночный файл."""
    if filename.lower().endswith(".zip") or content[:2] == b"PK":
        files = []
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for info in zf.infolist():
                if info.is_dir() or not info.filename.lower().endswith(ALLOWED):
                    continue
                if info.file_size > 20 * 1024 * 1024:
                    continue
                files.append((info.filename.rsplit("/", 1)[-1], zf.read(info)))
        return files
    return [(filename, content)]


def process_batch(batch_id: int) -> None:
    started = time.perf_counter()
    db = SessionLocal()
    try:
        batch = db.get(Batch, batch_id)
        if batch is None:
            return
        batch.status = "running"
        db.commit()
        profile = db.get(Profile, batch.profile_id)
        pv = current_version(db, profile)
        company = profile_company(db, profile)
        files = db.query(BatchFile).filter(BatchFile.batch_id == batch_id, BatchFile.done.is_(False)).all()
        tender_ids = list(batch.tender_ids or [])
        errors = list(batch.errors or [])
        for f in files:
            try:
                row = ingest(db, f.filename, f.content.encode("utf-8"))
                score_row(db, row, pv, company, force=True)
                tender_ids.append(row.id)
            except ParseError as exc:
                errors.append({"file": f.filename, "error": str(exc)})
                batch.failed += 1
            except Exception as exc:  # одна битая запись не должна ронять пакет
                log.exception("Ошибка обработки %s", f.filename)
                errors.append({"file": f.filename, "error": f"Внутренняя ошибка: {exc.__class__.__name__}"})
                batch.failed += 1
            f.done = True
            batch.processed += 1
            # Новые объекты списков: SQLAlchemy не отслеживает изменения внутри JSON-поля.
            batch.tender_ids = list(tender_ids)
            batch.errors = list(errors)
            db.commit()
        batch.status = "done"
        batch.finished_at = datetime.now(timezone.utc)
        db.commit()
        audit("batch_done", f"Пакет № {batch_id}: обработано {batch.processed}, ошибок {batch.failed}",
              duration_ms=(time.perf_counter() - started) * 1000,
              batch_id=batch_id, processed=batch.processed, failed=batch.failed)
    except Exception:
        log.exception("Пакет %s упал", batch_id)
        db.rollback()
        batch = db.get(Batch, batch_id)
        if batch:
            batch.status = "failed"
            db.commit()
    finally:
        db.close()


@celery_app.task(name="process_batch")
def process_batch_task(batch_id: int) -> None:
    process_batch(batch_id)


def dispatch_batch(batch_id: int) -> str:
    if settings.redis_url:
        process_batch_task.delay(batch_id)
        return "celery"
    threading.Thread(target=process_batch, args=(batch_id,), daemon=True).start()
    return "thread"
