import io
import time
import zipfile
from datetime import datetime, timedelta, timezone

from conftest import SAMPLES

from app.seed.demo import SPECS, notice_xml


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["queue"] == "in-process"


def test_seeded_feed(client):
    feed = client.get("/api/feed").json()
    assert feed["total"] >= 37
    assert sum(feed["counts"].values()) == feed["total"]
    first = feed["items"][0]
    assert first["verdict"] == "go" and first["main_reason"]


def test_feed_filters_and_search(client):
    go = client.get("/api/feed", params={"verdict": "go"}).json()
    assert all(i["verdict"] == "go" for i in go["items"])
    found = client.get("/api/feed", params={"q": "ноутбук"}).json()
    assert found["items"] and "ноутбук" in found["items"][0]["subject"].lower()


def test_company_lookup(client):
    assert client.get("/api/companies/5406123450").json()["is_msp"] is True
    assert client.get("/api/companies/1234567890").status_code == 400
    assert client.get("/api/companies/7707083893").status_code == 404


def test_upload_real_notice_and_get_card(client):
    content = (SAMPLES / "real_44fz_ef2020_0173100008726000065.xml").read_bytes()
    started = time.perf_counter()
    r = client.post("/api/tenders", files={"file": ("n.xml", content, "application/xml")})
    assert r.status_code == 200
    assert time.perf_counter() - started < 10  # ТЗ: скоринг < 10 с
    tid = r.json()["tender_id"]
    card = client.get(f"/api/tenders/{tid}").json()
    assert card["tender"]["purchase_number"] == "0173100008726000065"
    assert {f["key"] for f in card["result"]["factors"]} == {"profile", "price", "geo", "timing", "finance", "conditions", "customer"}
    assert card["similar"]


def test_upload_garbage_is_422(client):
    r = client.post("/api/tenders", files={"file": ("x.xml", b"<oops", "application/xml")})
    assert r.status_code == 422 and "XML" in r.json()["detail"]


def test_parse_text_then_save_new_version(client):
    profile = client.get("/api/profiles/1").json()
    parsed = client.post("/api/profiles/1/parse", json={"text": "Работаем только в Томской области. НМЦК до 5 млн."}).json()
    assert parsed["preferences"]["geo"]["regions"] == {"70": 1.0}
    saved = client.put("/api/profiles/1", json={"preferences": parsed["preferences"], "criteria_text": "тест"}).json()
    assert saved["version"] == profile["version"] + 1 and saved["rescored"] >= 37
    feed = client.get("/api/feed").json()
    assert feed["profile_version"] == saved["version"]
    # вернуть исходные настройки
    client.put("/api/profiles/1", json={"preferences": profile["preferences"], "criteria_text": profile["criteria_text"]})


def test_preview_does_not_save(client):
    profile = client.get("/api/profiles/1").json()
    prefs = profile["preferences"]
    prefs["conditions"]["methods"]["e_auction"] = "exclude"
    preview = client.post("/api/score/preview", json={"preferences": prefs}).json()
    assert sum(preview["counts"].values()) == preview["total"]
    assert client.get("/api/profiles/1").json()["version"] == profile["version"]


def test_batch_zip(client):
    now = datetime.now(timezone(timedelta(hours=3)))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for spec in SPECS[:5]:
            zf.writestr(f"dir/{spec.number}.xml", notice_xml(spec, now))
        zf.writestr("broken.xml", "<nope")
        zf.writestr("readme.txt", "skip me")
    r = client.post("/api/batches", files=[("files", ("pack.zip", buf.getvalue(), "application/zip"))]).json()
    assert r["total"] == 6
    for _ in range(100):
        b = client.get(f"/api/batches/{r['batch_id']}").json()
        if b["status"] == "done":
            break
        time.sleep(0.1)
    assert b["status"] == "done" and b["processed"] == 6 and b["failed"] == 1
    assert len(b["items"]) == 5 and b["errors"][0]["file"] == "broken.xml"


def test_export_xlsx_and_csv(client):
    x = client.get("/api/feed/export", params={"format": "xlsx"})
    assert x.status_code == 200 and x.content[:2] == b"PK"
    c = client.get("/api/feed/export", params={"format": "csv"})
    assert "Вердикт" in c.content.decode("utf-8-sig")


def test_feedback_and_accuracy(client):
    item = client.get("/api/feed").json()["items"][0]
    assert client.post(f"/api/scores/{item['score_id']}/feedback", json={"correct": True}).json()["ok"]
    acc = client.get("/api/accuracy").json()
    assert acc["feedback"]["total"] >= 1


def test_factors_schema_drives_ui(client):
    schema = client.get("/api/factors").json()
    assert [f["key"] for f in schema["factors"]] == ["profile", "price", "geo", "timing", "finance", "conditions", "customer"]
    assert len(schema["regions"]) >= 85
