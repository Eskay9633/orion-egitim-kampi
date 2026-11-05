"""OpenStax matematik kitapları (CNXML, GitHub openstax/osbooks-*): koleksiyon başına lisans okunur, yalnız CC BY 4.0
(ya da CC BY-SA 4.0) kitaplar alınır; NC/ND (ör. Calculus) atlanır. Çıktı: İngilizce bölüm paragrafları (çeviri girdisi,
translate_data translate-longform)."""
from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .collectors import classify_rights

CNX = "{http://cnx.rice.edu/cnxml}"
MML = "{http://www.w3.org/1998/Math/MathML}"
MD = "{http://cnx.rice.edu/mdml}"
COL = "{http://cnx.rice.edu/collxml}"
ALLOWED = {"cc-by-4.0", "cc-by-sa-4.0"}
SKIP = {"figure", "media", "table", "glossary", "footnote", "image", "iframe"}


def mathml(el) -> str:
    t = el.tag.replace(MML, "")
    ch = list(el)
    if t in ("mi", "mn", "mo", "mtext", "ms"):
        x = (el.text or "").strip()
        return {"−": "-", "⋅": "×", "·": "×"}.get(x, x)
    if t == "mfrac" and len(ch) == 2:
        a, b = mathml(ch[0]), mathml(ch[1])
        wrap = lambda s: s if re.fullmatch(r"[\w.]+", s) else f"({s})"
        return f"{wrap(a)}/{wrap(b)}"
    if t == "msup" and len(ch) == 2:
        return f"{mathml(ch[0])}^{mathml(ch[1])}"
    if t == "msub" and len(ch) == 2:
        return f"{mathml(ch[0])}_{mathml(ch[1])}"
    if t == "msqrt":
        return "√(" + "".join(mathml(c) for c in ch) + ")"
    if t == "mfenced":
        return "(" + ", ".join(mathml(c) for c in ch) + ")"
    parts = [mathml(c) for c in ch]
    return " ".join(p for p in parts if p) if t in ("math", "mrow", "mstyle", "semantics") else "".join(parts)


def inline(el) -> str:
    out = [el.text or ""]
    for c in el:
        tag = c.tag.split("}")[-1]
        if c.tag.startswith(MML):
            out.append(mathml(c))
        elif tag in SKIP:
            pass
        elif tag not in ("annotation-xml",):
            out.append(inline(c))
        out.append(c.tail or "")
    return re.sub(r"\s+", " ", "".join(out)).strip()


def module_paras(data: bytes) -> tuple[str, list[dict]]:
    root = ET.fromstring(data)
    title = (root.findtext(f"{CNX}title") or root.findtext(f".//{MD}title") or "").strip()
    paras = []

    def walk(el, kind="para"):
        for c in el:
            tag = c.tag.replace(CNX, "")
            if tag in SKIP:
                continue
            k = "ornek" if tag == "example" else ("cozum" if tag == "solution" else kind)
            if tag in ("para", "title") and el.tag.replace(CNX, "") not in ("figure", "table"):
                t = inline(c)
                if 20 <= len(t) <= 1500 and sum(ch.isalpha() for ch in t) / max(1, len(t)) >= 0.5:
                    paras.append({"tur": k, "en": t})
            else:
                walk(c, k)
    content = root.find(f"{CNX}content")
    if content is not None:
        walk(content)
    return title, paras


def books(tar_path: Path):
    """(koleksiyon dosyası, başlık, lisans, kısa ad, [modül kimlikleri], {modül: cnxml baytı})"""
    with tarfile.open(tar_path) as t:
        members = {m.name: m for m in t if m.isfile()}
        mods = {}
        for n, m in members.items():
            mm = re.search(r"/modules/(m\d+)/index\.cnxml$", n)
            if mm:
                mods[mm.group(1)] = t.extractfile(m).read()
        for n, m in sorted(members.items()):
            if not n.endswith(".collection.xml"):
                continue
            x = t.extractfile(m).read()
            root = ET.fromstring(x)
            lic_el = root.find(f".//{MD}license")
            lic = classify_rights([lic_el.get("url", "")]) if lic_el is not None else None
            title = (root.findtext(f".//{MD}title") or "").strip()
            slug = (root.findtext(f".//{MD}slug") or Path(n).name.replace(".collection.xml", "")).strip()
            ids = [e.get("document") for e in root.iter(f"{COL}module") if e.get("document")]
            yield n, title, lic, slug, ids, mods


def collect(tar_paths: list[Path], out: Path, n_shards: int = 2, repo_names: list[str] | None = None) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    shards = [open(out / f"openstax-{i:02d}.jsonl", "w", encoding="utf-8") for i in range(n_shards)]
    st = {"kitap": [], "atlanan_kitap": [], "bolum": 0, "paragraf": 0}
    seen = set()
    try:
        for ti, tp in enumerate(tar_paths):
            for coll, title, lic, slug, ids, mods in books(Path(tp)):
                if lic not in ALLOWED:
                    st["atlanan_kitap"].append({"baslik": title, "lisans": lic})
                    continue
                st["kitap"].append({"baslik": title, "lisans": lic, "depo": (repo_names or [None] * len(tar_paths))[ti]})
                for mid in ids:
                    if mid not in mods or mid in seen:
                        continue
                    seen.add(mid)  # aynı modül birden çok kitapta olabilir (Algebra & Trig / Precalculus)
                    mt, paras = module_paras(mods[mid])
                    if len(paras) < 3:
                        continue
                    did = "openstax-" + hashlib.sha1(f"{slug}/{mid}".encode()).hexdigest()[:12]
                    url = f"https://openstax.org/details/books/{slug}"
                    rec = {"id": did, "kaynak": "openstax", "source": f"OpenStax — {title}", "kategori": "matematik",
                           "license": lic, "title": mt, "url": url, "paras": paras,
                           "attribution": f"{title}, OpenStax (Rice University), {lic.upper()}, {url}; "
                                          f"İngilizceden Türkçeye makine çevirisi, değiştirilmiştir"}
                    shards[int(did[-6:], 16) % n_shards].write(json.dumps(rec, ensure_ascii=False) + "\n")
                    st["bolum"] += 1
                    st["paragraf"] += len(paras)
    finally:
        for f in shards:
            f.close()
    (out / "openstax-collect.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return st
