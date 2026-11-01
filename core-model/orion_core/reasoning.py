"""Basit akıl yürütme diyalogları (YALNIZCA eğitim).

Bilişsel Yetenek Sınavı'nın (shared/core-model/cognitive-exam.jsonl) maddelerini KOPYALAMAZ: konular, adlar, sayılar
ve kalıplar farklıdır; kural ve bağlam turları çoğunlukla çok turludur (sınavdakiler tek mesaj). Her kullanıcı
mesajı yine de dialogs.persona_dialogues'ta near_cogexam / near_exam süzgecinden geçer.
Türler: karşılaştırma, iki adımlı sözel aritmetik, sahibinin söylediğinde çelişki fark edip sorma, aynı sohbette
anlatılan yeni bir kuralı uygulama, üç tur boyunca bağlamı koruma. Sayılar üretilir, cevaplar hesaplanır (yanlış
cevap yok); cevap adımları kısaca gösterir.
"""
from __future__ import annotations

import random


def _cap(s: str) -> str:
    c = s[:1]
    return ("İ" if c == "i" else "I" if c == "ı" else c.upper()) + s[1:]


# ------------------------------------------------------------------ karşılaştırma
# (nesne çifti, ölçü, birim, büyük olan için sıfat)
CMP = [(("benim çantam", "kardeşimin çantası"), ("senin çantan", "kardeşininki"), "kilo", "ağır"),
       (("salondaki halı", "yatak odasındaki halı"), ("salondaki", "yatak odasındaki"), "metre", "uzun"),
       (("mavi kavanoz", "kırmızı kavanoz"), ("mavi kavanoz", "kırmızı kavanoz"), "litre", "büyük"),
       (("sabahki koşum", "akşamki koşum"), ("sabahki koşun", "akşamki koşun"), "kilometre", "uzun"),
       (("eski telefonum", "yeni telefonum"), ("eski telefonun", "yeni telefonun"), "gram", "ağır")]
CMP_Q = ["{A} {x} {u}, {b} {y} {u}. Hangisi daha {adj}, arada ne kadar fark var?",
         "{A} {x} {u} geliyor, {b} ise {y} {u}. Hangisi daha {adj}?"]
SHOP = [("süt", "şişe"), ("ekmek", "tane"), ("yumurta", "koli"), ("deterjan", "kutu")]


# Üçlü sıralama (Tur 23): kişi adları ve ölçüler sınavdakilerden farklı; cevap sıralamayı ve farkı gösterir
TRIO_NAMES = [("Deniz", "Deniz'in"), ("Kerem", "Kerem'in"), ("Selin", "Selin'in"), ("Mert", "Mert'in"),
              ("Ece", "Ece'nin"), ("Bora", "Bora'nın"), ("Nil", "Nil'in"), ("Tuna", "Tuna'nın"), ("Defne", "Defne'nin"),
              ("Arda", "Arda'nın"), ("İpek", "İpek'in"), ("Ozan", "Ozan'ın")]
# (cümle kalıbı, birim, aralık, çok/az sıfatı)
TRIO = [("{g} boyu {v} santimetre", "santimetre", (140, 195), "uzun", "kısa"),
        ("{n} {v} yaşında", "yaş", (8, 70), "büyük", "küçük"),
        ("{n} bu ay {v} kitap okudu", "kitap", (1, 12), "çok okuyan", "az okuyan"),
        ("{g} koşusu {v} dakika sürdü", "dakika", (18, 75), "uzun koşan", "kısa koşan")]


def trio_turns(rng: random.Random) -> list[tuple[str, str]]:
    people = rng.sample(TRIO_NAMES, 3)
    pat, unit, (lo, hi), more, less = rng.choice(TRIO)
    vals = rng.sample(range(lo, hi), 3)
    parts = ", ".join(pat.format(n=n, g=g, v=v) for (n, g), v in zip(people, vals))
    order = sorted(zip(vals, [n for n, _ in people]), reverse=True)
    listed = ", ".join(f"{n} {v}" for v, n in order)
    if rng.random() < 0.5:
        q = f"{parts}. En {more} kim, en {less} olanla arasında ne kadar fark var?"
        a = (f"Büyükten küçüğe: {listed}. En {more} {order[0][1]}, en {less} {order[2][1]}. "
             f"Fark {order[0][0]} − {order[2][0]} = {order[0][0] - order[2][0]} {unit}.")
    else:
        q = f"{parts}. Ortada kim kalıyor?"
        a = f"Büyükten küçüğe: {listed}. Ortada {order[1][1]} var."
    return [(q, a)]


def compare_turns(rng: random.Random) -> list[tuple[str, str]]:
    if rng.random() < 0.3:
        return trio_turns(rng)
    if rng.random() < 0.5:
        (qa, qb), (aa, ab), u, adj = rng.choice(CMP)
        x, y = rng.sample(range(2, 40), 2)
        q = rng.choice(CMP_Q).format(A=_cap(qa), b=qb, x=x, y=y, u=u, adj=adj)
        big = aa if x > y else ab
        return [(q, f"{_cap(big)} daha {adj}; arada {abs(x - y)} {u} fark var.")]
    item, unit = rng.choice(SHOP)
    p1, p2 = rng.sample(range(12, 60), 2)
    n = rng.randint(2, 6)
    q = (f"Köşedeki markette bir {unit} {item} {p1} lira, büyük markette {p2} lira. {n} {unit} alacağım; "
         f"hangisinden almalıyım, ne kadar kazanırım?")
    cheap, diff = ("köşedeki market" if p1 < p2 else "büyük market"), abs(p1 - p2)
    return [(q, f"{_cap(cheap)} daha ucuz. {unit.capitalize()} başına {diff} lira fark var; {n} {unit} için "
                f"{n} × {diff} = {n * diff} lira kazanırsın.")]


# ------------------------------------------------------------------ çok adımlı sözel aritmetik (Tur 23)
def multistep_turns(rng: random.Random) -> list[tuple[str, str]]:
    """Üç adımlı problemler; her adım ayrı bir eşitlik (zincirleme "a − b − c" yazılmaz)."""
    k = rng.randrange(5)
    if k == 0:
        n, per, tip = rng.randint(3, 6), rng.choice([120, 150, 180, 240]), rng.choice([30, 60, 90])
        total = n * per + tip
        while total % n:
            tip += 10
            total = n * per + tip
        q = (f"{n} arkadaş yemeğe çıktık, herkes {per} liralık menü aldı, üstüne {tip} lira bahşiş bıraktık. "
             f"Hesabı eşit bölersek kişi başı ne öderiz?")
        a = (f"Menüler {n} × {per} = {n * per} lira. Bahşişle {n * per} + {tip} = {total} lira. "
             f"Kişi başı {total} ÷ {n} = {total // n} lira.")
    elif k == 1:
        price = rng.choice([200, 300, 400, 500, 800])
        pct = rng.choice([10, 20, 25, 50])
        n = rng.randint(2, 4)
        off = price * pct // 100
        q = f"Etiket fiyatı {price} lira olan bir tişörtte yüzde {pct} indirim var. {n} tane alırsam ne öderim?"
        a = (f"{price} liranın yüzde {pct} kadarı {off} lira indirim eder; bir tanesi {price} − {off} = {price - off} lira. "
             f"{n} tanesi {n} × {price - off} = {n * (price - off)} lira.")
    elif k == 2:
        h, m = rng.randint(7, 15), rng.choice([0, 10, 15, 20, 30, 40])
        d1, d2, w = rng.choice([25, 35, 40, 50]), rng.choice([20, 30, 45]), rng.choice([10, 15, 20])
        tot = d1 + w + d2
        end = h * 60 + m + tot
        q = (f"Evden çıkış saatim {h}.{m:02d}. Otobüs {d1} dakika, aktarmada {w} dakika bekleme, "
             f"sonra metro {d2} dakika. Kaçta varırım?")
        a = (f"Toplam yol {d1} + {w} + {d2} = {tot} dakika. Çıkış {h}.{m:02d}, üstüne {tot} dakika: "
             f"varış saatin {end // 60}.{end % 60:02d}.")
    elif k == 3:
        boxes, per, eaten = rng.randint(3, 6), rng.choice([6, 8, 10, 12]), rng.randint(3, 9)
        kids = rng.choice([x for x in (2, 3, 4, 5, 6) if (boxes * per - eaten) % x == 0] or [1])
        left = boxes * per - eaten
        q = (f"{boxes} kutu kurabiye aldım, her kutuda {per} tane var. Yolda {eaten} tanesini yedik. "
             f"Kalanı {kids} çocuğa eşit paylaştıracağım; her çocuğa kaç tane düşer?")
        a = (f"Toplam {boxes} × {per} = {boxes * per} kurabiye. {boxes * per} − {eaten} = {left} kaldı. "
             f"{left} ÷ {kids} = {left // kids} tane düşer.")
    else:
        km, use = rng.choice([200, 300, 400, 500, 600]), rng.choice([5, 6, 7, 8])
        lt_price = rng.choice([40, 42, 45, 48])
        litres = km * use // 100
        q = (f"Arabam 100 kilometrede {use} litre yakıyor, yakıtın litresi {lt_price} lira. {km} kilometrelik yolun "
             f"yakıt masrafı ne tutar?")
        a = (f"{km} kilometre, 100 kilometrenin {km // 100} katı: {km // 100} × {use} = {litres} litre gerekir. {litres} × {lt_price} = "
             f"{litres * lt_price} lira tutar.")
    return [(q, a)]


