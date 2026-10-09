def test_learning_needs_labels_then_suggests(client):
    r = client.get("/api/learning/suggest").json()
    if not r["enough"]:
        assert "Нужно хотя бы" in r["message"]
    items = client.get("/api/feed?limit=100").json()["items"]
    go = [i for i in items if i["verdict"] == "go"][:4]
    # Пользователь считает, что все эти «Участвовать» на самом деле «Рассмотреть» — система должна это уловить.
    for i in go:
        client.post(f"/api/scores/{i['score_id']}/feedback", json={"correct": False, "expected_verdict": "consider"})
    r = client.get("/api/learning/suggest").json()
    assert r["enough"] and r["labels"] >= 4
    assert r["steps"] and r["preferences"] and r["suggested"] > r["baseline"], r
