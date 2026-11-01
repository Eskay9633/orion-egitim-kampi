"""Düşünür yöntemleriyle problem çözme diyalogları (YALNIZCA eğitim; dialogs.MIX "thinkers" kolu).

Sahibinin yönü: şablon akıl yürütme ezberleniyor; Orion'un bir DÜŞÜNME BİÇİMİ olsun. Her diyalogda Orion bir
problemi sekiz yöntemden biriyle çözer ve ilhamını tek, kısa, rakamsız bir cümleyle anar. Yöntem tanımları genel
ve bilinen nitelemelerdir; biyografi, tarih, yer, eser adı ya da söz (alıntı) UYDURULMAZ ve kullanılmaz:
  Cezerî          — mekanizmayı parçalara ayır, her parçayı çöz, sonra birleştir
  İbn Sina        — gözle, belirtileri topla, olasılıkları ele, sonuca var
  Farabi          — terimleri tanımla; öncüller → çıkarım → sonuç
  Gazali          — şüphe et ve doğrula: "emin miyim, nasıl bilebilirim?"; varsayımları sına, belirsizliği kabul et
  Ali Kuşçu       — dikkatle ölç, problemi sayıya dök, hesabı gözlemle sına, veriye uyan en basit modeli seç
  Bîrûnî          — kaynakları/ölçümleri karşılaştır, çapraz denetle, bilinenden dolaylı ölç
  Hârezmî         — adım adım yordam; denklemde iki tarafı dengele, sadeleştir
  İbnü'l-Heysem   — varsayım kur, kontrollü dene, sonucu gözle, gerekirse düzelt; doğrulanmamış iddiaya kuşku
Sayılar üretilir, cevaplar kodla hesaplanır (yanlış cevap yok); her üretici meta döndürür, testler yeniden hesaplar.
Sağlık benzeri sorularda teşhis/ilaç/tedavi önerisi YOK: belirtiler toplanır, "doktora danış" denir.
Kullanıcı mesajları dialogs.persona_dialogues'ta near_exam / near_cogexam süzgecinden geçer.
"""
from __future__ import annotations

import math
import random

THINKERS = ["Cezerî", "İbn Sina", "Farabi", "Gazali", "Ali Kuşçu", "Bîrûnî", "Hârezmî", "İbnü'l-Heysem"]

# Yöntem cümleleri: rakam, tarih, alıntı yok; yalnız yöntem nitelemesi
INTRO = {
    "Cezerî": ["Cezerî'nin makinelere baktığı gibi bakalım: parçalara ayırıp her birini çözelim, sonra birleştirelim.",
               "Bunu Cezerî usulüyle yapalım: önce parçalar, sonra bütün.",
               "Cezerî gibi düşünüyorum: düzeneği parçalarına ayır, tek tek bak, sonra yeniden kur."],
    "İbn Sina": ["İbn Sina'nın yolunu izleyelim: önce gözlem, sonra belirtiler, sonra olasılıkları eleme.",
                 "İbn Sina gibi önce işaretleri toplayalım, sonra olmayanları eleyelim.",
                 "Burada İbn Sina usulü işe yarar: belirtileri topla, olasılıkları tek tek ele."],
    "Farabi": ["Farabi'nin yöntemiyle gidelim: önce terimleri netleştir, sonra öncüllerden sonuca git.",
               "Farabi gibi düşünelim: tanım, öncüller, çıkarım.",
               "Önce kavramları tanımlayalım, sonra öncüllerden sonuç çıkaralım; Farabi'nin sevdiği düzen bu."],
    "Gazali": ["Gazali gibi önce kendime soruyorum: emin miyim, bunu nasıl bilebilirim?",
               "Burada Gazali'nin şüphesiyle başlayalım: söyleneni hemen kabul etmeyip doğrulayalım.",
               "Gazali usulü: varsayımı sına, emin olmadığın yeri açıkça söyle."],
    "Ali Kuşçu": ["Ali Kuşçu gibi bir gökbilimci bakışıyla: ölçelim, sayıya dökelim, hesabı gözlemle sınayalım.",
                  "Bunu Ali Kuşçu usulüyle çözelim: dikkatli ölçüm, sade hesap, sonra gözlemle karşılaştırma.",
                  "Ali Kuşçu'nun yaklaşımı burada iyi gider: veriye uyan en basit modeli seç."],
    "Bîrûnî": ["Bîrûnî gibi tek kaynağa güvenmeyelim: ölçümleri yan yana koyup karşılaştıralım.",
               "Bîrûnî usulü: doğrudan ölçemediğini bildiğin şeylerden dolaylı ölç.",
               "Burada Bîrûnî'nin yolu uyar: kaynakları çapraz denetle, aykırı olanı ayır."],
    "Hârezmî": ["Hârezmî gibi adım adım bir yordam yazalım.",
                "Bunu Hârezmî usulüyle çözelim: iki tarafı dengele, sadeleştir.",
                "Hârezmî'nin cebir yolu: bilinmeyeni yalnız bırakana kadar iki tarafa aynı işlemi uygula."],
    "İbnü'l-Heysem": ["İbnü'l-Heysem gibi bir varsayım kurup onu deneyle sınayalım.",
                      "Burada İbnü'l-Heysem'in yolu işe yarar: varsayım, kontrollü deney, gözlem.",
                      "İbnü'l-Heysem usulü: doğrulanmamış iddiayı kabul etmeden önce sına."],
}
# Kullanıcı bazen yöntemi kendisi ister (çeşitlilik)
ASK = {"Cezerî": "Cezerî gibi parçalara ayırarak bakar mısın?", "İbn Sina": "İbn Sina gibi belirtilerden gidebilir misin?",
       "Farabi": "Farabi gibi adım adım akıl yürütür müsün?", "Gazali": "Gazali gibi biraz şüpheci bakar mısın?",
       "Ali Kuşçu": "Ali Kuşçu gibi ölçerek hesaplar mısın?", "Bîrûnî": "Bîrûnî gibi karşılaştırarak bakar mısın?",
       "Hârezmî": "Hârezmî gibi adım adım çözer misin?", "İbnü'l-Heysem": "İbnü'l-Heysem gibi deneyle sınar mısın?"}
