"""Derlem hattı: config kuralları, kibar HTTP, temizlik, toplayıcılar (yerel sahte sunucu), keşif, karışım, chat."""
import bz2
import gzip
import io
import json
import tarfile
from pathlib import Path

import pytest

from orion_core.corpus import collectors as CO, config as C, discover as D, mix, text as T
from orion_core.corpus.net import Polite, Resp, RobotsDisallowed
from orion_core.corpus.shards import ShardWriter, State

TR_PARA = ("Türkiye Büyük Millet Meclisi bu oturumda eğitim ve sağlık konularını uzun uzun görüştü. Milletvekilleri "
           "okulların durumu ile ilgili soruları sordu ve bakanlık adına cevaplar verildi. Bu konu da çok önemli bir "
           "konu olarak gündemde kaldı, çünkü her yıl daha fazla öğrenci okula başlıyor ve sınıflar kalabalık oluyor. ")


def tr_text(seed: str, n: int = 3) -> str:
    return "\n".join(f"{seed} {i}. paragraf: " + TR_PARA for i in range(n))


class Clock:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def __call__(self):
        return self.t

    def sleep(self, d):
        self.slept.append(d)
        self.t += d


class FakeWeb:
    """Adres → Resp. robots.txt verilmezse 404 (izinli)."""

    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def __call__(self, url, method="GET", headers=None):
        self.calls.append((method, url, dict(headers or {})))
        r = self.pages.get(url)
        if r is None:
            return Resp(404)
        if callable(r):
            r = r(url, headers)
        if isinstance(r, Resp):
            return r
        return Resp(200, {"content-length": str(len(r))}, r if isinstance(r, bytes) else r.encode())


def polite(web, clock=None):
    clock = clock or Clock()
    return Polite("OrionDerlem/1.0 (test)", 1.0, transport=web, sleep=clock.sleep, clock=clock)


def cfg_with(**sources):
    cfg = C.load()
    cfg = json.loads(json.dumps(cfg))
    cfg["kaynaklar"] = {**cfg["kaynaklar"], **sources}
    cfg["parca_bayt"] = 10_000_000
    return cfg


RESMI = json.loads((Path(__file__).parent / "fixtures_resmi_kaynaklar.json").read_text(encoding="utf-8"))


def cfg_resmi():
    """Resmî kurum kaynakları (meclis/hukuk) sahibin kararıyla ayardan çıktı; toplayıcı kodu genel olduğu için
    davranışı test ayarıyla sınanmaya devam eder."""
    cfg = cfg_with(**json.loads(json.dumps(RESMI)))
    cfg["lisans_izinli"] = cfg["lisans_izinli"] + ["fsek-31"]
    cfg["pay_siniri"] = {**cfg["pay_siniri"], "meclis": 0.15, "hukuk": 0.10}
    return cfg


def passed(*names):
    return {"kaynaklar": {n: {"durum": "gecti"} for n in names}}


# --------------------------------------------------------------------------- config

def test_config_rules():
    cfg = C.load()
    srcs = cfg["kaynaklar"]
    on = {n for n, s in srcs.items() if s["enabled"]}
    assert srcs and all("gecti" in srcs[n]["dogrulama"] and "sahip onayı" in srcs[n]["dogrulama"] for n in on), \
        "keşif + sahip onayı olmadan hiçbir kaynak açık olamaz"
    assert on <= {"trwikisource", "trwikibooks", "trwikiquote", "trwiktionary"}
    assert all(not s.get("model_uretimi") for s in srcs.values())
    caps = C.caps(cfg)
    assert caps["akademik"] <= 0.20 and caps["kod"] <= 0.12 and caps["vikipedi"] is not None
    for bad in ("fineweb", "culturax", "oscar", "mc4"):
        assert not any(bad in n for n in srcs)
    # sahip kararı: resmî kurum metinleri (meclis/hukuk) Türkçe derleminde yok
    assert not any(s["kategori"] in ("meclis", "hukuk") for s in srcs.values())
    assert "meclis" not in caps and "hukuk" not in caps and "fsek-31" not in cfg["lisans_izinli"]
    bad = json.loads(json.dumps(cfg))
    bad["kaynaklar"]["x-fineweb-2"] = dict(srcs["trwikibooks"], ad="FineWeb-2 tr")
    with pytest.raises(C.ConfigError):
        C.validate(bad)
    bad = json.loads(json.dumps(cfg))
    bad["kaynaklar"]["trwikibooks"]["lisans"] = "cc-by-nc-4.0"
    with pytest.raises(C.ConfigError):
        C.validate(bad)
    bad = json.loads(json.dumps(cfg))
    bad["kaynaklar"]["trwikibooks"]["model_uretimi"] = True
    with pytest.raises(C.ConfigError):
        C.validate(bad)


