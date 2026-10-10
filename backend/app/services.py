"""Бизнес-логика поверх БД: загрузка извещений, оценка, лента, профили."""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import IS_POSTGRES
from app.domain import CanonicalTender, CompanyCard, Preferences
from app.egrul.providers import get_company, try_get_company
from app.eis.parser import parse_bytes
from app.models import Profile, ProfileVersion, Score, Tender
from app.reference import textvec
from app.scoring.engine import ScoreResult, evaluate

log = logging.getLogger(__name__)


def ingest(db: Session, filename: str, content: bytes) -> Tender:
    """Разбор файла и сохранение (повторная загрузка того же номера обновляет запись)."""
    canonical = parse_bytes(content, filename)
    payload = json.loads(canonical.model_dump_json())
    row = db.scalar(select(Tender).where(Tender.purchase_number == canonical.purchase_number))
    if row is None:
        row = Tender(purchase_number=canonical.purchase_number)
        db.add(row)
    else:
        db.query(Score).filter(Score.tender_id == row.id).delete()
    row.law = canonical.law
    row.subject = canonical.subject
    row.nmck = canonical.nmck
    row.region_code = canonical.delivery_region_code
    row.submission_deadline = canonical.submission_deadline
    if row.data and row.data.get("contract") and not payload.get("contract"):
        payload["contract"] = row.data["contract"]  # повторная загрузка извещения не теряет разобранный контракт
    row.data = payload
    row.raw_filename = filename[:255]
    row.raw_content = content.decode("utf-8", errors="replace")[:2_000_000]
    row.embedding = textvec.embed(canonical.text_for_matching())
    db.commit()
    db.refresh(row)
    return row


def read_documents(files: list[tuple[str, bytes]], law: str, tender: CanonicalTender | None = None,
                   company_inn: str | None = None):
    """Вложения любого вида → условия контракта + проверка каждого документа (тип, срок, ИНН).

    Проект контракта и ТЗ идут в разбор условий; лицензии, выписки, сертификаты, гарантии —
    в проверку срока действия против дат закупки. Нечитаемые файлы не роняют разбор, а попадают в находки.
    """
    from dataclasses import asdict

    from app.docs.checks import check
    from app.docs.contract import analyze
    from app.docs.extract import DocumentError, extract_document
    from app.domain import Finding

    texts, names, errors, doc_findings, docs = [], [], [], [], []
    for name, content in files:
        try:
            doc = extract_document(name, content)
        except DocumentError as exc:
            errors.append(Finding(code="unreadable", side="both", severity="warn" if "Tesseract" in str(exc) else "info",
                                  title=f"Не прочитан: {name}", detail=str(exc)))
            continue
        info, findings = check(name, doc.text, doc.method, tender, company_inn)
        docs.append(asdict(info))
        doc_findings += findings
        if info.doc_type in ("contract", "tz", "other"):
            texts.append(doc.text)
            names.append(name)
    terms = analyze("\n".join(texts), law, names) if texts else analyze("", law, names)
    if not texts:
        terms.findings = [f for f in terms.findings if f.code != "no_text"]
    terms.findings = errors + doc_findings + terms.findings
    terms.documents = docs
    return terms


def attach_documents(db: Session, row: Tender, files: list[tuple[str, bytes]], company_inn: str | None = None):
    from app.docs.contract import attach

    terms = read_documents(files, row.law, tender_model(row), company_inn)
    tender = attach(tender_model(row), terms)
    row.data = json.loads(tender.model_dump_json())
    db.query(Score).filter(Score.tender_id == row.id).delete()
    db.commit()
    return terms


def tender_model(row: Tender) -> CanonicalTender:
    return CanonicalTender.model_validate(row.data)


def current_version(db: Session, profile: Profile) -> ProfileVersion:
    return db.scalar(
        select(ProfileVersion).where(
            ProfileVersion.profile_id == profile.id, ProfileVersion.version == profile.current_version
        )
    )


