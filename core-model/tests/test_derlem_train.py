import json

from orion_core.train import load_derlem


def test_derlem_fence_and_flag(tmp_path):
    rows = [
        {"src": "Kişi1'e akşam uğrarım de", "tgt": '{"cmd":"msg.reply"}', "training_allowed": True},
        {"src": "gizli olmayan ama izinsiz", "tgt": '{"cmd":"ask"}', "training_allowed": False},
        {"src": "stabil coin ne demek", "tgt": '{"cmd":"ask"}', "training_allowed": True},  # kör sınav cümlesi: çit
    ]
    (tmp_path / "2026-11-30.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    got = load_derlem(tmp_path)
    assert [r["src"] for r in got] == ["Kişi1'e akşam uğrarım de"]
    assert got[0]["task"] == "t2c"
