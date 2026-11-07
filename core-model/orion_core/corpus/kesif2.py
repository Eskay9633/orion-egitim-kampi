"""Yeni kaynak keşfi (sahibin onayı 2026-11-07): kodlama (İngilizce), görsel ve video için aday veri setlerinin
lisansını KAYNAĞIN KENDİ metninden okur, veri adresine erişilebiliyor mu ve boyutu ne, bakar. Toplu indirme yok.
Çıktı: kaynak-kesif.json (her aday: durum gecti | inceleme | erisilemedi, bulunan lisans, kanıt adresi, boyut, not).
Model üretimi (LLM ile yazılmış) veri setleri aday listesine alınmaz."""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request

UA = "OrionDerlem/1.0 (license discovery; https://github.com/Eskay9633/orion-egitim-kampi)"

# lisans_url: lisans metni; veri: erişim/boyut denetlenecek adres(ler); bekle: izin verilen lisans kalıpları
ADAYLAR = {
    # ------------------------------------------------------------------ kodlama
    "stackexchange": dict(tur="kod-soru-cevap", lisans_url="https://archive.org/metadata/stackexchange",
                          veri=["https://archive.org/metadata/stackexchange"], bekle=["cc-by-sa"],
                          not_="Site başına 7z dökümler (archive.org). Yalnız programlama siteleri; ilk aday codereview, "
                               "softwareengineering, unix, cs; stackoverflow çok büyük (ayrıca bakılır)."),
    "mbpp": dict(tur="kod-test", lisans_url="https://raw.githubusercontent.com/google-research/google-research/master/mbpp/README.md",
                 veri=["https://raw.githubusercontent.com/google-research/google-research/master/mbpp/mbpp.jsonl"], bekle=["cc-by-4.0"]),
    "humaneval": dict(tur="kod-sinav", lisans_url="https://raw.githubusercontent.com/openai/human-eval/master/LICENSE",
                      veri=["https://raw.githubusercontent.com/openai/human-eval/master/data/HumanEval.jsonl.gz"], bekle=["mit"],
                      not_="Yalnız sınav; eğitime girmez."),
    "apps": dict(tur="kod-test", lisans_url="https://raw.githubusercontent.com/hendrycks/apps/main/LICENSE",
                 veri=["https://people.eecs.berkeley.edu/~hendrycks/APPS.tar.gz"], bekle=["mit"],
                 not_="Problemler Codeforces/Kattis vb. kaynaklı; veri adresi 403 verirse inceleme."),
    "code-contests": dict(tur="kod-test", lisans_url="https://raw.githubusercontent.com/google-deepmind/code_contests/main/README.md",
                          veri=["https://raw.githubusercontent.com/google-deepmind/code_contests/main/LICENSE"], bekle=["cc-by-4.0", "apache-2.0"],
                          not_="Veri GCS'te (gsutil); README'de veri lisansı CC BY 4.0 olmalı; çözümlerin kaynağı ayrıca bakılır."),
    # ------------------------------------------------------------------ eğitim kodu (yalnız teknik/kod, ağırlık yok)
    "nanogpt": dict(tur="egitim-kodu", lisans_url="https://raw.githubusercontent.com/karpathy/nanoGPT/master/LICENSE",
                    veri=[], bekle=["mit"]),
    "modded-nanogpt": dict(tur="egitim-kodu", lisans_url="https://raw.githubusercontent.com/KellerJordan/modded-nanogpt/master/LICENSE",
                           veri=[], bekle=["mit"], not_="Speedrun teknikleri (Muon vb.)."),
    "muon": dict(tur="egitim-kodu", lisans_url="https://raw.githubusercontent.com/KellerJordan/Muon/master/LICENSE",
                 veri=[], bekle=["mit"]),
    "diffusers": dict(tur="egitim-kodu", lisans_url="https://raw.githubusercontent.com/huggingface/diffusers/main/LICENSE",
                      veri=[], bekle=["apache-2.0"], not_="Görsel modeli için yalnız kod; hazır ağırlık kullanılmaz."),
    "xiaomi-mimo": dict(tur="egitim-kodu", lisans_url="https://raw.githubusercontent.com/XiaomiMiMo/MiMo/main/LICENSE",
                        veri=[], bekle=["apache-2.0", "mit"], not_="Yalnız eğitim tarifi/kodu incelenir; ağırlık alınmaz."),
    # ------------------------------------------------------------------ görsel
    "openmoji": dict(tur="gorsel-ikon", lisans_url="https://raw.githubusercontent.com/hfg-gmuend/openmoji/master/LICENSE.txt",
                     veri=["https://api.github.com/repos/hfg-gmuend/openmoji"], bekle=["cc-by-sa-4.0"]),
    "twemoji": dict(tur="gorsel-ikon", lisans_url="https://raw.githubusercontent.com/jdecked/twemoji/main/LICENSE-GRAPHICS",
                    veri=["https://api.github.com/repos/jdecked/twemoji"], bekle=["cc-by-4.0"]),
    "noto-emoji": dict(tur="gorsel-ikon", lisans_url="https://raw.githubusercontent.com/googlefonts/noto-emoji/main/LICENSE",
                       veri=["https://api.github.com/repos/googlefonts/noto-emoji"], bekle=["apache-2.0", "ofl"],
                       not_="Görseller Apache-2.0, yazı tipi OFL (README'ye göre; doğrulanmalı)."),
    "met-openaccess": dict(tur="gorsel-sanat", lisans_url="https://raw.githubusercontent.com/metmuseum/openaccess/master/README.md",
                           veri=["https://api.github.com/repos/metmuseum/openaccess"], bekle=["cc0"],
                           not_="Yalnız Is Public Domain=True eserler; görseller API ile tek tek (hız sınırı)."),
    "smithsonian-oa": dict(tur="gorsel-sanat", lisans_url="https://www.si.edu/openaccess",
                           veri=[], bekle=["cc0"], not_="API anahtarı gerekir (api.data.gov); sahibin anahtarı Vault'ta olmalı."),
    "open-images": dict(tur="gorsel-genel", lisans_url="https://storage.googleapis.com/openimages/web/factsfigures_v7.html",
                        veri=[], bekle=["cc-by-2.0", "cc-by-4.0"], not_="Görseller Flickr CC BY 2.0 (görsel başına); açıklamalar CC BY 4.0."),
    # ------------------------------------------------------------------ video
    "wikimedia-commons-video": dict(tur="video", lisans_url="https://commons.wikimedia.org/wiki/Commons:Licensing",
                                    veri=[], bekle=["cc-by", "cc0", "public domain"],
                                    not_="Dosya başına lisans; WebM. Kodla üretilen animasyonlar ayrıca (lisans sorunu yok)."),
}