def create_profile(db: Session, name: str, company_inn: str, prefs: Preferences, criteria_text: str | None) -> Profile:
    get_company(db, company_inn)  # проверка ИНН и прогрев кэша
    profile = Profile(name=name, company_inn=company_inn, current_version=1)
    db.add(profile)
    db.flush()
    db.add(ProfileVersion(profile_id=profile.id, version=1, criteria_text=criteria_text,
                          preferences=json.loads(prefs.model_dump_json())))
    db.commit()
    return profile


def new_version(db: Session, profile: Profile, prefs: Preferences, criteria_text: str | None) -> ProfileVersion:
    version = profile.current_version + 1
    pv = ProfileVersion(profile_id=profile.id, version=version, criteria_text=criteria_text,
                        preferences=json.loads(prefs.model_dump_json()))
    db.add(pv)
    profile.current_version = version
    db.commit()
    return pv


def compute(db: Session, tender: CanonicalTender, company: CompanyCard | None, prefs: Preferences,
            now: datetime | None = None, committed: tuple[float, int] = (0.0, 0)) -> ScoreResult:
    customer = try_get_company(db, tender.customer_inn)
    return evaluate(tender, company, customer, prefs, now=now, committed=committed)


BID_STATUSES = {
    "preparing": "Готовим заявку",
    "submitted": "Заявка подана",
    "won": "Выиграли — исполняем",
    "lost": "Не выиграли",
    "declined": "Отказались",
}


def bid_hold(tender: CanonicalTender, status: str) -> float:
    """Сколько денег заморожено: обеспечение заявки, пока идёт процедура; обеспечение контракта — при исполнении."""
    if status in ("preparing", "submitted"):
        return tender.app_guarantee_amount or 0.0
    if status == "won":
        if tender.contract_guarantee_amount is not None:
            return tender.contract_guarantee_amount
        return (tender.nmck or 0) * (tender.contract_guarantee_percent or 0) / 100
    return 0.0


def committed(db: Session, profile_id: int, exclude_tender_id: int | None = None) -> tuple[float, int]:
    from app.models import Bid

    total, count = 0.0, 0
    for bid in db.scalars(select(Bid).where(Bid.profile_id == profile_id)):
        if bid.tender_id == exclude_tender_id:
            continue
        row = db.get(Tender, bid.tender_id)
        hold = bid_hold(tender_model(row), bid.status) if row else 0.0
        if hold > 0:
            total, count = total + hold, count + 1
    return total, count


def score_row(db: Session, row: Tender, pv: ProfileVersion, company: CompanyCard | None, force: bool = False) -> Score:
    """Оценка из кэша (закупка × версия профиля) или новый расчёт."""
    existing = db.scalar(select(Score).where(Score.tender_id == row.id, Score.profile_version_id == pv.id))
    if existing and not force:
        return existing
    result = compute(db, tender_model(row), company, Preferences.model_validate(pv.preferences),
                     committed=committed(db, pv.profile_id, row.id))
    payload = json.loads(result.model_dump_json())
    if existing:
        existing.score, existing.verdict, existing.completeness = result.score, result.verdict, result.completeness
        existing.result, existing.elapsed_ms = payload, result.elapsed_ms
        existing.created_at = datetime.now(timezone.utc)
        score = existing
    else:
        score = Score(tender_id=row.id, profile_version_id=pv.id, score=result.score, verdict=result.verdict,
                      completeness=result.completeness, result=payload, elapsed_ms=result.elapsed_ms)
        db.add(score)
    db.commit()
    return score


def profile_company(db: Session, profile: Profile) -> CompanyCard | None:
    return try_get_company(db, profile.company_inn)


def rescore_all(db: Session, profile: Profile) -> int:
    pv = current_version(db, profile)
    company = profile_company(db, profile)
    rows = db.scalars(select(Tender)).all()
    for row in rows:
        score_row(db, row, pv, company, force=True)
    return len(rows)


VERDICT_ORDER = {"go": 0, "consider": 1, "skip": 2}


