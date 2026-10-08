import csv
import io
import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.domain import PROCEDURE_NAMES, VERDICT_NAMES, CanonicalTender, Preferences
from app.egrul.providers import CompanyNotFound, EgrulError, InvalidInn, get_company
from app.eis.parser import ParseError, parse_bytes
from app.models import Batch, BatchFile, Feedback, Profile, ProfileVersion, Score, Tender
from app.nlp import llm
from app.nlp.criteria import parse_criteria
from app.reference.regions import DISTRICTS, REGIONS
from app.scoring.factors import FACTORS
from app import services
from app.worker import dispatch_batch, unpack

router = APIRouter(prefix="/api")
settings = get_settings()
EVAL_REPORT = Path(__file__).resolve().parents[1] / "eval" / "report.json"


# ---------- служебное ----------

@router.get("/health", summary="Состояние сервиса и зависимостей")
def health(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {
        "status": "ok",
        "llm": llm.provider_status(),
        "egrul_provider": settings.egrul_provider if settings.dadata_api_key or settings.egrul_provider == "mock" else "mock",
        "queue": "celery" if settings.redis_url else "in-process",
    }


@router.get("/factors", summary="Схема факторов для панели настроек и паутинки")
def factors():
    return {
        "factors": [
            {"key": f.key, "label": f.label, "base_weight": f.base_weight, "description": f.description, "controls": f.controls}
            for f in FACTORS
        ],
        "regions": [{"code": r.code, "name": r.name, "district": r.district} for r in REGIONS],
        "districts": DISTRICTS,
        "procedures": PROCEDURE_NAMES,
        "verdicts": VERDICT_NAMES,
        "defaults": json.loads(Preferences().model_dump_json()),
    }


# ---------- компании (ЕГРЮЛ) ----------

@router.get("/companies/{inn}", summary="Карточка организации из ЕГРЮЛ по ИНН")
def company(inn: str, refresh: bool = False, db: Session = Depends(get_db)):
    try:
        return get_company(db, inn, refresh=refresh)
    except InvalidInn as exc:
        raise HTTPException(400, str(exc))
    except CompanyNotFound as exc:
        raise HTTPException(404, str(exc))
    except EgrulError as exc:
        raise HTTPException(502, str(exc))


# ---------- профили ----------

class ProfileCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    company_inn: str
    criteria_text: str | None = None
    preferences: Preferences | None = None


class ProfileUpdate(BaseModel):
    preferences: Preferences
    criteria_text: str | None = None


class ParseRequest(BaseModel):
    text: str = Field(..., max_length=5000)
    use_llm: bool = True


def _profile(db: Session, profile_id: int | None) -> Profile:
    profile = db.get(Profile, profile_id) if profile_id else db.scalar(select(Profile).order_by(Profile.id))
    if profile is None:
        raise HTTPException(404, "Профиль не найден — создайте его через POST /api/profiles")
    return profile


def _profile_out(db: Session, profile: Profile) -> dict:
    pv = services.current_version(db, profile)
    company_card = services.profile_company(db, profile)
    return {
        "id": profile.id,
        "name": profile.name,
        "company_inn": profile.company_inn,
        "company": company_card,
        "version": pv.version,
        "criteria_text": pv.criteria_text,
        "preferences": pv.preferences,
        "versions": [{"version": v.version, "created_at": v.created_at} for v in profile.versions],
    }


@router.get("/profiles", summary="Список профилей")
def list_profiles(db: Session = Depends(get_db)):
    return [{"id": p.id, "name": p.name, "company_inn": p.company_inn, "version": p.current_version}
            for p in db.scalars(select(Profile).order_by(Profile.id))]


@router.post("/profiles", summary="Создать профиль (критерии текстом и/или готовые настройки)")
def create_profile(body: ProfileCreate, db: Session = Depends(get_db)):
    prefs = body.preferences or Preferences()
    parsed = None
    if body.criteria_text:
        parsed = parse_criteria(body.criteria_text, prefs)
        prefs = parsed.preferences
    try:
        profile = services.create_profile(db, body.name, body.company_inn, prefs, body.criteria_text)
    except InvalidInn as exc:
        raise HTTPException(400, str(exc))
    except EgrulError as exc:
        raise HTTPException(404, str(exc))
    services.rescore_all(db, profile)
    out = _profile_out(db, profile)
    out["parsed"] = parsed.to_dict() if parsed else None
    return out


@router.get("/profiles/{profile_id}", summary="Профиль с текущими настройками")
def get_profile(profile_id: int, db: Session = Depends(get_db)):
    return _profile_out(db, _profile(db, profile_id))


@router.post("/profiles/{profile_id}/parse", summary="Разобрать текст критериев в настройки (без сохранения)")
def parse_profile_text(profile_id: int, body: ParseRequest, db: Session = Depends(get_db)):
    profile = _profile(db, profile_id)
    base = Preferences()
    base.geo.same_district_score = Preferences.model_validate(services.current_version(db, profile).preferences).geo.same_district_score
    return parse_criteria(body.text, base, use_llm=body.use_llm).to_dict()


@router.put("/profiles/{profile_id}", summary="Сохранить настройки как новую версию и пересчитать ленту")
def update_profile(profile_id: int, body: ProfileUpdate, db: Session = Depends(get_db)):
    profile = _profile(db, profile_id)
    services.new_version(db, profile, body.preferences, body.criteria_text)
    n = services.rescore_all(db, profile)
    out = _profile_out(db, profile)
    out["rescored"] = n
    return out


# ---------- закупки ----------

async def _read_upload(file: UploadFile) -> bytes:
    content = await file.read()
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"Файл больше {settings.max_upload_mb} МБ")
    if not content.strip():
        raise HTTPException(400, "Пустой файл")
    return content


