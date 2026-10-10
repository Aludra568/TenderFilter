"""Корпус реальных извещений ЕИС и отчёт о полноте разбора.

    python -m app.corpus download --pages 3   # свежие извещения 44-ФЗ из поиска ЕИС → eval/corpus/*.xml
    python -m app.corpus report               # полнота ключевых полей по типам документов → eval/corpus_report.json

Скачивание вежливое: последовательно, с паузой между запросами. Сами XML в репозиторий не кладутся
(.gitignore), отчёт — кладётся: по нему видно, на каких типах извещений парсер теряет поля.
"""

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import httpx
from lxml import etree

from app.eis.getdocs import EisApiError
from app.eis.parser import ParseError, parse_bytes
from app.eis.public import HEADERS, fetch_notice, ssl_context

ROOT = Path(__file__).resolve().parents[1] / "eval"
CORPUS = ROOT / "corpus"
SEARCH = "https://zakupki.gov.ru/epz/order/extendedsearch/results.html"
# Разные запросы — чтобы в корпус попали разные способы закупки, а не только аукционы.
QUERIES = ["", "запрос котировок", "конкурс", "поставка", "оказание услуг", "выполнение работ"]
FIELDS = ["subject", "nmck", "submission_deadline", "delivery_region_code", "okpd2", "customer_inn",
          "procedure_type", "contract_guarantee_percent", "app_guarantee_amount", "smp_only"]


def search(query: str, page: int) -> list[str]:
    params = {"searchString": query, "morphology": "on", "fz44": "on", "af": "on", "ca": "on",
              "pageNumber": page, "recordsPerPage": "_50", "sortBy": "UPDATE_DATE", "sortDirection": "false"}
    with httpx.Client(timeout=30, headers=HEADERS, verify=ssl_context()) as client:
        html = client.get(SEARCH, params=params).text
    return sorted(set(re.findall(r"regNumber=(\d{19})", html)))


def download(pages: int, delay: float) -> int:
    CORPUS.mkdir(parents=True, exist_ok=True)
    numbers: list[str] = []
    for q in QUERIES:
        for page in range(1, pages + 1):
            numbers += [n for n in search(q, page) if n not in numbers]
            time.sleep(delay)
    saved = 0
    for n in numbers:
        path = CORPUS / f"{n}.xml"
        if path.exists():
            continue
        for attempt in range(3):
            try:
                _, content = fetch_notice(n)
                path.write_bytes(content)
                saved += 1
                break
            except EisApiError as exc:
                if "частоту" in str(exc) and attempt < 2:
                    time.sleep(30 * (attempt + 1))  # ЕИС ответила 429 — ждём и повторяем
                    continue
                print(f"  {n}: {exc}")
                break
        time.sleep(delay)
    print(f"Номеров найдено {len(numbers)}, скачано новых {saved}, всего в корпусе {len(list(CORPUS.glob('*.xml')))}")
    return saved


def _present(value) -> bool:
    return value not in (None, "", [], "other")