EFENDIM_P = 0.08  # orion.json address.every = 5 → en fazla 1/5; burada daha seyrek
OPEN = ["", "", "Bakalım.", "Hemen bakalım.", "Güzel soru."]


def fmt(x: float) -> str:
    """Türkçe sayı: tamsa tam, değilse en çok iki ondalık, virgülle."""
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return f"{x:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _say(rng: random.Random, who: str, body: str, health: bool = False) -> str:
    """Açılış (seyrek "efendim") + yöntem cümlesi + gövde. Sağlık benzeri cevaplarda "efendim"/açılış yok."""
    op = "" if health else rng.choice(OPEN)
    if not health and rng.random() < EFENDIM_P:
        op = "Bakalım efendim."
    return " ".join(p for p in (op, rng.choice(INTRO[who]), body) if p)


def _q(rng: random.Random, who: str, q: str) -> str:
    return f"{q} {ASK[who]}" if rng.random() < 0.2 else q


# ------------------------------------------------------------------ Cezerî: parçalar → bütün (maliyet / plan)
PROJECTS = [("kitaplık", [("raf tahtası", "tane", (45, 120)), ("vida", "paket", (15, 40)), ("boya", "kutu", (90, 220))]),
            ("bahçe çiti", [("direk", "tane", (30, 80)), ("tel", "metre", (8, 20)), ("kapı menteşesi", "tane", (25, 60))]),
            ("kuş yuvası", [("kontrplak", "levha", (40, 90)), ("çivi", "kutu", (12, 30)), ("vernik", "şişe", (60, 140))]),
            ("akvaryum", [("cam", "levha", (70, 160)), ("silikon", "tüp", (35, 80)), ("filtre", "tane", (150, 400))])]


def cezeri_cost(rng: random.Random):
    proj, parts = rng.choice(PROJECTS)
    rows = []
    for name, unit, (lo, hi) in parts:
        rows.append((name, unit, rng.randint(1, 6) if unit != "metre" else rng.choice([10, 15, 20, 25]),
                     rng.randrange(lo, hi + 1, 5)))
    subs = [n * c for _, _, n, c in rows]
    tot = sum(subs)
    budget = rng.choice([None, round(tot * rng.uniform(0.8, 1.25) / 50) * 50])
    lst = ", ".join(f"{n} {u} {name} ({u} başı {c} lira)" for name, u, n, c in rows)
    q = f"Bir {proj} yapacağım. Gerekenler: {lst}." + (f" Bütçem {budget} lira, yeter mi?" if budget else " Toplam ne tutar?")
    body = " ".join(f"{name.capitalize()}: {n} × {c} = {s} lira." for (name, _, n, c), s in zip(rows, subs))
    body += f" Birleştirince {' + '.join(map(str, subs))} = {tot} lira."
    if budget:
        body += (f" Bütçen {budget} lira; {budget - tot} lira artar, yeter." if budget >= tot
                 else f" Bütçen {budget} lira; {tot - budget} lira eksik kalır, yetmez.")
    return [(_q(rng, "Cezerî", q), _say(rng, "Cezerî", body))], {"kind": "maliyet", "rows": rows, "tot": tot, "budget": budget}


MORNING = [("kahvaltı", (10, 30)), ("duş", (8, 20)), ("giyinmek", (5, 15)), ("çantayı hazırlamak", (5, 12))]


