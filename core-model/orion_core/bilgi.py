"""Bilgi ve anlama verisi (2026-11-14, sahibin önceliği: "beyni geliştirmek için veri setleri lazım").

Sohbet beyninin zayıf yerleri: bilgi ("Türkiye'nin başkenti" → "Tokyo"), metni anlama ve mantık. Bu üretici GitHub'ın
makinesinde çalışır (bilgi.yml), çıktıyı "diyalog-bilgi" Release'ine koyar; Kaggle oturumu ek diyalog olarak indirir.
Kaynaklar (lisans veri kartından; DOĞRULANMADI, çalışma anında yeniden denetlenmez):
  - Wikidata (CC0-1.0): ülke → başkent / kıta / para birimi; Türkiye illeri → plaka; kimyasal elementler → sembol, numara.
    Gerçekler sabit kalıplarla Türkçe soru-cevaba çevrilir (çok soru biçimi × birkaç cevap biçimi; ters sorular da).
  - XQuAD tr (google/xquad, CC BY-SA 4.0): okuduğunu anlama; bağlamın cevabı içeren cümlesi + soru → cevap.
  - Belebele tur_Latn (facebook/belebele, CC BY-SA 4.0): okuduğunu anlama, dört şıklı.
Sınav soruları ve yakın biçimleri (dialogs.QA_TESTS, near_exam, bilişsel sınav) hiç üretilmez: sınav ezberlenmesin.
Satır biçimi chat.extra_dialogues ile aynı: {"q","a","source","license","training_allowed":true}.
"""
from __future__ import annotations

import gzip
import json
import random
import re
import urllib.parse
import urllib.request
from pathlib import Path

UA = {"User-Agent": "orion-egitim/1.0 (open-source training data builder)", "Accept": "application/sparql-results+json"}
SPARQL = "https://query.wikidata.org/sparql"

# ------------------------------------------------------------------ Wikidata sorguları (etiketler Türkçe)
Q_COUNTRY = """SELECT ?cL ?capL ?contL ?curL WHERE {
 ?c wdt:P31 wd:Q6256 . FILTER NOT EXISTS { ?c wdt:P576 ?end }
 ?c rdfs:label ?cL FILTER(lang(?cL)='tr')
 OPTIONAL { ?c wdt:P36 ?cap . ?cap rdfs:label ?capL FILTER(lang(?capL)='tr') }
 OPTIONAL { ?c wdt:P30 ?cont . ?cont rdfs:label ?contL FILTER(lang(?contL)='tr') }
 OPTIONAL { ?c wdt:P38 ?cur . ?cur rdfs:label ?curL FILTER(lang(?curL)='tr') } }"""
Q_PROVINCE = """SELECT ?pL ?plate WHERE { ?p wdt:P31 wd:Q48336 ; wdt:P395 ?plate .
 ?p rdfs:label ?pL FILTER(lang(?pL)='tr') }"""
Q_ELEMENT = """SELECT ?eL ?sym ?num WHERE { ?e wdt:P31 wd:Q11344 ; wdt:P246 ?sym ; wdt:P1086 ?num .
 ?e rdfs:label ?eL FILTER(lang(?eL)='tr') }"""


def sparql(q: str) -> list[dict]:
    import time
    import urllib.error
    url = SPARQL + "?" + urllib.parse.urlencode({"query": q, "format": "json"})
    req = urllib.request.Request(url, headers=UA)
    # Wikidata sorgu hizmeti zaman zaman dakikada bir isteğe iner (HTTP 429): bekleyip yeniden dene (en çok 4 kez)
    for attempt in range(4):
        try:
            data = json.loads(urllib.request.urlopen(req, timeout=120).read())
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 3:
                raise
            time.sleep(75)
    return [{k: v["value"] for k, v in b.items()} for b in data["results"]["bindings"]]


# ------------------------------------------------------------------ Türkçe ekler (son sesli harf uyumu)
_V = "aeıioöuü"


def _last_vowel(w: str) -> str:
    for ch in reversed(w.lower()):
        if ch in _V:
            return ch
    return "e"


def gen(w: str) -> str:
    """Tamlayan eki: Fransa'nın, Mısır'ın, Peru'nun, Türkiye'nin."""
    v = _last_vowel(w); end = w[-1].lower()
    i = {"a": "ı", "ı": "ı", "e": "i", "i": "i", "o": "u", "u": "u", "ö": "ü", "ü": "ü"}[v]
    return f"{w}'{'n' if end in _V else ''}{i}n"


def loc(w: str) -> str:
    """Bulunma eki: Asya'da, Avrupa'da, Afrika'da."""
    v = _last_vowel(w)
    a = "a" if v in "aıou" else "e"
    d = "t" if w[-1].lower() in "fstkçşhp" else "d"
    return f"{w}'{d}{a}"


