"""CLINC150 → komut beyni için Türkçe dış veri (2026-11-17, sahibin onayı: "sohbet beyninde yaptığımız gibi İngilizce
insan yazımı veriyi çevirelim").

Kaynak: clinc/oos-eval data_full.json (Larson vd. 2019), lisans CC BY 3.0 Unported (depodaki LICENSE dosyasından
doğrulandı; iş her çalışmada LICENSE başlığını ve veri özetini yeniden denetler, tutmazsa durur). 150 niyet + kapsam dışı
(oos), insan yazımı İngilizce istekler. Çeviri: translate_data ile aynı açık çevirmen (opus-mt-tc-big en→tr, gidiş-dönüş
tr→en ile chrF denetimi). Model (ChatGPT vb.) üretimi veri yok.

Niyet eşleme (Orion'un protokolüne):
 - Orion'un yaptığı ve argümansız ya da güvenle çıkarılabilen işler → eylem (action):
   reminder → reminder.list, calendar → calendar.list (gün sözü yoksa ya da bugün/yarın ise), what_can_i_ask_you → help
 - Sohbet niyetleri (selam, şaka, kimsin...) → ask (chat)
 - Orion'un yapamadığı istekler (banka, uçuş, araç, yemek, müzik, hava...) ve kapsam dışı → ask (neg): yanlış işi azaltır
 - Argüman gerektiren ve Orion'da karşılığı olan niyetler (alarm, zamanlayıcı, çeviri, hesap, yapılacaklar...) ATLANIR:
   argümanı çeviride güvenle taşınamaz, yanlış öğretmektense hiç öğretmemek.
Eğitim/ölçüm ayrımı: satırlar massive.load_train ile aynı sızıntı denetiminden geçer (MASSIVE/xSID/elle yazılmış/kör kümeler).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import urllib.request
from collections import Counter
from pathlib import Path

DATA_URL = "https://raw.githubusercontent.com/clinc/oos-eval/master/data/data_full.json"
DATA_SHA256 = "36923c3705a59e08fe9c3883d8bc2dd966ef93e22cb78ac41171782a698d56e0"
LICENSE_URL = "https://raw.githubusercontent.com/clinc/oos-eval/master/LICENSE"
LICENSE_MARK = "Attribution 3.0 Unported"
OUT_NAME = "clinc-tr.jsonl"
ATTRIBUTION = ("CLINC150 (Larson vd., 2019, \"An Evaluation Dataset for Intent Classification and Out-of-Scope Prediction\"), "
               "https://github.com/clinc/oos-eval, CC BY 3.0. Türkçeye makine çevirisi (opus-mt-tc-big-en-tr, CC BY 4.0); "
               "niyetler Orion komutlarına eşlendi. Değiştirilmiş türev.")

ACTION = {"reminder": "reminder.list", "calendar": "calendar.list", "what_can_i_ask_you": "help"}
CHAT = {"greeting", "goodbye", "thank_you", "tell_joke", "fun_fact", "meaning_of_life", "are_you_a_bot", "how_old_are_you",
        "what_is_your_name", "what_are_your_hobbies", "where_are_you_from", "who_made_you", "who_do_you_work_for",
        "do_you_have_pets", "flip_coin", "roll_dice"}
# Orion'da karşılığı olan ama argümanı güvenle taşınamayan ya da belirsiz niyetler: hiç öğretilmez
SKIP = {"alarm", "timer", "reminder_update", "todo_list", "todo_list_update", "shopping_list", "shopping_list_update",
        "calendar_update", "translate", "calculator", "meeting_schedule", "schedule_meeting", "text", "user_name",
        "measurement_conversion", "change_ai_name", "change_user_name", "reset_settings", "sync_device", "repeat",
        "whisper_mode", "change_accent", "change_language", "change_speed", "change_volume", "yes", "no", "maybe", "cancel",
        "spelling", "definition",
        # Para birimi/kur soruları: Orion'un kripto fiyat komutuyla (market.crypto) karışıyor ("bitcoin kaç dolar" → soru)
        "exchange_rate"}
DAY_WORDS = {"today": "d+0", "tonight": "d+0", "tomorrow": "d+1"}
TIME_RE = re.compile(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|weekend|month|january|february|march|"
                     r"april|may|june|july|august|september|october|november|december|next|yesterday|\d)", re.I)


def fetch(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as r:
        dest.write_bytes(r.read())
    return dest


def verify(raw: Path, license_text: str) -> None:
    sha = hashlib.sha256(raw.read_bytes()).hexdigest()
    if sha != DATA_SHA256:
        raise SystemExit(f"CLINC150 özeti tutmuyor: {sha} (beklenen {DATA_SHA256}); iş durdu")
    if LICENSE_MARK not in license_text[:400]:
        raise SystemExit("CLINC150 lisansı beklenen CC BY 3.0 değil; iş durdu")


def label(intent: str, en: str) -> tuple[str, dict, str] | None:
    """(komut, argüman taslağı, tür) ya da None (atla). ask'ın sorusu çeviriden sonra doldurulur."""
    if intent in SKIP:
        return None
    if intent in ACTION:
        cmd = ACTION[intent]
        if cmd == "calendar.list":
            low = en.lower()
            day = next((v for k, v in DAY_WORDS.items() if re.search(rf"\b{k}\b", low)), None)
            if TIME_RE.search(low):
                return None  # başka gün sözü: gün argümanı çeviride güvenle taşınamaz
            return cmd, ({"day": day} if day else {}), "action"
        if TIME_RE.search(en) or any(re.search(rf"\b{k}\b", en.lower()) for k in DAY_WORDS):
            return None
        return cmd, {}, "action"
    return "ask", {}, ("chat" if intent in CHAT else "neg")


