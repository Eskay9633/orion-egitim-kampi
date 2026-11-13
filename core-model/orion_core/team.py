"""Ekip diyalogları (2026-11-14, sahibin isteği: Kaggle'a yeni veri): Orion'un 13 ajanlık ekibini tanıması.

Kaynak tek: shared/self/ajanlar.json (ad, rol, alt ajanlar, komutlar). Kotlin tarafı aynı dosyayı okur; ekip
değişince veri de kendiliğinden değişir. Cevaplar Orion'un kendi sesiyle ve kısa; kullanıcı verisi YOK (halka açık
depoda eğitilir). Soru biçimleri ekler gerektirmeyecek şekilde yazıldı ("Grace ne iş yapar?"): ses uyumu hatası olmasın.
"""
from __future__ import annotations

import json
import random
from functools import lru_cache
from pathlib import Path

AGENTS_PATH = Path(__file__).resolve().parents[2] / "shared" / "self" / "ajanlar.json"

# Komut → (iş adı, örnek cümle). "ask" ve "help" her ajanda var; ayırt edici değil, kullanılmaz.
CMD = {
    "reminder.set": ("hatırlatıcı kurmak", "yarın 10'da toplantı hatırlat"),
    "reminder.list": ("hatırlatıcılara bakmak", "hatırlatıcılarımı göster"),
    "calendar.add": ("takvime etkinlik eklemek", "cuma 14:00 takvime dişçi ekle"),
    "calendar.list": ("takvime bakmak", "yarın takvimde ne var"),
    "timer.start": ("zamanlayıcı kurmak", "10 dakikalık zamanlayıcı kur"),
    "mail.check": ("e-postalara bakmak", "yeni maillerime bak"),
    "mail.send": ("e-posta taslağı hazırlamak", "Ali'ye mail yaz: toplantı ertelendi"),
    "note.write": ("not almak", "not al: süt ve ekmek"),
    "note.search": ("notlarda arama yapmak", "notlarımda bütçe ara"),
    "research.start": ("araştırma yapmak", "güneş panelleri hakkında araştırma yap"),
    "provider.discover": ("yeni ücretsiz yapay zeka bulmak", "yeni ücretsiz yapay zeka bul"),
    "text.translate": ("çeviri yapmak", "İngilizceye çevir: günaydın"),
    "image.generate": ("resim çizmek", "resim oluştur: gün batımında İstanbul"),
    "image.analyze": ("fotoğraftaki yazıyı okumak", "ekran görüntüsündeki sorunu çöz"),
    "card.propose": ("ana sayfaya kart önermek", "grafik kartı ekle: haftalık harcama"),
    "repo.audit": ("bir GitHub deposunu denetlemek", "signal-bot reposunu denetle"),
    "calc.eval": ("hesap yapmak", "250'nin yüzde 18'i kaç"),
    "health.check": ("telefonun sağlığına bakmak", "telefonun sağlığını kontrol et"),
    "market.crypto": ("kripto piyasasına bakmak", "bugün kripto piyasası nasıl"),
    "market.alert": ("kripto fiyat alarmı kurmak", "bitcoin 100 bin dolara çıkınca haber ver"),
    "code.run": ("kod yazıp kapalı kutuda çalıştırmak", "kod yaz: 1'den 100'e kadar asal sayıları bul"),
    "code.repo": ("bir depoda değişiklik hazırlamak", "signal-bot README dosyasındaki kurulum adımını düzelt"),
    "work.check": ("yapılan işi denetlemek", "bunu kontrol et"),
    "skill.learn": ("yeni beceri tasarlamak", "beceri öğren: her sabah kripto ve takvimi özetle"),
    "skill.run": ("beceri çalıştırmak", "sabah rutini becerisini çalıştır"),
    "agent.hire": ("ekibe yardımcı ajan eklemek", "Sophia'ya yardımcı ajan ekle: kaynak doğrulayan"),
    "self.status": ("gelişim durumuna bakmak", "gelişim durumu"),
    "self.advise": ("Orion'un nasıl gelişeceğini düşünmek", "Orion'u nasıl geliştirebiliriz"),
    "app.open": ("uygulama açmak", "YouTube'da lofi müzik ara"),
    "memory.save": ("kalıcı hafızaya kaydetmek", "bunu hatırla: raporlar kısa olsun"),
}
_GENERIC = {"ask", "help"}


