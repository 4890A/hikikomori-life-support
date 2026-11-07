"""What she remembers: facts you can edit, episodes from sessions, and what the prompt gets."""

import json
import time

import pytest

from memory_store import FACTS_AFTER_HEARD, GUESS, MAX_FACTS, SAID, YOU, Memory, MemoryStore, PendingTurns, parse_json
from recall import episode_from, facts_messages, memory_text, related_episodes, transcript, when_was, worth_remembering
from timeline import HEARD, SAID as SAID_EVENT, SEEN, Event, Timeline, read_log


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path / "memory.json")


def episode(title: str, summary: str, start: float, **extra) -> dict:
    return {"log": f"{title}.jsonl", "start": start, "end": start + 60, "title": title, "summary": summary, "highlights": [], "apps": [], **extra}


def test_facts_she_learns_never_replace_yours(store):
    store.add_fact("名前はアレックス")
    store.apply_facts(["名前はアレクサンダー", "（たぶん）夜型", "猫が好き"], read=0)
    assert [(f["text"], f["source"]) for f in store.memory.facts] == [
        ("名前はアレックス", YOU), ("名前はアレクサンダー", SAID), ("夜型", GUESS), ("猫が好き", SAID)
    ]


def test_editing_a_fact_makes_it_yours(store):
    store.apply_facts(["犬が好き"], read=0)
    assert store.edit_fact(0, "犬より猫が好き")
    assert store.memory.facts[0]["source"] == YOU and store.memory.facts[0]["text"] == "犬より猫が好き"
    assert not store.edit_fact(5, "x")


def test_facts_wait_for_enough_of_your_words(store):
    for i in range(FACTS_AFTER_HEARD - 1):
        store.note_words(f"発言{i}")
    assert not store.needs_facts()
    store.note_words("最後")
    assert store.needs_facts()
    store.apply_facts([], read=1)
    assert store.memory.unread_words == ["発言1", "最後"]


def test_facts_are_cleaned_and_capped(store):
    store.apply_facts([" 同じ ", "同じ", 3, "", *[f"事実{i}" for i in range(MAX_FACTS + 5)]], read=0)
    texts = [f["text"] for f in store.memory.facts]
    assert texts.count("同じ") == 1 and len(texts) == MAX_FACTS


def test_memory_survives_a_restart(store):
    store.add_fact("名前はアレックス")
    store.add_episode(episode("麻雀の夜", "一緒に麻雀を見た", 1000.0))
    store.add_her(["パンダを審判と呼んでる"])
    again = MemoryStore(store.path)
    assert again.memory.facts[0]["text"] == "名前はアレックス"
    assert again.memory.episodes[0]["title"] == "麻雀の夜" and again.memory.her == ["パンダを審判と呼んでる"]


def test_old_memory_is_migrated(tmp_path):
    path = tmp_path / "memory.json"
    old = {"facts": ["名前はアレックス"], "summary": "麻雀を観戦した", "history": [{"role": "user", "content": "（画面を見て反応して）"}]}
    path.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    memory = MemoryStore(path).memory
    assert memory.facts[0]["text"] == "名前はアレックス" and memory.facts[0]["source"] == SAID
    assert memory.episodes[0]["summary"] == "麻雀を観戦した"


def test_forgetting_and_clearing(store):
    store.add_fact("一")
    store.add_fact("二")
    store.add_her(["あだ名"])
    assert store.forget_fact(0) and [f["text"] for f in store.memory.facts] == ["二"]
    assert store.forget_her(0) and not store.forget_her(0)
    store.clear()
    assert MemoryStore(store.path).memory.facts == []


def test_an_episode_ends_that_sessions_today_summary(store):
    store.set_today("a.jsonl", "麻雀を見てる")
    store.add_episode(episode("a", "麻雀", 1.0, log="a.jsonl"))
    assert store.memory.today == "" and store.has_episode("a.jsonl")