def cezeri_plan(rng: random.Random):
    tasks = [(t, rng.randrange(lo, hi + 1, 5) if hi >= 15 else rng.randint(lo, hi)) for t, (lo, hi) in rng.sample(MORNING, 3)]
    road = rng.choice([20, 25, 30, 35, 40, 45])
    arrive = rng.choice([8 * 60, 8 * 60 + 30, 9 * 60, 9 * 60 + 30, 10 * 60])
    tot = sum(d for _, d in tasks) + road
    wake = arrive - tot
    hm = lambda t: f"{t // 60}.{t % 60:02d}"  # noqa: E731
    lst = ", ".join(f"{t} {d} dakika" for t, d in tasks)
    q = f"İşe varış saatim {hm(arrive)}. Sabah {lst} sürüyor, yol da {road} dakika. En geç kaçta kalkmalıyım?"
    body = (f"Parçalar: {' + '.join(str(d) for _, d in tasks)} = {tot - road} dakika hazırlık, {road} dakika yol; "
            f"toplam {tot} dakika. Varış saatinden {tot} dakika geri gidince kalkış saatin en geç {hm(wake)}. "
            f"Birkaç dakika pay bırakmak iyi olur.")
    return [(_q(rng, "Cezerî", q), _say(rng, "Cezerî", body))], {"kind": "plan", "tot": tot, "wake": wake}


# ------------------------------------------------------------------ Cezerî / İbn Sina: arızayı parçalara ayır, ele
# (alet, [(parça, sağlam olduğunu gösteren gözlem, öneri)])
DEVICES = [
    ("masa lambası", [("priz", "aynı prize taktığım şarj aleti çalışıyor", "prizi kontrol ettir"),
                      ("kablo", "kabloda ezik ya da kopukluk yok", "kabloyu değiştir"),
                      ("düğme", "düğme tık diye yerine oturuyor ve başka lambada aynı tip düğme sorunsuz", "düğmeyi değiştir"),
                      ("ampul", "ampulü başka lambaya taktım, yandı", "ampulü değiştir")]),
    ("bisiklet", [("zincir", "zinciri yağladım, ses kesilmedi", "zinciri temizleyip yağla"),
                  ("pedal", "pedalları elle çevirince boşluk yok", "pedal yataklarını kontrol et"),
                  ("fren", "frene basmadan da ses geliyor", "fren pabuçlarını ayarla"),
                  ("vites", "vitesi değiştirince ses değişmiyor", "vites ayarını yaptır")]),
    ("kablosuz kulaklık", [("şarj", "şarjı tam dolu görünüyor", "kulaklığı tam şarj et"),
                           ("bluetooth", "telefonla bağlantı kuruluyor", "eşleştirmeyi silip yeniden eşleştir"),
                           ("ses ayarı", "telefonun sesi sonuna kadar açık", "ses ayarlarına bak"),
                           ("kulak ucu", "kulak uçlarını temizledim", "kulak uçlarını temizle")]),
    ("su ısıtıcısı", [("priz", "aynı prizde tost makinesi çalışıyor", "prizi kontrol ettir"),
                      ("taban", "ısıtıcı tabanına düzgün oturuyor", "tabanı temizle"),
                      ("su seviyesi", "içinde yeterince su var", "en az çizgisine kadar su koy"),
                      ("düğme", "düğmeye basınca ışığı yanıyor", "düğmeyi servise göster")]),
]


def fault_turns(rng: random.Random):
    who = rng.choice(["Cezerî", "İbn Sina"])
    dev, parts = rng.choice(DEVICES)
    bad = rng.randrange(len(parts))
    obs = [p for i, p in enumerate(parts) if i != bad]
    rng.shuffle(obs)
    sym = {"masa lambası": "yanmıyor", "bisiklet": "giderken tıkırdıyor", "kablosuz kulaklık": "ses vermiyor",
           "su ısıtıcısı": "ısıtmıyor"}[dev]
    q = f"{dev.capitalize()} {sym}. Şunlara baktım: " + "; ".join(o for _, o, _ in obs) + ". Sorun nerede olabilir?"
    names = ", ".join(p for p, _, _ in parts)
    elim = ", ".join(p for p, _, _ in obs)
    part, _, fix = parts[bad]
    body = (f"Olası parçalar: {names}. Gözlemlerin {elim} için sorun olmadığını gösteriyor. "
            f"Geriye {part} kalıyor; en olası sorun orada. Önce {fix}"
            + ("; elektrikli aletse önce fişini çek." if dev in ("masa lambası", "su ısıtıcısı") else ".")
            + " Düzelmezse yeniden bakarız.")
    return [(_q(rng, who, q), _say(rng, who, body))], {"kind": "ariza", "answer": part}


# ------------------------------------------------------------------ İbn Sina: kayıp eşya (ele)
PLACES = [("mutfak tezgâhı", "mutfak tezgâhına"), ("montun cebi", "montun cebine"),
          ("arabanın torpidosu", "arabanın torpidosuna"), ("kapının yanındaki sepet", "kapının yanındaki sepete"),
          ("çalışma masası", "çalışma masasına"), ("çantanın ön gözü", "çantanın ön gözüne"),
          ("koltuğun arası", "koltuğun arasına")]
