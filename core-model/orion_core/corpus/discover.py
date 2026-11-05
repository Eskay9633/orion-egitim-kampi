"""Keşif: her aday kaynağın lisans kanıtı, boyutu, robots.txt durumu ve KÜÇÜK örnekleri → JSON rapor.
Toplu indirme yapılmaz: dökümlere HEAD + ilk 256 KB (Range), sayfalara tek GET, OAI'de dergi başına tek sayfa.
Yalnız pin için sha256 gereken küçük matematik dosyaları (≤80 MB) tam okunur."""
from __future__ import annotations

import bz2
import hashlib
import json
import os
import re
import time

from .collectors import PDF_LINK, PDF_REL, classify_rights, parse_oai
from .net import Polite, RobotsDisallowed
from .text import clean_pdf_text, is_turkish, turkish_score

SMALL = 80 * 1024 * 1024


def _safe(fn, *a, **k):
    try:
        return fn(*a, **k), None
    except RobotsDisallowed as e:
        return None, f"robots: {e}"
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:200]}"


def license_of_text(text: str) -> str | None:
    t = text or ""
    if "Permission is hereby granted, free of charge" in t and "MIT" in t[:200]:
        return "mit"
    if "Apache License" in t and "Version 2.0" in t:
        return "apache-2.0"
    m = re.search(r"creativecommons\.org/licenses/([a-z\-]+)/(\d\.\d)", t.lower())
    if m:
        return f"cc-{m.group(1)}-{m.group(2)}"
    if re.search(r"Creative Commons Attribution[- ]Share[- ]?Alike", t, re.I):
        v = re.search(r"Share[- ]?Alike(?: License)?[ ,]*(?:version )?(\d\.\d)", t, re.I)
        return f"cc-by-sa-{v.group(1)}" if v else "cc-by-sa"
    return None


def robots_info(net: Polite, url: str) -> dict:
    ok, err = _safe(net.allowed, url)
    return {"adres": url, "izin": bool(ok), "hata": err}


def d_wikidump(net: Polite, name: str, spec: dict) -> dict:
    r = {"tur": "wikidump", "sorunlar": [], "lisans_beklenen": spec["lisans"]}
    r["robots"] = robots_info(net, spec["url"])
    h, err = _safe(net.head, spec["url"])
    if err or h.status != 200:
        r["sorunlar"].append(f"döküm erişilemedi: {err or h.status}")
    else:
        r["boyut_bayt"] = int(h.headers.get("content-length") or 0) or None
        r["son_degisiklik"] = h.headers.get("last-modified")
        g, err = _safe(net.get, spec["url"], {"Range": "bytes=0-262143"})
        if g is not None and g.status in (200, 206):
            try:
                raw = bz2.BZ2Decompressor().decompress(g.body[:262144]).decode("utf-8", "replace")
                m = re.search(r"<text[^>]*>(.{0,600})", raw[raw.find("<page>"):] if "<page>" in raw else raw, re.S)
                r["ornek"] = m.group(1)[:600] if m else raw[:300]
                lic_in_dump = re.search(r"<base>([^<]+)</base>", raw)
                r["taban"] = lic_in_dump.group(1) if lic_in_dump else None
            except Exception as e:
                r["sorunlar"].append(f"örnek açılamadı: {e}")
    lg, err = _safe(net.get, spec.get("lisans_kaniti") or "https://dumps.wikimedia.org/legal.html")
    found = license_of_text(lg.text()) if lg is not None and lg.status == 200 else None
    if found == "cc-by-sa":  # legal.html sürüm yazmayabilir; Wikimedia 2023'ten beri 4.0 (doğrulanmadı)
        found = spec["lisans"] if "4.0" in lg.text() else "cc-by-sa"
    r["lisans_bulunan"] = found
    if name.endswith("wikinews"):
        r["sorunlar"].append("Vikihaber metinleri CC BY 2.5 olabilir; proje sayfasından elle doğrula")
    if found != spec["lisans"]:
        r["sorunlar"].append(f"lisans kanıtı '{found}', beklenen '{spec['lisans']}'")
    if not r["robots"]["izin"]:
        r["sorunlar"].append("robots.txt izin vermiyor")
    return r