# ------------------------------------------------------------------ iki adımlı sözel aritmetik
def arithmetic_turns(rng: random.Random) -> list[tuple[str, str]]:
    k = rng.randrange(6)
    if k == 0:
        a, b = rng.randint(8, 40), rng.randint(3, 9)
        t = a * b + rng.randint(10, 200)
        q = f"Günde {a} sayfa kitap okuyorum. Kitap {t} sayfa; {b} gün sonra kaç sayfam kalır?"
        ans = f"{b} günde {a} × {b} = {a * b} sayfa okursun. {t} − {a * b} = {t - a * b} sayfa kalır."
    elif k == 1:
        p, n = rng.randint(15, 90), rng.randint(2, 5)
        m = rng.choice([x for x in (100, 200, 500) if x >= p * n] or [1000])
        q = f"Bir paket kurabiye {p} lira. {n} paket alıp kasaya {m} lira versem ne kadar para üstü alırım?"
        ans = f"{n} paket {n} × {p} = {n * p} lira tutar. {m} − {n * p} = {m - n * p} lira para üstü alırsın."
    elif k == 2:
        a, b, c = rng.randint(20, 70), rng.randint(15, 60), rng.choice([10, 15, 20])
        t = a + b + c
        q = (f"Ödevim {a} dakika, kitap okumam {b} dakika sürecek, arada da {c} dakika mola vereceğim. "
             f"Toplam kaç saat kaç dakika eder?")
        ans = f"{a} + {b} + {c} = {t} dakika; bu da {t // 60} saat {t % 60} dakika eder."
    elif k == 3:
        a, w = rng.randint(50, 400), rng.randint(3, 10)
        target = a * w + rng.randint(1, 20) * 50
        q = f"Her hafta {a} lira biriktiriyorum. Hedefim {target} lira; {w} hafta sonra hedefime ne kadar kalır?"
        ans = f"{w} haftada {a} × {w} = {a * w} lira birikir. {target} − {a * w} = {target - a * w} lira kalır."
    elif k == 4:
        n = rng.choice([2, 4, 5])
        per = rng.choice([50, 60, 80, 100])
        kk = rng.choice([x for x in (6, 8, 10, 12, 15, 20) if x != n])
        q = f"Tarif {n} kişilik ve {n * per} gram un istiyor. {kk} kişi için kaç gram un gerekir?"
        ans = f"Kişi başına {n * per} ÷ {n} = {per} gram düşüyor. {kk} kişi için {per} × {kk} = {per * kk} gram un gerekir."
    else:
        v = rng.choice([40, 50, 60, 80, 90])
        h = rng.randint(2, 5)
        mola = rng.choice([15, 20, 30])
        q = (f"Saatte {v} kilometre hızla {v * h} kilometre yol gideceğim, yolda bir kez {mola} dakika mola vereceğim. "
             f"Yolculuk toplam ne kadar sürer?")
        ans = f"{v * h} ÷ {v} = {h} saat yol, üstüne {mola} dakika mola: toplam {h} saat {mola} dakika sürer."
    return [(q, ans)]


# ------------------------------------------------------------------ çelişkiyi fark edip sorma
# (ilk söz, çelişen söz/istek, Orion'un yeniden söylemesi A, B, doğruysa yardım sorusu)
CONTRA = [
    ("{Day} akşamı tamamen boşum, bir plan yapalım.", "Ama {day} akşamı nöbetim var, onu da unutma.",
     "{day} akşamı boş olduğunu", "aynı akşam nöbetin olduğunu söylüyorsun", "{Day} akşamı nöbetin var mı, yoksa boş musun?"),
    ("{Day} günü hiç evde olmayacağım.", "{Day} günü evde misafir ağırlayacağım, ne pişireyim?",
     "{day} günü evde olmayacağını", "aynı gün evde misafir ağırlayacağını söylüyorsun",
     "Planın mı değişti, {day} günü evde misin?"),
    ("Ben hiç yüzme bilmem.", "Yarın havuzda iki kilometre yüzeceğim, öncesinde ne yesem?",
     "yüzme bilmediğini", "yarın iki kilometre yüzeceğini söylüyorsun", "Yüzmeyi yeni mi öğrendin, yoksa yanlış mı anladım?"),
    ("Evde hiç bitki yok.", "Saksılarımı ne sıklıkla sulamalıyım?",
     "evde hiç bitki olmadığını", "saksılarını soruyorsun", "Yeni bitki mi aldın, yoksa başka bir yerdeki saksılar mı?"),
    ("Arabam yok, her yere toplu taşımayla gidiyorum.", "Arabamın lastiklerini ne zaman değiştirmeliyim?",
     "araban olmadığını", "arabanın lastiklerini soruyorsun", "Yeni araba mı aldın, yoksa birinin arabası için mi soruyorsun?"),
    ("Üç kardeşiz, en küçükleri benim.", "Ailenin tek çocuğu olarak bayramda kimi ziyaret etsem?",
     "üç kardeş olduğunuzu", "ailenin tek çocuğu olduğunu söylüyorsun", "Hangisi doğru, kardeşlerin var mı?"),
    ("Bu hafta tamamen izindeyim, hiç işe gitmiyorum.", "Yarın sabah ofisteki toplantıya ne giysem?",
     "bu hafta izinde olduğunu", "yarın ofiste toplantın olduğunu söylüyorsun", "İznin bitti mi, yoksa toplantıya izinde mi katılacaksın?"),
    ("Sabahları hiç kahvaltı yapmam.", "Her sabahki kahvaltımı daha sağlıklı yapmak istiyorum, ne önerirsin?",
     "sabahları kahvaltı yapmadığını", "her sabahki kahvaltından bahsediyorsun", "Kahvaltıya yeni mi başladın?"),
    ("Hiç yurt dışına çıkmadım.", "Geçen yıl Paris'te gittiğim müzenin adını hatırlıyor musun?",
     "hiç yurt dışına çıkmadığını", "geçen yıl Paris'te olduğunu söylüyorsun", "Hangisi doğru, Paris'e gitmiş miydin?"),
]
CONTRA += [  # Tur 23: daha fazla çelişki türü
    ("Kedilere alerjim var, yanlarına bile yaklaşamıyorum.", "Bu akşam kedimi sevip oyun oynayacağım, hangi oyuncağı alayım?",
     "kedilere alerjin olduğunu", "kedinle oyun oynayacağını söylüyorsun", "Alerjin geçti mi, yoksa başka bir hayvan mı?"),
    ("{Day} günü şehir dışındayım, akşama kadar dönmem.", "{Day} öğlen evde bir tamirci bekliyorum, ne sormalıyım?",
     "{day} günü şehir dışında olacağını", "aynı gün öğlen evde tamirci beklediğini söylüyorsun",
     "{Day} günü evde misin, şehir dışında mı?"),
    ("Et yemiyorum, uzun zamandır vejetaryenim.", "Akşam için en güzel köfte tarifini verir misin?",
     "vejetaryen olduğunu", "köfte tarifi istiyorsun", "Sebzeli bir köfte mi istersin, yoksa başkası için mi?"),
    ("Hiç bisiklet sürmeyi bilmiyorum.", "Hafta sonu bisikletle 50 kilometrelik tura çıkacağım, ne götüreyim?",
     "bisiklet sürmeyi bilmediğini", "50 kilometrelik bisiklet turuna çıkacağını söylüyorsun",
     "Bisiklete yeni mi başladın, yoksa yanlış mı anladım?"),
    ("Kahveyi tamamen bıraktım, hiç içmiyorum.", "Bu sabahki üçüncü kahvemden sonra elim titriyor, normal mi?",
     "kahveyi bıraktığını", "bu sabah üç kahve içtiğini söylüyorsun", "Yeniden mi başladın? Önce hangisi doğru, onu bilelim."),
]
CONTRA_OPEN = ["Bir saniye, küçük bir karışıklık var:", "Dur bir dakika:", "Bir şeyi netleştirelim:",
               "Burada bir tutarsızlık görüyorum:"]


def contradiction_turns(rng: random.Random) -> list[tuple[str, str]]:
    day = rng.choice(DAYS)
    s1, s2, ra, rb, ask = (x.format(day=day, Day=_cap(day)) for x in rng.choice(CONTRA))
    a = f"{rng.choice(CONTRA_OPEN)} önce {ra} söyledin, şimdi de {rb}. {ask}"
    if rng.random() < 0.5:  # iki ayrı mesaj
        ack = rng.choice(["Tamam, not ettim.", "Anladım.", "Peki, aklımda."])
        a2 = f"{rng.choice(CONTRA_OPEN)} az önce {ra} söylemiştin, şimdi de {rb}. {ask}"
        return [(s1, ack), (s2, a2)]
    return [(f"{s1} {s2}", a)]


