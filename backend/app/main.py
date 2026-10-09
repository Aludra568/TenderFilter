import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.config import get_settings
from app.db import SessionLocal, init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if settings.seed_demo_data:
        from app.seed.loader import seed

        with SessionLocal() as db:
            seed(db)
    _warm_up()
    yield


def _warm_up() -> None:
    """Загружаем словари pymorphy3 и компилируем грамматики yargy при старте, а не на первом запросе."""
    from app.domain import Preferences
    from app.nlp.criteria import parse_criteria
    from app.reference.textvec import embed

    parse_criteria("Поставляем ноутбуки в Новосибирской области до 5 млн руб., подача не менее 3 дней",
                   Preferences(), use_llm=False)
    embed("поставка ноутбуков")


app = FastAPI(
    title="Тендерный фильтр — скоринг закупок",
    description="ИИ-скоринг закупок 44-ФЗ / 223-ФЗ по данным ЕИС и ЕГРЮЛ. "
                "LLM переводит критерии из текста в правила, детерминированный движок считает оценку.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
