"""Tur 24: daha çok ve daha çeşitli kişilik + akıl yürütme verisi.
- akıl yürütme: yeni kolların her cevabı girdilerden BAĞIMSIZ olarak yeniden hesaplanır (5000 örnek)
- çeşitlilik eşikleri (20 000 örnekte farklı cevap oranı), yeni kategorilerin kuralları
- sınav ayrıklığı: bilişsel sınav maddeleriyle sözcük Jaccard < 0.5, near_cogexam yok; karışım payları değişmedi."""
import random
import re

from orion_core import cogexam, dialogs, personality as P, reasoning as R

_EQ = re.compile(r"(\d+) ([×÷+−]) (\d+)(?: \+ (\d+))? = (\d+)")
NEW_R = list(R._GEN_META)
NEW_P = ["kendi", "takilma", "cesaret", "iyi_haber", "kotu_haber", "hatirlama", "fikir_sor", "itiraz", "hobi", "saat"]


def _hm(t):
    t %= 24 * 60
    return f"{t // 60}.{t % 60:02d}"


def _chain_order(q):
    """Sorudaki "X, Y'den daha ..." cümlelerinden sıralamayı kendimiz kurarız."""
    pairs = re.findall(r"(\w+), (\w+)'(?:dan|den|tan|ten) ", q)
    big = {a for a, _ in pairs} | {b for _, b in pairs}
    nxt = dict(pairs)
    top = next(x for x in big if x not in nxt.values())
    order = [top]
    while order[-1] in nxt:
        order.append(nxt[order[-1]])
    assert len(order) == len(big)
    return order


def _expected(meta, users):
    k = meta["kind"]
    if k == "zincir":
        order = _chain_order(users[-1])
        assert order == meta["order"]
        return order[0] if meta["ask"] == "top" else order[-1]
    if k == "sirala":
        vals, names, unit = meta["vals"], meta["names"], meta["unit"]
        for v in vals:
            assert str(v) in users[-1]
        if meta["mode"] == 0:
            return f"{max(vals) - min(vals)} {unit}"
        if meta["mode"] == 1:
            v = vals[names.index(meta["tgt"])]
            return f"{1 + sum(x > v for x in vals)}. sırada"
        return f"toplam {sum(vals)} {unit}"
    if k == "egerise":
        return {"mp": "evet", "mt": "hayır", "da": "söylenemez", "ac": "söylenemez"}[meta["case"]]
    if k == "yaya":
        left = [o for o in meta["opts"] if o not in meta["no"]]
        assert len(left) == 1
        return left[0]
    if k == "haric":
        for n in meta["names"]:
            assert n in users[-1]
        return f"{len(meta['names']) - len(meta['absent'])} kişi"
    if k == "bitis":
        assert str(meta["dur"]) in users[-1]
        return _hm(meta["start"] + meta["dur"])
    if k == "dakika":
        return f"{meta['h'] * 60 + meta['m']} dakika"
    if k == "gun":
        return f"{meta['len1'] - meta['d1'] + meta['d2']} gün"
    if k == "hesap":
        common = meta["total"] - meta["extra"]
        assert common % meta["n"] == 0
        return f"{common // meta['n']} lira"
    if k == "yuzde":
        part = meta["s"] * meta["pct"] / 100
        assert part == int(part)
        return f"{int(meta['s'] + part) if meta['up'] else int(part)} lira"
    if k == "haftalik":
        t = meta["d"] * meta["m"]
        return f"{t // 60} saat {t % 60} dakika" if t % 60 else f"{t // 60} saat"
    if k == "ustu":
        c = meta["pay"] - meta["n1"] * meta["p1"] - meta["n2"] * meta["p2"]
        assert c >= 0
        return f"{c} lira"
    if k == "hafta":
        need = meta["price"] - meta["have"]
        assert need > 0 and need % meta["w"] == 0
        return f"{need // meta['w']} hafta"
    if k == "geri":
        return _hm(meta["arrive"] - meta["prep"] - meta["cook"])
    if k == "su":
        assert meta["lt"] % meta["g"] == 0
        return f"{meta['lt'] // meta['g'] - meta['drank']} bardak"
    if k == "sayfa":
        rest = meta["total"] - meta["read"]
        assert rest % meta["days"] == 0
        return f"{rest // meta['days']} sayfa"
    if k == "toplam":
        return "tutarlı" if meta["n1"] + meta["n2"] == meta["tot"] else "çelişki"
    if k == "cuzdan":
        return "doğru" if meta["have"] - meta["spent"] == meta["left"] else "tutarsızlık"
    if k == "saat":
        return "çakışıyor" if meta["h1"] == meta["h2"] else "uygun"
    if k == "nobet":
        ppl, i = meta["ppl"], 0
        for _ in range(meta["d"]):  # pazartesiden gün gün ilerle
            i = (i + 1) % len(ppl)
        return f"sıra {ppl[i]}"
    if k == "kisa":
        return " → ".join(j for j, _ in sorted(meta["jobs"], key=lambda x: x[1]))
    if k == "harclik":
        return f"{meta['mult'] * (meta['y1'] + meta['y2'])} lira"
    if k == "puan":
        p = meta["d"] * meta["x"] - meta["w"] * meta["y"]
        assert p >= 0
        return f"{p} puan"
    if k == "iki_bilgi":
        return f"{meta['tgt']} {dict(meta['pairs'])[meta['tgt']]}"
    if k == "guncel":
        return f"saat {meta['h2']}.00"
    if k == "liste":
        n = meta["n"]
        return f"{sum(n)} parça" if "Toplam" in meta["q"] else f"{meta['items'][1]} {n[1]} tane"
    raise AssertionError(k)


