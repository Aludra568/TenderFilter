"""Источники данных ЕГРЮЛ. Выбор — переменной EGRUL_PROVIDER, при сбое — откат на демо-данные."""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain import CompanyCard, OkvedEntry
from app.egrul.inn import is_valid_inn
from app.models import Company
from app.reference.okved import OKVED_NAMES
from app.reference.regions import detect_region, region_from_inn

log = logging.getLogger(__name__)
_FIXTURES = Path(__file__).resolve().parent.parent / "seed" / "companies.json"


class EgrulError(Exception):
    pass


class InvalidInn(EgrulError):
    pass


class CompanyNotFound(EgrulError):
    pass


def _load_fixtures() -> dict[str, dict]:
    if not _FIXTURES.exists():
        return {}
    return {c["inn"]: c for c in json.loads(_FIXTURES.read_text(encoding="utf-8"))}


class MockProvider:
    name = "mock"

    def __init__(self) -> None:
        self.data = _load_fixtures()

    def fetch(self, inn: str) -> CompanyCard:
        raw = self.data.get(inn)
        if not raw:
            raise CompanyNotFound(f"ИНН {inn} нет в демо-данных")
        card = CompanyCard.model_validate({**raw, "source": "mock"})
        return _enrich(card)


class DaDataProvider:
    """https://dadata.ru/api/find-party/ — бесплатно до 10 000 запросов в сутки."""

    name = "dadata"
    url = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def fetch(self, inn: str) -> CompanyCard:
        try:
            resp = httpx.post(
                self.url,
                json={"query": inn, "branch_type": "MAIN"},
                headers={"Authorization": f"Token {self.api_key}", "Accept": "application/json"},
                timeout=8.0,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise EgrulError(f"DaData недоступна: {exc}") from exc
        suggestions = resp.json().get("suggestions") or []
        if not suggestions:
            raise CompanyNotFound(f"Организация с ИНН {inn} не найдена")
        return _enrich(self._map(inn, suggestions[0]))

    @staticmethod
    def _map(inn: str, s: dict) -> CompanyCard:
        d = s.get("data") or {}
        state = d.get("state") or {}
        reg_ms = state.get("registration_date")
        okveds: list[OkvedEntry] = []
        if d.get("okved"):
            okveds.append(OkvedEntry(code=d["okved"], main=True))
        for o in d.get("okveds") or []:
            if o.get("code") and o["code"] != d.get("okved"):
                okveds.append(OkvedEntry(code=o["code"], name=o.get("name"), main=bool(o.get("main"))))
        smb = ((d.get("documents") or {}).get("smb") or {})
        category = (smb.get("category") or "").lower() or None
        address = (d.get("address") or {})
        return CompanyCard(
            inn=inn,
            ogrn=d.get("ogrn"),
            name=(d.get("name") or {}).get("short_with_opf") or s.get("value") or inn,
            status=state.get("status") if state.get("status") in
            ("ACTIVE", "LIQUIDATING", "LIQUIDATED", "BANKRUPT", "REORGANIZING") else "UNKNOWN",
            registration_date=datetime.fromtimestamp(reg_ms / 1000, tz=timezone.utc) if reg_ms else None,
            address=address.get("value"),
            region_name=(address.get("data") or {}).get("region_with_type"),
            okveds=okveds,
            msp_category=category if category in ("micro", "small", "medium") else None,
            is_msp=bool(category) if smb else None,
            source="dadata",
        )


def _enrich(card: CompanyCard) -> CompanyCard:
    """Регион из адреса или ИНН, названия ОКВЭД из справочника."""
    if not card.region_code:
        region = detect_region(card.region_name) or detect_region(card.address) or region_from_inn(card.inn)
        if region:
            card.region_code, card.region_name = region.code, region.name
    for o in card.okveds:
        if not o.name:
            o.name = OKVED_NAMES.get(o.code) or OKVED_NAMES.get(o.code[:5])
    if card.is_msp is None and card.msp_category:
        card.is_msp = True
    return card


def _providers():
    s = get_settings()
    chain = []
    if s.egrul_provider == "dadata" and s.dadata_api_key:
        chain.append(DaDataProvider(s.dadata_api_key))
    chain.append(MockProvider())
    return chain


def get_company(db: Session, inn: str, refresh: bool = False) -> CompanyCard:
    """Карточка из кэша (24 ч) или из цепочки источников."""
    inn = (inn or "").strip()
    if not is_valid_inn(inn):
        raise InvalidInn("Некорректный ИНН: проверьте количество цифр и контрольную сумму")
    cached = db.get(Company, inn)
    ttl = timedelta(hours=get_settings().egrul_cache_hours)
    if cached and not refresh:
        fetched = cached.fetched_at if cached.fetched_at.tzinfo else cached.fetched_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - fetched < ttl:
            return CompanyCard.model_validate(cached.data)

    last_error: Exception | None = None
    for provider in _providers():
        try:
            card = provider.fetch(inn)
            break
        except EgrulError as exc:
            last_error = exc
            log.info("ЕГРЮЛ %s: %s", provider.name, exc)
    else:
        if cached:
            return CompanyCard.model_validate(cached.data)
        raise last_error or CompanyNotFound(inn)

    payload = json.loads(card.model_dump_json())
    if cached:
        cached.data, cached.source, cached.fetched_at = payload, card.source, datetime.now(timezone.utc)
    else:
        db.add(Company(inn=inn, data=payload, source=card.source, fetched_at=datetime.now(timezone.utc)))
    db.commit()
    return card


def try_get_company(db: Session, inn: str | None) -> CompanyCard | None:
    if not inn:
        return None
    try:
        return get_company(db, inn)
    except EgrulError:
        return None
