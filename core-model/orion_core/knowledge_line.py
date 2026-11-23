"""Bilgi satırı (sahibin kararı 2026-11-23: "kendi kendine öğrenme; Orion internete çıkmayı öğrenmeli").

Sohbet beyni bilgiyi ezberlemek yerine OKUYARAK cevaplar: istemin başına telefondaki bilgi bulucunun (doğrulanmış bilgi
hafızası, internet varsa Vikipedi) bulduğu kısa paragraf konur.

BİÇİM (Kotlin ChatBrain ile BİREBİR aynı; değiştirmeden önce iki tarafı birlikte güncelle):
    Bilgi: <paragraf>\\n
    Hafıza: <notlar>\\n          (isteğe bağlı, memory_notes.py)
    Kullanıcı: <soru>\\nOrion: <cevap>
Kurallar: "Bilgi: " dahil satır en çok MAX_LINE karakter; paragraf tek satır (satır sonu boşluğa çevrilir), cümle
sınırında kısaltılır, yarım cümle kalmaz. Bilgi yoksa satır HİÇ yazılmaz (eski istem aynen).
Davranış: cevap bilgideyse Orion onu kullanır; bilgi soruyla ilgisizse UYDURMAZ ("bu konuda bilgim yok, araştırayım" der).
"""
from __future__ import annotations

import random
import re

PREFIX = "Bilgi: "
MAX_LINE = 320
_SENT = re.compile(r"(?<=[.!?])\s+")

NO_INFO = ["Bu konuda elimde bilgi yok; istersen internetten araştırayım.",
           "Bunu bilmiyorum. İstersen araştırıp öğrenebilirim.",
           "Elimdeki bilgide bunun cevabı yok; araştırmamı ister misin?"]


def knowledge_line(text: str | None, limit: int = MAX_LINE) -> str | None:
    """Paragrafı tek satıra indirir ve cümle sınırında kısaltır. Sığan tek cümle yoksa None."""
    if not text or not text.strip():
        return None
    t = re.sub(r"\s+", " ", text).strip()
    room = limit - len(PREFIX)
    if len(t) <= room:
        return PREFIX + t
    out = ""
    for s in _SENT.split(t):
        if len(out) + len(s) + (1 if out else 0) > room:
            break
        out = f"{out} {s}" if out else s
    return PREFIX + out if out else None


def context_dialogs(items: list[tuple[str, str, str]], rng: random.Random, neg_frac: float = 0.3) -> list[dict]:
    """(bağlam, soru, cevap) üçlülerinden "Bilgi:" satırlı diyaloglar. neg_frac kadarına başka bir öğenin bağlamı verilir
    ve cevap "bilmiyorum, araştırayım" olur (uydurmamayı öğretir)."""
    lines = [knowledge_line(c) for c, _, _ in items]
    out = []
    for i, ((ctx, q, a), line) in enumerate(zip(items, lines)):
        if line is None or a not in line:
            continue
        out.append({"bilgi": line[len(PREFIX):], "q": q, "a": a if a.endswith((".", "!", "?")) else a + ".",
                    "source": "bilgi-satiri", "license": "cc-by-sa-4.0", "training_allowed": True})
        if rng.random() < neg_frac and len(items) > 1:
            j = rng.randrange(len(items))
            other = lines[j]
            if j != i and other and a not in other:
                out.append({"bilgi": other[len(PREFIX):], "q": q, "a": rng.choice(NO_INFO),
                            "source": "bilgi-satiri-yok", "license": "cc-by-sa-4.0", "training_allowed": True})
    return out
