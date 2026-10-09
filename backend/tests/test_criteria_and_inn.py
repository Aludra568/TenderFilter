import pytest

from app.egrul.inn import is_valid_inn
from app.nlp.criteria import parse_rules
from app.reference.regions import find_regions


@pytest.mark.parametrize("inn,ok", [("7702166610", True), ("7702166611", False), ("5406123450", True),
                                    ("123", False), ("abcdefghij", False), ("500100732259", True)])
def test_inn_checksum(inn, ok):
    assert is_valid_inn(inn) is ok


@pytest.mark.parametrize("text,codes", [
    ("в Москве и Московской области", {"77", "50"}),
    ("Новосибирская обл., г. Новосибирск", {"54"}),
    ("г. Томск", {"70"}),
    ("Кемеровская область — Кузбасс", {"42"}),
    ("Ханты-Мансийский автономный округ — Югра, г. Сургут", {"86"}),
    ("Кировский район г. Новосибирска", {"54"}),
])
def test_region_detection(text, codes):
    assert {r.code for r in find_regions(text)} == codes


def test_full_criteria_text():
    o = parse_rules(
        "Работаем в Новосибирской и Томской областях, в Алтайском крае — если выгодно. НМЦК от 1 до 30 млн. "
        "На обеспечения готовы отвлечь не больше 1 млн. На заявку нужно минимум 3 дня. Конкурсы не любим. "
        "Аванс важен. Поставляем ноутбуки, серверы и МФУ."
    )
    p = o.preferences
    assert p.geo.regions == {"54": 1.0, "70": 1.0, "22": 0.5}
    assert (p.price.min_rub, p.price.max_rub) == (1e6, 30e6)
    assert p.finance.guarantee_limit_rub == 1e6
    assert p.timing.min_days_to_deadline == 3 and p.timing.required
    assert p.conditions.methods["open_contest"] == "neutral"
    assert p.conditions.methods["e_auction"] == "prefer"
    assert p.finance.advance == "want"
    assert {"ноутбуки", "серверы", "мфу"} <= set(p.profile.keywords)
    assert o.unparsed == []
    assert all(r.source_text for r in o.recognized)


@pytest.mark.parametrize("text,check", [
    ("Работаем по всей Сибири, кроме Тывы", lambda p: "17" in p.geo.excluded and "54" in p.geo.regions),
    ("Конкурсы не берём, предпочитаем аукционы",
     lambda p: p.conditions.methods == {"open_contest": "exclude", "e_auction": "prefer"}),
    ("Аванс обязателен", lambda p: p.finance.advance == "must"),
    ("Контракты до 5 лямов", lambda p: p.price.max_rub == 5e6),
    ("Работаем только по 44-ФЗ", lambda p: p.conditions.laws == ["44-FZ"]),
    ("Не работаем с заказчиком ИНН 7702166610", lambda p: p.customer.excluded_inns == ["7702166610"]),
    ("Срок исполнения не менее 20 дней", lambda p: p.timing.min_contract_days == 20),
])
def test_phrases(text, check):
    assert check(parse_rules(text).preferences)


def test_unparsed_is_reported():
    o = parse_rules("НМЦК до 10 млн. Хотим работать с хорошими людьми.")
    assert o.unparsed == ["Хотим работать с хорошими людьми"]


def test_warehouses_from_text():
    from app.nlp.criteria import parse_criteria

    o = parse_criteria("Работаем в Новосибирской области. Есть склад в Красноярске и филиал в Томске.", use_llm=False)
    assert o.preferences.geo.regions == {"54": 1.0}
    assert set(o.preferences.geo.warehouses) == {"24", "70"}