LOST = ["anahtarlarımı", "gözlüğümü", "cüzdanımı", "kulaklığımı"]


def lost_turns(rng: random.Random):
    places = rng.sample(PLACES, rng.randint(3, 4))
    left = rng.choice(places)
    checked = [p for p in places if p != left]
    item = rng.choice(LOST)
    nom = [p for p, _ in places]
    q = (f"{item.capitalize()} bulamıyorum. Genelde şuralarda olur: {', '.join(nom[:-1])} ya da {nom[-1]}. "
         f"{', '.join(d for _, d in checked).capitalize()} baktım, yok. Neresi kaldı?")
    body = (f"Olasılıklar: {', '.join(nom)}. Baktığın yerler elendi: {', '.join(p for p, _ in checked)}. "
            f"Geriye {left[0]} kalıyor; önce oraya bak. Orada da yoksa en son nerede kullandığını birlikte düşünelim.")
    return [(_q(rng, "İbn Sina", q), _say(rng, "İbn Sina", body))], {"kind": "kayip", "answer": left[0]}


# ------------------------------------------------------------------ İbn Sina: sağlık benzeri (teşhis/ilaç YOK)
SIGNS = [("başım ağrıyor", "başın ağrıyor", ["öğleden sonraları oluyor", "gün boyu ekrana bakıyorum", "az su içtim", "uykum düzensiz"]),
         ("midem rahatsız", "miden rahatsız", ["yemekten sonra oluyor", "son günlerde çok kahve içtim", "akşam geç yiyorum"]),
         ("gözlerim yoruluyor", "gözlerin yoruluyor", ["akşamları artıyor", "telefona çok bakıyorum", "ışık loş bir odada çalışıyorum"]),
         ("sırtım tutuluyor", "sırtın tutuluyor", ["uzun süre oturuyorum", "sandalyem alçak", "sabahları daha hafif"])]


def health_turns(rng: random.Random):
    comp, comp2, signs = rng.choice(SIGNS)
    days = rng.randint(2, 6)
    got = rng.sample(signs, rng.randint(2, len(signs)))
    q = f"{days} gündür {comp}. {', '.join(got).capitalize()}. Sence neden olabilir?"
    body = (f"Belirtileri topluyorum: {days} gündür {comp2} ve bana {len(got)} ipucu verdin. Bunlar not edilmeye değer ipuçları, "
            f"ama teşhis koyamam; nedeni ancak bir hekim muayeneyle söyleyebilir. Geçmezse, artarsa ya da başka bir "
            f"belirti eklenirse doktora danış. Ne zaman başladığını ve neyle değiştiğini bir yere yazarsan doktora "
            f"anlatırken işine yarar.")
    return [(q, _say(rng, "İbn Sina", body, health=True))], {"kind": "saglik"}


# ------------------------------------------------------------------ Farabi: tanım → öncüller → çıkarım
DAYS = ["pazartesi", "salı", "çarşamba", "perşembe", "cuma", "cumartesi", "pazar"]
PLACES_RULE = ["kütüphane", "semt pazarı", "yüzme havuzu", "müze", "kırtasiye"]
# (tekil, çoğul, özellik, özellik soru eki, örnek, tekil soru eki)
CLASSES = [("kuş", "kuşlar", "kanatlı", "mı", "Pamuk", "mu"), ("arı", "arılar", "böcek", "mi", "Vızvız", "mi"),
           ("memeli", "memeliler", "omurgalı", "mı", "Karabaş", "mi"),
           ("metal", "metaller", "iletken", "mi", "bu bakır tel", "mi"),
           ("sürüngen", "sürüngenler", "soğukkanlı", "mı", "bu kertenkele", "mi")]


def farabi_turns(rng: random.Random):
    k = rng.randrange(3)
    if k == 0:
        place = rng.choice(PLACES_RULE)
        closed = sorted(rng.sample(range(7), 2))
        day = rng.randrange(7)
        cl = " ve ".join(DAYS[i] for i in closed)
        q = f"{place.capitalize()} {cl} günleri kapalı. Bugün {DAYS[day]}. Gidebilir miyim?"
        open_ = day not in closed
        body = (f"Terim: kapalı gün = {cl}. Öncül bir: {place} {cl} kapalı. Öncül iki: bugün {DAYS[day]}. "
                + (f"Çıkarım: {DAYS[day]} kapalı günlerden biri değil, yani gidebilirsin." if open_
                   else f"Çıkarım: {DAYS[day]} kapalı günlerden biri, yani bugün gitme; başka bir gün dene."))
        return [(_q(rng, "Farabi", q), _say(rng, "Farabi", body))], {"kind": "kural", "open": open_}
    sing, plur, prop, pq, x, sq = rng.choice(CLASSES)
    if k == 1:  # geçerli çıkarım
        q = f"Bütün {plur} {prop}. {x.capitalize()} bir {sing}. {x.capitalize()} {prop} {pq}?"
        body = (f"Öncül bir: bütün {plur} {prop}. Öncül iki: {x} bir {sing}. Çıkarım: {x} {plur} kümesinde, "
                f"o kümedeki her şey {prop}; yani evet, {x} {prop}.")
        return [(_q(rng, "Farabi", q), _say(rng, "Farabi", body))], {"kind": "kiyas", "valid": True}
    # geçersiz: sonucu tersinden okumak
    q = f"Bütün {plur} {prop}. {x.capitalize()} {prop}. O zaman {x} bir {sing} {sq}?"
    body = (f"Öncül bir: bütün {plur} {prop}; ama bu, her {prop} şeyin {sing} olduğunu söylemez. Öncül iki: {x} {prop}. "
            f"Çıkarım: bu iki öncülden {x} için kesin bir sonuç çıkmaz; başka bilgi gerekir.")
    return [(_q(rng, "Farabi", q), _say(rng, "Farabi", body))], {"kind": "kiyas", "valid": False}


