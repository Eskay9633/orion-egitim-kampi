"""Bilgi/anlama verisi: gerçek → Türkçe soru-cevap, ekler doğru, sınav sızmaz, biçim chat.extra_dialogues ile uyumlu."""
import gzip
import json
import random

from orion_core import bilgi, chat, dialogs


def test_suffixes():
    assert bilgi.gen("Fransa") == "Fransa'nın" and bilgi.gen("Mısır") == "Mısır'ın" and bilgi.gen("Peru") == "Peru'nun"
    assert bilgi.gen("Türkiye") == "Türkiye'nin" and bilgi.gen("Japonya") == "Japonya'nın"
    assert bilgi.loc("Asya") == "Asya'da" and bilgi.loc("Avrupa") == "Avrupa'da"


def test_country_facts_and_no_exam_leak():
    rows = bilgi.country_dialogs([
        {"cL": "Japonya", "capL": "Tokyo", "contL": "Asya", "curL": "Japon yeni"},
        {"cL": "Türkiye", "capL": "Ankara", "contL": "Asya"},
    ], random.Random(1))
    qs = [r["q"] for r in rows]
    assert "Japonya'nın başkenti neresi?" in qs and "Tokyo hangi ülkenin başkenti?" in qs
    assert any(r["a"] == "Japonya, Asya'da yer alır." for r in rows)
    assert all(not dialogs.is_exam_question(q) and not dialogs.near_exam(q) for q in qs), "sınav sorusu sızdı"
    assert all(r["license"] == "cc0-1.0" and r["training_allowed"] for r in rows)


def test_provinces_elements_reading():
    p = bilgi.province_dialogs([{"pL": "Mersin ili", "plate": "33"}])
    assert ("Mersin'in plaka kodu kaç?", "Mersin ilinin plaka numarası 33.") in [(r["q"], r["a"]) for r in p]
    e = bilgi.element_dialogs([{"eL": "demir", "sym": "Fe", "num": "26"}])
    assert any(r["a"] == "demir elementinin atom numarası 26." for r in e)
    x = bilgi.xquad_dialogs([{"context": "İstanbul büyük bir şehirdir. Boğaziçi Köprüsü 1973'te açıldı. Köprü uzundur.",
                              "question": "Boğaziçi Köprüsü ne zaman açıldı?", "answers": {"text": ["1973"]}}])
    assert x and "1973'te açıldı" in x[0]["q"] and x[0]["a"] == "Metne göre cevap: 1973."
    b = bilgi.belebele_dialogs([{"flores_passage": "Ali sabah erkenden okula gitti.", "question": "Ali nereye gitti?",
                                 "mc_answer1": "Eve", "mc_answer2": "Okula", "mc_answer3": "Pazara", "mc_answer4": "Parka",
                                 "correct_answer_num": "2"}])
    assert b and b[0]["a"] == "Doğru cevap B: Okula."


def test_rows_pass_extra_dialogues_loader(tmp_path):
    rows = bilgi.country_dialogs([{"cL": "Japonya", "capL": "Tokyo", "contL": "Asya", "curL": "Japon yeni"}], random.Random(1))
    rows += bilgi.province_dialogs([{"pL": "Mersin ili", "plate": "33"}])
    f = tmp_path / "bilgi.jsonl.gz"
    with gzip.open(f, "wt", encoding="utf-8") as g:
        for r in rows:
            g.write(json.dumps(r, ensure_ascii=False) + "\n")
    texts, st = chat.extra_dialogues(str(f), tmp_path / "c")
    assert len(texts) == len(rows) and not st["atilan"], st
