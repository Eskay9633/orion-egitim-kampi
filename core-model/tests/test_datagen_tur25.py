"""Tur 25: Emma ailesi şemaya uyar, çitli sınav cümlelerinden uzak kalır ve karışımda pay alır."""
import random
from collections import Counter

from orion_core import datagen


def test_tur25_valid_and_varied():
    rng = random.Random(25)
    cmds = Counter()
    for _ in range(3000):
        cmd, tr, args = datagen._gap_tur25(rng)
        datagen.validate_request({"v": 1, "id": "t", "cmd": cmd, "args": args})
        cmds[cmd] += 1
        assert tr.strip() and all(v not in ("", None) for v in args.values())
        if cmd == "reminder.set":
            assert args["repeat"] in ("daily", "weekly") and "@" in args["at"]
        if cmd == "calendar.add" and "place" in args:
            assert args["place"] in tr
    assert set(cmds) == {"reminder.set", "calendar.add", "timer.start", "reminder.list", "calendar.list"}


def test_tur25_share_in_realgap():
    rng = random.Random(7)
    seen = Counter(datagen.realgap_example(rng)[0] for _ in range(4000))
    assert seen["timer.start"] > 0 and seen["reminder.list"] > 0
