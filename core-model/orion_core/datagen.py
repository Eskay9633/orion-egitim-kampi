"""Dilbilgisinden PROGRAMLA eğitim verisi üretir (kota ve lisans sorunu yok).

Üç görev:
  t2c  Türkçe istek -> komut (çevirici görevi)
  plan komut -> ajan + adım planı (araç seçimi)
  ans  cevap -> sabit biçimli Türkçe cevap

Ayrımlar:
  train      eğitim şablonları + eğitim değerleri
  test_iid   eğitim şablonları + ayrılmış değerler (yeni içerik)
  test_ood   ayrılmış şablonlar (hiç görülmemiş söyleyiş)
Her örnek kendi doğrulayıcımızdan geçer; geçmeyen üretilmez.
"""
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from typing import Callable

from .protocol import ProtocolError, canonical, validate_request

# --------------------------------------------------------------------------- zaman

DOW_TR = [("pazartesi", "mon"), ("salı", "tue"), ("çarşamba", "wed"), ("perşembe", "thu"),
          ("cuma", "fri"), ("cumartesi", "sat"), ("pazar", "sun")]
MONTHS_TR = ["ocak", "şubat", "mart", "nisan", "mayıs", "haziran", "temmuz", "ağustos",
             "eylül", "ekim", "kasım", "aralık"]
MONTH_DAYS = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

# Sayının okunuşunun son hecesine göre bulunma eki ('de/'da/'te/'ta)
_UNIT_SUFFIX = {0: None, 1: "de", 2: "de", 3: "te", 4: "te", 5: "te", 6: "da", 7: "de", 8: "de", 9: "da"}
_TENS_SUFFIX = {1: "da", 2: "de", 3: "da", 4: "ta", 5: "de"}


