"""Публичная печатная форма ЕИС: XML извещения 44-ФЗ по реестровому номеру, без токена.

zakupki.gov.ru отдаёт XML-версию печатной формы извещения той же структуры, что выгрузка
(epNotificationEF2020 и др.). Сайт подписан сертификатом российского корневого центра Минцифры,
которого нет в стандартных хранилищах, поэтому TLS проверяется по приложенному официальному
сертификату (app/eis/certs) — проверка не отключается.
"""

import re
import ssl
from functools import lru_cache
from pathlib import Path

import httpx

from app.eis.getdocs import EisApiError

CERTS = Path(__file__).resolve().parent / "certs" / "bundle.pem"
VIEW_XML = "https://zakupki.gov.ru/epz/order/notice/printForm/viewXml.html"
HEADERS = {"User-Agent": "Mozilla/5.0 (TenderFilter)"}


@lru_cache(maxsize=1)
def ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if CERTS.exists():
        ctx.load_verify_locations(cafile=str(CERTS))
    return ctx


def fetch_notice(reg_number: str, timeout: float = 15.0) -> tuple[str, bytes]:
    try:
        with httpx.Client(timeout=timeout, headers=HEADERS, verify=ssl_context(), follow_redirects=True) as client:
            r = client.get(VIEW_XML, params={"regNumber": reg_number})
    except httpx.HTTPError as exc:
        raise EisApiError(f"ЕИС недоступна: {exc.__class__.__name__}") from exc
    body = r.content.lstrip()
    maintenance = re.search(r"регламентных\s+работ[\s\S]{0,200}?по\s+(\d{2}:\d{2}\s+\d{2}\.\d{2}\.\d{4})", r.text if not r.content.lstrip().startswith(b"<?xml") else "")
    if maintenance:
        raise EisApiError(f"ЕИС на регламентных работах до {maintenance.group(1)} (МСК) — загрузите извещение файлом")
    if r.status_code == 429:
        raise EisApiError("ЕИС временно ограничила частоту запросов — повторите через минуту")
    if r.status_code != 200 or not body.startswith(b"<?xml"):
        raise EisApiError("ЕИС не вернула XML извещения — проверьте номер (19 цифр, 44-ФЗ)")
    return f"{reg_number}.xml", body
