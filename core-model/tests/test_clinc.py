"""CLINC150 dönüştürücü: eşleme, atlama, çeviri sonrası satırların protokolden geçmesi (ağsız)."""
from orion_core import clinc


def test_label_mapping():
    assert clinc.label("reminder", "what are my reminders") == ("reminder.list", {}, "action")
    assert clinc.label("calendar", "what's on my calendar today") == ("calendar.list", {"day": "d+0"}, "action")
    assert clinc.label("calendar", "what's on my calendar for march 3") is None  # gün argümanı taşınamaz
    assert clinc.label("what_can_i_ask_you", "what can you do") == ("help", {}, "action")
    assert clinc.label("greeting", "hi there")[2] == "chat"
    assert clinc.label("book_flight", "book me a flight to boston") == ("ask", {}, "neg")
    assert clinc.label("oos", "how do i make a paper plane") == ("ask", {}, "neg")
    for skipped in ("alarm", "timer", "translate", "calculator", "todo_list_update"):
        assert clinc.label(skipped, "x") is None


def test_build_and_finish():
    data = {"train": [["what are my reminders", "reminder"], ["book me a flight to boston", "book_flight"],
                      ["set an alarm for 7", "alarm"], ["hi there", "greeting"]],
            "oos_train": [["how do i make a paper plane", "oos"]]}
    rows, stats = clinc.build(data)
    assert len(rows) == 4 and stats["atlandı:alarm"] == 1
    tr = ["hatırlatıcılarım neler", "bana Boston'a bir uçuş ayarla lütfen", "merhaba", "kağıttan uçak nasıl yapılır?"]
    out, st = clinc.finish(rows, tr, None)
    assert [r["cmd"] for r in out] == ["reminder.list", "ask", "ask", "ask"]
    ask = [r for r in out if r["cmd"] == "ask"][0]
    assert '"question":"bana Boston\'a bir uçuş ayarla"' in ask["tgt"], ask["tgt"]
    assert all(r["training_allowed"] is True and r["source"] == "clinc150" for r in out)


def test_extra_rows_leaking_into_eval_are_dropped(tmp_path):
    import json
    from orion_core import massive
    (tmp_path / massive.TRAIN_FILE).write_text(json.dumps({"src": "alarm kur", "tgt": "x", "kind": "action", "training_allowed": True}) + "\n")
    for name in massive.EVAL_FILES.values():
        (tmp_path / name).write_text(json.dumps({"src": "merhaba"}) + "\n")
    (tmp_path / "clinc-tr.jsonl").write_text(
        json.dumps({"src": "merhaba", "tgt": "y", "kind": "chat", "training_allowed": True}) + "\n" +
        json.dumps({"src": "uçak bileti al", "tgt": "z", "kind": "neg", "training_allowed": True}) + "\n")
    rows = massive.load_train(tmp_path)
    assert [r["src"] for r in rows] == ["alarm kur", "uçak bileti al"]
    assert rows[1]["pool"] == "clinc_neg"


def test_extra_action_rows_are_not_trained(tmp_path):
    import json
    from orion_core import massive
    (tmp_path / massive.TRAIN_FILE).write_text("")
    for name in massive.EVAL_FILES.values():
        (tmp_path / name).write_text(json.dumps({"src": "x"}) + "\n")
    (tmp_path / "clinc-tr.jsonl").write_text(json.dumps({"src": "hatırlatıcılarım", "tgt": "r", "kind": "action", "training_allowed": True}) + "\n")
    assert massive.load_train(tmp_path) == []
