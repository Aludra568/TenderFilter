from datetime import datetime, timedelta, timezone

from app.domain import CanonicalTender, CompanyCard, CustomRule, OkvedEntry, Preferences
from app.evaluation import run
from app.scoring.engine import evaluate

NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
COMPANY = CompanyCard(inn="5406123450", name="Демо", status="ACTIVE", region_code="54", is_msp=True,
                      okveds=[OkvedEntry(code="46.51", main=True)])


def tender(**kw) -> CanonicalTender:
    base = dict(purchase_number="1", law="44-FZ", procedure_type="e_auction", subject="Поставка ноутбуков",
                nmck=2_000_000, delivery_region_code="54", submission_deadline=NOW + timedelta(days=8),
                okpd2=["26.20.11.110"], smp_only=False, contract_guarantee_percent=5, contract_guarantee_amount=100_000)
    base.update(kw)
    return CanonicalTender(**base)


def prefs(**kw) -> Preferences:
    p = Preferences()
    p.price.min_rub, p.price.max_rub = 500_000, 10_000_000
    p.geo.regions = {"54": 1.0}
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def test_ideal_tender_is_go_and_fast():
    r = evaluate(tender(), COMPANY, None, prefs(), now=NOW)
    assert r.verdict == "go" and r.score >= 75
    assert r.elapsed_ms < 10_000  # ТЗ: < 10 секунд; на деле доли миллисекунды
    assert sum(f.points for f in r.factors) == __import__("pytest").approx(r.score, abs=0.5)


def test_every_factor_explains_itself():
    r = evaluate(tender(), COMPANY, None, prefs(), now=NOW)
    for f in r.factors:
        assert f.reasons, f.key


def test_expired_deadline_is_hard_stop():
    r = evaluate(tender(submission_deadline=NOW - timedelta(hours=1)), COMPANY, None, prefs(), now=NOW)
    assert r.verdict == "skip" and "истёк" in r.stops[0]


def test_smp_only_for_non_msp_company_is_stop():
    company = COMPANY.model_copy(update={"is_msp": False})
    r = evaluate(tender(smp_only=True), company, None, prefs(), now=NOW)
    assert r.verdict == "skip" and "СМП" in r.stops[0]


def test_off_profile_is_stop():
    r = evaluate(tender(subject="Поставка молока", okpd2=["10.51.11.110"]), COMPANY, None, prefs(), now=NOW)
    assert r.verdict == "skip" and "профил" in r.main_reason


def test_missing_data_is_decided_automatically_but_never_go():
    t = tender(nmck=None, submission_deadline=None, delivery_region_code=None)
    r = evaluate(t, COMPANY, None, prefs(), now=NOW)
    assert r.completeness < 0.7 and r.verdict == "consider"
    assert any("Мало данных" in f for f in r.flags)
    assert r.score > 0  # процент считается по найденным данным


def test_liquidating_customer_caps_verdict():
    customer = CompanyCard(inn="5406987651", name="Заказчик", status="LIQUIDATING")
    r = evaluate(tender(customer_inn="5406987651"), COMPANY, customer, prefs(), now=NOW)
    assert r.verdict == "consider" and r.flags


def test_importance_zero_disables_factor():
    p = prefs()
    p.geo.importance = 0
    r = evaluate(tender(delivery_region_code="49"), COMPANY, None, p, now=NOW)
    geo = next(f for f in r.factors if f.key == "geo")
    assert geo.weight == 0 and r.verdict == "go"


def test_custom_rule_without_code_change():
    p = prefs()
    p.custom_rules = [CustomRule(id="r1", label="Не берём закупки дороже 1,5 млн", field="nmck", op="gt",
                                 value=1_500_000, mode="stop")]
    r = evaluate(tender(), COMPANY, None, p, now=NOW)
    assert r.verdict == "skip" and r.stops == ["Не берём закупки дороже 1,5 млн"]


def test_deterministic():
    a = evaluate(tender(), COMPANY, None, prefs(), now=NOW)
    b = evaluate(tender(), COMPANY, None, prefs(), now=NOW)
    assert a.model_dump(exclude={"elapsed_ms"}) == b.model_dump(exclude={"elapsed_ms"})


def test_golden_set_accuracy():
    report = run(write=False)
    assert report["accuracy"] >= 0.8  # критерий ТЗ
    assert report["critical_errors"] == 0