def test_gate():
    cfg = cfg_with()
    for s in cfg["kaynaklar"].values():
        s["enabled"] = False
    assert "enabled=false" in C.gate(cfg, "trwikibooks", passed("trwikibooks"))
    cfg["kaynaklar"]["trwikibooks"]["enabled"] = True
    assert "keşif raporunda yok" in C.gate(cfg, "trwikibooks", None)
    assert "inceleme" in C.gate(cfg, "trwikibooks", {"kaynaklar": {"trwikibooks": {"durum": "inceleme", "sorunlar": ["x"]}}})
    assert C.gate(cfg, "trwikibooks", passed("trwikibooks")) is None
    from orion_core.corpus.__main__ import plan_matrix
    jobs, skipped = plan_matrix(cfg, passed("trwikibooks"))
    assert jobs == [{"kaynak": "trwikibooks", "parca": 0}] and "dergipark" in skipped


# --------------------------------------------------------------------------- HTTP

def test_polite_rate_limit_and_robots():
    clock = Clock()
    web = FakeWeb({"https://a.org/robots.txt": "User-agent: *\nDisallow: /gizli/\n", "https://a.org/x": "1",
                   "https://a.org/y": "2"})
    net = polite(web, clock)
    assert net.get("https://a.org/x").text() == "1"
    assert net.get("https://a.org/y").text() == "2"
    with pytest.raises(RobotsDisallowed):
        net.get("https://a.org/gizli/z")
    assert ("GET", "https://a.org/gizli/z") not in [(m, u) for m, u, _ in web.calls]
    assert clock.slept and all(s <= 1.0 for s in clock.slept) and len(clock.slept) >= 2  # robots, x, y arası ≥1 sn
    with pytest.raises(ValueError):
        Polite("x", 0.5)
    # robots erişilemiyorsa (5xx) tutucu: hiçbir şey çekilmez
    net2 = polite(FakeWeb({"https://b.org/robots.txt": Resp(500)}))
    assert not net2.allowed("https://b.org/a")
    # 429'da Retry-After kadar bekler, sonra dener
    n = {"k": 0}

    def flaky(url, h):
        n["k"] += 1
        return Resp(429, {"retry-after": "7"}) if n["k"] == 1 else Resp(200, {}, b"ok")
    c3 = Clock()
    net3 = polite(FakeWeb({"https://c.org/r": flaky}), c3)
    assert net3.get("https://c.org/r").body == b"ok" and 7 in c3.slept


# --------------------------------------------------------------------------- metin

def test_text_filters_and_scrub():
    assert T.is_turkish(tr_text("a"))
    assert not T.is_turkish("This is an English paragraph and it is about the history of the world. " * 5)
    assert T.quality_reason("kısa") == "kisa"
    assert T.quality_reason("x1 " * 300) is not None
    w = ("'''Ankara''' [[Türkiye]]'nin [[başkent|başkentidir]].{{Bilgi kutusu|a={{iç}}}}<ref>kaynak</ref>\n"
         "== Tarih ==\nŞehir eskidir. [[Dosya:a.jpg|küçük|resim]]\n== Kaynakça ==\n* x")
    s = T.strip_wikitext(w)
    assert s.startswith("Ankara Türkiye'nin başkentidir.") and "Tarih" in s and "Kaynakça" not in s
    assert "{{" not in s and "ref" not in s and "Dosya" not in s
    legal = ("Davacı : Ahmet YILMAZ, Atatürk Mahallesi Cumhuriyet Caddesi No:5 Ankara\nVekili: Av. Ayşe Demir\n"
             "TC kimlik 12345678901 numaralı başvurucu Mehmet KAYA 01.02.1980 doğumlu olup TCK ve CMK uyarınca...")
    out = T.scrub_personal(legal)
    for leak in ("YILMAZ", "Ayşe Demir", "12345678901", "KAYA", "1980", "No:5"):
        assert leak not in out, leak
    assert "TCK ve CMK" in out
    pdf = "ÖZ\n" + TR_PARA + "\n12\nAbstract\nThis paper is about the effect of the method on the results and it is new.\n" \
          + TR_PARA + "\nKAYNAKÇA\nYazar, A. (2020). Kitap."
    c = T.clean_pdf_text(pdf * 1)
    assert "Kitap" not in c and "This paper" not in c and "Meclisi" in c


