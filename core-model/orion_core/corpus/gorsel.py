"""Görsel verisi, ilk adım (sahibin isteği: görsel üretmeye hazırlık): açık lisanslı emoji/ikon görselleri + Türkçe adları.

Kaynaklar (lisanslar kaynak keşfinde denetlendi, iş akışı çalışırken lisans metni yeniden aranır):
- Twemoji grafikleri (jdecked/twemoji, assets/72x72): CC BY 4.0 — atıf: "Twemoji, © Twitter/X ve katkıda bulunanlar, CC BY 4.0".
- OpenMoji (hfg-gmuend/openmoji, 72x72 renkli): CC BY-SA 4.0 — atıf: "OpenMoji, HfG Schwäbisch Gmünd, CC BY-SA 4.0".
- Türkçe adlar: Unicode CLDR common/annotations/tr.xml (+ annotationsDerived): Unicode License v3.
- Noto Emoji: lisans keşifte netleşmedi (görseller Apache-2.0 mı, yazı tipi OFL mi) → doğrulanmadı, ALINMAZ.

Çıktı satırı (jsonl.gz, "gorsel-ikon" Release'i; derlem-* DEĞİL, metin derlemine karışmaz):
{"id", "kaynak", "lisans", "attribution", "emoji", "kod", "ad_tr", "anahtar_tr", "png_b64", "boyut",
 "training_allowed": true, "model_uretimi": false}. Türkçe adı olmayan görsel alınmaz (görsel + metin çifti şart)."""
from __future__ import annotations

import base64
import gzip
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

SOURCES = {
    "twemoji": {"lisans": "cc-by-4.0", "attribution": "Twemoji grafikleri © Twitter/X ve katkıda bulunanlar (jdecked/twemoji), CC BY 4.0"},
    "openmoji": {"lisans": "cc-by-sa-4.0",
                 "attribution": "OpenMoji, HfG Schwäbisch Gmünd ve katkıda bulunanlar (openmoji.org), CC BY-SA 4.0"},
}
NAMES_ATTRIBUTION = "Türkçe adlar: Unicode CLDR (unicode-org/cldr), Unicode License v3"
# Lisans metninde aranan ifadeler (iş akışında indirilen LICENSE dosyalarında)
LICENSE_MARKERS = {
    "twemoji": [r"creativecommons\.org/licenses/by/4\.0", r"CC[- ]BY 4\.0", r"Attribution 4\.0"],
    "openmoji": [r"CC[- ]BY[- ]SA 4\.0", r"by-sa/4\.0", r"Attribution-ShareAlike 4\.0"],
    "cldr": [r"UNICODE LICENSE V3", r"Unicode License v3", r"Permission is hereby granted, free of charge"],
}


def license_ok(name: str, text: str) -> bool:
    return any(re.search(p, text, re.I) for p in LICENSE_MARKERS[name])


def key(emoji_or_code: str) -> str:
    """Eşleştirme anahtarı: kod noktaları küçük harf onaltılık, '-' ile; FE0F (görünüm seçici) atılır.
    Hem emoji karakterinden ("😀") hem dosya adından ("1F600", "1f468-200d-1f469") çalışır."""
    s = emoji_or_code.strip()
    if re.fullmatch(r"[0-9a-fA-F]{2,6}(-[0-9a-fA-F]{2,6})*", s):
        parts = [p.lower().lstrip("0") or "0" for p in s.split("-")]
    else:
        parts = [f"{ord(c):x}" for c in s]
    return "-".join(p for p in parts if p != "fe0f")


def cldr_names(*xml_paths: Path) -> dict[str, dict]:
    """CLDR annotations XML → {anahtar: {"emoji", "ad_tr", "anahtar_tr"}}. type="tts" ad, diğeri anahtar sözcükler."""
    out: dict[str, dict] = {}
    for p in xml_paths:
        if not p or not Path(p).exists():
            continue
        root = ET.parse(p).getroot()
        for a in root.iter("annotation"):
            cp, txt = a.get("cp"), (a.text or "").strip()
            if not cp or not txt or txt == "↑↑↑":
                continue
            d = out.setdefault(key(cp), {"emoji": cp, "ad_tr": "", "anahtar_tr": []})
            if a.get("type") == "tts":
                d["ad_tr"] = txt
            else:
                d["anahtar_tr"] = [w.strip() for w in txt.split("|") if w.strip()]
    for d in out.values():
        if not d["ad_tr"] and d["anahtar_tr"]:
            d["ad_tr"] = d["anahtar_tr"][0]
    return {k: d for k, d in out.items() if d["ad_tr"]}


def rows_from_dir(source: str, png_dir: Path, names: dict[str, dict], limit: int = 0):
    """Bir kaynaktaki 72x72 PNG'ler → satırlar (yalnız Türkçe adı olanlar)."""
    meta = SOURCES[source]
    n = 0
    for p in sorted(Path(png_dir).glob("*.png")):
        k = key(p.stem)
        nm = names.get(k)
        if nm is None:
            continue
        data = p.read_bytes()
        if not data.startswith(b"\x89PNG"):
            continue
        yield {"id": f"{source}-{k}", "kaynak": source, "lisans": meta["lisans"],
               "attribution": meta["attribution"] + "; " + NAMES_ATTRIBUTION, "emoji": nm["emoji"], "kod": k,
               "ad_tr": nm["ad_tr"], "anahtar_tr": nm["anahtar_tr"], "png_b64": base64.b64encode(data).decode(),
               "boyut": 72, "training_allowed": True, "model_uretimi": False, "kategori": "gorsel-ikon"}
        n += 1
        if limit and n >= limit:
            return


def write(rows, path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


def main(argv=None) -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="orion_core.corpus.gorsel")
    ap.add_argument("--cldr", action="append", required=True, help="CLDR annotations tr.xml (birden çok verilebilir)")
    ap.add_argument("--twemoji", help="72x72 PNG klasörü")
    ap.add_argument("--openmoji", help="72x72 renkli PNG klasörü")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    names = cldr_names(*[Path(x) for x in a.cldr])
    out, st = Path(a.out), {"cldr_ad": len(names)}
    for src, d in (("twemoji", a.twemoji), ("openmoji", a.openmoji)):
        if d:
            st[src] = write(rows_from_dir(src, Path(d), names), out / f"gorsel-{src}.jsonl.gz")
    (out / "gorsel-stats.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(st, ensure_ascii=False))


if __name__ == "__main__":
    main()