@router.post("/tenders/parse", summary="Разобрать выгрузку ЕИС без сохранения")
async def parse_tender(file: UploadFile = File(...)) -> CanonicalTender:
    content = await _read_upload(file)
    try:
        return parse_bytes(content, file.filename or "")
    except ParseError as exc:
        raise HTTPException(422, str(exc))


@router.post("/tenders", summary="Загрузить извещение (XML/JSON) и сразу оценить")
async def upload_tender(file: UploadFile = File(...), profile_id: int | None = Form(None), db: Session = Depends(get_db)):
    content = await _read_upload(file)
    profile = _profile(db, profile_id)
    try:
        row = services.ingest(db, file.filename or "upload.xml", content)
    except ParseError as exc:
        raise HTTPException(422, str(exc))
    pv = services.current_version(db, profile)
    score = services.score_row(db, row, pv, services.profile_company(db, profile), force=True)
    return {"tender_id": row.id, "score_id": score.id, "result": score.result}


@router.get("/tenders/{tender_id}", summary="Закупка, её оценка по профилю и похожие закупки")
def get_tender(tender_id: int, profile_id: int | None = None, db: Session = Depends(get_db)):
    row = db.get(Tender, tender_id)
    if row is None:
        raise HTTPException(404, "Закупка не найдена")
    profile = _profile(db, profile_id)
    pv = services.current_version(db, profile)
    score = services.score_row(db, row, pv, services.profile_company(db, profile))
    customer = None
    if row.data.get("customer_inn"):
        from app.egrul.providers import try_get_company
        customer = try_get_company(db, row.data["customer_inn"])
    rank = db.scalar(select(func.count()).select_from(Score).where(
        Score.profile_version_id == pv.id, Score.score > score.score))
    return {
        "tender": row.data,
        "tender_id": row.id,
        "score_id": score.id,
        "result": score.result,
        "rank": (rank or 0) + 1,
        "customer": customer,
        "similar": [services._feed_item(t, services.score_row(db, t, pv, services.profile_company(db, profile)))
                    for t in services.similar(db, row)],
        "profile_version": pv.version,
    }