def test_new_reasoning_answers_independently_correct():
    rng = random.Random(2024)
    kinds = {}
    for i in range(5000):
        cat = NEW_R[i % len(NEW_R)]
        c, turns, meta = R.reasoning_sample(rng, cat)
        assert c == cat and meta is not None
        users = [q for q, _ in turns]
        final = turns[-1][1]
        exp = _expected(meta, users)
        assert exp in final, (exp, turns)
        kinds[meta["kind"]] = kinds.get(meta["kind"], 0) + 1
        for _, a in turns:  # her eşitlik tek işlem ve doğru
            for m in _EQ.finditer(a):
                x, op, y, z, r = m.groups()
                x, y, r = int(x), int(y), int(r)
                v = {"×": lambda: x * y, "÷": lambda: x / y, "+": lambda: x + y + int(z or 0), "−": lambda: x - y}[op]()
                assert v == r, a
        # kısa akıl yürütme gösterilir: adım + sonuç bağlacı
        assert final.startswith(tuple(R.FIRST)) and any(f". {s} " in final for s in R.SO), final
    assert len(kinds) >= 24 and min(kinds.values()) > 40, kinds


def test_reasoning_consistent_cases_both_ways():
    """Sayısal çelişki kolu yalnızca 'çelişki' demeyi öğretmez: tutarlı örnekler de var."""
    rng = random.Random(7)
    seen = set()
    for _ in range(1500):
        _, _, m = R.reasoning_sample(rng, "celiski_sayi")
        seen.add(_expected(m, ["x"]))
    assert {"tutarlı", "çelişki", "doğru", "tutarsızlık", "uygun", "çakışıyor"} <= seen


def _ratio(fn, n=20000, seed=1):
    rng = random.Random(seed)
    ans = [a for _ in range(n) for _, a in fn(rng)[1]]
    return len(set(ans)) / len(ans)