# ------------------------------------------------------------------ aynı sohbette anlatılan kuralı uygulama
RULES = [
    ("Bundan sonra 'mavi liste' dediğimde iş listemi kastediyorum.", "Anladım: 'mavi liste' senin iş listen demek.",
     "Mavi listeye ne eklemeliyim sence, yarın sunumum var.",
     "Mavi listeye, yani iş listene 'sunum hazırlığı' girsin bence; sunumdan önceki akşam da son bir prova iyi olur."),
    ("Bizim evde kural şu: kim çay demlerse bardakları öbürü yıkar.", "Tamam, kuralı anladım.",
     "Bu akşam çayı eşim demledi. Bardakları kim yıkayacak?",
     "Kurala göre bardakları demleyen değil öbürü yıkar; eşin demlediğine göre bardaklar sende."),
    ("Bir kelime oyunu oynayalım: her cevabının sonuna 'yıldız' ekle.", "Olur, başlayalım yıldız.",
     "Bugün hava nasıl olsun istersin?", "Güneşli ve serin olsun yıldız."),
    ("Ailemizde 'sarı gün' denince herkes evde yemek yer demek.", "Anladım, sarı günde herkes evde yer.",
     "Bugün sarı gün. Dışarıda yemek için rezervasyon önerir misin?",
     "Ama bugün sarı gün; kurala göre herkes evde yiyecek. Dışarıyı başka güne bırakalım, evde ne pişirelim?"),
    ("Bundan sonra 'gece modu' dediğimde kısa ve sakin cevap ver.", "Anladım; gece modunda kısa ve sakin.",
     "Gece modu. Yarın ne giysem?", "Rahat ve sıcak bir şey. İyi geceler."),
]


RULES += [  # Tur 23: kuralı YENİ bir duruma aktarma
    ("Evde kuralımız: kim yemeği yaparsa sofrayı öbürü toplar.", "Anladım, yapan değil öbürü toplar.",
     "Bugün yemeği kızım yaptı, oğlum da oradaydı. Sofrayı kim toplar?",
     "Kurala göre yemeği yapan değil öbürü toplar; kızın yaptığına göre sofrayı oğlun toplar."),
    ("Bundan sonra 'kırmızı kod' dediğimde acil olanları ilk sıraya koy.", "Tamam; kırmızı kod, acil olan önce demek.",
     "Kırmızı kod: fatura ödemesi bugün son gün, bir de kitap iadesi gelecek hafta.",
     "Kırmızı kod, acil olan önce: ilk iş bugün son günü olan fatura ödemesi; kitap iadesi gelecek haftaya kalabilir."),
    ("Bizim oyunda kural şu: zar çift gelirse iki adım ileri, tek gelirse bir adım geri.", "Anladım; çift ileri iki, tek geri bir.",
     "İlk atışta 4, ikincide 3 geldi. Başladığım yere göre neredeyim?",
     "4 çift: iki adım ileri. 3 tek: bir adım geri. Sonuçta başladığın yerin bir adım önündesin."),
]


def _num_rule(rng: random.Random) -> tuple[str, str, str, str]:
    """Sayılı kurallar: değerler her seferinde yeniden seçilir, cevap hesaplanır."""
    k = rng.randrange(4)
    if k == 3:  # Tur 23: dönüşüm kuralı (kendi birimi) → yeni miktara aktarma
        unit, worth = rng.choice([("yıldız", 3), ("jeton", 5), ("kupon", 4), ("rozet", 2)])
        have = rng.randint(3, 12)
        return (f"Kendi ödül sistemimizde bir {unit} {worth} puan ediyor.", f"Anladım: bir {unit} {worth} puan.",
                f"Oğlum bu hafta {have} {unit} topladı. Kaç puan etti?",
                f"{have} × {worth} = {have * worth} puan etti.")
    if k == 0:
        (x, px), (y, py) = rng.sample([("kitap okuma", 3), ("yürüyüş", 2), ("meditasyon", 4), ("spor", 5),
                                       ("bisiklet turu", 1)], 2)
        px, py = rng.randint(1, 6), rng.randint(1, 6)
        nx, ny = rng.randint(1, 4), rng.randint(1, 4)
        return (f"Kendi puan sistemim var: {x} {px} puan, {y} {py} puan.", f"Anladım: {x} {px}, {y} {py} puan.",
                f"Bugün {nx} kez {x}, {ny} kez de {y} yaptım. Kaç puan ettim?",
                f"{nx} × {px} = {nx * px}, {ny} × {py} = {ny * py}; toplam {nx * px + ny * py} puan.")
    if k == 1:
        m, n = rng.choice([8, 10, 12, 15, 20]), rng.randint(2, 5)
        return (f"Not: 'bir çay molası' benim için tam {m} dakika demek.", f"Tamam, bir çay molası {m} dakika.",
                f"Bugün {n} çay molası verdim. Toplam kaç dakika mola verdim?",
                f"{n} mola × {m} dakika = {n * m} dakika mola vermişsin.")
    lim, used = rng.choice([(2, 1.5), (3, 2), (3, 1), (4, 2.5), (2, 1)])
    words = {0.5: "30 dakika", 1: "1 saat", 1.5: "bir buçuk saat", 2: "2 saat", 2.5: "iki buçuk saat", 3: "3 saat"}
    fmt = words.__getitem__
    left = lim - used
    return (f"Kuralımız şu: hafta sonu ekran süresi en fazla {lim} saat.", f"Tamam, hafta sonu en fazla {lim} saat ekran.",
            f"Cumartesi {fmt(used)} dizi izledim. Daha ne kadar ekrana bakabilirim?",
            f"{lim} saatlik sınırdan {fmt(used)} kullandın; {fmt(left)} kaldı.")


def rule_turns(rng: random.Random) -> list[tuple[str, str]]:
    r, ack, q, a = _num_rule(rng) if rng.random() < 0.5 else rng.choice(RULES)
    return [(r, ack), (q, a)]


# ------------------------------------------------------------------ üç tur boyunca bağlam
# Üç tur: bilgi → araya ilgisiz bir mesaj → bilgiyi KULLANAN ya da hatırlatan soru. Yuvalı üretilir.
DAYS = ["pazartesi", "salı", "çarşamba", "perşembe", "cuma", "cumartesi", "pazar"]
EVENTS3 = [("kuzenimin nişanına gidiyorum", "nişan", "şık ama rahat bir şey: koyu renk bir pantolon ve güzel bir gömlek"),
           ("bir mülakata gireceğim", "mülakat", "sade ve ütülü bir gömlek, rahat ama düzgün ayakkabı"),
           ("arkadaşlarla doğa yürüyüşüne çıkıyoruz", "doğa yürüyüşü", "rahat bir pantolon, yağmurluk ve sağlam ayakkabı"),
           ("bir düğüne davetliyim", "düğün", "şık bir kıyafet ve uzun süre ayakta durabileceğin ayakkabılar"),
           ("plaja gidiyoruz", "plaj", "ince ve açık renk kıyafetler, şapka ve güneş kremi"),
           ("bir konsere gideceğim", "konser", "rahat ve katmanlı bir şey; içerisi ısınır, dışarısı serin olabilir")]
PLACES = [("salondaki kitaplığın üstünde", "salondaki kitaplığın üstünde"), ("mutfak tezgâhında", "mutfak tezgâhında"),
          ("arabanın torpidosunda", "arabanın torpidosunda"), ("yatak odasındaki komodinde", "yatak odasındaki komodinde"),
          ("işteki masamın çekmecesinde", "işteki masanın çekmecesinde"), ("montumun iç cebinde", "montunun iç cebinde"),
          ("banyodaki rafta", "banyodaki rafta"), ("çantamın yan gözünde", "çantanın yan gözünde")]
OBJECTS = [("telefonumu", "Telefonum"), ("anahtarlarımı", "Anahtarlarım"), ("gözlüğümü", "Gözlüğüm"),
           ("cüzdanımı", "Cüzdanım"), ("kulaklığımı", "Kulaklığım")]
BUDGET = [("ayakkabı", "Gördüğüm ayakkabı"), ("mont", "Beğendiğim mont"), ("kulaklık", "Baktığım kulaklık"),
          ("hediye", "Seçtiğim hediye")]
MID = [("Bu arada bugün hava çok güzel.", "Evet, değerlendirmek lazım!"),
       ("Öğlen güzel bir makarna yedim.", "Afiyet olsun, enerji depoladın."),
       ("Az önce bir kahve yaptım.", "Afiyet olsun!"),
       ("Akşam bir dizi izleyeceğim.", "Keyifli seyirler!"),
       ("Bugün işler biraz sakin.", "Sakin günler de lazım."),
       ("Komşunun kedisi yine balkona geldi.", "Demek misafirin var!")]
