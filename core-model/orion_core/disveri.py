"""Komut beyni için ek İngilizce insan yazımı veri (2026-11-19, sahibin onayı: "başka veriler var mı bak, iş yapacak;
yalnız Emma değil, diğer ajanlar ve EkBot da"). CLINC150 hattının (clinc.py) aynısı: indir → lisansı KAYNAĞINDAN denetle →
niyet eşle → çevir (opus-mt-tc-big, gidiş-dönüş chrF) → ölçüm cümleleriyle çakışanı at. Model üretimi veri yok.

Kaynaklar ve lisanslar (depodaki lisans dosyasından; iş her çalışmada yeniden denetler, tutmazsa o kaynak ATLANIR):
 - Banking77 (PolyAI, CC BY 4.0): bankacılık istekleri → Orion yapamaz (Chloe'nin alanına yakın; yanlış işi azaltır).
   Kur/döviz kategorileri atlanır: EkBot'un kripto fiyat komutuyla karışır (CLINC exchange_rate dersi).
 - SNIPS (Sonos nlu-benchmark, CC0 1.0): hava, müzik, rezervasyon, kitap/film arama → Orion yapamaz.
 - SGD (Google Schema-Guided Dialogue, CC BY-SA 4.0): diyaloğun ilk kullanıcı cümlesi; Orion'un yapamadığı hizmetler
   (uçuş, otel, restoran, araç, banka...) → Orion yapamaz. Takvim/Alarm/Mesaj hizmetleri atlanır (Orion'da karşılığı var,
   argümanı çeviride güvenle taşınamaz).
 - TOPv2 (Meta, alarm/hatırlatıcı/zamanlayıcı/mesaj/etkinlik/hava/müzik/yol): yalnız Orion'un YAPAMADIĞI niyetler
   (alarmı değiştir/sil/sustur/ertele, hatırlatıcıyı sil/değiştir, zamanlayıcıyı duraklat, hava, müzik, yol, etkinlik
   arama) → Orion yapamaz. Lisansın CC BY-SA olduğu yalnız ikincil kaynakta yazıyor: arşivde lisans metni yoksa TOPv2
   kullanılmaz ("doğrulanmadı").
Yalnız "ask" (yapılamayan istek) satırları üretilir: CLINC deneyi (2026-11-17) eylem satırlarının belirsiz cümleleri işe
çektiğini gösterdi. CC BY-SA kaynakların türevi (çeviri) aynı lisansla yayınlanır; atıf LISANS-ATIF.md'de.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import random
import re
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

OUT_NAME = "dis-tr.jsonl"
RAW = "https://raw.githubusercontent.com/"
BANKING = {"data": RAW + "PolyAI-LDN/task-specific-datasets/master/banking_data/train.csv",
           "license": RAW + "PolyAI-LDN/task-specific-datasets/master/LICENSE", "mark": "Attribution 4.0 International"}
SNIPS = {"base": RAW + "sonos/nlu-benchmark/master/2017-06-custom-intent-engines/",
         "license": RAW + "sonos/nlu-benchmark/master/LICENSE", "mark": "CC0 1.0 Universal",
         "intents": ["AddToPlaylist", "BookRestaurant", "GetWeather", "PlayMusic", "RateBook", "SearchCreativeWork",
                     "SearchScreeningEvent"]}
SGD = {"base": RAW + "google-research-datasets/dstc8-schema-guided-dialogue/master/train/",
       "license": RAW + "google-research-datasets/dstc8-schema-guided-dialogue/master/LICENSE.txt",
       "mark": "Attribution-ShareAlike 4.0 International", "files": 40}
TOPV2 = {"zip": "https://dl.fbaipublicfiles.com/TOPv2/TOPv2_Dataset.zip", "mark": "Attribution-ShareAlike"}
# 2026-11-20 (sahibin onayı): Multi3WOZ Türkçe (insan yazımı, kültüre uyarlanmış; ÇEVİRİSİZ), NLU++, Taskmaster-2
MULTI3WOZ = {"zip": RAW + "cambridgeltl/multi3woz/main/data.zip", "license": RAW + "cambridgeltl/multi3woz/main/LICENSE",
             "mark": "MIT License", "member": "data/Turkish/data.json"}
NLUPP = {"base": RAW + "PolyAI-LDN/task-specific-datasets/master/nlupp/data/", "license": BANKING["license"],
         "mark": "Attribution 4.0 International", "domains": ["banking", "hotels"], "folds": 20}
TM2 = {"base": RAW + "google-research-datasets/Taskmaster/master/TM-2-2020/data/",
       "license": RAW + "google-research-datasets/Taskmaster/master/TM-2-2020/README.md",
       "mark": "Creative Commons Attribution 4.0",
       "files": ["flights", "food-ordering", "hotels", "movies", "music", "restaurant-search", "sports"]}

# Kaynak başına üst sınır (çeviri süresi ve havuz dengesi)
CAP = {"banking77": 2500, "snips": 3000, "sgd": 3000, "topv2": 4000, "multi3woz": 3000, "multi3woz_chat": 800, "nlupp": 1500, "tm2": 2500}
# NLU++: tarih/saat taşıyan satırlar alınmaz ("yarın 7'de" kalıbı "yapamaz" diye öğretilirse hatırlatıcı tanıma bozulur)
NLUPP_TIME_SLOTS = {"date", "date_from", "date_to", "date_period", "time", "time_from", "time_to"}
MULTI3WOZ_CHAT_ACTS = ("general-thank", "general-bye", "general-greet")

BANKING_SKIP = {"exchange_rate", "exchange_via_app", "exchange_charge", "fiat_currency_support", "supported_cards_and_currencies"}
SGD_SKIP_PREFIX = ("Calendar", "Alarm", "Messaging")
# TOPv2: Orion'un yapamadığı niyetler (köşeli ayraçlı ayrıştırmanın en dış niyeti)
TOPV2_NEG = {
    "IN:UPDATE_ALARM", "IN:DELETE_ALARM", "IN:SILENCE_ALARM", "IN:SNOOZE_ALARM", "IN:RESUME_ALARM",
    "IN:DELETE_REMINDER", "IN:UPDATE_REMINDER", "IN:UPDATE_REMINDER_DATE_TIME", "IN:UPDATE_REMINDER_TODO",
    "IN:PAUSE_TIMER", "IN:RESUME_TIMER", "IN:RESTART_TIMER", "IN:ADD_TIME_TIMER", "IN:SUBTRACT_TIME_TIMER", "IN:DELETE_TIMER",
    "IN:UPDATE_TIMER",
    "IN:GET_WEATHER", "IN:GET_SUNRISE", "IN:GET_SUNSET",
    "IN:PLAY_MUSIC", "IN:PAUSE_MUSIC", "IN:SKIP_TRACK_MUSIC", "IN:PREVIOUS_TRACK_MUSIC", "IN:LIKE_MUSIC", "IN:DISLIKE_MUSIC",
    "IN:REPLAY_MUSIC", "IN:LOOP_MUSIC", "IN:STOP_MUSIC", "IN:CREATE_PLAYLIST_MUSIC", "IN:ADD_TO_PLAYLIST_MUSIC",
    "IN:REMOVE_FROM_PLAYLIST_MUSIC", "IN:START_SHUFFLE_MUSIC", "IN:SET_DEFAULT_PROVIDER_MUSIC",
    "IN:GET_ESTIMATED_DURATION", "IN:GET_ESTIMATED_ARRIVAL", "IN:GET_DIRECTIONS", "IN:GET_DISTANCE", "IN:GET_INFO_TRAFFIC",
    "IN:GET_ESTIMATED_DEPARTURE", "IN:UPDATE_DIRECTIONS", "IN:GET_INFO_ROAD_CONDITION", "IN:GET_LOCATION",
    "IN:GET_EVENT", "IN:GET_EVENT_ATTENDEE", "IN:GET_EVENT_ORGANIZER",
    "IN:REACT_MESSAGE", "IN:IGNORE_MESSAGE", "IN:GET_GROUP",
}
# EkBot'un kripto komutuyla karışabilecek cümleler hiç girmez
CRYPTO = re.compile(r"\b(bitcoin|btc|eth(ereum)?|crypto|coin|doge|solana|xrp)\b", re.I)


def _get(url: str, timeout: int = 120) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def _license_ok(url: str, mark: str) -> bool:
    try:
        return mark in _get(url, 60).decode("utf-8", "replace")[:600]
    except Exception:
        return False


def _row(source: str, en: str, intent: str, kind: str = "neg", tr: str | None = None) -> dict | None:
    en = " ".join(str(en).split()).strip()
    if not en or len(en) < 4 or CRYPTO.search(en) or (tr is not None and CRYPTO.search(tr)):
        return None
    r = {"en": en, "intent": intent, "cmd": "ask", "args": {}, "kind": kind, "source": source}
    if tr is not None:
        r["tr"] = " ".join(str(tr).split()).strip()  # Türkçe aslı: çeviri yapılmaz
    return r


def parse_multi3woz(data: dict) -> tuple[list[dict], list[dict]]:
    """(yapılamayan istekler, sohbet): diyaloğun ilk kullanıcı cümlesi + teşekkür/selam/veda cümleleri. Ara cümleler
    (bağlama bağlı: "hayır, ucuz olsun") alınmaz."""
    import ast
    neg, chat = [], []
    for did, d in data.items():
        for i, t in enumerate(d.get("log") or []):
            if t.get("speaker") != "USER" or not t.get("text"):
                continue
            a = t.get("dialog_act") or {}
            try:
                acts = a if isinstance(a, dict) else ast.literal_eval(a)
            except Exception:
                acts = {}
            names = list(acts.keys()) if isinstance(acts, dict) else []
            if names and all(n.startswith(MULTI3WOZ_CHAT_ACTS) for n in names):
                r = _row("multi3woz", t.get("en_text") or t["text"], names[0], "chat", t["text"])
                if r:
                    chat.append(r)
            elif i == 0:
                r = _row("multi3woz", t.get("en_text") or t["text"], names[0] if names else "ilk", "neg", t["text"])
                if r:
                    neg.append(r)
    return neg, chat


def parse_nlupp(domain: str, items: list) -> list[dict]:
    out = []
    for e in items:
        if not e.get("intents") or NLUPP_TIME_SLOTS & set((e.get("slots") or {}).keys()):
            continue
        r = _row("nlupp", e.get("text", ""), domain + ":" + "+".join(e["intents"][:3]))
        if r:
            out.append(r)
    return out


def parse_tm2(name: str, dialogues: list) -> list[dict]:
    out = []
    for d in dialogues:
        u = next((x for x in d.get("utterances", []) if x.get("speaker") == "USER" and x.get("text")), None)
        if u:
            r = _row("tm2", u["text"], name)
            if r:
                out.append(r)
    return out


def parse_banking(text: str) -> list[dict]:
    out = []
    for rec in csv.DictReader(io.StringIO(text)):
        if rec.get("category") in BANKING_SKIP:
            continue
        r = _row("banking77", rec.get("text", ""), rec.get("category", ""))
        if r:
            out.append(r)
    return out


def parse_snips(intent: str, doc: dict) -> list[dict]:
    out = []
    for ex in doc.get(intent, []):
        r = _row("snips", "".join(p.get("text", "") for p in ex.get("data", [])), intent)
        if r:
            out.append(r)
    return out


def parse_sgd(dialogues: list) -> list[dict]:
    out = []
    for d in dialogues:
        if any(s.startswith(SGD_SKIP_PREFIX) for s in d.get("services", [])):
            continue
        turns = d.get("turns") or []
        if not turns or turns[0].get("speaker") != "USER":
            continue
        fr = (turns[0].get("frames") or [{}])[0]
        r = _row("sgd", turns[0].get("utterance", ""), f"{fr.get('service', '?')}/{fr.get('state', {}).get('active_intent', '?')}")
        if r:
            out.append(r)
    return out


TOP_INTENT = re.compile(r"^\[\s*(IN:[A-Z_]+)")


def parse_topv2(tsv: str) -> list[dict]:
    out = []
    for i, line in enumerate(tsv.splitlines()):
        parts = line.split("\t")
        if len(parts) < 3 or (i == 0 and parts[0] == "domain"):
            continue
        m = TOP_INTENT.match(parts[2].strip())
        if not m or m.group(1) not in TOPV2_NEG:
            continue
        # İç içe ikinci bir niyet varsa (ör. hava + hatırlatıcı) belirsiz: atla
        if parts[2].count("[IN:") > 1:
            continue
        r = _row("topv2", parts[1], m.group(1))
        if r:
            out.append(r)
    return out


def _cap(rows: list[dict], n: int, rng: random.Random) -> list[dict]:
    seen, uniq = set(), []
    for r in rows:
        k = (r.get("tr") or r["en"]).lower()  # Türkçe aslı varsa tekilleştirme Türkçe metne göre
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    rng.shuffle(uniq)
    return uniq[:n]


def build(out: Path) -> tuple[list[dict], Counter, dict]:
    rng = random.Random(20261119)
    rows, stats, lic = [], Counter(), {}

    if _license_ok(BANKING["license"], BANKING["mark"]):
        lic["banking77"] = "CC BY 4.0 (doğrulandı)"
        rows += _cap(parse_banking(_get(BANKING["data"]).decode("utf-8")), CAP["banking77"], rng)
    else:
        lic["banking77"] = "lisans doğrulanamadı: atlandı"

    if _license_ok(SNIPS["license"], SNIPS["mark"]):
        lic["snips"] = "CC0 1.0 (doğrulandı)"
        sn = []
        for it in SNIPS["intents"]:
            try:
                sn += parse_snips(it, json.loads(_get(f"{SNIPS['base']}{it}/train_{it}_full.json").decode("utf-8", "replace")))
            except Exception as e:
                stats[f"snips-hata:{it}"] += 1
                print("SNIPS", it, e)
        rows += _cap(sn, CAP["snips"], rng)
    else:
        lic["snips"] = "lisans doğrulanamadı: atlandı"

    if _license_ok(SGD["license"], SGD["mark"]):
        lic["sgd"] = "CC BY-SA 4.0 (doğrulandı)"
        sg = []
        for k in range(1, SGD["files"] + 1):
            try:
                sg += parse_sgd(json.loads(_get(f"{SGD['base']}dialogues_{k:03d}.json")))
            except Exception as e:
                stats["sgd-hata"] += 1
                print("SGD", k, e)
        rows += _cap(sg, CAP["sgd"], rng)
    else:
        lic["sgd"] = "lisans doğrulanamadı: atlandı"

    try:
        z = zipfile.ZipFile(io.BytesIO(_get(TOPV2["zip"], 300)))
        names = z.namelist()
        lic_txt = "".join(z.read(n).decode("utf-8", "replace")[:2000] for n in names if re.search(r"licen[cs]e", n, re.I))
        if TOPV2["mark"] in lic_txt:
            lic["topv2"] = "CC BY-SA (arşivdeki lisans metninden doğrulandı)"
            tp = []
            for n in names:
                if n.endswith("_train.tsv"):
                    tp += parse_topv2(z.read(n).decode("utf-8", "replace"))
            rows += _cap(tp, CAP["topv2"], rng)
        else:
            lic["topv2"] = "arşivde lisans metni yok: doğrulanmadı, atlandı"
    except Exception as e:
        lic["topv2"] = f"indirilemedi ({type(e).__name__}): atlandı"

    if _license_ok(MULTI3WOZ["license"], MULTI3WOZ["mark"]):
        lic["multi3woz"] = "MIT (depodaki LICENSE'tan doğrulandı; veri için ayrı lisans yok)"
        try:
            z = zipfile.ZipFile(io.BytesIO(_get(MULTI3WOZ["zip"], 600)))
            neg, chat = parse_multi3woz(json.loads(z.read(MULTI3WOZ["member"]).decode("utf-8")))
            rows += _cap(neg, CAP["multi3woz"], rng) + _cap(chat, CAP["multi3woz_chat"], rng)
        except Exception as e:
            lic["multi3woz"] += f"; indirilemedi ({type(e).__name__})"
    else:
        lic["multi3woz"] = "lisans doğrulanamadı: atlandı"

    if _license_ok(NLUPP["license"], NLUPP["mark"]):
        lic["nlupp"] = "CC BY 4.0 (doğrulandı)"
        nl = []
        for dom in NLUPP["domains"]:
            for k in range(NLUPP["folds"]):
                try:
                    nl += parse_nlupp(dom, json.loads(_get(f"{NLUPP['base']}{dom}/fold{k}.json")))
                except Exception:
                    stats["nlupp-hata"] += 1
        rows += _cap(nl, CAP["nlupp"], rng)
    else:
        lic["nlupp"] = "lisans doğrulanamadı: atlandı"

    try:
        tm_ok = TM2["mark"] in _get(TM2["license"], 60).decode("utf-8", "replace")
    except Exception:
        tm_ok = False
    if tm_ok:
        lic["tm2"] = "CC BY 4.0 (TM-2-2020 README'sinden doğrulandı)"
        tm = []
        for name in TM2["files"]:
            try:
                tm += parse_tm2(name, json.loads(_get(f"{TM2['base']}{name}.json", 600)))
            except Exception:
                stats["tm2-hata"] += 1
        rows += _cap(tm, CAP["tm2"], rng)
    else:
        lic["tm2"] = "lisans doğrulanamadı: atlandı"

    for i, r in enumerate(rows):
        r["id"] = f"dis-{i}"
        stats[f"{r['source']}"] += 1
    out.mkdir(parents=True, exist_ok=True)
    (out / "dis-en.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    (out / "dis-lisans.json").write_text(json.dumps(lic, ensure_ascii=False, indent=1), encoding="utf-8")
    return rows, stats, lic


ATTRIBUTION = """Multi3WOZ satırları Türkçe aslıdır (çeviri yok). Diğerleri Türkçeye makine çevirisi (opus-mt-tc-big-en-tr, CC BY 4.0); yalnız "Orion bunu yapamaz" satırları. Değiştirilmiş türevler.
- Banking77: Casanueva vd. 2020, https://github.com/PolyAI-LDN/task-specific-datasets, CC BY 4.0
- SNIPS: Coucke vd. 2018, https://github.com/sonos/nlu-benchmark, CC0 1.0
- Schema-Guided Dialogue: Rastogi vd. 2020, https://github.com/google-research-datasets/dstc8-schema-guided-dialogue, CC BY-SA 4.0
  (bu kaynaktan türeyen satırlar CC BY-SA 4.0 ile paylaşılır)
