"""translate_data: sahte veri setleri ve sahte çevirmenle (ağ yok)."""
import gzip
import json

import pytest

from orion_core import chat, translate_data as td

LIC = {"OpenAssistant/oasst2": "apache-2.0", "databricks/databricks-dolly-15k": "cc-by-sa-3.0",
       "Anthropic/hh-rlhf": "mit", "nvidia/HelpSteer2": "cc-by-4.0",
       td.MT_MODEL: "cc-by-4.0", td.BT_MODEL: "cc-by-4.0"}


class FakeHub:
    """Hugging Face yerine: lisans bilgisi + yerel dosyalar."""

    def __init__(self, root, licenses=None, files=None):
        self.root, self.lic, self.f = root, dict(LIC, **(licenses or {})), files or {}

    def info(self, repo, kind="datasets"):
        lic = self.lic[repo]
        if lic is None:
            return {"tags": []}
        return {"cardData": {"license": lic}, "sha": "abc123", "tags": [f"license:{lic}"]}

    def files(self, repo):
        return sorted(self.f.get(repo, {}))

    def download(self, repo, path):
        p = self.root / repo.replace("/", "__") / path
        p.parent.mkdir(parents=True, exist_ok=True)
        data = "\n".join(json.dumps(r) for r in self.f[repo][path])
        if path.endswith(".gz"):
            p.write_bytes(gzip.compress(data.encode()))
        else:
            p.write_text(data)
        return p


def hh(*turns):
    return {"chosen": "".join(f"\n\nHuman: {q}\n\nAssistant: {a}" for q, a in turns), "rejected": "x"}


def fake_files():
    return {
        "databricks/databricks-dolly-15k": {"databricks-dolly-15k.jsonl": [
            {"instruction": "What is a good way to learn a new language?",
             "response": "Practice every day and talk with native speakers as much as you can.", "context": ""},
            {"instruction": "Summarize this text.", "response": "It is about cats.", "context": "Cats are animals."},
            {"instruction": "How far is the city from Texas?", "response": "It is about 40 miles away.", "context": ""},
            {"instruction": "Write a function in Python.", "response": "```python\ndef f(): pass\n```", "context": ""},
        ]},
        "Anthropic/hh-rlhf": {"helpful-base/train.jsonl.gz": [
            hh(("How can I sleep better?", "Try to go to bed at the same time every night and avoid screens before sleep.")),
            hh(("What is the capital of France?", "The capital of France is Paris."),
               ("What is it famous for?", "It is famous for its museums, food and the Eiffel Tower.")),
            hh(("What can I cook tonight?", "You could make a simple vegetable soup with what you have at home.")),  # tekrar değil
        ], "harmless-base/train.jsonl.gz": [hh(("bad", "bad"))]},
        "nvidia/HelpSteer2": {"train.jsonl.gz": [
            {"prompt": "Give me a tip for studying.", "response": "Take short breaks and review your notes often.",
             "helpfulness": 2, "correctness": 3},
            {"prompt": "Give me a tip for studying.", "response": "Study in a quiet place and take short breaks every hour.",
             "helpfulness": 4, "correctness": 4},
            {"prompt": "Hi<extra_id_1>Assistant", "response": "x", "helpfulness": 4},
        ]},
    }


def test_license_gate(tmp_path):
    hub = FakeHub(tmp_path)
    assert td.check_license(hub, "Anthropic/hh-rlhf", "mit")["license"] == "mit"
    with pytest.raises(td.LicenseError, match="LİSANS KAPISI"):
        td.check_license(FakeHub(tmp_path, {"Anthropic/hh-rlhf": "cc-by-nc-4.0"}), "Anthropic/hh-rlhf", "mit")
    with pytest.raises(td.LicenseError, match="beklenen"):
        td.check_license(FakeHub(tmp_path, {"Anthropic/hh-rlhf": "apache-2.0"}), "Anthropic/hh-rlhf", "mit")
    with pytest.raises(td.LicenseError, match="bulunamadı"):
        td.check_license(FakeHub(tmp_path, {"Anthropic/hh-rlhf": None}), "Anthropic/hh-rlhf", "mit")
    assert td.license_of({"tags": ["license:CC-BY-4.0"]}) == "cc-by-4.0"
    # çevirmen modelin lisansı uymazsa collect hiçbir şey indirmeden durur
    with pytest.raises(td.LicenseError):
        td.collect(["dolly"], 10, tmp_path / "c", hub=FakeHub(tmp_path, {td.MT_MODEL: "cc-by-nc-sa-4.0"}, fake_files()))
    assert not (tmp_path / "c" / "shard-00.jsonl").exists()


