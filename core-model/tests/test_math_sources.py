"""Matematik kaynakları: AQuA-RAT, SVAMP, MATH ayrıştırıcıları; OpenStax uzun metin; DeepMind üretici şablonları."""
import gzip
import io
import json
import tarfile
from pathlib import Path

import pytest

from orion_core import chat, translate_data as td
from orion_core.corpus import dmmath, openstax

APACHE = "Apache License\n                           Version 2.0, January 2004\n\n   TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION\n"
MIT = "MIT License\n\nCopyright (c) 2021\n\nPermission is hereby granted, free of charge, to any person obtaining a copy"

AQUA = [
    {"question": "A shop sells 12 pens for $36. How much does one pen cost?", "options": ["A)2", "B)3", "C)4", "D)5", "E)6"],
     "rationale": "The price of one pen is the total cost divided by the number of pens, so it is 36/12 = 3 dollars.\nAnswer: B", "correct": "B"},
    {"question": "Which word is a noun?", "options": ["A)run", "B)cat"], "rationale": "cat\nAnswer B", "correct": "B"},
    {"question": "What is 2+2?", "options": ["A)4", "B)5"], "rationale": "Option A is right.", "correct": "A"},
]
SVAMP = [{"ID": "chal-1", "Body": "Jack had 8 pens. He gave 3 pens to his friend.", "Question": "How many pens does Jack have now?",
          "Equation": "( 8.0 - 3.0 )", "Answer": 5.0, "Type": "Subtraction"}]
MATH_ROWS = [
    {"problem": "What is $\\frac{1}{2}$ of 10?", "level": "Level 1", "type": "Prealgebra",
     "solution": "Half of 10 is $\\frac{10}{2} = 5$. So the answer is $\\boxed{5}$."},
    {"problem": "Compute $\\int_0^1 x\\,dx$.", "level": "Level 2", "type": "Calculus",
     "solution": "It is $\\boxed{\\frac{1}{2}}$."},
    {"problem": "Hard one with 3 apples.", "level": "Level 5", "type": "Algebra", "solution": "$\\boxed{3}$"},
    {"problem": "Draw [asy] draw((0,0)); [/asy] How many sides?", "level": "Level 1", "type": "Geometry",
     "solution": "$\\boxed{4}$"},
]


def test_new_math_sources_are_opt_in_and_pinned():
    for n in ("aqua-rat", "svamp", "math"):
        s = td.SOURCES[n]
        assert s.get("math") and n not in td.DEFAULT_SOURCES
        assert not any(x in s["url"] for x in ("test", "dev.json"))
    assert set(td.DEFAULT_SOURCES) == {"oasst2", "dolly", "hh-rlhf", "helpsteer2", "gsm8k"}
    assert td.license_of_text(APACHE) == "apache-2.0" and td.license_of_text(MIT) == "mit"
    assert td.license_of_text("Apache License\nVersion 2.0") is None   # kırpılmış metin tanınmaz


def test_parsers():
    (q, a), = td.parse_aqua(AQUA)[0]
    steps, final = a.rsplit(td.MATH_SEP, 1)
    assert final == "3" and "36 lira" in q and "Answer" not in steps and len(td.parse_aqua(AQUA)) == 1
    (q, a), = td.parse_svamp(SVAMP)[0]
    assert q.startswith("Jack had 8 pens.") and a == "We compute 8 - 3 = 5." + td.MATH_SEP + "5"
    m = td.parse_math(MATH_ROWS)
    assert len(m) == 1
    (q, a), = m[0]
    assert q == "What is 1/2 of 10?" and a.endswith(td.MATH_SEP + "5") and "\\" not in a and "$" not in a
    assert td.delatex("$x^{2} \\cdot 3 \\le 5$") == "x^2 × 3 ≤ 5" and td.delatex("\\begin{align}x\\end{align}") is None


class UrlHub:
    def __init__(self, root, payloads, licenses):
        self.root, self.p, self.lic, self.fetched = Path(root), payloads, licenses, []

    def text(self, url):
        return self.lic[url]

    def info(self, repo, kind="datasets"):
        return {"cardData": {"license": "cc-by-4.0"}, "sha": "x"}

    def fetch(self, url, sha256):
        self.fetched.append(url)
        p = self.root / Path(url).name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(self.p[url])
        return p


def math_tar() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for name, row in [("MATH/train/prealgebra/1.json", MATH_ROWS[0]),
                          ("MATH/test/prealgebra/9.json", dict(MATH_ROWS[0], problem="TEST What is 3 of 3?"))]:
            b = json.dumps(row).encode()
            ti = tarfile.TarInfo(name)
            ti.size = len(b)
            t.addfile(ti, io.BytesIO(b))
    return buf.getvalue()