ACK = ["Tamam, aklımda.", "Anladım.", "Not ettim kafama.", "Tamam."]


ALLERGY = [("fıstığa", "fıstık", "fıstıksız bir kek; fıstık yerine yulaf ve kuru üzüm kullanabilirsin"),
           ("süte", "süt", "sütsüz bir tatlı: bitkisel sütle sütlaç ya da fırında tarçınlı elma"),
           ("yumurtaya", "yumurta", "yumurtasız bir tatlı: muzlu yulaf kurabiyesi iyi gider"),
           ("glutene", "gluten", "glutensiz bir tatlı: pirinç unuyla bir kek ya da fırında tarçınlı elma")]
# (benim …, benim …-in, senin …-in)
REL = [("annem", "annemin", "annenin"), ("eşim", "eşimin", "eşinin"), ("kardeşim", "kardeşimin", "kardeşinin"),
       ("en yakın arkadaşım", "en yakın arkadaşımın", "en yakın arkadaşının"), ("kızım", "kızımın", "kızının")]


def context3_turns(rng: random.Random) -> list[tuple[str, str]]:
    k = rng.randrange(6)
    if k == 4:  # Tur 23: kısıtı hatırlayıp öneriyi ona göre yapma
        who, mine, yours = rng.choice(REL)
        to, noun, sug = rng.choice(ALLERGY)
        t1 = (f"Bu arada {mine} {to} alerjisi var.", rng.choice(ACK))
        q = f"Akşam {who} için bir tatlı yapacağım, ne önerirsin?"
        return [t1, rng.choice(MID), (q, f"{_cap(yours)} {noun} alerjisi olduğu için {sug}.")]
    if k == 5:  # Tur 23: tarihten gün hesabı
        _, mine, yours = rng.choice(REL)
        day = rng.randint(3, 28)
        now = rng.randint(1, day - 1)
        t1 = (f"{_cap(mine)} doğum günü ayın {day}. günü.", rng.choice(ACK))
        q = f"Bugün ayın {now}. günü. Hediye için kaç günüm var?"
        return [t1, rng.choice(MID), (q, f"{_cap(yours)} doğum günü ayın {day}. günü, bugün {now}. gün: "
                                          f"{day} − {now} = {day - now} günün var.")]
    if k == 0:
        day = rng.choice(DAYS)
        ev, noun, dress = rng.choice(EVENTS3)
        t1 = (f"{_cap(day)} {ev}.", rng.choice(["Ne güzel!", "Harika, keyifli geçsin!", "Güzel bir plan."]))
        q, a = f"{_cap(day)} için ne giysem?", f"{_cap(noun)} için {dress} iyi olur."
    elif k == 1:
        (obj, Obj), (place, yours) = rng.choice(OBJECTS), rng.choice(PLACES)
        t1 = (f"{_cap(obj)} {place} unuttum galiba.", rng.choice(ACK))
        q, a = f"{Obj} nerede olabilir demiştim?", f"{_cap(yours)} unuttuğunu söylemiştin; önce oraya bak."
    elif k == 2:
        item, seen = rng.choice(BUDGET)
        b = rng.choice([500, 750, 1000, 1500, 2000])
        p = b + rng.choice([-200, -100, 100, 250, 300, 500])
        t1 = (f"Bu ay {item} için {b} lira ayırdım.", rng.choice(ACK))
        q = f"{seen} {p} lira, alayım mı?"
        if p > b:
            a = (f"Ayırdığın {b} liranın {p - b} lira üstünde. İndirimi beklemek ya da bütçeyi gözden geçirmek iyi "
                 f"olabilir; karar senin.")
        else:
            a = f"Ayırdığın {b} liranın içinde kalıyor, hatta {b - p} lira artıyor. Beğendiysen bence al; karar senin."
    else:
        i = rng.randrange(1, 7)
        day, prev = DAYS[i], DAYS[i - 1]
        t1 = (f"Sınavım {day} sabahı.", rng.choice(["Başarılar şimdiden!", "Tamam, aklımda. Başarılar!"]))
        q = "Çalışma planını hangi güne göre yapmalıyım?"
        a = f"Sınavın {day} sabahı; planı {prev} akşamı bitecek şekilde yap, son akşam yalnızca tekrar."
    return [t1, rng.choice(MID), (q, a)]


# ================================================================== Tur 24: parametrik akıl yürütme şablonları
# Her şablon (turlar, meta) döndürür; meta = {"kind": ..., girdiler..., "ans": cevapta geçmesi gereken sonuç}.
# Testler sonucu meta girdilerinden BAĞIMSIZ olarak yeniden hesaplar. Cevaplar kısa adımlar gösterir
# ("Önce …, sonra …, yani …"); zincirleme işlem yazılmaz (her eşitlik tek işlem).
# Sınav maddelerinden farklı adlar, konular ve kalıplar; her kullanıcı turu near_cogexam süzgecinden de geçer.

NAMES2 = [("Ilgaz", "Ilgaz'dan", "Ilgaz'ın"), ("Toprak", "Toprak'tan", "Toprak'ın"), ("Ada", "Ada'dan", "Ada'nın"),
          ("Mina", "Mina'dan", "Mina'nın"), ("Batu", "Batu'dan", "Batu'nun"), ("Irmak", "Irmak'tan", "Irmak'ın"),
          ("Kayra", "Kayra'dan", "Kayra'nın"), ("Ceren", "Ceren'den", "Ceren'in"), ("Sarp", "Sarp'tan", "Sarp'ın"),
          ("Lina", "Lina'dan", "Lina'nın"), ("Efe", "Efe'den", "Efe'nin"), ("Nazlı", "Nazlı'dan", "Nazlı'nın"),
          ("Tuğra", "Tuğra'dan", "Tuğra'nın"), ("Asya", "Asya'dan", "Asya'nın"), ("Doruk", "Doruk'tan", "Doruk'un"),
          ("Ekin", "Ekin'den", "Ekin'in")]
FIRST = ["Önce", "İlk olarak", "İlk adımda"]
THEN = ["sonra", "ardından", "sonra da"]
SO = ["Yani", "Dolayısıyla", "Sonuç olarak"]


def _steps(rng: random.Random, steps: list[str], concl: str) -> str:
    """"Önce a; sonra b; sonra c. Yani d." — adımlar küçük harfle başlar."""
    body = f"{rng.choice(FIRST)} {steps[0]}"
    for st in steps[1:]:
        body += f"; {rng.choice(THEN)} {st}"
    end = "" if concl.endswith(("?", "!")) else "."
    return f"{body}. {rng.choice(SO)} {concl}{end}"


def _join(*parts: str) -> str:
    return " ".join(p.strip() for p in parts if p and p.strip())


def _hm(t: int) -> str:
    return f"{(t // 60) % 24}.{t % 60:02d}"


# ------------------------------------------------------------------ sıralama: 3–4 öğe
# (öğeler, cümle kalıbı, birim, aralık, büyük sıfatı, küçük sıfatı)
ORD_ITEMS = [
    (["kırmızı valiz", "mavi valiz", "yeşil valiz", "siyah valiz"], "{x} {v} kilo", "kilo", (6, 32), "ağır", "hafif"),
    (["fırın", "manav", "eczane", "kırtasiye"], "{x} eve {v} metre", "metre", (80, 950), "uzak", "yakın"),
    (["sarı kova", "beyaz kova", "turuncu kova", "gri kova"], "{x} {v} litre", "litre", (3, 25), "büyük", "küçük"),
    (["birinci tarif", "ikinci tarif", "üçüncü tarif", "dördüncü tarif"], "{x} {v} dakikada pişiyor", "dakika", (12, 95),
     "uzun süren", "kısa süren"),
    (["mor defter", "lacivert defter", "pembe defter", "kahverengi defter"], "{x} {v} sayfa", "sayfa", (40, 240),
     "kalın", "ince"),
    (["kuzey yolu", "sahil yolu", "orman yolu", "köprü yolu"], "{x} {v} kilometre", "kilometre", (9, 58), "uzun", "kısa"),
]
ORD_NAMED = [("{n} bu hafta {v} saat uyudu", "saat", (38, 61), "çok uyuyan", "az uyuyan"),
             ("{g} kumbarasında {v} lira var", "lira", (35, 480), "çok biriktiren", "az biriktiren"),
             ("{n} bu ay {v} kez yüzmeye gitti", "kez", (2, 19), "çok giden", "az giden")]
ORD_REL = [("daha uzun boylu", "en uzun boylu", "en kısa boylu"), ("daha hızlı koşuyor", "en hızlı koşan", "en yavaş koşan"),
           ("daha erken kalkıyor", "en erken kalkan", "en geç kalkan"), ("daha çok kitap okuyor", "en çok okuyan", "en az okuyan")]


