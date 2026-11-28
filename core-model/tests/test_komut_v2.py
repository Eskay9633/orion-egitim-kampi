"""Veri seti v2: yalnız eğitime girer, sınav kümeleri değişmez; argüman sözcükleri bozulmaz."""
import json
import random

from orion_core import datagen, komut_v2
from orion_core.protocol import validate_request


def test_roughen_keeps_arguments():
    rng = random.Random(3)
    for _ in range(300):
        src = "yarın 10'da annemi aramayı hatırlat"
        out = komut_v2.roughen(rng, src, {"text": "annemi aramayı", "at": "d+1@10:00"})
        assert "annemi aramayı" in out


def test_new_patterns_valid_and_grammatical():
    rng = random.Random(1)
    for _ in range(200):
        cmd, src, args = komut_v2.new_pattern(rng)
        validate_request({"v": 1, "id": "t", "cmd": cmd, "args": args})
        assert "Babam'e" not in src and "Mustafa'e" not in src
    assert komut_v2._dat("Babam") == "Babam'a" and komut_v2._gen("Mustafa") == "Mustafa'nın"


def test_train_stream_has_v2():
    ex = datagen.generate(3000, "train", seed=9)
    assert any(json.loads(e["tgt"]).get("args", {}).get("action") == "auto" for e in ex if e["task"] == "t2c")
