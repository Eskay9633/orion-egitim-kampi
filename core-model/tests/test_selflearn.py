"""Kendi kendine öğrenme: yalnız son cevabı doğru ve adımlı kendi çözümleri yazılır."""
import gzip
import json

from orion_core import chat, selflearn as SL


def test_final_and_correct():
    assert SL.final_answer("Önce 3 ile 4'ü topla: 3 + 4 = 7. Cevap: 7") == "7"
    assert SL.is_correct("Adım adım: 10 - 4 = 6. Sonuç 6.", "6")
    assert SL.is_correct("Yarısı 2,5 olur.", "2.5") and SL.is_correct("Cevap: 1/2", "0.5")
    assert not SL.is_correct("Cevap: 8", "7") and not SL.is_correct("bilmiyorum", "7")


def test_run_keeps_only_verified(tmp_path):
    rows = [{"turns": [["Ali'nin 3 elması var, 4 tane daha aldı. Kaç elması oldu?", "x"]], "final": "7",
             "training_allowed": True, "source": "openai/grade-school-math"},
            {"q": "5 artı 6 kaçtır?", "a": "11", "training_allowed": True, "source": "google-deepmind/mathematics_dataset (x)"},
            {"q": "2 artı 2 kaçtır?", "a": "4", "training_allowed": False, "source": "google-deepmind/mathematics_dataset"}]
    p = tmp_path / "p.jsonl.gz"
    with gzip.open(p, "wt") as f:
        f.write("\n".join(json.dumps(r) for r in rows))
    probs = SL.load_problems([p], 10)
    assert {x["gold"] for x in probs} == {"7", "11"}

    def gen(model, bpe, prompt, max_new, temperature, seed):
        if "elma" in prompt:
            return "3 elma vardı. 4 tane daha aldı. 3 + 4 = 7. Cevap: 7"
        return "Cevap: 12"  # yanlış
    st = SL.run(None, None, probs, tmp_path / "o.jsonl.gz", k=2, generate=gen, prompt_for=chat.prompt_for)
    out = [json.loads(l) for l in gzip.open(tmp_path / "o.jsonl.gz", "rt")]
    assert st["denenen"] == 2 and st["cozulen"] == 1 and st["yazilan"] == 1
    assert out[0]["license"] == "orion-kendi" and out[0]["orion_kendi"] and out[0]["training_allowed"]
    assert "orion-kendi" in chat.EXTRA_LICENSES


def test_run_code_keeps_only_passing(tmp_path):
    probs = [{"id": "mbpp-1", "soru": "Write a function add(a, b) that returns the sum.", "testler": "assert add(2, 3) == 5",
              "source": "google-research/mbpp"},
             {"id": "apps-1", "soru": "Read two ints and print their product.", "io": [["2 3\n", "6\n"]], "source": "hendrycks/apps"}]

    def gen(model, bpe, prompt, max_new, temperature, seed):
        if "sum" in prompt:
            return "```python\ndef add(a, b):\n    return a + b\n```"
        return "```python\na, b = map(int, input().split())\nprint(a + b)\n```"  # yanlış
    st = SL.run_code(None, None, probs, tmp_path / "k.jsonl.gz", k=2, generate=gen, prompt_for=chat.prompt_for)
    rows = [json.loads(l) for l in gzip.open(tmp_path / "k.jsonl.gz", "rt")]
    assert st["denenen"] == 2 and st["gecen"] == 1 and rows[0]["license"] == "orion-kendi"
    assert rows[0]["a"].startswith("```python") and "return a + b" in rows[0]["a"]