# ------------------------------------------------------------------ Gazali: şüphe et, doğrula
ITEMS = ["mont", "ayakkabı", "kulaklık", "sırt çantası", "masa lambası", "tencere seti"]


def gazali_turns(rng: random.Random):
    if rng.random() < 0.55:  # indirim iddiası
        old = rng.choice([400, 500, 600, 750, 800, 1000, 1200])
        claim = rng.choice([30, 40, 50, 60])
        real = rng.choice([p for p in (10, 15, 20, 25, 30, 40, 50) if p != claim])
        new = old * (100 - real) // 100
        item = rng.choice(ITEMS)
        q = (f"Bir {item} için \"yüzde {claim} indirim\" yazıyor. Eski fiyatı {old} lira, şimdi {new} lira. "
             f"Kaçırmadan hemen alayım mı?")
        pct = (old - new) * 100 / old
        ok = abs(pct - claim) < 0.5
        body = (f"Hesaplayalım: {old} − {new} = {old - new} lira indirim; {old - new} ÷ {old} = yüzde {fmt(pct)}. "
                + ("Yazılan indirim doğru. " if ok else f"Yani yazılan yüzde {claim} değil, gerçek indirim yüzde {fmt(pct)}. ")
                + f"Eski fiyatın gerçekten {old} lira olduğunu ise buradan bilemem; emin değilim. "
                  f"Fiyat geçmişine ya da başka satıcılara bakıp öyle karar ver; acele ettiren indirim çoğu zaman acele "
                  f"ettirmek içindir.")
        return [(_q(rng, "Gazali", q), _say(rng, "Gazali", body))], {"kind": "indirim", "pct": pct, "ok": ok}
    # "büyük paket daha ucuz" iddiası
    small_g, big_g = rng.choice([(250, 1000), (500, 1500), (500, 2000), (400, 1200)])
    small_p = rng.choice([20, 24, 30, 36, 40])
    unit_small = small_p * 1000 / small_g
    factor = rng.choice([0.85, 0.9, 1.05, 1.1, 1.2])
    big_p = round(unit_small * factor * big_g / 1000)
    unit_big = big_p * 1000 / big_g
    item = rng.choice(["pirinç", "kahve", "deterjan", "un", "mercimek"])
    q = (f"Herkes büyük paket daha ucuz der. {item.capitalize()}: {small_g} gram {small_p} lira, {big_g} gram {big_p} lira. "
         f"Büyüğü mü alayım?")
    cheaper_big = unit_big < unit_small
    body = (f"Söylenene değil hesaba bakalım: küçük paketin kilosu {small_p} × 1000 ÷ {small_g} = {fmt(unit_small)} lira, "
            f"büyüğünki {big_p} × 1000 ÷ {big_g} = {fmt(unit_big)} lira. "
            + (f"Bu sefer gerçekten büyük paket ucuz. " if cheaper_big else "Bu sefer küçük paket daha ucuz; genel kanı burada tutmuyor. ")
            + "Yine de bitiremeyeceksen büyük paket israf olur; ne kadar kullandığını sen bilirsin.")
    return [(_q(rng, "Gazali", q), _say(rng, "Gazali", body))], {"kind": "birim_fiyat", "big_cheaper": cheaper_big,
                                                                     "u_small": unit_small, "u_big": unit_big}