def loc_suffix(n: int) -> str:
    """Saat/dakika okunuşuna göre bulunma eki: 3'te, 10'da, 14'te, 30'da, 45'te."""
    if n == 0:
        return "da"  # "sıfır" yerine "on iki"/"tam" gibi okunur; 00 için sıfırda
    u = n % 10
    if u:
        return _UNIT_SUFFIX[u]
    return _TENS_SUFFIX[(n // 10) % 10] if n < 60 else "de"


@dataclass
class TimeExpr:
    tr: str
    when: str


# Saatlerin okunuşu (yazıyla saat: "sabah yedide", "on birde")
HOUR_WORDS = {1: "bir", 2: "iki", 3: "üç", 4: "dört", 5: "beş", 6: "altı", 7: "yedi", 8: "sekiz", 9: "dokuz",
              10: "on", 11: "on bir", 12: "on iki"}
# "çeyrek geçe" belirtme hâli (3'ü, 9'u, 6'yı), "çeyrek kala" yönelme hâli (9'a, 7'ye, 6'ya)
_ACC_SUFFIX = {1: "i", 2: "yi", 3: "ü", 4: "ü", 5: "i", 6: "yı", 7: "yi", 8: "i", 9: "u", 10: "u", 11: "i", 12: "yi"}
_DAT_SUFFIX = {1: "e", 2: "ye", 3: "e", 4: "e", 5: "e", 6: "ya", 7: "ye", 8: "e", 9: "a", 10: "a", 11: "e", 12: "ye"}


def word_loc(n: int) -> str:
    """Yazıyla saat + bulunma eki: 7 → yedide, 10 → onda, 11 → on birde."""
    return HOUR_WORDS[n] + loc_suffix(n)


def _part(rng: random.Random, h: int) -> tuple[str, int] | None:
    """Gün bölümü + 12'lik saat. Yorum Kotlin TimeParser ile aynı: öğleden sonra/akşam 1-11 → +12,
    gece 6-11 → +12, öğle/öğlen 1-5 → +12, sabah olduğu gibi."""
    if 6 <= h <= 11:
        return "sabah", h
    if h == 12:
        return "öğlen", 12
    if 13 <= h <= 17:
        return "öğleden sonra", h - 12
    if 18 <= h <= 20:
        return "akşam", h - 12
    if 21 <= h <= 23:
        return rng.choice(["akşam", "gece"]), h - 12
    return None


def _ext_clock(rng: random.Random, h: int, m: int, bare_word: bool) -> str | None:
    """Yalnızca EĞİTİM için ek saat söyleyişleri (Kotlin TimeParser bunları henüz çözmüyor, bkz. rapor):
    çeyrek geçe/kala, gün bölümsüz yazıyla saat ("dokuzda")."""
    if m == 15:
        if 7 <= h <= 12 and rng.random() < 0.5:
            pre, n = "saat", h
        else:
            pre, n = _part(rng, h) or ("saat", h)
        return f"{pre} {n}'{_ACC_SUFFIX[n]} çeyrek geçe"
    if m == 45 and h + 1 <= 23:
        hh = h + 1
        if 8 <= hh <= 12 and rng.random() < 0.5:
            pre, n = "saat", hh
        else:
            pre, n = _part(rng, hh) or ("saat", hh)
        return f"{pre} {n}'{_DAT_SUFFIX[n]} çeyrek kala"
    if m == 0 and bare_word and 7 <= h <= 11:
        return word_loc(h)
    return None


def _clock_phrase(rng: random.Random, h: int, m: int, ext: bool = False, bare_word: bool = False) -> str:
    """Saat ifadesi; eki ile birlikte. h 0-23. ext=True yalnızca eğitimde (Kotlin'in çözmediği biçimler)."""
    if ext and rng.random() < 0.3:
        p = _ext_clock(rng, h, m, bare_word)
        if p:
            return p
    style = rng.random()
    part = _part(rng, h)
    if m == 0:
        if part and style < 0.4:
            pre, n = part
            if pre == "öğlen":
                return rng.choice(["öğlen", "öğlen 12'de", "saat 12'de"])
            if pre != "öğlen" and rng.random() < 0.4:
                return f"{pre} {word_loc(n)}"  # "sabah yedide", "akşam sekizde"
            return f"{pre} {n}'{loc_suffix(n)}"
        if style < 0.5 and 7 <= h <= 12:
            return f"saat {word_loc(h)}"  # "saat dokuzda"
        if style < 0.53 and 13 <= h <= 14:
            return f"öğlen {h - 12}'{loc_suffix(h - 12)}"  # "öğlen 1'de"
        if style < 0.78:
            return f"saat {h}'{loc_suffix(h)}"
        return f"saat {h:02d}:00'{loc_suffix(h)}"
    if m == 30:
        if style < 0.3:
            return f"saat {h} buçukta"
        if part and style < 0.55:
            pre, n = part
            if pre != "öğlen" and rng.random() < 0.4:
                return f"{pre} {HOUR_WORDS[n]} buçukta"  # "akşam sekiz buçukta"
            return f"{pre} {n} buçukta"  # "akşam 8 buçukta"
    if part and part[0] != "öğlen" and style > 0.85:
        return f"{part[0]} {part[1]}:{m:02d}'{loc_suffix(m)}"  # "akşam 8:15'te"
    if style > 0.7:
        return f"{h:02d}:{m:02d}'{loc_suffix(m)}"  # "18:05'te" (saat sözcüğü olmadan)
    return f"saat {h:02d}:{m:02d}'{loc_suffix(m)}"


def month_loc(month: str) -> str:
    """Ay adı + bulunma eki: kasımda, ekimde, martta, aralıkta."""
    hard = month[-1] in "çfhkpsşt"
    return month + ("t" if hard else "d") + G.h2(month)


def random_time(rng: random.Random, allow_offset: bool = True, split: str = "test") -> TimeExpr:
    """split='train' ise Kotlin'in henüz çözmediği ek söyleyişler de üretilir (test kümeleri değişmez)."""
    ext = split == "train"
    h = rng.choice([7, 8, 9, 9, 10, 10, 11, 12, 13, 14, 14, 15, 16, 17, 18, 19, 20, 21, 22])
    m = rng.choice([0, 0, 0, 0, 15, 30, 30, 45, 10, 20, 40, 50, 5])
    hm = f"{h:02d}:{m:02d}"
    kind = rng.random()
    if allow_offset and kind < 0.16:
        unit = rng.choice(["m", "m", "h", "d"])
        if unit == "m":
            n = rng.choice([5, 10, 15, 20, 25, 30, 40, 45, 50, 90])
            if n == 30 and rng.random() < 0.4:
                return TimeExpr("yarım saat sonra", "+30m")
            return TimeExpr(f"{n} dakika sonra", f"+{n}m")
        if unit == "h":
            n = rng.randint(1, 12)
            return TimeExpr(f"{n} saat sonra", f"+{n}h")
        n = rng.randint(2, 14)
        return TimeExpr(f"{n} gün sonra", f"+{n}d")
    if ext and kind > 0.995:
        # "bu gece yarısı" = bugünü yarına bağlayan gece 00:00
        return TimeExpr("bu gece yarısı", "d+1@00:00")
    if kind < 0.74:
        clock = _clock_phrase(rng, h, m, ext, bare_word=True)
        if kind < 0.38:
            return TimeExpr(f"yarın {clock}", f"d+1@{hm}")
        if kind < 0.47:
            return TimeExpr(f"bugün {clock}", f"d+0@{hm}")
        if kind < 0.52:
            return TimeExpr(f"öbür gün {clock}", f"d+2@{hm}")
        if kind < 0.57:
            n = rng.randint(3, 9)
            return TimeExpr(f"{n} gün sonra {clock}", f"d+{n}@{hm}")
        tr, code = rng.choice(DOW_TR)
        return TimeExpr(f"{tr} {clock}", f"{code}@{hm}")
    if kind < 0.79:
        # Gün sözcüğü yok: bugün sayılır (Kotlin TimeParser: gün yoksa d+0). Gün bölümü ya da "saat" şart.
        clock = _clock_phrase(rng, h, m, ext, bare_word=False)
        return TimeExpr(clock, f"d+0@{hm}")
    mo = rng.randint(1, 12)
    d = rng.randint(1, MONTH_DAYS[mo - 1])
    clock = _clock_phrase(rng, h, m, ext, bare_word=False)
    month = MONTHS_TR[mo - 1]
    r = rng.random()
    mtr = month_loc(month) if r < 0.3 else month
    if ext and rng.random() < 0.25:
        mtr = mtr[:1].upper() + mtr[1:]  # "1 Kasım": eğitimde büyük harfli ay adı da görülsün
    return TimeExpr(f"{d} {mtr} {clock}", f"{mo:02d}-{d:02d}@{hm}")


# --------------------------------------------------------------------------- değerler
# Her listenin son ~%25'i test_iid için ayrılır (eğitimde görülmez).

REMINDER_TEXTS = [
    "toplantı", "ilaç içmek", "annemi aramak", "faturayı ödemek", "spor salonu", "su içmek",
    "çöpü çıkarmak", "kitap okumak", "doktor randevusu", "kargo teslimi", "sunum provası",
    "ders çalışmak", "markete gitmek", "arabanın muayenesi", "kira ödemesi", "çiçekleri sulamak",
    "yürüyüş", "e-postaları kontrol etmek", "babamı aramak", "vitamin almak", "proje teslimi",
    "kediyi beslemek", "diş fırçalamak", "toplantı notlarını göndermek", "kursa gitmek",
    "eczaneye uğramak", "banka randevusu", "yoga", "uyumak", "mola vermek", "dişçi",
    "sınav", "elektrik faturası", "doğum günü hediyesi", "kuaför", "veteriner randevusu",
    "çamaşırları asmak", "bulaşık makinesi", "okul toplantısı", "maç",
]
NOTE_TEXTS = [
    "süt ve ekmek al", "yeni proje fikri: telefonla çalışan ajan ekibi", "kitap önerisi: Sapiens",
    "toplantıda bütçe konuşulacak", "arabanın lastikleri değişecek", "film listesi: Interstellar",
    "spor programı: pazartesi koşu, çarşamba ağırlık", "tatil için Kaş'a bakılacak",
    "anneme hediye olarak atkı", "haftalık harcama 1200 lira", "bahçeye domates ekilecek",
    "telefonun yedeği alınacak", "kursun ödevi perşembeye", "yeni tarif: mercimek çorbası",
    "Orion için kart fikirleri", "evin kirası arttı", "dişçi kontrolü altı ayda bir",
    "kahve çekirdeği bitti", "sunum slaytları hazır", "kitaplığa raf eklenecek",
    "aylık abonelikleri gözden geçir", "bisikletin zinciri yağlanacak", "haftaya misafir gelecek",
    "yeni dil öğrenme planı", "su faturası yüksek geldi", "pazar günü kahvaltı", "kamera lensi araştır",
    "doğum günü listesi", "laptop pili zayıfladı", "piknik malzemeleri",
]
TAGS = ["iş", "ev", "alışveriş", "fikir", "sağlık", "okul", "proje", "aile", "para", "kitap"]
QUERIES = [
    "bütçe", "toplantı", "kitap", "tatil", "proje", "harcama", "tarif", "spor", "hediye", "araba",
    "fatura", "film", "kira", "yedek", "kurs", "kahve", "abonelik", "misafir", "bisiklet", "lens",
]
TOPICS = [
    "rakip fiyatları", "elektrikli araçlar", "yapay zeka ajanları", "Xiaomi Note 13 Pro güncellemeleri",
    "ücretsiz LLM API'leri", "İstanbul'da kiralık daireler", "Python ile veri analizi", "güneş paneli maliyeti",
    "uyku düzeni", "Kotlin coroutines", "telefon pil ömrü", "en iyi not uygulamaları", "kripto vergileri",
    "akdeniz diyeti", "evde kahve demleme", "bulut depolama fiyatları", "Android güvenlik ayarları",
    "çocuklar için kodlama", "uzaktan çalışma araçları", "yerel yapay zeka modelleri", "kamp ekipmanı",
    "kitap özetleme yöntemleri", "akıllı ev cihazları", "fotoğrafçılık temelleri",
]
REPOS = [
    "Eskay9633/Jarvis-", "torvalds/linux", "google/guava", "pytorch/pytorch", "ggml-org/llama.cpp",
    "square/okhttp", "JetBrains/kotlin", "android/nowinandroid", "openai/gpt-oss", "huggingface/transformers",
    "Kotlin/kotlinx.coroutines", "microsoft/vscode", "facebook/react", "tensorflow/tensorflow",
]
EVENT_TITLES = [
    "dişçi", "proje toplantısı", "yoga dersi", "akşam yemeği", "veli toplantısı", "spor", "sunum",
    "doktor kontrolü", "kahve buluşması", "araba servisi", "kurs", "sinema", "konser", "mülakat",
    "kuaför", "banka görüşmesi", "doğum günü partisi", "maç", "ders", "staj görüşmesi",
]
PLACES = ["Kadıköy", "ofis", "evde", "Beşiktaş", "spor salonu", "kafe", "okul", "hastane", "online", "Moda"]
CARD_TITLES = [
    "Haftalık harcama", "Su tüketimi", "Okunan kitaplar", "Günlük adım", "Proje ilerlemesi",
    "Yapılacaklar", "Kota durumu", "Sabah rutini", "Aylık bütçe", "Uyku süresi", "Ders saatleri",
    "Rakip fiyatları", "Toplantı notları", "Pil sağlığı", "Antrenman", "Haftalık rapor",
]
TIMER_LABELS = ["çay", "makarna", "çalışma", "mola", "egzersiz", "yumurta", "toplantı", "kitap okuma", "meditasyon"]
NEEDS = ["kod yazma", "Türkçe çeviri", "resim tanıma", "uzun metin özeti", "araştırma", "matematik"]
MEMORY_TEXTS = [
    "sabahları kahve yerine çay içerim", "raporlar kısa olsun", "toplantılar 10'dan önce olmasın",
    "hafta sonu bildirim istemiyorum", "notları madde madde yaz", "faturayı her ayın 5'inde öde",
    "kodları Kotlin ile yaz", "araştırmalarda en az üç kaynak kullan", "cevaplar Türkçe olsun",
    "Sophia önce ücretsiz kaynaklara baksın", "akşam 10'dan sonra rahatsız etme",
]


_LEX_CACHE: dict = {}


def _lex() -> dict:
    if not _LEX_CACHE:
        from .lexicon import NOUNS, VERBS, noun_forms, verb_forms
        _LEX_CACHE["nouns"] = [f for w in NOUNS for f in noun_forms(w)]
        _LEX_CACHE["inf"] = [verb_forms(v)[1] for v in VERBS if "_" not in v]
    return _LEX_CACHE


NAMES = ["Ayşe", "Mehmet", "Zeynep", "Ali", "Elif", "Can", "Deniz", "Ece", "Burak", "Selin", "Kerem", "Defne",
         "Emre", "Melis", "Ozan", "İrem", "Tolga", "Nehir", "Umut", "Yasemin"]
ADJ = ["yeni", "eski", "büyük", "küçük", "hızlı", "önemli", "acil", "haftalık", "aylık", "günlük", "uzun", "kısa",
       "kırmızı", "mavi", "ucuz", "pahalı", "kolay", "zor", "son", "ilk", "özel", "ortak", "yerel", "dijital"]


def random_phrase(rng: random.Random, lo: int = 1, hi: int = 4, title: bool = False) -> str:
    """Kopyalamayı öğretmek için rastgele (anlamsız olabilen) Türkçe ifade."""
    lx = _lex()
    n = rng.randint(lo, hi)
    words = []
    for i in range(n):
        r = rng.random()
        if r < 0.5:
            words.append(rng.choice(lx["nouns"]))
        elif r < 0.65:
            words.append(rng.choice(ADJ))
        elif r < 0.75:
            words.append(rng.choice(NAMES) + rng.choice(["", "", "'nin", "'yı", "'ya", "'la"]))
        elif r < 0.83:
            words.append(str(rng.choice([rng.randint(1, 31), rng.randint(100, 5000), rng.randint(2020, 2030)])))
        else:
            words.append(rng.choice(lx["inf"]) if i == n - 1 else rng.choice(lx["nouns"]))
    out = " ".join(words)
    if title:
        out = out[:1].upper() + out[1:]
    return out


def random_repo(rng: random.Random) -> str:
    alnum = "abcdefghijklmnopqrstuvwxyz0123456789"
    owner = rng.choice("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ") + "".join(
        rng.choice(alnum + "ABCDEFGHIJKLMNOPQRSTUVWXYZ-") for _ in range(rng.randint(2, 12)))
    owner = owner.rstrip("-")
    name = "".join(rng.choice(alnum + "-._") for _ in range(rng.randint(2, 16))).strip("-._") or "repo"
    return f"{owner}/{name}"


def pick(rng: random.Random, values: list, split: str, rand=None, p_rand: float = 0.7) -> str:
    """Eğitimde çoğunlukla rastgele ifade (kopyalama öğrenilsin), testte gerçekçi listeden."""
    if split == "train" and rand is not None and rng.random() < p_rand:
        v = rand(rng)
        while len(v) < 3 or len(v) > 75:
            v = rand(rng)
        return v
    return rng.choice(_split(values, split))


def _split(values: list, split: str) -> list:
    cut = max(1, int(len(values) * 0.75))
    return values[:cut] if split == "train" else values[cut:] if split == "test_iid" else values


POLITE_PRE = ["", "", "", "", "Orion, ", "lütfen ", "hey Orion ", "acaba "]
POLITE_POST = ["", "", "", "", " lütfen", " teşekkürler", " rica etsem", "."]


# --------------------------------------------------------------------------- şablonlar
# Her komut: [(şablon üretici, ...)]. Listenin sonundaki OOD_N şablon test_ood'a ayrılır.

Gen = Callable[[random.Random, str], tuple[str, dict]]
OOD_N = 2


def _rem(rng, sp):
    t = random_time(rng, split=sp)
    txt = pick(rng, REMINDER_TEXTS, sp, lambda r: random_phrase(r, 1, 4))
    return t, txt


def reminder_templates() -> list[Gen]:
    def a(rng, sp):
        t, x = _rem(rng, sp); return f"{t.tr} {x} hatırlat", {"at": t.when, "text": x}
    def b(rng, sp):
        t, x = _rem(rng, sp); return f"{t.tr} bana {x} diye hatırlat", {"at": t.when, "text": x}
    def c(rng, sp):
        t, x = _rem(rng, sp); return f"{x} için {t.tr} hatırlatıcı kur", {"at": t.when, "text": x}
    def d(rng, sp):
        t, x = _rem(rng, sp); return f"hatırlatıcı kur: {x}, {t.tr}", {"at": t.when, "text": x}
    def e(rng, sp):
        h = rng.choice([7, 8, 9, 12, 13, 20, 21, 22]); m = rng.choice([0, 0, 30])
        x = pick(rng, REMINDER_TEXTS, sp, lambda r: random_phrase(r, 1, 4))
        return (f"her gün {_clock_phrase(rng, h, m, sp == 'train')} {x} hatırlat",
                {"at": f"d+0@{h:02d}:{m:02d}", "text": x, "repeat": "daily"})
    def f(rng, sp):
        tr, code = rng.choice(DOW_TR); h = rng.choice([8, 9, 10, 18, 19]); x = pick(rng, REMINDER_TEXTS, sp, lambda r: random_phrase(r, 1, 4))
        return (f"her {tr} {_clock_phrase(rng, h, 0, sp == 'train')} {x} hatırlat",
                {"at": f"{code}@{h:02d}:00", "text": x, "repeat": "weekly"})
    # OOD
    def g(rng, sp):
        t, x = _rem(rng, sp); return f"{x} konusunda {t.tr} beni uyar", {"at": t.when, "text": x}
    def h(rng, sp):
        t, x = _rem(rng, sp); return f"{t.tr} için alarm kur, {x}", {"at": t.when, "text": x}
    return [a, b, c, d, e, f, g, h]


def reminder_list_templates() -> list[Gen]:
    phrases = ["hatırlatıcılarımı göster", "bekleyen hatırlatmalar neler", "hangi hatırlatıcılar kurulu",
               "hatırlatıcıları listele", "kurulu alarmlarım neler", "hatırlatmalarıma bak",
               "ne hatırlatacaksın bana", "yaklaşan hatırlatıcılar hangileri"]
    return [(lambda p: (lambda rng, sp: (p, {})))(p) for p in phrases]


def note_write_templates() -> list[Gen]:
    def pick_(rng, sp): return pick(rng, NOTE_TEXTS, sp, lambda r: random_phrase(r, 2, 9))
    def a(rng, sp): x = pick_(rng, sp); return f"not al: {x}", {"text": x}
    def b(rng, sp): x = pick_(rng, sp); return f"şunu not et: {x}", {"text": x}
    def c(rng, sp): x = pick_(rng, sp); return f"{x} diye not yaz", {"text": x}
    def d(rng, sp): x = pick_(rng, sp); return f"notlarıma ekle: {x}", {"text": x}
    def e(rng, sp):
        x = pick_(rng, sp); tg = rng.choice(TAGS); return f"#{tg} etiketiyle not al: {x}", {"text": x, "tags": [tg]}
    def f(rng, sp):
        x = pick_(rng, sp); t1, t2 = rng.sample(TAGS, 2)
        return f"not yaz, etiketler {t1} ve {t2}: {x}", {"text": x, "tags": [t1, t2]}
    def g(rng, sp): x = pick_(rng, sp); return f"bir kenara yaz: {x}", {"text": x}
    def h(rng, sp): x = pick_(rng, sp); return f"unutmamak için kaydet: {x}", {"text": x}
    return [a, b, c, d, e, f, g, h]


def note_search_templates() -> list[Gen]:
    def q(rng, sp): return pick(rng, QUERIES, sp, lambda r: random_phrase(r, 1, 2))
    def a(rng, sp): x = q(rng, sp); return f"notlarımda {x} ara", {"query": x}
    def b(rng, sp): x = q(rng, sp); return f"{x} ile ilgili notları bul", {"query": x}
    def c(rng, sp): x = q(rng, sp); return f"{x} hakkında not var mı", {"query": x}
    def d(rng, sp):
        x = q(rng, sp); n = rng.choice([3, 5, 10, 20]); return f"{x} geçen son {n} notu göster", {"query": x, "limit": n}
    def e(rng, sp): x = q(rng, sp); return f"notlarda {x} geçenleri listele", {"query": x}
    def f(rng, sp): x = q(rng, sp); return f"{x} diye bir not yazmış mıydım", {"query": x}
    def g(rng, sp): x = q(rng, sp); return f"{x} notlarını getir", {"query": x}
    return [a, b, c, d, e, f, g]


def research_templates() -> list[Gen]:
    def tp(rng, sp): return pick(rng, TOPICS, sp, lambda r: random_phrase(r, 1, 5))
    def a(rng, sp): x = tp(rng, sp); return f"{x} hakkında araştırma yap", {"topic": x}
    def b(rng, sp): x = tp(rng, sp); return f"{x} konusunu araştır", {"topic": x}
    def c(rng, sp): x = tp(rng, sp); return f"hızlıca {x} araştır", {"topic": x, "depth": "quick"}
    def d(rng, sp): x = tp(rng, sp); return f"{x} hakkında derin araştırma yap", {"topic": x, "depth": "deep"}
    def e(rng, sp): x = tp(rng, sp); return f"{x} için detaylı bir araştırma başlat", {"topic": x, "depth": "deep"}
    def f(rng, sp): x = tp(rng, sp); return f"kısaca {x} nedir araştır", {"topic": x, "depth": "quick"}
    def g(rng, sp): x = tp(rng, sp); return f"Sophia {x} konusuna baksın", {"topic": x}
    def h(rng, sp): x = tp(rng, sp); return f"{x} hakkında ne bulabilirsin", {"topic": x}
    return [a, b, c, d, e, f, g, h]


def repo_templates() -> list[Gen]:
    def r(rng, sp): return pick(rng, REPOS, sp, random_repo, 0.85)
    def a(rng, sp): x = r(rng, sp); return f"{x} reposunu denetle", {"repo": x}
    def b(rng, sp): x = r(rng, sp); return f"{x} deposunu kontrol et", {"repo": x}
    def c(rng, sp): x = r(rng, sp); return f"{x} CI durumuna bak", {"repo": x, "scope": "ci"}
    def d(rng, sp): x = r(rng, sp); return f"{x} için güvenlik denetimi yap", {"repo": x, "scope": "security"}
    def e(rng, sp): x = r(rng, sp); return f"{x} derlemesi geçti mi", {"repo": x, "scope": "ci"}
    def f(rng, sp): x = r(rng, sp); return f"Jack {x} reposuna göz atsın", {"repo": x}
    def g(rng, sp): x = r(rng, sp); return f"{x} projesinin son durumunu özetle", {"repo": x}
    return [a, b, c, d, e, f, g]


def calendar_add_templates() -> list[Gen]:
    def ev(rng, sp):
        return random_time(rng, allow_offset=False, split=sp), pick(rng, EVENT_TITLES, sp, lambda r: random_phrase(r, 1, 3))
    def a(rng, sp): t, x = ev(rng, sp); return f"{t.tr} takvime {x} ekle", {"title": x, "start": t.when}
    def b(rng, sp): t, x = ev(rng, sp); return f"takvimime {t.tr} {x} koy", {"title": x, "start": t.when}
    def c(rng, sp):
        t, x = ev(rng, sp); n = rng.choice([15, 30, 45, 90, 120])
        return f"{t.tr} {x} etkinliği oluştur, {n} dakika sürecek", {"title": x, "start": t.when, "minutes": n}
    def d(rng, sp):
        t, x = ev(rng, sp); p = pick(rng, PLACES, sp, lambda r: random_phrase(r, 1, 2, True), 0.5)
        return f"{t.tr} {x} var, yer {p}, takvime ekle", {"title": x, "start": t.when, "place": p}
    def e(rng, sp):
        t, x = ev(rng, sp); n = rng.choice([1, 2, 3])
        return f"{t.tr} {n} saatlik {x} planla", {"title": x, "start": t.when, "minutes": n * 60}
    def f(rng, sp): t, x = ev(rng, sp); return f"{x} için {t.tr} randevu oluştur", {"title": x, "start": t.when}
    def g(rng, sp): t, x = ev(rng, sp); return f"ajandama yaz: {x}, {t.tr}", {"title": x, "start": t.when}
    return [a, b, c, d, e, f, g]


def calendar_list_templates() -> list[Gen]:
    days = [("bugün", "d+0"), ("yarın", "d+1"), ("öbür gün", "d+2")]
    def a(rng, sp): tr, d = rng.choice(days); return f"{tr} takvimde ne var", {"day": d}
    def b(rng, sp): tr, d = rng.choice(days); return f"{tr} programım ne", {"day": d}
    def c(rng, sp): n = rng.randint(3, 9); return f"{n} gün sonra neler var", {"day": f"d+{n}"}
    def d(rng, sp): tr, d = rng.choice(days); return f"{tr} için etkinliklerimi göster", {"day": d}
    def e(rng, sp): tr, d = rng.choice(days); return f"{tr} neler yapacağım", {"day": d}
    def f(rng, sp): tr, d = rng.choice(days); return f"{tr} boş muyum, takvime bak", {"day": d}
    return [a, b, c, d, e, f]


ATTACHED = "content://orion/ek"


def file_templates() -> list[Gen]:
    def a(rng, sp): return "ekteki dosyayı özetle", {"uri": ATTACHED}
    def b(rng, sp): return "bu dosyayı kısaca özetle", {"uri": ATTACHED, "length": "short"}
    def c(rng, sp): return "eklediğim belgenin uzun özetini çıkar", {"uri": ATTACHED, "length": "long"}
    def d(rng, sp): return "dosyanın orta uzunlukta özetini yaz", {"uri": ATTACHED, "length": "medium"}
    def e(rng, sp): return "bu belgede ne yazıyor, özetle", {"uri": ATTACHED}
    def f(rng, sp): return "eki okuyup ayrıntılı özet ver", {"uri": ATTACHED, "length": "long"}
    return [a, b, c, d, e, f]


IMAGE_PROMPTS = [
    "gün batımında İstanbul boğazı", "uzayda yüzen bir kedi", "karlı dağlarda ahşap bir kulübe", "robot bir aşçı",
    "su altında bir şehir", "Orion takımyıldızı altında kamp", "pastel renkli bir kahve dükkanı", "çizgi film tarzı bir ejderha",
    "minimal bir uygulama simgesi", "yağmurlu bir Kadıköy sokağı", "fütüristik bir telefon", "çiçek açmış bir kiraz ağacı",
    "eski bir kütüphane", "neon ışıklı bir oyun salonu", "deniz kenarında bir deniz feneri", "sevimli bir baykuş",
]
QUESTIONS = [
    "bu hata nasıl düzelir", "burada ne yazıyor", "hangi ayarı değiştirmeliyim", "fiyat ne kadar", "bu uyarı ne demek",
    "toplamı hesapla", "bu kod neden çalışmıyor", "tarih ne zaman", "hangi butona basmalıyım", "özet çıkar",
]


def image_analyze_templates() -> list[Gen]:
    def q(rng, sp): return pick(rng, QUESTIONS, sp, lambda r: random_phrase(r, 2, 6))
    def a(rng, sp): return "ekteki fotoğrafı oku", {"uri": ATTACHED}
    def b(rng, sp): return "bu ekran görüntüsünde ne yazıyor", {"uri": ATTACHED}
    def c(rng, sp): x = q(rng, sp); return f"resmi incele: {x}", {"uri": ATTACHED, "question": x}
    def d(rng, sp): x = q(rng, sp); return f"ekran görüntüsüne bak ve şunu cevapla: {x}", {"uri": ATTACHED, "question": x}
    def e(rng, sp): x = q(rng, sp); return f"fotoğrafa bakıp söyle: {x}", {"uri": ATTACHED, "question": x}
    def f(rng, sp): return "ss'teki sorunu çöz", {"uri": ATTACHED, "question": "sorunu çöz"}
    def g(rng, sp): return "fotoğraftaki yazıyı çıkar", {"uri": ATTACHED}
    def h(rng, sp): x = q(rng, sp); return f"görseli açıkla, {x}", {"uri": ATTACHED, "question": x}
    return [a, b, c, d, e, f, g, h]


def image_generate_templates() -> list[Gen]:
    def p(rng, sp): return pick(rng, IMAGE_PROMPTS, sp, lambda r: random_phrase(r, 2, 6))
    def a(rng, sp): x = p(rng, sp); return f"{x} resmi çiz", {"prompt": x}
    def b(rng, sp): x = p(rng, sp); return f"bana {x} görseli oluştur", {"prompt": x}
    def c(rng, sp): x = p(rng, sp); return f"resim oluştur: {x}", {"prompt": x}
    def d(rng, sp): x = p(rng, sp); return f"dikey bir {x} resmi yap", {"prompt": x, "size": "portrait"}
    def e(rng, sp): x = p(rng, sp); return f"yatay {x} görseli üret", {"prompt": x, "size": "landscape"}
    def f(rng, sp): x = p(rng, sp); return f"görsel üret: {x}", {"prompt": x}
    def g(rng, sp): x = p(rng, sp); return f"{x} temalı bir illüstrasyon hazırla", {"prompt": x}
    def h(rng, sp): x = p(rng, sp); return f"Luna {x} resmi tasarlasın", {"prompt": x}
    return [a, b, c, d, e, f, g, h]


QUESTIONS_GENERAL = [
    "kara delik nedir", "fotosentez nasıl olur", "İstanbul'un nüfusu kaç", "Python ile Kotlin farkı ne",
    "iyi uyumak için ne yapmalıyım", "ekmek nasıl mayalanır", "elektrikli araba mı benzinli mi", "Osmanlı ne zaman kuruldu",
    "kredi kartı faizi nasıl hesaplanır", "telefonum neden ısınıyor", "en iyi kahve demleme yöntemi ne", "bulut depolama nedir",
]
LANGS = [("İngilizce", "en"), ("Almanca", "de"), ("Fransızca", "fr"), ("İspanyolca", "es"), ("Arapça", "ar"), ("Rusça", "ru"),
         ("İtalyanca", "it"), ("Türkçe", "tr")]


# Belirli yardımcıya soru ("bunu Grok'a sor"): (yönelme hâlindeki ad, providers.json kimliği). Yaygın yazım hataları dahil.
HELPER_DATIVES = [
    ("Grok'a", "grok"), ("grok'a", "grok"), ("Groq'a", "groq"), ("Gemini'ye", "gemini"), ("ChatGPT'ye", "openai"),
    ("Claude'a", "claude"), ("DeepSeek'e", "deepseek"), ("Mistral'e", "mistral"), ("Perplexity'ye", "perplexity"),
    ("Kimi'ye", "kimi"), ("OpenRouter'a", "openrouter"), ("grock", "grok"), ("Cerebras'a", "cerebras"),
    ("GPT'ye", "openai"), ("gemini'ye", "gemini"), ("cemini'ye", "gemini"),
]
HELPER_VERBS = ["sor", "danış", "sorar mısın", "bir sor"]
HELPER_FRAMES = ["{Q} {H} {V}", "{Q}, bunu {H} {V}", "{H} {V}: {Q}", "{Q} bunu {H} {V}", "şunu {H} {V}: {Q}"]


def helper_ask(rng, sp, q: str, hf: bool = False, hv: bool = False) -> tuple[str, dict]:
    h, pid = G.choose(rng, HELPER_DATIVES, sp, hf or hv)
    v = rng.choice(HELPER_VERBS)
    frame = G.choose(rng, HELPER_FRAMES, sp, hf)
    if ":" not in frame and v == "sorar mısın" and rng.random() < 0.5:
        v = "sor"
    return _fill(frame, Q=q, H=h, V=v), {"question": q, "provider": pid}


def ask_templates() -> list[Gen]:
    def q(rng, sp): return pick(rng, QUESTIONS_GENERAL, sp, lambda r: random_phrase(r, 2, 6))
    def a(rng, sp): x = q(rng, sp); return f"{x}?", {"question": x}
    def b(rng, sp): x = q(rng, sp); return f"soru: {x}", {"question": x}
    def c(rng, sp): x = q(rng, sp); return f"bana anlat: {x}", {"question": x}
    def d(rng, sp): x = q(rng, sp); return f"merak ediyorum, {x}", {"question": x}
    def e(rng, sp): x = q(rng, sp); return f"Orion'a sor: {x}", {"question": x}
    def f(rng, sp): x = q(rng, sp); return f"açıkla: {x}", {"question": x}
    def g(rng, sp): return helper_ask(rng, sp, q(rng, sp))
    return [a, b, c, d, e, f, g]


def calc_templates() -> list[Gen]:
    def n(rng): return rng.choice([2, 3, 5, 12, 18, 25, 40, 75, 100, 150, 1250, 3600])
    def a(rng, sp): x, y = n(rng), n(rng); return f"{x} çarpı {y} kaç", {"expr": f"{x}*{y}"}
    def b(rng, sp): x, y = n(rng), n(rng); return f"{x} artı {y} kaç eder", {"expr": f"{x}+{y}"}
    def c(rng, sp): x, y = n(rng), n(rng); return f"hesapla: {x} bölü {y}", {"expr": f"{x}/{y}"}
    def d(rng, sp): x, y = n(rng), n(rng); return f"{x}'in yüzde {y}'si kaç", {"expr": f"{x}*{y}/100"}
    def e(rng, sp): x, y = n(rng), n(rng); return f"{x} eksi {y} kaç", {"expr": f"{x}-{y}"}
    def f(rng, sp): x, y, z = n(rng), n(rng), n(rng); return f"hesapla: ({x}+{y})*{z}", {"expr": f"({x}+{y})*{z}"}
    return [a, b, c, d, e, f]


def translate_templates() -> list[Gen]:
    def t(rng, sp): return pick(rng, NOTE_TEXTS, sp, lambda r: random_phrase(r, 2, 8))
    def a(rng, sp): x = t(rng, sp); ln, lc = rng.choice(LANGS); return f"{ln}ye çevir: {x}", {"text": x, "to": lc}
    def b(rng, sp): x = t(rng, sp); ln, lc = rng.choice(LANGS); return f"şunu {ln} yap: {x}", {"text": x, "to": lc}
    def c(rng, sp): x = t(rng, sp); return f"çevir: {x}", {"text": x}
    def d(rng, sp): x = t(rng, sp); ln, lc = rng.choice(LANGS); return f"{ln} karşılığı ne: {x}", {"text": x, "to": lc}
    def e(rng, sp): x = t(rng, sp); ln, lc = rng.choice(LANGS); return f"Emma {ln}ye çevirsin: {x}", {"text": x, "to": lc}
    def f(rng, sp): x = t(rng, sp); ln, lc = rng.choice(LANGS); return f"tercüme et ({ln}): {x}", {"text": x, "to": lc}
    return [a, b, c, d, e, f]


CARD_KIND_WORDS = {
    "chart": ["grafik", "çubuk grafik", "çizgi grafik"], "list": ["liste", "yapılacaklar listesi"],
    "timer": ["zamanlayıcı", "geri sayım"], "metric": ["metrik", "sayı"], "note": ["not"],
    "reminder": ["hatırlatıcı"], "research": ["araştırma"], "approval": ["onay"],
}


def card_templates() -> list[Gen]:
    def kt(rng, sp):
        kind = rng.choice(list(CARD_KIND_WORDS)); return kind, rng.choice(CARD_KIND_WORDS[kind]), pick(rng, CARD_TITLES, sp, lambda r: random_phrase(r, 1, 3, True))
    def a(rng, sp): k, w, t = kt(rng, sp); return f"'{t}' başlıklı bir {w} kartı ekle", {"kind": k, "title": t}
    def b(rng, sp): k, w, t = kt(rng, sp); return f"{w} kartı ekle: {t}", {"kind": k, "title": t}
    def c(rng, sp):
        k, w, t = kt(rng, sp); r, rtr = rng.choice([("daily", "her gün"), ("weekly", "her hafta"), ("hourly", "her saat")])
        return f"{t} için {w} kartı yap, {rtr} yenilensin", {"kind": k, "title": t, "refresh": r}
    def d(rng, sp): k, w, t = kt(rng, sp); return f"ana ekrana büyük bir {w} kartı koy: {t}", {"kind": k, "title": t, "size": "full"}
    def e(rng, sp):
        t = pick(rng, CARD_TITLES, sp, lambda r: random_phrase(r, 1, 3, True)); s, s_tr = rng.choice([("notes", "notlardan"), ("calendar", "takvimden"), ("quota", "kotadan")])
        return f"{s_tr} beslenen bir grafik kartı ekle: {t}", {"kind": "chart", "title": t, "source": s}
    def f(rng, sp): k, w, t = kt(rng, sp); return f"Luna {t} için bir {w} kartı tasarlasın", {"kind": k, "title": t}
    def g(rng, sp): k, w, t = kt(rng, sp); return f"ekranıma {t} gösteren {w} kartı ekler misin", {"kind": k, "title": t}
    return [a, b, c, d, e, f, g]


def timer_templates() -> list[Gen]:
    def n(rng): return rng.choice([1, 2, 3, 5, 7, 10, 15, 20, 25, 30, 45, 60, 90])
    def a(rng, sp): m = n(rng); return f"{m} dakikalık zamanlayıcı kur", {"minutes": m}
    def b(rng, sp): m = n(rng); return f"{m} dakika geri sayım başlat", {"minutes": m}
    def c(rng, sp): m = n(rng); lb = pick(rng, TIMER_LABELS, sp, lambda r: random_phrase(r, 1, 2)); return f"{lb} için {m} dakika say", {"minutes": m, "label": lb}
    def d(rng, sp): m = n(rng); lb = pick(rng, TIMER_LABELS, sp, lambda r: random_phrase(r, 1, 2)); return f"{lb} zamanlayıcısı, {m} dakika", {"minutes": m, "label": lb}
    def e(rng, sp): m = n(rng); return f"{m} dakika sonra haber ver diye sayaç başlat", {"minutes": m}
    def f(rng, sp): m = n(rng); lb = pick(rng, TIMER_LABELS, sp, lambda r: random_phrase(r, 1, 2)); return f"{m} dakikalık {lb} sayacı aç", {"minutes": m, "label": lb}
    return [a, b, c, d, e, f]


def discover_templates() -> list[Gen]:
    def a(rng, sp): return "yeni ücretsiz yapay zeka bul", {}
    def b(rng, sp): return "başka ücretsiz model var mı araştır", {}
    def c(rng, sp): x = pick(rng, NEEDS, sp, lambda r: random_phrase(r, 1, 3)); return f"{x} için ücretsiz yapay zeka bul", {"need": x}
    def d(rng, sp): return "beyne eklenebilecek yeni sağlayıcı ara", {}
    def e(rng, sp): x = pick(rng, NEEDS, sp, lambda r: random_phrase(r, 1, 3)); return f"{x} yapabilen bedava bir model öner", {"need": x}
    def f(rng, sp): return "kotası dolmayan yeni bir API bul", {}
    return [a, b, c, d, e, f]


def health_templates() -> list[Gen]:
    def a(rng, sp): return "telefonun sağlığını kontrol et", {}
    def b(rng, sp): return "güncellemeden önce telefonu kontrol et", {"purpose": "update"}
    def c(rng, sp): return "pil ve depolama durumu nasıl", {}
    def d(rng, sp): return "güncelleme yapsam sorun olur mu", {"purpose": "update"}
    def e(rng, sp): return "Maya telefonu bir ölçsün", {}
    def f(rng, sp): return "sistem güncellemesine hazır mıyım", {"purpose": "update"}
    return [a, b, c, d, e, f]


def memory_templates() -> list[Gen]:
    def x(rng, sp): return pick(rng, MEMORY_TEXTS, sp, lambda r: random_phrase(r, 2, 7))
    def a(rng, sp): t = x(rng, sp); return f"bunu hatırla: {t}", {"kind": "note", "text": t}
    def b(rng, sp): t = x(rng, sp); return f"tercihim şu: {t}", {"kind": "preference", "text": t}
    def c(rng, sp): t = x(rng, sp); return f"bu adımları beceri olarak kaydet: {t}", {"kind": "skill", "text": t}
    def d(rng, sp): t = x(rng, sp); return f"şunu aklında tut: {t}", {"kind": "note", "text": t}
    def e(rng, sp): t = x(rng, sp); return f"benim için kural: {t}", {"kind": "preference", "text": t}
    def f(rng, sp): t = x(rng, sp); return f"kalıcı hafızaya yaz: {t}", {"kind": "note", "text": t}
    return [a, b, c, d, e, f]


def help_templates() -> list[Gen]:
    phrases = ["neler yapabilirsin", "yardım", "komutları göster", "ne işe yararsın", "bana neler yaparsın",
               "hangi işleri yapabiliyorsun", "nasıl kullanılıyorsun", "yardım menüsü"]
    return [(lambda p: (lambda rng, sp: (p, {})))(p) for p in phrases]


SELF_ADVISE_PHRASES = [
    "Orion'u nasıl geliştirebiliriz", "kendini nasıl geliştirirsin", "daha iyi olmak için ne yapmalısın", "Orion'un eksikleri neler",
    "seni nasıl geliştirebiliriz", "Orion nasıl daha iyi olabilir", "eksiklerin neler", "zayıf yanların neler",
    "nasıl daha iyi olabilirsin", "Orion için gelişim önerisi ver", "Orion gelişimi nasıl daha iyi olabilir",
    "kendini nasıl iyileştirebilirsin", "Orion'un zayıf yanları neler", "daha iyi bir asistan olmak için ne yapmalısın",
    "gelişim önerisi ver", "Orion nasıl gelişir",
]


def g_self_advise(rng, sp, hf, hv):
    """Orion'u nasıl geliştirebiliriz: kendini tanıtıp yardımcılardan öneri ister; provider: adı verilen yardımcı."""
    q = G.choose(rng, SELF_ADVISE_PHRASES, sp, hf or hv)
    if rng.random() < 0.35:
        tr, args = helper_ask(rng, sp, q, hf, hv)
        return tr, {"provider": args["provider"]}
    return q, {}


def self_advise_templates() -> list[Gen]:
    def fixed(i):
        return lambda rng, sp: (SELF_ADVISE_PHRASES[i], {})
    def helper(rng, sp):
        tr, args = helper_ask(rng, sp, rng.choice(SELF_ADVISE_PHRASES[:8]))
        return tr, {"provider": args["provider"]}
    return [fixed(i) for i in range(0, 12)] + [helper, helper] + [fixed(i) for i in range(12, len(SELF_ADVISE_PHRASES))]


TEMPLATES: dict[str, list[Gen]] = {
    "reminder.set": reminder_templates(),
    "reminder.list": reminder_list_templates(),
    "note.write": note_write_templates(),
    "note.search": note_search_templates(),
    "research.start": research_templates(),
    "repo.audit": repo_templates(),
    "calendar.add": calendar_add_templates(),
    "calendar.list": calendar_list_templates(),
    "file.summarize": file_templates(),
    "image.analyze": image_analyze_templates(),
    "image.generate": image_generate_templates(),
    "card.propose": card_templates(),
    "timer.start": timer_templates(),
    "provider.discover": discover_templates(),
    "health.check": health_templates(),
    "memory.save": memory_templates(),
    "ask": ask_templates(),
    "calc.eval": calc_templates(),
    "text.translate": translate_templates(),
    "help": help_templates(),
    "market.crypto": [lambda rng, sp: g_crypto(rng, sp, False, False)] * 3,
    "skill.run": [lambda rng, sp: g_skill_run(rng, sp, False, False)] * 3,
    "skill.list": [lambda rng, sp: g_skill_list(rng, sp, False, False)] * 3,
    "skill.learn": [lambda rng, sp: g_skill_learn(rng, sp, False, False)] * 3,
    "skill.record": [lambda rng, sp: g_skill_record(rng, sp, False, False)] * 3,
    "agent.hire": [lambda rng, sp: g_agent_hire(rng, sp, False, False)] * 3,
    "mail.check": [lambda rng, sp: g_mail_check(rng, sp, False, False)] * 3,
    "mail.send": [lambda rng, sp: g_mail_send(rng, sp, False, False)] * 3,
    "self.status": [lambda rng, sp: g_self_status(rng, sp, False, False)] * 3,
    "app.open": [lambda rng, sp: g_app_open(rng, sp, False, False)] * 3,
    "app.list": [lambda rng, sp: g_app_list(rng, sp, False, False)] * 3,
    "memory.recall": [lambda rng, sp: g_memory_recall(rng, sp, False, False)] * 3,
    "self.advise": self_advise_templates(),
    "code.run": [lambda rng, sp: g_code_run(rng, sp, False, False)] * 3,
    "code.repo": [lambda rng, sp: g_code_repo(rng, sp, False, False)] * 3,
    "work.check": [lambda rng, sp: g_work_check(rng, sp, False, False)] * 3,
    "market.alert": [lambda rng, sp: g_alert(rng, sp, False, False)] * 3,
    "seo.audit": [lambda rng, sp: g_seo(rng, sp, False, False)] * 3,
    "web.search": [lambda rng, sp: g_web_search(rng, sp, False, False)] * 3,
    "web.read": [lambda rng, sp: g_web_read(rng, sp, False, False)] * 3,
    "ad.check": [lambda rng, sp: g_ad_check(rng, sp, False, False)] * 3,
    "ad.budget": [lambda rng, sp: g_ad_budget(rng, sp, False, False)] * 3,
    "design.colors": [lambda rng, sp: g_colors(rng, sp, False, False)] * 3,
    "research.watch": [lambda rng, sp: g_research_watch(rng, sp, False, False)] * 3,
    "repo.watch": [lambda rng, sp: g_repo_watch(rng, sp, False, False)] * 3,
    "work.digest": [lambda rng, sp: g_work_digest(rng, sp, False, False)] * 3,
    "msg.inbox": [lambda rng, sp: g_msg_inbox(rng, sp, False, False)] * 3,
    "msg.reply": [lambda rng, sp: g_msg_reply(rng, sp, False, False)] * 3,
    "msg.contacts": [lambda rng, sp: g_msg_contacts(rng, sp, False, False)] * 3,
}

# Komut ağırlıkları (gerçek kullanım tahmini; çok değerli olanlar daha sık)
WEIGHTS = {
    "reminder.set": 6, "reminder.list": 1, "note.write": 4, "note.search": 3, "research.start": 3,
    "repo.audit": 2, "calendar.add": 4, "calendar.list": 2, "file.summarize": 1, "image.analyze": 2, "image.generate": 2, "card.propose": 3,
    "timer.start": 2, "provider.discover": 1, "health.check": 1, "memory.save": 2, "ask": 3, "calc.eval": 2, "text.translate": 2, "market.crypto": 2, "skill.run": 2, "skill.list": 1, "skill.learn": 2, "skill.record": 1, "agent.hire": 1, "mail.check": 2, "mail.send": 1, "self.status": 1, "app.open": 2, "app.list": 1, "memory.recall": 1, "self.advise": 1, "help": 1,
    "code.run": 2, "code.repo": 1, "work.check": 1, "market.alert": 2,
    "seo.audit": 1, "ad.check": 1, "ad.budget": 1, "design.colors": 1, "research.watch": 1, "repo.watch": 1, "work.digest": 1,
    "msg.inbox": 1, "msg.reply": 2, "msg.contacts": 1, "web.search": 2, "web.read": 2,
}


def _templates_for(cmd: str, split: str) -> list[Gen]:
    t = TEMPLATES[cmd]
    if len(t) <= OOD_N + 2:
        return t  # çok az şablon: ayırmaya değmez
    return t[-OOD_N:] if split == "test_ood" else t[:-OOD_N]


_ASCII = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
_FREE_TEXT_ARGS = {"text", "title", "topic", "query", "label", "place", "need"}


def _noise(rng: random.Random, s: str, args: dict) -> tuple[str, dict]:
    """Telefonda yazım: kesme işareti düşmesi, bazen Türkçe karakter kaybı.
    Karakter kaybında serbest metin argümanları da aynı biçimde değişir (model kopyalar, düzeltmez).
    Büyük harf normalleştirmesi uygulamada yapılır (Normalizer), burada üretilmez."""
    r = rng.random()
    if r < 0.08:
        s = s.replace("'", "")
    elif r < 0.12:
        s = s.translate(_ASCII)
        args = {k: (v.translate(_ASCII) if k in _FREE_TEXT_ARGS and isinstance(v, str) else v) for k, v in args.items()}
    return s, args


def t2c_example(rng: random.Random, split: str = "train", noise: bool = True) -> dict:
    """split: train | test_iid | test_ood (dilbilgisi motorunun görülmemiş parçaları) |
    legacy_ood (Tur 1-2'nin ayrılmış eski kalıpları; eğitimde hiç kullanılmaz, yalnızca rapor)."""
    # Rastgele üretim nadiren protokol sınırını aşar (ör. çok kısa rol metni); o örnek atılır, yenisi üretilir.
    for _ in range(20):
        try:
            return _t2c_example_once(rng, split, noise)
        except ProtocolError:
            continue
    return _t2c_example_once(rng, split, noise)


def _t2c_example_once(rng: random.Random, split: str, noise: bool) -> dict:
    cmds = list(WEIGHTS)
    cmd = rng.choices(cmds, weights=[WEIGHTS[c] for c in cmds])[0]
    # Tek çekiliş yalnızca eğitimde (eskisi gibi): test/kalibrasyon kümelerinin rastgele akışı değişmez.
    r_train = rng.random() if split == "train" else 1.0
    if r_train < CONTRAST_FRAC:
        cmd, tr, args = contrast_example(rng)
    elif r_train < CONTRAST_FRAC + IDENTITY_FRAC:
        cmd, tr, args = identity_example(rng)
    elif r_train < CONTRAST_FRAC + IDENTITY_FRAC + SKILL_FRAC:
        cmd, tr, args = skill_example(rng)  # Tur 19 yeni beceri aileleri (yalnızca eğitim)
    elif r_train < CONTRAST_FRAC + IDENTITY_FRAC + SKILL_FRAC + REALGAP_FRAC:
        cmd, tr, args = realgap_example(rng)  # Tur 21 gerçek cümle açıkları (yalnızca eğitim)
    elif split == "legacy_ood":
        tr, args = rng.choice(_templates_for(cmd, "test_ood"))(rng, "test_ood")
    elif split == "test_ood" or rng.random() < GRAMMAR_FRAC:
        tr, args = grammar_example(rng, cmd, split)
    else:
        tr, args = rng.choice(_templates_for(cmd, split))(rng, split)
    tr = rng.choice(POLITE_PRE) + tr + rng.choice(POLITE_POST)
    if noise and split == "train":
        tr, args = _noise(rng, tr, args)
    req = validate_request({"v": 1, "id": "g", "cmd": cmd, "args": args})
    # Hedef: yalnız kullanıcının söylediği argümanlar (varsayılanlar doldurulmaz → kısa çıktı)
    return {"task": "t2c", "src": tr.strip(), "tgt": canonical({"cmd": cmd, "args": args}),
            "full": canonical(req)}


# --------------------------------------------------------------------------- plan

PLANS = {
    "reminder.set": ["when.resolve", "reminder.schedule", "memory.log"],
    "reminder.list": ["reminder.query", "card.render"],
    "note.write": ["secret.check", "note.insert", "memory.log"],
    "note.search": ["note.query", "card.render"],
    "research.start": ["net.check", "provider.ask", "sources.collect", "note.insert", "card.render"],
    "repo.audit": ["net.check", "github.read", "ci.read", "report.write", "card.render"],
    "calendar.add": ["when.resolve", "calendar.insert", "memory.log"],
    "calendar.list": ["calendar.query", "card.render"],
    "file.summarize": ["file.read", "secret.check", "summarize", "card.render"],
    "image.analyze": ["image.read", "ocr.run", "secret.check", "brain.reason", "card.render"],
    "image.generate": ["net.check", "image.provider", "image.save", "card.render"],
    "card.propose": ["card.validate", "proposal.create", "user.confirm"],
    "timer.start": ["timer.schedule", "card.render"],
    "provider.discover": ["net.check", "provider.ask", "provider.validate", "proposal.create", "user.confirm"],
    "health.check": ["battery.read", "storage.read", "backup.check", "card.render"],
    "memory.save": ["secret.check", "proposal.create", "user.confirm"],
    "ask": ["memory.recall", "brain.answer"],
    "calc.eval": ["expr.parse", "expr.eval"],
    "text.translate": ["brain.translate"],
    "market.crypto": ["net.check", "market.read", "card.render"],
    "skill.run": ["skill.load", "skill.validate", "steps.run", "card.render"],
    "skill.list": ["skill.load", "card.render"],
    "skill.learn": ["net.check", "skill.design", "skill.validate", "proposal.create", "user.confirm"],
    "skill.record": ["history.read", "skill.validate", "skill.save"],
    "agent.hire": ["agent.validate", "agent.save"],
    "mail.check": ["net.check", "vault.read", "imap.read", "secret.scrub", "card.render"],
    "mail.send": ["secret.check", "proposal.create", "user.confirm", "smtp.send"],
    "self.status": ["net.check", "releases.read", "update.check", "card.render"],
    "app.open": ["apps.query", "intent.build", "app.start"],
    "app.list": ["apps.query", "card.render"],
    "memory.recall": ["persona.read", "facts.recall", "card.render"],
    "self.advise": ["self.describe", "net.check", "provider.ask", "provider.ask", "advice.merge", "card.render"],
    "code.run": ["net.check", "helper.write", "sandbox.run", "tests.run", "review.check", "card.render"],
    "code.repo": ["net.check", "github.read", "helper.write", "scope.check", "review.check", "proposal.create", "user.confirm"],
    "work.check": ["history.read", "net.check", "provider.ask", "provider.ask", "card.render"],
    "market.alert": ["market.read", "alert.save", "card.render"],
    "seo.audit": ["net.check", "page.fetch", "seo.measure", "card.render"],
    "web.search": ["net.check", "web.query", "sources.collect", "card.render"],
    "web.read": ["net.check", "robots.check", "page.fetch", "text.extract", "card.render"],
    "ad.check": ["limits.read", "ad.measure", "card.render"],
    "ad.budget": ["budget.compute", "card.render"],
    "design.colors": ["color.parse", "contrast.compute", "card.render"],
    "research.watch": ["duty.save", "card.render"],
    "repo.watch": ["duty.save", "card.render"],
    "work.digest": ["duty.save", "card.render"],
    "msg.inbox": ["messages.read", "summary.compute", "card.render"],
    "msg.reply": ["messages.read", "style.read", "helper.write", "proposal.create", "user.confirm", "whatsapp.reply"],
    "msg.contacts": ["contacts.save", "card.render"],
    "help": ["commands.list"],
}


def plan_for(req: dict) -> str:
    from .protocol import load_schema
    spec = load_schema().commands[req["cmd"]]
    steps = list(PLANS[req["cmd"]])
    if req["cmd"] == "research.start" and req["args"].get("depth") == "deep":
        steps.insert(3, "provider.judge")
    if req["cmd"] == "reminder.set" and req["args"].get("repeat", "none") != "none":
        steps.insert(2, "repeat.schedule")
    return canonical({"agent": spec["agent"], "steps": steps})


def plan_example(rng: random.Random, split: str = "train") -> dict:
    ex = t2c_example(rng, split, noise=False)
    req = json.loads(ex["tgt"])
    return {"task": "plan", "src": ex["tgt"], "tgt": plan_for(req)}


# --------------------------------------------------------------------------- cevap

ERR_TR = {
    "E_OFFLINE": "Bunun için internet gerekiyor; bağlantı yok.",
    "E_QUOTA": "Bugünlük ücretsiz kotalar doldu.",
    "E_PROVIDER": "Sağlayıcıdan cevap alamadım.",
    "E_NOT_FOUND": "Bulamadım.",
    "E_SECRET": "Gizli bilgi içerdiği için kaydetmedim.",
    "E_PERMISSION": "Bunun için izin yok.",
    "E_AMBIGUOUS": "Tam anlayamadım.",
}


def _answer_text(rng: random.Random) -> str:
    """Cevapta kopyalanan hatırlatıcı metni: 1-6 kelime, sıkça mastar/ad tamlaması ("veteriner randevusu").
    Tur 13: yalnızca 30 sabit (çoğu 1-2 parça) metinle eğitilen model uzun metni kesiyordu ("veter")."""
    r = rng.random()
    if r < 0.3:
        return (random_phrase(rng, 1, 4) + " " + rng.choice(_lex()["inf"])).strip()
    if r < 0.45:
        return rng.choice(_lex()["nouns"]) + " " + rng.choice(["randevusu", "toplantısı", "faturası", "teslimi", "kontrolü",
                                                               "hediyesi", "provası", "ödemesi", "dersi", "sınavı"])
    return random_phrase(rng, 1, 6)


def answer_example(rng: random.Random, split: str = "train") -> dict:
    """Cevap JSON'undan sabit biçimli Türkçe cevap (Kotlin Responder ile aynı kalıplar)."""
    kind = rng.random()
    if kind < 0.3:
        code = rng.choice(list(ERR_TR))
        resp = {"v": 1, "id": "g", "status": "error", "result": None, "err_code": code, "next": []}
        return {"task": "ans", "src": canonical(resp), "tgt": ERR_TR[code]}
    if kind < 0.55:
        n = rng.randint(0, 12)
        resp = {"v": 1, "id": "g", "status": "ok", "result": {"count": n, "kind": "note"}, "err_code": None, "next": []}
        tgt = "Hiç not bulamadım." if n == 0 else f"{n} not buldum."
        return {"task": "ans", "src": canonical(resp), "tgt": tgt}
    if kind < 0.8:
        x = pick(rng, REMINDER_TEXTS, split, _answer_text, 0.85)
        resp = {"v": 1, "id": "g", "status": "ok", "result": {"kind": "reminder", "text": x}, "err_code": None, "next": []}
        return {"task": "ans", "src": canonical(resp), "tgt": f"Tamam, \"{x}\" için hatırlatıcı kurdum."}
    resp = {"v": 1, "id": "g", "status": "needs_confirmation", "result": {"kind": "proposal"}, "err_code": None, "next": []}
    return {"task": "ans", "src": canonical(resp), "tgt": "Bunu yapmadan önce onayını bekliyorum."}


# --------------------------------------------------------------------------- toplu üretim

def generate(n: int, split: str, seed: int, mix: tuple[float, float, float] = (0.8, 0.12, 0.08)) -> list[dict]:
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        r = rng.random()
        if r < mix[0]:
            out.append(t2c_example(rng, split))
        elif r < mix[0] + mix[1]:
            out.append(plan_example(rng, split))
        else:
            out.append(answer_example(rng, split))
    return out


def t2c_set(n: int, split: str, seed: int) -> list[dict]:
    rng = random.Random(seed)
    return [t2c_example(rng, split) for _ in range(n)]


def export_eval_fixture(path, n_iid: int = 600, n_ood: int = 400) -> None:
    """Kotlin çevirici testleri için sabit değerlendirme kümesi (Python ile aynı tohumlar)."""
    from pathlib import Path
    rows = []
    for split, n, seed in (("test_iid", n_iid, 101), ("test_ood", n_ood, 202)):
        for e in t2c_set(n, split, seed):
            rows.append({"split": split, "src": e["src"], "full": e["full"]})
    Path(path).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


# --------------------------------------------------------------------------- dilbilgisi motoru (Tur 3)
# Kök sebep düzeltmesi: sabit 98 kalıp yerine parçalardan kurulan cümleler (bkz. grammar.py).

from . import grammar as G  # noqa: E402


def _frame(rng, sp, frames, hf):
    return G.choose(rng, frames, sp, hf)


def _verb(rng, sp, verbs, hv, mood=True):
    v = G.choose(rng, verbs, sp, hv)
    if mood and rng.random() < 0.35:
        return rng.choice(G.moods(v)[1:])
    return v


def _fill(frame: str, **kw) -> str:
    out = frame
    for k, v in kw.items():
        out = out.replace("{" + k + "}", v)
    return " ".join(out.split()).replace(" ,", ",")


REM_VERBS = ["hatırlat", "hatırlatıcı kur", "haber ver", "hatırlatıcı ayarla", "uyar", "hatırlatma kur", "alarm kur",
             "bildirim gönder", "hatırlatma ekle", "aklıma getir", "alarm ayarla", "beni uyar", "bana hatırlat",
             "hatırlatıcı ekle", "bildir", "hatırlatıcı oluştur", "anımsat"]
REM_FRAMES = ["{T} {X} {V}", "{T} bana {X} diye {V}", "{X} için {T} {V}", "{X} var, {T} {V}",
              "{T} {X} için {V}", "{X} diye {T} {V}", "{X}, {T}, {V}", "{X} konusunda {T} {V}",
              "{T} {V}, {X}", "{T} bana {X} için {V}", "{X} için bana {T} {V}", "{T} {V}: {X}",
              "{V}: {X}, {T}", "{V}, {T} {X}"]
REM_ACC_FRAMES = ["{T} {XA} {V}", "{XA} {T} {V}", "{T} bana {XA} {V}", "{XA} unutmayayım, {T} {V}"]
REM_ACC_VERBS = ["hatırlat", "anımsat", "bana hatırlat", "aklıma getir", "unutturma", "hatırlatıver"]


def g_reminder(rng, sp, hf, hv):
    t = random_time(rng, split=sp)
    if rng.random() < 0.3:
        inf = pick(rng, [x for x in REMINDER_TEXTS if G.inf_accusative(x)], sp,
                   lambda r: (random_phrase(r, 0, 2) + " " + r.choice(_lex()["inf"])).strip())
        acc = G.inf_accusative(inf)
        if acc:
            v = G.choose(rng, REM_ACC_VERBS, sp, hv)
            return _fill(_frame(rng, sp, REM_ACC_FRAMES, hf), T=t.tr, XA=acc, V=v), {"at": t.when, "text": inf}
    x = pick(rng, REMINDER_TEXTS, sp, lambda r: random_phrase(r, 1, 4))
    v = _verb(rng, sp, REM_VERBS, hv)
    return _fill(_frame(rng, sp, REM_FRAMES, hf), T=t.tr, X=x, V=v), {"at": t.when, "text": x}


REMLIST_SUBJ = ["hatırlatıcılarım", "hatırlatmalarım", "alarmlarım", "kurulu hatırlatıcılar", "bekleyen hatırlatmalar",
                "yaklaşan hatırlatıcılar", "kurduğun hatırlatıcılar", "hatırlatıcı listem"]
REMLIST_PRED = ["neler", "hangileri", "göster", "listele", "ne durumda", "nelerdi", "bir bak", "aç", "kaç tane",
                "neler var", "getir", "söyle"]


def g_reminder_list(rng, sp, hf, hv):
    s = G.choose(rng, REMLIST_SUBJ, sp, hf)
    p = G.choose(rng, REMLIST_PRED, sp, hv)
    if p in ("göster", "listele", "getir", "aç", "söyle") and rng.random() < 0.5:
        s = s + "ı" if s.endswith("lar") or s.endswith("ım") or s.endswith("ler") else s
    return f"{s} {p}", {}


# Tur 14: ayrılmış "kayda geç" eğitime alındı (yalnızca karşıt çiftlerde: Kotlin kural çevirici bu ön eki
# çözmüyor, test kümelerine girmesin); yerine görülmemiş "bir not yaz" ayrıldı. "unutmamak için kaydet"
# ayrılmış kalır (legacy_ood'da da aynı kalıp var). Etiket: kaydet/kayda geç = note.write,
# "hafızana kaydet"/"tercihimi kaydet" = memory.save.
NOTE_VERBS = ["not al", "not et", "not yaz", "notlarıma ekle", "bir kenara yaz", "kaydet", "bir yere yaz", "unutmamak için kaydet",
              "not defterime ekle", "deftere yaz", "not düş", "bir not yaz", "not olarak kaydet", "bir yere not et",
              "notlara ekle", "not bırak", "yazıver"]
NOTE_FRAMES = ["{V}: {X}", "şunu {V}: {X}", "{X} diye {V}", "{X}, {V}", "{V} lütfen: {X}", "bunu {V}: {X}",
               "{V} — {X}", "hemen {V}: {X}"]


def g_note(rng, sp, hf, hv):
    x = pick(rng, NOTE_TEXTS, sp, lambda r: random_phrase(r, 2, 9))
    v = _verb(rng, sp, NOTE_VERBS, hv)
    return _fill(_frame(rng, sp, NOTE_FRAMES, hf), X=x, V=v), {"text": x}


NS_VERBS = ["bul", "göster", "getir", "listele", "ara", "aç", "çıkar", "bir bak"]
NS_FRAMES = ["notlarımda {Q} {V}", "{Q} ile ilgili notları {V}", "{Q} geçen notları {V}", "notlarda {Q} geçenleri {V}",
             "{Q} notlarını {V}", "{Q} hakkındaki notlarımı {V}", "{Q} konulu notlarımı {V}", "notlarımdan {Q} olanları {V}"]
NS_QFRAMES = ["{Q} hakkında not var mı", "{Q} diye bir not yazmış mıydım", "{Q} ile ilgili ne not almıştım",
              "{Q} hakkında ne yazmıştım", "{Q} notum var mıydı", "{Q} ile ilgili notum var mı", "{Q} konusunda not almış mıydım",
              "notlarımda {Q} geçiyor mu"]


def g_note_search(rng, sp, hf, hv):
    q = pick(rng, QUERIES, sp, lambda r: random_phrase(r, 1, 2))
    if rng.random() < 0.4:
        return _fill(_frame(rng, sp, NS_QFRAMES, hf or hv), Q=q), {"query": q}
    return _fill(_frame(rng, sp, NS_FRAMES, hf), Q=q, V=_verb(rng, sp, NS_VERBS, hv)), {"query": q}


RES_VERBS = ["araştır", "araştırma yap", "incele", "hakkında bilgi topla", "araştırıp anlat", "bir araştır",
             "araştırma başlat", "derle", "bilgi bul", "kaynak tara", "araştırıver", "araştırma hazırla"]
RES_FRAMES = ["{X} hakkında {V}", "{X} konusunu {V}", "{V}: {X}", "{X} ile ilgili {V}", "{X} için {V}",
              "bana {X} {V}", "{X} konusunda {V}", "şu konuyu {V}: {X}"]
DEPTH = [("", None), ("", None), ("hızlıca", "quick"), ("kısaca", "quick"), ("derinlemesine", "deep"),
         ("detaylı", "deep"), ("ayrıntılı", "deep"), ("kısa bir", "quick")]


def g_research(rng, sp, hf, hv):
    x = pick(rng, TOPICS, sp, lambda r: random_phrase(r, 1, 5))
    v = G.choose(rng, RES_VERBS, sp, hv)
    if v in ("hakkında bilgi topla",):
        f = "{X} {V}"
    else:
        f = _frame(rng, sp, RES_FRAMES, hf)
    d_tr, d = rng.choice(DEPTH)
    if d_tr:
        f = f.replace("{V}", d_tr + " {V}", 1)
    args = {"topic": x}
    if d:
        args["depth"] = d
    return _fill(f, X=x, V=v), args


CAL_VERBS = ["takvime ekle", "takvimime koy", "takvime yaz", "ajandama yaz", "ajandaya ekle", "randevu oluştur",
             "etkinlik oluştur", "programıma ekle", "takvime kaydet", "planla", "takvime işle", "etkinlik ekle"]
CAL_FRAMES = ["{T} {X} {V}", "{X} için {T} {V}", "{V}: {X}, {T}", "{X}, {T}, {V}", "{T} {X} var, {V}",
              "{T} {X} etkinliği, {V}", "{X} {T}, {V}", "{T} {V}: {X}",
              "{V}, {T} {X}", "{V}: {T} {X}"]


def g_calendar_add(rng, sp, hf, hv):
    t = random_time(rng, allow_offset=False, split=sp)
    x = pick(rng, EVENT_TITLES, sp, lambda r: random_phrase(r, 1, 3))
    v = _verb(rng, sp, CAL_VERBS, hv)
    args = {"title": x, "start": t.when}
    s = _fill(_frame(rng, sp, CAL_FRAMES, hf), T=t.tr, X=x, V=v)
    r = rng.random()
    if r < 0.12:
        n = rng.choice([15, 30, 45, 90, 120]); s += f", {n} dakika sürecek"; args["minutes"] = n
    elif r < 0.2:
        p = pick(rng, PLACES, sp, lambda q: random_phrase(q, 1, 2, True), 0.5); s += f", yer {p}"; args["place"] = p
    return s, args


DAYS = [("bugün", "d+0"), ("yarın", "d+1"), ("öbür gün", "d+2"), ("bu gün", "d+0"), ("ertesi gün", "d+2")]
CL_PRED = ["takvimde ne var", "programım ne", "neler var", "toplantım var mı", "işim var mı", "etkinliklerimi göster",
           "ne yapacağım", "randevum var mı", "takvimime bak", "planım ne", "programımda ne var", "bir işim var mı",
           "boş muyum", "meşgul müyüm"]


def g_calendar_list(rng, sp, hf, hv):
    if rng.random() < 0.25:
        n = rng.randint(3, 9); tr, d = f"{n} gün sonra", f"d+{n}"
    else:
        tr, d = rng.choice(DAYS)
    p = G.choose(rng, CL_PRED, sp, hf or hv)
    s = f"{tr} {p}" if rng.random() < 0.8 else f"{p}, {tr}"
    if p in ("boş muyum", "meşgul müyüm") and rng.random() < 0.3:
        s += rng.choice([", takvimime bak", ", takvimi kontrol et", ", ajandama bak"])
    return s, {"day": d}


TIMER_VERBS = ["zamanlayıcı kur", "geri sayım başlat", "sayaç başlat", "say", "süre tut", "zamanlayıcı başlat",
               "sayaç kur", "geri sayım yap"]
TIMER_FRAMES = ["{M} dakikalık {V}", "{M} dakika {V}", "{L} için {M} dakika {V}", "{V}: {M} dakika",
                "{M} dakikalık {L} {V}", "{L} için {M} dakikalık {V}", "{V}, {M} dakika", "{M} dk {V}"]


def g_timer(rng, sp, hf, hv):
    m = rng.choice([1, 2, 3, 4, 5, 7, 8, 10, 12, 15, 20, 25, 30, 40, 45, 60, 90, 120])
    f = _frame(rng, sp, TIMER_FRAMES, hf)
    v = _verb(rng, sp, TIMER_VERBS, hv)
    args = {"minutes": m}
    if "{L}" in f:
        lb = pick(rng, TIMER_LABELS, sp, lambda r: random_phrase(r, 1, 2))
        args["label"] = lb
        return _fill(f, M=str(m), L=lb, V=v), args
    return _fill(f, M=str(m), V=v), args


MEM_NOTE = ["bunu hatırla", "şunu aklında tut", "aklında olsun", "kalıcı hafızaya yaz", "hafızana kaydet",
            "bunu unutma", "şunu öğren", "bunu bil"]
MEM_PREF = ["tercihim şu", "benim için kural", "bundan sonra şöyle yap", "bir tercihim var", "kuralım şu",
            "her zaman şöyle olsun", "alışkanlığım şu", "alışkanlığımı kaydet", "tercihimi kaydet"]
# "yeni beceri: X" skill.learn'e aittir (aynı cümle iki komuta etiketlenmesin: model çelişkili veriyle yanlış iş yapar)
MEM_SKILL = ["bu adımları beceri olarak kaydet", "beceri olarak kaydet", "bunu beceri olarak öğren"]


def g_memory(rng, sp, hf, hv):
    x = pick(rng, MEMORY_TEXTS, sp, lambda r: random_phrase(r, 2, 7))
    r = rng.random()
    kind, pool = ("note", MEM_NOTE) if r < 0.5 else ("preference", MEM_PREF) if r < 0.85 else ("skill", MEM_SKILL)
    return f"{G.choose(rng, pool, sp, hf or hv)}: {x}", {"kind": kind, "text": x}


# "becerilerin neler" skill.list'e aittir (Tur 14: help ile çift etiketliydi)
HELP_PHR = ["neler yapabilirsin", "ne yapabiliyorsun", "yeteneklerin neler", "nasıl kullanılırsın", "komutların neler",
            "ne işe yararsın", "hangi işleri yaparsın", "yardım", "bana neler yaparsın", "neler biliyorsun",
            "kullanım kılavuzu", "ne yapabildiğini göster", "komutları göster", "yardım menüsü", "nasıl yardımcı olabilirsin",
            "ne yapabilirsin", "seninle neler yapabilirim"]


def g_help(rng, sp, hf, hv):
    return G.choose(rng, HELP_PHR, sp, hf or hv), {}


ASK_FRAMES = ["{X} nedir", "{X} nasıl yapılır", "{X} ne demek", "{X} neden önemli", "{X} hakkında bilgi ver",
              "{X} nasıl çalışır", "{X} ne işe yarar", "{X} nerede bulunur", "{X} kimdir", "{X} nasıl öğrenilir",
              "{X} ile ilgili ne biliyorsun", "{X} iyi mi kötü mü"]
ASK_PRE = ["", "", "", "soru: ", "bana anlat: ", "merak ediyorum, ", "açıkla: ", "sorum şu: ", "bir sorum var: "]


def g_ask(rng, sp, hf, hv):
    x = pick(rng, ["kara delik", "fotosentez", "yapay zeka", "Osmanlı İmparatorluğu", "kredi kartı faizi", "bulut depolama",
                   "elektrikli araba", "uyku düzeni", "Python dili", "kuantum bilgisayar", "Mars", "enflasyon",
                   "ekmek mayası", "güneş paneli", "deprem", "bağışıklık sistemi"], sp, lambda r: random_phrase(r, 1, 4))
    q = _fill(_frame(rng, sp, ASK_FRAMES, hf or hv), X=x)
    if rng.random() < 0.2:
        return helper_ask(rng, sp, q, hf, hv)
    pre = rng.choice(ASK_PRE)
    return pre + q + ("?" if not pre and rng.random() < 0.5 else ""), {"question": q}


_UNIT_W = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
_TENS_W = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]


def _num_last_word(n: int) -> str:
    """Sayının okunuşundaki son kelime (ek uyumu için): 250 → elli, 18 → sekiz, 300 → yüz, 2000 → bin."""
    if n == 0:
        return "sıfır"
    if n % 10:
        return _UNIT_W[n % 10]
    if n % 100:
        return _TENS_W[(n // 10) % 10]
    if n % 1000:
        return "yüz"
    return "bin"


def num_genitive(n: int) -> str:
    """250'nin, 18'in, 40'ın, 6'nın, 9'un."""
    w = _num_last_word(n)
    v = G.h4(w)
    return f"{n}'{'n' if w[-1] in G.VOWELS else ''}{v}n"


def num_possessive(n: int) -> str:
    """yüzde 18'i, yüzde 20'si, yüzde 6'sı, yüzde 40'ı."""
    w = _num_last_word(n)
    v = G.h4(w)
    return f"{n}'{'s' if w[-1] in G.VOWELS else ''}{v}"


CALC_NUMS = [2, 3, 4, 5, 6, 7, 8, 9, 12, 15, 18, 25, 40, 64, 75, 100, 150, 250, 1250, 3600]
# İşlem kalıpları: ayrılmış (i % 4 == 3) yerlerde yalnızca yeni kalıplar var; Tur 13'te ayrılmış olan
# "bölü"/"kere" kalıpları eğitime alındı (bölü hiç eğitimde yoktu → "4 bölü 250" = 4*250 hatası).
CALC_FORMS = [("{a} artı {b} kaç", "+"), ("{a} eksi {b} kaç", "-"), ("{a} çarpı {b} kaç", "*"), ("{a} ile {b} bölümü kaç", "/"),
              ("{a} ile {b} toplamı kaç", "+"), ("{a} ile {b} farkı kaç", "-"), ("{a} ile {b} çarpımı kaç", "*"),
              ("{a} x {b} ne eder", "*"), ("hesapla: {a}+{b}", "+"), ("hesapla: {a}*{b}", "*"),
              ("{a} x {b} kaç", "*"), ("{a} eksi {b} sonucu ne", "-"),
              ("{a} bölü {b} kaç", "/"), ("{a} kere {b} kaç eder", "*"), ("{a} bölü {b} ne eder", "/"),
              ("{a} ile {b} bölümü ne eder", "/"), ("{a} kere {b} kaç", "*"), ("{a} kere {b} ne eder", "*"),
              ("hesapla: {a} kere {b}", "*"), ("{a} ile {b} toplamı kaç eder", "+"), ("hesapla: {a} bölü {b}", "/"),
              ("{a} eksi {b} ne eder", "-"), ("{a} artı {b} ne eder", "+"), ("{a} ile {b} çarpımı ne eder", "*"),
              ("hesapla: {a} çarpı {b}", "*"), ("{a} çarpı {b} ne eder", "*"), ("{a} artı {b} kaç eder", "+"),
              ("{a} artı {b} eksi {c} kaç", "+-"), ("{a}'{ag} yüzde {b}'{bp} kaç", "%"), ("{a} kere {b} artı {c} kaç", "*+"),
              ("hesapla: {a} artı {b}", "+"), ("hesapla: {a} eksi {b}", "-")]
# Yalnızca eğitimde (Kotlin kural çevirici bu söyleyişleri çözmüyor; test kümeleri değişmesin)
CALC_FORMS_TRAIN = [("{a} sayısının yüzde {b}'{bp} ne eder", "%"), ("{a} kere {b} kaçtır", "*"), ("{a} bölü {b} kaçtır", "/"),
                    ("{a} çarpı {b} eşittir kaç", "*"), ("{a} kere {b} yapar kaç", "*")]


def g_calc(rng, sp, hf, hv):
    def n():
        if sp == "train" and rng.random() < 0.5:
            # Daha geniş sayı havuzu (kopyalama öğrenilsin): 2-999, bazen 1000-99999
            return rng.randint(1000, 99999) if rng.random() < 0.15 else rng.randint(2, 999)
        return rng.choice(CALC_NUMS)
    a, b, c = n(), n(), n()
    if sp == "train" and rng.random() < 0.12:
        f, op = rng.choice(CALC_FORMS_TRAIN)
    else:
        f, op = G.choose(rng, CALC_FORMS, sp, hf or hv)
    if op == "%":
        b = rng.choice([5, 10, 15, 18, 20, 25, 30, 40, 50, 75]) if rng.random() < 0.7 else rng.randint(1, 99)
        expr = f"{a}*{b}/100"
    elif len(op) == 2:
        expr = f"{a}{op[0]}{b}{op[1]}{c}"
    else:
        expr = f"{a}{op}{b}"
    s = f.replace("'{ag}", num_genitive(a)[len(str(a)):]).replace("'{bp}", num_possessive(b)[len(str(b)):])
    return s.format(a=a, b=b, c=c), {"expr": expr}


LANG = [("İngilizce", "en"), ("Almanca", "de"), ("Fransızca", "fr"), ("İspanyolca", "es"), ("Arapça", "ar"),
        ("Rusça", "ru"), ("İtalyanca", "it"), ("Türkçe", "tr")]
TR_FRAMES = ["{LD} çevir: {X}", "{LD} tercüme et: {X}", "şunu {L} yap: {X}", "{L} karşılığı ne: {X}",
             "{L} olarak yaz: {X}", "{L} nasıl söylenir: {X}", "bunu {LD} çevirir misin: {X}", "{L} çevirisi: {X}"]


def g_translate(rng, sp, hf, hv):
    x = pick(rng, NOTE_TEXTS, sp, lambda r: random_phrase(r, 2, 8))
    ln, lc = rng.choice(LANG)
    return _fill(_frame(rng, sp, TR_FRAMES, hf or hv), L=ln, LD=G.dative(ln), X=x), {"text": x, "to": lc}


IMGA = [("ekteki fotoğrafı oku", None), ("bu ekran görüntüsünde ne yazıyor", None), ("fotoğraftaki yazıyı çıkar", None),
        ("resimde ne yazdığını söyle", None), ("ss'i oku", None), ("görseldeki metni çıkar", None),
        ("ekran görüntüsündeki sorunu çöz", "sorunu çöz"), ("fotoğraftaki hatayı çöz", "hatayı çöz"),
        ("resimdeki yazıyı oku", None), ("görseldeki yazıyı oku", None)]
IMGA_Q = ["resmi incele: {Q}", "ekran görüntüsüne bak ve şunu cevapla: {Q}", "fotoğrafa bakıp söyle: {Q}",
          "şu görsele bir bak: {Q}", "ss'e bakar mısın: {Q}", "resimde şunu bul: {Q}", "görsele bak: {Q}",
          "fotoğrafa bak: {Q}"]


def g_image_analyze(rng, sp, hf, hv):
    if rng.random() < 0.4:
        s, q = G.choose(rng, IMGA, sp, hf or hv)
        return s, ({"uri": ATTACHED, "question": q} if q else {"uri": ATTACHED})
    q = pick(rng, QUESTIONS, sp, lambda r: random_phrase(r, 2, 6))
    return _fill(G.choose(rng, IMGA_Q, sp, hf or hv), Q=q), {"uri": ATTACHED, "question": q}


IMGG_VERBS = ["resmi çiz", "görseli oluştur", "resmi yap", "görseli üret", "resmi oluştur", "çizimi yap",
              "illüstrasyonu hazırla", "resmini çiz"]
# "çiz: X" yalnızca karşıt çiftlerde (Kotlin kural çevirici çözmüyor; test kümelerine girmesin)
IMGG_PRE = ["resim oluştur: {X}", "görsel üret: {X}", "bana bir resim çiz: {X}", "görsel oluştur: {X}",
            "{X} temalı bir görsel hazırla", "{X} temalı bir resim çiz"]


def g_image_generate(rng, sp, hf, hv):
    x = pick(rng, IMAGE_PROMPTS, sp, lambda r: random_phrase(r, 2, 6))
    args = {"prompt": x}
    if rng.random() < 0.35:
        return _fill(G.choose(rng, IMGG_PRE, sp, hf or hv), X=x), args
    v = G.choose(rng, IMGG_VERBS, sp, hv)
    size = rng.random()
    pre = ""
    if size < 0.12:
        pre = "dikey bir "; args["size"] = "portrait"
    elif size < 0.24:
        pre = "yatay bir "; args["size"] = "landscape"
    return f"{pre}{x} {v}".strip(), args


FILE_SUBJ = [("ekteki dosyayı", "ekteki dosyanın"), ("bu dosyayı", "bu dosyanın"), ("eklediğim belgeyi", "eklediğim belgenin"),
             ("ekteki pdf'i", "ekteki pdf'in"), ("bu belgeyi", "bu belgenin"), ("eki", "ekin"),
             ("gönderdiğim dosyayı", "gönderdiğim dosyanın"), ("ekli metni", "ekli metnin")]


def g_file(rng, sp, hf, hv):
    acc, gen = G.choose(rng, FILE_SUBJ, sp, hf)
    ln = rng.choice([("", None), ("kısaca ", "short"), ("uzun uzun ", "long"), ("ayrıntılı ", "long"), ("orta uzunlukta ", "medium")])
    verb = G.choose(rng, ["özetle", "özetler misin", "özetini çıkar", "özet geç"], sp, hv)
    args = {"uri": ATTACHED}
    if ln[1]:
        args["length"] = ln[1]
    if verb == "özetini çıkar":
        return f"{gen} {ln[0]}özetini çıkar", args
    if verb == "özet geç":
        return f"{gen} {ln[0]}özetini geç", args
    return f"{acc} {ln[0]}{verb}", args


REPO_FRAMES = ["{R} reposunu {V}", "{R} deposunu {V}", "{R} projesini {V}", "{V}: {R}", "{R} için {V}",
               "{R} projesinin durumunu {V}", "{R} reposunun son halini {V}"]
REPO_VERBS = ["denetle", "kontrol et", "incele", "gözden geçir", "bir bak", "analiz et", "tara", "değerlendir", "özetle"]


def g_repo(rng, sp, hf, hv):
    r = pick(rng, REPOS, sp, random_repo, 0.85)
    args = {"repo": r}
    if rng.random() < 0.3:
        sc, w = rng.choice([("ci", "CI durumunu"), ("ci", "derleme durumunu"), ("security", "güvenliğini")])
        args["scope"] = sc
        return f"{r} {w} {G.choose(rng, REPO_VERBS, sp, hv)}", args
    return _fill(G.choose(rng, REPO_FRAMES, sp, hf), R=r, V=G.choose(rng, REPO_VERBS, sp, hv)), args


def g_card(rng, sp, hf, hv):
    kind = rng.choice(list(CARD_KIND_WORDS)); w = rng.choice(CARD_KIND_WORDS[kind])
    t = pick(rng, CARD_TITLES, sp, lambda r: random_phrase(r, 1, 3, True))
    f = G.choose(rng, ["{W} kartı ekle: {T}", "ana ekrana {W} kartı koy: {T}", "{T} için {W} kartı yap",
                       "'{T}' başlıklı bir {W} kartı ekle", "yeni {W} kartı: {T}", "{T} başlıklı {W} kartı oluştur",
                       "ekrana {W} kartı ekle, adı {T}", "{W} kartı istiyorum: {T}",
                       "{T} için bir {W} kartı hazırla", "ana ekranıma {T} gösteren bir {W} kartı koy", "ekranıma {T} gösteren {W} kartı ekle",
                       "{T} için {W} kartı tasarla", "{T} gösteren {W} kartı ekle"], sp, hf or hv)
    return _fill(f, W=w, T=t), {"kind": kind, "title": t}


def g_discover(rng, sp, hf, hv):
    if rng.random() < 0.4:
        x = pick(rng, NEEDS, sp, lambda r: random_phrase(r, 1, 3))
        f = G.choose(rng, ["{N} için ücretsiz yapay zeka bul", "{N} yapabilen bedava bir model öner",
                           "{N} için ücretsiz bir model ara", "{N} işine yarayan bedava yapay zeka bul"], sp, hf or hv)
        return _fill(f, N=x), {"need": x}
    return G.choose(rng, ["yeni ücretsiz yapay zeka bul", "başka ücretsiz model var mı araştır", "beyne eklenebilecek yeni sağlayıcı ara",
                          "kotası dolmayan yeni bir API bul", "bedava yapay zeka sağlayıcısı bul", "yeni bir ücretsiz model öner",
                          "ücretsiz API ara", "yeni sağlayıcı bul"], sp, hf or hv), {}


def g_health(rng, sp, hf, hv):
    s, upd = G.choose(rng, [("telefonun sağlığını kontrol et", False), ("güncellemeden önce telefonu kontrol et", True),
                            ("pil ve depolama durumu nasıl", False), ("güncelleme yapsam sorun olur mu", True),
                            ("telefon sağlıklı mı", False), ("sistem güncellemesine hazır mıyım", True),
                            ("telefonumun durumu nasıl", False), ("güncellemeye hazır mıyım", True),
                            ("telefonu bir ölç", False), ("telefonun sağlığını ölç", False)], sp, hf or hv)
    return s, ({"purpose": "update"} if upd else {})


COINS = ["bitcoin", "ethereum", "solana", "dogecoin", "XRP", "cardano", "avalanche", "BNB", "tron", "polkadot",
         "litecoin", "chainlink", "shiba", "toncoin", "pepe", "sui"]
CRYPTO_ALL = ["bugün kripto piyasası nasıl", "coin borsası ne durumda", "kripto paralara bak", "kripto piyasasına göz at",
              "coinler ne alemde", "piyasa nasıl, kripto tarafı", "bugün coinler nasıl gidiyor", "kripto durumu ne",
              "coin piyasasını göster", "kriptolar yükselmiş mi", "kripto borsasında durum nasıl", "coin fiyatlarına bak"]
CRYPTO_ONE = ["{C} kaç {P}", "{C} fiyatı ne", "{C} ne durumda", "{C} kaç para", "{C} bugün nasıl", "{C} yükseldi mi",
              "{C} fiyatına bak", "{C} ne kadar oldu"]
CUR_WORDS = [("lira", "try"), ("TL", "try"), ("dolar", "usd"), ("euro", "eur")]


# EkBot fiyat alarmı (2026-11-13): "bitcoin 100 bin dolara çıkınca haber ver" → market.alert. Yön kelimesi varsa yazılır,
# yoksa (ör. "... olunca haber ver") yürütücü anlık fiyata göre seçer. Para birimi yalnız lira denince yazılır (varsayılan usd).
ALERT_UP = ["{C} {N} {P} çıkınca haber ver", "{C} {N} {P} çıkarsa bildir", "{C} {N} {A} geçerse uyar", "{C} {N} {P} çıktığında bana haber ver",
            "{C} {N} {P} yükselirse bildirim at", "{C} {N} {A} aşarsa haber ver", "{C} {N} {P} ulaşırsa beni uyar"]
ALERT_DOWN = ["{C} {N} {P} düşünce haber ver", "{C} {N} {P} düşerse bildir", "{C} {N} {P} inerse uyar", "{C} {N} {P} gerilerse haber ver",
              "{C} {N} {P} düştüğünde bana haber ver", "{C} {N} {P} inince bildirim at", "{C} {N} {Q} altına inerse uyar"]
ALERT_ANY = ["{C} {N} {R} olunca haber ver", "{C} için {N} {R} fiyat alarmı kur", "{C} fiyat alarmı: {N} {R}", "{C} {N} {R} olursa bildir",
             "{C} {N} {R} seviyesine gelince uyar", "{C} fiyatı {N} {R} olunca bana bildir"]
# para kelimesi: (yönelme "dolara", yalın "dolar", tamlayan "doların", belirtme "doları", para birimi)
ALERT_CUR = [("dolara", "dolar", "doların", "doları", "usd"), ("dolara", "dolar", "doların", "doları", "usd"),
             ("liraya", "lira", "liranın", "lirayı", "try"), ("TL'ye", "TL", "TL'nin", "TL'yi", "try")]


def _alert_price(rng) -> tuple[int, str]:
    """(değer, metin): düz rakam, "N bin" ya da noktalı binlik."""
    base = rng.choice([1, 2, 3, 5, 8, 12, 25, 40, 60, 75, 90, 100, 120, 150, 250, 500, 750, 1000, 2500, 4000, 65000, 90000, 100000, 120000])
    r = rng.random()
    if r < 0.2 and base < 1000:
        return base * 1000, f"{base} bin"
    if r < 0.35 and base >= 1000:
        return base, f"{base:,}".replace(",", ".")
    return base, str(base)


def g_alert(rng, sp, hf, hv):
    coin = pick(rng, COINS, sp)
    price, ptxt = _alert_price(rng)
    to, bare, gen, acc, cur = rng.choice(ALERT_CUR)
    r = rng.random()
    if r < 0.42:
        f, d = G.choose(rng, ALERT_UP, sp, hf or hv), "above"
    elif r < 0.8:
        f, d = G.choose(rng, ALERT_DOWN, sp, hf or hv), "below"
    else:
        f, d = G.choose(rng, ALERT_ANY, sp, hf or hv), None
    args = {"coin": coin, "price": price}
    if d:
        args["direction"] = d
    if cur != "usd":
        args["currency"] = cur
    return _fill(f, C=coin, N=ptxt, P=to, Q=gen, R=bare, A=acc), args


def g_crypto(rng, sp, hf, hv):
    if rng.random() < 0.4:
        s = G.choose(rng, CRYPTO_ALL, sp, hf or hv)
        if rng.random() < 0.3:
            w, c = rng.choice(CUR_WORDS)
            return f"{s}, {w} olarak", {"currency": c}
        return s, {}
    # Rastgele kelime kullanılmaz: "domates kaç TL" kripto sorusu sanılmasın.
    coin = pick(rng, COINS, sp)
    f = G.choose(rng, CRYPTO_ONE, sp, hf or hv)
    w, c = rng.choice(CUR_WORDS)
    args = {"coin": coin}
    if "{P}" in f:
        if c != "try" or rng.random() < 0.5:
            args["currency"] = c
        return _fill(f, C=coin, P=w), args
    return _fill(f, C=coin), args


SKILL_NAMES = ["sabah rutini", "akşam kontrolü", "kripto özeti", "haftalık plan", "iş başlangıcı", "spor takibi",
               "okuma listesi", "gün sonu raporu", "proje durumu", "hafta sonu planı", "fatura kontrolü", "kod çalışması"]
SKILL_GOALS = ["her sabah takvimimi ve kripto piyasasını özetle", "github'da yapay zeka ajanları için iyi repolar bul ve not al",
               "haftalık harcamalarımı notlardan derle", "bana her akşam yarının planını çıkar", "yeni çıkan Android güncellemelerini takip et",
               "okuduğum kitapları not alıp haftalık özetle", "anahtarlı yapay zekalar için kullanılabilir bir çözüm bul",
               "işe yarar ücretsiz araçlar bulup listele"]
ROLES = ["kaynakları doğrulayan titiz araştırmacı", "kod örneklerini inceleyen yazılımcı", "kısa ve net özet çıkaran editör",
         "fiyat ve piyasa verisini yorumlayan analist", "Türkçe metinleri düzelten yazım uzmanı", "görsel fikir üreten tasarımcı"]
AGENT_TR = [("Sophia", "sophia", "'ya"), ("Jack", "jack", "'e"), ("Emma", "emma", "'ya"), ("Chloe", "chloe", "'ye"),
            ("Luna", "luna", "'ya"), ("Mike", "mike", "'a"), ("David", "david", "'e"), ("Maya", "maya", "'ya"), ("Grace", "grace", "'e"),
            ("EkBot", "ekbot", "'a"), ("Leo", "leo", "'ya"), ("Nora", "nora", "'ya"), ("Iris", "iris", "'e"), ("Zoe", "zoe", "'ye")]


def g_skill_run(rng, sp, hf, hv):
    x = pick(rng, SKILL_NAMES, sp, lambda r: random_phrase(r, 1, 3))
    v = G.choose(rng, ["çalıştır", "kullan", "uygula", "başlat", "yap"], sp, hv)
    if rng.random() < 0.35:
        inp = pick(rng, NOTE_TEXTS, sp, lambda r: random_phrase(r, 1, 5))
        return f"{x} becerisini {v}: {inp}", {"name": x, "input": inp}
    return f"{x} becerisini {v}", {"name": x}


def g_skill_list(rng, sp, hf, hv):
    return G.choose(rng, ["becerilerimi göster", "becerilerin neler", "hangi becerilerin var", "becerileri listele",
                          "araçlarını göster", "dış ajanları göster", "becerilerini göster", "becerilerin ne"], sp, hf or hv), {}


SKILL_CONVERBS = ["bulup", "toplayıp", "okuyup", "inceleyip", "derleyip", "karşılaştırıp", "araştırıp", "seçip",
                  "ayıklayıp", "özetleyip", "kontrol edip", "sıralayıp"]
SKILL_FINAL_VERBS = ["listele", "özetle", "bul", "derle", "takip et", "çıkar", "hazırla", "karşılaştır", "raporla",
                     "bildir", "göster", "sırala", "gönder", "incele", "hesapla"]


def _skill_goal(rng: random.Random) -> str:
    """Eğitim hedefi; çoğu emir fiiliyle biter ("... araçlar bulup listele"): son fiil hedefe dahildir (Tur 13 hatası)."""
    r = rng.random()
    if r < 0.4:
        return f"{random_phrase(rng, 1, 4)} {rng.choice(SKILL_CONVERBS)} {rng.choice(SKILL_FINAL_VERBS)}"
    if r < 0.8:
        return f"{random_phrase(rng, 2, 6)} {rng.choice(SKILL_FINAL_VERBS)}"
    return random_phrase(rng, 3, 8)


def g_skill_learn(rng, sp, hf, hv):
    goal = pick(rng, SKILL_GOALS, sp, _skill_goal)
    pre = G.choose(rng, ["beceri öğren", "yeni beceri öğren", "şunu yapmayı öğren", "yeni beceri"], sp, hf or hv)
    return f"{pre}: {goal}", {"goal": goal}


def g_skill_record(rng, sp, hf, hv):
    x = pick(rng, SKILL_NAMES, sp, lambda r: random_phrase(r, 1, 3))
    if rng.random() < 0.6:
        n = rng.randint(1, 8)
        w = G.choose(rng, ["işi", "adımı", "komutu"], sp, hv)
        return f"son {n} {w} beceri olarak kaydet: {x}", {"name": x, "count": n}
    pre = G.choose(rng, ["son yaptıklarımı", "bunları", "bunu"], sp, hf)
    return f"{pre} beceri olarak kaydet: {x}", {"name": x}


def g_agent_hire(rng, sp, hf, hv):
    role = pick(rng, ROLES, sp, lambda r: random_phrase(r, 2, 6))
    v = G.choose(rng, ["yardımcı ajan ekle", "yardımcı al", "dış ajan ekle", "yardımcı ajan al"], sp, hf or hv)
    if rng.random() < 0.7:
        name, aid, suf = rng.choice(AGENT_TR)
        return f"{name}{suf} {v}: {role}", {"role": role, "helps": aid}
    return f"{v}: {role}", {"role": role}


MAIL_CHECK = ["yeni maillerime bak", "e-postalarımı kontrol et", "gelen kutuma bak", "yeni mail var mı", "maillerimi oku",
              "e-postalarım neler", "gelen kutusunu göster", "postalarıma bak", "mail geldi mi", "e-posta kutumu kontrol et"]
MAIL_TO = ["ali@ornek.com", "ayse.yilmaz@gmail.com", "info@sirket.com.tr", "destek@uygulama.io", "mehmet@okul.edu.tr"]
MAIL_SUBJ = ["Yarınki toplantı", "Fatura hakkında", "Proje güncellemesi", "Teşekkürler", "Randevu talebi", "Haftalık rapor"]


def g_mail_check(rng, sp, hf, hv):
    s = G.choose(rng, MAIL_CHECK, sp, hf or hv)
    r = rng.random()
    if r < 0.25:
        n = rng.choice([3, 5, 10, 20])
        return f"son {n} maili göster", {"count": n}
    if r < 0.4:
        who = rng.choice(NAMES)
        return f"{who}'dan mail geldi mi", {"query": who}
    return s, {}


def g_mail_send(rng, sp, hf, hv):
    to = rng.choice(MAIL_TO)
    subj = pick(rng, MAIL_SUBJ, sp, lambda r: random_phrase(r, 1, 4, True))
    body = pick(rng, NOTE_TEXTS, sp, lambda r: random_phrase(r, 3, 10))
    v = G.choose(rng, ["mail yaz", "e-posta gönder", "mail at", "e-posta hazırla"], sp, hf or hv)
    return f"{to} adresine {v}: konu: {subj}; {body}", {"to": to, "subject": subj, "body": body}


APP_SEARCH = [("YouTube'da", "YouTube"), ("Spotify'da", "Spotify"), ("Haritalarda", "Haritalar"), ("Google'da", "Google"),
              ("Play Store'da", "Play Store"), ("GitHub'da", "GitHub"), ("Vikipedi'de", "Vikipedi")]
APP_OPEN = [("Spotify'ı", "Spotify"), ("WhatsApp'ı", "WhatsApp"), ("Instagram'ı", "Instagram"), ("YouTube'u", "YouTube"),
            ("Telegram'ı", "Telegram"), ("Gmail'i", "Gmail"), ("kamerayı", "kamera"), ("ayarları", "ayarlar"), ("Netflix'i", "Netflix")]
APP_QUERIES = ["lofi müzik", "Kadıköy", "kotlin dersleri", "yapay zeka haberleri", "türkçe rap", "orion takımyıldızı",
               "pilav tarifi", "android geliştirme", "satranç açılışları", "yakındaki eczaneler"]


def g_app_open(rng, sp, hf, hv):
    if rng.random() < 0.6:
        loc, name = rng.choice(APP_SEARCH)
        q = pick(rng, APP_QUERIES, sp, lambda r: random_phrase(r, 1, 3))
        v = G.choose(rng, ["ara", "bul", "aç", "göster"], sp, hv)
        return f"{loc} {q} {v}", {"name": name, "query": q}
    acc, name = rng.choice(APP_OPEN)
    if rng.random() < 0.3:
        return f"{name} uygulamasını {G.choose(rng, ['aç', 'başlat', 'çalıştır'], sp, hv)}", {"name": name}
    return f"{acc} {G.choose(rng, ['aç', 'başlat'], sp, hv)}", {"name": name}


def g_app_list(rng, sp, hf, hv):
    return G.choose(rng, ["uygulamalarımı göster", "hangi uygulamalar var", "kurulu uygulamaları listele", "telefondaki uygulamalar neler",
                          "uygulamalarımı listele", "hangi uygulamalarım var"], sp, hf or hv), {}


RECALL_TOPICS = ["annem", "babam", "ailem", "eşim", "işim", "okulum", "sağlığım", "rutinlerim", "tercihlerim", "kardeşim",
                 "arkadaşlarım", "çocuklarım", "evim", "alışkanlıklarım", "sevdiklerim"]


def g_memory_recall(rng, sp, hf, hv):
    """Katmanlı hafıza: Orion kullanıcı hakkında ne biliyor (query: konu, ör. annem)."""
    if rng.random() < 0.35:
        t = pick(rng, RECALL_TOPICS, sp)
        v = G.choose(rng, ["ne biliyorsun", "neler biliyorsun", "ne hatırlıyorsun", "neler hatırlıyorsun"], sp, hv)
        frame = G.choose(rng, ["{t} hakkında {v}", "benim {t} hakkında {v}", "{t} ile ilgili {v}"], sp, hf)
        return frame.format(t=t, v=v), {"query": t}
    return G.choose(rng, ["hakkımda ne biliyorsun", "beni ne kadar tanıyorsun", "beni tanıyor musun", "neleri hatırlıyorsun",
                          "hafızanda neler var", "hakkımda neler biliyorsun", "beni hatırlıyor musun", "hakkımda bildiklerini göster",
                          "hafızamı göster", "kişiliğimi özetle", "hakkımda neler öğrendin", "beni ne kadar iyi tanıyorsun"],
                    sp, hf or hv), {}


def g_self_status(rng, sp, hf, hv):
    return G.choose(rng, ["gelişim durumu", "gelişimin ne durumda", "yeni sürüm var mı", "güncelleme var mı", "kendini güncelle",
                          "yeni beyin var mı", "eğitim ne durumda", "gelişimini kontrol et", "gelişimine bak", "yeni beyin sürümü çıktı mı"],
                    sp, hf or hv), {}


# --------------------------------------------------------------------------- kod ekibi (Leo, Nora, Iris; 2026-11-13)
# Görev (task) cümlenin kendisidir: Kotlin kural çevirici de tüm cümleyi verir (hitap ve kibarlık atılır).
# Ortam/internet etiketleri RuleTranslator.codeRun kurallarıyla aynıdır; görev ifadeleri bu tetikleri İÇERMEZ.

CODE_TASKS = ["1'den 100'e kadar asal sayıları bul", "bu listedeki sayıların ortalamasını hesapla", "metindeki kelimeleri say",
              "250 ile 17'nin ekokunu hesapla", "verilen tarihler arasındaki gün farkını hesapla", "harcamaları kategoriye göre topla",
              "isim listesini alfabetik sırala", "metindeki e-posta adreslerini ayıkla", "fibonacci dizisinin ilk 20 terimini listele",
              "kredi taksitlerini hesapla", "Celsius değerlerini Fahrenheit'a çevir", "tekrar eden satırları temizle",
              "notlarımdaki tarihleri bul", "en sık geçen beş kelimeyi listele", "iki listeyi birleştir", "çarpım tablosunu üret",
              "metni cümlelere ayır", "sayıların medyanını hesapla", "rastgele güçlü bir parola üret", "faiz getirisini hesapla"]
CODE_NET_TASKS = ["dolar kurunu çek", "bitcoin fiyatını çek", "Vikipedi özetini çek", "hava tahminini çek",
                  "son depremleri çek", "euro kurunu çek", "altın fiyatını çek", "haber başlıklarını çek"]
CODE_VERBS_END = ["bul", "hesapla", "say", "listele", "sırala", "ayıkla", "üret", "topla", "çevir", "temizle"]
_CODE_BAD = re.compile(r"python|javascript|\bjs\b|github|atolye|telefonda|kutuda|internet|web|site|\bapi\b|cevrimici|online|canli veri|guncel|http|"
                       r"nasil|nedir|ne demek|neden|niye|ogren|ogret|kod|program|betik|script|fonksiyon|algoritma")


def _code_task(rng, sp):
    def rand(r):
        return random_phrase(r, 1, 4) + " " + r.choice(CODE_VERBS_END)
    for _ in range(30):
        t = pick(rng, CODE_TASKS, sp, rand, 0.5)
        if not _CODE_BAD.search(_fold(t)):
            return t
    return rng.choice(_split(CODE_TASKS, sp))


def _fold(s: str) -> str:
    from .dialogs import fold
    return fold(s)


CODE_MAKE_FRAMES = ["kod yaz: {T}", "{T} için kod yaz", "bir program yaz: {T}", "{T}, bunun için bir betik yaz", "kodla {T}",
                    "kod yazarak {T}", "bir fonksiyon yaz: {T}", "{T} için küçük bir program oluştur", "{T} diye bir kod hazırla",
                    "betikle {T}", "{T} için bir script yaz", "{T}, kodunu yaz"]


def g_code_run(rng, sp, hf, hv):
    r = rng.random()
    if r < 0.18:
        t = rng.choice(_split(CODE_NET_TASKS, sp))
        f = G.choose(rng, ["internetten {T}en bir kod yaz", "internete çıkıp {T}en bir program yaz", "kodla internetten {T}",
                           "internetten {T}, bunun için kod yaz"], sp, hf or hv)
        tr = _fill(f, T=t)  # "{T}en": "dolar kurunu çek" → "dolar kurunu çeken"
        return tr, {"task": tr, "net": True}
    t = _code_task(rng, sp)
    if r < 0.33:
        f = G.choose(rng, ["python ile {T}", "pythonla {T}", "GitHub'da python ile {T}", "python ile {T}, kodunu yaz"], sp, hf or hv)
        tr = _fill(f, T=t)
        return tr, {"task": tr, "env": "github"}
    if r < 0.45:
        f = G.choose(rng, ["javascript ile {T}", "telefonda kodla {T}", "js ile {T}", "telefonda {T} için kod yaz"], sp, hf or hv)
        tr = _fill(f, T=t)
        return tr, {"task": tr, "env": "phone"}
    tr = _fill(G.choose(rng, CODE_MAKE_FRAMES, sp, hf or hv), T=t)
    return tr, {"task": tr}


REPO_FIX_THINGS = ["kurulum adımını", "yazım hatalarını", "eski sürüm numarasını", "bozuk bağlantıyı", "lisans satırını",
                   "açıklama paragrafını", "örnek komutu", "başlığı", "Türkçe karakter hatalarını", "eksik virgülleri",
                   "eski ekran görüntüsü bağlantısını", "çalıştırma komutunu"]
REPO_FIX_PATHS = ["README.md", "docs/KURULUM.md", "main.py", "src/index.js", "config.json", "CHANGELOG.md", "app/build.gradle.kts",
                  ".github/workflows/ci.yml", "docs/PROTOCOL.md", "requirements.txt"]
REPO_FIX_VERBS = ["düzelt", "güncelle", "değiştir", "düzenle"]


def g_code_repo(rng, sp, hf, hv):
    rep = pick(rng, REPOS, sp, random_repo, 0.85)
    x = pick(rng, REPO_FIX_THINGS, sp)
    v = G.choose(rng, REPO_FIX_VERBS, sp, hv)
    if rng.random() < 0.7:
        pth = pick(rng, REPO_FIX_PATHS, sp)
        f = G.choose(rng, ["{R} deposunda {P} dosyasındaki {X} {V}", "{R} reposunda {P} içinde {X} {V}", "{R} {P} {X} {V}",
                           "{R} deposundaki {P} dosyasında {X} {V}", "{R} için {P} dosyasındaki {X} {V}"], sp, hf)
        tr = _fill(f, R=rep, P=pth, X=x, V=v)
        return tr, {"repo": rep, "task": tr, "path": pth}
    f = G.choose(rng, ["{R} deposunda {X} {V}", "{R} reposunda {X} {V}", "{R} projesinde {X} {V}"], sp, hf)
    tr = _fill(f, R=rep, X=x, V=v)
    return tr, {"repo": rep, "task": tr}


WORK_CHECK_PHRASES = ["bunu kontrol et", "şunu doğrula", "son cevabı kontrol et", "cevabını doğrula", "bu sonucu denetle",
                      "yaptığın işi gözden geçir", "bunu bir daha kontrol et", "denetçilere kontrol ettir", "doğru mu kontrol et",
                      "bu cevabı teyit et", "son cevabını doğrula", "sonucu kontrol et", "bu işi denetle", "söylediğini doğrula",
                      "bunu iki kez kontrol et"]
WORK_CHECK_TEXTS = ["İstanbul'un nüfusu 16 milyondur", "Ay Dünya'dan 384 bin kilometre uzaktadır", "250'nin yüzde 18'i 45 eder",
                    "Ankara 1923'te başkent oldu", "suyun kaynama noktası 100 derecedir", "bir yılda 52 hafta vardır",
                    "Everest 8848 metredir", "ışık hızı saniyede 300 bin kilometredir"]


def g_work_check(rng, sp, hf, hv):
    if rng.random() < 0.3:
        x = pick(rng, WORK_CHECK_TEXTS, sp, lambda r: random_phrase(r, 3, 8), 0.5)
        v = G.choose(rng, ["şunu doğrula", "bunu kontrol et", "şunu kontrol et", "doğrula", "teyit et", "şunu denetle"], sp, hf or hv)
        return f"{v}: {x}", {"text": x}
    return G.choose(rng, WORK_CHECK_PHRASES, sp, hf or hv), {}


# --------------------------------------------------------------------------- Grace / Maya araçları (2026-11-14)
SEO_SITES = ["ornekkahve.com", "benimdukkanim.com.tr", "yogastudyo.net", "kitapkosesi.com", "evdekiusta.com.tr", "tatlicitulin.com",
             "kodokulu.org", "bisikletci.shop", "minikmama.com", "anadolutur.com.tr", "sanatatolye.net", "tamirci34.com"]
SEO_PATHS = ["", "", "", "/blog", "/urunler", "/hakkimizda", "/blog/kahve-demleme", "/iletisim", "/menu"]
SEO_KWS = ["kahve", "yoga dersi", "ikinci el kitap", "kombi tamiri", "doğum günü pastası", "python kursu", "bisiklet bakımı",
           "organik mama", "kapadokya turu", "seramik atölyesi", "telefon tamiri", "ev temizliği"]
SEO_FRAMES = ["{U} sitesinin SEO denetimini yap", "{U} için SEO kontrolü yap", "{U} sayfasının SEO'suna bak", "seo denetimi: {U}",
              "{U} adresini SEO açısından incele", "Grace, {U} sitemin SEO'sunu kontrol et", "{U} arama motoruna uygun mu, SEO'suna bak",
              "{U} sayfamın site içi SEO eksiklerini çıkar"]
SEO_KW_FRAMES = ["{U} sitesinin SEO denetimini yap, anahtar kelime: {K}", "{U} için SEO kontrolü, anahtar kelime {K}",
                 "{U} sayfası '{K}' anahtar kelimesiyle SEO açısından nasıl", "seo denetimi: {U} anahtar kelime: {K}",
                 "Grace, {U} sitemin SEO'sunu {K} anahtar kelimesine göre incele", "{U} SEO'su nasıl, anahtar kelimem {K}"]


SEO_WATCH_FRAMES = ["{U} sitesinin SEO denetimini her hafta yap", "{U} SEO'sunu haftada bir kontrol et", "{U} sitemi SEO için takip et",
                    "Grace, {U} sayfasının SEO'sunu izle", "{U} için haftalık SEO denetimi kur"]


def g_seo(rng, sp, hf, hv):
    url = "https://" + rng.choice(["", "www."]) + pick(rng, SEO_SITES, sp) + rng.choice(SEO_PATHS)
    if rng.random() < 0.2:
        return _fill(G.choose(rng, SEO_WATCH_FRAMES, sp, hf or hv), U=url), {"url": url, "watch": True}
    if rng.random() < 0.5:
        kw = pick(rng, SEO_KWS, sp, lambda r: random_phrase(r, 1, 2), 0.5)
        return _fill(G.choose(rng, SEO_KW_FRAMES, sp, hf or hv), U=url, K=kw), {"url": url, "keyword": kw}
    return _fill(G.choose(rng, SEO_FRAMES, sp, hf or hv), U=url), {"url": url}


# --------------------------------------------------------------------------- Sophia: gerçek internet (2026-11-23)
# Sahibin kararı: "Orion internete çıkmalı". web.search = internette arama (araştırma görevinden ayrı: sonuç listesi),
# web.read = verilen https adresindeki sayfayı okumak. "X nedir" soruları ask'ta kalır; "araştır" research.start'ta.
WEB_QUERIES = ["kara delik nedir", "istanbul hava kirliliği", "elektrikli araba şarj istasyonları", "ankara kitap fuarı",
               "en iyi kahve demleme yöntemi", "python öğrenme kaynakları", "deprem çantasında ne olmalı", "galatasaray son maç",
               "türkiye enflasyon oranı", "yapay zeka haberleri", "kapadokya balon turu fiyatları", "evde ekmek tarifi",
               "redmi note 13 pro güncelleme", "kombi bakımı nasıl yapılır", "uzay teleskobu yeni görüntüler", "izmir konser takvimi"]
WEB_SEARCH_FRAMES = ["internette {Q} ara", "{Q} diye internette ara", "webde {Q} ara", "internetten {Q} araştır bul",
                     "{Q} için internette arama yap", "Sophia, internette {Q} ara", "{Q} hakkında internette ne var, ara",
                     "google'da {Q} ara", "{Q} diye bir arama yap internette", "internette arat: {Q}", "{Q} için web araması yap",
                     "nette {Q} ara bakalım"]
WEB_SEARCH_N_FRAMES = ["internette {Q} ara, ilk {N} sonucu göster", "{Q} için internette ara, {N} sonuç yeter",
                       "webde {Q} ara ve {N} sonuç getir", "internette {Q} ara bana {N} tane sonuç ver"]
WEB_SEARCH_READ_FRAMES = ["internette {Q} ara ve ilk sonucu oku", "{Q} diye ara, ilk çıkan sayfayı oku",
                          "internette {Q} ara, en iyi sonucu okuyup anlat", "webde {Q} ara ve ilk sayfayı özetle"]
WEB_SITES = ["ntv.com.tr/teknoloji", "bilimgenc.tubitak.gov.tr/makale", "tr.wikipedia.org/wiki/Kara_delik", "haberler.com/ekonomi",
             "evrimagaci.org/kara-delikler", "mgm.gov.tr/tahmin", "ornekblog.com/kahve-demleme", "yemek.com/tarif/ekmek",
             "donanimhaber.com/redmi-note-13", "afad.gov.tr/deprem-cantasi", "kodokulu.org/python-baslangic", "sozcu.com.tr/spor"]
WEB_READ_FRAMES = ["şu sayfayı oku: {U}", "{U} sayfasını oku", "{U} adresindeki yazıyı oku", "{U} linkini aç ve oku",
                   "bu bağlantıda ne yazıyor: {U}", "{U} sayfasında ne anlatılıyor oku", "Sophia, {U} sayfasını okur musun",
                   "{U} adresine gir, yazanı oku", "şu linki oku bana: {U}", "{U} sayfasını okuyup özetle",
                   "{U} haberini oku", "oku: {U}"]
WEB_LEARN_FRAMES = ["{U} sayfasını oku ve öğren", "{U} adresindeki bilgiyi öğren", "şu sayfadan öğren: {U}",
                    "{U} sayfasını oku, bilgini hafızana yaz", "{U} yazısını oku ve aklında tut"]


def g_web_search(rng, sp, hf, hv):
    q = pick(rng, WEB_QUERIES, sp, lambda r: random_phrase(r, 1, 4), 0.5)
    r = rng.random()
    if r < 0.15:
        n = rng.choice([3, 5, 10])
        return _fill(G.choose(rng, WEB_SEARCH_N_FRAMES, sp, hf or hv), Q=q).replace("{N}", str(n)), {"query": q, "n": n}
    if r < 0.27:
        return _fill(G.choose(rng, WEB_SEARCH_READ_FRAMES, sp, hf or hv), Q=q), {"query": q, "read": True}
    return _fill(G.choose(rng, WEB_SEARCH_FRAMES, sp, hf or hv), Q=q), {"query": q}


def g_web_read(rng, sp, hf, hv):
    url = "https://" + rng.choice(["", "www."]) + pick(rng, WEB_SITES, sp)
    if url.startswith("https://www.tr."):
        url = url.replace("https://www.", "https://", 1)
    if rng.random() < 0.2:
        return _fill(G.choose(rng, WEB_LEARN_FRAMES, sp, hf or hv), U=url), {"url": url, "learn": True}
    return _fill(G.choose(rng, WEB_READ_FRAMES, sp, hf or hv), U=url), {"url": url}


AD_TEXTS = ["Taze kahve kapında | Hemen sipariş ver", "Yaz indirimi başladı! Tüm ürünlerde %30", "Ücretsiz deneme dersi için hemen kaydol",
            "El yapımı seramik kupalar | Sınırlı sayıda", "Kombi bakımında kış fırsatı, randevunu al", "Yeni sezon bisikletleri incele",
            "Organik mama ile mutlu dostlar | Ücretsiz kargo", "Kapadokya balon turu erken rezervasyon fırsatı"]
AD_FRAMES = ["reklam metnimi kontrol et: {T}", "bu reklam metni sınırlara uyuyor mu: {T}", "Maya, reklam başlığımı denetle: {T}",
             "reklam metni karakter kontrolü: {T}", "şu reklam metnini incele: {T}", "reklam yazım uygun mu, kontrol et: {T}"]
AD_META_FRAMES = ["instagram reklam metnimi kontrol et: {T}", "facebook reklamım için metni denetle: {T}", "meta reklam metni uygun mu: {T}",
                  "insta reklamı için şu metni kontrol et: {T}"]


def g_ad_check(rng, sp, hf, hv):
    t = pick(rng, AD_TEXTS, sp, lambda r: random_phrase(r, 3, 9), 0.5)
    if rng.random() < 0.4:
        return _fill(G.choose(rng, AD_META_FRAMES, sp, hf or hv), T=t), {"text": t, "platform": "meta"}
    return _fill(G.choose(rng, AD_FRAMES, sp, hf or hv), T=t), {"text": t}


AD_BUDGET_FRAMES = ["{B} TL bütçeyle tıklama başı {C} TL ise kaç tıklama alırım", "reklam bütçem {B} TL, tıklama başına {C} TL, kaç tıklama eder",
                    "{B} liralık bütçe ve {C} TL tıklama başı maliyetle kaç kişi gelir", "Maya, {B} TL bütçe tıklama başı {C} TL hesapla",
                    "bütçe {B} TL, cpc {C}: kaç tıklama", "{B} TL reklam bütçesiyle tıklama başı {C} lira olursa ne olur"]
AD_CONV_TAIL = [", dönüşüm oranı %{V}", ", dönüşüm %{V} olursa kaç satış olur", " ve dönüşüm yüzde {V}"]
AD_PRICE_TAIL = [", ürün fiyatı {P} TL", ", ürün {P} TL", " ve sepet tutarı {P} TL"]


def g_ad_budget(rng, sp, hf, hv):
    b = rng.choice([500, 1000, 1500, 2000, 2500, 3000, 5000, 7500, 10000, 15000, 20000, 50000])
    btxt = f"{b:,}".replace(",", ".") if b >= 10000 and rng.random() < 0.6 else str(b)
    c = rng.choice(["1", "2", "2,5", "3", "3,5", "4", "0,8", "1,2", "5", "7,5", "10"])
    text = _fill(G.choose(rng, AD_BUDGET_FRAMES, sp, hf or hv), B=btxt, C=c)
    args = {"budget": b, "cpc": c}
    if rng.random() < 0.5:
        v = rng.choice(["1", "2", "2,5", "3", "4", "5", "0,5"])
        text += rng.choice(AD_CONV_TAIL).replace("{V}", v)
        args["conv"] = v
        if rng.random() < 0.5:
            p = rng.choice([150, 250, 400, 600, 900, 1200])
            text += rng.choice(AD_PRICE_TAIL).replace("{P}", str(p))
            args["price"] = p
    return text, args


# --------------------------------------------------------------------------- Luna / Sophia / Jack / Mike araçları (2026-11-14)
COLOR_NAMES = ["mavi", "lacivert", "kırmızı", "yeşil", "sarı", "turuncu", "mor", "pembe", "siyah", "beyaz", "gri", "turkuaz", "bordo", "mint", "krem"]
COLOR_HEX = ["#1E88E5", "#E53935", "#2E7D32", "#FDD835", "#3EB489", "#212121", "#F5F5F5", "#8E24AA", "#00ACC1", "#FF7043", "#263238", "#FFC107"]
PALETTE_FRAMES = ["{A} için renk paleti çıkar", "{A} rengine uygun palet öner", "Luna, {A} ana rengiyle palet hazırla", "{A} rengiyle uyumlu renkler bul",
                  "{A} için palet oluştur", "ana rengim {A}, paleti çıkar"]
CONTRAST_FRAMES = ["{A} yazı {B} zeminde okunur mu", "{A} metin {B} arka plan kontrastı ne", "{A} ile {B} kontrastını ölç",
                   "Luna, {A} yazıyı {B} zemin üstünde okunurluk açısından kontrol et", "{B} zemine {A} yazı okunabilir mi", "kontrast: {A} ve {B}"]


def g_colors(rng, sp, hf, hv):
    # Eğitimde elle yazılmış/kör değerlendirme cümlesinin aynısı üretilmez (renk çiftleri az; çakışma olabiliyordu)
    for _ in range(20):
        tr, args = _g_colors_once(rng, sp, hf, hv)
        if sp != "train" or not _fenced(tr):
            return tr, args
    return tr, args


def _g_colors_once(rng, sp, hf, hv):
    def col():
        return rng.choice(COLOR_HEX) if rng.random() < 0.5 else rng.choice(COLOR_NAMES)
    if rng.random() < 0.45:
        a = col()
        return _fill(G.choose(rng, PALETTE_FRAMES, sp, hf or hv), A=a), {"colors": [a]}
    a, b = col(), col()
    while b == a:
        b = col()
    f = G.choose(rng, CONTRAST_FRAMES, sp, hf or hv)
    # Komut sırası: yazı (A), zemin (B); cümlede zemin önce gelse de
    return _fill(f, A=a, B=b), {"colors": [a, b]}


WATCH_TOPICS = ["yapay zeka", "iklim değişikliği", "mars keşfi", "kuantum bilgisayar", "elektrikli otomobil", "türk sineması",
                "dünya kupası", "deprem", "uzay teleskobu", "yenilenebilir enerji", "blokzincir", "osmanlı tarihi"]
TOPIC_WATCH_FRAMES = ["{T} konusunu takip et", "{T} konusunu izle, değişince haber ver", "Sophia, {T} konusunu takipte tut",
                      "{T} konusundaki gelişmeleri takip et", "{T} maddesini izle", "{T} hakkındaki gelişmeleri izle"]
TOPIC_UNWATCH_FRAMES = ["{T} konusunu takip etmeyi bırak", "{T} konusunu izlemeyi bırak", "{T} konusunun takibini kaldır"]
REPOS = ["eskay/orion", "torvalds/linux", "kotlin/kotlinx.coroutines", "openai/whisper", "square/okhttp", "pallets/flask",
         "facebook/react", "google/guava", "psf/requests", "vuejs/core"]
REPO_WATCH_FRAMES = ["{R} deposunu izle, CI kırılınca haber ver", "{R} deposunu nöbete al", "Jack, {R} reposunu takip et",
                     "{R} deposunu izle", "{R} derlemesi kırılırsa haber ver, takip et", "{R} reposuna göz kulak ol"]
REPO_UNWATCH_FRAMES = ["{R} deposunu izlemeyi bırak", "{R} deposunun takibini kaldır", "{R} reposunu takip etmeyi bırak"]
DIGEST_FRAMES = ["her akşam günün özetini gönder", "her akşam saat {H}'de günün özetini gönder", "akşam özeti istiyorum",
                 "Mike, her gün ekibin özetini at", "günlük özet bildirimini aç", "gün sonu özeti saat {H}'de gelsin"]
DIGEST_OFF_FRAMES = ["akşam özetini kapat", "günlük özet istemiyorum", "gün sonu özetini durdur"]
DUTY_LIST = ["nöbetleri göster", "neleri izliyorsun", "takip ettiklerini listele", "ajan nöbetlerini göster", "kurulu nöbetler neler"]


def g_research_watch(rng, sp, hf, hv):
    r = rng.random()
    if r < 0.15:
        return G.choose(rng, DUTY_LIST, sp, hf or hv), {"action": "list"}
    t = pick(rng, WATCH_TOPICS, sp, lambda q: random_phrase(q, 1, 3), 0.5)
    if r < 0.3:
        return _fill(G.choose(rng, TOPIC_UNWATCH_FRAMES, sp, hf or hv), T=t), {"topic": t, "action": "remove"}
    return _fill(G.choose(rng, TOPIC_WATCH_FRAMES, sp, hf or hv), T=t), {"topic": t}


def g_repo_watch(rng, sp, hf, hv):
    repo = pick(rng, REPOS, sp)
    if rng.random() < 0.2:
        return _fill(G.choose(rng, REPO_UNWATCH_FRAMES, sp, hf or hv), R=repo), {"repo": repo, "action": "remove"}
    return _fill(G.choose(rng, REPO_WATCH_FRAMES, sp, hf or hv), R=repo), {"repo": repo}


def g_work_digest(rng, sp, hf, hv):
    if rng.random() < 0.2:
        return G.choose(rng, DIGEST_OFF_FRAMES, sp, hf or hv), {"action": "off"}
    f = G.choose(rng, DIGEST_FRAMES, sp, hf or hv)
    if "{H}" in f:
        h = rng.choice([19, 20, 21, 22, 23])
        return f.replace("{H}", str(h)), {"hour": h}
    return f, {}


# --------------------------------------------------------------------------- Zoe › WhatsApp (2026-11-16)
MSG_CONTACTS = ["Annem", "Babam", "Ahmet", "Ayşe", "Mehmet", "Elif", "Kardeşim", "Can", "Zeynep", "Murat", "Selin", "Emre"]
MSG_SAY = ["yarın geliyorum", "tamam uygunum", "15:00 olur", "akşam ararım", "biraz geç kalacağım", "teşekkür ederim",
           "evet geliyorum", "şu an toplantıdayım", "hafta sonu buluşalım", "yoldayım"]
INBOX_FRAMES = ["whatsapp'ta kim yazdı", "mesajlarımı özetle", "whatsapp mesajlarıma bak", "yeni mesaj var mı", "cevap bekleyen mesaj var mı",
                "Zoe, mesajları özetle", "wp'de neler var", "okunmamış mesajlarım neler", "bugün kimler mesaj attı"]
REPLY_FRAMES = ["{C}'e cevap yaz: {S}", "{C}'e cevap ver: {S}", "Zoe, {C}'e cevap yaz: {S}", "{C}'e whatsapp'tan cevap yaz: {S}",
                "{C}'e yanıt yaz: {S}", "{C}'e cevap gönder: {S}"]
REPLY_BARE = ["{C}'e cevap yaz", "{C}'e cevap hazırla", "Zoe, {C}'e cevap ver", "{C}'e yanıt yaz"]
CONTACT_AUTO = ["Zoe, {C}'e otomatik cevap ver", "{C}'e kendin cevap ver", "{C}'e otomatik yanıt ver", "{C}'e bundan sonra kendin cevap ver"]
CONTACT_ADD = ["Zoe, {C}'i izle", "{C}'in mesajlarını izle", "whatsapp'ta {C}'i takip et", "{C}'in whatsapp mesajlarını takibe al"]
CONTACT_REMOVE = ["{C}'i izlemeyi bırak", "Zoe, {C}'i takip etmeyi bırak"]
CONTACT_LIST = ["Zoe, izlediğin kişileri göster", "whatsapp'ta kimleri izliyorsun", "Zoe kimleri izliyorsun"]


def _dat(c):
    """Kişi adına yönelme eki (kesme işaretli) yerine çerçevede sabit 'e kullanılır; ünlü uyumu kabaca."""
    v = [ch for ch in c.lower() if ch in "aeıioöuü"]
    back = bool(v) and v[-1] in "aıou"
    y = "y" if c[-1].lower() in "aeıioöuü" else ""
    return "'" + y + ("a" if back else "e")


def g_msg_inbox(rng, sp, hf, hv):
    f = G.choose(rng, INBOX_FRAMES, sp, hf or hv)
    args = {}
    if "bekleyen" in f:
        args["waiting"] = True
    return f, args


def g_msg_reply(rng, sp, hf, hv):
    c = pick(rng, MSG_CONTACTS, sp)
    if rng.random() < 0.7:
        s = pick(rng, MSG_SAY, sp, lambda r: random_phrase(r, 2, 6), 0.4)
        f = G.choose(rng, REPLY_FRAMES, sp, hf or hv)
        return f.replace("{C}'e", c + _dat(c)).replace("{S}", s), {"contact": c, "say": s}
    f = G.choose(rng, REPLY_BARE, sp, hf or hv)
    return f.replace("{C}'e", c + _dat(c)), {"contact": c}


def g_msg_contacts(rng, sp, hf, hv):
    c = pick(rng, MSG_CONTACTS, sp)
    r = rng.random()
    last = [ch for ch in c.lower() if ch in "aeıioöuü"][-1]
    y = "y" if c[-1].lower() in "aeıioöuü" else ""
    acc = "'" + y + {"a": "ı", "ı": "ı", "e": "i", "i": "i", "o": "u", "u": "u", "ö": "ü", "ü": "ü"}[last]
    gen = "'" + ("n" if y else "") + {"a": "ı", "ı": "ı", "e": "i", "i": "i", "o": "u", "u": "u", "ö": "ü", "ü": "ü"}[last] + "n"
    if r < 0.35:
        f = G.choose(rng, CONTACT_AUTO, sp, hf or hv)
        return f.replace("{C}'e", c + _dat(c)).replace("{C}", c), {"action": "auto", "contact": c}
    if r < 0.7:
        f = G.choose(rng, CONTACT_ADD, sp, hf or hv)
        return f.replace("{C}'in", c + gen).replace("{C}'i", c + acc), {"action": "add", "contact": c}
    if r < 0.85:
        f = G.choose(rng, CONTACT_REMOVE, sp, hf or hv)
        return f.replace("{C}'i", c + acc), {"action": "remove", "contact": c}
    return G.choose(rng, CONTACT_LIST, sp, hf or hv), {"action": "list"}


GRAMMAR = {
    "reminder.set": g_reminder, "reminder.list": g_reminder_list, "note.write": g_note, "note.search": g_note_search,
    "research.start": g_research, "repo.audit": g_repo, "calendar.add": g_calendar_add, "calendar.list": g_calendar_list,
    "file.summarize": g_file, "image.analyze": g_image_analyze, "image.generate": g_image_generate, "card.propose": g_card,
    "timer.start": g_timer, "provider.discover": g_discover, "health.check": g_health, "memory.save": g_memory,
    "ask": g_ask, "calc.eval": g_calc, "text.translate": g_translate, "help": g_help, "market.crypto": g_crypto,
    "skill.run": g_skill_run, "skill.list": g_skill_list, "skill.learn": g_skill_learn, "skill.record": g_skill_record,
    "agent.hire": g_agent_hire, "mail.check": g_mail_check, "mail.send": g_mail_send, "self.status": g_self_status, "app.open": g_app_open, "app.list": g_app_list,
    "memory.recall": g_memory_recall, "self.advise": g_self_advise,
    "code.run": g_code_run, "code.repo": g_code_repo, "work.check": g_work_check, "market.alert": g_alert,
    "seo.audit": g_seo, "web.search": g_web_search, "web.read": g_web_read, "ad.check": g_ad_check, "ad.budget": g_ad_budget,
    "design.colors": g_colors, "research.watch": g_research_watch, "repo.watch": g_repo_watch, "work.digest": g_work_digest,
    "msg.inbox": g_msg_inbox, "msg.reply": g_msg_reply, "msg.contacts": g_msg_contacts,
}
GRAMMAR_FRAC = 0.75


AGENT_NAMES = ["Mike", "Sophia", "Emma", "Zoe", "Luna", "David", "Jack", "Chloe", "Grace", "Maya", "EkBot", "Leo", "Nora", "Iris", "Orion"]


# --------------------------------------------------------------------------- karşıt çiftler (Tur 14)
# Aynı anahtar sözcük, farklı komut. Yalnızca EĞİTİMDE üretilir; değerler eğitim havuzlarından, kalıplar
# dilbilgisi motorunun eğitim parçalarıdır (ayrılmış i % 4 == 3 parçaları ve legacy_ood'un birebir kalıpları
# kullanılmaz; bkz. test_datagen.test_contrast_frames_not_held_out).
# Tur 18 denetimi: ayrılmış kalıpların yakın kopyası olan "yakın-ıska" grupları kaldırıldı (OOD ölçümünü şişiriyordu);
# grup sayısı yine 7, oran 0.08 (bkz. test_datagen_tur18.test_new_contrast_templates_far_from_held_out).
CONTRAST_FRAC = 0.08


def _c_text(rng, values, lo, hi):
    return pick(rng, values, "train", lambda r: random_phrase(r, lo, hi))


def _c_mem(rng):
    return _c_text(rng, MEMORY_TEXTS, 2, 7)


def _c_note(rng):
    return _c_text(rng, NOTE_TEXTS, 2, 9)


def _c_rem(rng):
    return _c_text(rng, REMINDER_TEXTS, 1, 4)


def _c_ev(rng):
    return _c_text(rng, EVENT_TITLES, 1, 3)


def _c_topic(rng):
    return _c_text(rng, TOPICS, 1, 5)


def _c_prompt(rng):
    return _c_text(rng, IMAGE_PROMPTS, 2, 6)


def _c_q(rng):
    return _c_text(rng, QUESTIONS, 2, 6)


def _c_min(rng):
    return rng.choice([1, 2, 3, 4, 5, 7, 8, 10, 12, 15, 20, 25, 30, 40, 45, 60, 90])


def _c_day(rng):
    return rng.choice([("bugün", "d+0"), ("yarın", "d+1"), ("öbür gün", "d+2")])


def _contrast_groups() -> dict[str, list]:
    """Grup adı → [(komut, üretici)]. Her grupta aynı anahtar sözcüğün en az iki farklı komutu var."""
    def t(rng):
        return random_time(rng, split="train")

    def tc(rng):
        return random_time(rng, allow_offset=False, split="train")

    return {
        "kaydet": [
            ("memory.save", lambda rng: (lambda x: (f"tercihimi kaydet: {x}", {"kind": "preference", "text": x}))(_c_mem(rng))),
            ("memory.save", lambda rng: (lambda x: (f"hafızana kaydet: {x}", {"kind": "note", "text": x}))(_c_mem(rng))),
            ("memory.save", lambda rng: (lambda x: (f"bunu tercih olarak kaydet: {x}", {"kind": "preference", "text": x}))(_c_mem(rng))),
            ("note.write", lambda rng: (lambda x: (f"kaydet: {x}", {"text": x}))(_c_note(rng))),
            ("note.write", lambda rng: (lambda x: (f"kayda geç: {x}", {"text": x}))(_c_note(rng))),
            ("note.write", lambda rng: (lambda x: (f"{x}, kayda geç", {"text": x}))(_c_note(rng))),
            ("note.write", lambda rng: (lambda x: (f"not olarak kaydet: {x}", {"text": x}))(_c_note(rng))),
            ("note.write", lambda rng: (lambda x: (f"not al: {x}", {"text": x}))(_c_note(rng))),
        ],
        "sayaç/hatırlat": [
            ("timer.start", lambda rng: (lambda m: (f"{m} dakika sonra haber ver diye {rng.choice(['geri sayım başlat', 'zamanlayıcı kur', 'sayaç kur'])}",
                                                    {"minutes": m}))(_c_min(rng))),
            ("timer.start", lambda rng: (lambda m, lb: (f"{lb} için {m} dakika {rng.choice(['zamanlayıcı kur', 'sayaç kur', 'geri sayım başlat'])}",
                                                        {"minutes": m, "label": lb}))(_c_min(rng), _c_text(rng, TIMER_LABELS + ["toplantı hazırlığı"], 1, 2))),
            ("reminder.set", lambda rng: (lambda m, x: (f"{m} dakika sonra {x} diye haber ver", {"at": f"+{m}m", "text": x}))(_c_min(rng), _c_rem(rng))),
            ("reminder.set", lambda rng: (lambda tt, x: (f"{x} için {tt.tr} hatırlatıcı kur", {"at": tt.when, "text": x}))(t(rng), _c_rem(rng))),
        ],
        "takvim": [
            ("calendar.list", lambda rng: (lambda d: (f"{d[0]} boş muyum, takvimime bak", {"day": d[1]}))(_c_day(rng))),
            ("calendar.list", lambda rng: (lambda d: (f"{d[0]} meşgul müyüm", {"day": d[1]}))(_c_day(rng))),
            ("calendar.list", lambda rng: (lambda d: (f"{d[0]} boş muyum", {"day": d[1]}))(_c_day(rng))),
            ("calendar.add", lambda rng: (lambda tt, x: (f"{tt.tr} {x} takvime ekle", {"title": x, "start": tt.when}))(tc(rng), _c_ev(rng))),
            ("calendar.add", lambda rng: (lambda tt, x: (f"ajandaya ekle, {tt.tr} {x}", {"title": x, "start": tt.when}))(tc(rng), _c_ev(rng))),
            ("calendar.add", lambda rng: (lambda tt, x: (f"takvime ekle: {tt.tr} {x}", {"title": x, "start": tt.when}))(tc(rng), _c_ev(rng))),
        ],
        "anımsat/ajanda": [
            ("reminder.set", lambda rng: (lambda tt, x: (f"anımsat: {x}, {tt.tr}", {"at": tt.when, "text": x}))(t(rng), _c_rem(rng))),
            ("reminder.set", lambda rng: (lambda tt, x: (f"bildir, {tt.tr} {x}", {"at": tt.when, "text": x}))(t(rng), _c_rem(rng))),
            ("reminder.set", lambda rng: (lambda tt, x: (f"hatırlat, {tt.tr} {x}", {"at": tt.when, "text": x}))(t(rng), _c_rem(rng))),
            ("calendar.add", lambda rng: (lambda tt, x: (f"ajandaya ekle: {x}, {tt.tr}", {"title": x, "start": tt.when}))(tc(rng), _c_ev(rng))),
            ("calendar.add", lambda rng: (lambda tt, x: (f"takvime ekle, {tt.tr} {x}", {"title": x, "start": tt.when}))(tc(rng), _c_ev(rng))),
        ],
        "hakkında": [
            ("research.start", lambda rng: (lambda x: (f"{x} hakkında neler bulabilirsin", {"topic": x}))(_c_topic(rng))),
            ("research.start", lambda rng: (lambda x: (f"{x} hakkında ne bulabileceğine bak", {"topic": x}))(_c_topic(rng))),
            ("memory.recall", lambda rng: ("hakkımda ne biliyorsun", {})),
            ("memory.recall", lambda rng: ("hakkımda neler biliyorsun", {})),
            ("memory.recall", lambda rng: (lambda q: (f"{q} hakkında ne biliyorsun", {"query": q}))(rng.choice(_split(RECALL_TOPICS, "train")))),
        ],
        "neler yapabilir": [
            ("help", lambda rng: ("seninle neler yapabilirim", {})),
            ("help", lambda rng: ("seninle ne yapabilirim", {})),
            ("help", lambda rng: ("neler yapabilirsin", {})),
            ("memory.recall", lambda rng: ("benim hakkımda neler biliyorsun", {})),
            ("memory.recall", lambda rng: ("beni ne kadar tanıyorsun", {})),
        ],
        "görsel": [
            ("image.generate", lambda rng: (lambda x: (f"çiz: {x}", {"prompt": x}))(_c_prompt(rng))),
            ("image.generate", lambda rng: (lambda x: (f"{x} temalı bir görsel hazırla", {"prompt": x}))(_c_prompt(rng))),
            ("image.generate", lambda rng: (lambda x: (f"{x} temalı bir resim çiz", {"prompt": x}))(_c_prompt(rng))),
            ("note.write", lambda rng: (lambda x: (f"not al: {x}", {"text": x}))(_c_prompt(rng))),
            ("image.analyze", lambda rng: (lambda q: (f"görsele bak: {q}", {"uri": ATTACHED, "question": q}))(_c_q(rng))),
            ("image.analyze", lambda rng: ("resimdeki yazıyı oku", {"uri": ATTACHED})),
            ("image.analyze", lambda rng: ("görseldeki yazıyı oku", {"uri": ATTACHED})),
            ("ask", lambda rng: (lambda q: (f"soru: {q}", {"question": q}))(_c_q(rng))),
            ("ask", lambda rng: (lambda q: (f"{q}?", {"question": q}))(_c_q(rng))),
        ],
    }


CONTRAST_GROUPS = _contrast_groups()


def contrast_example(rng: random.Random) -> tuple[str, str, dict]:
    """(komut, cümle, argümanlar): önce grup, sonra gruptaki bir üye (karşıt komutlar eşit sıklıkta görülsün)."""
    group = CONTRAST_GROUPS[rng.choice(sorted(CONTRAST_GROUPS))]
    cmd, gen = rng.choice(group)
    tr, args = gen(rng)
    return cmd, tr, args


# --------------------------------------------------------------------------- kimlik soruları (yalnızca eğitim)
# "Sen kimsin / neden özelsin / kime aitsin / seni kim yaptı / mutlu musun": Kotlin kural çevirici bunları serbest soruya
# (ask {question}) çevirir; yürütücü kimlik dosyasından (shared/self/orion.json, IdentityTopic) cevaplar. "Beni tanıyor
# musun" ise Orion'un kimliği değil, sahibini tanımasıdır → memory.recall. Yalnızca EĞİTİM akışına girer (test kümeleri
# ve translator-eval.jsonl değişmez: test_datagen_tur18.SPLIT_SHA).
IDENTITY_FRAC = 0.01
IDENTITY_ASK = [
    "sen kimsin", "kimsin sen", "sen nesin", "kendini tanıt", "kendini tanıtır mısın", "adın ne", "senin adın ne",
    "neden özelsin", "sen neden bu kadar özelsin", "seni özel kılan ne", "senin farkın ne",
    "kime aitsin", "sen kime aitsin", "sahibin kim", "kimin asistanısın",
    "seni kim yaptı", "seni kim yarattı", "seni kim oluşturdu", "yaratıcın kim",
    "mutlu musun", "sen mutlu musun", "seni ne mutlu eder", "seni ne sevindirir",
    "hikayeni anlat", "senin hikayen ne",
]
# "Orion nerede" öğretmen tarafından nota çevrilmişti (2026-11-09): yer/durum soruları da sorudur (ask, kimlik değil).
STATUS_ASK = ["orion nerede", "neredesin", "sen neredesin", "orion ne yapıyor", "ne yapıyorsun", "şu an ne yapıyorsun",
              "orion ne durumda", "orion şu an nerede", "emma nerede", "mike ne yapıyor"]
IDENTITY_RECALL = ["beni tanıyor musun", "beni ne kadar tanıyorsun", "beni hatırlıyor musun"]


def identity_example(rng: random.Random) -> tuple[str, str, dict]:
    """(komut, cümle, argümanlar): kimlik sorusu → ask {question}; sahibini tanıma → memory.recall."""
    if rng.random() < 0.15:
        return "memory.recall", rng.choice(IDENTITY_RECALL), {}
    q = rng.choice(IDENTITY_ASK) if rng.random() >= 0.2 else rng.choice(STATUS_ASK)
    return "ask", q + rng.choice(["", "?"]), {"question": q}


# --------------------------------------------------------------------------- Tur 19: yeni beceri aileleri (yalnızca eğitim)
# Komut beyninin ek adımları (6000 → 10000) aynı veriyi tekrarlamak yerine YENİ becerilere harcansın diye.
# Dört aile; hepsi yalnızca EĞİTİM akışına girer (r_train çekilişi yalnızca split="train"), test/kalibrasyon kümeleri
# ve Kotlin translator-eval.jsonl değişmez (test_datagen_tur18.SPLIT_SHA). Kurallar (tests/test_datagen_tur19.py):
#   - değer havuzları değerlendirme kümelerinin değerlerinden ve _split'in ayrılmış (test) dilimlerinden ayrıktır,
#   - fiil/çerçeveler yalnızca eğitim parçalarından (split_pool "train") ya da ayrılmış yapılara Jaccard < 0.6 yeni çerçeveler,
#   - hiçbir cümle elle yazılmış/kör kümelerin bir cümlesiyle aynı ya da sözcük-Jaccard ≥ 0.8 değildir (_fenced).
# Bilerek EKLENMEYENLER (protokol/çevirici karşılığı yok, anlam uydurulmaz): saniyeli süreler ("kırk beş saniye":
# timer.start minutes tam sayı ≥ 1), saatsiz gün bölümü ("iki gün sonra sabah", "akşamüstü": Kotlin TimeParser bunu
# ya +2d'ye çevirir ya hiç çözmez), "notlarımda X geçenleri göster" (ayrılmış NS_FRAMES[3] kalıbının birebir yapısı).
SKILL_FRAC = 0.11  # t2c eğitim çekilişlerinin %11'i ≈ tüm akışın %8,1'i (tohum %3, dış veri %5 ile)
SKILL_MIX = (("sayı", 0.30), ("göreli", 0.25), ("uzun_ad", 0.25), ("not_arama", 0.20))


def num_words(n: int) -> str:
    """1-99 arası sayının okunuşu: 15 → on beş, 45 → kırk beş, 70 → yetmiş."""
    assert 1 <= n <= 99
    return " ".join(w for w in (_TENS_W[n // 10], _UNIT_W[n % 10]) if w)


def _dur(nom: str, minutes: int, at: str | None = None) -> tuple[str, int, str]:
    """(okunuş, dakika, ofset). Ofset: tam saatler +Nh, diğerleri +Nm (protokol 'when': N tam sayı)."""
    return nom, minutes, at or f"+{minutes}m"


# Yazıyla süreler (rakamla "15 dakika" zaten dilbilgisi motorunda var)
SKILL_MINUTES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 18, 20, 25, 30, 35, 40, 45, 50, 55, 70, 75, 80, 90]
SKILL_DURATIONS = (
    [_dur(f"{num_words(n)} dakika", n) for n in SKILL_MINUTES]
    + [_dur(f"{HOUR_WORDS[h]} saat", 60 * h, f"+{h}h") for h in (1, 2, 3, 4, 5, 6)]
    + [_dur("yarım saat", 30), _dur("çeyrek saat", 15), _dur("bir buçuk saat", 90), _dur("iki buçuk saat", 150),
       _dur("üç buçuk saat", 210), _dur("bir saat on beş dakika", 75), _dur("bir saat yirmi dakika", 80),
       _dur("bir saat kırk beş dakika", 105), _dur("iki saat otuz dakika", 150), _dur("1,5 saat", 90),
       _dur("2 buçuk saat", 150), _dur("1 buçuk saat", 90)]
)


def dur_adj(nom: str) -> str:
    """Sıfat hâli: on beş dakikalık, yarım saatlik, bir buçuk saatlik."""
    return nom + ("lık" if nom.endswith("dakika") else "lik")


def dur_dat(nom: str) -> str:
    """Yönelme hâli: on beş dakikaya, yarım saate."""
    return nom + ("ya" if nom.endswith("dakika") else "e")


# Zamanlayıcı etiketleri: el yazımı/kör kümelerin etiketleri ("çalışma", "haşlanmış yumurta") ve ayrılmış dilim yok.
SKILL_TIMER_LABELS = [x for x in _split(TIMER_LABELS, "train") if x != "çalışma"] + [
    "pilav", "kek", "demlik", "fırındaki börek", "ders molası", "şınav seti", "yüz maskesi", "pomodoro",
    "kısa mola", "ekmek hamuru", "tavuk haşlama", "çamaşır suyu bekletme", "saç boyası", "kuru fasulye",
]
# Zamanlayıcı söyleyişleri (yeni; ayrılmış TIMER_FRAMES "{V}: {M} dakika", "{M} dk {V}" ve fiiller "say",
# "geri sayım yap" kullanılmaz; yalın "{A} {V}" ve "zamanlayıcıyı {D} kur", ayrılmış "{V}: {M} dakika" yapısına
# Jaccard ≥ 0.6 benzediği için yok). A = sıfat ("on beş dakikalık"), N = yalın, D = yönelme ("yarım saate").
SKILL_TIMER_FRAMES = [
    "şimdi {A} bir {V}", "{L} için {A} {V}", "{A} {L} sayacı kur", "bana {A} bir zamanlayıcı kurar mısın",
    "{A} bir geri sayım istiyorum", "zamanlayıcıyı {D} ayarlar mısın", "sayacı {D} ayarla", "{N} sonra çalacak bir zamanlayıcı kur",
    "{L} {N} sürecek, {V}", "{N} boyunca süre tut", "{L} için sayacı {D} kurar mısın",
]


def _skill_numbers(rng: random.Random) -> tuple[str, str, dict]:
    """Yazıyla sayı ve süreler → timer.start {minutes} ya da reminder.set {at:+Nm|+Nh}."""
    nom, minutes, at = rng.choice(SKILL_DURATIONS)
    if rng.random() < 0.6:
        f = rng.choice(SKILL_TIMER_FRAMES)
        args: dict = {"minutes": minutes}
        lb = ""
        if "{L}" in f:
            lb = rng.choice(SKILL_TIMER_LABELS)
            args["label"] = lb
        v = _verb(rng, "train", TIMER_VERBS, False)
        return "timer.start", _fill(f, A=dur_adj(nom), N=nom, D=dur_dat(nom), L=lb, V=v), args
    x = pick(rng, REMINDER_TEXTS, "train", lambda r: random_phrase(r, 1, 4))
    v = _verb(rng, "train", REM_VERBS, False)
    return "reminder.set", _fill(_frame(rng, "train", REM_FRAMES, False), T=f"{nom} sonra", X=x, V=v), {"at": at, "text": x}


def _daypart_clock(rng: random.Random, h: int, m: int) -> str:
    """Gün bölümlü saat (sabah dokuzda, öğleden sonra 4'te, akşam sekiz buçukta); yorum _part ile aynı."""
    pre, n = _part(rng, h)
    if pre == "öğlen":
        return rng.choice(["öğlen", "öğlen 12'de"]) if m == 0 else "öğlen 12 buçukta"
    if m == 30:
        return f"{pre} {rng.choice([HOUR_WORDS[n], str(n)])} buçukta"
    return f"{pre} {word_loc(n)}" if rng.random() < 0.5 else f"{pre} {n}'{loc_suffix(n)}"


def _rel_time(rng: random.Random, allow_offset: bool) -> TimeExpr:
    """Göreli zamanlar: yazıyla 'üç saat sonra' (+3h), 'iki gün sonra' (+2d), 'iki gün sonra sabah dokuzda' (d+2@09:00),
    'bu akşam sekizde' (d+0@20:00), 'öğleden sonra 4'te' (d+0@16:00). Hepsi random_time/Kotlin TimeParser yorumuyla aynı."""
    r = rng.random() if allow_offset else 0.4 + 0.6 * rng.random()
    if r < 0.2:
        n = rng.randint(1, 12)
        w = HOUR_WORDS[n] if rng.random() < 0.7 else str(n)
        return TimeExpr(f"{w} saat sonra", f"+{n}h")
    if r < 0.32:
        n = rng.choice([15, 16, 18, 20, 24, 36, 48, 72])
        return TimeExpr(f"{n} saat sonra", f"+{n}h")
    if r < 0.4:
        n = rng.randint(2, 10)
        return TimeExpr(f"{HOUR_WORDS[n] if n <= 12 else n} gün sonra", f"+{n}d")
    h = rng.choice([7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22])
    m = rng.choice([0, 0, 0, 30])
    clock = _daypart_clock(rng, h, m)
    hm = f"{h:02d}:{m:02d}"
    if r < 0.62:
        n = rng.randint(2, 9)
        return TimeExpr(f"{HOUR_WORDS[n] if rng.random() < 0.6 else n} gün sonra {clock}", f"d+{n}@{hm}")
    if r < 0.74 and h >= 18:
        return TimeExpr(f"bu {clock}", f"d+0@{hm}")  # "bu akşam sekizde", "bu gece on birde"
    if r < 0.86 and 13 <= h <= 17:
        day, code = rng.choice([("", "d+0@"), ("bugün ", "d+0@"), ("yarın ", "d+1@")] + [(f"{d} ", f"{c}@") for d, c in DOW_TR])
        return TimeExpr(f"{day}{clock}".strip(), f"{code}{hm}")
    day, code = rng.choice([("yarın", "d+1"), ("öbür gün", "d+2"), ("bugün", "d+0")])
    return TimeExpr(f"{day} {clock}", f"{code}@{hm}")


def _skill_relative(rng: random.Random) -> tuple[str, str, dict]:
    if rng.random() < 0.7:
        t = _rel_time(rng, True)
        x = pick(rng, REMINDER_TEXTS, "train", lambda r: random_phrase(r, 1, 4))
        v = _verb(rng, "train", REM_VERBS, False)
        return "reminder.set", _fill(_frame(rng, "train", REM_FRAMES, False), T=t.tr, X=x, V=v), {"at": t.when, "text": x}
    t = _rel_time(rng, False)
    x = pick(rng, EVENT_TITLES, "train", lambda r: random_phrase(r, 1, 3))
    v = _verb(rng, "train", CAL_VERBS, False)
    return "calendar.add", _fill(_frame(rng, "train", CAL_FRAMES, False), T=t.tr, X=x, V=v), {"title": x, "start": t.when}


# Çok sözcüklü, iyelikli adlar: argüman tümüyle korunmalı ("annemin doğum günü", "kombi servisi randevusu").
# Değerlendirme kümelerindeki değerler (ör. el yazımı "diş randevusu", "akşam yemeği") bilerek yok.
MULTI_REM_TEXTS = [
    "annemin doğum günü", "kombi servisi randevusu", "babamın emeklilik yemeği", "arabanın kasko yenilemesi",
    "kızımın okul gezisi", "apartman yönetim toplantısı", "diş hekimi kontrolü", "kedinin kuduz aşısı",
    "doğalgaz faturasının son günü", "teyzemin hastane randevusu", "kira sözleşmesinin yenilenmesi",
    "oğlumun yüzme kursu kaydı", "eşimin terfi kutlaması", "anneannemin ilaç saati", "çocukların karne günü",
    "ehliyet yenileme randevusu", "kuru temizlemeden ceketi almak", "bulaşık makinesi tamircisi",
    "su sayacının okunması", "komşunun taşınma yardımı", "dedemin bayram ziyareti", "ofisin yangın tatbikatı",
    "kardeşimin mezuniyet töreni", "bebeğin altı aylık aşısı", "kombinin yıllık bakımını yaptırmak",
    "annemin tansiyon ilacını almak", "evin sigorta poliçesini yenilemek", "babamın göz muayenesi",
]
MULTI_EVENT_TITLES = [
    "kardeşimin nişan töreni", "şirketin yıl sonu yemeği", "kombi servisi randevusu", "ekip haftalık değerlendirme toplantısı",
    "çocukların yüzme dersi", "annemin doğum günü yemeği", "apartman yönetim toplantısı", "kedinin aşı kontrolü",
    "ev sahibiyle kira görüşmesi", "üniversite arkadaşlarıyla buluşma", "bankada kredi görüşmesi", "proje lansman sunumu",
    "okulun bahar şenliği", "dedemin doksanıncı yaş günü", "yeni ofisin açılış kokteyli", "müşteriyle sözleşme imzası",
    "fizik tedavi seansı", "diş hekimi kontrolü", "kızımın piyano resitali", "babamın göz muayenesi",
]
MULTI_NOTE_TEXTS = [
    "annemin doğum günü için kaşmir şal alınacak", "kombi servisi salı günü geliyor",
    "arabanın kasko poliçesi mart sonunda bitiyor", "çocukların okul servis ücreti arttı",
    "kiracının depozitosu iade edilecek", "babamın tansiyon ilacı değişti", "balkon kapısının menteşesi gıcırdıyor",
    "düğün hediyesi için ortak hesap açıldı", "apartman aidatı 1500 liraya çıktı", "yeni telefonun garanti belgesi çekmecede",
    "bahar temizliği için perdeler yıkanacak", "kedinin mamasını değiştirmeyi dene", "teyzemlere bayramda tatlı götür",
    "kurs kayıt ücreti iki taksit", "dedemin doksanıncı yaş günü için albüm hazırla", "ofisin yangın tatbikatı cuma günü",
]


def _skill_multiword(rng: random.Random) -> tuple[str, str, dict]:
    r = rng.random()
    if r < 0.45:
        t = random_time(rng, split="train")
        x = rng.choice(MULTI_REM_TEXTS)
        acc = G.inf_accusative(x)
        if acc and rng.random() < 0.6:
            v = G.choose(rng, REM_ACC_VERBS, "train", False)
            return "reminder.set", _fill(_frame(rng, "train", REM_ACC_FRAMES, False), T=t.tr, XA=acc, V=v), {"at": t.when, "text": x}
        v = _verb(rng, "train", REM_VERBS, False)
        return "reminder.set", _fill(_frame(rng, "train", REM_FRAMES, False), T=t.tr, X=x, V=v), {"at": t.when, "text": x}
    if r < 0.8:
        t = random_time(rng, allow_offset=False, split="train")
        x = rng.choice(MULTI_EVENT_TITLES)
        v = _verb(rng, "train", CAL_VERBS, False)
        return "calendar.add", _fill(_frame(rng, "train", CAL_FRAMES, False), T=t.tr, X=x, V=v), {"title": x, "start": t.when}
    x = rng.choice(MULTI_NOTE_TEXTS)
    v = _verb(rng, "train", NOTE_VERBS, False)
    return "note.write", _fill(_frame(rng, "train", NOTE_FRAMES, False), X=x, V=v), {"text": x}


# Not arama: doğal söyleyişler. Sorgu havuzu değerlendirme sorgularından ("kira", "veteriner", "kapıcı", "doğum günü",
# "sigorta", "anahtar") ve QUERIES'in ayrılmış diliminden ayrık. QI = birleşik "ile" ("aidatla", "vize başvurusuyla").
# Yalın "{Q} hakkındaki notlar", "{Q} ile ilgili notlarımı getirir misin" ayrılmış yapılara Jaccard ≥ 0.6 (eğitim
# çerçevesi + ayrılmış fiil "listele") benzediği için uzatılmış hâlleriyle var.
SKILL_QUERIES = [
    "aidat", "tapu", "pasaport", "vize başvurusu", "düğün", "taşınma", "boya badana", "kreş", "emeklilik",
    "garanti belgesi", "tatil rotası", "bahçe", "ders programı", "kitap listesi", "kamp malzemeleri", "araba bakımı",
    "mülakat", "kombi bakımı", "elektrik tesisatı", "yatırım fonu", "doktor raporu", "okul servisi",
]
SKILL_NS_FRAMES = [
    "{Q} ile ilgili notlarımı bulur musun", "{QI} ilgili yazdığım her şeyi göster", "{Q} hakkındaki notlarıma ihtiyacım var",
    "{Q} hakkındaki notlar, hepsini görmek istiyorum", "{Q} hakkında yazdığım notlar nerede", "{Q} hakkında tuttuğum notları aç",
    "{Q} konusunda yazdığım notları bul", "{Q} ile alakalı notlar var mıydı", "not defterimde {Q} ile ilgili ne var",
    "{Q} için aldığım notları göster", "{QI} ilgili kaydettiğim notlar hangileri", "{Q} geçen bir not yazmıştım, onu bul",
    "{QI} alakalı ne yazdıysam getir",
]


def with_ile(q: str) -> str:
    """Birleşik 'ile': aidat → aidatla, vize başvurusu → vize başvurusuyla, düğün → düğünle."""
    return q + ("y" if q[-1] in G.VOWELS else "") + "l" + G.h2(q)


def _skill_note_search(rng: random.Random) -> tuple[str, str, dict]:
    frames = SKILL_NS_FRAMES
    if rng.random() < 0.35:
        q = rng.choice(SKILL_QUERIES)
    else:
        q = pick(rng, QUERIES, "train", lambda r: random_phrase(r, 1, 2))
        if q not in QUERIES:  # rastgele ifade (ekli olabilir): birleşik "ile" yapılmaz
            frames = [f for f in frames if "{QI}" not in f]
    f = rng.choice(frames)
    return "note.search", _fill(f, Q=q, QI=with_ile(q)), {"query": q}


SKILL_FAMILIES = {"sayı": _skill_numbers, "göreli": _skill_relative, "uzun_ad": _skill_multiword,
                  "not_arama": _skill_note_search}

_FENCE: dict = {}


def _fence_norm(s: str) -> str:
    """test_handwritten._norm ile aynı: nezaket ön/son ekleri ve noktalama atılır."""
    s = s.lower().strip().rstrip(".?!").strip()
    for p in ("hey orion ", "orion, ", "orion ", "lütfen ", "acaba "):
        if s.startswith(p):
            s = s[len(p):]
    for p in (" lütfen", " teşekkürler", " rica etsem"):
        if s.endswith(p):
            s = s[: -len(p)]
    return s.strip()


def _fence_toks(s: str) -> frozenset:
    import re
    return frozenset(re.sub(r"[.,:;?!\"]", " ", _fence_norm(s)).split())


def _fence() -> dict:
    """Elle yazılmış + kör değerlendirme cümleleri (yalnızca DIŞLAMA için; eğitime hiçbir şey eklemez)."""
    if not _FENCE:
        from pathlib import Path
        base = Path(__file__).resolve().parents[2] / "shared" / "core-model"
        srcs = []
        for name in ("handwritten-eval.jsonl", "blind-eval.jsonl", "ajan-sinavi.jsonl", "ajan-sinavi-2.jsonl"):
            p = base / name
            if p.exists():
                srcs += [json.loads(x)["src"] for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
        _FENCE["norm"] = {_fence_norm(s) for s in srcs}
        _FENCE["toks"] = [_fence_toks(s) for s in srcs]
    return _FENCE


def _fenced(src: str) -> bool:
    """Değerlendirme cümlesiyle aynı ya da sözcük-Jaccard ≥ 0.8 → üretilmez (yeniden çekilir)."""
    f = _fence()
    if _fence_norm(src) in f["norm"]:
        return True
    t = _fence_toks(src)
    return any(len(t & u) / len(t | u) >= 0.8 for u in f["toks"])


def skill_example(rng: random.Random, family: str | None = None) -> tuple[str, str, dict]:
    """(komut, cümle, argümanlar): yeni beceri ailelerinden biri (SKILL_MIX oranlarıyla)."""
    names = [n for n, _ in SKILL_MIX]
    fam = family or rng.choices(names, weights=[w for _, w in SKILL_MIX])[0]
    for _ in range(20):
        cmd, tr, args = SKILL_FAMILIES[fam](rng)
        if not _fenced(tr):
            return cmd, tr, args
    raise ProtocolError("E_INTERNAL", "beceri ailesi değerlendirme cümlelerinden uzak cümle üretemedi")


# --------------------------------------------------------------------------- gerçek cümle açıkları (Tur 21, yalnızca eğitim)
# 2026-11-16 ölçümü (komut-20261116-1418, xSID/MASSIVE yanlış işleri): (1) saatsiz gün sözü ("Yarın X'i hatırlat",
# "Salı günü ...", "Gelecek pazartesi ...") bugüne çevriliyor ya da metne karışıyordu; (2) Orion'un yapamadığı istekler
# (resim arama, rezervasyon, çalma listesi, hava durumu) ve olumsuz/iptal cümleleri ("beni uyandırma", "alarmı iptal et")
# bir işe çevriliyordu. Doğrusu: saatsiz gün → 09:00 (Kotlin TimeParser varsayılanı), yapılamayan istek → ask.
# Değerler kendi listelerimizden; elle yazılmış/kör kümeler ve (hazırsa) MASSIVE/xSID değerlendirme cümleleri çitle dışlanır.
REALGAP_FRAC = 0.10  # Tur 26: 0.08 → 0.10 (tüm ajanlar)

GAP_INF = ["eczaneden ilaç almak", "kuzenimi aramak", "su faturasını yatırmak", "kargoyu teslim almak", "bisikleti tamir ettirmek",
           "anneannemi ziyaret etmek", "kütüphaneye kitap iade etmek", "arabayı yıkatmak", "ödevi teslim etmek",
           "bankaya uğramak", "pasaport başvurusu yapmak", "balkonu temizlemek", "çiçekçiden buket almak",
           "ekmek almak", "komşuya anahtar bırakmak", "spor çantasını hazırlamak", "veterinere aşı için gitmek",
           "teyzemi aramak", "fotoğrafları yedeklemek", "kombiyi kontrol ettirmek", "postaneye uğramak",
           "dişçiden randevu almak", "kira sözleşmesini imzalamak", "terziye pantolon bırakmak"]
GAP_DAYS = [("yarın", "d+1"), ("bugün", "d+0"), ("öbür gün", "d+2"), ("pazartesi", "mon"), ("salı günü", "tue"),
            ("çarşamba günü", "wed"), ("gelecek perşembe", "thu"), ("önümüzdeki cuma", "fri"), ("cumartesi günü", "sat"),
            ("gelecek pazar", "sun"), ("pazartesi günü", "mon"), ("önümüzdeki salı", "tue"), ("perşembe", "thu")]
GAP_REM_V = ["hatırlat", "bana hatırlat", "hatırlatır mısın", "unutmamam için hatırlat", "aklıma getir"]
GAP_CLOCK = [("sabah 8'de", "08:00"), ("sabah 9'da", "09:00"), ("öğleden sonra 3'te", "15:00"), ("öğleden sonra 5'te", "17:00"),
             ("akşam 7'de", "19:00"), ("sabah 6:45'te", "06:45"), ("sabah 8:15'te", "08:15"), ("öğlen 12'de", "12:00"),
             ("akşam 8:30'da", "20:30"), ("öğleden sonra 2'de", "14:00"), ("sabah 11'de", "11:00")]
GAP_NAMES = ["Kuzey Işıkları", "Mavi Kapı", "Son Tren", "Rüzgarın Sesi", "Eski Liman", "Gece Bekçisi", "Kırmızı Balon",
             "Taş Köprü", "Yaz Yağmuru", "Sessiz Orman", "Altın Kafes", "Uzak Ada"]
GAP_CITIES = ["Eskişehir", "Trabzon", "Çanakkale", "Van", "Sinop", "Bodrum", "Kars", "Edirne", "Rize", "Muğla", "Hatay", "Ordu"]
GAP_VENUES = ["Deniz Kızı Lokantası", "Köşe Kahve", "Bahçe Restoran", "Yıldız Pide", "Liman Balıkçısı", "Asmalı Ev"]
GAP_SONGS = ["Gesi Bağları", "Üsküdar'a Gider İken", "Yağmur", "Bir Teselli Ver", "Kara Toprak", "Sarı Gelin"]
GAP_LISTS = ["yolculuk", "spor", "sabah", "hafta sonu", "çalışma", "parti"]
GAP_ASK = [
    "{N} filminin resmini bul", "{N} adlı resmi internette ara", "{N} afişinin fotoğrafını göster", "bana {N} fotoğrafı bul",
    "{V} için {k} kişilik masa ayırt", "{C} şehrinde {k} kişilik restoran rezervasyonu yap", "{V} için akşama yer ayırt",
    "{S} şarkısını {L} çalma listesine ekle", "{L} listesine {S} parçasını koy", "çalma listemden {S} şarkısını çıkar",
    "{C} için yarın hava nasıl olacak", "{C} şehrinde yağmur yağacak mı", "bu akşam {C} şehrinde hava kaç derece",
    "yarın beni uyandırma", "sabahki alarmımı iptal et", "alarmımı {m} dakika ertele", "hatırlatıcılarımın hepsini sil",
    "hiç alarm istemiyorum", "{h} alarmını kapat", "dünkü hatırlatıcıyı iptal et", "bu gece alarm kurma",
    # Tur 23b (komut-20261119-1954 xSID yanlış işleri): alarmı değiştirme/temizleme/durdurma bir iş değil (Orion yapamaz)
    "yarınki alarmı {h} değiştir", "alarmımı {h} olarak güncelle", "{h} alarmını {m} dakika ileri al", "kurduğum alarmları temizle",
    "bütün alarmları sil", "ayarlı alarmların hepsini kaldır", "{h} alarmını durdur", "çalan alarmı sustur",
    "hafta içi alarmlarımı kapat", "hatırlatıcının saatini değiştir", "yarınki hatırlatıcıyı {h} olarak düzelt",
    "alarmı bir saat geç kur, eskisini sil", "{h} alarmını iptal edip yenisini kurma",
]


# Tur 22 (2026-11-17, sahibin telefon denemesi): "herhangi gelen bir mesaj var mı bana" sohbet sorusu sanılıp yardımcıya
# gidiyordu; ajana seslenip talimat vermek ("Zoe dediğimde sen cevap ver") bir iş değil, sohbettir (ask).
GAP_INBOX = ["herhangi gelen bir mesaj var mı bana", "bana mesaj geldi mi", "kimden mesaj var", "bana kim yazdı",
             "gelen mesajları göster", "bana yazan var mı", "mesaj atan oldu mu", "son gelen mesajlar ne",
             "whatsapp'tan bir şey geldi mi", "bugün bana kimler yazdı", "yazan biri oldu mu"]
# "gelen kutusu" e-postadır (mail.check); Tur 22'de msg.inbox'a yazılmıştı, elle yazılmış kümede e-posta sorusunu bozdu
GAP_INBOX_WAIT = ["cevap vermediğim mesaj var mı", "cevaplamadığım kimse kaldı mı", "beklettiğim mesaj var mı"]
GAP_AGENT_TALK = ["{A} burada mısın", "{A} beni duyuyor musun", "{A} dediğimde sen cevap ver", "{A}, sadece sen cevap ver",
                  "{A} sana soru soruyorum", "{A} neredesin", "{A} uyanık mısın", "{A}, bundan sonra sen cevapla"]


def _gap_agent(rng):
    r = rng.random()
    pre = rng.choice(["", "", "Zoe, ", "Zoe "])
    if r < 0.45:
        tr = pre + rng.choice(GAP_INBOX)
        return "msg.inbox", (tr[:1].upper() + tr[1:] if rng.random() < 0.3 else tr), {}
    if r < 0.6:
        return "msg.inbox", pre + rng.choice(GAP_INBOX_WAIT), {"waiting": True}
    tr = rng.choice(GAP_AGENT_TALK).replace("{A}", rng.choice(["Zoe", "Emma", "Sophia", "Mike", "Luna"]))
    return "ask", tr, {"question": tr}


# Tur 23 (2026-11-19, ekip sistemi 3-4 sonrası ölçüm): yeni yeteneklerin cümleleri işe gitmiyordu: gün planı soruları
# ("günümü özetle", "bugünkü planım ne") sohbet sanılıyordu (Emma › Gün planlayıcı: calendar.list); "X hakkında son
# haberler" / "kaynakları karşılaştır" araştırma değil soru sanılıyordu (Sophia kendi kaynaklarıyla: research.start);
# "kim yazdı bana" (söz sırası) gelen kutusu, "notlarımda X geçen var mı" not araması değildi.
TEAM_DAY = [("günümü özetle", "d+0"), ("bugünkü planım ne", "d+0"), ("bugün beni neler bekliyor", "d+0"),
            ("bugünün planını söyle", "d+0"), ("bugün programımda ne var", "d+0"), ("bugün planımda neler var", "d+0"),
            ("yarınki planım ne", "d+1"), ("yarın beni neler bekliyor", "d+1"), ("yarının planını özetle", "d+1"),
            ("bugün için planımı özetle", "d+0"), ("bugün yapacaklarım ne", "d+0"), ("yarın programım nasıl", "d+1")]
TEAM_NEWS = ["{X} hakkında son haberler", "{X} ile ilgili son haberleri araştır", "{X} konusunda yeni ne var, araştır",
             "{X} konusunu kaynaklardan karşılaştır", "{X} hakkında kaynakları karşılaştır", "{X} hakkında farklı kaynaklara bak",
             "{X} ile ilgili haberleri topla", "{X} konusundaki son gelişmeleri araştır", "{X} hakkında ne yazılmış, karşılaştır"]
TEAM_INBOX = ["kim yazdı bana", "mesaj geldi mi bana", "yazan oldu mu bana", "kimler yazmış bana", "mesaj var mı bana",
              "bir mesaj gelmiş mi"]
TEAM_NOTE = ["notlarımda {Q} geçen var mı", "{Q} ile ilgili notum var mı", "notlarımda {Q} var mıydı",
             "{Q} hakkında not almış mıydım", "notlarıma bak, {Q} geçiyor mu"]


def _gap_team(rng):
    r = rng.random()
    if r < 0.3:
        tr, d = rng.choice(TEAM_DAY)
        tr = rng.choice(["", "", "Emma, ", "Emma "]) + tr
        return "calendar.list", tr, {"day": d}
    if r < 0.6:
        x = rng.choice(TOPICS)
        tr = rng.choice(["", "", "Sophia, ", "Sophia "]) + _fill(rng.choice(TEAM_NEWS), X=x)
        return "research.start", tr, {"topic": x}
    if r < 0.75:
        return "msg.inbox", rng.choice(["", "", "Zoe, "]) + rng.choice(TEAM_INBOX), {}
    q = rng.choice(QUERIES)
    return "note.search", _fill(rng.choice(TEAM_NOTE), Q=q), {"query": q}


# Tur 24 (2026-11-20, ajan sınavı bulguları): sınavın kendi cümleleri DEĞİL, takılınan söyleyiş aileleri (sınav çitli):
# "X'e … diye yaz / … de" (Zoe cevabı), "X yazarsa sen cevapla" (otomatik), "… olduğunu unutma" (hafıza), "a çarpı b bölü c"
# (hesap), "kayıtlı becerilerim" (beceri listesi), "haftalık iş özeti" (iş özeti), "pilim / şarjım" (telefon sağlığı).
T24_SAY = ["birazdan çıkıyorum", "yarın uygunum", "akşama döneceğim", "toplantı uzadı", "geliyorum", "sonra konuşalım",
           "evdeyim", "trafikteyim", "yarın ararım", "tamam anlaştık"]
T24_REPLY = ["{C}'e {S} diye yaz", "{C}'e {S} de", "{C}'e yaz: {S}", "{C}'e söyle, {S}", "{C}'e {S} diye cevap ver",
             "{C}'e haber ver: {S}", "{C}'e {S} diye mesaj at"]
T24_AUTO = ["{C} yazarsa sen cevapla", "{C} yazınca cevabı sen ver", "{C}'e gelen mesajları sen yanıtla", "{C} mesaj atarsa kendin cevapla"]
T24_LIST = ["izlediğin kişiler kimler", "Zoe kişi listeni göster", "takip ettiğin kişileri listele", "hangi kişileri izliyorsun"]
T24_MEM = [("{X} olduğunu unutma", "preference"), ("{X} olduğunu aklında tut", "preference"), ("şunu hafızana yaz: {X}", "note"),
           ("benim hakkımda şunu bil: {X}", "preference")]
T24_MEMX = ["çayı şekersiz içerim", "sabahları koşarım", "fıstığa alerjim var", "akşamları erken yatarım", "deniz kenarını severim",
            "hafta sonları çalışmam"]
T24_CALC = [("{a} çarpı {b} bölü {c} hesapla", "*/"), ("{a} artı {b} eksi {c} kaç eder", "+-"), ("{a} çarpı {b} artı {c} ne yapar", "*+"),
            ("{a} bölü {b} çarpı {c} hesaplar mısın", "/*")]
T24_SKILL = ["kayıtlı becerileri listele", "öğrendiğin becerileri göster", "kayıtlı becerilerin neler", "beceri listemi aç"]
T24_DIGEST = ["haftalık iş özetini hazırla", "bu haftaki işleri özetle", "ekibin bu hafta ne yaptığını özetle"]
T24_HEALTH = ["şarjım neden çabuk bitiyor", "pil sağlığıma bak", "telefonum neden ısınıyor bir kontrol et", "pilim ne durumda"]


def _gap_tur24(rng):
    r = rng.random()
    c = rng.choice(MSG_CONTACTS)
    if r < 0.25:
        sy = rng.choice(T24_SAY)
        return "msg.reply", rng.choice(T24_REPLY).replace("{C}'e", c + _dat(c)).replace("{S}", sy), {"contact": c, "say": sy}
    if r < 0.37:
        return "msg.contacts", rng.choice(T24_AUTO).replace("{C}'e", c + _dat(c)).replace("{C}", c), {"action": "auto", "contact": c}
    if r < 0.42:
        return "msg.contacts", rng.choice(T24_LIST), {"action": "list"}
    if r < 0.55:
        f, kind = rng.choice(T24_MEM)
        x = rng.choice(T24_MEMX)
        return "memory.save", f.replace("{X}", x), {"kind": kind, "text": x}
    if r < 0.7:
        f, ops = rng.choice(T24_CALC)
        a, b, cc = rng.randint(2, 999), rng.randint(2, 99), rng.randint(2, 50)
        return "calc.eval", f.format(a=a, b=b, c=cc), {"expr": f"{a}{ops[0]}{b}{ops[1]}{cc}"}
    if r < 0.8:
        return "skill.list", rng.choice(T24_SKILL), {}
    if r < 0.88:
        return "work.digest", rng.choice(T24_DIGEST), {}
    return "health.check", rng.choice(T24_HEALTH), {}


# Tur 25 (2026-11-20 gece, sahibin isteği: "Emma öncelikli gelişsin, ajanlar ve alt ajanlar da dahil"): Emma'nın
# dört alt ajanının (ayıklayıcı, zamanlayıcı, takvim, gün) günlük söyleyişleri. Sınavın cümleleri DEĞİL (çitli).
T25_DAILY = [("her sabah {k}", "sabah"), ("her akşam {k}", "akşam"), ("her gün {k}", "gün")]
T25_DAILY_CLK = {"sabah": [("7'de", "07:00"), ("8'de", "08:00"), ("6:30'da", "06:30"), ("9'da", "09:00")],
                 "akşam": [("8'de", "20:00"), ("9'da", "21:00"), ("10'da", "22:00"), ("7'de", "19:00")],
                 "gün": [("öğlen 12'de", "12:00"), ("saat 14:00'te", "14:00"), ("sabah 10'da", "10:00"), ("akşam 6'da", "18:00")]}
T25_DAILY_X = ["ilacımı içmeyi", "su içmeyi", "vitamin almayı", "yürüyüşe çıkmayı", "çiçekleri sulamayı", "günlük yazmayı",
               "esneme yapmayı", "kediyi beslemeyi"]
T25_WEEK = [("her pazartesi", "mon"), ("her salı", "tue"), ("her çarşamba", "wed"), ("her perşembe", "thu"), ("her cuma", "fri"),
            ("her cumartesi", "sat"), ("her pazar", "sun")]
T25_WEEK_X = ["çöpü çıkarmayı", "haftalık raporu göndermeyi", "pazara gitmeyi", "annemi aramayı", "faturaları kontrol etmeyi",
              "çamaşır yıkamayı", "yüzmeye gitmeyi"]
T25_EV = ["Ahmet'le kahve", "doktor randevusu", "proje toplantısı", "veli toplantısı", "diş kontrolü", "spor salonu",
          "akşam yemeği", "kuaför", "arabanın bakımı", "ekip görüşmesi", "Ayşe'nin doğum günü", "noter randevusu"]
T25_PLACE = [("Köşe Kahve'de", "Köşe Kahve"), ("hastanede", "hastane"), ("ofiste", "ofis"), ("okulda", "okul"),
             ("Kadıköy'de", "Kadıköy"), ("serviste", "servis"), ("Moda'da", "Moda")]
T25_TIMER = [("çay", "çay demlensin diye"), ("makarna", "makarna için"), ("mola", "mola için"), ("fırın", "fırındaki kek için"),
             ("ders", "ders çalışmak için"), ("toplantı", "toplantıya hazırlanmak için")]
T25_REMLIST = ["hatırlatıcılarımda ne var", "kurduğum hatırlatıcıları göster", "bekleyen hatırlatıcılarım neler",
               "hangi hatırlatıcılar kurulu", "hatırlatmalarımı listele"]
T25_DAYQ = [("bugün beni ne bekliyor, kısaca söyle", "d+0"), ("yarın neler var, bir bak", "d+1"),
            ("öbür gün programım dolu mu", "d+2"), ("bugün kaç işim var", "d+0"), ("yarın erken bir işim var mı", "d+1"),
            ("bugünkü randevularım ne", "d+0"), ("yarınki toplantılarımı say", "d+1")]
T25_EMMA = ["", "", "Emma, ", "Emma ", "Emma bana "]


def _gap_tur25(rng):
    r = rng.random()
    pre = rng.choice(T25_EMMA)
    if r < 0.18:
        f, kind = rng.choice(T25_DAILY)
        clk, hm = rng.choice(T25_DAILY_CLK[kind])
        x = rng.choice(T25_DAILY_X)
        verb = rng.choice(["hatırlat", "hatırlatır mısın", "her seferinde hatırlat"])
        tr = pre + f.replace("{k}", clk) + f" {x} {verb}"
        return "reminder.set", tr, {"at": f"d+0@{hm}", "text": x, "repeat": "daily"}
    if r < 0.32:
        tr_d, code = rng.choice(T25_WEEK)
        clk, hm = rng.choice(GAP_CLOCK)
        x = rng.choice(T25_WEEK_X)
        tr = pre + f"{tr_d} {clk} {x} hatırlat"
        return "reminder.set", tr, {"at": f"{code}@{hm}", "text": x, "repeat": "weekly"}
    if r < 0.55:
        tr_d, code = rng.choice(GAP_DAYS[:7])
        clk, hm = rng.choice(GAP_CLOCK)
        ev = rng.choice(T25_EV)
        k = rng.random()
        if k < 0.35:
            pl, place = rng.choice(T25_PLACE)
            return ("calendar.add", pre + f"{tr_d} {clk} {ev} var, {pl}, takvime yaz",
                    {"title": ev, "start": f"{code}@{hm}", "place": place})
        if k < 0.65:
            n = rng.choice([30, 45, 90, 120])
            return ("calendar.add", pre + f"{tr_d} {clk} {ev} ekle, {n} dakika sürer",
                    {"title": ev, "start": f"{code}@{hm}", "minutes": n})
        return "calendar.add", pre + f"{ev} için {tr_d} {clk} takvime yer aç", {"title": ev, "start": f"{code}@{hm}"}
    if r < 0.7:
        lb, why = rng.choice(T25_TIMER)
        m = rng.choice([3, 5, 7, 10, 12, 20, 25, 40])
        return "timer.start", pre + rng.choice([f"{why} {m} dakika say", f"{why} {m} dakikalık sayaç kur"]), {"minutes": m, "label": lb}
    if r < 0.82:
        return "reminder.list", pre + rng.choice(T25_REMLIST), {}
    tr, d = rng.choice(T25_DAYQ)
    return "calendar.list", pre + tr, {"day": d}


# Tur 26 (2026-11-21, sahibin isteği: "komut beynine tüm agentları ekle, öncelik Zoe, Emma ve Mike, sonra diğerleri").
# Her ajanın kendi komutları, o ajana seslenerek ("Zoe, ..."); dil bilgisi şablonları (GRAMMAR, eğitim bölümü) + Zoe/Emma/
# Mike için yeni söyleyiş aileleri. Ajan sınavının cümleleri DEĞİL (sınav ve dış değerlendirme çitli). Paylar: Zoe %30,
# Emma %25, Mike %15, diğer 11 ajan %30 (eşit).
T26_AGENT_CMDS = {
    "zoe": ["msg.inbox", "msg.reply", "msg.contacts", "reminder.set"],
    "emma": ["reminder.set", "reminder.list", "calendar.add", "calendar.list", "timer.start", "note.write", "note.search",
             "text.translate", "mail.check", "health.check", "app.open", "memory.save", "memory.recall"],
    "mike": ["skill.run", "skill.list", "skill.record", "agent.hire", "memory.save", "memory.recall", "work.digest"],
    "sophia": ["research.start", "provider.discover", "research.watch", "web.search", "web.read"],
    "luna": ["image.generate", "card.propose", "design.colors"],
    "david": ["self.status", "skill.learn", "self.advise"],
    "jack": ["repo.audit", "image.analyze", "code.run", "repo.watch"],
    "chloe": ["calc.eval", "file.summarize", "note.search"],
    "grace": ["seo.audit"], "maya": ["ad.check", "ad.budget"], "ekbot": ["market.crypto", "market.alert"],
    "leo": ["code.run", "code.repo"], "nora": ["work.check"], "iris": ["work.check"],
}
T26_NAMES = {"zoe": "Zoe", "emma": "Emma", "mike": "Mike", "sophia": "Sophia", "luna": "Luna", "david": "David", "jack": "Jack",
             "chloe": "Chloe", "grace": "Grace", "maya": "Maya", "ekbot": "EK BOT", "leo": "Leo", "nora": "Nora", "iris": "Iris"}
# Zoe: kişiye göre gelen kutusu, kişi yönetimi, cevap; mesaj görgüsü soruları iş değildir (ask)
T26_ZOE_INBOX_C = ["{C} ne yazmış", "{C} bana ne demiş", "{C} en son ne yazdı bakar mısın", "{C} mesaj attı mı", "{C} yazdı mı bana",
                   "{C} ne demiş bir bak"]
T26_ZOE_REMOVE = ["{C} için takibi bırak", "{C} artık izlenmesin", "{C} listeden çıksın", "{C} için mesaj izlemeyi kapat"]
T26_ZOE_ASK = ["{C}'e cevap vermeden önce bana sor", "{C}'e yazmadan önce bana danış", "{C}'e cevabı ben onaylayayım"]
T26_ZOE_SEND = ["{C}'e mesaj at, {S}", "{C}'e şunu ilet: {S}", "{C}'e kısaca {S} yaz", "{C}'e whatsapp'tan {S} diye yaz"]
T26_ZOE_Q = ["mesajı görüp cevap vermemek kabalık mı", "whatsapp'ta çift mavi tik ne anlama geliyor", "sesli mesaj atmak rahatsız edici mi",
             "gece geç saatte mesaj atılır mı", "grup sohbetinden sessizce çıkmak ayıp mı", "mesajlara ne kadar sürede dönmek gerekir",
             "iş mesajlarına hafta sonu cevap verilir mi"]
# Emma: göreli zamanlı hatırlatma, günün bölümüne göre takvim
T26_EMMA_REL = [("{n} dakika sonra {X} hatırlat", "m"), ("{n} dakika sonra bana {X} diye seslen", "m"), ("{n} saat sonra {X} hatırlat", "h"),
                ("{n} saat içinde {X} aklıma getir", "h")]
T26_EMMA_X = ["ocağı kapatmayı", "çamaşırları asmayı", "ilacımı içmeyi", "toplantıya hazırlanmayı", "annemi aramayı", "kargoyu almayı",
              "suyu kapatmayı", "arabayı park yerinden almayı"]
T26_EMMA_DAYQ = [("bu akşam bir planım var mı", "d+0"), ("yarın öğleden sonra neyim var", "d+1"), ("bugün öğlene kadar ne var", "d+0"),
                 ("yarın akşam boş muyum", "d+1"), ("öbür gün sabah ne var", "d+2")]
# Mike: iş özeti aç/kapat/göster, yeni yardımcı ajan (rol), ekip hafızası
T26_MIKE_DIGEST = [("iş özetini kapat", {"action": "off"}), ("akşam özetini artık gönderme", {"action": "off"}),
                   ("iş özeti ayarlarımı göster", {"action": "list"}), ("özet ayarı ne durumda", {"action": "list"}),
                   ("her akşam {H}'de iş özeti gönder", "H"), ("iş özetini saat {H}'e al", "H")]
T26_MIKE_ROLES = ["muhasebe takibi yapan biri", "yemek tarifleri bulan biri", "spor programı hazırlayan biri", "seyahat planlayan biri",
                  "fatura ve abonelik takipçisi", "çocuk etkinlikleri öneren biri", "bahçe bakımı danışmanı"]
T26_MIKE_HIRE = ["ekibe {R} lazım", "bize {R} gerekiyor", "{R} işe al", "ekibimize {R} ekle", "Mike, {R} bul ve ekibe kat"]


# Karşı örnekler (2026-11-21, sahibin onayı: "yanlış işi hedefleyen karşı örnekler"): her ajanın alanında konuşan ama iş
# istemeyen cümleler → ask. Tur 26'da çok "yap" cümlesi eklenmiş, eş "soru" azdı; xSID yanlış işi %1,0 → %2,4 çıkmıştı.
T26_NEG = {
    "zoe": ["sevgilime ne zaman yazmalıyım sence", "uzun mesaj mı kısa mesaj mı daha iyi", "mesajlarıma neden geç dönüyorum",
            "whatsapp yedeği nasıl alınır", "okundu bilgisini kapatmak ayıp mı", "arkadaşıma kırgın olduğumu nasıl söylerim",
            "mesaj atmak mı aramak mı daha samimi"],
    "emma": ["sabah rutini nasıl oluşturulur", "takvim tutmak gerçekten işe yarar mı", "erteleme alışkanlığından nasıl kurtulurum",
             "günde kaç saat uyumak gerekir", "not almanın en iyi yöntemi ne", "hatırlatıcıları neden unutuyorum",
             "verimli çalışmak için kaç mola vermeli", "pomodoro tekniği nedir"],
    "mike": ["iş bölümü nasıl yapılır", "ekipte motivasyon nasıl artar", "haftalık özet yazmak işe yarar mı",
             "yeni birini işe almak ne zaman mantıklı", "görev dağıtırken nelere dikkat etmeli", "toplantılar neden uzar"],
    "sophia": ["araştırma yaparken nelere dikkat etmeli", "kaynak göstermek neden önemli", "haberlerin doğruluğu nasıl anlaşılır",
               "wikipedia güvenilir bir kaynak mı"],
    "luna": ["hangi renkler sakinlik verir", "iyi bir logo neye benzer", "kartlar mı liste mi daha kullanışlı",
             "koyu tema göz yorgunluğunu azaltır mı"],
    "david": ["uygulamalar neden sürekli güncelleme ister", "yeni sürümde ne değişti merak ediyorum", "yapay zeka nasıl öğrenir"],
    "jack": ["açık kaynak ne demek", "github ne işe yarar", "bir depoyu yıldızlamak ne anlama gelir", "hata ayıklama nasıl öğrenilir"],
    "chloe": ["bütçe yapmanın faydası ne", "kredi kartı borcu nasıl kapatılır", "harcamalarımı azaltmanın yolu ne",
              "faiz ile enflasyon arasındaki ilişki ne"],
    "grace": ["seo öğrenmek zor mu", "google sıralaması neden değişir", "blog yazmak siteye trafik getirir mi"],
    "maya": ["reklam bütçesi nasıl belirlenir", "iyi bir reklam sloganı nasıl yazılır", "sosyal medya reklamları işe yarar mı"],
    "ekbot": ["kripto parada uzun vade mantıklı mı", "borsa ile kripto arasındaki fark ne", "coin fiyatları neden bu kadar oynak"],
    "leo": ["programlamaya nereden başlamalı", "yapay zeka kod yazmayı öğrenebilir mi", "hangi dil daha hızlı çalışır"],
    "nora": ["bir bilginin doğru olduğundan nasıl emin olurum", "test yazmak zaman kaybı mı"],
    "iris": ["iyi bir inceleme nasıl yazılır", "eleştiriyi kişisel almamak için ne yapmalı"],
}
# 2026-11-22 sabah: uzun eğitimde kripto bilgi soruları fiyat komutuna, düşünme soruları öneri komutuna kayıyordu (ikinci
# kör sınav: 218k'da 1, 427k'da 9 yanlış iş). Terim × soru kalıbı karşı örnekleri: hepsi bilgi sorusu → ask. Sınav
# cümleleriyle aynı/çok yakın düşenleri çit (_fenced) zaten atar.
_KRIPTO_TERIM = ["kripto para", "bitcoin", "ethereum", "altcoin", "stabil coin", "blokzincir", "kripto madenciliği",
                 "kripto cüzdanı", "nft", "staking", "soğuk cüzdan", "token", "halving"]
_BILGI_KALIP = ["{t} nedir", "{t} ne demek", "{t} nasıl çalışır", "{t} riskli mi", "{t} güvenli mi", "{t} ne işe yarar",
                "{t} almak mantıklı mı", "{t} neden bu kadar popüler", "{t} hakkında bilgi verir misin"]
T26_NEG["ekbot"] = T26_NEG["ekbot"] + [k.format(t=t) for t in _KRIPTO_TERIM for k in _BILGI_KALIP]
_DUSUNCE_TERIM = ["eleştirel düşünce", "mantıklı düşünme", "analitik düşünce", "yaratıcı düşünme", "problem çözme becerisi",
                  "odaklanma", "dikkat"]
_GELISIM_KALIP = ["{t} nasıl geliştirilir", "{t} nedir", "{t} neden önemli", "{t} için ne yapmalı"]
T26_NEG["iris"] = T26_NEG["iris"] + [k.format(t=t) for t in _DUSUNCE_TERIM for k in _GELISIM_KALIP]


def _t26_zoe(rng):
    c = rng.choice(MSG_CONTACTS)
    d = c + _dat(c)
    r = rng.random()
    if r < 0.2:
        return "msg.inbox", rng.choice(T26_ZOE_INBOX_C).replace("{C}", c), {"contact": c}
    if r < 0.35:
        return "msg.contacts", rng.choice(T26_ZOE_REMOVE).replace("{C}", c), {"action": "remove", "contact": c}
    if r < 0.45:
        return "msg.contacts", rng.choice(T26_ZOE_ASK).replace("{C}'e", d), {"action": "ask", "contact": c}
    if r < 0.7:
        sy = rng.choice(MSG_SAY)
        return "msg.reply", rng.choice(T26_ZOE_SEND).replace("{C}'e", d).replace("{S}", sy), {"contact": c, "say": sy}
    q = rng.choice(T26_ZOE_Q)
    return "ask", q, {"question": q}


def _t26_emma(rng):
    r = rng.random()
    if r < 0.5:
        f, u = rng.choice(T26_EMMA_REL)
        n = rng.choice([5, 10, 15, 20, 30, 45]) if u == "m" else rng.choice([1, 2, 3, 4])
        x = rng.choice(T26_EMMA_X)
        return "reminder.set", f.replace("{n}", str(n)).replace("{X}", x), {"at": f"+{n}{u}", "text": x}
    tr, d = rng.choice(T26_EMMA_DAYQ)
    return "calendar.list", tr, {"day": d}


def _t26_mike(rng):
    if rng.random() < 0.5:
        f, a = rng.choice(T26_MIKE_DIGEST)
        if a == "H":
            h = rng.choice([18, 19, 20, 21, 22])
            return "work.digest", f.replace("{H}", str(h)), {"hour": h}
        return "work.digest", f, a
    role = rng.choice(T26_MIKE_ROLES)
    return "agent.hire", rng.choice(T26_MIKE_HIRE).replace("{R}", role), {"role": role}


def _gap_tur26(rng):
    # Şablonlardan biri şemanın izin vermediği bir değer üretebilir (ör. agent.hire helps=zoe): şemaya uyan çıkana dek
    for _ in range(20):
        cmd, tr, args = _gap_tur26_once(rng)
        try:
            validate_request({"v": 1, "id": "g", "cmd": cmd, "args": args})
            return cmd, tr, args
        except ProtocolError:
            continue
    return _t26_mike(rng)


def _gap_tur26_once(rng):
    r = rng.random()
    agent = "zoe" if r < 0.30 else "emma" if r < 0.55 else "mike" if r < 0.70 else rng.choice(
        [a for a in T26_AGENT_CMDS if a not in ("zoe", "emma", "mike")])
    # Üçte biri karşı örnek: ajanın alanında soru (iş değil); bazen ajana seslenerek
    if rng.random() < 0.33:
        q = rng.choice(T26_NEG[agent])
        if rng.random() < 0.3:
            q = T26_NAMES[agent] + rng.choice([", ", " "]) + q
        return "ask", q, {"question": q}
    # Öncelikli üçlüde yarısı yeni söyleyiş aileleri, yarısı ajanın kendi komut şablonları
    if agent in ("zoe", "emma", "mike") and rng.random() < 0.5:
        cmd, tr, args = {"zoe": _t26_zoe, "emma": _t26_emma, "mike": _t26_mike}[agent](rng)
    else:
        cmd = rng.choice(T26_AGENT_CMDS[agent])
        tr, args = GRAMMAR[cmd](rng, "train", False, False)
    if cmd != "ask" and rng.random() < 0.45:
        tr = T26_NAMES[agent] + rng.choice([", ", " "]) + tr
    return cmd, tr, args


def _gap_day_reminder(rng):
    tr_d, code = rng.choice(GAP_DAYS)
    inf = rng.choice(GAP_INF)
    acc = G.inf_accusative(inf)
    r = rng.random()
    if r < 0.55:
        tr = f"{tr_d} {acc} {rng.choice(GAP_REM_V)}"
        at = f"{code}@09:00"
    elif r < 0.8:
        clk, hm = rng.choice(GAP_CLOCK)
        tr = f"{tr_d} {clk} {acc} {rng.choice(GAP_REM_V)}"
        at = f"{code}@{hm}"
    else:
        clk, hm = rng.choice(GAP_CLOCK)
        tr = f"{tr_d} {clk} {inf} için hatırlatıcı {rng.choice(['kur', 'ekle', 'ayarla'])}"
        at = f"{code}@{hm}"
    if rng.random() < 0.4:
        tr = tr[:1].upper() + tr[1:]
    return "reminder.set", tr, {"at": at, "text": inf}


def _gap_ask(rng):
    f = rng.choice(GAP_ASK)
    hours = ["sabah yedi", "akşam beş", "saat altı", "sabah sekiz"]
    q = _fill(f, N=rng.choice(GAP_NAMES), C=rng.choice(GAP_CITIES), V=rng.choice(GAP_VENUES), S=rng.choice(GAP_SONGS),
              L=rng.choice(GAP_LISTS), k=str(rng.choice([2, 3, 4, 5, 6, 8])), m=str(rng.choice([5, 10, 15])), h=rng.choice(hours))
    tr = q[:1].upper() + q[1:] if rng.random() < 0.3 else q
    return "ask", tr, {"question": tr}


_GAP_EXT: dict = {}


def _gap_ext_fenced(src: str) -> bool:
    """MASSIVE/xSID değerlendirme cümlelerine (hazırlandıysa) aynı ya da Jaccard ≥ 0.8 olan üretilmez."""
    if "toks" not in _GAP_EXT:
        try:
            from . import massive
            rows = [r["src"] for v in massive.load_eval_sets().values() for r in v]
        except Exception:
            rows = []
        _GAP_EXT["norm"] = {_fence_norm(s) for s in rows}
        _GAP_EXT["toks"] = [_fence_toks(s) for s in rows]
    if _fence_norm(src) in _GAP_EXT["norm"]:
        return True
    t = _fence_toks(src)
    return any(len(t & u) / len(t | u) >= 0.8 for u in _GAP_EXT["toks"])


def realgap_example(rng: random.Random) -> tuple[str, str, dict]:
    """(komut, cümle, argümanlar): yarısı saatsiz/gün sözlü hatırlatıcı, yarısı yapılamayan istek → ask."""
    for _ in range(30):
        r = rng.random()
        # Tur 25: Emma ailesi %22 pay alır (sahibin önceliği); diğer aileler aynı sırayla daraldı
        # Tur 26: tüm ajanlar (öncelik Zoe, Emma, Mike) %30 pay; Tur 25 Emma ailesi %14
        cmd, tr, args = (_gap_day_reminder if r < 0.14 else _gap_ask if r < 0.28 else _gap_agent if r < 0.36 else _gap_team if r < 0.46
                         else _gap_tur24 if r < 0.56 else _gap_tur25 if r < 0.70 else _gap_tur26)(rng)
        if not _fenced(tr) and not _gap_ext_fenced(tr):
            return cmd, tr, args
    raise ProtocolError("E_INTERNAL", "gerçek açık ailesi değerlendirme cümlelerinden uzak cümle üretemedi")


def grammar_example(rng: random.Random, cmd: str, split: str) -> tuple[str, dict]:
    hf = hv = False
    if split == "test_ood":
        r = rng.random()
        hf, hv = (True, False) if r < 0.4 else (False, True) if r < 0.8 else (True, True)
    tr, args = GRAMMAR[cmd](rng, split, hf, hv)
    # Ajana seslenme ("Luna, ..." / "Luna ...") hiçbir argümanın parçası değildir (Tur 6 kök sebep).
    if rng.random() < 0.12:
        tr = rng.choice(AGENT_NAMES) + rng.choice([" ", ", "]) + tr
    return tr, args
