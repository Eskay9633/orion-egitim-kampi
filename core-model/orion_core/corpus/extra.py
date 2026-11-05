"""Ek Türkçe kaynaklar (sahibin onayı 2026-11-05): Tatoeba cümleleri, UD Türkçe ağaç bankaları, Common Voice cümleleri
ve Simple English Wikipedia (Türkçeye makine çevirisi için hazırlık).

Her toplayıcı lisansı KAYNAĞIN KENDİ METNİNDEN çalışma anında denetler; tanınmazsa LicenseError (hiçbir şey yazılmaz).
Çıktı: derlem kayıtları (id, text, kategori, license, attribution, url, training_allowed=true, model_uretimi=false)."""
from __future__ import annotations

import bz2
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from .shards import ShardWriter
from .text import norm, strip_wikitext


class LicenseError(RuntimeError):
    pass


def _id(*parts: str) -> str:
    return hashlib.sha1("/".join(parts).encode()).hexdigest()[:14]


def _rec(did: str, text: str, kaynak: str, kategori: str, lic: str, attribution: str, url: str, **kw) -> dict:
    return {"id": did, "text": text, "kaynak": kaynak, "kategori": kategori, "license": lic, "attribution": attribution,
            "url": url, "training_allowed": True, "model_uretimi": False, **kw}


# --------------------------------------------------------------------------- Tatoeba

def tatoeba_license(terms_text: str) -> str:
    """tatoeba.org kullanım şartları: cümleler CC BY 2.0 FR (bir kısmı CC0). En kısıtlayıcısı (cc-by-2.0) uygulanır."""
    t = re.sub(r"\s+", " ", terms_text or "")
    if re.search(r"CC[ -]BY 2\.0", t) and not re.search(r"NonCommercial|CC[ -]BY[ -]NC", t, re.I):
        return "cc-by-2.0"
    raise LicenseError("Tatoeba kullanım şartlarında CC BY 2.0 bulunamadı; toplanmadı")


def tatoeba(tsv_bz2: Path, terms_text: str, out: Path, per_doc: int = 40) -> dict:
    """tur_sentences_detailed.tsv.bz2 (id, dil, cümle, kullanıcı, eklenme, değişme) → 40 cümlelik belgeler."""
    lic = tatoeba_license(terms_text)
    w = ShardWriter(out, "tatoeba")
    drop, buf, seen = Counter(), [], set()

    def flush():
        if buf:
            ids = [b[0] for b in buf]
            users = sorted({b[2] for b in buf if b[2] and b[2] != "\\N"})
            w.write(_rec("tatoeba-" + _id(*ids), "\n".join(b[1] for b in buf), "tatoeba", "genel", lic,
                         f"Tatoeba (tatoeba.org) katkıcıları: {', '.join(users[:20]) or 'bilinmiyor'}; CC BY 2.0 FR; "
                         f"cümle no: {ids[0]}–{ids[-1]}", f"https://tatoeba.org/tr/sentences/show/{ids[0]}"))
            buf.clear()
    with bz2.open(tsv_bz2, "rt", encoding="utf-8", errors="replace") as f:
        for row in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            if len(row) < 3 or row[1] != "tur":
                drop["dil"] += 1
                continue
            s = norm(row[2]).strip()
            key = s.lower()
            if len(s) < 8 or key in seen:
                drop["kisa_ya_da_tekrar"] += 1
                continue
            seen.add(key)
            buf.append((row[0], s, row[3] if len(row) > 3 else ""))
            if len(buf) >= per_doc:
                flush()
    flush()
    w.close()
    return {"kaynak": "tatoeba", "lisans": lic, "belge": w.docs, "karakter": w.chars, "cumle": len(seen), "atilan": dict(drop)}


# --------------------------------------------------------------------------- Universal Dependencies (Türkçe)

UD_OK = {"Attribution-ShareAlike 4.0": "cc-by-sa-4.0", "Attribution 4.0": "cc-by-4.0",
         "Attribution-ShareAlike 3.0": "cc-by-sa-3.0"}


def ud_license(license_text: str) -> str:
    t = re.sub(r"\s+", " ", license_text or "")
    if re.search(r"NonCommercial|NoDerivatives|NoDerivs|GPL", t, re.I):
        raise LicenseError("UD bankası ticari olmayan/türetilemez ya da GPL lisanslı")
    for k, v in UD_OK.items():
        if k in t:
            return v
    raise LicenseError("UD lisansı tanınmadı")