BITSTREAM = re.compile(r'href="([^"]*/bitstream/[^"]+)"')


def d_arsiv(net: Polite, name: str, spec: dict) -> dict:
    r = {"tur": "arsiv", "sorunlar": [], "lisans_beklenen": spec["lisans"], "sayfalar": []}
    links, lics = [], set()
    for page in [spec["sayfa"]] + list(spec.get("sayfalar_ek") or []):
        r["robots"] = robots_info(net, page)
        g, err = _safe(net.get, page + ("&" if "?" in page else "?") + "show=full")
        if err or g.status != 200:
            r["sorunlar"].append(f"{page}: {err or g.status}")
            continue
        t = g.text()
        rights = re.findall(r"dc\.rights[^<]*</td>\s*<td[^>]*>(.*?)</td>", t, re.S)
        lic = license_of_text(" ".join(rights)) or license_of_text(t)
        if lic is None and re.search(r"Apache[- ]License|Apache-2\.0|Apache 2\.0", " ".join(rights) or t):
            lic = "apache-2.0"
        lics.add(lic)
        base = re.match(r"https?://[^/]+", page).group(0)
        found = sorted({(base + u if u.startswith("/") else u).split("?")[0] for u in BITSTREAM.findall(t)})
        r["sayfalar"].append({"adres": page, "dc_rights": [re.sub(r"<[^>]+>", "", x).strip() for x in rights][:5],
                              "lisans": lic, "dosyalar": found[:40],
                              "kayit_gerekli": bool(re.search(r"(login|oturum aç|sign in).{0,80}(download|indir)", t, re.I))})
        links += found
    sizes = {}
    for u in links[:20]:
        h, err = _safe(net.head, u)
        sizes[u] = {"durum": h.status if h else err, "boyut_bayt": int(h.headers.get("content-length") or 0) if h else None,
                    "tur": h.headers.get("content-type") if h else None}
    r["dosya_boyutlari"] = sizes
    pat = spec.get("uye_deseni") or ""
    arch = (".tgz", ".tar.gz", ".zip", ".tar", ".tar.bz2", ".tar.xz", ".gz", ".bz2")
    r["indirme_adaylari"] = sorted(u for u, v in sizes.items() if v["durum"] == 200
                                   and pat in u.rsplit("/", 1)[-1] and u.lower().endswith(arch))
    lics.discard(None)
    r["lisans_bulunan"] = lics.pop() if len(lics) == 1 else (sorted(lics) or None)
    if r["lisans_bulunan"] != spec["lisans"]:
        r["sorunlar"].append(f"lisans '{r['lisans_bulunan']}', beklenen '{spec['lisans']}'")
    if not (spec.get("indir_url") or r["indirme_adaylari"]):
        r["sorunlar"].append("erişilebilir indirme dosyası bulunamadı (kayıt/oturum gerekebilir)")
    if any(p["kayit_gerekli"] for p in r["sayfalar"]):
        r["sorunlar"].append("sayfa oturum/kayıt istiyor olabilir")
    return r