# ------------------------------------------------------------------ Ali Kuşçu: ölç, sayıya dök, gözlemle sına
def kuscu_turns(rng: random.Random):
    k = rng.randrange(3)
    if k == 0:  # boya hesabı
        w, h = rng.choice([3, 3.5, 4, 4.5, 5]), rng.choice([2.5, 2.6, 2.8, 3])
        walls = rng.choice([2, 3, 4])
        door = rng.choice([0, 2, 3])
        cover = rng.choice([8, 10, 12])
        area = w * h * walls - door
        litres = math.ceil(area / cover - 1e-9)
        q = (f"{walls} duvar boyayacağım; her biri {fmt(w)} metre en, {fmt(h)} metre yükseklikte."
             + (f" Kapı ve pencere toplam {door} metrekare." if door else "")
             + f" Bir litre boya {cover} metrekareye yetiyormuş. Kaç litre almalıyım?")
        body = (f"Ölçüleri sayıya dökelim: bir duvar {fmt(w)} × {fmt(h)} = {fmt(w * h)} metrekare, {walls} duvar "
                f"{fmt(w * h * walls)} metrekare" + (f"; kapı ve pencereyi düşünce {fmt(area)} metrekare" if door else "")
                + f". {fmt(area)} ÷ {cover} = {fmt(area / cover)}; yani en az {litres} litre (tek kat). "
                f"İlk duvarı boyayınca ne kadar gittiğine bak; hesap gözlemle uyuyorsa devam.")
        return [(_q(rng, "Ali Kuşçu", q), _say(rng, "Ali Kuşçu", body))], {"kind": "boya", "area": area, "litres": litres}
    if k == 1:  # adımla ölçme
        step = rng.choice([60, 65, 70, 75, 80])
        n = rng.choice([400, 600, 800, 1000, 1200, 1500])
        q = (f"Bir adımım yaklaşık {step} santimetre. Parkın çevresini yürüdüm, {n} adım tuttu. Çevresi kaç metre eder?")
        m = step * n / 100
        body = (f"{n} × {step} = {n * step} santimetre; 100'e bölünce {fmt(m)} metre. Adım boyu tam sabit değildir, "
                f"o yüzden bu bir tahmin; bir kez de bilinen bir mesafede adımlarını sayarsan ölçünü düzeltirsin.")
        return [(_q(rng, "Ali Kuşçu", q), _say(rng, "Ali Kuşçu", body))], {"kind": "adim", "m": m}
    # büyüme: veriye uyan en basit model (doğrusal)
    v0, d = rng.randint(3, 15), rng.choice([1, 2, 3])
    later = rng.choice([3, 4, 5, 7])
    plant = rng.choice(["fasulye fidesi", "nane", "domates fidesi", "ayçiçeği"])
    vals = [v0 + i * d for i in range(3)]
    pred = vals[-1] + later * d
    q = (f"Saksıdaki {plant} için üç gün üst üste boy ölçtüm: {vals[0]}, {vals[1]}, {vals[2]} santimetre. "
         f"Böyle giderse {later} gün sonra kaç santimetre olur?")
    body = (f"Farklara bakalım: {vals[1]} − {vals[0]} = {d}, {vals[2]} − {vals[1]} = {d}. Veriye uyan en basit model: "
            f"her gün {d} santimetre. {vals[2]} + {later} × {d} = {pred} santimetre. Bitkiler hep aynı hızda büyümez; "
            f"birkaç gün sonra yeniden ölçüp modeli sına.")
    return [(_q(rng, "Ali Kuşçu", q), _say(rng, "Ali Kuşçu", body))], {"kind": "buyume", "pred": pred}


# ------------------------------------------------------------------ Bîrûnî: dolaylı ölçüm, çapraz denetim
def biruni_turns(rng: random.Random):
    if rng.random() < 0.5:  # gölgeyle yükseklik (benzer üçgenler)
        me = rng.choice([150, 160, 170, 175, 180])
        my_sh = rng.choice([100, 120, 150, 200])
        ratio = rng.choice([3, 4, 5, 6, 8])
        tree_sh = my_sh * ratio
        thing, gen = rng.choice([("ağaç", "ağacın"), ("direk", "direğin"), ("bina", "binanın"), ("minare", "minarenin")])
        h = me * ratio
        q = (f"Boyum {me} santimetre, gölgem {my_sh} santimetre. Aynı anda {gen} gölgesi {fmt(tree_sh / 100)} metre. "
             f"{thing.capitalize()} ne kadar yüksek?")
        body = (f"Aynı anda güneş ışığı ikimize de aynı açıyla düşer, o yüzden boy ile gölge orantılı. "
                f"Gölgesi seninkinin {fmt(tree_sh / 100)} m ÷ {fmt(my_sh / 100)} m = {ratio} katı; yüksekliği de "
                f"{me} × {ratio} = {h} santimetre, yani {fmt(h / 100)} metre. Zemin eğimliyse sonuç biraz sapar.")
        return [(_q(rng, "Bîrûnî", q), _say(rng, "Bîrûnî", body))], {"kind": "golge", "h": h}
    base = rng.choice([12, 18, 24, 30, 36])
    a, b = base, base + rng.choice([0, 1])
    out = base + rng.choice([7, 9, 12, -6])
    src = rng.sample(["harita uygulaması", "arabanın göstergesi", "yol tabelası", "arkadaşımın uygulaması"], 3)
    vals = [a, b, out]
    order = list(range(3))
    rng.shuffle(order)
    lst = ", ".join(f"{src[i]} {vals[i]}" for i in order)
    avg = (a + b) / 2
    q = f"Eve olan mesafe için üç farklı şey söylüyor: {lst} kilometre. Hangisine güveneyim?"
    body = (f"Üç ölçümü yan yana koyalım: {a} ile {b} birbirine yakın, {out} ötekilerden {fmt(abs(out - avg))} kilometre kadar "
            f"ayrık. İki bağımsız kaynak uyuşuyor; aykırı olanı ayırıp ortalarını alırsak {fmt(avg)} kilometre. "
            f"Aykırı kaynak farklı bir rota hesaplıyor da olabilir; ona ayrıca bak.")
    return [(_q(rng, "Bîrûnî", q), _say(rng, "Bîrûnî", body))], {"kind": "capraz", "avg": avg, "outlier": out}


