import json

import pytest

import prompts
from character import CharacterCard, DEFAULT_CARD
from cues import EMOJI_EMOTIONS, clean_spoken, parse_items, Emoji
from memory_store import MAX_FACTS, MAX_HISTORY_MESSAGES, Memory, MemoryStore, PendingTurns, parse_update, update_messages
from prompts import build_system_prompt, recent_emoji, screen_message, speech_message

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
    text = build_system_prompt(CARD) + prompts.screen_instruction(CARD) + speech_message("x", "y", [])
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


def test_memory_comes_after_the_parts_that_rarely_change():
    prompt = build_system_prompt(CARD, Memory(facts=["名前はアレックス"], summary="一緒に動画を見た"))
    assert prompt.index("😊") < prompt.index("名前はアレックス") < prompt.index("一緒に動画を見た")


def test_screen_message_always_asks_for_the_summary_the_bridge_reads():
    card = CharacterCard(name="テスト子", screen_instruction="好きに話して")
    content = screen_message(card, "data:image/jpeg;base64,x", [])
    assert "好きに話して" in content[0]["text"] and prompts.SUMMARY_MARKER in content[0]["text"]
    assert content[1]["image_url"]["url"] == "data:image/jpeg;base64,x"


def test_recent_emoji_come_from_her_latest_replies_only():
    history = [{"role": "assistant", "content": f"{e}ね"} for e in ("🎉", "😲", "😏", "🤭")]
    history.insert(1, {"role": "user", "content": "🥺だよ"})
    assert recent_emoji(history) == ["😲", "😏", "🤭"]


def test_recent_emoji_keep_joined_emoji_whole_and_unrepeated():
    history = [{"role": "assistant", "content": "😮‍💨はあ😮‍💨"}]
    assert recent_emoji(history) == ["😮‍💨"]


def test_messages_ask_her_to_avoid_recent_emoji():
    history = [{"role": "assistant", "content": "😲わあ"}]
    assert "😲" in speech_message("x", None, history)
    assert "😲" in screen_message(CARD, "data:image/jpeg;base64,x", history)[0]["text"]
    assert "最近" not in speech_message("x", None, [])


def test_speech_message_includes_the_screen_when_known():
    assert "東1局" in speech_message("x", "東1局", [])
    assert "直前の画面" not in speech_message("x", None, [])


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path / "memory.json")


def test_memory_survives_a_restart(store):
    store.add_exchange("こんにちは", "😊やあ", True)
    store.apply_update(["名前はアレックス"], "挨拶した", processed=1)
    again = MemoryStore(store.path)
    assert again.memory.facts == ["名前はアレックス"]
    assert again.memory.summary == "挨拶した"
    assert again.memory.history[-1] == {"role": "assistant", "content": "😊やあ"}


def test_history_stays_within_its_limit(store):
    for i in range(MAX_HISTORY_MESSAGES):
        store.add_exchange(f"発言{i}", f"返事{i}", True)
    assert len(store.memory.history) == MAX_HISTORY_MESSAGES
    assert store.memory.history[-1]["content"] == f"返事{MAX_HISTORY_MESSAGES - 1}"


def test_update_waits_for_enough_exchanges(store):
    for _ in range(7):
        store.add_exchange("（画面）", "😊うん", False)
    assert not store.needs_update()
    store.add_exchange("（画面）", "😊うん", False)
    assert store.needs_update()


def test_what_you_say_triggers_an_update_sooner(store):
    for _ in range(2):
        store.add_exchange("発言", "😊うん", True)
    assert not store.needs_update()
    store.add_exchange("発言", "😊うん", True)
    assert store.needs_update()


def test_update_keeps_exchanges_it_did_not_see(store):
    store.add_exchange("一", "😊", True)
    store.add_exchange("二", "😊", True)
    store.apply_update([], "", processed=1)
    assert [item["user"] for item in store.memory.unprocessed] == ["二"]