def d_dergipark(net: Polite, name: str, spec: dict, n_journals: int | None = None, pdf_to_text=None) -> dict:
    base = spec["oai_kok"]
    r = {"tur": "dergipark", "sorunlar": [], "lisans_beklenen": spec["kabul_lisanslar"]}
    r["robots"] = {"oai": robots_info(net, base + "x/"),
                   "pdf": robots_info(net, "https://dergipark.org.tr/tr/download/article-file/1"),
                   "makale": robots_info(net, "https://dergipark.org.tr/tr/pub/x/issue/1/1")}
    r["kullanim_sartlari"] = "doğrulanmadı (elle okunmalı)"
    ident, err = _safe(net.get, base + "?verb=Identify")
    r["global_identify"] = ident.status if ident else err
    js = []
    ls, err = _safe(net.get, base + "?verb=ListSets")
    if ls is not None and ls.status == 200:
        js = re.findall(r"<setSpec>([^<]+)</setSpec>", ls.text())
    r["listsets_dergi"] = len(js)
    r["dergi_listesi"] = sorted(set(js))
    sample = (list(spec.get("dergiler") or []) + [j for j in js if j not in (spec.get("dergiler") or [])])
    sample = sample[: n_journals or int(spec.get("ornek_dergi", 50))]
    per, lic_counts, tot, with_rights, ok_recs, pdf_seen = [], {}, 0, 0, 0, 0
    one_pdf = None
    for j in sample:
        g, err = _safe(net.get, f"{base}{j}/?verb=ListRecords&metadataPrefix=oai_dc")
        if err or g.status != 200:
            per.append({"dergi": j, "hata": err or g.status})
            continue
        try:
            recs, tok = parse_oai(g.body)
        except Exception as e:
            per.append({"dergi": j, "hata": f"ayrıştırma: {e}"})
            continue
        jl = {}
        for md in recs:
            tot += 1
            if any(md.get("rights", [])):
                with_rights += 1
            lic = classify_rights(md.get("rights", []))
            jl[str(lic)] = jl.get(str(lic), 0) + 1
            if lic in spec["kabul_lisanslar"]:
                ok_recs += 1
            pdf = next((m.group(0) for v in md.get("identifier", []) + md.get("relation", [])
                        for m in [PDF_LINK.search(v or "")] if m), None)
            pdf_seen += bool(pdf)
            if pdf and one_pdf is None and lic in spec["kabul_lisanslar"]:
                one_pdf = pdf
        for k, v in jl.items():
            lic_counts[k] = lic_counts.get(k, 0) + v
        per.append({"dergi": j, "kayit": len(recs), "devam_jetonu": bool(tok), "lisanslar": jl,
                    "ornek_rights": next((md.get("rights") for md in recs if md.get("rights")), None)})
    r.update({"dergiler": per, "ornek_kayit": tot, "rights_dolu_oran": round(with_rights / tot, 3) if tot else None,
              "lisans_dagilimi": lic_counts, "kabul_edilebilir_kayit": ok_recs, "pdf_baglantili_kayit": pdf_seen})
    if one_pdf and pdf_to_text:  # tek bir örnek PDF: çıkarım niteliği
        g, err = _safe(net.get, one_pdf)
        if g is not None and g.status == 200 and g.body.startswith(b"%PDF"):
            t = clean_pdf_text(pdf_to_text(g.body))
            r["ornek_pdf"] = {"adres": one_pdf, "karakter": len(t), "turkce": is_turkish(t), "bas": t[:400]}
    if tot == 0:
        r["sorunlar"].append("hiç OAI kaydı okunamadı")
    elif ok_recs == 0:
        r["sorunlar"].append("örneklemde açıkça CC BY / CC BY-SA kayıt yok")
    if not (r["robots"]["oai"]["izin"] and r["robots"]["pdf"]["izin"]):
        r["sorunlar"].append("robots.txt OAI ya da PDF yoluna izin vermiyor")
    r["lisans_bulunan"] = "kayit-duzeyinde" if ok_recs else None
    return r


