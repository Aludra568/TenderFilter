import io
import zipfile
from datetime import datetime, timezone

import httpx
import pytest

from app.egrul import providers
from app.egrul.providers import CircuitBreaker, EgrulError, FnsProvider
from app.eis import getdocs
from app.scoring import ahp
from app.scoring.engine import evaluate
from tests.conftest import SAMPLES
from tests.test_engine import COMPANY, NOW, prefs, tender

KEYS = ["profile", "price", "geo", "timing", "finance", "conditions", "customer"]


# ---------- веса ----------

def test_roc_weights_sum_to_one_and_follow_order():
    w = ahp.roc_weights(KEYS)
    assert abs(sum(w.values()) - 1) < 1e-3
    assert list(w.values()) == sorted(w.values(), reverse=True)
    assert w["profile"] == pytest.approx(0.3704, abs=1e-4)


def test_ahp_consistent_answers():
    r = ahp.weights_from_pairs(["a", "b", "c"], [("a", "b", 2), ("b", "c", 3), ("a", "c", 6)])
    assert r["consistent"] and r["cr"] < 1e-6
    assert r["weights"]["a"] == pytest.approx(0.6, abs=1e-3)
    assert ahp.advise(r) == []


def test_ahp_inconsistency_points_to_contradicting_pair():
    r = ahp.weights_from_pairs(["a", "b", "c"], [("a", "b", 3), ("b", "c", 2), ("a", "c", 1 / 2)])
    assert not r["consistent"]
    tips = ahp.advise(r, {"a": "Профиль", "b": "Цена", "c": "География"})
    assert "противоречивы" in tips[0]
    # без ответа «Профиль vs Цена» остальные дают Профиль/Цена = (1/2)/2 = 1/4
    worst = next(p for p in r["worst_pairs"] if (p["a"], p["b"]) == ("a", "b"))
    assert worst["implied"] == pytest.approx(0.25, abs=1e-3)
    assert any("менее важно в 4 раза" in t for t in tips)


def test_explicit_weights_override_importance():
    p = prefs()
    base = evaluate(tender(nmck=40_000_000), COMPANY, None, p, now=NOW)
    p.weights = {k: (0.9 if k == "price" else 0.1 / 6) for k in KEYS}
    heavy_price = evaluate(tender(nmck=40_000_000), COMPANY, None, p, now=NOW)
    price = next(f for f in heavy_price.factors if f.key == "price")
    assert price.weight == pytest.approx(90)
    assert heavy_price.score < base.score


def test_weights_api(client):
    q = client.get("/api/weights/questions").json()
    assert len(q["pairs"]) >= len(KEYS) - 1
    roc = client.post("/api/weights", json={"method": "roc", "ranking": KEYS}).json()
    assert roc["weights"]["profile"] > roc["weights"]["customer"]
    pairs = [{"a": p["a"], "b": p["b"], "value": 1} for p in q["pairs"]]
    res = client.post("/api/weights", json={"method": "ahp", "pairs": pairs}).json()
    assert res["consistent"] and all(v == pytest.approx(1 / 7, abs=1e-3) for v in res["weights"].values())
    assert client.post("/api/weights", json={"method": "roc", "ranking": KEYS[:3]}).status_code == 422
    loose = [{"a": "profile", "b": "price", "value": 2}] * 6
    assert client.post("/api/weights", json={"method": "ahp", "pairs": loose}).status_code == 422


# ---------- ФНС: размыкатель ----------

def test_circuit_breaker_backoff_and_reset():
    b = CircuitBreaker(base=60, cap=200)
    b.check()
    b.failure("капча")
    with pytest.raises(EgrulError, match="капча"):
        b.check()
    first = b.open_until
    b.failure("HTTP 429")
    assert b.state()["failures"] == 2 and b.open_until > first
    b.success()
    b.check()
    assert not b.state()["open"]


