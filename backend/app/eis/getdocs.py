"""Загрузка извещения 44-ФЗ из ЕИС по реестровому номеру через официальный сервис getDocsIP.

С 01.01.2025 открытый FTP ЕИС закрыт; данные выдаются через SOAP-сервис по токену физлица
(получается в личном кабинете ЕИС через Госуслуги). Порядок обмена:
  1) POST SOAP getDocsByReestrNumberRequest → в ответе ссылки dataInfo/archiveUrl;
  2) GET архива — токен нужно передать ещё и HTTP-заголовком individualPerson_token
     (в инструкции ЕИС этого нет, выяснено сообществом: habr.com/articles/869934);
  3) в ZIP-архиве — XML извещения той же структуры, что разбирает app.eis.parser.
Схема строгая: порядок элементов менять нельзя, иначе сервис отвечает ошибкой валидации.
Без токена сервис не проверялся — модуль покрыт тестами на сборку запроса и разбор ответа.
"""

import io
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

import httpx
from lxml import etree

from app.config import get_settings

NS_WS = "http://zakupki.gov.ru/fz44/get-docs-ip/ws"
MSK = timezone(timedelta(hours=3))


class EisApiError(Exception):
    pass


def build_request(reestr_number: str, token: str, subsystem: str = "PRIZ",
                  request_id: str | None = None, now: datetime | None = None) -> str:
    created = (now or datetime.now(MSK)).astimezone(MSK).isoformat(timespec="seconds")
    return (
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        f'xmlns:ws="{NS_WS}">'
        f"<soapenv:Header><individualPerson_token>{escape(token)}</individualPerson_token></soapenv:Header>"
        "<soapenv:Body><ws:getDocsByReestrNumberRequest>"
        f"<index><id>{request_id or uuid.uuid4()}</id><createDateTime>{created}</createDateTime><mode>PROD</mode></index>"
        f"<selectionParams><subsystemType>{escape(subsystem)}</subsystemType>"
        f"<reestrNumber>{escape(reestr_number)}</reestrNumber></selectionParams>"
        "</ws:getDocsByReestrNumberRequest></soapenv:Body></soapenv:Envelope>"
    )


def parse_response(content: bytes) -> list[str]:
    """Ссылки на архивы из ответа; ошибка сервиса (SOAP Fault, errorInfo) — исключение с её текстом."""
    try:
        root = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as exc:
        raise EisApiError("ЕИС вернула не XML") from exc
    texts = lambda name: [(el.text or "").strip() for el in root.iter() if etree.QName(el).localname == name]
    fault = texts("faultstring") or texts("errorInfo") or [m for m in texts("message") if m]
    urls = [u for u in texts("archiveUrl") if u]
    if not urls:
        raise EisApiError(f"ЕИС: {fault[0]}" if fault else "ЕИС не нашла документов по этому номеру")
    return urls


def pick_notice(archive: bytes) -> tuple[str, bytes]:
    """Из ZIP — XML извещения (epNotification*/fcsNotification*); иначе первый XML."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(archive))
    except zipfile.BadZipFile as exc:
        raise EisApiError("Архив ЕИС повреждён или пуст") from exc
    xmls = [n for n in zf.namelist() if n.lower().endswith(".xml") and zf.getinfo(n).file_size < 50 * 2**20]
    if not xmls:
        raise EisApiError("В архиве ЕИС нет XML")
    best = next((n for n in xmls if "notification" in n.lower()), xmls[0])
    return best.rsplit("/", 1)[-1], zf.read(best)


def fetch_notice(reestr_number: str, subsystem: str = "PRIZ") -> tuple[str, bytes]:
    s = get_settings()
    if not s.eis_token:
        raise EisApiError("Не задан EIS_TOKEN — получите токен в личном кабинете ЕИС и добавьте его в .env")
    body = build_request(reestr_number, s.eis_token, subsystem)
    try:
        with httpx.Client(timeout=httpx.Timeout(120, connect=30)) as client:
            r = client.post(s.eis_getdocs_url, content=body.encode("utf-8"),
                            headers={"Content-Type": "text/xml; charset=utf-8"})
            if r.status_code >= 400 and not r.content:
                raise EisApiError(f"ЕИС ответила {r.status_code}")
            urls = parse_response(r.content)
            arc = client.get(urls[0], headers={"individualPerson_token": s.eis_token})
            arc.raise_for_status()
    except httpx.HTTPError as exc:
        raise EisApiError(f"Сервис ЕИС недоступен: {exc.__class__.__name__}") from exc
    return pick_notice(arc.content)
