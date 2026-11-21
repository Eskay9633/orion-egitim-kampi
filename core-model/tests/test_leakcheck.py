from orion_core.leakcheck import check


def test_exact_and_near_counts():
    train = ["yarın takvimde ne var", "ışıkları hemen kapat lütfen şimdi", "bambaşka bir cümle burada"]
    sets = {"a": ["Yarın takvimde ne var?", "ışıkları hemen kapat lütfen", "hiç benzemeyen bir soru"]}
    r = check(train, sets)["a"]
    assert r["exact"] == 1
    # "ışıkları hemen kapat lütfen" ⊂ eğitim cümlesi: Jaccard 4/5 = 0.8 → yakın
    assert r["near"] == 2
    assert r["n"] == 3
