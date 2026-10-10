import io
import zipfile
from pathlib import Path

import pytest

from app.docs.contract import analyze, attach
from app.docs.extract import DocumentError, extract_text
from app.scoring.engine import evaluate
from tests.test_engine import COMPANY, NOW, prefs, tender

FIX = Path(__file__).parent / "fixtures"
BAD = (FIX / "contract_bad.txt").read_text(encoding="utf-8")
GOOD = (FIX / "contract_good.txt").read_text(encoding="utf-8")


def codes(terms):
    return {f.code for f in terms.findings}


def test_bad_contract_terms():
    t = analyze(BAD)
    assert (t.payment_days, t.payment_working) == (30, True)
    assert t.acceptance_days == 25 and t.advance_percent == 0
    assert t.supplier_penalty == "elevated" and t.max_fine_percent == 20
    assert t.brands_without_equivalent == ["HP"]
    assert {"payment_late", "acceptance_late", "penalty_high", "fine_high", "brand_no_equivalent", "original_only"} <= codes(t)


def test_good_contract_has_no_risks():
    t = analyze(GOOD)
    assert t.payment_days == 7 and t.advance_percent == 30 and t.supplier_penalty == "standard"
    assert t.warranty_months == 36 and t.brands_without_equivalent == []
    assert not [f for f in t.findings if f.severity != "info"]


def test_findings_are_two_sided():
    t = analyze(BAD)
    sides = {f.code: f.side for f in t.findings}
    assert sides["brand_no_equivalent"] == "customer"  # риск ФАС — заказчику
    assert sides["cash_gap"] == "supplier"  # кассовый разрыв — поставщику
    assert sides["penalty_high"] == "both"


def test_223_fz_payment_is_not_flagged_as_44_violation():
    assert "payment_late" not in codes(analyze(BAD, law="223-FZ"))


def test_contract_lowers_score_and_fills_advance():
    base = evaluate(tender(), COMPANY, None, prefs(), now=NOW)
    t = attach(tender(), analyze(BAD))
    assert t.advance_percent == 0 and t.sources["advance_percent"].path == "проект контракта"
    risky = evaluate(t, COMPANY, None, prefs(), now=NOW)
    cond = next(f for f in risky.factors if f.key == "conditions")
    assert risky.score < base.score and any("Контракт" in r for r in cond.reasons)
    assert risky.verdict != "go"  # высокий риск контракта — красный флаг
    good = evaluate(attach(tender(), analyze(GOOD)), COMPANY, None, prefs(), now=NOW)
    assert good.verdict == "go"


def _docx(text: str) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in text.splitlines())
    xml = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
           f'wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", xml)
    return buf.getvalue()


def test_extract_docx_and_errors():
    assert "оригинальные картриджи" in extract_text("contract.docx", _docx(BAD))
    with pytest.raises(DocumentError):
        extract_text("x.docx", b"not a zip")
    with pytest.raises(DocumentError):
        extract_text("old.doc", b"\xd0\xcf\x11\xe0")


def test_documents_api(client):
    from tests.conftest import SAMPLES

    path = next(SAMPLES.glob("real_44fz_ef2020_*.xml"))
    resp = client.post("/api/quick-score", files=[("file", (path.name, path.read_bytes())),
                                                  ("documents", ("contract.docx", _docx(BAD))),
                                                  ("documents", ("scan.doc", b"\xd0\xcf\x11\xe0"))],
                       data={"save": "true"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    contract = body["tender"]["contract"]
    assert contract["payment_days"] == 30 and "contract.docx" in contract["files"]
    assert any(f["code"] == "unreadable" for f in contract["findings"])
    assert "documents_ms" in body["timings"]

    tid = body["tender_id"]
    r2 = client.post(f"/api/tenders/{tid}/documents", files=[("files", ("good.txt", GOOD.encode()))])
    assert r2.status_code == 200 and r2.json()["contract"]["payment_days"] == 7
    card = client.get(f"/api/tenders/{tid}").json()
    assert card["tender"]["contract"]["advance_percent"] == 30


# Фразы из реальных проектов контрактов ЕИС, на которых правила ошибались, — не должны давать ложных рисков.
REAL_SNIPPETS = """
Подрядчик обязан представлять Заказчику в течение 10 рабочих дней со дня оплаты Подрядчиком выполненных обязательств по договору с субподрядчиком, соисполнителем следующие документы.
Заказчик обязан в срок не позднее 10 дней после получения требования Поставщика об уплате штрафа оплатить штраф.
Работа клиентской части с операционными системами: Alt Linux, Astra Linux, MS Windows 7/8/10/11 32-bit и 64-bit.
Факт внесения денежных средств подтверждается платёжным поручением либо оригинальной выпиской из банка.
Оплата указанных в п.1.1 настоящего контракта услуг осуществляется Заказчиком ежемесячно по факту оказанных услуг, не более чем в течение семи рабочих дней с даты подписания заказчиком электронного документа о приемке.
""" + "Прочие условия контракта. " * 20


def test_real_contract_snippets_no_false_risks():
    t = analyze(REAL_SNIPPETS)
    assert (t.payment_days, t.payment_working) == (7, True)  # «семи рабочих дней», а не 10 дней субподрядчику
    assert t.brands_without_equivalent == []
    bad = {f.code for f in t.findings if f.severity != "info"}
    assert not bad & {"payment_late", "brand_no_equivalent", "original_only"}
    assert "compat_required" in {f.code for f in t.findings}