def test_collect_requires_pinned_sha_then_reads_train_only(tmp_path, monkeypatch):
    S = td.SOURCES
    payloads = {S["aqua-rat"]["url"]: "\n".join(json.dumps(r) for r in AQUA).encode(),
                S["svamp"]["url"]: json.dumps(SVAMP).encode(), S["math"]["url"]: math_tar()}
    lic = {S["aqua-rat"]["license_url"]: APACHE, S["svamp"]["license_url"]: MIT, S["math"]["license_url"]: MIT}
    hub = UrlHub(tmp_path / "h", payloads, lic)
    # sha256 sabitlenmemiş: indirilmez, "alınamadı" raporlanır (lisans kapısı yine geçer)
    with pytest.raises(RuntimeError, match="hiçbir kaynaktan"):
        td.collect(["aqua-rat", "svamp", "math"], 100, tmp_path / "c0", hub=hub)
    assert hub.fetched == []
    for n in ("aqua-rat", "svamp", "math"):
        monkeypatch.setitem(td.SOURCES[n], "sha256", "0" * 64)
    st = td.collect(["aqua-rat", "svamp", "math"], 100, tmp_path / "c", n_shards=1, hub=hub)
    rows = [json.loads(l) for l in open(tmp_path / "c" / "shard-00.jsonl")]
    assert st["kaynak"]["math"]["kalan"] == 1 and not any("TEST" in r["turns"][0][0] for r in rows)
    assert {r["final"] for r in rows} == {"3", "5"} and all(r.get("final") for r in rows)
    lics = {r["source"]: r["license"] for r in rows}
    assert lics["google-deepmind/AQuA"] == "apache-2.0" and lics["arkilpatel/SVAMP"] == "mit"


# --------------------------------------------------------------------------- OpenStax

CNXML = """<document xmlns="http://cnx.rice.edu/cnxml" xmlns:m="http://www.w3.org/1998/Math/MathML"><title>{t}</title><content>
<section><title>Add Whole Numbers</title>
<para>To add two whole numbers, line up the digits by place value and add each column.</para>
<para>The sum of <m:math><m:mn>3</m:mn><m:mo>+</m:mo><m:mn>4</m:mn></m:math> is seven, which we write as a number.</para>
<example><para>Add <m:math><m:mfrac><m:mn>1</m:mn><m:mn>2</m:mn></m:mfrac></m:math> and one half to get one whole number.</para></example>
<figure><media><image src="x.png"/></media><caption>A picture caption that should be skipped here.</caption></figure>
<exercise><problem><para>Find the sum of 12 and 30 using the column method shown above.</para></problem>
<solution><para>The sum of 12 and 30 is 42, as the columns show clearly.</para></solution></exercise>
</section></content></document>"""
COLL = """<col:collection xmlns:col="http://cnx.rice.edu/collxml" xmlns:md="http://cnx.rice.edu/mdml"><col:metadata>
<md:title>{title}</md:title><md:license url="{lic}">x</md:license><md:slug>{slug}</md:slug></col:metadata>
<col:content><col:module document="{mod}"/></col:content></col:collection>"""


def openstax_tar(path: Path):
    files = {"r/collections/prealgebra.collection.xml": COLL.format(title="Prealgebra 2e", slug="prealgebra-2e", mod="m1",
                                                                    lic="http://creativecommons.org/licenses/by/4.0/"),
             "r/collections/calculus.collection.xml": COLL.format(title="Calculus Volume 1", slug="calculus-volume-1", mod="m2",
                                                                  lic="http://creativecommons.org/licenses/by-nc-sa/4.0/"),
             "r/modules/m1/index.cnxml": CNXML.format(t="Introduction to Whole Numbers"),
             "r/modules/m2/index.cnxml": CNXML.format(t="Limits")}
    with tarfile.open(path, "w:gz") as t:
        for n, s in files.items():
            b = s.encode()
            ti = tarfile.TarInfo(n)
            ti.size = len(b)
            t.addfile(ti, io.BytesIO(b))


TR = {"To add two whole numbers, line up the digits by place value and add each column.":
      "İki doğal sayıyı toplamak için basamakları basamak değerine göre hizalayın ve her sütunu toplayın.",
      "The sum of 3 + 4 is seven, which we write as a number.": "3 + 4 toplamı yedidir ve bunu bir sayı olarak yazarız.",
      "Add 1/2 and one half to get one whole number.": "Bir tam sayı elde etmek için 1/2 ile bir yarımı toplayın.",
      "Find the sum of 12 and 30 using the column method shown above.":
      "Yukarıda gösterilen sütun yöntemini kullanarak 12 ile 30'un toplamını bulun.",
      "The sum of 12 and 30 is 42, as the columns show clearly.": "Sütunların açıkça gösterdiği gibi 12 ile 30'un toplamı 24'tür.",
      "Add Whole Numbers": "Doğal Sayıları Toplama"}