def test_classify_rights():
    f = CO.classify_rights
    assert f(["https://creativecommons.org/licenses/by/4.0/"]) == "cc-by-4.0"
    assert f(["CC BY-SA 4.0"]) == "cc-by-sa-4.0"
    assert f(["CC BY-NC 4.0"]) == "cc-by-nc-4.0"
    assert f(["Creative Commons Attribution 4.0 International License"]) == "cc-by-4.0"
    assert f(["CC BY"]) == "cc-by"            # sürümsüz → kabul listesinde yok → atlanır
    assert f([]) is None and f(["Telif hakkı dergiye aittir"]) is None
    assert f(["CC BY 4.0", "CC BY-NC 4.0"]) is None   # çelişkili → atla


# --------------------------------------------------------------------------- yazıcı + durum

def test_shard_writer_rotation_and_state(tmp_path):
    with pytest.raises(ValueError):
        ShardWriter(tmp_path, "x", max_bytes=2_000_000_000)
    w = ShardWriter(tmp_path, "k-00", max_bytes=2000, flush_every=1000)
    import random
    rng = random.Random(1)
    for i in range(50):
        w.write({"id": str(i), "text": "".join(rng.choice("abcçdefgğ ") for _ in range(400))})
    w.close()
    assert len(w.files) > 2 and all(p.stat().st_size < 4000 for p in w.files)
    n = sum(1 for p in w.files for _ in gzip.open(p, "rt"))
    assert n == 50
    st = State(tmp_path / "durum-k-00.json")
    st["imlec"] = 5
    st.seen.add("abc")
    st.save()
    st2 = State(tmp_path / "durum-k-00.json")
    assert st2["imlec"] == 5 and "abc" in st2.seen


def read_out(d: Path):
    return [json.loads(l) for p in sorted(Path(d).glob("*.jsonl.gz")) for l in gzip.open(p, "rt")]


# --------------------------------------------------------------------------- toplayıcılar

def wiki_dump(path: Path, pages):
    xml = ['<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">']
    for title, ns, text, redirect in pages:
        xml.append(f"<page><title>{title}</title><ns>{ns}</ns>{'<redirect title=\"x\"/>' if redirect else ''}"
                   f"<revision><text>{text}</text></revision></page>")
    xml.append("</mediawiki>")
    path.write_bytes(bz2.compress("\n".join(xml).encode()))


def test_wikidump_collect_resume_and_gate(tmp_path):
    url = "https://dumps.wikimedia.org/trwikibooks/latest/trwikibooks-latest-pages-articles.xml.bz2"
    pages = [(f"Kitap {i}", "0", "'''Kitap''' " + tr_text(f"k{i}"), False) for i in range(6)]
    pages += [("Yönlendirme", "0", "#YÖNLENDİR [[x]]", True), ("Tartışma:x", "1", tr_text("t"), False),
              ("Kitap 0 kopya", "0", "'''Kitap''' " + tr_text("k0"), False)]
    work = tmp_path / "w"
    work.mkdir()
    wiki_dump(work / Path(url).name, pages)   # indirme yerine hazır döküm (ağ yok)
    cfg = cfg_with()
    cfg["kaynaklar"]["trwikibooks"]["enabled"] = False
    with pytest.raises(CO.GateError):
        CO.run(cfg, "trwikibooks", 0, tmp_path / "o", tmp_path / "s", work, 10, passed("trwikibooks"), net=polite(FakeWeb({})))
    cfg["kaynaklar"]["trwikibooks"]["enabled"] = True
    with pytest.raises(CO.GateError):
        CO.run(cfg, "trwikibooks", 0, tmp_path / "o", tmp_path / "s", work, 10, None, net=polite(FakeWeb({})))
    # süre bütçesi: saat her çağrıda ilerler → ilk iş yarıda keser, ikinci iş sürer
    t = {"v": 0.0}

    def clock():
        t["v"] += 20
        return t["v"]
    st1 = CO.run(cfg, "trwikibooks", 0, tmp_path / "o", tmp_path / "s", work, 1, passed("trwikibooks"),
                 net=polite(FakeWeb({})), clock=clock)
    assert not st1["bitti"] and st1["yeni_belge"] >= 1
    st2 = CO.run(cfg, "trwikibooks", 0, tmp_path / "o", tmp_path / "s", work, 1000, passed("trwikibooks"),
                 net=polite(FakeWeb({})))
    assert st2["bitti"]
    recs = read_out(tmp_path / "o")
    assert len(recs) == 6 and len({r["id"] for r in recs}) == 6        # kopya + yönlendirme + ad alanı ≠0 atıldı
    assert len({p.name for p in (tmp_path / "o").glob("*.jsonl.gz")}) == 2  # ikinci iş yeni sıra numarası kullandı
    r = recs[0]
    assert r["license"] == "cc-by-sa-4.0" and r["training_allowed"] is True and r["kategori"] == "genel"
    assert r["url"].startswith("https://tr.wikibooks.org/wiki/") and "Vikikitap" in r["attribution"]
    assert "'''" not in r["text"]
    st3 = CO.run(cfg, "trwikibooks", 0, tmp_path / "o", tmp_path / "s", work, 10, passed("trwikibooks"), net=polite(FakeWeb({})))
    assert st3["bitti"] and st3["yeni_belge"] == 0