@router.get("/tenders/{tender_id}/raw", response_class=PlainTextResponse, summary="Исходный файл извещения")
def tender_raw(tender_id: int, db: Session = Depends(get_db)):
    row = db.get(Tender, tender_id)
    if row is None:
        raise HTTPException(404, "Закупка не найдена")
    return row.raw_content or ""


# ---------- оценка ----------

class ScoreRequest(BaseModel):
    tender_id: int | None = None
    tender: CanonicalTender | None = None
    profile_id: int | None = None
    company_inn: str | None = None
    preferences: Preferences | None = None


@router.post("/score", summary="Оценить закупку: по id или передав каноническую модель, с профилем или настройками")
def score(body: ScoreRequest, db: Session = Depends(get_db)):
    if body.tender is not None:
        tender = body.tender
    elif body.tender_id is not None:
        row = db.get(Tender, body.tender_id)
        if row is None:
            raise HTTPException(404, "Закупка не найдена")
        tender = services.tender_model(row)
    else:
        raise HTTPException(400, "Передайте tender_id или tender")
    if body.preferences is not None:
        prefs = body.preferences
        company_card = get_company(db, body.company_inn) if body.company_inn else None
    else:
        profile = _profile(db, body.profile_id)
        prefs = Preferences.model_validate(services.current_version(db, profile).preferences)
        company_card = services.profile_company(db, profile)
    return services.compute(db, tender, company_card, prefs)


class PreviewRequest(BaseModel):
    profile_id: int | None = None
    preferences: Preferences
    tender_id: int | None = None


@router.post("/score/preview", summary="Пересчитать ленту с черновыми настройками (без сохранения)")
def score_preview(body: PreviewRequest, db: Session = Depends(get_db)):
    return services.preview(db, _profile(db, body.profile_id), body.preferences, body.tender_id)


# ---------- лента и экспорт ----------

@router.get("/feed", summary="Лента закупок, отсортированная по оценке")
def feed(profile_id: int | None = None, verdict: str | None = Query(None, pattern="^(go|consider|skip|manual)$"),
         q: str | None = None, sort: str = Query("score", pattern="^(score|deadline|nmck)$"),
         limit: int = Query(50, le=500), offset: int = 0, db: Session = Depends(get_db)):
    return services.feed(db, _profile(db, profile_id), verdict, q, sort, limit, offset)


