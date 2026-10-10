from app.labeling import kappa


def test_kappa():
    assert kappa(["go", "skip", "consider"], ["go", "skip", "consider"]) == 1.0
    assert kappa(["go", "go", "skip", "skip"], ["go", "skip", "go", "skip"]) == 0.0
    assert 0 < kappa(["go", "go", "skip", "consider"], ["go", "go", "skip", "skip"]) < 1
