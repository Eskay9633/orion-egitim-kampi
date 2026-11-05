"""Metin temizleme: viki işaretlemesi, PDF çıktısı, Türkçe dil ve nitelik süzgeci, tekilleştirme, kişisel veri temizliği."""
from __future__ import annotations

import hashlib
import html
import re
import unicodedata

from .. import scrub as _scrub

WORD = re.compile(r"[^\W\d_]+", re.U)
TR_CHARS = set("çğıöşüÇĞİÖŞÜ")
TR_STOP = {"ve", "bir", "bu", "için", "ile", "da", "de", "ki", "çok", "daha", "gibi", "olarak", "ama", "veya", "en",
           "olan", "her", "şey", "o", "var", "yok", "ise", "kadar", "sonra", "önce", "göre", "değil", "olduğu",
           "ancak", "ya", "mı", "mi", "ne", "şu", "biri", "bunu", "bunun", "olan", "olup", "üzere", "ilgili"}
EN_STOP = {"the", "and", "of", "to", "is", "in", "that", "for", "with", "this", "are", "was", "be", "by", "on",
           "as", "which", "from", "it", "an", "or", "were", "have", "has", "not", "at"}


def words(s: str) -> list[str]:
    return WORD.findall(s.lower())


def turkish_score(text: str) -> tuple[float, float, float]:
    """(Türkçe işlev sözcüğü oranı, İngilizce işlev sözcüğü oranı, Türkçe harf oranı)."""
    w = words(text[:20000])
    if not w:
        return 0.0, 0.0, 0.0
    letters = [c for c in text[:20000] if c.isalpha()]
    return (sum(x in TR_STOP for x in w) / len(w), sum(x in EN_STOP for x in w) / len(w),
            sum(c in TR_CHARS for c in letters) / max(1, len(letters)))


def is_turkish(text: str) -> bool:
    tr, en, ch = turkish_score(text)
    return tr >= 0.04 and en < 0.04 and ch >= 0.015


def quality_reason(text: str, min_chars: int = 300) -> str | None:
    """None = geçer. Kısa, sembol ağırlıklı, tekrar eden satırlı ya da sözcük yapısı bozuk (OCR/çıkarım çöpü) metni atar."""
    if len(text) < min_chars:
        return "kisa"
    letters = sum(c.isalpha() for c in text)
    if letters / max(1, len(text)) < 0.6:
        return "harf_orani"
    w = words(text)
    if not w:
        return "sozcuk_yok"
    avg = sum(map(len, w)) / len(w)
    if not (3.0 <= avg <= 12.0):
        return "sozcuk_uzunlugu"
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if len(lines) >= 10 and len(set(lines)) / len(lines) < 0.7:
        return "tekrar_satir"
    if sum(len(x) == 1 for x in w) / len(w) > 0.2:
        return "tek_harf"
    return None


def norm(text: str) -> str:
    text = unicodedata.normalize("NFC", html.unescape(text)).replace("­", "").replace("\x00", " ")
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return "\n".join(ln.strip() for ln in text.split("\n")).strip()


def doc_hash(text: str) -> str:
    return hashlib.sha1(re.sub(r"\W+", " ", text.lower()).strip().encode()).hexdigest()[:16]


def para_hashes(text: str, min_len: int = 80) -> list[str]:
    return [doc_hash(p) for p in text.split("\n") if len(p) >= min_len]


# --------------------------------------------------------------------------- viki işaretlemesi

def _drop_nested(s: str, open_: str, close: str) -> str:
    out, depth, i = [], 0, 0
    while i < len(s):
        if s.startswith(open_, i):
            depth += 1
            i += len(open_)
        elif depth and s.startswith(close, i):
            depth -= 1
            i += len(close)
        else:
            if not depth:
                out.append(s[i])
            i += 1
    return "".join(out)


FILE_LINK = re.compile(r"\[\[(?:Dosya|Resim|File|Image|Kategori|Category|Media|Ortam):[^\[\]]*(?:\[\[[^\]]*\]\][^\[\]]*)*\]\]", re.I)
CUT_HEADINGS = re.compile(r"^=+\s*(Kaynakça|Kaynaklar|Dış bağlantılar|Ayrıca bakınız|Notlar|Dipnotlar)\s*=+\s*$", re.M | re.I)


