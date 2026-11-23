import random

from orion_core.chat import prompt_for
from orion_core.knowledge_line import MAX_LINE, PREFIX, context_dialogs, knowledge_line


def test_line_rules():
    assert knowledge_line(None) is None and knowledge_line("  ") is None
    l = knowledge_line("Ankara Türkiye'nin başkentidir.\nNüfusu kalabalıktır.")
    assert l == "Bilgi: Ankara Türkiye'nin başkentidir. Nüfusu kalabalıktır."
    long = " ".join(f"Cümle numarası {i} burada biter." for i in range(60))
    k = knowledge_line(long)
    assert k.startswith(PREFIX) and len(k) <= MAX_LINE and k.endswith(".")


def test_prompt_order_and_backward_compat():
    assert prompt_for("Nasılsın?") == "Kullanıcı: Nasılsın?\nOrion:"
    p = prompt_for("Başkent neresi?", memory="Konya'da yaşıyorsun", knowledge="Ankara Türkiye'nin başkentidir.")
    assert p == "Bilgi: Ankara Türkiye'nin başkentidir.\nHafıza: Konya'da yaşıyorsun\nKullanıcı: Başkent neresi?\nOrion:"


def test_context_dialogs_pos_and_neg():
    items = [("Ankara Türkiye'nin başkentidir.", "Türkiye'nin başkenti neresi?", "Ankara"),
             ("Kilimanjaro Afrika'nın en yüksek dağıdır.", "Afrika'nın en yüksek dağı hangisi?", "Kilimanjaro")]
    rows = context_dialogs(items, random.Random(0), neg_frac=1.0)
    pos = [r for r in rows if r["source"] == "bilgi-satiri"]
    neg = [r for r in rows if r["source"] == "bilgi-satiri-yok"]
    assert len(pos) == 2 and all(r["a"].rstrip(".") in r["bilgi"] for r in pos)
    assert neg and all("araştır" in r["a"] for r in neg)
    assert all(r["training_allowed"] for r in rows)