- Multi3WOZ: Hu vd. 2023, https://github.com/cambridgeltl/multi3woz, MIT (Türkçe, insan yazımı, kültüre uyarlanmış)
- NLU++: Casanueva vd. 2022, https://github.com/PolyAI-LDN/task-specific-datasets, CC BY 4.0
- Taskmaster-2: Byrne vd. 2020, https://github.com/google-research-datasets/Taskmaster, CC BY 4.0
- TOPv2: Chen vd. 2020, https://fb.me/TOPv2Dataset, CC BY-SA (yalnız arşivdeki lisans metniyle doğrulandıysa kullanıldı;
  dis-lisans.json'a bakın)"""


def main(argv=None) -> None:
    from . import clinc
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--out", required=True)
    t = sub.add_parser("translate")
    t.add_argument("--rows", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--ct2", required=True)
    t.add_argument("--ct2-back")
    t.add_argument("--threads", type=int, default=4)
    a = ap.parse_args(argv)
    if a.cmd == "build":
        rows, stats, lic = build(Path(a.out))
        print(f"dış veri: {len(rows)} satır", dict(stats), json.dumps(lic, ensure_ascii=False))
        if not rows:
            raise SystemExit("dış veri: hiçbir kaynak lisans denetiminden geçmedi")
        return
    import gzip
    from .translate_data import Ct2Translator, MT_MODEL, BT_MODEL
    rows = [json.loads(x) for x in Path(a.rows).read_text(encoding="utf-8").splitlines() if x.strip()]
    # Türkçe aslı olan satırlar (Multi3WOZ) çevrilmez; yalnız İngilizceler çevrilir
    need = [i for i, r in enumerate(rows) if not r.get("tr")]
    mt = Ct2Translator(a.ct2, MT_MODEL, threads=a.threads)([rows[i]["en"] for i in need]) if need else []
    tr = [r.get("tr") for r in rows]
    for i, t in zip(need, mt):
        tr[i] = t
    back = None
    if a.ct2_back and need:
        bt = Ct2Translator(a.ct2_back, BT_MODEL, threads=a.threads)([tr[i] for i in need])
        back = [None] * len(rows)
        for i, b in zip(need, bt):
            back[i] = b
    out_rows, stats = clinc.finish(rows, tr, back)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with gzip.open(out / (OUT_NAME + ".gz"), "wt", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out / "dis-stats.json").write_text(json.dumps({"satir": len(out_rows), "dagilim": dict(stats.most_common())},
                                                   ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "LISANS-ATIF-DIS.md").write_text("# Lisans ve atıf (dış veri)\n\n" + ATTRIBUTION + "\n", encoding="utf-8")
    print(f"dış veri tr: {len(out_rows)} satır", json.dumps(dict(stats.most_common(12)), ensure_ascii=False))


if __name__ == "__main__":
    main()
