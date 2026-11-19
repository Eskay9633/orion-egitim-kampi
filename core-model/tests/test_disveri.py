"""Dış veri (Banking77, SNIPS, SGD, TOPv2): ayrıştırıcılar yalnız 'Orion yapamaz' satırı üretir; kripto ve Orion'da
karşılığı olan hizmetler girmez. İnternetsiz."""
from orion_core import disveri as D


def test_banking_skips_exchange_and_crypto():
    rows = D.parse_banking("text,category\nWhere is my card?,card_arrival\nWhat is the exchange rate?,exchange_rate\n"
                           "Can I buy bitcoin?,card_arrival\n")
    assert [r["en"] for r in rows] == ["Where is my card?"]
    assert all(r["cmd"] == "ask" and r["kind"] == "neg" and r["source"] == "banking77" for r in rows)


def test_snips_joins_spans():
    doc = {"GetWeather": [{"data": [{"text": "weather in "}, {"text": "Paris", "entity": "city"}]}]}
    assert D.parse_snips("GetWeather", doc)[0]["en"] == "weather in Paris"


def test_sgd_skips_calendar_alarm_and_uses_first_user_turn():
    dl = [{"services": ["Flights_1"], "turns": [{"speaker": "USER", "utterance": "Find me a flight to Rome",
                                                   "frames": [{"service": "Flights_1", "state": {"active_intent": "SearchOnewayFlight"}}]}]},
          {"services": ["Calendar_1"], "turns": [{"speaker": "USER", "utterance": "What is on my calendar", "frames": [{}]}]}]
    rows = D.parse_sgd(dl)
    assert [r["en"] for r in rows] == ["Find me a flight to Rome"]
    assert rows[0]["intent"] == "Flights_1/SearchOnewayFlight"


def test_topv2_only_cannot_do_intents():
    tsv = ("domain\tutterance\tsemantic_parse\n"
           "alarm\tdelete my 7 am alarm\t[IN:DELETE_ALARM delete my [SL:ALARM_NAME 7 am ] alarm ]\n"
           "alarm\tset an alarm for 7\t[IN:CREATE_ALARM set an alarm for [SL:DATE_TIME 7 ] ]\n"
           "weather\tweather and remind me\t[IN:GET_WEATHER weather [SL:X [IN:CREATE_REMINDER remind ] ] ]\n")
    rows = D.parse_topv2(tsv)
    assert [r["en"] for r in rows] == ["delete my 7 am alarm"]


def test_cap_dedupes():
    import random
    rows = [D._row("snips", "Play jazz", "PlayMusic"), D._row("snips", "play jazz", "PlayMusic")]
    assert len(D._cap(rows, 10, random.Random(1))) == 1
