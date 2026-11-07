import json

import prompts
from character import CharacterCard, DEFAULT_CARD
from cues import EMOJI_EMOTIONS, clean_spoken, parse_items, Emoji
from acts import ACTS
from prompts import build_system_prompt, look_message, recent_emoji, reply_message

CARD = CharacterCard.model_validate(json.loads(DEFAULT_CARD.read_text(encoding="utf-8")))


def test_prompt_lists_every_expression_emoji_except_those_left_out():
    guide = prompts.emoji_guide()
    for emoji in EMOJI_EMOTIONS:
        assert (emoji in guide) == (emoji not in prompts.LEFT_OUT_OF_PROMPT)


def test_prompt_gives_every_expression_a_name():
    assert set(EMOJI_EMOTIONS.values()) <= set(prompts.EMOTION_NAMES)


def test_voice_meanings_describe_only_mapped_emoji():
    assert set(prompts.VOICE_MEANINGS) <= set(EMOJI_EMOTIONS)


def test_voice_only_emoji_have_no_expression():
    assert not set(prompts.VOICE_ONLY_EMOJI) & set(EMOJI_EMOTIONS)


def test_overused_sound_effects_are_not_offered():
    for emoji in ("🥤", "🤐", "👃", "👅", "💋"):
        assert emoji not in build_system_prompt(CARD)


def test_prompt_emoji_survive_parsing_whole():
    for emoji in [*EMOJI_EMOTIONS, *prompts.VOICE_ONLY_EMOJI]:
        assert clean_spoken(f"{emoji}テスト") == f"{emoji}テスト"


def test_default_card_is_not_about_one_kind_of_content():
    text = build_system_prompt(CARD) + look_message(CARD, "data:,", "", ACTS["opinion"], 2, [])[0]["text"] + reply_message("x", "", ACTS["reply"], [])
    for word in ("麻雀", "牌", "プレイヤー"):
        assert word not in text

def test_default_card_examples_use_only_offered_emoji_and_open_with_a_face():
    offered = {*EMOJI_EMOTIONS, *prompts.VOICE_ONLY_EMOJI} - prompts.LEFT_OUT_OF_PROMPT
    for example in CARD.examples:
        emoji = [item for item in parse_items(example) if isinstance(item, Emoji)]
        assert {item.char for item in emoji} <= offered, example
        assert emoji[0].emotion is not None and example.startswith(emoji[0].char), example
        assert len(emoji) in (2, 3), example


def test_card_fields_all_reach_the_prompt():
    card = CharacterCard(
        name="テスト子", personality="性格X", speech_style="話し方X", scenario="状況X",
        likes=["好きX"], dislikes=["苦手X"], rules=["ルールX"], examples=["😊例X"],
    )
    prompt = build_system_prompt(card)
    for text in ("テスト子", "性格X", "話し方X", "状況X", "好きX", "苦手X", "ルールX", "😊例X"):
        assert text in prompt


def test_technical_emoji_rules_stay_when_a_card_has_no_rules():
    prompt = build_system_prompt(CharacterCard(name="テスト子"))
    assert "返事の最初の文字" in prompt and "😊" in prompt


def test_screen_text_is_treated_as_data_not_instructions():
    assert prompts.SAFETY_RULE in build_system_prompt(CharacterCard(name="テスト子"))


def test_empty_sections_are_left_out():
    prompt = build_system_prompt(CharacterCard(name="テスト子"))
    assert "好きなもの" not in prompt and "覚えていること" not in prompt


def test_look_message_asks_for_what_the_bridge_reads_in_order():
    card = CharacterCard(name="テスト子", screen_instruction="好きに話して")
    content = look_message(card, "data:image/jpeg;base64,x", "文脈", ACTS["question"], 2, [])
    text = content[0]["text"]
    assert "好きに話して" in text and "文脈" in text and "質問" in text
    assert text.index("見たもの:") < text.index("気になる度:") < text.index("セリフ:")
    assert "2未満なら「なし」" in text
    assert content[1]["image_url"]["url"] == "data:image/jpeg;base64,x"


def test_a_line_that_must_be_said_has_no_way_out():
    text = look_message(CARD, "data:,", "", ACTS["smalltalk"], 0, [])[0]["text"]
    assert "なし" not in text.split("セリフ:")[1]


def test_recent_emoji_come_from_her_latest_lines_only():
    assert recent_emoji([f"{e}ね" for e in ("🎉", "😲", "😏", "🤭")]) == ["😲", "😏", "🤭"]


def test_recent_emoji_keep_joined_emoji_whole_and_unrepeated():
    assert recent_emoji(["😮‍💨はあ😮‍💨"]) == ["😮‍💨"]


def test_messages_ask_her_to_avoid_recent_emoji():
    assert "😲" in reply_message("x", "", ACTS["reply"], ["😲わあ"])
    assert "😲" in look_message(CARD, "data:,", "", ACTS["opinion"], 2, ["😲わあ"])[0]["text"]
    assert "最近" not in reply_message("x", "", ACTS["reply"], [])


def test_a_reply_carries_the_screen_when_given():
    content = reply_message("これ何？", "", ACTS["reply"], [], image_url="data:image/jpeg;base64,x")
    assert "これ何？" in content[0]["text"] and content[1]["image_url"]["url"] == "data:image/jpeg;base64,x"
    assert isinstance(reply_message("x", "", ACTS["reply"], []), str)


def test_context_shows_the_timeline_and_notes():
    text = prompts.context_block("- 10秒前 見た: 猫", 23, notes=["まだ答えていない"])
    assert "23分目" in text and "見た: 猫" in text and "（まだ答えていない）" in text
    assert "まだ何もない" in prompts.context_block("", 0)

def test_next_line_is_told_what_she_is_still_saying():
    screen = look_message(CARD, "data:,", "", ACTS["opinion"], 2, [], now_saying="😲うわ、すごい！")[0]["text"]
    speech = reply_message("ねえ", "", ACTS["reply"], [], now_saying="😲うわ、すごい！")
    for text in (screen, speech):
        assert "「😲うわ、すごい！」と話している途中" in text


def test_no_note_when_she_is_not_mid_line():
    assert "話している途中" not in reply_message("ねえ", "", ACTS["reply"], [])
    assert "話している途中" not in look_message(CARD, "data:,", "", ACTS["opinion"], 2, [])[0]["text"]


def test_verbal_habits_are_pointed_out():
    lines = ["😲わ、すごいじゃん！", "😊いい感じじゃん", "🤔え、なにそれ？", "😆わ、やったね"]
    assert prompts.repeated_habits(lines) == ["じゃん", "わ、"]
    assert prompts.repeated_habits(["😊いいね", "🤔どうかな"]) == []
    assert "「じゃん」「わ、」ばかり" in reply_message("x", "", ACTS["reply"], lines)


def test_next_line_avoids_the_emoji_she_is_using_right_now():
    assert "最近使った絵文字: 😲" in reply_message("ねえ", "", ACTS["reply"], [], now_saying="😲うわ")
