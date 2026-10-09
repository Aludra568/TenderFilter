import time

from app.config import get_settings
from app.egrul.providers import FnsProvider
from app.nlp import criteria, llm
from conftest import SAMPLES

REAL = SAMPLES / "real_44fz_ef2020_0173100008726000065.xml"


def test_fns_mapping_from_real_responses():
    # Формат ответов egrul.nalog.ru и rmsp.nalog.ru (снят с живых сервисов 08.10.2026).
    egrul_row = {"c": "ООО «РОМАШКА»", "n": "ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ «РОМАШКА»", "i": "4707048043",
                 "o": "1224700016750", "r": "10.10.2022", "rn": "ЛЕНИНГРАДСКАЯ ОБЛАСТЬ", "k": "ul"}
    msp_row = {"inn": "4707048043", "category": 1, "okved1": "35.22", "okved1name": "Распределение газообразного топлива"}
    card = FnsProvider.map("4707048043", egrul_row, msp_row)
    assert card.name == "ООО «РОМАШКА»" and card.status == "ACTIVE"
    assert card.is_msp is True and card.msp_category == "micro"
    assert card.okveds[0].code == "35.22"
    assert card.registration_date.year == 2022

    closed = FnsProvider.map("7707083893", {"c": "ПАО", "i": "7707083893", "e": "01.01.2025", "rn": "Г.Москва"}, {})
    assert closed.status == "LIQUIDATED" and closed.is_msp is False
    unknown = FnsProvider.map("7707083893", {"c": "ПАО", "i": "7707083893"}, None)
    assert unknown.is_msp is None


def test_quick_score_full_flow(client):
    started = time.perf_counter()
    r = client.post(
        "/api/quick-score",
        files={"file": ("notice.xml", REAL.read_bytes(), "application/xml")},
        data={"inn": "5406123450", "criteria_text": "Работаем в Москве. НМЦК до 150 млн. Поставляем ноутбуки. Аванс не важен."},
    )
    elapsed = time.perf_counter() - started
    assert r.status_code == 200, r.text
    body = r.json()
    assert elapsed < 10  # критерий ТЗ на всю цепочку
    assert body["company"]["inn"] == "5406123450"
    assert body["criteria"]["recognized"] and body["criteria"]["engine"].startswith("rules")
    assert body["result"]["verdict"] in ("go", "consider")
    assert set(body["timings"]) >= {"parse_ms", "egrul_ms", "criteria_ms", "scoring_ms", "total_ms"}
    assert body["tender_id"]


def test_quick_score_without_inn_uses_profile(client):
    r = client.post("/api/quick-score", files={"file": ("n.xml", REAL.read_bytes(), "application/xml")}, data={"save": "false"})
    assert r.status_code == 200 and r.json()["tender_id"] is None
    assert r.json()["company"]["inn"] == "5406123450"


def test_quick_score_bad_inn_and_unknown_inn(client):
    files = {"file": ("n.xml", REAL.read_bytes(), "application/xml")}
    assert client.post("/api/quick-score", files=files, data={"inn": "123"}).status_code == 400
    r = client.post("/api/quick-score", files=files, data={"inn": "7707083893"})
    assert r.status_code == 404 and "ИНН" in r.json()["detail"]


def test_audit_log(client):
    client.post("/api/quick-score", files={"file": ("n.xml", REAL.read_bytes(), "application/xml")}, data={"inn": "5406123450"})
    logs = client.get("/api/logs").json()
    events = {item["event"] for item in logs}
    assert {"quick_score", "egrul_lookup"} <= events
    quick = next(item for item in logs if item["event"] == "quick_score")
    assert quick["duration_ms"] is not None and quick["detail"]["timings"]["total_ms"] < 10_000


def test_unreachable_llm_does_not_block(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "ollama")
    monkeypatch.setattr(s, "ollama_url", "http://10.255.255.1:11434")  # недоступный адрес
    started = time.perf_counter()
    outcome = criteria.parse_criteria("НМЦК до 10 млн. Хотим работать с хорошими людьми.", timeout=1.0)
    assert time.perf_counter() - started < 5
    assert outcome.preferences.price.max_rub == 10e6 and outcome.engine.startswith("rules")


def test_llm_timeout_falls_back_to_rules(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "ollama")
    monkeypatch.setattr(s, "ollama_url", "http://10.255.255.1:11434")
    monkeypatch.setattr(llm, "provider_status", lambda timeout=1.5: {"ready": True})
    started = time.perf_counter()
    outcome = criteria.parse_criteria("НМЦК до 10 млн. Хотим работать с хорошими людьми.", timeout=1.0)
    assert time.perf_counter() - started < 4
    assert outcome.engine == "rules (LLM не ответила вовремя)"
    assert outcome.unparsed == ["Хотим работать с хорошими людьми"]