def test_unreadable_memory_is_kept_aside_not_overwritten(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text("{broken", encoding="utf-8")
    assert MemoryStore(path).memory.facts == []
    assert (tmp_path / "memory.unreadable.json").read_text(encoding="utf-8") == "{broken"


def test_a_turn_can_only_be_committed_once():
    turns = PendingTurns()
    turn_id = turns.start(act="reply")
    turns.add_written(turn_id, "😊うん", 1.2)
    assert turns.commit(turn_id) == {"written": {"😊うん": 1.2}, "act": "reply"}
    assert turns.commit(turn_id) is None


def test_old_uncommitted_turns_age_out():
    turns = PendingTurns()
    oldest = turns.start()
    for _ in range(PendingTurns.LIMIT):
        turns.start()
    assert turns.commit(oldest) is None


def test_parse_json_reads_fenced_json_and_rejects_the_rest():
    assert parse_json('```json\n{"facts": ["a"]}\n```') == {"facts": ["a"]}
    assert parse_json("ごめんね") is None and parse_json("{not json}") is None


def test_facts_come_only_from_your_words_and_yours_are_fixed():
    memory = Memory(facts=[{"text": "名前はアレックス", "source": YOU, "added": 0}, {"text": "夜型", "source": GUESS, "added": 0}])
    content = facts_messages(memory, ["猫を飼ってる"])[1]["content"]
    assert "本人が書いた事実: [\"名前はアレックス\"]" in content
    assert "（たぶん）夜型" in content and "ユーザーの発言: 猫を飼ってる" in content


def test_the_prompt_gets_facts_her_bits_last_time_and_today():
    now = time.time()
    memory = Memory(
        facts=[{"text": "猫が好き", "source": SAID, "added": 0}, {"text": "名前はアレックス", "source": YOU, "added": 0}],
        her=["パンダを審判と呼んでる"],
        episodes=[episode("料理動画", "カレーを作る動画を見た", now - 86400, highlights=["玉ねぎで泣いた"])],
        today="マイクラで家を建ててる",
    )
    text = memory_text(memory, now=now)
    assert text.index("名前はアレックス") < text.index("猫が好き")
    for part in ("パンダを審判", "前回: 昨日の", "料理動画", "玉ねぎで泣いた", "今日のここまで: マイクラ"):
        assert part in text


def test_greeting_knows_whether_you_have_met():
    assert "初めて" in memory_text(Memory(), greeting=True)
    assert "3日前。久しぶり" in memory_text(Memory(last_seen=time.time() - 3 * 86400), greeting=True)
    assert "5分前。久しぶりではない" in memory_text(Memory(last_seen=time.time() - 300), greeting=True)
    assert "初めて" not in memory_text(Memory())


def test_older_memories_come_back_when_they_match():
    now = time.time()
    memory = Memory(
        episodes=[
            episode("マイクラ", "マインクラフトでダイヤを探した", now - 5 * 86400, apps=["マインクラフト"]),
            episode("料理", "オムライスの動画を見た", now - 3 * 86400),
            episode("最新", "雑談した", now - 3600),
        ]
    )
    assert [e["title"] for e in related_episodes(memory, "マインクラフトでダイヤ掘ってる")] == ["マイクラ"]
    assert related_episodes(memory, "") == []


def test_times_of_past_sessions_read_naturally():
    now = time.mktime((2026, 11, 7, 21, 0, 0, 0, 0, -1))
    assert when_was(time.mktime((2026, 11, 6, 22, 0, 0, 0, 0, -1)), now) == "昨日の夜"
    assert when_was(time.mktime((2026, 11, 7, 9, 0, 0, 0, 0, -1)), now) == "今日の朝"
    assert when_was(time.mktime((2025, 12, 31, 13, 0, 0, 0, 0, -1)), now) == "ずっと前の昼"


def test_a_session_transcript_skips_repeated_notes_and_quiet_sessions_are_not_episodes():
    events = [Event(SEEN, "猫が寝てる", 0), Event(SEEN, "猫が寝てる", 5), Event(HEARD, "かわいい", 6), Event(SAID_EVENT, "😊ほんとに", 8)]
    text = transcript(events)
    assert text.count("猫が寝てる") == 1 and "きみ: かわいい" in text and "あなた: 😊ほんとに" in text
    assert worth_remembering(events) and not worth_remembering(events[:2])


def test_an_episode_is_only_made_from_a_usable_reply():
    data = {"title": "猫の動画", "summary": "猫を見た", "highlights": ["寝顔", 3, ""], "her": ["猫派"]}
    made = episode_from(data, "x.jsonl", 1.0, 2.0)
    assert made["highlights"] == ["寝顔"] and made["her"] == ["猫派"] and made["log"] == "x.jsonl"
    assert episode_from({"title": "x"}, "x.jsonl", 1.0, 2.0) is None


def test_a_finished_session_is_handed_over_with_its_log(tmp_path):
    ended = []
    timeline = Timeline(tmp_path)
    timeline.on_session_end = ended.append
    timeline.add(HEARD, "こんにちは")
    first = timeline.path
    timeline.new_session()
    assert ended == [first] and timeline.path != first
    assert [e.kind for e in read_log(first)] == ["session", "heard"]