def report() -> dict:
    files = sorted(CORPUS.glob("*.xml"))
    by_type: dict[str, list[dict]] = defaultdict(list)
    errors = []
    for f in files:
        content = f.read_bytes()
        try:
            root = etree.QName(etree.fromstring(content, etree.XMLParser(resolve_entities=False, huge_tree=True))).localname
        except etree.XMLSyntaxError:
            root = "битый XML"
        try:
            t = parse_bytes(content, f.name)
        except ParseError as exc:
            errors.append({"file": f.name, "root": root, "error": str(exc)})
            continue
        data = t.model_dump()
        by_type[root].append({k: _present(data.get(k)) for k in FIELDS})
    types = {}
    for root, rows in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        types[root] = {"count": len(rows), "fields": {k: round(sum(r[k] for r in rows) / len(rows), 3) for k in FIELDS}}
    all_rows = [r for rows in by_type.values() for r in rows]
    overall = {k: round(sum(r[k] for r in all_rows) / len(all_rows), 3) for k in FIELDS} if all_rows else {}
    key = ["subject", "nmck", "submission_deadline", "delivery_region_code", "customer_inn"]
    # Обеспечение заявки в запросах котировок и небольших аукционах не требуется — его отсутствие не ошибка.
    rep = {
        "files": len(files),
        "parsed": len(all_rows),
        "parse_errors": errors,
        "key_fields_complete": round(sum(all(r[k] for k in key) for r in all_rows) / len(all_rows), 3) if all_rows else None,
        "overall": overall,
        "by_document_type": types,
        "roots": dict(Counter({k: v["count"] for k, v in types.items()})),
    }
    (ROOT / "corpus_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["download", "report", "contracts", "contracts-report"])
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--pages", type=int, default=1)
    ap.add_argument("--delay", type=float, default=0.7)
    args = ap.parse_args()
    if args.cmd == "download":
        download(args.pages, args.delay)
        return 0
    if args.cmd == "contracts":
        print(f"Скачано проектов контрактов: {download_contracts(args.limit, args.delay)}")
        return 0
    if args.cmd == "contracts-report":
        r = contracts_report()
        print(f"Файлов {r['files']}, читаемых {r['readable']}; найдено: " +
              ", ".join(f"{k} {v:.0%}" for k, v in r["found"].items() if v is not None))
        for u in r["unreadable"]:
            print(f"  нечитаемо: {u['file']} — {u['why']}")
        return 0
    r = report()
    print(f"Файлов {r['files']}, разобрано {r['parsed']}, ошибок {len(r['parse_errors'])}; "
          f"все ключевые поля (предмет, НМЦК, срок, регион, ИНН заказчика) — {r['key_fields_complete']:.0%}")
    for root, v in r["by_document_type"].items():
        weak = {k: f"{x:.0%}" for k, x in v["fields"].items() if x < 0.95}
        print(f"  {root}: {v['count']} шт.; поля < 95%: {weak or 'нет'}")
    for e in r["parse_errors"][:10]:
        print(f"  ✗ {e['file']} ({e['root']}): {e['error']}")
    return 0



# ---------- проекты контрактов из вложений ----------

CONTRACTS = CORPUS / "contracts"


def contract_links() -> list[tuple[str, str, str]]:
    from urllib.parse import unquote

    out = []
    for f in sorted(CORPUS.glob("*.xml")):
        root = etree.fromstring(f.read_bytes(), etree.XMLParser(resolve_entities=False, huge_tree=True))
        for att in root.iter():
            if isinstance(att.tag, str) and etree.QName(att).localname == "attachmentInfo":
                d = {etree.QName(c).localname: (c.text or "").strip() for c in att if isinstance(c.tag, str)}
                name = unquote(d.get("fileName", ""))
                if "контракт" in name.lower() and "обосн" not in name.lower() and d.get("url"):
                    out.append((f.stem, name, d["url"]))
                    break
    return out


def download_contracts(limit: int, delay: float) -> int:
    CONTRACTS.mkdir(parents=True, exist_ok=True)
    saved = 0
    with httpx.Client(timeout=60, headers=HEADERS, verify=ssl_context(), follow_redirects=True) as client:
        for reg, name, url in contract_links()[:limit]:
            ext = name.rsplit(".", 1)[-1].lower()
            path = CONTRACTS / f"{reg}.{ext}"
            if path.exists():
                continue
            r = client.get(url)
            if r.status_code == 429:
                time.sleep(40)
                r = client.get(url)
            if r.status_code == 200 and r.content:
                path.write_bytes(r.content)
                saved += 1
            else:
                print(f"  {reg}: HTTP {r.status_code}")
            time.sleep(delay)
    return saved


def contracts_report() -> dict:
    from app.docs.contract import analyze
    from app.docs.extract import DocumentError, extract_text

    rows = []
    for path in sorted(CONTRACTS.glob("*.*")):
        row = {"file": path.name, "format": path.suffix.lstrip(".")}
        try:
            text = extract_text(path.name, path.read_bytes())
        except DocumentError as exc:
            row["error"] = str(exc)
            rows.append(row)
            continue
        t = analyze(text)
        row.update({"chars": len(text), "payment_days": t.payment_days, "acceptance_days": t.acceptance_days,
                    "advance_percent": t.advance_percent, "supplier_penalty": t.supplier_penalty,
                    "max_fine_percent": t.max_fine_percent, "warranty_months": t.warranty_months,
                    "brands": t.brands_without_equivalent, "findings": [f.code for f in t.findings if f.severity != "info"]})
        rows.append(row)
    readable = [r for r in rows if "error" not in r and r["chars"] > 2000]
    share = lambda key: round(sum(r[key] is not None for r in readable) / len(readable), 3) if readable else None  # noqa: E731
    rep = {"files": len(rows), "readable": len(readable),
           "unreadable": [{"file": r["file"], "why": r.get("error") or "мало текста (скан?)"} for r in rows if r not in readable],
           "found": {k: share(k) for k in ("payment_days", "acceptance_days", "advance_percent", "supplier_penalty", "max_fine_percent")},
           "rows": rows}
    (ROOT / "contracts_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    return rep


if __name__ == "__main__":
    sys.exit(main())