# ------------------------------------------------------------------ Hârezmî: denklem, iki tarafı dengele
# (ad, ilgi hâli, bulunma hâli) çiftleri
PAIRS = [(("Ece", "Ece'nin", "Ece'de"), ("Bora", "Bora'nın", "Bora'da")),
         (("Selin", "Selin'in", "Selin'de"), ("Mert", "Mert'in", "Mert'te")),
         (("Deniz", "Deniz'in", "Deniz'de"), ("Arda", "Arda'nın", "Arda'da")),
         (("Nil", "Nil'in", "Nil'de"), ("Kerem", "Kerem'in", "Kerem'de"))]
_DAT1 = {1: "e", 2: "ye", 3: "e", 4: "e", 5: "e", 6: "ya", 7: "ye", 8: "e", 9: "a"}
_DAT10 = {10: "a", 20: "ye", 30: "a", 40: "a", 50: "ye", 60: "a", 70: "e", 80: "e", 90: "a"}


def dat(n: int) -> str:
    """Sayıya yönelme eki: 2'ye, 3'e, 6'ya, 9'a, 10'a."""
    return f"{n}'" + (_DAT1[n % 10] if n % 10 else _DAT10[n % 100] if n % 100 else "e")


def harezmi_turns(rng: random.Random):
    k = rng.randrange(3)
    if k == 0:  # ax + b = c
        a, x, b = rng.randint(2, 9), rng.randint(3, 25), rng.randint(1, 40)
        c = a * x + b
        q = f"Bir sayının {a} katının {b} fazlası {c} ediyor. Sayı kaç?"
        body = (f"Sayıya x diyelim: {a}x + {b} = {c}. İki taraftan {b} çıkar: {a}x = {c - b}. "
                f"İki tarafı {dat(a)} böl: x = {x}. Sınayalım: {a} × {x} + {b} = {c}, tutuyor.")
        return [(_q(rng, "Hârezmî", q), _say(rng, "Hârezmî", body))], {"kind": "denklem", "x": x}
    (n1, g1, l1), (n2, g2, l2) = rng.choice(PAIRS)
    if k == 1:  # oranla paylaşma
        m, x = rng.choice([2, 3, 4]), rng.choice([20, 30, 40, 50, 60, 75])
        tot = x * (m + 1)
        q = f"{g1} parası {g2} parasının {m} katı. İkisinin toplamı {tot} lira. Kimde ne kadar var?"
        body = (f"{g2} parasına x diyelim; {l1} {m}x var. x + {m}x = {tot}, yani {m + 1}x = {tot}. "
                f"İki tarafı {dat(m + 1)} böl: x = {x}. {l2} {x}, {l1} {m} × {x} = {m * x} lira. "
                f"Sınama: {x} + {m * x} = {tot}.")
        return [(_q(rng, "Hârezmî", q), _say(rng, "Hârezmî", body))], {"kind": "pay", "x": x, "y": m * x}
    # iki taraflı: ax + b = cx + d
    x = rng.randint(2, 15)
    c = rng.randint(1, 4)
    a = c + rng.randint(2, 5)
    b = rng.randint(1, 20)
    d = (a - c) * x + b
    cx = "x" if c == 1 else f"{c}x"
    q = f"{a}x + {b} = {cx} + {d} denkleminde x kaç?"
    body = (f"Bilinmeyenleri bir yana toplayalım: iki taraftan {cx} çıkar, {a - c}x + {b} = {d}. "
            f"İki taraftan {b} çıkar: {a - c}x = {d - b}. İki tarafı {dat(a - c)} böl: x = {x}. "
            f"Sınama: {a} × {x} + {b} = {a * x + b}, {c} × {x} + {d} = {c * x + d}; eşit.")
    return [(_q(rng, "Hârezmî", q), _say(rng, "Hârezmî", body))], {"kind": "denklem2", "x": x}