def d_belge_listesi(net: Polite, name: str, spec: dict, pdf_to_text=None) -> dict:
    r = {"tur": "belge_listesi", "sorunlar": [], "lisans_beklenen": spec["lisans"], "lisans_bulunan": spec["lisans"],
         "lisans_notu": "yasal istisna (FSEK md.31); sahip kararıyla dahil"}
    r["robots"] = robots_info(net, spec["kok"])
    g, err = _safe(net.get, spec["kok"])
    r["kok_durum"] = g.status if g else err
    captcha = bool(g is not None and b"captcha" in g.body.lower())
    sample = None
    if spec.get("url_sablonu"):
        n = spec.get("ornek_n") or (spec.get("aralik") or [1])[0]
        sample = spec["url_sablonu"].format(n=n)
        r["robots_ornek"] = robots_info(net, sample)
        s, err = _safe(net.get, sample)
        r["ornek_durum"] = s.status if s else err
        if s is not None and s.status == 200:
            captcha = captcha or b"captcha" in s.body[:200000].lower()
            r["ornek_tur"] = "pdf" if s.body.startswith(b"%PDF") else s.headers.get("content-type")
            if s.body.startswith(b"%PDF") and pdf_to_text:
                t = pdf_to_text(s.body)
                r["ornek_metin"] = {"karakter": len(t), "bas": t[:300], "turkce_puan": turkish_score(t)}
        else:
            r["sorunlar"].append(f"örnek belge alınamadı ({r['ornek_durum']}); URL şablonu yanlış olabilir")
    elif not spec.get("url_listesi"):
        r["sorunlar"].append("url_listesi yok (adres listesi elle hazırlanmalı)")
    r["captcha"] = captcha
    if captcha:
        r["sorunlar"].append("CAPTCHA görüldü: otomatik toplama yapılmaz")
    if not r["robots"]["izin"] or (r.get("robots_ornek") and not r["robots_ornek"]["izin"]):
        r["sorunlar"].append("robots.txt izin vermiyor")
    return r


DETECTORS = {"wikidump": d_wikidump, "arsiv": d_arsiv, "dergipark": d_dergipark, "belge_listesi": d_belge_listesi}
COURT_SITES = ["https://karararama.yargitay.gov.tr/", "https://karararama.danistay.gov.tr/", "https://emsal.uyap.gov.tr/",
               "https://www.resmigazete.gov.tr/"]


def d_math(net: Polite, key: str, spec: dict, gh_headers: dict) -> dict:
    r = {"sorunlar": [], "lisans_beklenen": spec.get("lisans")}
    if spec.get("lisans_url"):
        g, err = _safe(net.get, spec["lisans_url"])
        r["lisans_bulunan"] = license_of_text(g.text()) if g is not None and g.status == 200 else None
        r["lisans_adres_durum"] = g.status if g else err
        if r["lisans_bulunan"] != spec.get("lisans"):
            r["sorunlar"].append(f"LICENSE '{r['lisans_bulunan']}', beklenen '{spec.get('lisans')}'")
    if spec.get("veri_url"):
        h, err = _safe(net.head, spec["veri_url"])
        size = int(h.headers.get("content-length") or 0) if h is not None and h.status == 200 else None
        r["veri"] = {"adres": spec["veri_url"], "durum": h.status if h else err, "boyut_bayt": size}
        if size and size <= SMALL:
            g, err = _safe(net.get, spec["veri_url"])
            if g is not None and g.status == 200:
                r["veri"]["sha256"] = hashlib.sha256(g.body).hexdigest()   # translate_data SOURCES'a sabitlemek için
    if spec.get("pypi"):
        g, err = _safe(net.get, spec["pypi"])
        if g is not None and g.status == 200:
            info = json.loads(g.body).get("info", {})
            r["pypi"] = {"surum": info.get("version"), "lisans": info.get("license"),
                         "siniflar": [c for c in info.get("classifiers", []) if "License" in c]}
    if spec.get("risk"):
        r["sorunlar"].append(spec["risk"])
    if key == "openstax":
        o = d_openstax(net, spec, gh_headers)
        if o.pop("sorunlar_ek", None):
            r["sorunlar"].append("izinli (CC BY) kitap bulunamadı")
        r.update(o)
    r["durum"] = "gecti" if not r["sorunlar"] else "inceleme"
    return r


