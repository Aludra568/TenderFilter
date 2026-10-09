"""Файл жюри не должен ронять систему: на любой мусор — понятная ошибка 4xx, а не 500."""

import json
from pathlib import Path

import pytest

SAMPLE = next((Path(__file__).resolve().parents[1] / "samples").glob("real_44fz_ef2020_*.xml")).read_bytes()

BOMB = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">]>
<epNotificationEF2020><commonInfo><purchaseNumber>&lol3;</purchaseNumber></commonInfo></epNotificationEF2020>"""
XXE = b"""<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>
<epNotificationEF2020><commonInfo><purchaseNumber>1</purchaseNumber><purchaseObjectInfo>&e;</purchaseObjectInfo></commonInfo></epNotificationEF2020>"""

CASES = {
    "garbage.xml": b"\x00\x01\x02 not xml at all \xff\xfe",
    "truncated.xml": SAMPLE[: len(SAMPLE) // 2],
    "other_schema.xml": b"<?xml version='1.0'?><catalog><book>1</book></catalog>",
    "empty_root.xml": b"<?xml version='1.0'?><epNotificationEF2020/>",
    "bomb.xml": BOMB,
    "xxe.xml": XXE,
    "array.json": b"[1, 2, 3]",
    "broken.json": b'{"purchaseNumber": ',
    "cp1251.xml": SAMPLE.decode("utf-8").replace('encoding="UTF-8"', 'encoding="windows-1251"').encode("cp1251", errors="replace"),
    "picture.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
}


@pytest.mark.parametrize("name", CASES)
@pytest.mark.parametrize("endpoint", ["/api/tenders", "/api/quick-score", "/api/customer/check", "/api/tenders/parse"])
def test_bad_files_never_500(client, endpoint, name):
    r = client.post(endpoint, files={"file": (name, CASES[name])}, data={"save": "false"} if "quick" in endpoint else None)
    assert r.status_code < 500, (endpoint, name, r.text[:300])
    if r.status_code >= 400:
        detail = r.json()["detail"]
        assert isinstance(detail, str) and len(detail) > 5  # человеку понятно, что не так
    if name == "xxe.xml" and r.status_code == 200:
        assert "root:" not in json.dumps(r.json(), ensure_ascii=False)


def test_cp1251_notice_is_parsed(client):
    r = client.post("/api/tenders/parse", files={"file": ("cp1251.xml", CASES["cp1251.xml"])})
    assert r.status_code == 200 and r.json()["nmck"]


def test_empty_and_oversized(client, monkeypatch):
    assert client.post("/api/tenders", files={"file": ("e.xml", b"   ")}).status_code == 400
    from app import api

    monkeypatch.setattr(api.settings, "max_upload_mb", 0.001)
    assert client.post("/api/tenders", files={"file": ("big.xml", SAMPLE)}).status_code == 413


@pytest.mark.parametrize("doc", [("scan.pdf", b"%PDF-1.4 broken"), ("x.docx", b"PK\x03\x04junk"), ("a.rtf", b"{\rtf1}")])
def test_bad_documents_never_500(client, doc):
    r = client.post("/api/quick-score", files=[("file", ("n.xml", SAMPLE)), ("documents", doc)], data={"save": "false"})
    assert r.status_code == 200, r.text[:300]
    assert any(f["code"] in ("unreadable", "no_text") for f in r.json()["tender"]["contract"]["findings"])