PAT = [
    ("cc-by-nc", r"NonCommercial|CC[- ]BY[- ]NC"),
    ("cc-by-nd", r"NoDerivatives|CC[- ]BY[- ]ND"),
    ("cc-by-sa-4.0", r"Attribution[- ]ShareAlike 4\.0|CC[- ]BY[- ]SA[- ]4\.0|by-sa/4\.0"),
    ("cc-by-sa", r"Attribution[- ]?Share[- ]?Alike|CC[- ]BY[- ]SA|by-sa/"),
    ("cc-by-4.0", r"Attribution 4\.0|CC[- ]BY[- ]4\.0|licenses/by/4\.0"),
    ("cc-by-2.0", r"CC[- ]BY[- ]2\.0|licenses/by/2\.0"),
    ("cc0", r"\bCC0\b|CC-0|publicdomain/zero|Creative Commons Zero"),
    ("mit", r"MIT License|Permission is hereby granted, free of charge"),
    ("apache-2.0", r"Apache License,? Version 2\.0|apache\.org/licenses/LICENSE-2\.0"),
    ("ofl", r"SIL Open Font License|\bOFL\b"),
    ("public domain", r"public domain"),
]


def get(url: str, method: str = "GET", limit: int = 400_000) -> tuple[int, str, dict]:
    req = urllib.request.Request(url, method=method, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read(limit).decode("utf-8", "replace") if method == "GET" else ""
            return r.status, body, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, "", dict(e.headers or {})
    except Exception as e:  # ağ hatası
        return 0, repr(e), {}


def licenses_in(text: str) -> list[str]:
    return [k for k, p in PAT if re.search(p, text or "", re.I)]


def check(name: str, a: dict) -> dict:
    r = {"tur": a["tur"], "lisans_kaniti": a["lisans_url"], "not": a.get("not_", "")}
    code, body, _ = get(a["lisans_url"])
    r["lisans_adres_durum"] = code
    found = licenses_in(body)
    r["lisans_bulunan"] = found
    bad = [f for f in found if f in ("cc-by-nc", "cc-by-nd")]
    ok = [f for f in found if any(f.startswith(b) or b.startswith(f) for b in a["bekle"])]
    r["veri"] = []
    for u in a["veri"]:
        c, b, h = get(u, "HEAD") if not u.startswith("https://api.github.com") and "metadata" not in u else get(u)
        item = {"adres": u, "durum": c, "boyut_bayt": int(h["Content-Length"]) if h.get("Content-Length", "").isdigit() else None}
        if u.startswith("https://api.github.com") and b:
            try:
                j = json.loads(b)
                item.update(depo_lisans=(j.get("license") or {}).get("spdx_id"), depo_boyut_kb=j.get("size"))
            except ValueError:
                pass
        if "archive.org/metadata" in u and b:
            try:
                j = json.loads(b)
                lic = (j.get("metadata") or {}).get("licenseurl", "")
                item["licenseurl"] = lic
                files = [f for f in j.get("files", []) if f.get("name", "").endswith(".7z")]
                item["dosya_sayisi"] = len(files)
                prog = [f for f in files if re.match(r"(codereview|softwareengineering|unix|cs|stackoverflow)\.", f["name"])]
                item["programlama_dosyalari"] = [{"ad": f["name"], "boyut": int(f.get("size", 0))} for f in prog][:30]
                if lic:
                    found += licenses_in(lic.replace("by-sa", "CC BY SA"))
                    r["lisans_bulunan"] = sorted(set(found))
                    ok = [f for f in r["lisans_bulunan"] if any(f.startswith(b_) or b_.startswith(f) for b_ in a["bekle"])]
            except ValueError:
                pass
        r["veri"].append(item)
        time.sleep(1)
    veri_ok = all(v["durum"] in (200, 302) for v in r["veri"]) if r["veri"] else True
    if bad:
        r["durum"] = "red (ticari olmayan/türetilemez)"
    elif code != 200:
        r["durum"] = "erisilemedi"
    elif ok and veri_ok:
        r["durum"] = "gecti"
    else:
        r["durum"] = "inceleme"
    return r


def main(out: str) -> None:
    rep = {"tarih": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "kaynaklar": {}}
    for name, a in ADAYLAR.items():
        rep["kaynaklar"][name] = check(name, a)
        print(name, rep["kaynaklar"][name]["durum"], rep["kaynaklar"][name]["lisans_bulunan"], flush=True)
        time.sleep(1)
    rep["ozet"] = {k: v["durum"] for k, v in rep["kaynaklar"].items()}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "kaynak-kesif.json")
