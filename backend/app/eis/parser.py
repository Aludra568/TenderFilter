"""Разбор выгрузок ЕИС (XML 44-ФЗ / 223-ФЗ, JSON) в каноническую модель закупки."""

import json
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import yaml
from lxml import etree

from app.domain import PROCEDURE_NAMES, CanonicalTender, FieldSource, TenderItem
from app.reference.regions import detect_region

MSK = timezone(timedelta(hours=3))
_MAP_PATH = Path(__file__).with_name("field_map.yaml")

_SMP_RE = re.compile(r"малого предпринимательства|\bсмп\b|социально ориентированн|\bсонко\b", re.I)
_NATIONAL_RE = re.compile(
    r"национальн\w* режим|запрет\w*[^.]{0,80}иностран|ограничени\w*[^.]{0,80}иностран|\b1875\b|"
    r"постановлени\w*[^.]{0,40}№\s*(616|617|878|102)\b",
    re.I,
)


class ParseError(ValueError):
    """Файл не удалось разобрать: битый XML, не та схема, нет ключевых полей."""


@lru_cache
def field_map() -> dict:
    return yaml.safe_load(_MAP_PATH.read_text(encoding="utf-8"))


def _local(tag) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _xml_parser() -> etree.XMLParser:
    # Защита от XXE и «бомб»: без сущностей, без сети, без огромных деревьев.
    return etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, remove_comments=True)


def _children_by_name(el, name: str):
    return [c for c in el if _local(c.tag) == name]


def _descendants_by_name(el, name: str):
    return [d for d in el.iter() if d is not el and _local(d.tag) == name]


def find_path(el, path: str):
    """Первый элемент по цепочке локальных имён; каждый шаг — сначала прямые дети, потом потомки."""
    current = [el]
    for step in path.split("/"):
        nxt = []
        for node in current:
            hits = _children_by_name(node, step) or _descendants_by_name(node, step)
            nxt.extend(hits)
        if not nxt:
            return None
        current = nxt
    return current[0]


def find_all_path(el, path: str):
    steps = path.split("/")
    current = _descendants_by_name(el, steps[0])
    for step in steps[1:]:
        current = [h for node in current for h in (_children_by_name(node, step) or _descendants_by_name(node, step))]
    return current


def element_path(el) -> str:
    parts = []
    node = el
    while node is not None:
        parts.append(_local(node.tag))
        node = node.getparent()
    return "/".join(reversed(parts))


def _text(el) -> str | None:
    if el is None:
        return None
    text = "".join(el.itertext()).strip()
    return text or None


def parse_number(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = value.replace(" ", "").replace(" ", "").replace(",", ".")
    m = re.search(r"-?\d+(\.\d+)?", cleaned)
    return float(m.group()) if m else None


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    v = value.strip()
    for candidate in (v, v.replace("Z", "+00:00")):
        try:
            dt = datetime.fromisoformat(candidate)
            return dt if dt.tzinfo else dt.replace(tzinfo=MSK)
        except ValueError:
            pass
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}):(\d{2}))?", v)
    if m:
        d, mo, y, hh, mm = m.groups()
        return datetime(int(y), int(mo), int(d), int(hh or 0), int(mm or 0), tzinfo=MSK)
    return None


def parse_term_days(text: str | None) -> int | None:
    """«в течение 30 календарных дней» → 30; рабочие дни переводим в календарные (×1,4)."""
    if not text:
        return None
    t = text.lower()
    m = re.search(r"(\d{1,3})\s*\(?[а-я\s]*\)?\s*(календарн|рабоч)?\w*\s*(дн|день|дня)", t)
    if not m:
        return None
    days = int(m.group(1))
    if m.group(2) and m.group(2).startswith("рабоч"):
        days = round(days * 1.4)
    return days


def detect_procedure(root_name: str, code: str | None, name: str | None) -> str:
    text = f"{name or ''}".lower()
    if "аукцион" in text:
        return "e_auction"
    if "конкурс" in text:
        return "open_contest"
    if "котиров" in text:
        return "quotation_request"
    if "предложени" in text:
        return "proposal_request"
    if "единствен" in text:
        return "single_supplier"
    probe = f"{root_name} {code or ''}".upper()
    for marker, kind in (("EZK", "quotation_request"), ("ZK", "quotation_request"), ("EZP", "proposal_request"),
                         ("ZP", "proposal_request"), ("EOK", "open_contest"), ("OK", "open_contest"),
                         ("EF", "e_auction"), ("EA", "e_auction"), ("AE", "e_auction"), ("EP", "single_supplier")):
        if marker in probe:
            return kind
    return "other"


