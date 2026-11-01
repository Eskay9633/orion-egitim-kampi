# Çeviri verisi denetim klasörü

`hedef.txt` dosyasını bu klasöre `ÇİFT PARÇA [KAYNAKLAR] [koru|yeni]` biçiminde yazıp main'e işlemek
`ceviri` iş akışını (.github/workflows/cevir.yml) başlatır. Dosya değişmezse yeniden başlamaz;
yeniden çalıştırmak için içeriği değiştir ya da Actions → ceviri → Run workflow kullan.

- `100000 3` — bütün kaynaklar (oasst2, dolly, hh-rlhf, helpsteer2, gsm8k), 3 paralel parça
- `8000 2 gsm8k` — yalnız GSM8K (insan yazımı matematik problemleri, MIT; yalnız train, test bölümü hiç alınmaz)
- KAYNAKLAR boş ya da `hepsi` = hepsi
- Dördüncü alan: `koru` (varsayılan) — bir önceki `ceviri-*` Release'inin satırları yeni Release'e aynen taşınır
  (eski + yeni tek `ceviri.jsonl.gz`); `yeni` — yalnız bu çalışmanın satırları.

Çıktı: `ceviri-YYYYMMDD-HHMM` ön sürüm Release'i (`ceviri.jsonl.gz`, `stats.json`, `LISANS-ATIF.md`).
Kaggle (kaggle.yml) en yeni `ceviri-*` Release'ini kendiliğinden kullanır (kaggle/hedef.txt'te üçüncü alan `yok` ile kapatılır).
Veri depoya işlenmez.
