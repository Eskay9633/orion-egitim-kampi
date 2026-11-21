"""Yeni veri katmanı (sahibin kararı 2026-11-21: "bize veri şart, Orion gelişmeli").

Sohbet beyni için iki yeni ek diyalog dosyası üretir (chat.extra_dialogues biçimi: {"turns"|"q","a", "source", "license",
"training_allowed": true}); kaggle.yml "diyalog-*" Release'lerini oturuma kendiliğinden ekler.

1) diyalog-sentetik: büyük Türkçe talimat/sohbet setleri. Bunlar yapay zekâ ile üretilmiş ya da çevrilmiş metinlerdir;
   sahip gelişim için açtı (eski "model üretimi veri girmez" kuralı bu setler için kalktı). Kaynak adı "sentetik:" ile
   başlar; eğitim raporunda ayrı sayılır, gerekirse tek satırla çıkarılır. Her tur dialogs.clean_pair'den geçer (sınav
   soruları, başka model kimliği, Türkçe olmayan cevap atılır).
2) diyalog-orion: Orion'un kendi verisi (lisans "orion-kendi"): 14 ajanın kimlik/rol/düşünme/ilke metinleri soru-cevap
   olarak ve komut beyninin Türkçe cümleleri "iş mi, sohbet mi" cevabıyla (sohbet beyni de ayırmayı öğrenir). Ölçüm
   kümeleriyle aynı (normalize) cümle girmez.
"""
from __future__ import annotations

import argparse
import gzip
import json
import random
import re
import urllib.request
from collections import Counter
from pathlib import Path

from . import SHARED
from .dialogs import clean_pair

# (depo, lisans, en çok satır). Lisanslar veri kartlarından (2026-11-21 araştırması); InstrucTurca kartı Apache-2.0 der,
# meta verisi cc-by-sa-4.0: temkinli olan yazıldı.
SENTETIK = [
    ("turkish-nlp-suite/InstrucTurca", "cc-by-sa-4.0", 120_000),
    ("ogulcanaydogan/Turkish-LLM-v10-Training", "apache-2.0", 120_000),
    ("cisimcik/turkish-chat-max-25k", "cc0-1.0", 30_000),
    ("VoidOaz/turkish-daily-dialogues-5k", "cc-by-4.0", 10_000),
]
FILE_EXT = (".parquet", ".jsonl", ".json", ".jsonl.gz")

Q_KEYS = ("instruction", "talimat", "prompt", "question", "soru", "input_text", "query", "user", "inputs", "girdi")
X_KEYS = ("input", "context", "giris", "giriş", "baglam", "bağlam")
A_KEYS = ("output", "response", "answer", "cevap", "yanit", "yanıt", "completion", "assistant", "targets", "cikti", "çıktı")
CONV_KEYS = ("messages", "conversations", "conversation", "dialog", "dialogue", "turns", "chat")
USER_ROLES = {"user", "human", "prompter", "kullanici", "kullanıcı"}
BOT_ROLES = {"assistant", "gpt", "bot", "model", "asistan"}