def _detect_law(root) -> str:
    name = _local(root.tag).lower()
    ns = (root.tag.split("}")[0] if "}" in root.tag else "").lower()
    if name.startswith("purchasenotice") or "223" in ns or find_path(root, "registrationNumber") is not None:
        return "223-FZ"
    return "44-FZ"


def _json_to_xml(data, tag: str = "root"):
    el = etree.Element(re.sub(r"[^A-Za-z0-9_]", "_", tag) or "item")
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, list):
                for item in v:
                    el.append(_json_to_xml(item, k))
            else:
                el.append(_json_to_xml(v, k))
    elif data is not None:
        el.text = str(data)
    return el


def parse_bytes(content: bytes, filename: str = "") -> CanonicalTender:
    """Определяет формат по содержимому и возвращает каноническую закупку."""
    head = content.lstrip()[:1]
    if head in (b"{", b"["):
        return parse_json(content)
    return parse_xml(content)


def parse_json(content: bytes) -> CanonicalTender:
    try:
        data = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ParseError(f"Некорректный JSON: {exc}") from exc
    if isinstance(data, list):
        if not data:
            raise ParseError("Пустой JSON-массив")
        data = data[0]
    # Уже каноническая модель (наш экспорт или API)?
    if isinstance(data, dict) and {"purchase_number", "law", "subject"} <= set(data):
        tender = CanonicalTender.model_validate(data)
        return _post_process(tender, extracted_by="json")
    root = _json_to_xml(data, "root")
    return _parse_tree(root, extracted_by="json")


def parse_xml(content: bytes) -> CanonicalTender:
    try:
        root = etree.fromstring(content, parser=_xml_parser())
    except etree.XMLSyntaxError as exc:
        raise ParseError(f"Некорректный XML: {exc}") from exc
    # Обёртки export/body/item — спускаемся к первому «содержательному» узлу.
    return _parse_tree(root, extracted_by="xml")