def test_fns_captcha_opens_breaker(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        return httpx.Response(200, json={"captchaRequired": True})

    real_client = httpx.Client
    monkeypatch.setattr(providers.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(FnsProvider, "breaker", CircuitBreaker())
    fns = FnsProvider(timeout=1)
    with pytest.raises(EgrulError, match="капч"):
        fns.fetch("5406123450")
    n = len(calls)
    with pytest.raises(EgrulError, match="не опрашивается"):
        fns.fetch("5406123450")
    assert len(calls) == n  # второй запрос в сеть не ушёл


# ---------- ЕИС getDocsIP ----------

def test_getdocs_request_has_strict_order_and_token():
    xml = getdocs.build_request("0173100008726000065", "T<1>", request_id="id-1",
                                now=datetime(2026, 10, 9, 9, tzinfo=timezone.utc))
    assert "<individualPerson_token>T&lt;1&gt;</individualPerson_token>" in xml
    assert "<createDateTime>2026-10-09T12:00:00+03:00</createDateTime>" in xml
    order = [xml.index(t) for t in ("<id>", "<createDateTime>", "<mode>PROD", "<subsystemType>PRIZ", "<reestrNumber>")]
    assert order == sorted(order)


def test_getdocs_response_and_archive():
    ok = (b'<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>'
          b'<ns2:getDocsByReestrNumberResponse xmlns:ns2="x"><dataInfo><archiveUrl>https://int44/a.zip</archiveUrl>'
          b'</dataInfo></ns2:getDocsByReestrNumberResponse></soap:Body></soap:Envelope>')
    assert getdocs.parse_response(ok) == ["https://int44/a.zip"]
    fault = (b'<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body><soap:Fault>'
             b'<faultstring>Token is invalid</faultstring></soap:Fault></soap:Body></soap:Envelope>')
    with pytest.raises(getdocs.EisApiError, match="Token is invalid"):
        getdocs.parse_response(fault)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("sign.xml", "<x/>")
        zf.writestr("epNotificationEF2020_0173100008726000065.xml", (SAMPLES / "real_44fz_ef2020_0173100008726000065.xml").read_bytes())
    name, content = getdocs.pick_notice(buf.getvalue())
    assert name.startswith("epNotification") and content.startswith(b"<")


def test_by_number_without_token(client):
    r = client.post("/api/tenders/by-number", json={"reestr_number": "0173100008726000065"})
    assert r.status_code == 503 and "EIS_TOKEN" in r.json()["detail"]
    assert client.post("/api/tenders/by-number", json={"reestr_number": "123"}).status_code == 422


# ---------- нечёткая логика ----------

def test_time_left_has_no_cliff_at_minimum():
    from app.scoring import fuzzy

    just_below, at_min = fuzzy.time_left(2.9, 3).score, fuzzy.time_left(3.0, 3).score
    assert abs(at_min - just_below) < 0.05  # раньше здесь был обрыв 0,6 → 0,2
    assert fuzzy.time_left(10, 3).score == 1.0 and fuzzy.time_left(1, 3).score == pytest.approx(0.2)


def test_guarantee_load_terms():
    from app.scoring import fuzzy

    assert fuzzy.guarantee_load(0.3).dominant == "лёгкая"
    assert fuzzy.guarantee_load(0.8).score == pytest.approx(0.7)
    assert fuzzy.guarantee_load(2.0).score == 0.0


def test_borderline_price_explains_membership():
    r = evaluate(tender(nmck=12_500_000), COMPANY, None, prefs(), now=NOW)
    price = next(f for f in r.factors if f.key == "price")
    assert 0 < price.score < 1
    assert any("μ:" in x for x in price.reasons)


def test_fuzzy_curves_api(client):
    c = client.get("/api/fuzzy/curves").json()
    assert {"price", "time_left", "guarantee_load"} <= set(c)
    assert all(0 <= p["mu"] <= 1 for p in c["price"])


def test_fns_lookup_respects_total_budget(monkeypatch):
    import time

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"t": "token"})
        return httpx.Response(200, json={"status": "wait"})  # ФНС бесконечно «думает»

    real_client = httpx.Client
    monkeypatch.setattr(providers.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(FnsProvider, "breaker", CircuitBreaker())
    started = time.monotonic()
    with pytest.raises(EgrulError, match="не успел"):
        FnsProvider(timeout=1.0).fetch("5406123450")
    assert time.monotonic() - started < 1.6
