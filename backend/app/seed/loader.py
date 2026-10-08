"""Наполнение пустой базы демо-данными при первом запуске."""

import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Profile, Tender
from app.nlp.criteria import parse_criteria
from app.seed.demo import DEMO_COMPANY_INN, DEMO_CRITERIA, demo_files
from app.services import create_profile, ingest, rescore_all

log = logging.getLogger(__name__)
SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def seed(db: Session) -> None:
    if db.scalar(select(func.count()).select_from(Tender)):
        return
    log.info("Заполняю базу демо-данными")
    files = demo_files()
    for path in sorted(SAMPLES.glob("real_*.xml")):
        files.append((path.name, path.read_bytes()))
    for name, content in files:
        try:
            ingest(db, name, content)
        except Exception:
            log.exception("Не удалось загрузить демо-файл %s", name)
    if not db.scalar(select(func.count()).select_from(Profile)):
        outcome = parse_criteria(DEMO_CRITERIA, use_llm=False)
        profile = create_profile(db, "Поставщик IT, Сибирь", DEMO_COMPANY_INN, outcome.preferences, DEMO_CRITERIA)
        rescore_all(db, profile)