def _ok(q: str) -> bool:
    """Sınav sorusu ve yakın biçimleri üretilmez."""
    from . import dialogs
    from .cogexam import near_cogexam
    return not (dialogs.is_exam_question(q) or dialogs.near_exam(q) or near_cogexam(q))


def _row(q: str, a: str, source: str, lic: str) -> dict:
    return {"q": q, "a": a, "source": source, "license": lic, "training_allowed": True}


# ------------------------------------------------------------------ Wikidata gerçekleri → diyalog
def country_dialogs(rows: list[dict], rng: random.Random) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple] = set()
    for r in rows:
        c = r.get("cL", "").strip()
        if not c or (c, r.get("capL"), r.get("contL"), r.get("curL")) in seen:
            continue
        seen.add((c, r.get("capL"), r.get("contL"), r.get("curL")))
        cap, cont, cur = r.get("capL"), r.get("contL"), r.get("curL")
        if cap:
            for q in [f"{gen(c)} başkenti neresi?", f"{c} başkenti hangi şehir?", f"{gen(c)} başkenti hangi şehirdir?",
                      f"{c} ülkesinin başkenti ne?"]:
                if _ok(q):
                    out.append(_row(q, rng.choice([f"{gen(c)} başkenti {cap}.", f"{cap}, {gen(c)} başkentidir.",
                                                   f"{c} ülkesinin başkenti {cap}."]), "wikidata", "cc0-1.0"))
            q = f"{cap} hangi ülkenin başkenti?"
            if _ok(q):
                out.append(_row(q, f"{cap}, {gen(c)} başkentidir.", "wikidata", "cc0-1.0"))
        if cont:
            for q in [f"{c} hangi kıtada?", f"{c} hangi kıtada yer alır?"]:
                if _ok(q):
                    out.append(_row(q, f"{c}, {loc(cont)} yer alır.", "wikidata", "cc0-1.0"))
        if cur:
            for q in [f"{gen(c)} para birimi ne?", f"{c} hangi parayı kullanır?"]:
                if _ok(q):
                    out.append(_row(q, f"{gen(c)} para birimi {cur}.", "wikidata", "cc0-1.0"))
    return out


def province_dialogs(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        p, plate = r.get("pL", "").replace(" ili", "").strip(), r.get("plate", "").strip()
        if not p or not plate.isdigit():
            continue
        # Cevapta Türkçe harf olmalı (clean_pair Türkçe oranı süzgeci): "numarası", "numaralı"
        for q, a in [(f"{gen(p)} plaka kodu kaç?", f"{p} ilinin plaka numarası {int(plate):02d}."),
                     (f"{int(plate):02d} plaka hangi ilin?", f"{int(plate):02d} numaralı plaka {p} iline aittir."),
                     (f"{p} plakası kaç?", f"{p} ilinin plaka numarası {int(plate):02d}.")]:
            if _ok(q):
                out.append(_row(q, a, "wikidata", "cc0-1.0"))
    return out


def element_dialogs(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        e, sym, num = r.get("eL", "").strip(), r.get("sym", "").strip(), r.get("num", "").split(".")[0]
        if not e or not sym:
            continue
        for q, a in [(f"{e} elementinin sembolü ne?", f"{e} elementinin sembolü {sym}."),
                     (f"{sym} hangi elementin sembolü?", f"{sym}, {e} elementinin sembolüdür."),
                     (f"{e} elementinin atom numarası kaç?", f"{e} elementinin atom numarası {num}.")]:
            if num.isdigit() or "atom" not in q:
                if _ok(q):
                    out.append(_row(q, a, "wikidata", "cc0-1.0"))
    return out


# ------------------------------------------------------------------ okuduğunu anlama
_SENT = re.compile(r"(?<=[.!?])\s+")


def answer_window(context: str, answer: str, max_chars: int = 420) -> str | None:
    """Bağlamdan cevabı içeren cümle (+ gerekirse önceki cümle), en çok max_chars."""
    sents = _SENT.split(context.strip())
    for i, s in enumerate(sents):
        if answer in s:
            w = s
            if i > 0 and len(sents[i - 1]) + len(s) + 1 <= max_chars:
                w = sents[i - 1] + " " + s
            return w if len(w) <= max_chars else None
    return None


def xquad_dialogs(items: list[dict]) -> list[dict]:
    """items: {"context","question","answers":{"text":[...]}} (google/xquad xquad.tr)."""
    out = []
    for it in items:
        ans = (it.get("answers") or {}).get("text") or []
        if not ans:
            continue
        a = str(ans[0]).strip()
        ctx = answer_window(str(it.get("context", "")), a)
        q0 = str(it.get("question", "")).strip()
        if not ctx or not q0:
            continue
        q = f"Şu metne göre cevapla: {ctx}\nSoru: {q0}"
        if len(q) <= 590 and _ok(q0):
            out.append(_row(q, f"Metne göre cevap: {a}.", "xquad-tr", "cc-by-sa-4.0"))
    return out


def belebele_dialogs(items: list[dict]) -> list[dict]:
    """items: {"flores_passage","question","mc_answer1..4","correct_answer_num"} (facebook/belebele tur_Latn)."""
    out = []
    for it in items:
        p = str(it.get("flores_passage", "")).strip()
        try:
            k = int(str(it.get("correct_answer_num", "")).strip())
        except ValueError:
            continue
        opts = [str(it.get(f"mc_answer{i}", "")).strip() for i in range(1, 5)]
        if not p or not (1 <= k <= 4) or not all(opts):
            continue
        q = f"Metin: {p}\nSoru: {it.get('question', '')}\n" + "\n".join(f"{'ABCD'[i]}) {o}" for i, o in enumerate(opts))
        if len(q) <= 590:
            out.append(_row(q, f"Doğru cevap {'ABCD'[k - 1]}: {opts[k - 1]}.", "belebele-tr", "cc-by-sa-4.0"))
    return out


# ------------------------------------------------------------------ Hugging Face dosyaları
def _hf_get(repo: str, needle: str) -> bytes | None:
    """Veri kümesindeki adında needle geçen ilk dosya (parquet/json/jsonl)."""
    url = f"https://huggingface.co/api/datasets/{repo}/tree/main?recursive=1"
    files = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]}), timeout=60).read())
    paths = [f["path"] for f in files if f.get("type") == "file" and needle in f["path"]
             and f["path"].endswith((".parquet", ".json", ".jsonl"))]
    if not paths:
        return None
    raw = f"https://huggingface.co/datasets/{repo}/resolve/main/{sorted(paths)[0]}"
    return sorted(paths)[0].encode() + b"\n" + urllib.request.urlopen(urllib.request.Request(raw, headers={"User-Agent": UA["User-Agent"]}), timeout=300).read()