def test_english_filters():
    assert td.en_reject("How do I bake bread?", "Mix flour, water and yeast, then bake it.") is None
    assert td.en_reject("What is 401k?", "It is a plan for the money you save.") == "abd_ozgu"
    assert td.en_reject("Price?", "It costs $20 or so for the whole thing.") == "abd_ozgu"
    assert td.en_reject("Code?", "Use `print(x)` to see the value of the thing.") == "kod_matematik"
    assert td.en_reject("Who are you?", "I am an AI assistant made by OpenAI.") == "model_kimligi"
    assert td.en_reject("Nasılsın?", "İyiyim, teşekkür ederim, sen nasılsın bugün?") == "ingilizce_degil"
    long = " ".join(["This is a sentence with seven words."] * 15)
    cut = td.cut_answer(long)
    assert cut and len(cut.split()) <= 120 and cut.endswith(".")
    assert td.cut_answer("word " * 200) == ""  # cümle sonu yok


def test_parsers():
    rows = [
        {"message_id": "q1", "parent_id": None, "role": "prompter", "lang": "en", "text": "Hello, how are you?"},
        {"message_id": "a1", "parent_id": "q1", "role": "assistant", "lang": "en", "text": "worse", "rank": 1},
        {"message_id": "a2", "parent_id": "q1", "role": "assistant", "lang": "en", "text": "I am fine, thanks!", "rank": 0},
        {"message_id": "q2", "parent_id": "a2", "role": "prompter", "lang": "en", "text": "What do you like?"},
        {"message_id": "a3", "parent_id": "q2", "role": "assistant", "lang": "en", "text": "I like books.", "rank": 0},
        {"message_id": "q3", "parent_id": None, "role": "prompter", "lang": "de", "text": "Hallo"},
    ]
    assert td.parse_oasst2(rows) == [[("Hello, how are you?", "I am fine, thanks!"), ("What do you like?", "I like books.")]]
    assert td.parse_hh([hh(("a", "b"), ("c", "d"), ("e", "f"))]) == []  # 3 tur: kısa değil
    assert td.parse_hh([hh(("a", "b"))]) == [[("a", "b")]]


def test_collect_shards(tmp_path):
    hub = FakeHub(tmp_path / "hf", files=fake_files())
    st = td.collect(["dolly", "hh-rlhf", "helpsteer2"], 100, tmp_path / "c", n_shards=2, hub=hub)
    rows = [json.loads(x) for i in range(2) for x in (tmp_path / "c" / f"shard-{i:02d}.jsonl").read_text().splitlines()]
    assert st["diyalog"] == len(rows) == 5
    by = {r["source"]: r for r in rows}
    assert by["databricks/databricks-dolly-15k"]["license"] == "cc-by-sa-3.0"
    assert "CC BY-SA 3.0" in by["databricks/databricks-dolly-15k"]["attribution"]
    hs = [r for r in rows if r["source"] == "nvidia/HelpSteer2"]
    assert len(hs) == 1 and "quiet place" in hs[0]["turns"][0][1]  # en yararlı cevap
    assert any(len(r["turns"]) == 2 for r in rows)  # çok turlu hh
    assert st["atilan"]["dolly"] == {"abd_ozgu": 1, "kod_matematik": 1}
    assert st["lisanslar"]["translator"]["license"] == "cc-by-4.0"
    assert all("harmless" not in json.dumps(r) and r["turns"][0][0] != "bad" for r in rows)
    # sınır
    td.collect(["hh-rlhf"], 1, tmp_path / "d", n_shards=1, hub=hub)
    assert len((tmp_path / "d" / "shard-00.jsonl").read_text().splitlines()) == 1


