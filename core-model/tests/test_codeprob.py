"""Kod sınavı ve kum havuzu: doğru çözüm geçer, yanlış/sonsuz döngü geçmez; MBPP/APPS diyalog biçimi."""
import json

from orion_core import codeexec as X, codeprob as P


def test_sandbox_pass_fail_timeout():
    assert X.passes_asserts("def f(x):\n    return x + 1\n", "assert f(1) == 2")
    assert not X.passes_asserts("def f(x):\n    return x\n", "assert f(1) == 2")
    ok, _, err = X.run_python("while True:\n    pass\n", timeout=1.5)
    assert not ok and "zaman" in err
    assert X.passes_io("print(sum(map(int, input().split())))", [("1 2\n", "3\n"), ("5 5", "10")])
    assert X.extract_code("İşte:\n```python\ndef g():\n    return 1\n```") == "def g():\n    return 1"


def test_humaneval_exam_scoring():
    probs = [{"task_id": "T/0", "prompt": "def add(a, b):\n", "entry_point": "add",
              "test": "def check(c):\n    assert c(2, 3) == 5\n"},
             {"task_id": "T/1", "prompt": "def neg(a):\n", "entry_point": "neg",
              "test": "def check(c):\n    assert c(2) == -2\n"}]
    good = {"T/0": "```python\n    return a + b\n```", "T/1": "```python\ndef neg(a):\n    return a\n```"}
    st = P.humaneval_exam(probs, lambda q: good["T/0"] if "add" in q else good["T/1"])
    assert st["gecen"] == 1 and st["toplam"] == 2 and st["puan"] == 0.5


def test_training_dialogs_format(tmp_path):
    rows = [{"id": "mbpp-1", "soru": "Write a function to add two numbers.", "kod": "def add(a,b):\n    return a+b",
             "license": "apache-2.0", "source": "google-research/mbpp", "attribution": "MBPP"}]
    d = P.training_dialogs(rows)
    assert d[0]["q"].startswith(P.Q_PREFIX) and d[0]["a"].startswith("```python") and d[0]["training_allowed"]
    from orion_core.chat import EXTRA_LICENSES
    assert "apache-2.0" in EXTRA_LICENSES and "mit" in EXTRA_LICENSES


def test_code_answers_pass_clean_pair():
    from orion_core import dialogs
    q = "Şu problemi Python ile çöz:\nWrite a function to find the maximum of a list of integers without using max()."
    a = "```python\ndef mx(xs):\n    m = xs[0]\n    for x in xs:\n        if x > m:\n            m = x\n    return m\n```"
    assert dialogs.clean_pair(q, a) == (q, a)
    assert dialogs.clean_pair("What is the weather like today in London city?", "It is sunny and warm today in the city") is None
