import json

import numpy as np

from cues import Emoji, Fragment, Punct, ReplyParser, StreamSegmenter, build_cues, clean_spoken, parse_items, split_segments


def aligned(text: str, times: dict[str, tuple[float, float]]):
    items = parse_items(text)
    for item in items:
        if isinstance(item, Fragment):
            item.phones = ["a"]
            item.start, item.end = times[item.text]
    return items


def test_parse_keeps_zwj_and_variation_emoji_whole():
    items = parse_items("ね…😮‍💨まぁ🌬️。")
    assert [i.char for i in items if isinstance(i, Emoji)] == ["😮‍💨", "🌬️"]
    assert [i.text for i in items if isinstance(i, Fragment)] == ["ね", "まぁ"]


def test_long_vowel_mark_stays_inside_words():
    items = parse_items("やったー😆！")
    assert isinstance(items[0], Fragment) and items[0].text == "やったー"
    assert isinstance(items[-1], Punct)


def test_trailing_emoji_colors_the_sentence_and_holds_until_speech_resumes():
    items = aligned("今日はね、楽しかった😊。次は", {"今日はね": (1.0, 1.5), "楽しかった": (1.8, 2.5), "次は": (3.0, 3.4)})
    cues = build_cues(items, [], 4.0)
    assert [(c.emotion, c.kind, c.start, c.end) for c in cues] == [("happy", "trailing", 1.0, 3.0)]


def test_leading_emoji_starts_at_the_sound_performed_in_the_gap():
    items = aligned("あって…😮‍💨まぁ。", {"あって": (0.5, 1.0), "まぁ": (3.0, 3.5)})
    cues = build_cues(items, [(0.5, 1.0), (1.8, 2.4), (3.0, 3.5)], 4.0)
    assert [(c.emotion, c.kind, c.start, c.end) for c in cues] == [("sigh", "leading", 1.8, 4.0)]


def test_leading_emoji_without_gap_sound_starts_at_speech():
    items = aligned("😊はい。", {"はい": (0.4, 0.8)})
    cues = build_cues(items, [(0.4, 0.8)], 2.0)
    assert (cues[0].start, cues[0].kind) == (0.4, "leading")


def test_later_cue_cuts_off_the_earlier_one():
    items = aligned(
        "恥ずかしい🫣…😮‍💨まぁ。", {"恥ずかしい": (0.5, 1.5), "まぁ": (3.0, 3.5)}
    )
    cues = build_cues(items, [(0.5, 1.5), (2.0, 2.5), (3.0, 3.5)], 4.0)
    assert [(c.emotion, c.start, c.end) for c in cues] == [("embarrassed", 0.5, 2.0), ("sigh", 2.0, 4.0)]


def test_second_emoji_only_reaches_back_to_the_previous_expression():
    items = aligned("嬉しい😊、悲しい😭。", {"嬉しい": (0.5, 1.0), "悲しい": (1.5, 2.0)})
    cues = build_cues(items, [], 3.0)
    assert [(c.emotion, c.start) for c in cues] == [("happy", 0.5), ("sad", 1.5)]


def test_voice_only_emoji_has_no_cue():
    items = aligned("もしもし📞。", {"もしもし": (0.5, 1.0)})
    assert build_cues(items, [], 2.0) == []


def test_arm_pose_needs_a_long_enough_cue():
    items = aligned("うーん🤔。", {"うーん": (0.5, 1.2)})
    assert build_cues(items, [], 3.0)[0].as_dict()["arms"] is True
    items = aligned("うーん🤔。次", {"うーん": (0.5, 0.8), "次": (1.0, 1.2)})
    assert build_cues(items, [], 3.0)[0].as_dict()["arms"] is False


def test_cue_with_numpy_times_is_json_serializable():
    start, end = np.float64(0.5), np.float64(1.2)
    items = aligned("うーん🤔。", {"うーん": (start, end)})
    json.dumps(build_cues(items, [], np.float64(3.0))[0].as_dict())