def test_facts_are_cleaned_and_capped(store):
    store.apply_update([" 同じ ", "同じ", 3, "", *[f"事実{i}" for i in range(MAX_FACTS + 5)]], "流れ", processed=0)
    assert store.memory.facts.count("同じ") <= 1
    assert 3 not in store.memory.facts and "" not in store.memory.facts
    assert len(store.memory.facts) == MAX_FACTS


def test_screen_comments_cannot_become_facts_about_you():
    pending = [{"user": None, "reply": "😊きみは猫が好きなんだね"}, {"user": "犬が好き", "reply": "😆いいね"}]
    prompt = update_messages(Memory(), pending)[1]["content"]
    assert prompt.count("ユーザーの発言") == 1
    assert "ユーザーの発言: 犬が好き" in prompt


def test_parse_update_reads_fenced_json():
    assert parse_update('```json\n{"facts": ["a"], "summary": "b"}\n```') == (["a"], "b")


@pytest.mark.parametrize("text", ["ごめんね", "{not json}", '{"facts": "a", "summary": "b"}', '{"facts": []}'])
def test_parse_update_rejects_anything_else(text):
    assert parse_update(text) is None


def test_forgetting_and_clearing(store):
    store.apply_update(["一", "二"], "流れ", processed=0)
    assert store.forget_fact(0) and store.memory.facts == ["二"]
    assert not store.forget_fact(5)
    store.clear()
    assert MemoryStore(store.path).memory.facts == []


def test_unreadable_memory_is_kept_aside_not_overwritten(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text("{broken", encoding="utf-8")
    store = MemoryStore(path)
    assert store.memory.facts == []
    assert (tmp_path / "memory.unreadable.json").read_text(encoding="utf-8") == "{broken"


def test_next_line_is_told_what_she_is_still_saying():
    screen = screen_message(CARD, "data:image/jpeg;base64,x", [], now_saying="😲うわ、すごい！")[0]["text"]
    speech = speech_message("ねえ", None, [], now_saying="😲うわ、すごい！")
    for text in (screen, speech):
        assert "「😲うわ、すごい！」と話している途中" in text


def test_no_note_when_she_is_not_mid_line():
    assert "話している途中" not in speech_message("ねえ", None, [])
    assert "話している途中" not in screen_message(CARD, "data:image/jpeg;base64,x", [])[0]["text"]


def test_next_line_avoids_the_emoji_she_is_using_right_now():
    assert "最近使った絵文字: 😲" in speech_message("ねえ", None, [], now_saying="😲うわ")


def test_a_discarded_line_is_never_remembered(store):
    turns = PendingTurns()
    turn_id = turns.start("（画面）", False)
    turns.set_summary(turn_id, "捨てられた状況")
    assert turns.commit(turn_id, [], store)
    assert store.memory.history == [] and store.memory.unprocessed == []
    assert store.memory.screen_summary is None


def test_commit_saves_only_the_sentences_that_played(store):
    turns = PendingTurns()
    turn_id = turns.start("発言", True)
    turns.set_summary(turn_id, "東1局")
    assert turns.commit(turn_id, ["😲うわ！"], store)
    assert store.memory.history[-1] == {"role": "assistant", "content": "😲うわ！"}
    assert store.memory.history[-2] == {"role": "user", "content": "発言"}
    assert store.memory.screen_summary == "東1局"
    assert store.memory.unprocessed == [{"user": "発言", "reply": "😲うわ！"}]


def test_a_screen_turn_counts_as_no_words_from_you(store):
    turns = PendingTurns()
    assert turns.commit(turns.start("（画面）", False), ["😊うん"], store)
    assert store.memory.unprocessed == [{"user": None, "reply": "😊うん"}]


def test_a_turn_can_only_be_committed_once(store):
    turns = PendingTurns()
    turn_id = turns.start("発言", True)
    assert turns.commit(turn_id, ["😊うん"], store)
    assert not turns.commit(turn_id, ["😊うん"], store)
    assert len(store.memory.history) == 2


def test_old_uncommitted_turns_age_out(store):
    turns = PendingTurns()
    oldest = turns.start("古い", True)
    for _ in range(PendingTurns.LIMIT):
        turns.start("新しい", True)
    assert not turns.commit(oldest, ["😊うん"], store)
