"""Источники данных ЕГРЮЛ. Выбор — переменной EGRUL_PROVIDER, при сбое — откат на демо-данные."""

import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.audit import audit
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


class CaptchaRequired(EgrulError):
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


class CircuitBreaker:
    """Размыкатель для внешнего сервиса: после сбоя (капча, 403/429, таймаут) не ходим туда какое-то время.

    egrul.nalog.ru при частых запросах просит капчу и временно блокирует IP. Без размыкателя каждая
    закупка пакета ждала бы полный таймаут; с ним пакет сразу уходит на кэш и демо-данные.
    Пауза растёт экспоненциально: 60 с, 120 с, 240 с … до 15 мин; успешный ответ сбрасывает счётчик.
    """

    def __init__(self, base: float = 60.0, cap: float = 900.0) -> None:
        self.base, self.cap = base, cap
        self.failures = 0
        self.open_until = 0.0
        self.reason = ""
        self._lock = threading.Lock()

    def check(self) -> None:
        with self._lock:
            left = self.open_until - time.monotonic()
            if left > 0:
                raise EgrulError(f"Сервис ФНС временно не опрашивается ({self.reason}), повтор через {int(left) + 1} с")

    def success(self) -> None:
        with self._lock:
            self.failures, self.open_until, self.reason = 0, 0.0, ""

    def failure(self, reason: str) -> None:
        with self._lock:
            pause = min(self.cap, self.base * 2 ** self.failures)
            self.failures += 1
            self.open_until = time.monotonic() + pause
            self.reason = reason
        log.warning("ФНС: %s — пауза %d с", reason, pause)

    def state(self) -> dict:
        left = max(0.0, self.open_until - time.monotonic())
        return {"open": left > 0, "retry_in_s": int(left), "failures": self.failures, "reason": self.reason or None}


class FnsProvider:
    """Открытые сервисы ФНС без ключа.

    egrul.nalog.ru — наименование, ОГРН, дата регистрации, регион, факт прекращения деятельности;
    rmsp.nalog.ru  — реестр МСП: категория и основной ОКВЭД.
    Полный список ОКВЭД ЕГРЮЛ отдаёт только в PDF-выписке, поэтому для не-МСП ОКВЭД может отсутствовать.
    """

    name = "fns"
    headers = {"User-Agent": "Mozilla/5.0 (TenderFilter)", "X-Requested-With": "XMLHttpRequest"}
    breaker = CircuitBreaker()

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout

    def fetch(self, inn: str) -> CompanyCard:
        self.breaker.check()
        # Общий бюджет на поиск: ФНС отдаёт результат опросом, и без бюджета одна компания
        # могла бы занять десятки секунд — а вся оценка обязана уложиться в 10 с.
        self.deadline = time.monotonic() + self.timeout
        try:
            with httpx.Client(timeout=self.timeout, headers=self.headers) as client:
                row = self._egrul(client, inn)
                msp = self._msp(client, inn)
        except CompanyNotFound:
            self.breaker.success()  # сервис ответил — просто нет такой организации
            raise
        except CaptchaRequired as exc:
            self.breaker.failure("капча")
            raise EgrulError(str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            self.breaker.failure(f"HTTP {exc.response.status_code}")
            raise EgrulError(f"Сервис ФНС ответил ошибкой {exc.response.status_code}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            self.breaker.failure(exc.__class__.__name__)
            raise EgrulError(f"Сервис ФНС недоступен: {exc.__class__.__name__}") from exc
        self.breaker.success()
        return _enrich(self.map(inn, row, msp))

    def _left(self) -> float:
        return self.deadline - time.monotonic()

    def _egrul(self, client: httpx.Client, inn: str) -> dict:
        r = client.post("https://egrul.nalog.ru/", data={"query": inn, "vyp3CaptchaToken": "", "page": "",
                                                          "region": "", "PreventChromeAutocomplete": ""},
                        timeout=max(0.5, self._left()))
        r.raise_for_status()
        body = r.json()
        if body.get("captchaRequired"):
            raise CaptchaRequired("Сервис ФНС запросил капчу — повторите позже или подключите DaData")
        token = body.get("t")
        if not token:
            raise EgrulError("Сервис ФНС не вернул результат поиска")
        for attempt in range(6):
            if self._left() < 0.3:
                break
            res = client.get(f"https://egrul.nalog.ru/search-result/{token}",
                             params={"r": int(time.time() * 1000)}, timeout=max(0.3, self._left()))
            res.raise_for_status()
            data = res.json()
            if data.get("status") == "wait":
                time.sleep(min(0.4 * (attempt + 1), max(0.0, self._left() - 0.3)))
                continue
            rows = [row for row in data.get("rows") or [] if row.get("i") == inn]
            if not rows:
                raise CompanyNotFound(f"Организация с ИНН {inn} не найдена в ЕГРЮЛ")
            return rows[0]
        raise EgrulError("Сервис ФНС не успел ответить")

    def _msp(self, client: httpx.Client, inn: str) -> dict | None:
        if self._left() < 0.5:
            return None  # бюджет исчерпан — статус МСП неизвестен, оценка не ждёт
        try:
            r = client.post("https://rmsp.nalog.ru/search-proc.json",
                            data={"mode": "quick", "query": inn, "page": "1", "pageSize": "10"},
                            timeout=max(0.5, self._left()))
            r.raise_for_status()
            rows = [row for row in r.json().get("data") or [] if row.get("inn") == inn]
            return rows[0] if rows else {}
        except (httpx.HTTPError, ValueError):
            return None  # реестр МСП недоступен — статус МСП неизвестен

    @staticmethod
    def map(inn: str, row: dict, msp: dict | None) -> CompanyCard:
        def date(v: str | None):
            if not v:
                return None
            try:
                return datetime.strptime(v[:10], "%d.%m.%Y").replace(tzinfo=timezone.utc)
            except ValueError:
                return None

        okveds = []
        if msp and msp.get("okved1"):
            okveds.append(OkvedEntry(code=msp["okved1"], name=msp.get("okved1name"), main=True))
        category = {1: "micro", 2: "small", 3: "medium"}.get(int(msp.get("category") or 0)) if msp else None
        return CompanyCard(
            inn=inn,
            ogrn=row.get("o"),
            name=row.get("c") or row.get("n") or inn,
            status="LIQUIDATED" if row.get("e") else "ACTIVE",
            registration_date=date(row.get("r")),
            address=row.get("rn"),
            region_name=row.get("rn"),
            okveds=okveds,
            msp_category=category,
            # Нет в реестре МСП → не МСП; реестр недоступен → неизвестно.
            is_msp=None if msp is None else bool(category),
            source="fns",
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
    if s.egrul_public_fns:
        chain.append(FnsProvider(s.egrul_timeout_seconds))
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
    started = time.perf_counter()
    tried: list[str] = []
    for provider in _providers():
        tried.append(provider.name)
        try:
            card = provider.fetch(inn)
            break
        except EgrulError as exc:
            last_error = exc
            log.info("ЕГРЮЛ %s: %s", provider.name, exc)
    else:
        elapsed = (time.perf_counter() - started) * 1000
        audit("egrul_lookup", f"ИНН {inn}: {last_error}", level="warning", duration_ms=elapsed, inn=inn, tried=tried)
        if cached:
            return CompanyCard.model_validate(cached.data)
        raise last_error or CompanyNotFound(inn)
    audit("egrul_lookup", f"ИНН {inn}: {card.name} ({card.source})", duration_ms=(time.perf_counter() - started) * 1000,
          inn=inn, source=card.source, tried=tried)

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
