from app.scoring.engine import evaluate
from tests.test_engine import COMPANY, NOW, prefs, tender


def test_warehouse_region_counts_as_own():
    p = prefs()
    t = tender(delivery_region_code="24")  # Красноярский край — вне регионов профиля
    base = next(f for f in evaluate(t, COMPANY, None, p, now=NOW).factors if f.key == "geo")
    p.geo.warehouses = ["24"]
    geo = next(f for f in evaluate(t, COMPANY, None, p, now=NOW).factors if f.key == "geo")
    assert geo.score == 0.9 > (base.score or 0) and "склад" in geo.reasons[0]


def test_committed_guarantees_reduce_free_limit():
    p = prefs()
    p.finance.guarantee_limit_rub = 2_000_000
    t = tender(app_guarantee_amount=100_000, contract_guarantee_amount=400_000)
    free = next(f for f in evaluate(t, COMPANY, None, p, now=NOW).factors if f.key == "finance")
    busy = next(f for f in evaluate(t, COMPANY, None, p, now=NOW, committed=(1_800_000, 3)).factors if f.key == "finance")
    assert busy.score < free.score
    assert "свободном лимите" in busy.reasons[0] and "3 заявках" in busy.reasons[0]


def test_bid_api_changes_free_limit(client):
    feed = client.get("/api/feed?limit=50").json()["items"]
    tid = next(i["tender_id"] for i in feed if i["verdict"] != "skip")
    r = client.put(f"/api/tenders/{tid}/bid", json={"status": "won"})
    assert r.status_code == 200 and r.json()["status_name"].startswith("Выиграли")
    bids = client.get("/api/bids").json()
    assert bids["bids"][0]["tender_id"] == tid
    assert any(i["bid_status"] == "won" for i in client.get("/api/feed?limit=100").json()["items"])
    assert client.get(f"/api/tenders/{tid}").json()["bid_status"] == "won"
    client.put(f"/api/tenders/{tid}/bid", json={"status": None})
    assert client.get("/api/bids").json()["bids"] == []