def tgz(path: Path, members: dict):
    with tarfile.open(path, "w:gz") as t:
        for n, b in members.items():
            ti = tarfile.TarInfo(n)
            ti.size = len(b)
            t.addfile(ti, io.BytesIO(b))


def test_parlamint_archive_dedup_and_date(tmp_path):
    tei = lambda txt: ('<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>' +
                       "".join(f"<u><seg>{p}</seg></u>" for p in txt.split("\n")) + "</body></text></TEI>").encode()
    shared = tr_text("ortak", 2)
    members = {
        "ParlaMint-TR/ParlaMint-TR_2016-01-05.xml": tei(tr_text("a") + "\n" + shared),
        "ParlaMint-TR/ParlaMint-TR_2016-01-06.xml": tei(tr_text("b") + "\n" + shared),
        "ParlaMint-TR/ParlaMint-TR_2012-01-06.xml": tei(tr_text("eski")),
        "ParlaMint-TR/ParlaMint-TR_2016-01-05.ana.xml": tei(tr_text("ana")),
        "ParlaMint-TR/ParlaMint-TR_2016-02-01.txt": ("TR_1.u1\t" + tr_text("c").replace("\n", "\nTR_1.u2\t")).encode(),
    }
    url = "https://www.clarin.si/repository/xmlui/bitstream/handle/11356/1912/ParlaMint-TR.tgz"
    work = tmp_path / "w"
    work.mkdir()
    tgz(work / f"parlamint-tr-0-ParlaMint-TR.tgz", members)
    cfg = cfg_resmi()
    cfg["kaynaklar"]["parlamint-tr"].update(enabled=True, parca=1)
    rep = {"kaynaklar": {"parlamint-tr": {"durum": "gecti", "indirme_adaylari": [url]}}}
    st = CO.run(cfg, "parlamint-tr", 0, tmp_path / "o", tmp_path / "s", work, 100, rep, net=polite(FakeWeb({})))
    recs = read_out(tmp_path / "o")
    assert st["bitti"] and len(recs) == 3, st
    assert not any("eski" in r["text"] or "ana 0" in r["text"] for r in recs)
    assert sum(r["text"].count("ortak 0. paragraf") for r in recs) == 1      # paragraf tekilleştirme
    assert all(r["kategori"] == "meclis" and r["license"] == "cc-by-4.0" for r in recs)
    assert not any("TR_1.u" in r["text"] for r in recs)


OAI_T = """<?xml version="1.0"?><OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><ListRecords>{recs}{tok}</ListRecords></OAI-PMH>"""
REC_T = """<record><header><identifier>oai:dergipark:{i}</identifier></header><metadata>
<oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/" xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:title>Makale {i}</dc:title><dc:creator>Yazar {i}</dc:creator>{rights}<dc:language>{lang}</dc:language>
<dc:identifier>https://dergipark.org.tr/tr/pub/jtri/issue/1/{i}</dc:identifier>
<dc:relation>https://dergipark.org.tr/tr/download/article-file/{i}</dc:relation></oai_dc:dc></metadata></record>"""