TR = {
    "Practice every day and talk with native speakers as much as you can.":
        "Her gün pratik yapın ve yapabildiğiniz kadar ana dili konuşanlarla konuşun.",
    "What is a good way to learn a new language?": "Yeni bir dil öğrenmenin iyi bir yolu nedir?",
    "How can I sleep better?": "Nasıl daha iyi uyuyabilirim?",
    "Try to go to bed at the same time every night and avoid screens before sleep.":
        "Her gece aynı saatte yatmaya çalışın ve uyumadan önce ekranlardan kaçının.",
    "What is the capital of France?": "Fransa'nın başkenti neresidir?",
    "The capital of France is Paris.": "Fransa'nın başkenti Paris'tir.",
    "What is it famous for?": "Ne ile ünlüdür?",
    "It is famous for its museums, food and the Eiffel Tower.": "Müzeleri, yemekleri ve Eyfel Kulesi ile ünlüdür.",
    "What can I cook tonight?": "Bu akşam ne pişirebilirim?",
    "You could make a simple vegetable soup with what you have at home.":
        "You could make a simple vegetable soup with what you have at home.",  # çevrilmemiş → atılır
    "Give me a tip for studying.": "Bana ders çalışmak için bir ipucu ver.",
    "Study in a quiet place and take short breaks every hour.":
        "Sessiz bir yerde çalış ve her saat kısa molalar ver ver ver ver.",  # döngü → atılır
}


def fake_tr(xs):
    return [TR.get(x, "Bu bir deneme çevirisidir ve oldukça güzel bir cümledir.") for x in xs]


def fake_back(xs):
    inv = {v: k for k, v in TR.items()}
    return [inv.get(x, "something else entirely") for x in xs]


def test_translate_and_merge(tmp_path):
    hub = FakeHub(tmp_path / "hf", files=fake_files())
    td.collect(["dolly", "hh-rlhf", "helpsteer2"], 100, tmp_path / "c", n_shards=2, hub=hub)
    lic = json.loads((tmp_path / "c" / "licenses.json").read_text())
    outs = []
    for i in range(2):
        o = tmp_path / "o" / f"tr-{i:02d}.jsonl"
        td.translate_shard(tmp_path / "c" / f"shard-{i:02d}.jsonl", o, fake_tr, fake_back, lic, sample_pct=100)
        outs.append(o)
    st = td.merge(outs, tmp_path / "rel", collect_stats=tmp_path / "c" / "collect.json")
    rows = [json.loads(x) for x in gzip.open(tmp_path / "rel" / "ceviri.jsonl.gz", "rt", encoding="utf-8")]
    assert st["kalan"] == len(rows)
    assert st["atilan"].get("cevrilmemis_ingilizce") == 1 and st["atilan"].get("tekrar_dongusu") == 1
    assert st["chrf"]["ornek"] == 3 and st["atilan"].get("gidis_donus_chrf", 0) <= 1
    for r in rows:
        assert r["training_allowed"] is True and td.MT_MODEL in r["translator"] and r["translator_license"] == "cc-by-4.0"
        assert "_chrf" not in r and r["license"] in td.LICENSE_ALLOW and r["attribution"]
    dolly = [r for r in rows if "dolly" in r["source"]]
    if dolly:  # "siz" → "sen" (Orion sen diye konuşur)
        assert "yapabildiğin" in dolly[0]["a"] and "yapabildiğiniz" not in dolly[0]["a"]
    assert (tmp_path / "rel" / "LISANS-ATIF.md").read_text().count("CC BY-SA 3.0") >= 1
    assert st["lisanslar"]["dolly"]["license"] == "cc-by-sa-3.0"


def test_turkish_filters():
    assert td.to_sen("Siz ne düşünüyorsunuz? Bilgisayarınızı kapatabilirsiniz.") == "Sen ne düşünüyorsun? Bilgisayarını kapatabilirsin."
    assert td.to_sen("Akdeniz ve deniz kenarında yalnız.") == "Akdeniz ve deniz kenarında yalnız."
    assert td.to_sen("Size yardım edebilir miyim? Evinizde misiniz?") == "Sana yardım edebilir miyim? Evinde misin?"
    assert td.tr_reject("Hello there, my friend, how are you?", "Merhaba") == "uzunluk_orani"
    assert td.tr_reject("This is fine and good", "Bu iyi ve güzel bir şey") is None
    assert td.has_loop("çok çok çok çok güzel")
    assert td.chrf("the cat sat", "the cat sat") == pytest.approx(100.0)
    assert td.chrf("abc", "xyz") == 0.0
    assert td.translate_texts(["Hi there. How are you?\n- First item."], lambda xs: [x.upper() for x in xs]) == \
        ["HI THERE. HOW ARE YOU?\n- FIRST ITEM."]