@router.get("/feed/export", summary="Выгрузка ленты в XLSX или CSV")
def feed_export(profile_id: int | None = None, format: str = Query("xlsx", pattern="^(xlsx|csv)$"),
                verdict: str | None = None, db: Session = Depends(get_db)):
    data = services.feed(db, _profile(db, profile_id), verdict, None, "score", 10_000, 0)
    header = ["Номер", "Предмет", "Закон", "Способ", "Заказчик", "Регион", "НМЦК, ₽", "Подача до", "Оценка, %",
              "Вердикт", "Главная причина"]
    rows = [[i["purchase_number"], i["subject"], i["law"], i["procedure_name"], i["customer_name"], i["region_name"],
             i["nmck"], (i["submission_deadline"] or "")[:16].replace("T", " "), i["score"],
             VERDICT_NAMES.get(i["verdict"], i["verdict"]), i["main_reason"]] for i in data["items"]]
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=";")
        writer.writerow(header)
        writer.writerows(rows)
        return StreamingResponse(io.BytesIO(buf.getvalue().encode("utf-8-sig")), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="tenders_{stamp}.csv"'})
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Лента"
    ws.append(header)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    fills = {"Участвовать": "D9F8EA", "Рассмотреть": "FFEDB8", "Не участвовать": "FFDCE3", "Проверить вручную": "E6E2FF"}
    for r in rows:
        ws.append(r)
        fill = fills.get(r[9])
        if fill:
            ws.cell(ws.max_row, 10).fill = PatternFill("solid", fgColor=fill)
    for col, width in zip("ABCDEFGHIJK", (24, 60, 8, 24, 40, 28, 14, 18, 10, 18, 70)):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A2"
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return StreamingResponse(out, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="tenders_{stamp}.xlsx"'})


# ---------- пакетная загрузка ----------

@router.post("/batches", summary="Пакетная загрузка: ZIP или несколько XML/JSON, обработка в очереди")
async def create_batch(files: list[UploadFile] = File(...), profile_id: int | None = Form(None), db: Session = Depends(get_db)):
    profile = _profile(db, profile_id)
    unpacked: list[tuple[str, bytes]] = []
    for f in files:
        content = await _read_upload(f)
        try:
            unpacked += unpack(f.filename or "file", content)
        except Exception:
            raise HTTPException(422, f"Не удалось распаковать {f.filename}")
    if not unpacked:
        raise HTTPException(422, "В загрузке нет файлов .xml или .json")
    batch = Batch(profile_id=profile.id, status="queued", total=len(unpacked), errors=[], tender_ids=[])
    db.add(batch)
    db.flush()
    for name, content in unpacked:
        db.add(BatchFile(batch_id=batch.id, filename=name[:255], content=content.decode("utf-8", errors="replace")))
    db.commit()
    mode = dispatch_batch(batch.id)
    return {"batch_id": batch.id, "total": batch.total, "queue": mode}


@router.get("/batches/{batch_id}", summary="Прогресс пакета и его результаты")
def get_batch(batch_id: int, db: Session = Depends(get_db)):
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(404, "Пакет не найден")
    profile = _profile(db, batch.profile_id)
    pv = services.current_version(db, profile)
    items = []
    if batch.status == "done":
        for tid in batch.tender_ids or []:
            row = db.get(Tender, tid)
            if row:
                items.append(services._feed_item(row, services.score_row(db, row, pv, services.profile_company(db, profile))))
        items.sort(key=lambda x: (services.VERDICT_ORDER.get(x["verdict"], 9), -x["score"]))
    return {"id": batch.id, "status": batch.status, "total": batch.total, "processed": batch.processed,
            "failed": batch.failed, "errors": batch.errors, "items": items}


@router.get("/demo/batch.zip", summary="Демо-пакет извещений со свежими датами — для проверки пакетной загрузки")
def demo_zip():
    import zipfile

    from app.seed.demo import demo_files

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in demo_files():
            zf.writestr(name, content)
        real = Path(__file__).resolve().parents[1] / "samples"
        for path in real.glob("real_*.xml"):
            zf.writestr(path.name, path.read_bytes())
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": 'attachment; filename="demo_notices.zip"'})


# ---------- обратная связь и точность ----------

class FeedbackIn(BaseModel):
    correct: bool
    expected_verdict: str | None = Field(None, pattern="^(go|consider|skip|manual)$")
    comment: str | None = Field(None, max_length=1000)


@router.post("/scores/{score_id}/feedback", summary="Отметка «вердикт верный / неверный»")
def feedback(score_id: int, body: FeedbackIn, db: Session = Depends(get_db)):
    if db.get(Score, score_id) is None:
        raise HTTPException(404, "Оценка не найдена")
    db.add(Feedback(score_id=score_id, correct=body.correct, expected_verdict=body.expected_verdict, comment=body.comment))
    db.commit()
    return {"ok": True}


@router.get("/accuracy", summary="Точность: эталонный набор + отметки пользователей")
def accuracy(db: Session = Depends(get_db)):
    total = db.scalar(select(func.count()).select_from(Feedback)) or 0
    correct = db.scalar(select(func.count()).select_from(Feedback).where(Feedback.correct.is_(True))) or 0
    report = json.loads(EVAL_REPORT.read_text(encoding="utf-8")) if EVAL_REPORT.exists() else None
    timings = db.execute(select(func.avg(Score.elapsed_ms), func.max(Score.elapsed_ms))).one()
    return {
        "feedback": {"total": total, "correct": correct, "rate": round(correct / total, 3) if total else None},
        "golden": report,
        "timing_ms": {"avg": round(timings[0] or 0, 2), "max": round(timings[1] or 0, 2)},
    }
