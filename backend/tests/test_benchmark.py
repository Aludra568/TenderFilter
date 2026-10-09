from app.benchmark import run


def test_rules_dev_set_does_not_regress():
    assert run("rules", write=False)["phrase_accuracy"] >= 0.95


def test_rules_holdout_set():
    # Отложенный набор не используется для доработки правил — это честная оценка на новых формулировках.
    assert run("rules", write=False, dataset="phrases_holdout")["check_accuracy"] >= 0.85