def build(data: dict) -> tuple[list[dict], Counter]:
    rows, stats, seen = [], Counter(), set()
    for part in ("train", "val", "test", "oos_train", "oos_val", "oos_test"):
        for en, intent in data.get(part, []):
            en = " ".join(str(en).split())
            if not en or en.lower() in seen:
                stats["tekrar"] += 1
                continue
            seen.add(en.lower())
            lab = label(intent, en)
            if lab is None:
                stats[f"atlandı:{intent}"] += 1
                continue
            cmd, args, kind = lab
            rows.append({"id": f"clinc-{len(rows)}", "en": en, "intent": intent, "cmd": cmd, "args": args, "kind": kind})
            stats[f"{cmd}/{kind}"] += 1
    return rows, stats


def finish(rows: list[dict], tr: list[str], back: list[str] | None) -> tuple[list[dict], Counter]:
    """Çevrilmiş satırlardan eğitim satırları (doğrulayıcıdan ve çeviri süzgecinden geçenler)."""
    from . import translate_data as T
    from .massive import make_row, strip_polite, Skip
    out, stats = [], Counter()
    for i, (r, t) in enumerate(zip(rows, tr)):
        t = " ".join(t.split()).strip()
        native = bool(r.get("tr"))  # Türkçe aslı (çeviri değil): çeviri süzgeçleri uygulanmaz
        why = None if native else T.tr_reject(r["en"], t)
        if why:
            stats[f"süzgeç:{why}"] += 1
            continue
        if not native and back is not None and back[i] is not None and T.chrf(back[i], r["en"]) < 0.30:
            stats["süzgeç:gidiş-dönüş"] += 1
            continue
        args = dict(r["args"])
        if r["cmd"] == "ask":
            args = {"question": strip_polite(t).rstrip("?.! ").strip() or t}
        try:
            src = r.get("source", "clinc150")
            row = make_row(t, r["cmd"], args, kind=r["kind"], intent=("clinc" if src == "clinc150" else src) + ":" + r["intent"],
                           partition="train", source=src)
        except Skip as e:
            stats[f"geçersiz:{e}"] += 1
            continue
        row.update({"training_allowed": True, "origin": "dataset"})
        out.append(row)
        stats[f"{r['cmd']}/{r['kind']}"] += 1
    return out, stats


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="indir, denetle, eşle → İngilizce satırlar")
    b.add_argument("--out", required=True)
    t = sub.add_parser("translate", help="çevir, süz → Türkçe eğitim satırları (gz)")
    t.add_argument("--rows", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--ct2", required=True)
    t.add_argument("--ct2-back")
    t.add_argument("--threads", type=int, default=4)
    a = ap.parse_args(argv)
    if a.cmd == "build":
        out = Path(a.out)
        raw = fetch(DATA_URL, out / "raw" / "data_full.json")
        lic = urllib.request.urlopen(LICENSE_URL, timeout=60).read().decode("utf-8", "replace")
        verify(raw, lic)
        rows, stats = build(json.loads(raw.read_text(encoding="utf-8")))
        (out / "clinc-en.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        (out / "build-stats.json").write_text(json.dumps(dict(stats.most_common()), ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"CLINC150: {len(rows)} satır eşlendi", json.dumps(dict(stats.most_common(12)), ensure_ascii=False))
        return
    from .translate_data import Ct2Translator, MT_MODEL, BT_MODEL
    rows = [json.loads(x) for x in Path(a.rows).read_text(encoding="utf-8").splitlines() if x.strip()]
    mt = Ct2Translator(a.ct2, MT_MODEL, threads=a.threads)
    tr = mt([r["en"] for r in rows])
    back = None
    if a.ct2_back:
        bt = Ct2Translator(a.ct2_back, BT_MODEL, threads=a.threads)
        back = bt(tr)
    out_rows, stats = finish(rows, tr, back)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with gzip.open(out / (OUT_NAME + ".gz"), "wt", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out / "stats.json").write_text(json.dumps({"satir": len(out_rows), "dagilim": dict(stats.most_common())}, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    (out / "LISANS-ATIF.md").write_text("# Lisans ve atıf\n\n" + ATTRIBUTION + "\n", encoding="utf-8")
    print(f"CLINC150 tr: {len(out_rows)} satır", json.dumps(dict(stats.most_common(15)), ensure_ascii=False))


if __name__ == "__main__":
    main()
