# Derlem (Türkçe metin toplama) — istek dosyası

`istek.txt` dosyasının İLK satırı `main`'e işlenince `derlem` iş akışı çalışır:

| Satır | Ne yapar |
|---|---|
| `kesif` | Lisans/boyut/robots keşfi; toplu indirme yok. Release `derlem-kesif-YYYYMMDD-HHMM` (`kesif.json`). |
| `topla` | `shared/core-model/derlem-kaynaklar.json`'da `enabled=true` VE en yeni keşifte `durum=gecti` kaynakları toplar. |
| `topla trwikisource,dergipark` | Yalnız bu kaynaklar (yine kapıdan geçmeleri gerekir). |
| `topla etkin 8` | Bitmeyen parçalar varsa iş kendini en çok 8 kez daha başlatır (her tur ≤5,5 saat). |
| `openstax` | OpenStax CC BY matematik kitapları → çeviri → Release `derlem-openstax`. |
| `dmmath` | DeepMind mathematics_dataset üreticisiyle Türkçe şablonlu problemler → Release `derlem-dmmath`. |

Toplanan veri kaynak başına `derlem-<kaynak>` Release'inde durur (`<kaynak>-<parça>-<sıra>.jsonl.gz`, her biri <2GB;
`durum-*.json` + `tekil-*.txt.gz` sürdürme durumu). Sohbet beyni: `chat prepare --corpus https://github.com/<depo>/releases/tag/derlem-<kaynak>`.

Kurallar: istek arası ≥1 sn, robots.txt'e uyulur, CAPTCHA aşılmaz, model üretimi veri ve ODC-By web taramaları yok.
Pay sınırları (dil modeli akışında en çok): vikipedi %35, meclis %15, akademik %20, hukuk %10, sözlük %5, matematik %10.
