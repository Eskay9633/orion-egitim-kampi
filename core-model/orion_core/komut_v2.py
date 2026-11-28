"""Komut beyni veri seti v2 (sahibin isteği 2026-11-28: "var olana yeni şeyler ekle, sıfırdan ama var olanlar dahil").

Yalnız EĞİTİM akışına girer (datagen._t2c_example_once, split == "train"); değerlendirme ve kalibrasyon kümeleri
değişmez. Üç aile:

1. Telefonda gerçek yazım: harf düşmesi, iki harfin yer değiştirmesi, harf tekrarı, komşu tuş, eksik boşluk. Yalnız
   argüman OLMAYAN sözcüklere uygulanır (model serbest metni kopyalar; argümanı bozmak hedefi yanlış yapardı).
2. Gündelik konuşma: "abi", "kanka", "ya", "şey", "bi", "hadi", emoji, ünlem; cümle başına ve sonuna.
3. Yeni kalıplar: bağlantı inceleme ("şu linke bak", "bunu incele"), Zoe'ye kişi başına otomatik cevap
   ("Ali'ye sen cevap ver", "Ayşe'nin mesajlarına kendin yaz").
"""
from __future__ import annotations

import random
import re

V2_FRAC = 0.12

FILLER_PRE = ["abi ", "kanka ", "ya ", "şey ", "hadi ", "bi ", "baksana ", "orion ya ", "dostum ", "hocam "]
FILLER_POST = [" ya", " abi", " kanka", " hadi", " be", " 🙏", " 👍", "!", "!!", " pls", " lütfen ya", " şimdi"]
_NEIGHBOR = {"a": "s", "s": "a", "e": "r", "r": "e", "ı": "o", "i": "u", "l": "k", "k": "l", "n": "m", "m": "n",
             "t": "y", "y": "t", "d": "f", "u": "ı", "o": "p", "ş": "ğ", "ç": "ö", "g": "h", "h": "g", "b": "v"}
_VOWELS = set("aeıioöuü")


def _typo(rng: random.Random, w: str) -> str:
    if len(w) < 4 or not w.isalpha():
        return w
    i = rng.randrange(1, len(w) - 1)
    r = rng.random()
    if r < 0.3 and w[i] in _VOWELS:
        return w[:i] + w[i + 1:]                      # ünlü düşmesi: hatırlat → hatrlat
    if r < 0.5:
        return w[:i] + w[i + 1] + w[i] + w[i + 2:]    # yer değiştirme
    if r < 0.7:
        return w[:i] + w[i] + w[i:]                   # harf tekrarı
    c = _NEIGHBOR.get(w[i])
    return w[:i] + c + w[i + 1:] if c else w          # komşu tuş


def _protected(args: dict) -> set[str]:
    words = set()
    for v in args.values():
        if isinstance(v, str):
            words.update(re.findall(r"\w+", v.lower()))
        elif isinstance(v, (int, float)):
            words.add(str(v))
    return words


def roughen(rng: random.Random, src: str, args: dict) -> str:
    """Argüman olmayan sözcüklere 1-2 yazım hatası + gündelik dolgu."""
    keep = _protected(args)
    toks = src.split(" ")
    cand = [i for i, t in enumerate(toks) if re.sub(r"\W", "", t.lower()) not in keep and len(t) >= 4
            and not any(ch.isdigit() for ch in t) and "://" not in t]
    for i in rng.sample(cand, min(len(cand), rng.choice([1, 1, 2]))):
        m = re.match(r"^(\W*)(\w+)(\W*)$", toks[i])
        if m:
            toks[i] = m.group(1) + _typo(rng, m.group(2)) + m.group(3)
    s = " ".join(toks)
    if rng.random() < 0.15:
        s = re.sub(r" (de|da|mi|mı|mu|mü)\b", r"\1", s, count=1)  # eksik boşluk: "sende", "gelirmisin"
    if rng.random() < 0.5:
        s = rng.choice(FILLER_PRE) + s
    if rng.random() < 0.5:
        s = s.rstrip(".") + rng.choice(FILLER_POST)
    return s


# ---------------------------------------------------------------------------------------------- yeni kalıplar

_LINK_SITES = ["shbd.io/s/yavuBsST", "ornekkasa.com/kasa/123", "haberler.com/teknoloji/yeni-telefon", "evrimagaci.org/karadelik",
               "oyunsitesi.net/inceleme/gta-6", "forum.ornek.org/konu/4521", "blog.ornekyazar.com/tarif", "kisa.link/a9Kd2",
               "magaza.ornek.com.tr/urun/88", "ntv.com.tr/ekonomi/dolar"]
_LINK_FRAMES = ["{U} bu bağlantıyı incele", "şu linke bak {U}", "{U} buna bir bak", "bu linki incele: {U}", "{U} ne anlatıyor bak",
                "{U} sayfasını kontrol et", "{U} bunu incele bana anlat", "şu sayfayı analiz et {U}", "{U} linkine bak bakalım",
                "{U} buradaki bilgiyi incele"]
_CONTACTS = ["Ali", "Ayşe", "Mustafa", "Annem", "Babam", "Zeki", "Fatih", "Elif", "Mehmet", "Selin", "Kardeşim", "Ahmet Abi"]
_AUTO_FRAMES = ["{C}'e sen cevap ver", "{C} yazınca kendin cevapla", "{C}'nin mesajlarına otomatik cevap ver",
                "Zoe {C}'e kendi başına cevap versin", "{C}'e bana sormadan cevap ver", "{C} için otomatik cevabı aç",
                "{C}'e artık sen yaz", "{C} mesaj atarsa sen ilgilen"]
_ASK_FRAMES = ["{C}'e cevap vermeden önce bana sor", "{C} için otomatik cevabı kapat", "{C}'e kendin cevap verme bana sor",
               "{C}'nin mesajlarında önce bana danış"]


def _last_vowel(w: str) -> str:
    v = [ch for ch in w.lower() if ch in _VOWELS]
    return v[-1] if v else "e"


def _dat(c: str) -> str:
    """Yönelme eki: Ali'ye, Annem'e, Babam'a, Mustafa'ya."""
    back = _last_vowel(c) in "aıou"
    return c + "'" + ("y" if c[-1].lower() in _VOWELS else "") + ("a" if back else "e")


def _gen(c: str) -> str:
    """İlgi eki: Ali'nin, Mustafa'nın, Mehmet'in, Annem'in."""
    v = _last_vowel(c)
    suf = {"a": "ın", "ı": "ın", "e": "in", "i": "in", "o": "un", "u": "un", "ö": "ün", "ü": "ün"}[v]
    return c + "'" + ("n" if c[-1].lower() in _VOWELS else "") + suf


def _fill(frame: str, c: str) -> str:
    return frame.replace("{C}'e", _dat(c)).replace("{C}'nin", _gen(c)).replace("{C}", c)


def new_pattern(rng: random.Random) -> tuple[str, str, dict]:
    r = rng.random()
    if r < 0.5:
        u = "https://" + rng.choice(_LINK_SITES)
        return "web.read", rng.choice(_LINK_FRAMES).replace("{U}", u), {"url": u}
    c = rng.choice(_CONTACTS)
    if r < 0.85:
        return "msg.contacts", _fill(rng.choice(_AUTO_FRAMES), c), {"action": "auto", "contact": c}
    return "msg.contacts", _fill(rng.choice(_ASK_FRAMES), c), {"action": "ask", "contact": c}
