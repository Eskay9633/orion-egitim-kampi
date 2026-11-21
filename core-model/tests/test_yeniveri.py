from orion_core.yeniveri import _third_person, ajan_diyaloglari, komut_diyaloglari, row_turns
from orion_core.massive import held_out_keys, norm_key


def test_row_formats():
    assert row_turns({"messages": [{"role": "user", "content": "selam"}, {"role": "assistant", "content": "merhaba"}]}) == [("selam", "merhaba")]
    assert row_turns({"instruction": "özetle", "input": "metin", "output": "özet"}) == [("özetle\nmetin", "özet")]
    assert row_turns({"conversations": [{"from": "human", "value": "a"}, {"from": "gpt", "value": "b"}]}) == [("a", "b")]
    assert row_turns({"foo": 1}) == []


def test_third_person():
    assert _third_person("ürün yöneticisisin, teslimleri birleştirirsin") == "ürün yöneticisi, teslimleri birleştirir"
    assert _third_person("kesin") == "kesin"


def test_orion_rows_fenced():
    a = ajan_diyaloglari()
    assert len(a) >= 40 and all(r["license"] == "orion-kendi" and r["training_allowed"] for r in a)
    k = komut_diyaloglari(800)
    held = held_out_keys()
    assert k and not any(norm_key(r["q"]) in held for r in k)
