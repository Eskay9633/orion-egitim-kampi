"""Görsel verisi (emoji + Türkçe ad): anahtar eşleştirme, CLDR okuma, yalnız adlı görseller, lisans denetimi."""
import base64
import gzip
import json

from orion_core.corpus import gorsel

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20

XML = """<?xml version="1.0" encoding="UTF-8"?><ldml><annotations>
<annotation cp="😀">gülen yüz | mutlu | sırıtma</annotation>
<annotation cp="😀" type="tts">sırıtan yüz</annotation>
<annotation cp="❤️">kalp | sevgi</annotation>
<annotation cp="👨‍👩‍👧" type="tts">aile: erkek, kadın, kız</annotation>
</annotations></ldml>"""


def test_key_normalizes_fe0f_and_case():
    assert gorsel.key("😀") == gorsel.key("1F600") == gorsel.key("1f600") == "1f600"
    assert gorsel.key("❤️") == gorsel.key("2764") == "2764"
    assert gorsel.key("👨‍👩‍👧") == gorsel.key("1F468-200D-1F469-200D-1F467") == "1f468-200d-1f469-200d-1f467"


def test_rows_only_named_and_valid(tmp_path):
    x = tmp_path / "tr.xml"
    x.write_text(XML, encoding="utf-8")
    names = gorsel.cldr_names(x)
    assert names["1f600"]["ad_tr"] == "sırıtan yüz" and "mutlu" in names["1f600"]["anahtar_tr"]
    assert names["2764"]["ad_tr"] == "kalp"  # tts yoksa ilk anahtar sözcük
    d = tmp_path / "png"
    d.mkdir()
    (d / "1f600.png").write_bytes(PNG)
    (d / "2764-fe0f.png").write_bytes(PNG)
    (d / "1f680.png").write_bytes(PNG)  # adı yok → alınmaz
    (d / "1f468-200d-1f469-200d-1f467.png").write_bytes(b"bozuk")  # PNG değil → alınmaz
    n = gorsel.write(gorsel.rows_from_dir("twemoji", d, names), tmp_path / "o" / "g.jsonl.gz")
    rows = [json.loads(l) for l in gzip.open(tmp_path / "o" / "g.jsonl.gz", "rt", encoding="utf-8")]
    assert n == 2 and {r["kod"] for r in rows} == {"1f600", "2764"}
    r = rows[0]
    assert r["lisans"] == "cc-by-4.0" and r["training_allowed"] is True and r["model_uretimi"] is False
    assert "CLDR" in r["attribution"] and base64.b64decode(r["png_b64"]) == PNG


def test_license_markers():
    assert gorsel.license_ok("twemoji", "licensed under CC-BY 4.0: https://creativecommons.org/licenses/by/4.0/")
    assert gorsel.license_ok("openmoji", "Attribution-ShareAlike 4.0 International")
    assert gorsel.license_ok("cldr", "UNICODE LICENSE V3\nPermission is hereby granted, free of charge")
    assert not gorsel.license_ok("twemoji", "All rights reserved")
