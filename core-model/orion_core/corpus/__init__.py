"""Orion Türkçe derlem hattı (gelişim deposunda GitHub Actions'ta çalışır).

  discover  → kaynak kartları/LICENSE/boyut/robots + küçük örnekler → derlem-kesif-<tarih> Release raporu (toplu indirme YOK)
  collect   → yalnız config'de enabled=true VE keşifte durum=gecti kaynaklar; ≥1 sn/istek, robots.txt'e uyar,
              sürdürülebilir durum (durum-*.json), parçalı jsonl.gz (<2GB) ve belge başına kaynak/lisans/atıf
  mix       → chat.prepare --corpus: kategori pay sınırlarıyla örnekleme (akademik ≤%20, kod ≤%12 ...)

Kaynak listesi ve pay sınırları: shared/core-model/derlem-kaynaklar.json. Model üretimi veri ve ODC-By web taramaları
(FineWeb-2, CulturaX, OSCAR, mC4) bu hatta HİÇ yoktur.
"""