def _records(blob: bytes) -> list[dict]:
    name, data = blob.split(b"\n", 1)
    name = name.decode()
    if name.endswith(".parquet"):
        import io
        import pyarrow.parquet as pq
        return pq.read_table(io.BytesIO(data)).to_pylist()
    text = data.decode("utf-8")
    if name.endswith(".jsonl"):
        return [json.loads(l) for l in text.splitlines() if l.strip()]
    obj = json.loads(text)
    if isinstance(obj, dict) and "data" in obj:  # SQuAD biçimi
        rows = []
        for art in obj["data"]:
            for par in art.get("paragraphs", []):
                for qa in par.get("qas", []):
                    rows.append({"context": par["context"], "question": qa["question"],
                                 "answers": {"text": [a["text"] for a in qa.get("answers", [])]}})
        return rows
    return obj if isinstance(obj, list) else []


def build(out: Path, seed: int = 7) -> dict:
    rng = random.Random(seed)
    rows: list[dict] = []
    stats: dict[str, object] = {}
    for name, fn in [("ulkeler", lambda: country_dialogs(sparql(Q_COUNTRY), rng)), ("iller", lambda: province_dialogs(sparql(Q_PROVINCE))),
                     ("elementler", lambda: element_dialogs(sparql(Q_ELEMENT))),
                     ("xquad", lambda: xquad_dialogs(_records(_hf_get("google/xquad", "xquad.tr") or b"x.json\n[]"))),
                     ("belebele", lambda: belebele_dialogs(_records(_hf_get("facebook/belebele", "tur_Latn") or b"x.json\n[]")))]:
        try:
            got = fn()
            rows += got
            stats[name] = len(got)
            print(f"bilgi: {name} {len(got)} diyalog", flush=True)
        except Exception as e:  # bir kaynak inmezse diğerleri sürer
            stats[name] = f"atlandı: {e!r}"[:200]
            print(f"bilgi: {name} atlandı: {e!r}", flush=True)
    rng.shuffle(rows)
    out.mkdir(parents=True, exist_ok=True)
    with gzip.open(out / "bilgi.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    stats["toplam"] = len(rows)
    (out / "bilgi.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    return stats


if __name__ == "__main__":
    import sys
    print(json.dumps(build(Path(sys.argv[1] if len(sys.argv) > 1 else "bilgi-out")), ensure_ascii=False, indent=1))