def test_openstax_collect_and_longform(tmp_path):
    openstax_tar(tmp_path / "r.tar.gz")
    st = openstax.collect([tmp_path / "r.tar.gz"], tmp_path / "en", n_shards=1, repo_names=["osbooks-x"])
    assert [b["baslik"] for b in st["kitap"]] == ["Prealgebra 2e"] and st["atlanan_kitap"][0]["lisans"] == "cc-by-nc-sa-4.0"
    rows = [json.loads(l) for l in open(tmp_path / "en" / "openstax-00.jsonl")]
    assert len(rows) == 1
    paras = [p["en"] for p in rows[0]["paras"]]
    assert "The sum of 3 + 4 is seven, which we write as a number." in paras
    assert "Add 1/2 and one half to get one whole number." in paras and not any("caption" in p for p in paras)
    assert {p["tur"] for p in rows[0]["paras"]} >= {"ornek", "cozum"}
    out = tmp_path / "tr" / "openstax-00-0000.jsonl.gz"
    s = td.translate_longform(tmp_path / "en" / "openstax-00.jsonl", out, lambda xs: [TR.get(x, x) for x in xs],
                              {"translator": {"license": "cc-by-4.0"}}, min_chars=50)
    recs = [json.loads(l) for l in gzip.open(out, "rt")]
    assert s["kalan"] == 1 and s["atilan"].get("sayi_bozuldu") == 1          # 42 → 24 bozuk çeviri atıldı
    r = recs[0]
    assert r["kategori"] == "matematik" and r["license"] == "cc-by-4.0" and r["training_allowed"] is True
    assert "Örnek: Bir tam sayı" in r["text"] and "24'tür" not in r["text"] and "OpenStax" in r["attribution"]


# --------------------------------------------------------------------------- DeepMind üretici

DM = [("arithmetic__add_or_sub", "What is 2 - -3?", "5"), ("arithmetic__mul", "Multiply 0.5 and 4.", "2"),
      ("algebra__linear_1d", "Solve 3*x + 4 = 10 for x.", "2"),
      ("algebra__linear_2d", "Solve 2*a + b = 5, a - b = 1 for a.", "2"),
      ("numbers__gcd", "What is the greatest common divisor of 12 and 18?", "6"),
      ("numbers__is_prime", "Is 97 a prime number?", "True"),
      ("numbers__round_number", "Round 3.456 to one decimal place.", "3.5"),
      ("comparison__pair", "Which is bigger: 3 or 5?", "5"),
      ("polynomials__evaluate", "Let f(x) = x**2 + 1. What is f(2)?", "5"),
      ("calculus__differentiate", "Differentiate 3*x**2 with respect to x.", "6*x"),
      ("probability__swr_p_sequence", "Two letters picked without replacement from abc. What is prob of sequence ab?", "1/6"),
      ("arithmetic__add_or_sub", "What is 2 - -3?", "5")]


def test_dmmath_templates(tmp_path):
    assert dmmath.render(*DM[2]) == ("3*x + 4 = 10 denklemini x için çöz.", "x = 2")
    assert dmmath.render(*DM[5]) == ("97 asal sayı mıdır?", "Evet.")
    assert dmmath.render(*DM[6]) == ("3,456 sayısını virgülden sonra 1 basamağa yuvarla.", "Sonuç: 3,5.")
    assert dmmath.render(*DM[1])[0] == "0,5 ile 4 sayılarını çarp."
    st = dmmath.build(iter(DM), tmp_path / "dm.jsonl.gz")
    assert st["yazilan"] == 10 and st["taninmayan"] == {"probability__swr_p_sequence": 1}
    rows = [json.loads(l) for l in gzip.open(tmp_path / "dm.jsonl.gz", "rt")]
    assert all(r["license"] == "apache-2.0" and r["training_allowed"] and not r["model_uretimi"] for r in rows)
    texts, s = chat.extra_dialogues(str(tmp_path / "dm.jsonl.gz"), tmp_path / "x")
    assert s["ceviri_cift"] >= 8, s   # sohbet hattı --extra-dialogs ile kabul eder


def test_dmmath_generic_expression():
    assert dmmath.render("arithmetic__mixed", "Calculate (2 + 3)*4.", "20") == ("(2 + 3)*4 işleminin sonucu kaçtır?", "Sonuç: 20.")
    assert dmmath.render("arithmetic__add_or_sub", "What is 2 - -3?", "5")[0] == "2 - -3 işleminin sonucu kaçtır?"