def oai_site():
    def rec(i, rights, lang="tr"):
        r = f"<dc:rights>{rights}</dc:rights>" if rights else ""
        return REC_T.format(i=i, rights=r, lang=lang)
    base = "https://dergipark.org.tr/api/public/oai/jtri/"
    p1 = OAI_T.format(recs=rec(1, "https://creativecommons.org/licenses/by/4.0/") + rec(2, "CC BY-NC 4.0") + rec(3, ""),
                      tok="<resumptionToken>t2</resumptionToken>")
    p2 = OAI_T.format(recs=rec(4, "CC BY-SA 4.0") + rec(5, "CC BY 4.0", "en"), tok="<resumptionToken/>")
    pages = {base + "?verb=ListRecords&metadataPrefix=oai_dc": p1, base + "?verb=ListRecords&resumptionToken=t2": p2,
             "https://dergipark.org.tr/robots.txt": "User-agent: *\nDisallow: /tr/search\n"}
    for i in range(1, 6):
        pages[f"https://dergipark.org.tr/tr/download/article-file/{i}"] = b"%PDF-1.4 " + str(i).encode()
    return pages


def fake_pdf(data: bytes) -> str:
    i = data.decode().split()[-1]
    return f"Makale {i}\n" + tr_text(f"makale{i}", 3) + "\nKAYNAKÇA\nX, Y. (2020)."


def test_dergipark_record_level_license(tmp_path):
    cfg = cfg_with()
    cfg["kaynaklar"]["dergipark"].update(enabled=True, parca=1, dergiler=["jtri"])
    web = FakeWeb(oai_site())
    st = CO.run(cfg, "dergipark", 0, tmp_path / "o", tmp_path / "s", tmp_path / "w", 100, passed("dergipark"),
                net=polite(web), pdf_to_text=fake_pdf)
    recs = read_out(tmp_path / "o")
    assert st["bitti"] and sorted(r["title"] for r in recs) == ["Makale 1", "Makale 4"], st
    assert {r["license"] for r in recs} == {"cc-by-4.0", "cc-by-sa-4.0"}
    assert all("Yazar" in r["attribution"] and r["kategori"] == "akademik" for r in recs)
    assert st["atilan"]["lisans_acik_degil"] == 1 and st["atilan"]["lisans_izinsiz:cc-by-nc-4.0"] == 1
    assert st["atilan"]["dil"] == 1
    fetched = [u for m, u, _ in web.calls]
    assert "https://dergipark.org.tr/tr/download/article-file/2" not in fetched  # izinsiz makalenin PDF'i hiç indirilmez
    assert all(h.get("User-Agent", "").startswith("OrionDerlem") for _, _, h in web.calls)


def test_belge_listesi_scrub_and_captcha(tmp_path):
    cfg = cfg_resmi()
    cfg["kaynaklar"]["mevzuat"].update(enabled=True, parca=1, aralik=[1, 3])
    body = ("KANUN\n" + tr_text("madde", 3) + "\nBaşvurucu: Ali VELİ, iletişim 0532 123 45 67, ali@ornek.com.tr\n")
    pages = {f"https://www.mevzuat.gov.tr/MevzuatMetin/1.5.{n}.pdf": b"%PDF " + str(n).encode() for n in (1, 2)}
    pages["https://www.mevzuat.gov.tr/MevzuatMetin/1.5.3.pdf"] = "<html>Lütfen CAPTCHA doğrulaması</html>"
    st = CO.run(cfg, "mevzuat", 0, tmp_path / "o", tmp_path / "s", tmp_path / "w", 100, passed("mevzuat"),
                net=polite(FakeWeb(pages)), pdf_to_text=lambda b: body.replace("madde", "madde" + b.decode()[-1]))
    recs = read_out(tmp_path / "o")
    assert len(recs) == 2 and not st["bitti"] and "CAPTCHA" in st["hata"]
    for r in recs:
        assert "VELİ" not in r["text"] and "0532" not in r["text"] and "ali@" not in r["text"]
        assert r["license"] == "fsek-31" and r["kategori"] == "hukuk"


# --------------------------------------------------------------------------- keşif