def strip_wikitext(s: str) -> str:
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"<ref[^>]*/>", "", s)
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.S)
    s = re.sub(r"<(math|code|pre|gallery|timeline|score|syntaxhighlight)[^>]*>.*?</\1>", "", s, flags=re.S | re.I)
    s = _drop_nested(s, "{{", "}}")
    s = _drop_nested(s, "{|", "|}")
    m = CUT_HEADINGS.search(s)
    if m:
        s = s[:m.start()]
    s = FILE_LINK.sub("", s)
    s = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\[\[([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\[https?://\S+\s([^\]]*)\]", r"\1", s)
    s = re.sub(r"\[https?://\S+\]", "", s)
    s = re.sub(r"'{2,}", "", s)
    s = re.sub(r"^=+\s*(.*?)\s*=+\s*$", r"\1", s, flags=re.M)
    s = re.sub(r"^[*#:;]+\s*", "", s, flags=re.M)
    s = re.sub(r"</?[a-zA-Z][^>]*>", "", s)
    s = re.sub(r"__[A-ZÇĞİÖŞÜ]+__", "", s)
    return norm(s)


# --------------------------------------------------------------------------- PDF çıktısı

REF_HEAD = re.compile(r"^\s*(KAYNAKÇA|Kaynakça|KAYNAKLAR|Kaynaklar|REFERENCES|References|BIBLIOGRAPHY|Extended Abstract|EXTENDED ABSTRACT)\s*$", re.M)


def clean_pdf_text(s: str) -> str:
    s = s.replace("\f", "\n")
    m = None
    for m in REF_HEAD.finditer(s):
        pass
    if m and m.start() > len(s) * 0.4:   # kaynakça sondadır; öndeki "Kaynaklar" kelimesi kesilmesin
        s = s[:m.start()]
    s = re.sub(r"(\w)-\n(\w)", r"\1\2", s)                     # satır sonu tirelemesi
    lines = [ln.strip() for ln in s.split("\n")]
    lines = [ln for ln in lines if ln and not re.fullmatch(r"[\d\s\-–—|/.]{1,12}", ln)]  # sayfa numaraları
    paras, cur = [], []
    for ln in lines:
        cur.append(ln)
        if re.search(r"[.!?:;»\"”)]$", ln):
            paras.append(" ".join(cur))
            cur = []
    if cur:
        paras.append(" ".join(cur))
    # İngilizce özet/paragraflar ve çok kısa başlık parçaları atılır
    keep = [p for p in paras if len(p) >= 40 and not (turkish_score(p)[1] >= 0.06)]
    return norm("\n".join(keep))


# --------------------------------------------------------------------------- kişisel veri (mevzuat/karar)

ROLE = (r"(?:Davacı|Davalı|Davacılar|Davalılar|Sanık|Sanıklar|Müşteki|Mağdur|Katılan|Başvurucu|Başvurucular|Şikâyetçi|"
        r"Şikayetçi|Müdahil|Vekili|Vekilleri|Müdafi|Müdafii|Tanık|İhbar Olunan|Borçlu|Alacaklı|Hükümlü|Çocuk|Maktul)")
ROLE_NAME = re.compile(ROLE + r"(\s*\(.*?\))?\s*:\s*[^\n]{1,120}")
ADV = re.compile(r"\bAv\.\s*(?:[A-ZÇĞİÖŞÜ][a-zçğıöşü]+\s+){0,2}[A-ZÇĞİÖŞÜ][\wçğıöşüÇĞİÖŞÜ]+")
NAME_SURNAME = re.compile(r"\b[A-ZÇĞİÖŞÜ][a-zçğıöşü]{1,20}(?:\s+[A-ZÇĞİÖŞÜ][a-zçğıöşü]{1,20})?\s+[A-ZÇĞİÖŞÜ]{2,}(?:-[A-ZÇĞİÖŞÜ]{2,})?\b")
UPPER_OK = {"TBMM", "T.C", "AİHM", "AİHS", "CMK", "HMK", "TCK", "TMK", "HUMK", "İYUK", "AYM", "KHK", "SGK", "TL",
            "YTL", "ABD", "AB", "BM", "NATO", "TRT", "PTT", "MHP", "CHP", "AKP", "HDP", "İİK", "TTK", "VUK", "FSEK"}
BIRTH = re.compile(r"\b\d{1,2}[./]\d{1,2}[./](?:19|20)\d{2}\s+doğumlu\b", re.I)


def scrub_personal(text: str) -> str:
    """Orion scrub (TCKN, telefon, e-posta, IBAN, adres) + yargı kararlarındaki taraf/vekil adları + 'Ad SOYAD' kalıbı."""
    text = _scrub.scrub(text)
    text = ROLE_NAME.sub(lambda m: m.group(0).split(":")[0] + ": <GIZLI:AD>", text)
    text = ADV.sub("Av. <GIZLI:AD>", text)

    def ns(m):
        return m.group(0) if m.group(0).split()[-1] in UPPER_OK else "<GIZLI:AD>"
    text = NAME_SURNAME.sub(ns, text)
    return BIRTH.sub("<GIZLI:DOGUM>", text)


def html_to_text(s: str) -> str:
    s = re.sub(r"<(script|style|nav|header|footer)[^>]*>.*?</\1>", "", s, flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>|</p>|</div>|</h\d>|</li>", "\n", s, flags=re.I)
    return norm(re.sub(r"<[^>]+>", "", s))