def test_segments_split_at_sentence_ends_and_keep_emoji_with_their_sentence():
    a = "あ" * 40
    assert split_segments(f"{a}😊。{a}😭！") == [f"{a}😊。", f"{a}😭！"]


def test_short_tail_is_merged_instead_of_synthesized_alone():
    a = "あ" * 50
    assert split_segments(f"{a}。いっか。") == [f"{a}。いっか。"]


def test_long_sentence_splits_at_commas():
    a = "あ" * 50
    assert split_segments(f"{a}、{a}。") == [f"{a}、", f"{a}。"]


def run_parser(deltas: list[str]):
    parser = ReplyParser()
    events = [parser.feed(delta) for delta in deltas] + [parser.finish()]
    return parser, [e.emoji.char for e in events if e.emoji], [s for e in events for s in e.segments]


def test_segmenter_joins_sentences_split_across_deltas():
    segmenter = StreamSegmenter()
    assert segmenter.feed("今日はとても楽し") == []
    assert segmenter.feed("かったよ。") == []  # A trailing emoji might still follow.
    assert segmenter.feed("次もがんばろうね") == ["今日はとても楽しかったよ。"]
    assert segmenter.flush() == ["次もがんばろうね"]


def test_segmenter_moves_emoji_after_punctuation_to_the_text_it_opens():
    segmenter = StreamSegmenter()
    segmenter.feed("今日はとても楽しかったよ！")
    assert segmenter.feed("😊次もね") == ["今日はとても楽しかったよ！"]
    assert segmenter.flush() == ["😊次もね"]


def test_segmenter_keeps_a_final_emoji_with_the_last_sentence():
    segmenter = StreamSegmenter()
    segmenter.feed("今日はとても楽しかったよ！😊")
    assert segmenter.flush() == ["今日はとても楽しかったよ！😊"]


def test_segmenter_keeps_a_joined_emoji_whole_when_moving_it():
    segmenter = StreamSegmenter()
    segmenter.feed("今日はとても楽しかったよ。😮‍💨")
    assert segmenter.feed("まぁね") == ["今日はとても楽しかったよ。"]
    assert segmenter.flush() == ["😮‍💨まぁね"]


def _emotions(text: str, times: dict[str, tuple[float, float]], duration: float = 5.0):
    items = aligned(text, times)
    spans = list(times.values())
    return [(c.emotion, round(c.start, 2)) for c in build_cues(items, spans, duration)]


def test_two_opening_emoji_in_separate_segments_each_get_a_cue():
    assert _emotions("😲わ、すごい！", {"わ": (0.1, 0.3), "すごい": (0.5, 1.0)}) == [("surprised", 0.1)]
    assert _emotions("🤭可愛いね。", {"可愛いね": (0.1, 0.8)}) == [("happy", 0.1)]


def test_emoji_after_opened_text_starts_the_next_part_instead_of_overwriting():
    cues = _emotions("😟あらら😮‍💨大変だね。", {"あらら": (0.1, 0.6), "大変だね": (1.0, 1.8)})
    assert cues == [("worried", 0.1), ("sigh", 1.0)]


def test_emoji_after_unopened_text_still_colors_that_text():
    cues = _emotions("えへへ🤭、今日は楽しかったよ😊。", {"えへへ": (0.1, 0.5), "今日は楽しかったよ": (0.8, 1.8)})
    assert cues == [("happy", 0.1)]


def test_segmenter_merges_short_sentences_with_the_next():
    segmenter = StreamSegmenter()
    assert segmenter.feed("えっ！もうリーチなの？ちょっと") == ["えっ！もうリーチなの？"]
    assert segmenter.flush() == ["ちょっと"]


def test_segmenter_flushes_a_short_reply():
    segmenter = StreamSegmenter()
    assert segmenter.feed("おっ！") == []
    assert segmenter.flush() == ["おっ！"]
    assert segmenter.flush() == []