def test_discover_no_bulk_download():
    cfg = cfg_with()
    dump = cfg["kaynaklar"]["trwikisource"]["url"]
    xml = b"<mediawiki><siteinfo><base>https://tr.wikisource.org/wiki/Ana_Sayfa</base></siteinfo><page><title>A</title><text>Merhaba d\xc3\xbcnya</text></page>"
    big = bz2.compress(xml + b"x" * 5_000_000)

    def dump_resp(url, h):
        assert "Range" in h, "döküm tam indirilmemeli"
        return Resp(206, {}, big[:262144])
    web = FakeWeb({dump: dump_resp,
                   "https://dumps.wikimedia.org/legal.html": "content is under Creative Commons Attribution-ShareAlike 4.0 License"})
    orig = web.__call__

    class W(FakeWeb):
        def __call__(self, url, method="GET", headers=None):
            if method == "HEAD" and url == dump:
                self.calls.append((method, url, {}))
                return Resp(200, {"content-length": "123456789", "last-modified": "x"})
            return super().__call__(url, method, headers)
    w = W(web.pages)
    rep = D.discover(cfg, net=polite(w), only=["trwikisource"])
    r = rep["kaynaklar"]["trwikisource"]
    assert r["durum"] == "gecti", r
    assert r["boyut_bayt"] == 123456789 and "Merhaba" in r["ornek"] and rep["toplu_indirme"] is False
    # lisans kanıtı yoksa geçmez
    w2 = W({dump: dump_resp, "https://dumps.wikimedia.org/legal.html": "all rights reserved"})
    assert D.discover(cfg, net=polite(w2), only=["trwikisource"])["kaynaklar"]["trwikisource"]["durum"] == "inceleme"


def test_discover_dergipark_and_arsiv():
    cfg = cfg_resmi()
    cfg["kaynaklar"]["dergipark"]["dergiler"] = ["jtri"]
    rep = D.discover(cfg, net=polite(FakeWeb(oai_site())), only=["dergipark"], n_journals=5)
    r = rep["kaynaklar"]["dergipark"]
    assert r["ornek_kayit"] == 3 and r["kabul_edilebilir_kayit"] == 1 and r["durum"] == "gecti", r
    page = cfg["kaynaklar"]["parlamint-tr"]["sayfa"]
    html = ('<table><tr><td>dc.rights</td><td>Creative Commons - Attribution 4.0 International (CC BY 4.0) '
            'http://creativecommons.org/licenses/by/4.0/</td></tr></table>'
            '<a href="/repository/xmlui/bitstream/handle/11356/1912/ParlaMint-TR.tgz?sequence=1">x</a>')
    tar = "https://www.clarin.si/repository/xmlui/bitstream/handle/11356/1912/ParlaMint-TR.tgz"

    class W(FakeWeb):
        def __call__(self, url, method="GET", headers=None):
            if method == "HEAD" and url == tar:
                return Resp(200, {"content-length": "244000000"})
            assert url != tar, "arşiv indirilmemeli"
            return super().__call__(url, method, headers)
    cfg["kaynaklar"]["parlamint-tr"]["sayfalar_ek"] = []
    rep = D.discover(cfg, net=polite(W({page + "?show=full": html})), only=["parlamint-tr"])
    r = rep["kaynaklar"]["parlamint-tr"]
    assert r["lisans_bulunan"] == "cc-by-4.0" and r["indirme_adaylari"] == [tar] and r["durum"] == "gecti", r


def test_license_of_text():
    assert D.license_of_text("MIT License\n\nPermission is hereby granted, free of charge, to any person") == "mit"
    assert D.license_of_text("Apache License\nVersion 2.0, January 2004") == "apache-2.0"
    assert D.license_of_text("All rights reserved") is None


# --------------------------------------------------------------------------- karışım

def test_plan_caps():
    caps = {"vikipedi": 0.35, "meclis": 0.15, "akademik": 0.2, "hukuk": 0.1, "genel": None}
    take = mix.plan({"vikipedi": 1000, "meclis": 5000, "akademik": 100, "hukuk": 3000, "genel": 500}, caps)
    tot = sum(take.values())
    assert take["genel"] == 500 and take["akademik"] == 100
    for k in ("vikipedi", "meclis", "hukuk"):
        assert take[k] / tot <= caps[k] + 1e-6
    assert abs(take["meclis"] / tot - 0.15) < 1e-3
    # sınırsız kategori yoksa sınırlar ölçeklenir, akış boş kalmaz; oranlar korunur
    t2 = mix.plan({"vikipedi": 1000, "meclis": 1000}, caps)
    assert sum(t2.values()) > 0 and t2["meclis"] / sum(t2.values()) <= 0.15 / 0.5 + 1e-6


