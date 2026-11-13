"""Ekip diyalogları (team.py): 13 ajan ajanlar.json'dan, sınav soruları eğitime girmez, sahip/kullanıcı verisi yok."""
import random

from orion_core import dialogs, team


def test_every_agent_and_count_from_shared_file():
    names = [a["name"] for a in team.agents()]
    assert len(names) == 13 and "Leo" in names and "EkBot" in names
    seen = set()
    rng = random.Random(3)
    for _ in range(3000):
        _, turns = team.team_turns(rng)
        for q, a in turns:
            seen.update(n for n in names if n in a)
            assert "@" not in a and "Eskay" not in a  # kişisel veri / depo sahibi adı yok
    assert seen == set(names)


def test_team_lines_reach_persona_data_without_exam_questions():
    lines = dialogs.persona_dialogues(4000, seed=11)
    team_lines = [l for l in lines if "ekibimde" in l.lower() or "Ekibimde" in l]
    assert team_lines, "ekip diyalogu eğitime girmiyor"
    for l in team_lines:
        q = l.split("\n")[0].removeprefix(dialogs.USER)
        assert not dialogs.is_exam_question(q)