def order_turns(rng: random.Random):
    k = rng.randrange(3)
    if k == 2:  # karşılaştırma zinciri (karışık sırada verilir) → en büyük/en küçük ya da iki uç
        n = rng.choice([3, 4])
        people = rng.sample(NAMES2, n)  # gerçek sıra: büyükten küçüğe
        comp, top, bot = rng.choice(ORD_REL)
        facts = [f"{a[0]}, {b[1]} {comp}" for a, b in zip(people, people[1:])]
        rng.shuffle(facts)
        chain = " > ".join(p[0] for p in people)
        if rng.random() < 0.5:
            ask, ans = f"{_cap(top)} kim?", people[0][0]
        else:
            ask, ans = f"{_cap(bot)} kim?", people[-1][0]
        q = ". ".join(facts) + ". " + ask
        a = _steps(rng, [f"bilgileri tek sıraya dizelim: {chain}", f"en başta {people[0][0]}, en sonda {people[-1][0]} kalıyor"],
                   f"{ask[:-5].lower()} {ans}")
        return [(q, a)], {"kind": "zincir", "order": [p[0] for p in people], "ask": "top" if ans == people[0][0] else "bot",
                          "ans": ans}
    n = rng.choice([3, 4])
    if k == 0:
        items, pat, unit, (lo, hi), more, less = rng.choice(ORD_ITEMS)
        names = rng.sample(items, n)
        vals = rng.sample(range(lo, hi), n)
        parts = ", ".join(pat.format(x=x, v=v) for x, v in zip(names, vals))
        parts = _cap(parts)
    else:
        pat, unit, (lo, hi), more, less = rng.choice(ORD_NAMED)
        ppl = rng.sample(NAMES2, n)
        names = [p[0] for p in ppl]
        vals = rng.sample(range(lo, hi), n)
        parts = ", ".join(pat.format(n=p[0], g=p[2], v=v) for p, v in zip(ppl, vals))
    order = sorted(zip(vals, names), reverse=True)
    listed = ", ".join(f"{x} {v}" for v, x in order)
    mode = rng.randrange(3)
    if mode == 0:
        q = f"{parts}. En {more} hangisi, en {less} olanla farkı ne?"
        d = order[0][0] - order[-1][0]
        a = _steps(rng, [f"büyükten küçüğe sıralayalım: {listed}",
                         f"farkı bulalım: {order[0][0]} − {order[-1][0]} = {d} {unit}"],
                   f"en {more} {order[0][1]}, en {less} {order[-1][1]}; arada {d} {unit} var")
        ans = f"{d} {unit}"
    elif mode == 1:
        tgt = rng.choice(names)
        rank = [x for _, x in order].index(tgt) + 1
        q = f"{parts}. Büyükten küçüğe dizersek {tgt} kaçıncı sırada?"
        a = _steps(rng, [f"büyükten küçüğe sıralayalım: {listed}"], f"{tgt} {rank}. sırada")
        ans = f"{rank}. sırada"
    else:
        tot = sum(vals)
        q = f"{parts}. Hepsi toplam ne kadar ediyor, en {less} hangisi?"
        steps = [f"en {less} olanı bulalım: {order[-1][1]} ({order[-1][0]} {unit})"]
        acc = vals[0]
        for v in vals[1:]:
            steps.append(f"{acc} + {v} = {acc + v}")
            acc += v
        a = _steps(rng, steps, f"toplam {tot} {unit}, en {less} {order[-1][1]}")
        ans = f"toplam {tot} {unit}"
    return [(q, a)], {"kind": "sirala", "names": names, "vals": vals, "mode": mode, "unit": unit,
                      "tgt": tgt if mode == 1 else None, "ans": ans}


# ------------------------------------------------------------------ basit mantık: eğer-ise, ya-ya da, değil
# (kural, P doğru, P yanlış, Q doğru, Q yanlış, Q sorusu, P sorusu, Q evet cevabı, P hayır cevabı)
IFTHEN = [
    ("Kargo öğlene kadar gelirse paketi akşam birlikte açacağız.", "Kargo saat 11'de geldi.", "Kargo öğleden sonra geldi.",
     "Paketi akşam birlikte açtık.", "Paketi akşam açmadık.", "Paketi akşam birlikte açacak mıyız?",
     "Kargo öğlene kadar gelmiş mi?", "paketi akşam birlikte açacaksınız", "kargo öğlene kadar gelmemiş"),
    ("Su ısıtıcısının ışığı yanarsa fişi takılıdır.", "Isıtıcının ışığı şu an yanıyor.", "Isıtıcının ışığı yanmıyor.",
     "Isıtıcının fişi takılı.", "Isıtıcının fişi takılı değil.", "Isıtıcının fişi takılı mı?",
     "Isıtıcının ışığı yanıyor mu?", "fişi takılı", "ışığı yanmıyor"),
    ("Kütüphane kartın varsa kitap ödünç alabilirsin.", "Kütüphane kartım var.", "Kütüphane kartım yok.",
     "Kitap ödünç aldım.", "Kitap ödünç alamadım.", "Kitap ödünç alabilir miyim?",
     "Kütüphane kartım var mı?", "kitap ödünç alabilirsin", "kütüphane kartın yok"),
    ("Saksının toprağı kuruysa çiçeği sularız.", "Bugün saksının toprağı kupkuruydu.", "Bugün saksının toprağı nemliydi.",
     "Bugün çiçeği suladım.", "Bugün çiçeği sulamadım.", "Bugün çiçek sulandı mı?",
     "Bugün saksının toprağı kuru muydu?", "çiçek sulandı", "toprak kuru değilmiş"),
    ("Akşam altıdan önce eve dönersem yürüyüşe çıkarız.", "Bugün beşte eve döndüm.", "Bugün sekizde eve döndüm.",
     "Bugün yürüyüşe çıktık.", "Bugün yürüyüşe çıkmadık.", "Bugün yürüyüşe çıkacak mıyız?",
     "Altıdan önce eve dönmüş müyüm?", "yürüyüşe çıkacaksınız", "altıdan önce dönmemişsin"),
    ("Kombinin basıncı düşükse uyarı ışığı yanar.", "Kombinin basıncı düşük görünüyor.", "Kombinin basıncı normal.",
     "Kombinin uyarı ışığı yanıyor.", "Kombinin uyarı ışığı yanmıyor.", "Uyarı ışığı yanar mı?",
     "Kombinin basıncı düşük mü?", "uyarı ışığı yanar", "basınç düşük değil"),
]
IF_OPEN = ["Kuralımız şu:", "Bizde böyle:", "Bil bakalım:", ""]


def logic_turns(rng: random.Random):
    k = rng.randrange(3)
    if k == 0:
        rule, p, np_, q_, nq, askq, askp, yes, nop = rng.choice(IFTHEN)
        case = rng.choice(["mp", "mt", "da", "ac"])
        lead = _join(rng.choice(IF_OPEN), rule)
        rule_l = rule[0].lower() + rule[1:-1]
        if case == "mp":
            u = f"{lead} {p} {askq}"
            a = _steps(rng, [f"kural diyor ki: {rule_l}", "koşul gerçekleşmiş"], f"evet, {yes}")
            ans = "evet"
        elif case == "mt":
            u = f"{lead} {nq} {askp}"
            a = _steps(rng, [f"kural diyor ki: {rule_l}", "koşul gerçekleşseydi sonuç da olurdu, ama sonuç olmamış"],
                       f"hayır, {nop}")
            ans = "hayır"
        elif case == "da":
            u = f"{lead} {np_} {askq}"
            a = _steps(rng, [f"kural yalnızca koşul gerçekleşince ne olacağını söylüyor", "koşul gerçekleşmemiş, kural bu durum için bir şey demiyor"],
                       "kesin bir şey söylenemez; başka bir sebeple yine olabilir")
            ans = "söylenemez"
        else:
            u = f"{lead} {q_} {askp}"
            a = _steps(rng, [f"kural koşuldan sonuca gidiyor, tersini söylemiyor", "sonucun olması koşulun olduğunu kanıtlamaz"],
                       "kesin bir şey söylenemez; sonuç başka bir sebeple de olmuş olabilir")
            ans = "söylenemez"
        return [(u, a)], {"kind": "egerise", "case": case, "ans": ans}
    if k == 1:  # ya ... ya da: eleme
        obj, places = rng.choice([
            ("Şemsiyem", [("vestiyerde", "vestiyerde"), ("arabada", "arabada"), ("ofiste", "ofiste"), ("annemde", "annende")]),
            ("Şarj aletim", [("salonda", "salonda"), ("mutfakta", "mutfakta"), ("çantamda", "çantanda"), ("arabada", "arabada")]),
            ("Pasaportum", [("çekmecede", "çekmecede"), ("kasada", "kasada"), ("dolabın üstünde", "dolabın üstünde")]),
            ("Okuma gözlüğüm", [("komodinde", "komodinde"), ("ceketimin cebinde", "ceketinin cebinde"), ("banyoda", "banyoda"),
                                ("masada", "masada")])])
        n = rng.choice([2, 3]) if len(places) >= 3 else 2
        ps = rng.sample(places, n)
        keep = rng.randrange(n)
        mine = [m for m, _ in ps]
        opts = " ya " + ", ya ".join(mine[:-1]) + " ya da " + mine[-1]
        no = [ps[i] for i in range(n) if i != keep]
        checked = " ".join(f"{_cap(m)} baktım, yok." for m, _ in no)
        u = f"{obj}{opts}. {checked} Nerede olmalı?"
        steps = [f"seçenekler: {', '.join(y for _, y in ps)}"] + [f"{y} olmadığına göre o eleniyor" for _, y in no]
        a = _steps(rng, steps, f"geriye tek seçenek kalıyor: {ps[keep][1]}")
        return [(u, a)], {"kind": "yaya", "opts": [y for _, y in ps], "no": [y for _, y in no], "ans": ps[keep][1]}
    # değil / hariç: kümeden çıkarma
    who = rng.sample(NAMES2, rng.choice([4, 5]))
    names = [w[0] for w in who]
    absent = rng.sample(names, rng.choice([1, 2]))
    came = [x for x in names if x not in absent]
    ab = " ve ".join(absent)
    u = rng.choice([f"Pikniğe {', '.join(names[:-1])} ve {names[-1]} çağrıldı. {ab} gelemedi. Kimler geldi, kaç kişi?",
                    f"Takımda {', '.join(names[:-1])} ve {names[-1]} var. Bu antrenmana {ab} dışında herkes katıldı. "
                    f"Kimler katıldı, kaç kişi?"])
    a = _steps(rng, [f"listede {len(names)} kişi var", f"{ab} çıkınca {len(names)} − {len(absent)} = {len(came)} kişi kalıyor"],
               f"{', '.join(came)}; toplam {len(came)} kişi")
    return [(u, a)], {"kind": "haric", "names": names, "absent": absent, "ans": f"{len(came)} kişi"}