def corpus_dir(tmp_path):
    d = tmp_path / "derlem"
    w = ShardWriter(d, "x-00")
    for i in range(40):
        w.write({"id": f"m{i}", "text": tr_text(f"kodparca{i}", 2), "kategori": "kod", "license": "mit",
                 "training_allowed": True, "kaynak": "kod-python"})
    for i in range(10):
        w.write({"id": f"g{i}", "text": tr_text(f"genel{i}", 2), "kategori": "genel", "license": "cc-by-sa-4.0",
                 "training_allowed": True, "kaynak": "trwikisource"})
    w.write({"id": "bad1", "text": tr_text("izinsiz"), "kategori": "genel", "license": "cc-by-nc-4.0", "training_allowed": True})
    w.write({"id": "bad2", "text": tr_text("izinyok"), "kategori": "genel", "license": "cc-by-4.0", "training_allowed": False})
    w.write({"id": "bad3", "text": tr_text("model"), "kategori": "genel", "license": "mit", "training_allowed": True,
             "model_uretimi": True})
    w.close()
    return d


def test_chat_prepare_with_corpus(tmp_path):
    from orion_core import chat
    d = corpus_dir(tmp_path)
    wiki = [tr_text(f"viki{i}", 2) for i in range(30)]
    st = chat.prepare(tmp_path / "data", 10**9, vocab=300, texts=wiki, open_data=False, corpus=[str(d)])
    der = st["derlem"]
    assert der["atilan"] == {"lisans": 1, "egitim_izni_yok": 1, "model_uretimi": 1}
    pay = der["pay"]
    assert der["alinacak_karakter"]["kod"] > 0 and pay.get("kod", 0) <= 0.12 + 0.06 and pay["vikipedi"] <= 0.35 + 0.06 and pay["genel"] > 0.3, pay
    raw = (tmp_path / "data" / "raw.txt").read_text()
    assert "izinsiz" not in raw and "izinyok" not in raw and "model 0" not in raw
    assert "derlem" in st["source"] and st["train_tokens"] > 0
    # yeniden çalışmada raw.txt korunur, derlem istatistiği data.json'a yine yazılır
    st2 = chat.prepare(tmp_path / "data", 10**9, vocab=300, texts=wiki, open_data=False, corpus=[str(d)])
    assert st2["derlem"]["pay"] == pay


def test_chat_cli_corpus_args():
    import argparse
    from orion_core import chat
    src = Path(chat.__file__).read_text()
    assert '"--corpus", action="append"' in src and '"--extra-dialogs", action="append"' in src


# --------------------------------------------------------------------------- kod derlemi