def test_budget_partial(tmp_path):
    shard = tmp_path / "s.jsonl"
    shard.write_text(json.dumps({"id": "x", "source": "s", "license": "mit", "attribution": "a",
                                 "turns": [["How can I sleep better?", "Try to go to bed at the same time every night and avoid screens before sleep."]]}) + "\n")
    st = td.translate_shard(shard, tmp_path / "o.jsonl", fake_tr, None, {}, budget_min=1e-9)
    assert st["yarim"] and st["islenen"] == 0


FEW = ["Kullanıcı: merhaba\nOrion: Merhaba, nasıl yardımcı olabilirim?"] * 50


def test_chat_extra_dialogs(tmp_path, monkeypatch):
    from orion_core import dialogs
    monkeypatch.setattr(chat, "persona_dialogues", lambda n, **k: FEW)  # hız: 60000 kişilik diyaloğu kodlamaya gerek yok
    exam_q = dialogs.QA_TESTS[0][0]
    rows = [
        {"q": "Nasıl daha iyi uyuyabilirim?", "a": "Her gece aynı saatte yatmaya çalış ve ekranlardan uzak dur.",
         "source": "Anthropic/hh-rlhf", "license": "mit", "training_allowed": True},
        {"q": "Fransa'nın başkenti neresidir?", "a": "Fransa'nın başkenti Paris'tir.", "source": "Anthropic/hh-rlhf",
         "license": "mit", "training_allowed": True,
         "turns": [["Fransa'nın başkenti neresidir?", "Fransa'nın başkenti Paris'tir."],
                   ["Ne ile ünlüdür?", "Müzeleri, yemekleri ve Eyfel Kulesi ile ünlüdür."]]},
        {"q": exam_q, "a": "Ben Orion, senin asistanınım.", "source": "x", "license": "mit", "training_allowed": True},
        {"q": "Gizli soru nedir?", "a": "Bu satır eğitime girmemeli çünkü izin yok.", "source": "x", "license": "mit",
         "training_allowed": False},
        {"q": "Lisanssız soru nedir?", "a": "Bu satır da girmemeli çünkü lisans uygun değil.", "source": "x",
         "license": "cc-by-nc-4.0", "training_allowed": True},
    ]
    p = tmp_path / "extra.jsonl.gz"
    with gzip.open(p, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    texts, st = chat.extra_dialogues(str(p), tmp_path / "cache")
    assert st["ceviri_cift"] == 2 and len(texts) == 2
    assert st["atilan"] == {"suzgec_ya_da_sinav": 1, "egitim_izni_yok": 1, "lisans": 1}
    assert texts[0] == dialogs.format_dialog(rows[0]["q"], rows[0]["a"])
    assert texts[1].count("Kullanıcı: ") == 2 and "\nOrion: Müzeleri" in texts[1]
    assert not any(exam_q in t for t in texts)
    # prepare: istatistik data.json'a yazılır; ek veri yoksa alan da yok
    docs = ["Türkiye güzel bir ülkedir ve çok kalabalıktır. " * 20] * 30
    st1 = chat.prepare(tmp_path / "d1", 10**9, vocab=300, texts=docs, open_data=False, extra_dialogs=str(p))
    assert st1["ceviri_cift"] == 2 and st1["ceviri"]["kaynaklar"] == {"Anthropic/hh-rlhf": 2}
    assert json.loads((tmp_path / "d1" / "data.json").read_text())["ceviri_cift"] == 2
    st0 = chat.prepare(tmp_path / "d0", 10**9, vocab=300, texts=docs, open_data=False, tokenizer=tmp_path / "d1" / "tokenizer.json")
    assert "ceviri_cift" not in st0 and st1["dialog_tokens"] > st0["dialog_tokens"]


def test_train_exam_best(tmp_path, monkeypatch):
    monkeypatch.setattr(chat, "persona_dialogues", lambda n, **k: FEW)
    docs = ["Türkiye güzel bir ülkedir ve çok kalabalıktır. " * 20] * 30
    data = tmp_path / "d"
    chat.prepare(data, 10**9, vocab=300, texts=docs, open_data=False)
    cfg = dict(ctx=32, d_model=32, n_layer=1, n_head=2, d_ff=64)
    st = chat.train(data, tmp_path / "run", steps=4, budget_min=5, batch=2, lr=1e-3, dialog_frac=0.75, config=cfg,
                    save_every=2, exam_every=2)
    assert (tmp_path / "run" / "best.pt").exists() and st["best_exam"]["step"] in (2, 4)
    assert len((tmp_path / "run" / "exam.jsonl").read_text().splitlines()) == 2
    m = chat.export_chat(tmp_path / "run", data, tmp_path / "exp-best", ckpt_name="best.pt")
    assert m["step"] == st["best_exam"]["step"]


# ------------------------------------------------------------------ GSM8K (insan yazımı matematik, MIT, yalnız train)

MIT_TEXT = ("MIT License\n\nCopyright (c) 2021 OpenAI\n\nPermission is hereby granted, free of charge, to any person "
            "obtaining a copy of this software...\n")
GSM_ROWS = [
    {"question": "Natalia sold clips to 48 of her friends in April, and then she sold half as many clips in May. "
                 "How many clips did Natalia sell altogether in April and May?",
     "answer": "Natalia sold 48/2 = <<48/2=24>>24 clips in May.\nNatalia sold 48+24 = <<48+24=72>>72 clips altogether "
               "in April and May.\n#### 72"},
    {"question": "Weng earns $12 an hour for babysitting. Yesterday, she just did 50 minutes of babysitting. How much did she earn?",
     "answer": "Weng earns 12/60 = $<<12/60=0.2>>0.2 per minute.\nWorking 50 minutes, she earned 0.2 x 50 = $<<0.2*50=10>>10.\n#### 10"},
]


class GsmHub(FakeHub):
    def __init__(self, root, rows=GSM_ROWS, license_text=MIT_TEXT, sha=None):
        super().__init__(root)
        self.rows, self.lt, self.sha = rows, license_text, sha
        self.fetched = []

    def text(self, url):
        assert url == td.SOURCES["gsm8k"]["license_url"]
        return self.lt

    def fetch(self, url, sha256):
        self.fetched.append(url)
        if self.sha is not None and self.sha != sha256:
            raise RuntimeError("sha256 tutmadı")
        p = self.root / "gsm" / "train.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(json.dumps(r) for r in self.rows))
        return p


def test_gsm8k_source_train_only():
    spec = td.SOURCES["gsm8k"]
    assert spec["url"].endswith("/grade_school_math/data/train.jsonl") and spec["license"] == "mit"
    assert "test" not in spec["url"] and "socratic" not in spec["url"]
    assert not any("test" in str(v) for k, v in spec.items() if k in ("url", "pattern"))
    assert len(spec["sha256"]) == 64


def test_gsm8k_parse_and_license(tmp_path):
    (q, a), = td.parse_gsm8k(GSM_ROWS[:1])[0]
    steps, final = a.rsplit(td.MATH_SEP, 1)
    assert "<<" not in steps and ">>" not in steps and final == "72" and "48/2 = 24" in steps
    (q2, a2), = td.parse_gsm8k(GSM_ROWS[1:])[0]
    assert "12 lira" in q2 and "$" not in q2 + a2 and "0.2 × 50 = 10 lira" in a2
    assert td.check_source_license(GsmHub(tmp_path), "gsm8k")["license"] == "mit"
    with pytest.raises(td.LicenseError, match="LİSANS KAPISI"):
        td.check_source_license(GsmHub(tmp_path, license_text="Apache License\nVersion 2.0"), "gsm8k")
    with pytest.raises(td.LicenseError):
        td.collect(["gsm8k"], 10, tmp_path / "c", hub=GsmHub(tmp_path, license_text="All rights reserved"))
    assert not (tmp_path / "c" / "shard-00.jsonl").exists()


GSM_TR = {
    "Natalia sold clips to 48 of her friends in April, and then she sold half as many clips in May.":
        "Natalia nisan ayında 48 arkadaşına toka sattı, mayıs ayında ise bunun yarısı kadar toka sattı.",
    "How many clips did Natalia sell altogether in April and May?":
        "Natalia nisan ve mayıs aylarında toplam kaç toka sattı?",
    "Natalia sold 48/2 = 24 clips in May.": "Natalia mayıs ayında 48/2 = 24 toka sattı.",
    "Natalia sold 48+24 = 72 clips altogether in April and May.": "Natalia nisan ve mayıs aylarında toplam 48+24 = 72 toka sattı.",
    "Weng earns 12 lira an hour for babysitting.": "Weng çocuk bakıcılığından saatte 12 lira kazanıyor.",
    "Yesterday, she just did 50 minutes of babysitting.": "Dün sadece 50 dakika çocuk baktı.",
    "How much did she earn?": "Ne kadar kazandı?",
    "Weng earns 12/60 = 0.2 lira per minute.": "Weng dakikada 12/60 = 0,2 lira kazanıyor.",
    "Working 50 minutes, she earned 0.2 × 50 = 10 lira.": "50 dakika çalışarak 0,2 × 50 = 19 lira kazandı.",  # sayı bozuk
}


def test_gsm8k_collect_translate_merge_keeps_previous(tmp_path):
    hub = GsmHub(tmp_path / "hf")
    st = td.collect(["gsm8k"], 100, tmp_path / "c", n_shards=1, hub=hub)
    assert st["diyalog"] == 2 and all("test" not in u for u in hub.fetched)
    rows = [json.loads(x) for x in (tmp_path / "c" / "shard-00.jsonl").read_text().splitlines()]
    assert {r["final"] for r in rows} == {"72", "10"} and all(td.MATH_SEP not in r["turns"][0][1] for r in rows)
    o = tmp_path / "o" / "tr-00.jsonl"
    ts = td.translate_shard(tmp_path / "c" / "shard-00.jsonl", o, lambda xs: [GSM_TR.get(x, x) for x in xs], None, {})
    assert ts["atilan"].get("sayi_bozuldu") == 1  # 10 → 19: yanlış sayı öğretilmez
    prev = tmp_path / "prev.jsonl.gz"
    old = {"id": "dolly-abc", "q": "Merhaba nasılsın?", "a": "İyiyim, sağ ol.", "source": "databricks/databricks-dolly-15k",
           "license": "cc-by-sa-3.0", "training_allowed": True, "attribution": "x"}
    bad = dict(old, id="x-1", training_allowed=False)
    with gzip.open(prev, "wt", encoding="utf-8") as f:
        f.write(json.dumps(old, ensure_ascii=False) + "\n" + json.dumps(bad) + "\n")
    ms = td.merge([o], tmp_path / "rel", collect_stats=tmp_path / "c" / "collect.json", prev=prev)
    out = [json.loads(x) for x in gzip.open(tmp_path / "rel" / "ceviri.jsonl.gz", "rt", encoding="utf-8")]
    assert ms["onceki"]["satir"] == 1 and ms["yeni"] == 1 and len(out) == 2
    g = next(r for r in out if r["source"] == "openai/grade-school-math")
    assert g["a"].endswith("\nSonuç: 72.") and "48+24 = 72" in g["a"] and g["training_allowed"] is True
    assert g["license"] == "mit" and "GSM8K" in g["attribution"]
    assert "GSM8K" in (tmp_path / "rel" / "LISANS-ATIF.md").read_text()
    # sohbet beyni bu satırı alır (Türkçe süzgeç + sınav dışı)
    texts, cs = chat.extra_dialogues(str(tmp_path / "rel" / "ceviri.jsonl.gz"), tmp_path / "x")
    assert cs["ceviri_cift"] == 2 and any("Sonuç: 72." in t for t in texts)


def test_numbers_kept():
    assert td.numbers_kept("1,000 and 0.2", "1.000 ve 0,2")
    assert not td.numbers_kept("48+24 = 72", "48+24 = 27")
    assert td.final_tr("2.5") == "2,5"
