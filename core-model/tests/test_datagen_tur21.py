"""Tur 21: gerçek cümle açıkları (saatsiz gün sözlü hatırlatıcı, yapılamayan istek → ask). Yalnızca eğitim akışı."""
import random

from orion_core import datagen
from orion_core.protocol import validate_request


def test_realgap_valid_and_fenced():
    rng = random.Random(5)
    for _ in range(2000):
        cmd, tr, args = datagen.realgap_example(rng)
        validate_request({"v": 1, "id": "g", "cmd": cmd, "args": args})
        assert not datagen._fenced(tr)
        assert not datagen._gap_ext_fenced(tr)
        if cmd == "ask":
            assert args["question"] == tr
        elif cmd == "reminder.set":
            assert "@" in args["at"] or args["at"].startswith("+")  # Tur 26: göreli ("20 dakika sonra")
        elif cmd == "research.start":
            assert args["topic"] in tr
        elif cmd == "note.search":
            assert args["query"] in tr
        elif cmd == "calendar.list":
            assert args["day"].startswith("d+")  # Tur 25-26
        elif cmd in ("msg.reply", "msg.contacts", "memory.save", "calc.eval", "skill.list", "work.digest", "health.check"):
            pass  # Tur 24 (şema validate_request ile denetlendi)
        elif cmd in ("calendar.add", "timer.start", "reminder.list"):
            pass  # Tur 25 Emma ailesi (test_datagen_tur25)
        elif cmd != "msg.inbox":
            # Tur 26: tüm ajanların komutları (şema validate_request ile denetlendi)
            assert cmd in {c for cs in datagen.T26_AGENT_CMDS.values() for c in cs} | {"ask"}


def test_tur23_team_capabilities_present():
    rng = random.Random(11)
    cmds = {datagen._gap_team(rng)[0] for _ in range(400)}
    assert cmds == {"calendar.list", "research.start", "msg.inbox", "note.search"}


def test_day_only_reminder_defaults_to_nine():
    rng = random.Random(7)
    seen = 0
    for _ in range(500):
        cmd, tr, args = datagen._gap_day_reminder(rng)
        if not any(c.isdigit() for c in tr):
            seen += 1
            assert args["at"].endswith("@09:00"), (tr, args)
            assert not args["at"].startswith("d+0") or "bugün" in tr.lower()
    assert seen > 100


def test_realgap_only_in_training_stream():
    srcs = {e["src"] for e in datagen.t2c_set(4000, "train", seed=31)}
    gap = {t for t in srcs if "unutmamam için hatırlat" in t or "kişilik masa ayırt" in t or "alarmımı" in t}
    assert gap, "gerçek açık ailesi eğitim akışında görünmüyor"
    for split in ("test_iid", "test_ood"):
        test = {e["src"] for e in datagen.t2c_set(1000, split, seed=31)}
        assert not any("unutmamam için hatırlat" in t or "kişilik masa ayırt" in t for t in test)


def test_tur22_inbox_and_agent_talk():
    rng = random.Random(9)
    seen = set()
    for _ in range(400):
        cmd, tr, args = datagen._gap_agent(rng)
        validate_request({"v": 1, "id": "g", "cmd": cmd, "args": args})
        seen.add(cmd)
        if cmd == "ask":
            assert args["question"] == tr
    assert seen == {"msg.inbox", "ask"}
