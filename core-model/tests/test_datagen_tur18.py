"""Tur 18 (denetim sonrası): test kümeleri değişmedi; karşıt çiftler ayrılmış (OOD) kalıpları taklit etmez.

Tur 18'de test_ood yanlış-iş çözümlemesinden türetilen "yakın-ıska" grupları, ayrılmış kalıpların tek sözcüğü
değiştirilmiş kopyalarıydı ("{X} var, {T} {V}" → "{X} olacak, {T} hatırlat"); OOD güvenlik tabanını şişiriyordu.
Hepsi kaldırıldı. Bu dosya (1) değerlendirme/kalibrasyon kümelerinin parmak izini, (2) bundan sonra eklenecek her
karşıt çiftin ayrılmış kalıplardan yapısal olarak uzak olduğunu (yuva normalize edilmiş sözcük-Jaccard < 0.6) korur."""
import hashlib
import json
import random
import re

import pytest

from orion_core import SHARED, datagen

# Değerlendirme (evaluate.run_eval) ve kalibrasyon kümelerinin parmak izi. 2026-11-13: EkBot onuncu ajan olarak
# eklendi (sahibin isteği); ajan adları cümlelere girdiği için kümeler yeniden üretildi. Eşikler değişmedi.
# 2026-11-13 (2): Leo, Nora, Iris ve code.run / code.repo / work.check komutları eklendi (sahibin isteği: kod yazan
# ve işi denetleyen ajanlar); kümeler yeniden üretildi. Eşikler değişmedi.
SPLIT_SHA = {
    ("test_iid", 600, 101): "a1044377771d15af52218d2a0da2a1411d66c525b440d070a53d614b86e2b9dc",
    ("test_ood", 400, 202): "d95f78e3b631c98bf2adf2dbe36856f3f42b4c9b204b57f8b02d01ee3a019255",
    ("legacy_ood", 400, 202): "111d38ec52f70bfdf50425587a76766f56a115a3e8729788179f196387d5b630",
    ("test_iid", 1000, 707): "4ac5b2d0da6a811ccda481820423f9bac404b7cb58879250d8082c6ac147d639",
    ("test_ood", 1000, 909): "9e6b933687b4271ca3597668cd208b078dcd02716c9eeebfaa34926128fb2164",
    ("legacy_ood", 1000, 808): "9e3a9ab44571937a415fc93448b86904ef8587f2390a4253cda2b6caf423699d",
}

# Tur 14 karşıt grupları: ayrılmış fiil/yüklem parçalarını içermedikleri test_datagen_tur14'te denetlenir. Sözcük
# kümesi ölçüsü sırayı görmediği için bu eski gruplar ("takvime ekle: {T} {X}" ~ ayrılmış "{T} {V}: {X}") burada
# muaf; bundan sonra eklenen HER grup aşağıdaki Jaccard sınırına tabidir.
TUR14_GROUPS = {"kaydet", "sayaç/hatırlat", "takvim", "anımsat/ajanda", "hakkında", "neler yapabilir", "görsel"}
JACCARD_MAX = 0.6

# Denetimde bulunan, kaldırılan yakın-ıska kalıpları (ayrılmış kalıbın bir sözcüğü değiştirilmiş hâli).
REMOVED_NEAR_MISS = [
    "{X} olacak, {T} hatırlat",            # ayrılmış REM_FRAMES[3] "{X} var, {T} {V}"
    "{X}meyi unutmamalıyım, {T} hatırlat",  # ayrılmış REM_ACC_FRAMES[3] "{XA} unutmayayım, {T} {V}"
    "{X}meyi atlamayayım, {T} anımsat",
    "güncellemen var mı",                   # ayrılmış "güncelleme var mı"
    "gelişim için öneri ver",               # ayrılmış "gelişim önerisi ver"
    "{X} için {T} hatırlatma oluştur",      # ayrılmış fiil "hatırlatıcı oluştur"
    "notlarımdan {X} içerenleri bul",       # ayrılmış "notlarımdan {Q} olanları {V}"
    "45 dk'lık sayaç kur",                  # ayrılmış TIMER_FRAMES[7] "{M} dk {V}"
    "{T} {X} planıma ekle",                 # ayrılmış fiil "programıma ekle"
]
# Birebir de eğitim akışında görülmemeli (Jaccard'ın kaçırdığı "ekteki fotoğrafa göz at: {Q}" dahil).
REMOVED_LITERALS = ["olacak, ", "unutmamalıyım", "atlamayayım", "ihmal etmeyeyim", "aklımdan çıkmasın",
                    "güncellemen var mı", "gelişim için öneri", "gelişimin için öneri", "fotoğrafa göz at", "planıma ekle",
                    "planımda ne var", "içerenleri", "konulu olanları", "dk'lık", "hatırlatma oluştur", "alarm oluştur",
                    "bildirim oluştur", "unutmamak için not al", "unutmayayım diye"]


