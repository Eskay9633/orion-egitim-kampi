"""DeepMind mathematics_dataset (Apache-2.0 üretici KODU) ile kodla üretilen problemler → Türkçe şablonlarla Q/A.
Çeviri ya da dil modeli YOK: soru kalıbı düzenli ifadeyle ayrıştırılır, Türkçe kalıba yerleştirilir; tanınmayan kalıp
atılır. Çıktı chat.prepare --extra-dialogs biçimindedir (q, a, license, training_allowed)."""
from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

N = r"(-?\d+(?:\.\d+)?(?:/\d+)?)"
EXPR = r"([-\d.+*/() ]*[\d)])"
NEAREST = {"integer": "en yakın tam sayıya", "ten": "en yakın onluğa", "one hundred": "en yakın yüzlüğe",
           "one thousand": "en yakın binliğe", "ten thousand": "en yakın on binliğe", "one hundred thousand":
           "en yakın yüz binliğe", "one million": "en yakın milyonluğa", "1000": "en yakın binliğe", "100": "en yakın yüzlüğe",
           "10": "en yakın onluğa"}
DP = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5}


def _calc(e):
    return f"{e.strip()} işleminin sonucu kaçtır?"


# (modül öneki, kalıp, soru üretici, cevap biçimi: "sonuc" | "evet" | "degisken")
TEMPLATES = [
    ("arithmetic", rf"^(?:Add|Sum|Put together|Total of) {N} and {N}\.?$", lambda m: f"{m[1]} ile {m[2]} sayılarını topla.", "sonuc"),
    ("arithmetic", rf"^What is {N} plus {N}\?$", lambda m: f"{m[1]} artı {m[2]} kaçtır?", "sonuc"),
    ("arithmetic", rf"^Subtract {N} from {N}\.?$", lambda m: f"{m[2]} sayısından {m[1]} çıkar.", "sonuc"),
    ("arithmetic", rf"^What is {N} (?:minus|take away) {N}\?$", lambda m: f"{m[1]} eksi {m[2]} kaçtır?", "sonuc"),
    ("arithmetic", rf"^What is the difference between {N} and {N}\?$", lambda m: f"{m[1]} ile {m[2]} arasındaki fark kaçtır?", "sonuc"),
    ("arithmetic", rf"^What is {N} less than {N}\?$", lambda m: f"{m[2]} sayısının {m[1]} eksiği kaçtır?", "sonuc"),
    ("arithmetic", rf"^Multiply {N} and {N}\.?$", lambda m: f"{m[1]} ile {m[2]} sayılarını çarp.", "sonuc"),
    ("arithmetic", rf"^What is {N} times {N}\?$", lambda m: f"{m[1]} çarpı {m[2]} kaçtır?", "sonuc"),
    ("arithmetic", rf"^(?:What is the product of|Product of|Calculate the product of|Work out) {N} and {N}[.?]?$",
     lambda m: f"{m[1]} ile {m[2]} sayılarının çarpımı kaçtır?", "sonuc"),
    ("arithmetic", rf"^Divide {N} by {N}\.?$", lambda m: f"{m[1]} sayısını {m[2]} sayısına böl.", "sonuc"),
    ("arithmetic", rf"^What is {N} divided by {N}\?$", lambda m: f"{m[1]} bölü {m[2]} kaçtır?", "sonuc"),
    ("arithmetic", rf"^(?:What is|Calculate|Compute|Evaluate|Work out|What is the value of|Determine) {EXPR}[.?]?$",
     lambda m: _calc(m[1]), "sonuc"),
    ("arithmetic", rf"^{EXPR}$", lambda m: _calc(m[1]), "sonuc"),
    ("algebra__linear_1d", r"^Solve (.+?) for ([a-z])\.$", lambda m: f"{m[1]} denklemini {m[2]} için çöz.", "degisken"),
    ("algebra__linear_2d", r"^Solve (.+?), (.+?) for ([a-z])\.$",
     lambda m: f"{m[1]} ve {m[2]} denklemlerini {m[3]} için çöz.", "degisken3"),
    ("numbers__gcd", rf"^(?:What is|Calculate) the (?:greatest common (?:divisor|factor)|highest common (?:divisor|factor)) of {N} and {N}[.?]$",
     lambda m: f"{m[1]} ve {m[2]} sayılarının en büyük ortak böleni kaçtır?", "sonuc"),
    ("numbers__lcm", rf"^(?:What is|Calculate|Find) the (?:lowest|least|smallest) common multiple of {N} and {N}[.?]$",
     lambda m: f"{m[1]} ve {m[2]} sayılarının en küçük ortak katı kaçtır?", "sonuc"),
    ("numbers__is_prime", rf"^Is {N} (?:a prime number|prime)\?$", lambda m: f"{m[1]} asal sayı mıdır?", "evet"),
    ("numbers__is_prime", rf"^Is {N} composite\?$", lambda m: f"{m[1]} bileşik sayı mıdır?", "evet"),
    ("numbers__div_remainder", rf"^(?:What is|Calculate) the remainder when {N} is divided by {N}[.?]$",
     lambda m: f"{m[1]} sayısı {m[2]} sayısına bölündüğünde kalan kaçtır?", "sonuc"),
    ("numbers__round_number", rf"^(?:Round|What is) {N} (?:rounded )?to the nearest ({'|'.join(NEAREST)})[.?]$",
     lambda m: f"{m[1]} sayısını {NEAREST[m[2]]} yuvarla.", "sonuc"),
    ("numbers__round_number", rf"^(?:Round|What is) {N} (?:rounded )?to ({'|'.join(DP)}) (?:decimal places?|dps?)[.?]$",
     lambda m: f"{m[1]} sayısını virgülden sonra {DP[m[2]]} basamağa yuvarla.", "sonuc"),
    ("comparison__pair", rf"^Which is (?:bigger|greater): {N} or {N}\?$", lambda m: f"Hangisi daha büyük: {m[1]} mi, {m[2]} mi?", "sonuc"),
    ("comparison__pair", rf"^Which is smaller: {N} or {N}\?$", lambda m: f"Hangisi daha küçük: {m[1]} mi, {m[2]} mi?", "sonuc"),
    ("comparison__pair", rf"^Is {N} (?:greater|bigger) than {N}\?$", lambda m: f"{m[1]}, {m[2]} sayısından büyük müdür?", "evet"),
    ("comparison__pair", rf"^Is {N} (?:less|smaller) than {N}\?$", lambda m: f"{m[1]}, {m[2]} sayısından küçük müdür?", "evet"),
    ("polynomials__evaluate", r"^Let ([a-z])\(([a-z])\) = (.+?)\. (?:What is|Calculate|Give|Determine) \1\((-?\d+)\)[.?]$",
     lambda m: f"{m[1]}({m[2]}) = {m[3]} olsun. {m[1]}({m[4]}) kaçtır?", "sonuc"),
    ("calculus__differentiate", r"^(?:Find the|What is the|Differentiate) ?(first|second|third)? ?(?:derivative of )?(.+?) (?:wrt|with respect to) ([a-z])[.?]$",
     lambda m: f"{m[2]} ifadesinin {m[3]} değişkenine göre {({'second': 'ikinci ', 'third': 'üçüncü '}).get(m[1] or '', '')}türevini bul.", "sonuc"),
]
COMPILED = [(p, re.compile(rx), q, k) for p, rx, q, k in TEMPLATES]


