from datetime import timedelta

from app import customer as cust
from app.docs.contract import analyze, attach
from app.domain import CompanyCard, OkvedEntry
from tests.test_documents import BAD, _docx
from tests.test_engine import NOW, tender


def codes(fs):
    return {f.code for f in fs}


def test_short_deadline_is_flagged_for_customer():
    t = tender(published_at=NOW, submission_deadline=NOW + timedelta(days=4))
    assert "deadline_short" in codes(cust.check_notice(t))
    ok = tender(published_at=NOW, submission_deadline=NOW + timedelta(days=8))
    assert "deadline_ok" in codes(cust.check_notice(ok))
    big = tender(nmck=400_000_000, published_at=NOW, submission_deadline=NOW + timedelta(days=8))
    assert "deadline_short" in codes(cust.check_notice(big))  # свыше 300 млн — минимум 15 дней


def test_contract_risks_visible_to_customer():
    t = attach(tender(), analyze(BAD))
    found = codes(cust.check_notice(t))
    assert {"brand_no_equivalent", "payment_late", "penalty_high"} <= found
    assert "cash_gap" not in found  # это риск поставщика


def test_supplier_interest():
    res = cust.supplier_interest(tender(), now=NOW)
    assert res["total"] == 3 and sum(res["counts"].values()) == 3
    it = next(p for p in res["profiles"] if p["profile"].startswith("IT"))
    assert it["verdict"] in ("go", "consider")


def test_participant_checks():
    t = tender(smp_only=True, nmck=20_000_000)
    good = CompanyCard(inn="5406123450", name="ООО Хорошая", status="ACTIVE", is_msp=True,
                       registration_date=NOW - timedelta(days=2000), okveds=[OkvedEntry(code="46.51", main=True)])
    r = cust.check_participant(t, good, cust.Participant(inn=good.inn, price=19_000_000), now=NOW)
    assert r["risk"] == "low"
    bad = good.model_copy(update={"is_msp": False, "registration_date": NOW - timedelta(days=60), "status": "LIQUIDATING"})
    r = cust.check_participant(t, bad, cust.Participant(inn=good.inn, price=14_000_000), now=NOW)
    assert r["risk"] == "high"
    assert {"inactive", "young", "not_smp", "dumping"} <= codes(r["findings"])


def test_customer_api(client):
    from tests.conftest import SAMPLES

    path = next(SAMPLES.glob("real_*.xml"))
    r = client.post("/api/customer/check", files=[("file", (path.name, path.read_bytes())),
                                                  ("documents", ("contract.docx", _docx(BAD)))])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["high"] >= 2 and body["interest"]["total"] == 3
    r2 = client.post("/api/customer/participants",
                     json={"tender": body["tender"], "participants": [{"inn": "5406123450", "price": 50_000_000}]})
    assert r2.status_code == 200
    p = r2.json()["participants"][0]
    assert p["company"]["name"] and any(f["code"] == "dumping" for f in p["findings"])
