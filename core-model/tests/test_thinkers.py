"""Tur 26: düşünür yöntemleriyle problem çözme kolu (thinkers.py) — doğruluk, uydurma yok, çeşit, sınav dışı."""
import math
import random
import re
from collections import Counter

import pytest

from orion_core import dialogs, thinkers as T
from orion_core.cogexam import near_cogexam

N = 4000


@pytest.fixture(scope="module")
def samples():
    rng = random.Random(11)
    return [T.thinker_sample(rng) for _ in range(N)]


def _num(s):
    return float(s.replace(",", "."))


def test_mix_has_no_thinkers():
    assert dialogs.MIX == {"reasoning": 0.48, "thinkers": 0.0, "personality": 0.30, "memory": 0.12, "principled": 0.05, "route": 0.03, "legacy": 0.02}
    st: dict = {}
    d = dialogs.persona_dialogues(3000, seed=5, stats=st)
    sh = dialogs.mix_shares(st)
    assert sh.get("thinkers", 0) == 0, sh  # Tur 27: kol kapalı
    assert not any(T.thinker_of(x) for x in d)  # düşünür adları eğitim diyaloglarına girmez


def test_answers_correct(samples):
    for cat, turns, m in samples:
        (q, a), = turns
        k = m["kind"]
        if k == "maliyet":
            assert m["tot"] == sum(n * c for _, _, n, c in m["rows"]) and f"= {m['tot']} lira" in a
            if m["budget"]:
                assert ("yeter." in a) == (m["budget"] >= m["tot"])
        elif k == "plan":
            assert f"en geç {m['wake'] // 60}.{m['wake'] % 60:02d}" in a
        elif k in ("ariza", "kayip"):
            assert f"Geriye {m['answer']} kalıyor" in a
        elif k == "kural":
            assert ("gidebilirsin" in a) == m["open"]
        elif k == "kiyas":
            assert ("yani evet" in a) == m["valid"] and (("kesin bir sonuç çıkmaz" in a) != m["valid"])
        elif k == "indirim":
            old, new = map(int, re.search(r"Eski fiyatı (\d+) lira, şimdi (\d+) lira", q).groups())
            assert m["pct"] == pytest.approx((old - new) * 100 / old)
            assert f"yüzde {T.fmt(m['pct'])}" in a and ("Yazılan indirim doğru." in a) == m["ok"]
        elif k == "birim_fiyat":
            sg, sp, bg, bp = map(int, re.search(r"(\d+) gram (\d+) lira, (\d+) gram (\d+) lira", q).groups())
            assert (bp / bg < sp / sg) == m["big_cheaper"] and ("gerçekten büyük paket ucuz" in a) == m["big_cheaper"]
        elif k == "boya":
            assert m["litres"] == math.ceil(m["area"] / int(re.search(r"boya (\d+) metrekareye", q).group(1)) - 1e-9)
            assert f"en az {m['litres']} litre" in a
        elif k == "adim":
            st, n = map(int, re.search(r"adımım yaklaşık (\d+) santimetre.*?(\d+) adım", q).groups())
            assert m["m"] == st * n / 100 and f"{T.fmt(m['m'])} metre" in a
        elif k == "buyume":
            v = list(map(int, re.search(r"(\d+), (\d+), (\d+) santimetre", q).groups()))
            later = int(re.search(r"(\d+) gün sonra", q).group(1))
            assert m["pred"] == v[2] + later * (v[1] - v[0]) and f"= {m['pred']} santimetre" in a
        elif k == "golge":
            me, sh = map(int, re.search(r"Boyum (\d+) santimetre, gölgem (\d+)", q).groups())
            far = _num(re.search(r"gölgesi ([\d,]+) metre", q).group(1)) * 100
            assert m["h"] == pytest.approx(me * far / sh) and f"{T.fmt(m['h'] / 100)} metre" in a
        elif k == "capraz":
            assert f"{T.fmt(m['avg'])} kilometre" in a and str(m["outlier"]) in a
        elif k in ("denklem", "denklem2"):
            assert f"x = {m['x']}" in a
            if k == "denklem":
                aa, bb, cc = map(int, re.search(r"(\d+) katının (\d+) fazlası (\d+)", q).groups())
                assert aa * m["x"] + bb == cc
            else:
                g = re.search(r"(\d+)x \+ (\d+) = (\d*)x \+ (\d+)", q).groups()
                aa, bb, cc, dd = int(g[0]), int(g[1]), int(g[2] or 1), int(g[3])
                assert aa * m["x"] + bb == cc * m["x"] + dd
        elif k == "pay":
            tot = int(re.search(r"toplamı (\d+) lira", q).group(1))
            assert m["x"] + m["y"] == tot and f"{m['y']} lira" in a
        elif k == "olcum":
            assert f"{T.fmt(m['m1'])}" in a and f"{T.fmt(m['m2'])}" in a
            assert ("destekleniyor" in a) == m["real"]