# ------------------------------------------------------------------ birim ve zaman hesabı
MONTHS = [("mart", 31), ("nisan", 30), ("mayıs", 31), ("haziran", 30), ("temmuz", 31), ("ağustos", 31), ("eylül", 30),
          ("ekim", 31), ("kasım", 30)]


def units_turns(rng: random.Random):
    k = rng.randrange(6)
    if k == 0:  # dakika → saat-dakika + bitiş saati
        m = rng.randint(70, 200)
        st = rng.randint(17, 21) * 60 + rng.choice([0, 15, 30, 45])
        what = rng.choice(["Film", "Konser", "Maç yayını", "Tiyatro oyunu", "Belgesel"])
        u = f"{what} {m} dakika sürüyor, başlangıç saati {_hm(st)}. Kaç saat kaç dakika eder, kaçta biter?"
        a = _steps(rng, [f"{m} dakika {m // 60} saat {m % 60} dakika eder",
                         f"başlangıca {m // 60} saat {m % 60} dakika ekleyelim"], f"bitiş saati {_hm(st + m)}")
        return [(u, a)], {"kind": "bitis", "start": st, "dur": m, "ans": _hm(st + m)}
    if k == 1:  # saat-dakika → dakika
        h, mm = rng.randint(1, 5), rng.choice([10, 15, 20, 25, 40, 45, 50])
        what = rng.choice(["Yolculuk", "Ders", "Antrenman", "Toplantı", "Ödev"])
        u = f"{what} {h} saat {mm} dakika sürdü. Bu toplam kaç dakika eder?"
        a = _steps(rng, [f"{h} × 60 = {h * 60} dakika", f"{h * 60} + {mm} = {h * 60 + mm}"], f"{h * 60 + mm} dakika eder")
        return [(u, a)], {"kind": "dakika", "h": h, "m": mm, "ans": f"{h * 60 + mm} dakika"}
    if k == 2:  # tarihe kalan gün
        i = rng.randrange(len(MONTHS) - 1)
        (m1, l1), (m2, _) = MONTHS[i], MONTHS[i + 1]
        d1, d2 = rng.randint(2, l1 - 1), rng.randint(1, 28)
        ev = rng.choice(["tatilim başlıyor", "kuzenimin düğünü var", "taşınıyoruz", "kursum başlıyor", "maraton koşusu var"])
        u = f"Bugün {d1} {m1}. {d2} {m2} tarihinde {ev}. Kaç gün kaldı?"
        rest = l1 - d1
        a = _steps(rng, [f"{m1} {l1} gün çekiyor, ay sonuna {l1} − {d1} = {rest} gün var",
                         f"{m2} ayında {d2} gün daha", f"{rest} + {d2} = {rest + d2}"], f"{rest + d2} gün kaldı")
        return [(u, a)], {"kind": "gun", "d1": d1, "len1": l1, "d2": d2, "ans": f"{rest + d2} gün"}
    if k == 3:  # hesabı bölme: biri ayrıca bir şey almış
        n = rng.randint(3, 6)
        per = rng.choice([150, 180, 200, 240, 260, 300, 350])
        extra = rng.choice([60, 80, 90, 120, 150])
        who = rng.choice(NAMES2)
        total = n * per + extra
        u = (f"Hesap {total} lira geldi, {n} kişiyiz. {who[0]} ayrıca {extra} liralık tatlı aldı, onu kendisi ödeyecek. "
             f"Ortak kısmı eşit bölersek kişi başı ne düşer, {who[0]} toplam ne öder?")
        a = _steps(rng, [f"tatlıyı çıkaralım: {total} − {extra} = {n * per} lira ortak", f"{n * per} ÷ {n} = {per} lira kişi başı",
                         f"{who[0]} için {per} + {extra} = {per + extra}"],
                   f"kişi başı {per} lira, {who[0]} {per + extra} lira öder")
        return [(u, a)], {"kind": "hesap", "total": total, "n": n, "extra": extra, "ans": f"{per} lira"}
    if k == 4:  # yüzde: pay ve kalan / zam
        s = rng.choice([8000, 12000, 15000, 20000, 24000, 30000])
        pct = rng.choice([10, 15, 20, 25, 30, 35, 40])
        r = s // 100 * pct
        if rng.random() < 0.5:
            u = f"Aylık gelirim {s} lira, yüzde {pct} kadarını biriktirmek istiyorum. Ne kadar biriktiririm, ne kalır?"
            a = _steps(rng, [f"yüzde biri {s} ÷ 100 = {s // 100} lira", f"yüzde {pct} kadarı {s // 100} × {pct} = {r} lira",
                             f"kalan {s} − {r} = {s - r}"], f"{r} lira biriktirirsin, {s - r} lira kalır")
            return [(u, a)], {"kind": "yuzde", "s": s, "pct": pct, "up": False, "ans": f"{r} lira"}
        u = f"Aidatımız {s // 10} liraydı, yüzde {pct} zam geldi. Yeni aidat ne kadar?"
        s2 = s // 10
        r2 = s2 * pct // 100
        a = _steps(rng, [f"zam için {s2} × {pct} = {s2 * pct}, bunu 100'e bölünce {r2} lira",
                         f"{s2} + {r2} = {s2 + r2}"], f"yeni aidat {s2 + r2} lira")
        return [(u, a)], {"kind": "yuzde", "s": s2, "pct": pct, "up": True, "ans": f"{s2 + r2} lira"}
    # günlük dakika → haftalık saat
    m = rng.choice([20, 25, 30, 35, 40, 45, 50, 75, 90])
    d = rng.choice([5, 6, 7])
    act = rng.choice(["yürüyüş", "piyano çalışması", "kitap okuma", "esneme hareketi", "dil çalışması"])
    t = m * d
    u = f"Haftada {d} gün, her gün {m} dakika {act} yapıyorum. Haftada toplam kaç saat ediyor?"
    hm = f"{t // 60} saat {t % 60} dakika" if t % 60 else f"{t // 60} saat"
    a = _steps(rng, [f"{d} × {m} = {t} dakika", f"{t} dakika {hm} eder"], f"haftada {hm}")
    return [(u, a)], {"kind": "haftalik", "d": d, "m": m, "ans": hm}


