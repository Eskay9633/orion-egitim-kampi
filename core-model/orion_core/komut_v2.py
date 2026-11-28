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
    # 2026-11-28: yeni kalıpların %60'ı ajan aileleri (datagen.py'ye dokunmadan: çalışan eğitimin önbelleği korunur)
    if rng.random() < 0.6:
        return agent_pattern(rng)
    r = rng.random()
    if r < 0.5:
        u = "https://" + rng.choice(_LINK_SITES)
        return "web.read", rng.choice(_LINK_FRAMES).replace("{U}", u), {"url": u}
    c = rng.choice(_CONTACTS)
    if r < 0.85:
        return "msg.contacts", _fill(rng.choice(_AUTO_FRAMES), c), {"action": "auto", "contact": c}
    return "msg.contacts", _fill(rng.choice(_ASK_FRAMES), c), {"action": "ask", "contact": c}


# ------------------------------------------------------------------------- ajan aileleri (2026-11-28, ajan denetimi)
# Ajan sınavı 3'te beynin tanımadığı gündelik kalıplar. Kural katmanı bunları zaten tanıyor; ama sahibin kuralı:
# komut beyni kurala yaslanmamalı, aynı cümleyi kendisi de anlamalı. Sınav cümleleri birebir veriye girmez (_exam_keys).

_PEOPLE = ["Ece", "Hakan", "Murat", "Deniz", "Burcu", "Kaan", "Oya", "Serkan", "Pınar", "Tolga", "Nazlı", "Emir", "Cansu", "Ufuk"]
_KIN = ["Annem", "Babam", "Ablam", "Abim", "Eşim", "Kardeşim", "Teyzem", "Dayım", "Patronum", "Hocam", "Arkadaşım", "Komşum"]
_SAYINGS = ["geç kalacağım", "birazdan çıkıyorum", "yoldayım", "eve vardım", "akşam ararım", "toplantıdayım", "yarın uğrarım",
            "tamamdır görüşürüz", "yemeğe yetişirim", "trafikteyim", "sonra konuşalım", "işim bitince dönerim", "kapıdayım"]
_SAY_FRAMES = ["{D} {S} diye yaz", "{D} {S} diye haber ver", "{D} {S} diye mesaj at", "{D} {S} de", "{D} {S} yaz",
               "{D} {S} diye ilet", "{D} {S} diye söyle", "Zoe, {D} {S} diye yaz"]
_ROLES = ["muhasebe işlerine bakacak", "kira ödemelerini takip edecek", "spor haberlerini tarayacak", "anime takvimini izleyecek",
          "fatura tarihlerini takip edecek", "film önerileri hazırlayacak", "kripto haberlerini özetleyecek", "alışveriş listesini yönetecek",
          "ders notlarını düzenleyecek", "iş ilanlarını tarayacak", "sağlık randevularını izleyecek", "yemek tarifleri bulacak"]
_HIRE_FRAMES = ["{R} bir yardımcı ajan ekle", "ekibe {R} biri lazım", "{R} bir uzman lazım", "{R} yeni bir ajan ekle",
                "ekibimize {R} birisi gerek", "{R} bir yardımcı ajan al"]
_RECALL = ["tercihlerimi", "alışkanlıklarımı", "rutinlerimi", "sevdiklerimi", "sevmediklerimi"]
_RECALL_FRAMES = ["hangi {Q} biliyorsun", "benim hangi {Q} hatırlıyorsun", "{Q} biliyor musun", "hangi {Q} öğrendin"]
_NEEDS = ["konuşmayı yazıya çeviren", "görsel üreten", "metin özetleyen", "ses çıkaran", "pdf okuyan", "çeviri yapan", "video özetleyen"]
_DISC_FRAMES = ["ücretsiz {N} bir servis bul", "bedava {N} bir servis ara", "ücretsiz {N} servis öner"]
_CARDS = [("kripto", "metric"), ("hava durumu", "metric"), ("döviz", "metric"), ("yapılacaklar listesi", "list"), ("alışveriş listesi", "list"),
          ("adım sayısı", "metric"), ("bitcoin", "metric")]