def _txt(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def row_turns(r: dict) -> list[tuple[str, str]]:
    """Bilinen biçimlerden (sohbet listesi, talimat/girdi/çıktı, soru/cevap) (soru, cevap) turları."""
    low = {str(k).lower(): v for k, v in r.items()}
    for k in CONV_KEYS:
        conv = low.get(k)
        if isinstance(conv, str):
            try:
                conv = json.loads(conv)
            except ValueError:
                conv = None
        if isinstance(conv, list) and conv and isinstance(conv[0], dict):
            turns, q = [], None
            for m in conv:
                role = str(m.get("role") or m.get("from") or m.get("speaker") or "").lower()
                text = _txt(m.get("content") or m.get("value") or m.get("text"))
                if role in USER_ROLES:
                    q = text
                elif role in BOT_ROLES and q:
                    turns.append((q, text))
                    q = None
            if turns:
                return turns
    q = next((_txt(low[k]) for k in Q_KEYS if _txt(low.get(k))), "")
    a = next((_txt(low[k]) for k in A_KEYS if _txt(low.get(k))), "")
    x = next((_txt(low[k]) for k in X_KEYS if _txt(low.get(k))), "")
    if not q and x:  # yalnız girdi/çıktı (ör. InstrucTurca: "Input", "Output")
        q, x = x, ""
    if q and x and x != q:
        q = f"{q}\n{x}"
    return [(q, a)] if q and a else []


def clean_turns(turns: list[tuple[str, str]]) -> list[list[str]]:
    out = []
    for q, a in turns:
        c = clean_pair(q, a)
        if c is None:
            break
        out.append(list(c))
    return out


def _hf_list(repo: str) -> list[str]:
    url = f"https://huggingface.co/api/datasets/{repo}/tree/main?recursive=1"
    files = json.loads(urllib.request.urlopen(url, timeout=60).read())
    return sorted(f["path"] for f in files if f.get("type") == "file" and f["path"].endswith(FILE_EXT)
                  and "test" not in Path(f["path"]).name.lower())


def _hf_get(repo: str, p: str, cache: Path) -> Path:
    local = cache / repo.replace("/", "__") / p.replace("/", "__")
    local.parent.mkdir(parents=True, exist_ok=True)
    if not local.exists():
        print(f"indiriliyor: {repo}/{p}", flush=True)
        urllib.request.urlretrieve(f"https://huggingface.co/datasets/{repo}/resolve/main/{p}", local)
    return local


def _rows(path: Path):
    name = path.name
    if name.endswith(".parquet"):
        import pyarrow.parquet as pq
        pf = pq.ParquetFile(path)
        for b in pf.iter_batches(batch_size=4096):
            yield from b.to_pylist()
    elif name.endswith((".jsonl", ".jsonl.gz")):
        op = gzip.open if name.endswith(".gz") else open
        with op(path, "rt", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        yield json.loads(line)
                    except ValueError:
                        continue
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = next((v for v in data.values() if isinstance(v, list)), [])
        yield from (r for r in data if isinstance(r, dict))


def sentetik(cache: Path, out: Path, sources=SENTETIK) -> dict:
    stats: dict = {}
    with gzip.open(out, "wt", encoding="utf-8") as f:
        for repo, lic, cap in sources:
            st = Counter()
            try:
                files = _hf_list(repo)
                st["dosya"] = len(files)
                for p in files:
                    for r in _rows(_hf_get(repo, p, cache)):
                        if st["alindi"] >= cap:
                            break
                        turns = clean_turns(row_turns(r))
                        if not turns:
                            st["atildi"] += 1
                            if st["atildi"] == 1:
                                st["ornek_alanlar"] = 0  # ilk atılan satırın alanları teşhis için aşağıda
                                stats.setdefault("ilk_atilan_alanlar", {})[repo] = sorted(map(str, r.keys()))[:12]
                            continue
                        f.write(json.dumps({"turns": turns, "source": f"sentetik:{repo}", "license": lic,
                                            "training_allowed": True}, ensure_ascii=False) + "\n")
                        st["alindi"] += 1
                    if st["alindi"] >= cap:
                        break
            except Exception as e:  # bir kaynak alınamazsa diğerleri sürer; rapora yazılır
                st["hata"] = f"{type(e).__name__}: {str(e)[:160]}"
                print(f"uyarı: {repo}: {e}", flush=True)
            st.pop("ornek_alanlar", None)
            stats[repo] = dict(st)
            print(f"{repo}: {dict(st)}", flush=True)
    return stats


# --------------------------------------------------------------------------- Orion'un kendi verisi

def _third_person(s: str) -> str:
    """Ajan tanımları ikinci tekil şahısla yazılı ("...lidersin, yazarsın"): üçüncü şahsa çevrilir (uzun sözcükte
    yalnız sondaki -sın/-sin/-sun/-sün atılır; kısa sözcüklere dokunulmaz)."""
    return re.sub(r"\b(\w{4,}?)(s[ıiuü]n)\b", lambda m: m.group(1) if len(m.group(0)) >= 7 else m.group(0), s)


def ajan_diyaloglari() -> list[dict]:
    d = json.loads((SHARED / "self" / "ajanlar.json").read_text(encoding="utf-8"))
    rows = []
    for a in d["agents"]:
        name, role = a.get("name", ""), a.get("role", "")
        ident, think = _third_person(a.get("identity", "")), _third_person(a.get("thinking", ""))
        subs = [s.get("name", "") for s in a.get("subagents", []) if s.get("name")]
        own = [_third_person(p) for p in a.get("own_principles", [])]
        pairs = [(f"{name} kim?", f"{name}, Orion ekibinde {role}. {ident}".strip()),
                 (f"{name} ne iş yapar?", f"{name} {role} olarak çalışır. {ident}".strip())]
        if think:
            pairs.append((f"{name} nasıl düşünür?", think))
        if subs:
            pairs.append((f"{name} hangi alt ajanlarla çalışır?", f"{name} ile çalışan alt ajanlar: " + ", ".join(subs) + "."))
        if own:
            pairs.append((f"{name} hangi ilkelere uyar?", " ".join(own)))
        for q, ans in pairs:
            if (c := clean_pair(q, ans)):
                rows.append({"q": c[0], "a": c[1], "source": "orion:ajanlar", "license": "orion-kendi", "training_allowed": True})
    return rows


def komut_diyaloglari(n: int, seed: int = 11) -> list[dict]:
    """Komut beyninin cümleleri: "iş mi, sohbet mi" cevabıyla. Ölçüm kümeleriyle normalize hâli aynı olan cümle girmez."""
    from . import datagen
    from .massive import held_out_keys, norm_key
    cmds = json.loads((SHARED / "protocol" / "v1" / "commands.json").read_text(encoding="utf-8"))["commands"]
    held = held_out_keys()
    rows, seen = [], set()
    for e in datagen.generate(n, "train", seed=seed):
        k = norm_key(e["src"])
        if k in held or k in seen:
            continue
        seen.add(k)
        try:
            cmd = json.loads(e["tgt"]).get("cmd")
        except (ValueError, AttributeError):
            continue
        if not cmd:
            continue
        if cmd == "ask":
            ans = "Bu bir iş değil; sohbet ya da soru. Cevaplarım."
        else:
            spec = cmds.get(cmd, {})
            ans = f"Bu bir iş: {spec.get('doc', cmd)} Makine dili: {e['tgt']}"
        if (c := clean_pair(e["src"], ans)):
            rows.append({"q": c[0], "a": c[1], "source": "orion:komut", "license": "orion-kendi", "training_allowed": True})
    random.Random(seed).shuffle(rows)
    return rows


def orion(out: Path, n_komut: int = 60_000) -> dict:
    a, k = ajan_diyaloglari(), komut_diyaloglari(n_komut)
    with gzip.open(out, "wt", encoding="utf-8") as f:
        for r in a + k:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return {"ajan": len(a), "komut": len(k)}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--cache", default="work/yeniveri-cache")
    ap.add_argument("--skip-sentetik", action="store_true")
    ap.add_argument("--n-komut", type=int, default=60_000)
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rep = {"orion": orion(out / "orion.jsonl.gz", a.n_komut)}
    if not a.skip_sentetik:
        rep["sentetik"] = sentetik(Path(a.cache), out / "sentetik.jsonl.gz")
    (out / "yeniveri.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