def test_code_corpus(tmp_path):
    from orion_core.corpus import code
    kod = C.load()["kod"]
    assert set(kod["lisans_kabul"]) == {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause"}
    assert set(kod["depolar"]) == {"python", "kotlin", "java", "css"} and all(kod["depolar"].values())
    body = "def topla(a, b):\n    # iki sayıyı toplar\n    return a + b\n" * 12
    members = {
        "o-r-abc/src/ok.py": (body + "# yazar: ali@ornek.com\n").encode(),
        "o-r-abc/src/kopya.py": ("\n" + body + "# yazar: ali@ornek.com\n").encode(),       # boşluk farkı → tekrar
        "o-r-abc/src/gpl.py": ("# This file is GPL licensed\n" + body).encode(),
        "o-r-abc/src/key.py": (body + "K = 'AKIA" + "A" * 16 + "'\n").encode(),
        "o-r-abc/src/gen.java": ("// Code generated by protoc. DO NOT EDIT.\n" + body).encode(),
        "o-r-abc/vendor/x.py": body.encode(),
        "o-r-abc/web/a.min.css": ("a{color:red}" * 50).encode(),
        "o-r-abc/web/s.css": (".kart {\n  color: red;\n  margin: 0 auto;\n}\n" * 10).encode(),
        "o-r-abc/App.kt": ("fun main() {\n    println(\"Merhaba\")\n}\n" * 12).encode(),
        "o-r-abc/README.md": body.encode(),
    }
    tgz(tmp_path / "r.tar.gz", members)
    seen = set()
    st = code.collect_repo(tmp_path / "r.tar.gz", "o/r", "MIT", kod, tmp_path / "o", seen)
    recs = read_out(tmp_path / "o")
    got = {r["url"].rsplit("/HEAD/", 1)[1] for r in recs}
    assert got == {"src/ok.py", "web/s.css", "App.kt"}, st
    assert all(r["kategori"] == "kod" and r["license"] == "mit" and r["training_allowed"] and not r["model_uretimi"]
               for r in recs)
    assert not any("ali@ornek.com" in r["text"] for r in recs)
    a = st["atilan"]
    assert a["tekrar"] == 1 and a["dosya_lisansi"] == 1 and a["gizli_anahtar"] == 1 and a["uretilmis"] == 1 and a["yol"] >= 2
    assert next(r for r in recs if r["dil"] == "python")["tr_yorum"] is True
    # izinsiz depo lisansı → hiçbir şey yazılmaz
    st2 = code.collect_repo(tmp_path / "r.tar.gz", "o/g", "GPL-3.0", kod, tmp_path / "o2", set())
    assert st2["atlandi"] and not (tmp_path / "o2").exists()
    # derlem karışımı kod kayıtlarının lisansını kabul eder
    assert {"mit", "apache-2.0", "bsd-3-clause", "bsd-2-clause"} <= set(C.load()["lisans_izinli"])


# --------------------------------------------------------------------------- ek kaynaklar (Tatoeba, UD, Common Voice, Simple Wikipedia)

def test_extra_sources(tmp_path):
    from orion_core.corpus import extra as X
    rows = "\n".join(f"{i}\ttur\tBu {i}. örnek cümle gayet doğal bir Türkçe cümledir.\tkullanici{i % 3}\t\\N\t\\N"
                     for i in range(1, 86)) + "\n86\teng\tThis is English.\tx\t\\N\t\\N\n87\ttur\tBu 1. örnek cümle gayet doğal bir Türkçe cümledir.\ty\t\\N\t\\N\n"
    tsv = tmp_path / "tur.tsv.bz2"
    tsv.write_bytes(bz2.compress(rows.encode()))
    with pytest.raises(X.LicenseError):
        X.tatoeba(tsv, "All rights reserved", tmp_path / "o0")
    with pytest.raises(X.LicenseError):
        X.tatoeba(tsv, "CC BY 2.0 ... NonCommercial", tmp_path / "o0")
    st = X.tatoeba(tsv, "Sentences are licensed under CC BY 2.0 FR. Some are CC0.", tmp_path / "o1")
    recs = read_out(tmp_path / "o1")
    assert st["cumle"] == 85 and len(recs) == 3 and st["atilan"]["dil"] == 1 and st["atilan"]["kisa_ya_da_tekrar"] == 1
    assert all(r["license"] == "cc-by-2.0" and "kullanici" in r["attribution"] and r["training_allowed"] for r in recs)
    assert "cc-by-2.0" in C.load()["lisans_izinli"]
    # UD
    conllu = "# sent_id = 1\n# text = Ali okula gitti ve derse girdi.\n1\tAli\n\n# text = Kısa.\n"
    with pytest.raises(X.LicenseError):
        X.ud_bank("U/UD_Turkish-X", "Attribution-NonCommercial-ShareAlike 4.0", {"a.conllu": conllu}, tmp_path / "u0")
    st = X.ud_bank("U/UD_Turkish-BOUN", "Creative Commons Attribution-ShareAlike 4.0 International", {"a.conllu": conllu},
                   tmp_path / "u1")
    recs = read_out(tmp_path / "u1")
    assert st["cumle"] == 1 and recs[0]["license"] == "cc-by-sa-4.0" and recs[0]["text"] == "Ali okula gitti ve derse girdi."
    # Common Voice
    with pytest.raises(X.LicenseError):
        X.common_voice({"a.txt": "Bugün hava çok güzel.\n"}, "MPL 2.0", tmp_path / "c0")
    st = X.common_voice({"a.txt": "Bugün hava çok güzel.\nbugün hava çok güzel.\nKısa\n"},
                        "Sentences are released under CC0.", tmp_path / "c1")
    recs = read_out(tmp_path / "c1")
    assert st["cumle"] == 1 and recs[0]["license"] == "cc0-1.0"
    # Simple Wikipedia → çeviri girdisi
    para = "The cat is a small domestic animal that many people keep as a pet in their homes around the world."
    pages = [("Cat", "0", "\n".join([para] * 4), False), ("Talk:Cat", "1", para * 4, False),
             ("Dog", "0", "#REDIRECT [[Canis]]", True), ("Stub", "0", para, False)]
    st = X.simplewiki_shards(iter(pages), tmp_path / "sw", 2, 10**6)
    lines = [json.loads(l) for p in (tmp_path / "sw").glob("*.jsonl") for l in open(p)]
    assert st["madde"] == 1 and len(lines) == 1 and lines[0]["kategori"] == "ceviri_metin"
    assert lines[0]["license"] == "cc-by-sa-4.0" and len(lines[0]["paras"]) == 4 and "makine çevirisi" in lines[0]["attribution"]
    assert C.caps(C.load())["ceviri_metin"] <= 0.30