def _parse_tree(root, extracted_by: str) -> CanonicalTender:
    law = _detect_law(root)
    spec = field_map()[law]
    sources: dict[str, FieldSource] = {}
    values: dict[str, str | None] = {}

    for field, paths in spec["fields"].items():
        for path in paths:
            el = find_path(root, path)
            text = _text(el)
            if text:
                values[field] = text
                sources[field] = FieldSource(path=element_path(el), raw=text[:300], extracted_by=extracted_by)
                break

    def collect(paths: list[str]) -> list[str]:
        out: list[str] = []
        for path in paths:
            for el in find_all_path(root, path):
                t = _text(el)
                if t and t not in out:
                    out.append(t)
        return out

    okpd2 = [c for c in collect(spec["lists"].get("okpd2", [])) if re.match(r"^\d{2}(\.\d+)*$", c)]
    ktru = collect(spec["lists"].get("ktru", []))
    requirements = collect(spec["lists"].get("requirements", []))

    items: list[TenderItem] = []
    item_spec = spec.get("items", {})
    containers = [el for name in item_spec.get("container", []) for el in _descendants_by_name(root, name)]
    for container in containers[:300]:
        def first(paths: list[str], container=container):
            for p in paths:
                t = _text(find_path(container, p))
                if t:
                    return t
            return None

        name = first(item_spec.get("name", []))
        if not name:
            continue
        items.append(TenderItem(
            name=name[:300],
            okpd2=first(item_spec.get("okpd2", [])),
            ktru=first(item_spec.get("ktru", [])),
            quantity=parse_number(first(item_spec.get("quantity", []))),
            price=parse_number(first(item_spec.get("price", []))),
        ))
    for item in items:
        if item.okpd2 and item.okpd2 not in okpd2 and re.match(r"^\d{2}(\.\d+)*$", item.okpd2):
            okpd2.append(item.okpd2)

    purchase_number = values.get("purchase_number")
    subject = values.get("subject") or (items[0].name if items else None)
    if not purchase_number:
        raise ParseError("Не найден номер закупки — файл не похож на извещение ЕИС")
    if not subject:
        raise ParseError("Не найден предмет закупки")

    flags = spec.get("flags", {})
    smp_flag = None
    for path in flags.get("smp_only", []):
        el = find_path(root, path)
        t = _text(el)
        if t is not None:
            smp_flag = t.strip().lower() in ("true", "1", "да")
            sources["smp_only"] = FieldSource(path=element_path(el), raw=t, extracted_by=extracted_by)
            break
    codes = collect(spec["lists"].get("requirement_codes", []))
    smp_codes = set(flags.get("smp_codes", []))
    req_text = " | ".join(requirements)
    if smp_flag is None and (codes or requirements):
        smp_flag = bool(smp_codes & set(codes)) or bool(_SMP_RE.search(req_text)) or bool(re.search(r"ч\.\s*3\s*ст\.\s*30", req_text))
        if smp_flag:
            hit = next((r for r in requirements if re.search(r"ч\.\s*3\s*ст\.\s*30|малого предпринимательства|СМП", r, re.I)), req_text)
            sources["smp_only"] = FieldSource(path="requirementsInfo / preferensesInfo", raw=hit[:300], extracted_by=extracted_by)
    national = None
    for path in flags.get("national_regime", []):
        els = _descendants_by_name(root, path)
        if els:
            national = bool(national) or any((_text(e) or "").lower() == "true" for e in els)
            if national and "national_regime" not in sources:
                sources["national_regime"] = FieldSource(path=element_path(els[0]), raw=f"{path} = true", extracted_by=extracted_by)
    if requirements and _NATIONAL_RE.search(req_text):
        national = True
        sources.setdefault("national_regime", FieldSource(path="requirements", raw=req_text[:300], extracted_by=extracted_by))

    tender = CanonicalTender(
        purchase_number=purchase_number.strip(),
        law=law,
        procedure_type=detect_procedure(_local(root.tag), values.get("placing_way_code"), values.get("placing_way_name")),
        procedure_name=values.get("placing_way_name"),
        subject=subject.strip()[:1000],
        nmck=parse_number(values.get("nmck")),
        currency=(values.get("currency") or "RUB")[:8],
        customer_inn=(values.get("customer_inn") or "").strip() or None,
        customer_name=values.get("customer_name"),
        delivery_place=values.get("delivery_place"),
        published_at=parse_datetime(values.get("published_at")),
        submission_deadline=parse_datetime(values.get("deadline")),
        contract_term_days=parse_term_days(values.get("delivery_term")),
        app_guarantee_amount=parse_number(values.get("app_guarantee_amount")),
        contract_guarantee_percent=parse_number(values.get("contract_guarantee_part")),
        contract_guarantee_amount=parse_number(values.get("contract_guarantee_amount")),
        advance_percent=parse_number(values.get("advance_percent")),
        smp_only=smp_flag,
        national_regime=national,
        requirements=requirements[:30],
        okpd2=okpd2[:50],
        ktru=ktru[:50],
        items=items,
        url=values.get("url"),
        sources=sources,
    )
    part = parse_number(values.get("app_guarantee_part"))
    if tender.app_guarantee_amount is None and part is not None and tender.nmck:
        tender.app_guarantee_amount = round(tender.nmck * part / 100, 2)
    end = parse_datetime(values.get("contract_end_date"))
    start = tender.submission_deadline or tender.published_at
    if tender.contract_term_days is None and end and start:
        # Контракт заключают примерно через 10 дней после окончания подачи заявок.
        tender.contract_term_days = max(1, (end - start).days - 10)
        sources["delivery_term"] = sources.get("contract_end_date") or FieldSource(path="contract_end_date", raw=str(end.date()))
    return _post_process(tender, extracted_by=extracted_by)


def _post_process(tender: CanonicalTender, extracted_by: str) -> CanonicalTender:
    if tender.contract_guarantee_amount is None and tender.contract_guarantee_percent is not None and tender.nmck:
        tender.contract_guarantee_amount = round(tender.nmck * tender.contract_guarantee_percent / 100, 2)
    if tender.contract_guarantee_percent is None and tender.contract_guarantee_amount and tender.nmck:
        tender.contract_guarantee_percent = round(tender.contract_guarantee_amount / tender.nmck * 100, 2)
    if not tender.delivery_region_code:
        region = detect_region(tender.delivery_place) or detect_region(tender.customer_name)
        if region:
            tender.delivery_region_code = region.code
            tender.delivery_region_name = region.name
    if not tender.procedure_name:
        tender.procedure_name = PROCEDURE_NAMES.get(tender.procedure_type)
    warnings = []
    if tender.nmck is None:
        warnings.append("Не найдена НМЦК")
    if tender.submission_deadline is None:
        warnings.append("Не найден срок окончания подачи заявок")
    if not tender.okpd2:
        warnings.append("Не найдены коды ОКПД 2")
    if not tender.delivery_region_code:
        warnings.append("Не удалось определить регион поставки")
    tender.parse_warnings = warnings
    return tender
