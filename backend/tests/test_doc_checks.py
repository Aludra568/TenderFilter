import io
import os
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.docs import ocr
from app.docs.checks import check, classify, validity
from tests.test_engine import NOW, tender

TODAY = date(2026, 10, 10)
LICENSE_EXPIRED = """ЛИЦЕНЗИЯ № Л041-01126-54/00012345
на осуществление медицинской деятельности
Выдана: ООО «Сибтехснаб», ИНН 5406123450
Дата предоставления лицензии: 15.03.2020
Лицензия действительна до 12.03.2025"""


def codes(fs):
    return {f.code for f in fs}


def test_expired_license_is_caught():
    info, fs = check("license.pdf", LICENSE_EXPIRED, "text", tender(), "5406123450", today=TODAY)
    assert info.doc_type == "license" and info.valid_until == "12.03.2025"
    assert "doc_expired" in codes(fs)
    assert next(f for f in fs if f.code == "doc_expired").severity == "high"


def test_date_forms_and_indefinite():
    assert validity("Срок действия: по 12 марта 2027 г.")[0] == date(2027, 3, 12)
    assert validity("Сертификат действует с 01.01.2025 по 31.12.2027")[0] == date(2027, 12, 31)
    assert validity("Дата окончания срока действия: 2028-05-01")[0] == date(2028, 5, 1)
    assert validity("Лицензия предоставлена бессрочно")[1] is True


def test_expires_before_deadline_and_during_contract():
    t = tender(submission_deadline=NOW + timedelta(days=20), contract_term_days=90)
    soon = f"Сертификат соответствия. Срок действия до {(NOW + timedelta(days=5)):%d.%m.%Y}"
    assert "doc_expires_before_deadline" in codes(check("cert.pdf", soon, "text", t, None, today=TODAY)[1])
    mid = f"Сертификат соответствия. Срок действия до {(NOW + timedelta(days=60)):%d.%m.%Y}"
    assert "doc_expires_during_contract" in codes(check("cert.pdf", mid, "text", t, None, today=TODAY)[1])


def test_bank_guarantee_must_outlive_contract_by_a_month():
    t = tender(submission_deadline=NOW + timedelta(days=10), contract_term_days=60)
    short = f"Независимая (банковская) гарантия № 77. Гарантия действует по {(NOW + timedelta(days=80)):%d.%m.%Y}"
    fs = check("bg.pdf", short, "text", t, None, today=TODAY)[1]
    assert "guarantee_too_short" in codes(fs)
    ok = f"Банковская гарантия. Действует до {(NOW + timedelta(days=200)):%d.%m.%Y}"
    assert "doc_valid" in codes(check("bg.pdf", ok, "text", t, None, today=TODAY)[1])


def test_document_of_another_company():
    fs = check("license.pdf", LICENSE_EXPIRED.replace("5406123450", "7707083893"), "text", tender(), "5406123450",
               today=TODAY)[1]
    assert "doc_other_inn" in codes(fs)


def test_classify_universal():
    assert classify("Выписка из реестра членов саморегулируемой организации")[0] == "sro"
    assert classify("ДЕКЛАРАЦИЯ О СООТВЕТСТВИИ ЕАЭС N RU Д-RU")[0] == "declaration"
    assert classify("Проект контракта. 1. Предмет контракта")[0] == "contract"
    assert classify("Доверенность № 5")[0] == "power_of_attorney"


def test_quick_score_flags_expired_license(client):
    from tests.conftest import SAMPLES

    path = next(SAMPLES.glob("real_44fz_ef2020_*.xml"))
    r = client.post("/api/quick-score", files=[("file", (path.name, path.read_bytes())),
                                               ("documents", ("license.txt", LICENSE_EXPIRED.encode()))],
                    data={"save": "false"})
    assert r.status_code == 200, r.text
    contract = r.json()["tender"]["contract"]
    assert "doc_expired" in {f["code"] for f in contract["findings"]}
    assert contract["documents"][0]["doc_type"] == "license"


def _font():
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf"):
        if Path(p).exists():
            return p
    return None


# В CI (GitHub Actions выставляет CI=true) Tesseract ставится — там тест обязан выполниться, а не пропуститься.
@pytest.mark.skipif(not os.environ.get("CI") and (not ocr.available() or not _font()),
                    reason="нет Tesseract с русским языком — проверяется в CI")
def test_scanned_expired_license_via_ocr():
    from PIL import Image, ImageDraw, ImageFont

    from app.docs.extract import extract_document

    img = Image.new("RGB", (1800, 900), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(_font(), 48)
    for i, line in enumerate(LICENSE_EXPIRED.splitlines()):
        draw.text((60, 60 + i * 110), line, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    doc = extract_document("скан_лицензии.png", buf.getvalue())
    assert doc.method == "ocr"
    info, fs = check(doc.name, doc.text, doc.method, tender(), "5406123450", today=TODAY)
    assert info.doc_type == "license"
    assert "doc_expired" in codes(fs) and "ocr_used" in codes(fs)