def feed(db: Session, profile: Profile, verdict: str | None = None, q: str | None = None,
         sort: str = "score", limit: int = 50, offset: int = 0) -> dict:
    pv = current_version(db, profile)
    company = profile_company(db, profile)
    rows = db.scalars(select(Tender)).all()
    items = []
    counts = {"go": 0, "consider": 0, "skip": 0}
    stop_count = 0
    from app.models import Bid

    bids = {b.tender_id: b.status for b in db.scalars(select(Bid).where(Bid.profile_id == profile.id))}
    query_vec = textvec.embed(q) if q else None
    for row in rows:
        s = score_row(db, row, pv, company)
        counts[s.verdict] = counts.get(s.verdict, 0) + 1
        if s.result.get("stops"):
            stop_count += 1
        if verdict and s.verdict != verdict:
            continue
        relevance = None
        if q:
            ql = q.lower()
            text_hit = ql in row.subject.lower() or ql in row.purchase_number or ql in (row.data.get("customer_name") or "").lower()
            relevance = 1.0 if text_hit else textvec.cosine(query_vec, row.embedding or [])
            if not text_hit and relevance < 0.12:
                continue
        item = _feed_item(row, s, relevance)
        item["bid_status"] = bids.get(row.id)
        items.append(item)
    if q:
        items.sort(key=lambda x: (-(x["relevance"] or 0), -x["score"]))
    elif sort == "deadline":
        items.sort(key=lambda x: x["submission_deadline"] or "9999")
    elif sort == "nmck":
        items.sort(key=lambda x: -(x["nmck"] or 0))
    else:
        items.sort(key=lambda x: (VERDICT_ORDER.get(x["verdict"], 9), -x["score"]))
    return {
        "profile_id": profile.id,
        "profile_version": pv.version,
        "total": len(rows),
        "counts": counts,
        "stop_count": stop_count,
        "items": items[offset: offset + limit],
        "filtered": len(items),
    }


def _feed_item(row: Tender, s: Score, relevance: float | None = None) -> dict:
    d = row.data
    return {
        "tender_id": row.id,
        "score_id": s.id,
        "purchase_number": row.purchase_number,
        "subject": row.subject,
        "law": row.law,
        "procedure_name": d.get("procedure_name"),
        "customer_name": d.get("customer_name"),
        "region_name": d.get("delivery_region_name"),
        "nmck": row.nmck,
        "submission_deadline": d.get("submission_deadline"),
        "smp_only": d.get("smp_only"),
        "score": s.score,
        "verdict": s.verdict,
        "completeness": s.completeness,
        "main_reason": s.result.get("main_reason"),
        "factors": [{"key": f["key"], "label": f["label"], "score": f["score"]} for f in s.result.get("factors", [])],
        "relevance": round(relevance, 3) if relevance is not None else None,
    }


def preview(db: Session, profile: Profile, prefs: Preferences, tender_id: int | None) -> dict:
    """Пересчёт ленты с черновыми настройками без сохранения — для «живых» ползунков."""
    company = profile_company(db, profile)
    rows = db.scalars(select(Tender)).all()
    counts = {"go": 0, "consider": 0, "skip": 0}
    example = None
    for row in rows:
        result = compute(db, tender_model(row), company, prefs, committed=committed(db, profile.id, row.id))
        counts[result.verdict] += 1
        if row.id == tender_id:
            example = json.loads(result.model_dump_json())
    return {"counts": counts, "total": len(rows), "example": example}


def similar(db: Session, row: Tender, limit: int = 5) -> list[Tender]:
    if not row.embedding:
        return []
    if IS_POSTGRES:
        vec = "[" + ",".join(f"{x:.6f}" for x in row.embedding) + "]"
        stmt = (select(Tender).where(Tender.id != row.id, Tender.embedding.is_not(None))
                .order_by(text("embedding <=> CAST(:v AS vector)")).limit(limit))
        return list(db.scalars(stmt, {"v": vec}))
    others = [t for t in db.scalars(select(Tender).where(Tender.id != row.id)) if t.embedding]
    others.sort(key=lambda t: -textvec.cosine(row.embedding, t.embedding))
    return others[:limit]