def _tokens(s: str) -> frozenset:
    """Yuva normalize edilmiş, kaba gövdeli sözcük kümesi: {T} → t, serbest metin yuvaları ({X},{XA},{Q},{L}…) → x,
    sayılar → m; kesme sonrası ek ve noktalama atılır; Türkçe ekler için ilk 5 harf ("güncellemen" ~ "güncelleme")."""
    s = s.lower()
    s = re.sub(r"\{t\}\w*", " tslot ", s)
    s = re.sub(r"\{[a-z]+\}\w*", " xslot ", s)
    s = re.sub(r"'\w*", "", s)
    s = re.sub(r"\d+", " mslot ", s)
    s = re.sub(r"[,:;.?!\"]", " ", s)
    return frozenset(w[:5] for w in s.split())


def _jaccard(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b)


class _Slots:
    """Üreticileri yuva adlarıyla çalıştırır: zaman → {T}, değer havuzları ve rastgele ifadeler → {X}."""

    def __enter__(self):
        self.saved = (datagen.random_time, datagen.pick, datagen.random_phrase)
        datagen.random_time = lambda rng, allow_offset=True, split="test": datagen.TimeExpr("{T}", "d+1@09:00")
        datagen.pick = lambda rng, values, split, rand=None, p_rand=0.7: "{X}mek"  # mastar bekleyenler de çalışsın
        datagen.random_phrase = lambda *a, **k: "{X}"
        return self

    def __exit__(self, *exc):
        datagen.random_time, datagen.pick, datagen.random_phrase = self.saved


@pytest.fixture(scope="module")
def held_out() -> dict:
    """Ayrılmış yapılar: test_ood'un dilbilgisi örnekleri (ayrılmış çerçeve ve/veya fiil) + legacy_ood kalıpları,
    yuvalarla. Mevcut sızıntı testleriyle aynı kaynak (split_pool 'held' parçaları ve _templates_for('test_ood'))."""
    rng = random.Random(1)
    out: dict = {}
    with _Slots():
        for cmd in datagen.GRAMMAR:
            for _ in range(1500):
                try:
                    tr, _a = datagen.grammar_example(rng, cmd, "test_ood")
                except Exception:  # yuva değerleri bazı protokol sınırlarını aşabilir; yapı yine toplanır
                    continue
                out.setdefault(_tokens(tr), tr)
            for _ in range(200):
                try:
                    tr, _a = rng.choice(datagen._templates_for(cmd, "test_ood"))(rng, "test_ood")
                except Exception:
                    continue
                out.setdefault(_tokens(tr), tr)
    assert len(out) > 3000
    return out


def _closest(src: str, held: dict) -> tuple[float, str]:
    t = _tokens(src)
    return max((_jaccard(t, h), s) for h, s in held.items())


def test_eval_and_calibration_sets_unchanged():
    for (split, n, seed), want in SPLIT_SHA.items():
        got = hashlib.sha256("".join(json.dumps([e["src"], e["full"]], ensure_ascii=False) + "\n"
                                     for e in datagen.t2c_set(n, split, seed)).encode()).hexdigest()
        assert got == want, (split, n, seed)


def test_kotlin_fixture_matches_generator(tmp_path):
    p = tmp_path / "te.jsonl"
    datagen.export_eval_fixture(p)
    assert p.read_text(encoding="utf-8") == (SHARED / "core-model" / "translator-eval.jsonl").read_text(encoding="utf-8")


def test_detector_flags_removed_near_miss_templates(held_out):
    """Ölçü dürüst mü: denetimde bulunan yakın-ıska kalıplarını yakalar."""
    for c in REMOVED_NEAR_MISS:
        score, h = _closest(c, held_out)
        assert score >= JACCARD_MAX, (c, score, h)


def test_new_contrast_templates_far_from_held_out(held_out):
    """Tur 14 sonrası eklenen hiçbir karşıt kalıp, yuvalar normalize edildikten sonra ayrılmış bir kalıba
    sözcük-Jaccard ≥ 0.6 ile benzemez (tek sözcük değiştirilmiş kopya OOD ölçümünü şişirir)."""
    assert TUR14_GROUPS <= set(datagen.CONTRAST_GROUPS)
    rng = random.Random(2)
    bad = []
    with _Slots():
        for name in sorted(set(datagen.CONTRAST_GROUPS) - TUR14_GROUPS):
            for _cmd, gen in datagen.CONTRAST_GROUPS[name]:
                for _ in range(60):
                    tr, _a = gen(rng)
                    score, h = _closest(tr, held_out)
                    if score >= JACCARD_MAX:
                        bad.append((name, tr, h, round(score, 2)))
    assert not bad, bad[:10]


def test_contrast_frac_matches_group_count():
    """Yakın-ıska grupları kaldırıldı: 7 grup, oran Tur 14 değeri (0.08)."""
    assert set(datagen.CONTRAST_GROUPS) == TUR14_GROUPS
    assert datagen.CONTRAST_FRAC == 0.08


def test_removed_near_miss_phrases_absent_from_training_stream():
    srcs = [e["src"] for e in datagen.t2c_set(20000, "train", seed=23)]
    for s in srcs:
        for lit in REMOVED_LITERALS:
            assert lit not in s, (lit, s)