def conllu_sentences(text: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"^# text = (.+)$", text, re.M)]


def ud_bank(repo: str, license_text: str, conllu_texts: dict[str, str], out: Path, per_doc: int = 30) -> dict:
    lic = ud_license(license_text)
    slug = re.sub(r"[^a-z0-9]+", "-", repo.lower()).strip("-")
    w = ShardWriter(out, f"ud-{slug}")
    n = 0
    for name, txt in sorted(conllu_texts.items()):
        sents = [norm(s) for s in conllu_sentences(txt) if len(s) >= 8]
        n += len(sents)
        for i in range(0, len(sents), per_doc):
            part = sents[i:i + per_doc]
            w.write(_rec(f"ud-{slug}-" + _id(name, str(i)), "\n".join(part), "ud-turkce", "genel", lic,
                         f"{repo} (Universal Dependencies), {lic.upper()}", f"https://github.com/{repo}"))
    w.close()
    return {"kaynak": repo, "lisans": lic, "cumle": n, "belge": w.docs, "karakter": w.chars}


# --------------------------------------------------------------------------- Common Voice cümleleri

def cv_license(doc_text: str) -> str:
    t = doc_text or ""
    if re.search(r"\bCC0\b|CC-0|creativecommons\.org/publicdomain/zero", t, re.I):
        return "cc0-1.0"
    raise LicenseError("Common Voice cümle lisansı (CC0) belgede bulunamadı")


def common_voice(files: dict[str, str], doc_text: str, out: Path, per_doc: int = 40) -> dict:
    lic = cv_license(doc_text)
    w = ShardWriter(out, "commonvoice-tr")
    seen, n = set(), 0
    for name, txt in sorted(files.items()):
        sents = []
        for ln in txt.splitlines():
            s = norm(ln).strip()
            if len(s) >= 8 and s.lower() not in seen:
                seen.add(s.lower())
                sents.append(s)
        n += len(sents)
        for i in range(0, len(sents), per_doc):
            w.write(_rec("cv-" + _id(name, str(i)), "\n".join(sents[i:i + per_doc]), "commonvoice", "genel", lic,
                         "Mozilla Common Voice cümle katkıcıları (CC0)", "https://github.com/common-voice/common-voice"))
    w.close()
    return {"kaynak": "commonvoice", "lisans": lic, "cumle": n, "belge": w.docs, "karakter": w.chars}


# --------------------------------------------------------------------------- Simple English Wikipedia → çeviri girdisi

def _paras(text: str, lo: int = 80, hi: int = 1200) -> list[str]:
    out = []
    for p in strip_wikitext(text).split("\n"):
        p = p.strip()
        if lo <= len(p) <= hi and not p.startswith(("|", "{", "!", "*", "#", "=")) and p.count(" ") >= 8:
            out.append(p)
    return out


def simplewiki_shards(pages, out_dir: Path, n_shards: int, max_chars: int, min_paras: int = 3) -> dict:
    """pages: iter_pages(dump) çıktısı. translate-longform girdisi (id, paras=[{en}], license, attribution...)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fs = [open(out_dir / f"simplewiki-{k:02d}.jsonl", "w", encoding="utf-8") for k in range(n_shards)]
    st = Counter()
    for title, ns, text, redirect in pages:
        if st["karakter"] >= max_chars:
            break
        if ns != "0" or redirect or text.lstrip().lower().startswith("#redirect"):
            continue
        paras = _paras(text)
        if len(paras) < min_paras:
            st["kisa"] += 1
            continue
        did = "simplewiki-" + _id(title or "")
        url = "https://simple.wikipedia.org/wiki/" + (title or "").replace(" ", "_")
        rec = {"id": did, "kaynak": "simplewiki", "source": f"Simple English Wikipedia — {title}", "kategori": "ceviri_metin",
               "license": "cc-by-sa-4.0", "title": title, "url": url, "paras": [{"en": p} for p in paras],
               "attribution": f"Simple English Wikipedia katkıcıları, \"{title}\", CC BY-SA 4.0, {url}; "
                              f"İngilizceden Türkçeye makine çevirisi, değiştirilmiştir"}
        fs[int(did[-6:], 16) % n_shards].write(json.dumps(rec, ensure_ascii=False) + "\n")
        st["madde"] += 1
        st["karakter"] += sum(map(len, paras))
    for f in fs:
        f.close()
    return dict(st)