def d_openstax(net: Polite, spec: dict, gh_headers: dict) -> dict:
    repos = list(spec.get("depolar") or [])
    g, err = _safe(net.get, "https://api.github.com/orgs/openstax/repos?per_page=100&type=public", gh_headers)
    if g is not None and g.status == 200:
        names = [x["name"] for x in json.loads(g.body) if x["name"].startswith("osbooks-")]
        repos += [n for n in names if n not in repos and re.search(r"math|algebra|calc|stat|trig|precalc", n)]
    books = []
    for repo in repos:
        c, err = _safe(net.get, f"https://api.github.com/repos/openstax/{repo}/contents/collections", gh_headers)
        if c is None or c.status != 200:
            books.append({"depo": repo, "hata": err or c.status})
            continue
        for f in json.loads(c.body):
            if not f["name"].endswith(".collection.xml"):
                continue
            x, err = _safe(net.get, f["download_url"])
            t = x.text() if x is not None and x.status == 200 else ""
            lic = re.search(r'<md:license[^>]*url="([^"]+)"', t)
            title = re.search(r"<md:title>([^<]+)</md:title>", t)
            spdx = classify_rights([lic.group(1)]) if lic else None
            books.append({"depo": repo, "koleksiyon": f["name"], "baslik": title.group(1) if title else None,
                          "lisans": spdx, "izinli": spdx in ("cc-by-4.0", "cc-by-sa-4.0")})
    izinli = [b for b in books if b.get("izinli")]
    out = {"kitaplar": books, "izinli_kitap": len(izinli)}
    if not izinli:
        out["sorunlar_ek"] = "izinli (CC BY) kitap bulunamadı"
    return out


def discover(cfg: dict, net: Polite | None = None, only: list[str] | None = None, pdf_to_text=None,
             n_journals: int | None = None) -> dict:
    net = net or Polite(cfg["user_agent"], float(cfg.get("istek_araligi_sn", 1.0)))
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    gh = {"Authorization": f"Bearer {tok}"} if tok else {}
    rep = {"tarih": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "arac": "orion_core.corpus discover",
           "toplu_indirme": False, "user_agent": cfg["user_agent"], "kaynaklar": {}, "matematik": {}, "ek": {}}
    for name, spec in cfg["kaynaklar"].items():
        if only and name not in only:
            continue
        print(f"keşif: {name}", flush=True)
        fn = DETECTORS[spec["tur"]]
        kw = {}
        if spec["tur"] == "dergipark":
            kw = {"n_journals": n_journals, "pdf_to_text": pdf_to_text}
        elif spec["tur"] == "belge_listesi":
            kw = {"pdf_to_text": pdf_to_text}
        try:
            r = fn(net, name, spec, **kw)
        except Exception as e:
            r = {"sorunlar": [f"keşif hatası: {type(e).__name__}: {e}"]}
        r["durum"] = "gecti" if not r.get("sorunlar") else "inceleme"
        r["config_enabled"] = spec.get("enabled", False)
        rep["kaynaklar"][name] = r
    if not only or "matematik" in only:
        for key, spec in (cfg.get("matematik") or {}).items():
            if key.startswith("_"):
                continue
            print(f"keşif: matematik/{key}", flush=True)
            try:
                rep["matematik"][key] = d_math(net, key, spec, gh)
            except Exception as e:
                rep["matematik"][key] = {"durum": "inceleme", "sorunlar": [f"{type(e).__name__}: {e}"]}
        rep["ek"]["yargi_siteleri_robots"] = [robots_info(net, u) for u in COURT_SITES]
    rep["istek_sayisi"] = len(net.log)
    rep["ozet"] = {n: r["durum"] for n, r in rep["kaynaklar"].items()} | {f"matematik/{k}": v["durum"] for k, v in rep["matematik"].items()}
    return rep
