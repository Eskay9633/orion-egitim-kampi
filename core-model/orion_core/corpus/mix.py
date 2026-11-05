"""Derlem karışımı: kategori pay sınırlarıyla dil modeli belgesi örnekleme (chat.prepare --corpus).

Pay sınırı c_k, dil modeli akışındaki TOPLAM karakterin en çok c_k kesridir (ör. meclis ≤ 0.15). Sınırsız (null)
kategoriler tamamen alınır; sınırlı kategoriler gerekirse seyreltilir. Hiç sınırsız kategori yoksa sınırlar mevcut
kategoriler üzerinde toplam 1 olacak şekilde ölçeklenir (aksi halde akış boş kalırdı)."""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Iterable

RELEASE_RE = re.compile(r"https://github\.com/([^/]+)/([^/]+)/releases/(?:tag/([^/?#]+)|latest)")


def plan(avail: dict[str, int], caps: dict[str, float | None]) -> dict[str, float]:
    """Kategori başına alınacak karakter. En büyük T: Σ_k min(avail_k, cap_k·T) ≥ T (sınırsız: avail_k)."""
    cats = {k: v for k, v in avail.items() if v > 0}
    if not cats:
        return {}
    cp = {k: caps.get(k, caps.get("genel")) for k in cats}
    if all(v is not None for v in cp.values()):
        s = sum(cp.values())
        if s < 1:
            cp = {k: v / s for k, v in cp.items()}

    def f(T):
        return sum(cats[k] if cp[k] is None else min(cats[k], cp[k] * T) for k in cats)
    lo, hi = 0.0, float(sum(cats.values()))
    for _ in range(80):
        mid = (lo + hi) / 2
        if f(mid) >= mid - 1e-6:
            lo = mid
        else:
            hi = mid
    T = lo
    return {k: float(cats[k]) if cp[k] is None else min(float(cats[k]), cp[k] * T) for k in cats}


def keep_fraction(doc_id: str) -> float:
    return int(hashlib.sha1(doc_id.encode()).hexdigest()[:12], 16) / float(16 ** 12)


def _release_assets(url: str) -> list[str]:
    m = RELEASE_RE.match(url)
    owner, repo, tag = m.group(1), m.group(2), m.group(3)
    api = f"https://api.github.com/repos/{owner}/{repo}/releases/" + (f"tags/{tag}" if tag else "latest")
    rel = json.loads(urllib.request.urlopen(urllib.request.Request(api, headers={"Accept": "application/vnd.github+json"}),
                                            timeout=60).read())
    return sorted(a["browser_download_url"] for a in rel.get("assets", []) if a["name"].endswith(".jsonl.gz"))


def resolve(srcs: Iterable[str], cache: Path) -> list[Path]:
    """Yerel klasör/dosya ya da GitHub Release adresi → yerel *.jsonl.gz listesi."""
    out = []
    for s in srcs:
        if RELEASE_RE.match(s) or s.startswith(("http://", "https://")):
            urls = _release_assets(s) if RELEASE_RE.match(s) else [s]
            for u in urls:
                p = Path(cache) / hashlib.sha1(u.encode()).hexdigest()[:10] / u.rsplit("/", 1)[-1]
                p.parent.mkdir(parents=True, exist_ok=True)
                if not p.exists():
                    print(f"derlem indiriliyor: {u}", flush=True)
                    urllib.request.urlretrieve(u, str(p) + ".part")
                    Path(str(p) + ".part").replace(p)
                out.append(p)
        else:
            p = Path(s)
            out += sorted(p.rglob("*.jsonl.gz")) if p.is_dir() else [p]
    return out


def iter_docs(files: list[Path], allow: set[str], drop: Counter):
    for p in files:
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                if r.get("training_allowed") is not True:
                    drop["egitim_izni_yok"] += 1
                    continue
                if r.get("model_uretimi"):
                    drop["model_uretimi"] += 1
                    continue
                if str(r.get("license", "")).lower() not in allow:
                    drop["lisans"] += 1
                    continue
                if not r.get("text") or not r.get("kategori"):
                    drop["bos"] += 1
                    continue
                yield r


def sample(files: list[Path], caps: dict, allow: set[str], extra_avail: dict[str, int] | None = None,
           max_chars: int | None = None) -> tuple[dict[str, float], dict]:
    """İki geçiş: (1) kategori başına mevcut karakter, (2) plan. Döner: (kategori → tutma oranı, istatistik).
    extra_avail: derlem dışından gelen akış (ör. Vikipedi metni → 'vikipedi')."""
    drop: Counter = Counter()
    avail: Counter = Counter(extra_avail or {})
    docs: Counter = Counter()
    for r in iter_docs(files, allow, drop):
        avail[r["kategori"]] += len(r["text"])
        docs[r["kategori"]] += 1
    take = plan(dict(avail), caps)
    tot = sum(take.values())
    if max_chars and tot > max_chars:
        take = {k: v * max_chars / tot for k, v in take.items()}
        tot = max_chars
    ratio = {k: (take.get(k, 0) / avail[k]) if avail[k] else 0.0 for k in avail}
    st = {"mevcut_karakter": dict(avail), "belge": dict(docs), "alinacak_karakter": {k: int(v) for k, v in take.items()},
          "pay": {k: round(v / tot, 4) for k, v in take.items()} if tot else {}, "pay_siniri": caps,
          "atilan": dict(drop), "dosya": len(files)}
    return ratio, st


def select(files: list[Path], ratio: dict[str, float], allow: set[str]):
    """Belge kimliğinin özetine göre deterministik seçim (aynı girdi → aynı karışım)."""
    for r in iter_docs(files, allow, Counter()):
        if keep_fraction(r["id"]) < ratio.get(r["kategori"], 0.0):
            yield r
