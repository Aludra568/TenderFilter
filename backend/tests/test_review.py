from app.scoring import review as rv
from app.scoring.engine import evaluate
from tests.test_engine import COMPANY, NOW, prefs, tender


def scored(**kw):
    t = tender(**kw)
    return t, evaluate(t, COMPANY, None, prefs(), now=NOW).model_dump()


def fake(answer):
    return lambda system, user, schema, timeout: answer


def test_no_llm_keeps_algorithm():
    t, res = scored()
    r = rv.review(t, res, complete=fake(None))
    assert r.status == "unavailable" and r.final_verdict == res["verdict"] and not r.changed


def test_agree():
    t, res = scored()
    r = rv.review(t, res, complete=fake({"agree": True, "issues": []}))
    assert r.status == "agree" and r.final_verdict == "go"


def test_verified_objection_corrects_verdict_without_touching_score():
    t, res = scored(subject="Поставка ноутбуков с установкой и обучением персонала в течение 12 месяцев")
    ans = {"agree": False, "suggested_verdict": "consider",
           "issues": [{"factor": "profile", "problem": "Кроме поставки нужны обучение и сервис на год",
                       "quote": "обучением персонала в течение 12 месяцев"}]}
    r = rv.review(t, res, complete=fake(ans))
    assert r.status == "doubt" and r.changed and r.final_verdict == "consider"
    out = rv.apply(res, r)
    assert out["verdict"] == "consider" and out["score"] == res["score"]
    assert out["review"]["algorithm_verdict"] == "go"
    assert any("Проверка ИИ" in f for f in out["flags"])


def test_hallucinated_quote_is_ignored():
    t, res = scored()
    ans = {"agree": False, "issues": [{"factor": "geo", "problem": "Поставка на Камчатку",
                                       "quote": "доставка в Петропавловск-Камчатский"}]}
    r = rv.review(t, res, complete=fake(ans))
    assert r.status == "unconfirmed" and not r.changed and r.final_verdict == "go"
    assert r.issues[0].verified is False


def test_quote_from_criteria_counts():
    t, res = scored()
    ans = {"agree": False, "issues": [{"factor": "other", "problem": "Пользователь не работает с ноутбуками б/у",
                                       "quote": "б/у не берём"}]}
    r = rv.review(t, res, criteria_text="Ноутбуки, б/у не берём", complete=fake(ans))
    assert r.issues[0].verified and r.final_verdict == "consider"  # без мнения модели — на ступень ниже


def test_stop_factor_is_not_overridden():
    t, res = scored(smp_only=True)
    company_res = evaluate(t, COMPANY.model_copy(update={"is_msp": False}), None, prefs(), now=NOW).model_dump()
    assert company_res["stops"]
    ans = {"agree": False, "suggested_verdict": "go",
           "issues": [{"factor": "conditions", "problem": "Можно участвовать", "quote": "Поставка ноутбуков"}]}
    r = rv.review(t, company_res, complete=fake(ans))
    assert r.status == "doubt" and not r.changed and r.final_verdict == "skip"


def test_no_time_left_skips_llm():
    t, res = scored()
    called = []
    r = rv.review(t, res, timeout=0.1, complete=lambda *a: called.append(1))
    assert r.status == "unavailable" and not called


def test_quick_score_includes_review(client):
    from tests.conftest import SAMPLES

    path = next(SAMPLES.glob("real_44fz_ef2020_*.xml"))
    resp = client.post("/api/quick-score", files={"file": (path.name, path.read_bytes())},
                       data={"criteria_text": "Поставляем медицинские изделия", "save": "false"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["review"]["status"] == "unavailable"  # в тестах LLM отключена
    assert "review_ms" in body["timings"]


def test_correction_is_at_most_one_step():
    assert rv.corrected_verdict("go", "skip") == "consider"
    assert rv.corrected_verdict("skip", "go") == "consider"
    assert rv.corrected_verdict("consider", "go") == "go"
    assert rv.corrected_verdict("go", "go") == "go"