_CARD_FRAMES = ["ana ekrana {T} kartı ekle", "ana sayfaya {T} kartı koy", "ekrana {T} kartı ekle", "bir {T} kartı oluştur"]
_HEX = ["#FFFFFF", "#000000", "#777777", "#1E88E5", "#FDD835", "#2E7D32", "#C62828", "#333333", "#F5F5F5", "#0D47A1"]
_STATUS = ["yeni güncelleme gelmiş mi", "güncelleme çıktı mı bak", "komut beyninin durumu ne", "sohbet beyninin son durumu ne",
           "çekirdek model ne durumda", "eğitim nerede kaldı", "eğitim bitti mi", "yeni bir güncellemen var mı", "modelin son durumu ne"]
_ADVISE = ["hangi yapay zeka servisini önerirsin", "hangi modeli kullanmamızı tavsiye edersin", "hangi sağlayıcıyı önerirsin bize",
           "{A} mi {B} mi bizim için daha iyi", "{A} mı {B} mı kullanalım sence", "{A} mi yoksa {B} mi daha uygun"]
_HELPERS = ["gemini", "deepseek", "mistral", "openrouter", "groq", "cerebras"]
_GOALS = ["e postalarımı etiketlemeyi", "haftalık plan hazırlamayı", "faturaları özetlemeyi", "market listesi çıkarmayı",
          "toplantı notlarını düzenlemeyi", "spor sonuçlarını derlemeyi", "anime bölümlerini takip etmeyi"]
_DOMAINS = ["kahvedukkani.com", "benimblogum.net", "ornekfirin.com.tr", "kitapci-ornek.com", "spor-ornek.org", "tasarimci.io"]
_KEYWORDS = ["kahve", "roman", "ekmek", "koşu ayakkabısı", "logo tasarımı"]
_SEO_FRAMES = ["{U} seo kontrolü yap", "{U} sitesinin seo puanı kaç", "{U} sitemin seo eksiklerini bul",
               "{U} sitesini {K} anahtar kelimesiyle denetle"]
_CHECK = ["az önce yazdığın kodu test et", "demin yazdığın fonksiyonu kontrol et", "son işini bir de denetle", "son işini nora kontrol etsin",
          "hazırladığın metni iris incelesin", "bu cevabın doğruluğunu kontrol et", "ürettiğin betiği yeniden kontrol et",
          "yazdığın kodu bir daha denetle, hata var mı", "son cevabını tekrar kontrol et"]
_WATCH_LIST = ["izlediğin konuları göster", "takip ettiğin konuların listesi", "hangi konuları izliyorsun", "nöbetteki konuları listele"]

_EXAM_KEYS: set | None = None


def _key(s: str) -> str:
    return re.sub(r"[^\w]+", " ", s.lower()).strip()


def _exam_keys() -> set:
    """Ajan sınavlarındaki cümleler (birebir) eğitime girmesin."""
    global _EXAM_KEYS
    if _EXAM_KEYS is None:
        import json
        from pathlib import Path
        base = Path(__file__).resolve().parents[2] / "shared" / "core-model"
        keys = set()
        for p in base.glob("ajan-sinavi*.jsonl"):
            keys |= {_key(json.loads(x)["src"]) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()}
        _EXAM_KEYS = keys
    return _EXAM_KEYS


def _q(w: str) -> str:
    """Soru eki ünlü uyumu: gemini mi, mistral mı, groq mu."""
    return {"a": "mı", "ı": "mı", "e": "mi", "i": "mi", "o": "mu", "u": "mu", "ö": "mü", "ü": "mü"}[_last_vowel(w)]


def _kin_gen(k: str) -> str:
    """Akrabalık adının ilgi eki, kesmesiz: Annem → annemin, Babam → babamın."""
    return k.lower() + {"a": "ın", "ı": "ın", "e": "in", "i": "in", "o": "un", "u": "un", "ö": "ün", "ü": "ün"}[_last_vowel(k)]


def _kin_dat(k: str) -> str:
    """Akrabalık adının yönelme eki, kesmesiz: Annem → anneme, Babam → babama."""
    return k.lower() + ("a" if _last_vowel(k) in "aıou" else "e")


def agent_pattern(rng: random.Random) -> tuple[str, str, dict]:
    for _ in range(20):
        cmd, src, args = _agent_once(rng)
        if _key(src) not in _exam_keys():
            return cmd, src, args
    return cmd, src, args