def tr_num(s: str) -> str:
    return re.sub(r"(?<=\d)\.(?=\d)", ",", s)


def render(module: str, question: str, answer: str) -> tuple[str, str] | None:
    q, a = question.strip(), answer.strip()
    for pre, rx, qf, kind in COMPILED:
        if not module.startswith(pre):
            continue
        m = rx.match(q)
        if not m:
            continue
        if kind == "evet":
            if a not in ("True", "False"):
                return None
            ans = "Evet." if a == "True" else "Hayır."
        elif kind == "degisken":
            ans = f"{m[2]} = {tr_num(a)}"
        elif kind == "degisken3":
            ans = f"{m[3]} = {tr_num(a)}"
        else:
            ans = f"Sonuç: {tr_num(a)}."
        return tr_num(qf(m)), ans
    return None


def dm_problems(per_module: int, filters: list[str], seed: int = 1):
    """mathematics_dataset kütüphanesinden (pip install mathematics_dataset) doğrudan örnek; zorluk 3 düzey."""
    import random
    import numpy as np
    from mathematics_dataset.modules import modules as M  # Apache-2.0 (doğrulanmadı: keşif PyPI lisansını okur)
    random.seed(seed)
    np.random.seed(seed)

    def entropy_fn(level, n):
        lo, hi = level / n, (level + 1) / n

        def f(rng):
            ln = rng[1] - rng[0]
            return (rng[0] + lo * ln, rng[0] + hi * ln)
        return f
    for lvl in range(3):
        for top, sub in M.train(entropy_fn(lvl, 3)).items():
            for name, fn in sub.items():
                full = f"{top}__{name}"
                if "composed" in full or (filters and not any(full.startswith(x) for x in filters)):
                    continue
                for _ in range(per_module):
                    p = fn()
                    yield full, str(p.question), str(p.answer)


def build(problems, out: Path) -> dict:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    st, miss, seen = Counter(), Counter(), set()
    with gzip.open(out, "wt", encoding="utf-8") as f:
        for module, q, a in problems:
            r = render(module, q, a)
            if r is None:
                miss[module] += 1
                continue
            h = hashlib.sha1((r[0] + "|" + r[1]).encode()).hexdigest()[:14]
            if h in seen:
                st["tekrar"] += 1
                continue
            seen.add(h)
            f.write(json.dumps({"id": f"dmmath-{h}", "q": r[0], "a": r[1], "modul": module,
                                "source": "google-deepmind/mathematics_dataset (kodla üretim, Türkçe şablon)",
                                "license": "apache-2.0", "training_allowed": True, "model_uretimi": False,
                                "attribution": "Problemler google-deepmind/mathematics_dataset üreticisiyle (Apache-2.0, "
                                               "Saxton ve ark. 2019) üretildi; Türkçe kalıplar Orion'a ait"},
                               ensure_ascii=False) + "\n")
            st[module] += 1
    return {"yazilan": sum(v for k, v in st.items() if k != "tekrar"), "modul": dict(st), "taninmayan": dict(miss)}