@lru_cache(maxsize=1)
def agents() -> list[dict]:
    return json.loads(AGENTS_PATH.read_text(encoding="utf-8"))["agents"]


def _jobs(a: dict) -> list[str]:
    return [c for c in a.get("commands", []) if c not in _GENERIC and c in CMD]


def _and(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " ve " + xs[-1]


ABOUT_Q = ["{n} kim?", "{n} ne iş yapar?", "Ekipte {n} ne yapıyor?", "{n} hangi işlere bakıyor?", "Bana {n} hakkında bilgi ver.",
           "{n} ne işe yarar?", "{n} senin ekibinde mi?", "{n} neyle ilgileniyor?"]
TEAM_Q = ["Ekibinde kimler var?", "Ekibini tanıtır mısın?", "Kaç ajanın var?", "Yardımcı ajanların kimler?", "Ekibin kaç kişi?",
          "Seninle kimler çalışıyor?", "Ajanlarını sayar mısın?"]
WHO_Q = ["{job} işine kim bakıyor?", "{job} için hangi ajan çalışıyor?", "Ekipte {job} işini kim yapar?",
         "{job} işini hangi ajana verirsin?"]
CHECK_Q = ["Yaptığın işi kim kontrol ediyor?", "Kodları kim denetliyor?", "İşin doğru olduğunu nereden bileceğim?",
           "Denetçilerin kimler?", "Hata yaparsan kim yakalar?"]
SUB_Q = ["{n} tek başına mı çalışıyor?", "{n} alt ajanları var mı?", "{n} yanında kimler var?"]


def about(a: dict, rng: random.Random) -> str:
    jobs = _jobs(a)
    s = f"{a['name']} ekibimde {a['role']} olarak çalışır."
    if jobs:
        s += f" {_and([CMD[c][0] for c in jobs[:3]]).capitalize()} onun işi."
        s += f" Örneğin \"{CMD[rng.choice(jobs)][1]}\" dersen {a['name']} devreye girer."
    return s


def team_turns(rng: random.Random) -> tuple[str, list[tuple[str, str]]]:
    """(kategori, [(kullanıcı, Orion), ...]). Kategoriler: ekip_tanit, ekip_ajan, ekip_is, ekip_denetim, ekip_alt."""
    ags = agents()
    r = rng.random()
    if r < 0.15:
        names = [f"{a['name']} ({a['role']})" for a in ags]
        a = (f"Ekibimde {len(ags)} ajan var: " + _and(names) + ". İşi kim yapacaksa ona veririm; "
             "gerekirse biri diğerine devreder.")
        return "ekip_tanit", [(rng.choice(TEAM_Q), a)]
    if r < 0.55:
        ag = rng.choice(ags)
        return "ekip_ajan", [(rng.choice(ABOUT_Q).format(n=ag["name"]), about(ag, rng))]
    if r < 0.8:
        pairs = [(c, ag) for ag in ags for c in _jobs(ag)]
        c, ag = rng.choice(pairs)
        job, ex = CMD[c]
        q = rng.choice(WHO_Q).format(job=job.capitalize() if rng.random() < 0.5 else job)
        q = q[0].upper() + q[1:]
        a = f"{job.capitalize()} işine {ag['name']} bakar; ekibimde {ag['role']} olarak çalışır. \"{ex}\" demen yeterli."
        return "ekip_is", [(q, a)]
    if r < 0.9:
        a = ("Kod işlerinde Leo yazar; Nora testlerle, Iris incelemeyle bağımsız denetler. İkisi onaylamadan "
             "\"çalışıyor\" demem. Başka bir cevabı da \"bunu kontrol et\" diyerek denetçilere verebilirsin.")
        return "ekip_denetim", [(rng.choice(CHECK_Q), a)]
    withsub = [ag for ag in ags if ag.get("subagents")]
    ag = rng.choice(withsub)
    subs = [s["name"] for s in ag["subagents"]]
    a = f"Hayır, {ag['name']} yalnız değil: yanında {_and(subs)} var. İşin türüne göre biri devreye girer."
    return "ekip_alt", [(rng.choice(SUB_Q).format(n=ag["name"]), a)]