def _agent_once(rng: random.Random) -> tuple[str, str, dict]:
    k = rng.randrange(14)
    if k == 0:
        frames = _SAY_FRAMES
        if rng.random() < 0.5:
            c = rng.choice(_PEOPLE); d = _dat(c)
        else:
            c = rng.choice(_KIN); d = _kin_dat(c)
            frames = [x for x in _SAY_FRAMES if "diye" in x]   # kesmesiz akraba adı yalnız "diye" ile
        say = rng.choice(_SAYINGS)
        return "msg.reply", rng.choice(frames).replace("{D}", d).replace("{S}", say), {"contact": c, "say": say}
    if k == 1:
        c = rng.choice(_PEOPLE + _KIN)
        f = rng.choice(["{G} attığı mesajları göster", "{G} gönderdiği son mesaj ne", "{G} yazdığı mesajlara bak"])
        return "msg.inbox", f.replace("{G}", (_kin_gen(c) if c in _KIN else _gen(c))), {"contact": c}
    if k == 2:
        c = rng.choice(_PEOPLE + _KIN)
        f = rng.choice(["{G} mesajlarına artık sen bak", "{G} mesajlarına bundan sonra sen cevap ver", "{G} mesajlarıyla sen ilgilen"])
        return "msg.contacts", f.replace("{G}", (_kin_gen(c) if c in _KIN else _gen(c))), {"action": "auto", "contact": c}
    if k == 3:
        role = rng.choice(_ROLES)
        return "agent.hire", rng.choice(_HIRE_FRAMES).replace("{R}", role), {"role": role}
    if k == 4:
        q = rng.choice(_RECALL)
        src = rng.choice(_RECALL_FRAMES).replace("{Q}", q)
        return "memory.recall", src, {"query": q[:-1] if q.endswith(("ı", "i", "u", "ü")) else q}
    if k == 5:
        need = rng.choice(_NEEDS)
        return "provider.discover", rng.choice(_DISC_FRAMES).replace("{N}", need), {"need": need}
    if k == 6:
        t, kind = rng.choice(_CARDS)
        return "card.propose", rng.choice(_CARD_FRAMES).replace("{T}", t), {"kind": kind, "title": t}
    if k == 7:
        a, b = rng.sample(_HEX, 2)
        f = rng.choice(["{B} zemin üstüne {A} yazı uygun mu", "{B} zeminde {A} yazı okunur mu", "{A} yazı {B} zemine uyar mı"])
        return "design.colors", f.replace("{A}", a).replace("{B}", b), {"colors": [a, b]}
    if k == 8:
        return "self.status", rng.choice(_STATUS), {}
    if k == 9:
        a, b = rng.sample(_HELPERS, 2)
        f = rng.choice(_ADVISE).replace("{A} mı", "{A} mi").replace("{B} mı", "{B} mi")
        return "self.advise", f.replace("{A} mi", a + " " + _q(a)).replace("{B} mi", b + " " + _q(b)).replace("{A}", a).replace("{B}", b), {}
    if k == 10:
        goal = rng.choice(_GOALS)
        return "skill.learn", goal + rng.choice([" öğren", " de öğren"]), {"goal": goal}
    if k == 11:
        dom = rng.choice(_DOMAINS); kw = rng.choice(_KEYWORDS)
        f = rng.choice(_SEO_FRAMES)
        args = {"url": "https://" + dom}
        if "{K}" in f:
            args["keyword"] = kw
        return "seo.audit", f.replace("{U}", dom).replace("{K}", kw), args
    if k == 12:
        return "work.check", rng.choice(_CHECK), {}
    if rng.random() < 0.5:
        return "research.watch", rng.choice(_WATCH_LIST), {"action": "list"}
    # Yüze ve bine biten sayılar: ek her zaman 'den / 'e (iki yüz'den, on beş bin'e)
    a = rng.choice([200, 300, 1500, 2000, 15000, 40000]); b = a + rng.choice([100, 200, 500, 1000, 3000])
    f = rng.choice(["{A}'den {B}'e yüzde kaç arttı hesapla", "yüzde kaç zam aldım hesapla {A}'den {B}'e", "{A}'den {B}'e artış yüzde kaç"])
    return "calc.eval", f.replace("{A}", str(a)).replace("{B}", str(b)), {"expr": f"({b}-{a})/{a}*100"}