# ------------------------------------------------------------------ İbnü'l-Heysem: varsayım, kontrollü deney
CLAIMS = [("şarjı gece boyu takılı bırakmak pili daha hızlı bitiriyor", "günlük pil tüketimi", "yüzde"),
          ("telefonu uçak modunda şarj etmek daha hızlı dolduruyor", "yarım saatte dolan şarj", "yüzde"),
          ("modemi yükseğe koymak interneti hızlandırıyor", "ölçülen hız", "megabit"),
          ("ekran parlaklığını düşürmek pili gün sonuna kadar yetiriyor", "akşam kalan şarj", "yüzde"),
          ("telefonu serin bir odada şarj etmek daha hızlı dolduruyor", "yarım saatte dolan şarj", "yüzde"),
          ("bitkiyi sabah sulamak akşam sulamaktan daha iyi büyütüyor", "haftalık boy artışı", "santimetre")]


def heysem_turns(rng: random.Random):
    if rng.random() < 0.5:  # ölçülmüş iki durum: ortalamaları karşılaştır
        base = rng.randint(5, 30)
        boost = rng.choice([0, 1, 10, 15, 25])
        g1 = [base + rng.choice([-1, 0, 1]) for _ in range(3)]
        g2 = [v + boost + rng.choice([-1, 0, 1]) for v in g1]
        m1, m2 = sum(g1) / 3, sum(g2) / 3
        diff = m2 - m1
        real = abs(diff) >= 5
        q = (f"İnternetim odamda yavaş. Odada üç ölçüm: {', '.join(map(str, g1))} megabit. Modemin yanında: "
             f"{', '.join(map(str, g2))} megabit. Sorun uzaklık mı?")
        body = (f"Varsayım: hız modeme uzaklıktan düşüyor. Deneyin iki durumu var; ortalamalar: odada "
                f"({' + '.join(map(str, g1))}) ÷ 3 = {fmt(m1)}, modemin yanında ({' + '.join(map(str, g2))}) ÷ 3 = {fmt(m2)} megabit. "
                + (f"Fark {fmt(diff)} megabit, ölçüm oynamasından çok büyük; varsayım destekleniyor. Modemi yaklaştırmayı "
                   f"ya da bir sinyal güçlendiriciyi dene." if real else
                   f"Fark yalnız {fmt(abs(diff))} megabit, ölçüm oynaması kadar; uzaklık varsayımı tutmadı. Sıradaki "
                   f"varsayım: hattın kendisi ya da aynı anda bağlı cihazlar; tek tek dene."))
        return [(_q(rng, "İbnü'l-Heysem", q), _say(rng, "İbnü'l-Heysem", body))], {"kind": "olcum", "m1": m1, "m2": m2,
                                                                                    "real": real}
    claim, measure, unit = rng.choice(CLAIMS)
    days = rng.choice([5, 7, 10])
    q = f"Biri {claim} dedi. Doğru mu?"
    body = (f"Bunu doğrulanmış bilgi sayamam; önce sınayalım. Varsayım: {claim}. Deney: {days} gün eski alışkanlıkla, "
            f"{days} gün yeni yöntemle; başka hiçbir şeyi değiştirmeden her gün {measure} değerini {unit} olarak yaz. "
            f"Sonra iki dönemin ortalamasını karşılaştır; fark küçükse iddia bu deneyle doğrulanmadı demektir. "
            f"İstersen sonuçları birlikte yorumlarız.")
    return [(_q(rng, "İbnü'l-Heysem", q), _say(rng, "İbnü'l-Heysem", body))], {"kind": "iddia"}


# ------------------------------------------------------------------ kol
# kategori → (üretici, yöntem(ler)); ağırlıklar sekiz adı dengeli dağıtır (yaklaşık her biri %11–14)
_GEN = {"cezeri_maliyet": cezeri_cost, "cezeri_plan": cezeri_plan, "ariza": fault_turns, "kayip": lost_turns,
        "saglik": health_turns, "farabi": farabi_turns, "gazali": gazali_turns, "kuscu": kuscu_turns,
        "biruni": biruni_turns, "harezmi": harezmi_turns, "heysem": heysem_turns}
WEIGHTS = {"cezeri_maliyet": 0.07, "cezeri_plan": 0.04, "ariza": 0.09, "kayip": 0.04, "saglik": 0.04, "farabi": 0.12,
           "gazali": 0.12, "kuscu": 0.12, "biruni": 0.12, "harezmi": 0.12, "heysem": 0.12}


def thinker_of(answer: str) -> str | None:
    return next((t for t in THINKERS if t in answer), None)


def thinker_sample(rng: random.Random, category: str | None = None):
    """(kategori, turlar, meta)."""
    cat = category or rng.choices(list(WEIGHTS), weights=list(WEIGHTS.values()))[0]
    turns, meta = _GEN[cat](rng)
    return cat, turns, meta


def thinker_turns(rng: random.Random, category: str | None = None) -> tuple[str, list[tuple[str, str]]]:
    cat, turns, _ = thinker_sample(rng, category)
    return cat, turns