# ------------------------------------------------------------------ çok adımlı planlar (ara sonuç açıkça)
def plan_turns(rng: random.Random):
    k = rng.randrange(5)
    if k == 0:  # alışveriş + para üstü
        (i1, p1), (i2, p2) = rng.sample([("defter", 45), ("kalem", 15), ("silgi", 10), ("cetvel", 25), ("boya kalemi", 60),
                                         ("dosya", 35)], 2)
        n1, n2 = rng.randint(2, 5), rng.randint(2, 6)
        tot = n1 * p1 + n2 * p2
        pay = next(x for x in (100, 200, 300, 500, 1000) if x >= tot)
        u = f"Kırtasiyede {i1} {p1} lira, {i2} {p2} lira. {n1} {i1} ve {n2} {i2} alıp {pay} lira verirsem ne kadar para üstü alırım?"
        a = _steps(rng, [f"{i1} için {n1} × {p1} = {n1 * p1}", f"{i2} için {n2} × {p2} = {n2 * p2}",
                         f"toplam {n1 * p1} + {n2 * p2} = {tot}"], f"{pay} − {tot} = {pay - tot} lira para üstü alırsın")
        return [(u, a)], {"kind": "ustu", "n1": n1, "p1": p1, "n2": n2, "p2": p2, "pay": pay, "ans": f"{pay - tot} lira"}
    if k == 1:  # birikim: kaç hafta
        price = rng.choice([1500, 2400, 3000, 3600, 4200, 5000])
        w = rng.choice([100, 150, 200, 250, 300])
        weeks = rng.randint(3, 12)
        have = price - w * weeks
        if have <= 0:
            have, price = 200, w * weeks + 200
        item = rng.choice(["bisiklet", "kulaklık", "tablet", "kamp çadırı", "gitar"])
        u = f"{_cap(item)} {price} lira, elimde {have} lira var. Her hafta {w} lira ayırırsam kaç haftada alırım?"
        a = _steps(rng, [f"eksik kalan {price} − {have} = {price - have} lira", f"{price - have} ÷ {w} = {weeks}"],
                   f"{weeks} haftada alırsın")
        return [(u, a)], {"kind": "hafta", "price": price, "have": have, "w": w, "ans": f"{weeks} hafta"}
    if k == 2:  # geriye doğru zaman planı
        arrive = rng.randint(18, 21) * 60 + rng.choice([0, 30])
        prep, cook = rng.choice([15, 20, 25, 30]), rng.choice([35, 40, 45, 50, 60, 75])
        tot = prep + cook
        u = (f"Misafirlerin geliş saati {_hm(arrive)}. Hazırlık {prep} dakika, pişirme {cook} dakika sürüyor. "
             f"En geç kaçta başlamalıyım?")
        a = _steps(rng, [f"toplam süre {prep} + {cook} = {tot} dakika", f"geliş saatinden {tot} dakika geri gidelim"],
                   f"en geç başlama saatin {_hm(arrive - tot)}")
        return [(u, a)], {"kind": "geri", "arrive": arrive, "prep": prep, "cook": cook, "ans": _hm(arrive - tot)}
    if k == 3:  # su hedefi
        lt = rng.choice([2000, 2500, 3000])
        g = rng.choice([200, 250, 500])
        g = g if lt % g == 0 else 250
        need = lt // g
        drank = rng.randint(1, need - 1)
        u = f"Günde {lt} mililitre su içmek istiyorum, bardağım {g} mililitre. Şu ana kadar {drank} bardak içtim. Kaç bardak kaldı?"
        a = _steps(rng, [f"hedef {lt} ÷ {g} = {need} bardak", f"{need} − {drank} = {need - drank}"],
                   f"{need - drank} bardak kaldı")
        return [(u, a)], {"kind": "su", "lt": lt, "g": g, "drank": drank, "ans": f"{need - drank} bardak"}
    # kitabı bitirme: günde kaç sayfa
    days = rng.randint(3, 10)
    per = rng.randint(12, 45)
    read = rng.randint(20, 150)
    total = read + days * per
    u = f"Kitap {total} sayfa, {read} sayfasını okudum. {days} gün içinde bitirmek istiyorum. Günde kaç sayfa okumalıyım?"
    a = _steps(rng, [f"kalan {total} − {read} = {total - read} sayfa", f"{total - read} ÷ {days} = {per}"],
               f"günde {per} sayfa okumalısın")
    return [(u, a)], {"kind": "sayfa", "total": total, "read": read, "days": days, "ans": f"{per} sayfa"}


