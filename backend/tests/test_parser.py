import json
from datetime import datetime, timedelta, timezone

import pytest
from conftest import SAMPLES

from app.eis.parser import ParseError, parse_bytes
from app.seed.demo import SPECS, notice_223_xml, notice_xml

REAL = SAMPLES / "real_44fz_ef2020_0173100008726000065.xml"


def test_real_eis_notice_key_fields():
    t = parse_bytes(REAL.read_bytes())
    assert t.purchase_number == "0173100008726000065"
    assert t.law == "44-FZ"
    assert t.procedure_type == "e_auction"
    assert t.nmck == pytest.approx(108142501.80)
    assert t.customer_inn == "7702166610"
    assert t.delivery_region_code == "77"
    assert t.submission_deadline == datetime(2026, 10, 20, 9, 0, tzinfo=timezone(timedelta(hours=3)))
    assert t.app_guarantee_amount == pytest.approx(1081425.02)
    assert t.contract_guarantee_percent == 10.0
    assert t.okpd2 == ["26.20.11.110"]
    assert len(t.items) == 2 and t.items[0].quantity == 365
    assert t.national_regime is True
    assert t.smp_only is False
    assert t.contract_term_days and t.contract_term_days > 30
    assert not t.parse_warnings


def test_every_value_has_source_path():
    t = parse_bytes(REAL.read_bytes())
    for field in ("nmck", "deadline", "customer_inn", "delivery_place", "contract_guarantee_part"):
        assert field in t.sources
        assert t.sources[field].path.startswith("epNotificationEF2020/")


def test_demo_notices_roundtrip():
    now = datetime(2026, 10, 8, 12, tzinfo=timezone(timedelta(hours=3)))
    for spec in SPECS:
        t = parse_bytes(notice_xml(spec, now).encode())
        assert t.purchase_number == spec.number
        assert t.nmck == pytest.approx(spec.nmck)
        assert t.smp_only is spec.smp
        assert bool(t.national_regime) is spec.national
        assert t.okpd2 == list(dict.fromkeys(i[1] for i in spec.items))


def test_223fz_notice():
    t = parse_bytes(notice_223_xml(datetime.now(timezone.utc)).encode())
    assert t.law == "223-FZ"
    assert t.purchase_number == "32615000412"
    assert t.procedure_type == "proposal_request"
    assert t.nmck == 3150000
    assert t.smp_only is True
    assert t.delivery_region_code == "54"
    assert set(t.okpd2) == {"26.20.11.110", "26.20.17.110"}


def test_canonical_json_input():
    t = parse_bytes(REAL.read_bytes())
    again = parse_bytes(t.model_dump_json().encode())
    assert again.purchase_number == t.purchase_number and again.nmck == t.nmck


def test_arbitrary_json_uses_same_field_map():
    payload = {"commonInfo": {"purchaseNumber": "0123", "purchaseObjectInfo": "Поставка бумаги"},
               "maxPriceInfo": {"maxPrice": "150000.50"}, "collectingInfo": {"endDT": "2026-11-01T10:00:00+03:00"}}
    t = parse_bytes(json.dumps(payload, ensure_ascii=False).encode())
    assert t.subject == "Поставка бумаги" and t.nmck == 150000.5


@pytest.mark.parametrize("content", [b"<broken", b"<root><x>1</x></root>", b"{not json"])
def test_bad_input_raises_parse_error(content):
    with pytest.raises(ParseError):
        parse_bytes(content)


def test_xxe_is_not_resolved(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET")
    xml = f"""<?xml version="1.0"?>
<!DOCTYPE r [<!ENTITY x SYSTEM "file:///{secret.as_posix()}">]>
<epNotificationEF2020><commonInfo><purchaseNumber>1</purchaseNumber>
<purchaseObjectInfo>&x;</purchaseObjectInfo></commonInfo></epNotificationEF2020>""".encode()
    try:
        t = parse_bytes(xml)
        assert "TOP-SECRET" not in t.subject
    except ParseError:
        pass


_REAL = sorted(SAMPLES.glob("real_44fz_*.xml"))


@pytest.mark.parametrize("path", _REAL, ids=[p.name for p in _REAL])
def test_real_notices_of_all_types_have_key_fields(path):
    t = parse_bytes(path.read_bytes(), path.name)
    assert t.subject and t.nmck and t.submission_deadline and t.customer_inn
    assert t.delivery_region_code, t.delivery_place
    assert t.procedure_type != "other"