YEAR = re.compile(r"\b\d{3,4}\s*(yılı|yılında|senesi|doğumlu)|yüzyıl|\bdoğdu\b|\böldü\b|\byaşadı\b|"
                  r"\bdemiş(tir)?\b|\bder ki\b|\bdediği gibi\b|\bsöylemiştir\b|\beserinde\b|\bkitabında\b", re.I)
QUOTE = re.compile(r"[\"“”«»„]")


def test_no_invented_biography_or_quotes(samples):
    for _, turns, _ in samples:
        for _, a in turns:
            assert not YEAR.search(a), a
            assert not QUOTE.search(a), a
            # düşünürün adı geçen cümlede hiç rakam yok (tarih/sayı uydurma riski sıfır)
            for sent in re.split(r"(?<=[.!?])\s+", a):
                if any(t in sent for t in T.THINKERS):
                    assert not re.search(r"\d", sent), sent
    for who, pool in T.INTRO.items():
        for s in pool:
            assert who in s and not re.search(r"\d", s) and not QUOTE.search(s)


def test_each_answer_names_one_method(samples):
    for _, turns, _ in samples:
        (_, a), = turns
        named = [t for t in T.THINKERS if t in a]
        assert len(named) == 1, a


def test_variety_and_balance(samples):
    by = Counter(T.thinker_of(t[0][1]) for _, t, _ in samples)
    assert set(by) == set(T.THINKERS)
    for who in T.THINKERS:
        assert 0.07 < by[who] / N < 0.2, by
    qs = {t[0][0] for _, t, _ in samples}
    ans = {t[0][1] for _, t, _ in samples}
    assert len(qs) > 0.65 * N and len(ans) > 0.75 * N
    assert len({c for c, _, _ in samples}) == len(T.WEIGHTS)


def test_health_no_medical_advice():
    rng = random.Random(3)
    for _ in range(300):
        _, turns, _ = T.thinker_sample(rng, "saglik")
        a = turns[0][1].lower()
        assert "doktora danış" in a and "teşhis koyamam" in a
        assert not re.search(r"\bilaç|\bmg\b|tablet|hap\b|ağrı kesici|antibiyotik|\bşurup", a), a
        assert "efendim" not in a


def test_efendim_rare(samples):
    n = sum("efendim" in t[0][1].lower() for _, t, _ in samples)
    assert 0 < n / N <= 0.2
    assert all(t[0][1].lower().count("efendim") <= 1 for _, t, _ in samples)


def test_exam_disjoint(samples):
    bad = sum(not dialogs._turns_ok(t) for _, t, _ in samples)
    assert bad < 0.05 * N
    st: dict = {}
    for x in dialogs.persona_dialogues(2000, seed=9, stats=st):
        if not T.thinker_of(x):
            continue
        for line in x.split("\n"):
            if line.startswith("Kullanıcı: "):
                q = line[len("Kullanıcı: "):]
                assert not dialogs.is_exam_question(q) and not dialogs.near_exam(q) and not near_cogexam(q)


def test_turkish_suffix_helper():
    assert [T.dat(n) for n in (2, 3, 4, 5, 6, 9, 10, 20)] == ["2'ye", "3'e", "4'e", "5'e", "6'ya", "9'a", "10'a", "20'ye"]
    assert T.fmt(2.5) == "2,5" and T.fmt(10.0) == "10" and T.fmt(10 / 3) == "3,33"