# ------------------------------------------------------------------ çelişki: sayısal tutarlılık denetimi
def contra_num_turns(rng: random.Random):
    k = rng.randrange(3)
    ok = rng.random() < 0.4  # bazen tutarlıdır: her şeye "çelişki" demeyi öğrenmesin
    if k == 0:
        n1, n2 = rng.randint(6, 18), rng.randint(6, 18)
        tot = n1 + n2 if ok else n1 + n2 + rng.choice([-3, -2, 2, 3, 4])
        grp = rng.choice([("Kursumuzda", "kursiyer", "kadın", "erkek"), ("Koroda", "kişi", "soprano", "bas"),
                          ("Bahçede", "ağaç", "elma", "erik")])
        t1 = (f"{grp[0]} toplam {tot} {grp[1]} var.", rng.choice(["Tamam.", "Anladım.", "Not ettim kafama."]))
        u2 = f"{n1} {grp[2]}, {n2} {grp[3]} var. Bu sayılar tutuyor mu?"
        s = n1 + n2
        if ok:
            a = _steps(rng, [f"{n1} + {n2} = {s}", f"bu, başta söylediğin {tot} ile aynı"], "sayılar tutarlı, sorun yok")
        else:
            a = _steps(rng, [f"{n1} + {n2} = {s}", f"başta söylediğin toplam ise {tot}"],
                       f"burada bir çelişki var; {s} mü, {tot} mü, hangisi doğru?")
        return [t1, (u2, a)], {"kind": "toplam", "n1": n1, "n2": n2, "tot": tot, "ans": "tutarlı" if ok else "çelişki"}
    if k == 1:
        have = rng.choice([500, 750, 1000, 1200, 1500])
        spent = rng.randint(4, have // 50 - 2) * 25
        left = have - spent if ok else have - spent + rng.choice([-100, -50, 50, 100])
        t1 = (f"Sabah cüzdanımda {have} lira vardı.", rng.choice(["Tamam.", "Anladım."]))
        u2 = f"Gün içinde {spent} lira harcadım, şimdi {left} lira kaldı. Hesap doğru mu?"
        r = have - spent
        if ok:
            a = _steps(rng, [f"{have} − {spent} = {r}", "söylediğin kalanla aynı"], "hesap doğru")
        else:
            a = _steps(rng, [f"{have} − {spent} = {r}", f"senin söylediğin kalan ise {left}"],
                       f"bir tutarsızlık var; {abs(r - left)} liralık fark nereden geliyor, bir harcama unutulmuş olabilir mi?")
        return [t1, (u2, a)], {"kind": "cuzdan", "have": have, "spent": spent, "left": left,
                               "ans": "doğru" if ok else "tutarsızlık"}
    day = rng.choice(DAYS)
    h = rng.randint(9, 17)
    e1 = rng.choice(["veteriner randevum", "kombi bakımı için servis geliyor", "noter randevum", "kurs sınavım"])
    e2 = rng.choice(["şehir dışına giden trene bineceğim", "uzun bir yüzme dersim var", "arkadaşımın taşınmasına yardım edeceğim"])
    h2 = h if not ok else (h + rng.choice([3, 4]) if h <= 13 else h - rng.choice([3, 4]))
    t1 = (f"{_cap(day)} saat {h}.00'de {e1}.", rng.choice(["Tamam, aklımda.", "Anladım."]))
    u2 = f"{_cap(day)} saat {h2}.00'de de {e2}. Programım uygun mu?"
    if ok:
        a = _steps(rng, [f"ilki saat {h}.00'de, ikincisi {h2}.00'de", f"arada {abs(h2 - h)} saat var"],
                   "çakışma yok, program uygun; yine de yol süresini hesaba kat")
    else:
        a = _steps(rng, [f"ilki saat {h}.00'de", f"ikincisi de aynı saatte, {h2}.00'de"],
                   "iki iş çakışıyor; hangisini başka saate alalım?")
    return [t1, (u2, a)], {"kind": "saat", "h1": h, "h2": h2, "ans": "uygun" if ok else "çakışıyor"}


# ------------------------------------------------------------------ uydurma kuralı yeni duruma aktarma
CHORES = ["bulaşık", "çöp", "çiçek sulama", "market", "kedi maması"]


def transfer_turns(rng: random.Random):
    k = rng.randrange(4)
    if k == 0:  # dönüşümlü nöbet
        ppl = [p[0] for p in rng.sample(NAMES2, rng.choice([3, 4]))]
        chore = rng.choice(CHORES)
        d = rng.randrange(1, 7)
        r = (f"Evde {chore} nöbeti sırayla: {', '.join(ppl)}. Her gün bir kişi, pazartesi {ppl[0]} başlıyor.",
             rng.choice(["Anladım, sırayla dönüyor.", "Tamam, pazartesi " + ppl[0] + " başlıyor."]))
        u = f"{_cap(DAYS[d])} günü {chore} kimde?"
        who = ppl[d % len(ppl)]
        a = _steps(rng, [f"pazartesi 1. gün, {DAYS[d]} {d + 1}. gün", f"{len(ppl)} kişi dönüyor; {d + 1}. gün sıra "
                                                                       f"{d % len(ppl) + 1}. kişide"],
                   f"{DAYS[d]} günü sıra {who}")
        return [r, (u, a)], {"kind": "nobet", "ppl": ppl, "d": d, "ans": who}
    if k == 1:  # en kısa iş önce
        jobs = rng.sample([("fatura kontrolü", 10), ("çamaşır asma", 15), ("e-postalara bakma", 20), ("mutfak temizliği", 40),
                           ("ütü", 35), ("bitki sulama", 5), ("dolap düzenleme", 50), ("market listesi", 8)], rng.choice([3, 4]))
        r = ("Bundan sonra kuralım şu: aynı anda birkaç iş varsa en kısa süren önce yapılır.",
             rng.choice(["Anladım: kısa olan önce.", "Tamam, en kısa iş önce."]))
        u = "Şimdi şunlar var: " + ", ".join(f"{j} {m} dakika" for j, m in jobs) + ". Hangi sırayla yapayım?"
        srt = sorted(jobs, key=lambda x: x[1])
        a = _steps(rng, ["süreleri kısadan uzuna dizelim: " + ", ".join(f"{j} ({m})" for j, m in srt)],
                   "sıra şöyle: " + " → ".join(j for j, _ in srt))
        return [r, (u, a)], {"kind": "kisa", "jobs": jobs, "ans": " → ".join(j for j, _ in srt)}
    if k == 2:  # yaşın katı harçlık
        mult = rng.choice([5, 10, 15, 20])
        (a1, _, _), (a2, _, _) = rng.sample(NAMES2, 2)
        y1, y2 = rng.randint(6, 15), rng.randint(6, 15)
        r = (f"Bizde haftalık harçlık kuralı: yaşının {mult} katı lira.", f"Anladım: yaş × {mult} lira.")
        u = f"{a1} {y1}, {a2} {y2} yaşında. İkisine toplam ne kadar harçlık düşer?"
        a = _steps(rng, [f"{a1}: {y1} × {mult} = {y1 * mult}", f"{a2}: {y2} × {mult} = {y2 * mult}",
                         f"{y1 * mult} + {y2 * mult} = {(y1 + y2) * mult}"], f"toplam {(y1 + y2) * mult} lira")
        return [r, (u, a)], {"kind": "harclik", "mult": mult, "y1": y1, "y2": y2, "ans": f"{(y1 + y2) * mult} lira"}
    # doğru/yanlış puanlama
    x, y = rng.choice([(4, 1), (5, 2), (3, 1), (10, 3)])
    d = rng.randint(6, 20)
    w = rng.randint(1, min(10, d * x // y))
    r = (f"Bilgi yarışmamızda kural: doğru cevap {x} puan, yanlış cevap eksi {y} puan, boş sıfır.",
         f"Anladım: doğru +{x}, yanlış −{y}, boş 0.")
    u = f"{d} doğru, {w} yanlış yaptım. Puanım kaç?"
    a = _steps(rng, [f"doğrular {d} × {x} = {d * x}", f"yanlışlar {w} × {y} = {w * y}"],
               f"{d * x} − {w * y} = {d * x - w * y} puan")
    return [r, (u, a)], {"kind": "puan", "x": x, "y": y, "d": d, "w": w, "ans": f"{d * x - w * y} puan"}


# ------------------------------------------------------------------ 3–4 tur bağlam + çeldirici
EV_PLACES = [("veteriner", "veteriner randevusu"), ("kuaför", "kuaför randevusu"), ("tamirci", "tamirci"),
             ("göz doktoru", "göz doktoru randevusu"), ("kurs kaydı", "kurs kaydı")]
CTX_MID = [("Bu arada hava kapanıyor.", "Şemsiyeyi unutma o zaman."), ("Az önce bir bardak su içtim.", "Güzel, iyi gelir."),
           ("Akşam erken yatacağım.", "İyi fikir."), ("Bugün biraz yorgunum.", "Biraz dinlen o zaman."),
           ("Kahvemi yeni bitirdim.", "Afiyet olsun!"), ("Balkonda biraz oturdum.", "Hava almak iyi gelir.")]
SHOP_ITEMS = ["elma", "yumurta", "ekmek", "domates", "limon", "portakal", "yoğurt"]


def context4_turns(rng: random.Random):
    k = rng.randrange(3)
    ack = lambda: rng.choice(["Tamam, aklımda.", "Anladım.", "Not ettim kafama."])
    if k == 0:  # iki benzer bilgi, birini sor
        (e1, n1), (e2, n2) = rng.sample(EV_PLACES, 2)
        d1, d2 = rng.sample(DAYS, 2)
        turns = [(f"{_cap(n1)} {d1} günü, {n2} ise {d2} günü.", ack()), rng.choice(CTX_MID)]
        if rng.random() < 0.5:
            turns.append(rng.choice([m for m in CTX_MID if m != turns[1]]))
        pick = rng.random() < 0.5
        tgt, day, oth, oday = (n1, d1, n2, d2) if pick else (n2, d2, n1, d1)
        q = f"{_cap(tgt)} hangi gün demiştim?"
        a = _steps(rng, [f"iki şey söylemiştin: {n1} {d1}, {n2} {d2}", f"sorduğun {tgt}"], f"{tgt} {day} günü")
        return turns + [(q, a)], {"kind": "iki_bilgi", "pairs": [(n1, d1), (n2, d2)], "tgt": tgt, "ans": day}
    if k == 1:  # güncelleme: son söylenen geçerli
        h1, h2 = rng.sample(range(9, 18), 2)
        what = rng.choice(["Toplantı", "Ders", "Prova", "Antrenman"])
        turns = [(f"{what} yarın saat {h1}.00'de.", ack()),
                 (f"Pardon, değişti: {what.lower()} için yeni saat {h2}.00.", rng.choice(["Tamam, güncelledim kafamda.", "Anladım, yeni saat aklımda."])),
                 rng.choice(CTX_MID)]
        q = f"{what} yarın kaçtaydı?"
        a = _steps(rng, [f"ilk söylediğin saat {h1}.00", f"değişiklikle yeni saat {h2}.00 oldu"], f"geçerli saat {h2}.00")
        return turns + [(q, a)], {"kind": "guncel", "h1": h1, "h2": h2, "ans": f"{h2}.00"}
    # liste + ekleme + çeldirici → toplam
    (i1, i2, i3) = rng.sample(SHOP_ITEMS, 3)
    n1, n2, n3 = rng.randint(2, 9), rng.randint(2, 9), rng.randint(1, 6)
    turns = [(f"Market listesi: {n1} {i1}, {n2} {i2}.", ack()), rng.choice(CTX_MID),
             (f"Bir de {n3} {i3} ekle.", rng.choice(["Ekledim kafamdaki listeye.", "Tamam, listede."]))]
    if rng.random() < 0.5:
        q = f"Toplam kaç parça alacağım?"
        a = _steps(rng, [f"{n1} + {n2} + {n3} = {n1 + n2 + n3}"], f"toplam {n1 + n2 + n3} parça")
        ans = f"{n1 + n2 + n3} parça"
    else:
        q = f"Listede {i2} kaç taneydi?"
        a = _steps(rng, [f"listede {n1} {i1}, {n2} {i2} ve {n3} {i3} var"], f"{i2} {n2} tane")
        ans = f"{i2} {n2} tane"
    return turns + [(q, a)], {"kind": "liste", "n": [n1, n2, n3], "items": [i1, i2, i3], "q": q, "ans": ans}



# Tur 23: çok adımlı problemler ayrı kol; karşılaştırmaya üçlü sıralama, çelişki/kural/bağlama yeni türler eklendi.
# Tur 24: yedi yeni parametrik kol (sıralama, mantık, birim/zaman, plan, sayısal çelişki, kural aktarma, 4 tur bağlam);
# eski kollar toplam %40, yeniler %60.
WEIGHTS = {"karsilastirma": 0.06, "aritmetik": 0.08, "cok_adim": 0.06, "celiski": 0.07, "kural": 0.06, "baglam": 0.07,
           "siralama": 0.09, "mantik": 0.10, "birim": 0.10, "plan": 0.08, "celiski_sayi": 0.07, "aktarma": 0.08,
           "baglam4": 0.08}
_GEN = {"karsilastirma": compare_turns, "aritmetik": arithmetic_turns, "cok_adim": multistep_turns,
        "celiski": contradiction_turns, "kural": rule_turns, "baglam": context3_turns}
# meta döndüren yeni kollar: (turlar, meta)
_GEN_META = {"siralama": order_turns, "mantik": logic_turns, "birim": units_turns, "plan": plan_turns,
             "celiski_sayi": contra_num_turns, "aktarma": transfer_turns, "baglam4": context4_turns}


def reasoning_sample(rng: random.Random, category: str | None = None):
    """(kategori, turlar, meta); eski kollarda meta None. Testler meta girdilerinden sonucu yeniden hesaplar."""
    cat = category or rng.choices(list(WEIGHTS), weights=list(WEIGHTS.values()))[0]
    if cat in _GEN_META:
        turns, meta = _GEN_META[cat](rng)
        return cat, turns, meta
    return cat, _GEN[cat](rng), None


def reasoning_turns(rng: random.Random, category: str | None = None) -> tuple[str, list[tuple[str, str]]]:
    cat, turns, _ = reasoning_sample(rng, category)
    return cat, turns
