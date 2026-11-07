"""The look-first reply parser, the act picker and the timeline."""

import random

import pytest

from acts import ACTS, BEAT, COMMENT, MOMENT, REPLY, choose_act
from cues import LookParser
from timeline import DECLINED, HEARD, SAID, SEEN, Timeline, ago


def run(chunks: list[str], threshold: int = 2) -> tuple[LookParser, list[str], str | None]:
    parser = LookParser(threshold, min_segment_chars=1)
    segments: list[str] = []
    emoji = None
    for chunk in chunks:
        events = parser.feed(chunk)
        segments += events.segments
        emoji = emoji or (events.emoji.char if events.emoji else None)
    events = parser.finish()
    segments += events.segments
    emoji = emoji or (events.emoji.char if events.emoji else None)
    return parser, segments, emoji


def by_character(text: str) -> list[str]:
    return list(text)


REPLY_TEXT = "見たもの: 相手がリーチした\n気になる度: 3\nセリフ: 😲えっ、もうリーチ！🤔きみ、どうする？"


@pytest.mark.parametrize("chunks", [[REPLY_TEXT], by_character(REPLY_TEXT)])
def test_speaks_only_the_line_however_it_streams(chunks):
    parser, segments, emoji = run(chunks)
    assert parser.observation == "相手がリーチした" and parser.interest == 3
    assert not parser.declined and emoji == "😲"
    assert "".join(segments) == "😲えっ、もうリーチ！🤔きみ、どうする？"


def test_below_the_bar_she_stays_quiet_and_stops_reading():
    parser = LookParser(threshold=2, min_segment_chars=1)
    for chunk in by_character("見たもの: 何も変わらない\n気になる度: 1\n"):
        assert parser.feed(chunk).segments == []
    assert parser.declined and parser.finished and parser.observation == "何も変わらない"


@pytest.mark.parametrize("line", ["なし", "（なし）", "なし。"])
def test_nothing_as_her_line_is_declining(line):
    parser, segments, _ = run(by_character(f"見たもの: 画面\n気になる度: 2\nセリフ: {line}"))
    assert parser.declined and segments == []


def test_a_line_on_the_row_after_its_label():
    parser, segments, _ = run(["見たもの: 猫\n気になる度: 2\nセリフ:\n😊かわいい猫だね。"])
    assert "".join(segments) == "😊かわいい猫だね。" and not parser.declined


def test_decorated_and_full_width_labels():
    parser, segments, _ = run(["**見たもの**：犬が走る\n- 気になる度：２\nセリフ：😆速いじゃん！"])
    assert parser.observation == "犬が走る" and parser.interest == 2 and segments == ["😆速いじゃん！"]


def test_a_reply_that_skips_the_labels_is_spoken_as_it_is():
    parser, segments, _ = run(by_character("😏へえ、やるじゃん！"))
    assert segments == ["😏へえ、やるじゃん！"] and not parser.declined and parser.observation is None


def test_anything_after_her_line_is_not_spoken():
    _, segments, _ = run([REPLY_TEXT + "\n見たもの: 別の話\nセリフ: 😊もう一回"])
    assert "".join(segments) == "😲えっ、もうリーチ！🤔きみ、どうする？"


def test_no_line_at_all_is_declining():
    parser, segments, _ = run(["見たもの: 画面\n気になる度: 3"])
    assert parser.declined and segments == []


def test_a_bar_of_zero_always_speaks():
    parser, segments, _ = run(["見たもの: 静かな画面\n気になる度: 0\nセリフ: 😪ちょっと眠くなってきた。"], threshold=0)
    assert segments == ["😪ちょっと眠くなってきた。"] and not parser.declined


def test_seeing_what_she_already_saw_declines_however_she_rates_it():
    parser = LookParser(threshold=2, min_segment_chars=1, is_stale=lambda seen: seen == "同じ手牌")
    parser.feed("見たもの: 同じ手牌\n気になる度: 3\nセリフ: 😲わあ！")
    assert parser.declined and parser.finish().segments == []


def test_seeing_something_new_still_speaks():
    parser, segments, _ = run(["見たもの: 新しい局\n気になる度: 3\nセリフ: 😲始まった！"])
    parser2 = LookParser(threshold=2, min_segment_chars=1, is_stale=lambda seen: seen == "同じ手牌")
    events = parser2.feed("見たもの: 新しい局\n気になる度: 3\nセリフ: 😲始まった！")
    assert segments and events.segments + parser2.finish().segments == segments


def test_the_same_note_repeated_is_shown_once(tmp_path):
    timeline = Timeline(None)
    timeline.add(SEEN, "下側の手牌がそろってる")
    timeline.add(SEEN, "下側の手牌がそろってる")
    timeline.add(SEEN, "下の手牌がそろってる")
    timeline.add(SAID, "😊いいね")
    timeline.add(SEEN, "下側の手牌がそろってる")
    assert timeline.render().count("手牌") == 2


def test_decided_once_she_has_rated_it():
    parser = LookParser(threshold=1)
    parser.feed("見たもの: 猫\n")
    assert not parser.decided
    parser.feed("気になる度: 2\n")
    assert parser.decided


def test_acts_follow_where_the_line_comes_from():
    assert choose_act(REPLY, []).key == "reply"
    assert choose_act(MOMENT, []).key == "reaction"
    assert choose_act(COMMENT, [], rng=random.Random(1)).key in {"opinion", "tease", "predict", "question"}


def test_no_act_three_times_running():
    for seed in range(50):
        assert choose_act(COMMENT, ["opinion", "opinion"], rng=random.Random(seed)).key != "opinion"


def test_no_question_right_after_a_question():
    for seed in range(50):
        assert choose_act(BEAT, ["question"], rng=random.Random(seed)).key != "question"
        assert choose_act(COMMENT, [], asked_last=True, rng=random.Random(seed)).key != "question"


def test_callbacks_need_something_to_recall_and_some_time_between():
    for seed in range(50):
        assert choose_act(BEAT, [], has_history=False, rng=random.Random(seed)).key != "callback"
        assert choose_act(BEAT, [], has_history=True, seconds_since_callback=30, rng=random.Random(seed)).key != "callback"
    assert any(choose_act(BEAT, [], has_history=True, rng=random.Random(s)).key == "callback" for s in range(50))


def test_every_act_says_how_long():
    for act in ACTS.values():
        assert f"{act.min_chars}〜{act.max_chars}文字" in act.describe()


def test_times_read_naturally():
    assert [ago(s) for s in (1, 40, 150, 7300)] == ["たった今", "40秒前", "2分前", "2時間前"]


def test_timeline_shows_what_happened_in_order_and_logs_it(tmp_path):
    timeline = Timeline(tmp_path)
    timeline.add(SEEN, "相手がリーチ", interest=3)
    timeline.add(DECLINED, "相手がリーチ")
    timeline.add(HEARD, "やばい")
    timeline.add(SAID, "😲えっ！", act="reaction", cut=True)
    text = timeline.render()
    assert text.index("見た: 相手がリーチ") < text.index("きみ: 「やばい」") < text.index("あなた: 「😲えっ！」（途中で止めた）")
    assert "declined" not in text
    logged = list(tmp_path.glob("*.jsonl"))[0].read_text(encoding="utf-8").splitlines()
    assert len(logged) == 5 and '"session"' in logged[0]


def test_old_events_drop_out_of_the_prompt(tmp_path):
    timeline = Timeline(None)
    old = timeline.add(SEEN, "古い")
    old.t -= 1000
    timeline.add(SEEN, "新しい")
    assert "古い" not in timeline.render() and "新しい" in timeline.render()