def test_variety_thresholds():
    # Tur 23 ölçümü (20k örnek, tüm cevaplar): kişilik 0.186, akıl yürütme 0.216
    assert _ratio(P.personality_turns) >= 0.35
    assert _ratio(R.reasoning_turns) >= 0.40
    rng = random.Random(3)
    for cat in NEW_P:
        ans = [a for _ in range(1500) for _, a in P.personality_turns(rng, cat)[1]]
        assert len(set(ans)) > 120, (cat, len(set(ans)))
    for cat in NEW_R:
        ans = [a for _ in range(1500) for _, a in R.reasoning_turns(rng, cat)[1]]
        assert len(set(ans)) > 300, (cat, len(set(ans)))


def _exam_toks():
    out = []
    for it in cogexam.load_items():
        for t in it["turns"]:
            tk = dialogs._near_toks(t)
            if tk:
                out.append((t, tk))
    return out


def test_new_generators_exam_disjoint_jaccard():
    exam = _exam_toks()
    rng = random.Random(99)
    users = []
    for i in range(5000):
        users += [q for q, _ in R.reasoning_sample(rng, NEW_R[i % len(NEW_R)])[1]]
    for i in range(3000):
        users += [q for q, _ in P.personality_turns(rng, NEW_P[i % len(NEW_P)])[1]]
    for q in set(users):
        t = dialogs._near_toks(q)
        assert not cogexam.near_cogexam(q) and not dialogs.is_exam_question(q), q
        if len(t) < 2:
            continue
        for e, et in exam:
            j = len(t & et) / len(t | et)
            assert j < 0.5, (q, e, j)


def test_new_names_not_from_exam():
    exam = {w for it in cogexam.load_items() for t in it["turns"] for w in dialogs.fold(t).split()}
    names = {n for n, _, _ in R.NAMES2} | set(P.FRIENDS)
    assert not {dialogs.fold(n) for n in names} & exam


def test_personality_new_rules():
    rng = random.Random(5)
    for _ in range(1500):
        t = P.disagree_turns(rng)
        assert "karar senin" in t[0][1].lower(), t  # nazik itiraz: gerekçe + son söz sahibinde
        assert any(w in t[0][1] for w in ("Çünkü", "Sebebi şu", ".")), t
    # kendi tercihleri tutarlı: aynı soruya hep aynı seçim (soru metni yalnızca bir maddeye ait)
    for _ in range(3000):
        (q, a), *_ = P.own_turns(rng)
        own = [o for o in P.OWN2 if any(dialogs.fold(q).endswith(dialogs.fold(x)[1:]) for x in o[0])]
        assert len(own) == 1, q
        assert any(p in a for p in own[0][1]), (q, a)
    # espriler tekrarsız; aynı diyalogda aynı espri iki kez yok
    assert len(P.JOKES) == len(set(P.JOKES)) >= 39
    for _ in range(3000):
        js = [j for _, a in P.joke_turns(rng) for j in P.JOKES if j in a]
        assert len(js) == len(set(js)), js
    # hatırlama: üçüncü turda baştaki ad kullanılır
    for _ in range(1000):
        t = P.recall_turns(rng)
        name = next(n for n in P.FRIENDS if n in t[0][0])
        assert name in t[-1][1], t
    # kötü haberde espri ve "efendim" yok
    for _ in range(1000):
        a = P.personality_turns(rng, "kotu_haber")[1][0][1]
        assert "efendim" not in a.lower() and not any(j in a for j in P.JOKES)


def test_shares_and_weights_unchanged():
    assert dialogs.MIX == {"personality": 0.35, "memory": 0.10, "principled": 0.10, "reasoning": 0.35, "route": 0.05,
                           "legacy": 0.05}
    assert set(NEW_P) <= set(P.WEIGHTS) and set(NEW_R) <= set(R.WEIGHTS)
    assert abs(sum(P.WEIGHTS.values()) - 1) < 1e-9 and abs(sum(R.WEIGHTS.values()) - 1) < 1e-9


def test_reasoning_sample_deterministic():
    r1, r2 = random.Random(5), random.Random(5)
    assert [R.reasoning_sample(r1) for _ in range(500)] == [R.reasoning_sample(r2) for _ in range(500)]
