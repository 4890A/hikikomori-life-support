"""What kind of line she says this turn, so she doesn't make the same kind of remark every time.

The program picks the act and its length, and the prompt asks the model for it. Leaving variety to
the model alone gave one reaction-plus-observation after another.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

# Why a line is being made, from the browser's turn-taking.
REPLY, MOMENT, COMMENT, BEAT, GREETING = "reply", "moment", "comment", "beat", "greeting"
CALLBACK_EVERY_SECONDS = 180
REPLY_QUESTION_CHANCE = 0.3


@dataclass(frozen=True)
class Act:
    key: str
    name: str
    instruction: str
    min_chars: int
    max_chars: int

    def describe(self) -> str:
        return f"今回の役目: {self.name}。{self.instruction}{self.min_chars}〜{self.max_chars}文字。"


ACTS = {
    "reaction": Act("reaction", "リアクション", "画面で起きたことに、短く素直に反応する。", 5, 15),
    "opinion": Act("opinion", "感想", "見えていることへの自分の感想や好き嫌いを言う。", 15, 35),
    "tease": Act("tease", "ツッコミ", "きみや画面の展開に、軽くツッコむか、からかう。", 15, 35),
    "predict": Act("predict", "予想", "この先どうなりそうか軽く予想する。外れてもいい。", 15, 35),
    "question": Act("question", "質問", "きみに答えやすい短い質問をひとつする。", 10, 30),
    "callback": Act("callback", "思い出話", "少し前にあったことや話したことを思い出して、今とつなげる。", 20, 50),
    "smalltalk": Act("smalltalk", "雑談", "画面から少し離れて、自分の好きなものや、きみのことを話題にする。", 15, 50),
    "reply": Act("reply", "返事", "きみの言ったことに、まず答える。", 15, 60),
    "greeting": Act(
        "greeting",
        "あいさつ",
        "見せてもらうものが始まるところであいさつする。前に会ったことがあれば、前回のことや久しぶりかどうかに軽く触れる。",
        10,
        40,
    ),
}

WEIGHTS = {
    COMMENT: {"opinion": 3, "tease": 2, "predict": 2, "question": 2, "callback": 1},
    BEAT: {"smalltalk": 3, "question": 2, "callback": 2},
}


def choose_act(
    source: str,
    recent: list[str],
    asked_last: bool = False,
    seconds_since_callback: float = float("inf"),
    has_history: bool = False,
    rng: random.Random | None = None,
) -> Act:
    """recent: the keys of her latest acts, oldest first. asked_last: her last line was a question."""
    rng = rng or random.Random()
    if source == REPLY:
        act = ACTS["reply"]
        if rng.random() < REPLY_QUESTION_CHANCE and not asked_last:
            act = replace(act, instruction=act.instruction + "最後に短い質問を返してもいい。")
        return act
    if source == MOMENT:
        return ACTS["reaction"]
    if source == GREETING:
        return ACTS["greeting"]
    weights = dict(WEIGHTS.get(source, WEIGHTS[COMMENT]))
    if asked_last or "question" in recent[-2:]:
        weights.pop("question", None)
    if not has_history or seconds_since_callback < CALLBACK_EVERY_SECONDS:
        weights.pop("callback", None)
    if len(recent) >= 2 and recent[-1] == recent[-2]:
        weights.pop(recent[-1], None)
    if not weights:
        return ACTS["smalltalk" if source == BEAT else "opinion"]
    keys = list(weights)
    return ACTS[rng.choices(keys, weights=[weights[k] for k in keys])[0]]