def test_clean_spoken_removes_broken_emoji_and_other_scripts():
    assert clean_spoken("😮\u200dฟその手、 playerwinは38000点だよ！") == "😮その手、は38000点だよ！"


def test_clean_spoken_keeps_whole_emoji_sequences():
    assert clean_spoken("😮‍💨まぁ🌬️ね。") == "😮‍💨まぁ🌬️ね。"


def test_parser_reports_the_face_before_any_sentence_ends():
    parser = ReplyParser()
    assert parser.feed("😲").emoji is None  # The next delta could extend the emoji.
    events = parser.feed("えっ")
    assert events.emoji is not None and events.emoji.emotion == "surprised"
    assert events.segments == []
    assert parser.feed("、もう").emoji is None


def test_parser_waits_for_a_joined_emoji_split_across_deltas():
    _, emoji, _ = run_parser(["😮", "\u200d💨", "まぁね"])
    assert emoji == ["😮‍💨"]


def test_parser_without_a_leading_emoji_shows_no_early_face():
    _, emoji, segments = run_parser(["もうリーチなの😲？"])
    assert emoji == []
    assert segments == ["もうリーチなの😲？"]


def test_parser_ignores_a_leading_emoji_with_no_expression():
    _, emoji, _ = run_parser(["📞もしもし、聞こえてる？"])
    assert emoji == []


def test_parser_finish_reports_an_emoji_only_reply():
    _, emoji, segments = run_parser(["😲"])
    assert emoji == ["😲"]
    assert segments == []


def test_parser_never_speaks_the_summary():
    parser, _, segments = run_parser(["😲えっ、すごい展開になってきたね！\n[", "[状況", "]] 東4局で親がリーチ"])
    assert segments == ["😲えっ、すごい展開になってきたね！"]
    assert parser.summary == "東4局で親がリーチ"


def test_parser_releases_a_lone_bracket():
    _, _, segments = run_parser(["これは[", "テストなんだけど"])
    assert segments == ["これはテストなんだけど"]


def test_parser_reads_a_summary_with_a_different_label():
    parser, _, _ = run_parser(["いい感じだね、その調子！\n[[リーチがかかってる]]"])
    assert parser.summary == "リーチがかかってる"


def test_parser_summary_on_the_line_after_its_label():
    parser, _, _ = run_parser(["いい感じだね、その調子！\n[[状況]]\n東4局で一位"])
    assert parser.summary == "東4局で一位"


def test_parser_cuts_a_reply_that_repeats_after_its_summary():
    parser, _, segments = run_parser(["😱おっ、チャンスあるじゃん！\n[[状況]] 南4場で終盤😱おっ、チャンスあるじゃん！\n[[状況]] 南4場で終盤"])
    assert segments == ["😱おっ、チャンスあるじゃん！"]
    assert parser.summary == "南4場で終盤"


def test_parser_stops_when_a_sentence_repeats():
    parser, _, segments = run_parser(["今日はとても楽しかったよ。今日はとても楽しかったよ。また遊ぼうね。"])
    assert segments == ["今日はとても楽しかったよ。"]
    assert parser.finished


def test_parser_stops_speaking_past_the_length_cap():
    sentence = "これはとても長い文章のテストなんだけど{}番目だよ。"
    parser = ReplyParser()
    segments = [s for i in range(10) for s in parser.feed(sentence.format("一二三四五六七八九十"[i])).segments]
    assert parser.finished
    assert 3 <= len(segments) <= 4


def test_parser_has_no_summary_when_none_was_written():
    parser, _, _ = run_parser(["おめでとう、よく上がれたね！"])
    assert parser.summary is None


def test_parser_speaks_the_last_sentence_as_soon_as_the_summary_starts():
    parser = ReplyParser()
    assert parser.feed("😲えっ、すごい展開になってきたね！\n[").segments == []
    assert parser.feed("[状況").segments == ["😲えっ、すごい展開になってきたね！"]
    assert parser.feed("]] 東4局").segments == []
    assert parser.finish().segments == []
    assert parser.summary == "東4局"