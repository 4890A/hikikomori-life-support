"""The character card: who she is, in a file you can edit.

characters/deepseek-chan.json is the default. Edits from the panel go to a separate file in the
companion data folder, so resetting just deletes that file. Override with COMPANION_CHARACTER.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CARD = Path(os.environ.get("COMPANION_CHARACTER", ROOT / "characters" / "deepseek-chan.json"))
DATA_DIR = Path(os.environ.get("COMPANION_DATA_DIR", ROOT / "companion-data"))
CUSTOM_CARD = DATA_DIR / "character.json"


class CharacterCard(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    personality: str = Field(default="", max_length=2000)
    speech_style: str = Field(default="", max_length=2000)
    scenario: str = Field(default="", max_length=2000)
    likes: list[str] = Field(default_factory=list, max_length=30)
    dislikes: list[str] = Field(default_factory=list, max_length=30)
    rules: list[str] = Field(default_factory=list, max_length=30)
    examples: list[str] = Field(default_factory=list, max_length=20)
    screen_instruction: str = Field(default="今の画面を見て、一言反応してください。", min_length=1, max_length=1000)


def _read(path: Path) -> CharacterCard:
    return CharacterCard.model_validate(json.loads(path.read_text(encoding="utf-8")))


def load_card() -> CharacterCard:
    return _read(CUSTOM_CARD if CUSTOM_CARD.exists() else DEFAULT_CARD)


def save_card(card: CharacterCard) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = CUSTOM_CARD.with_suffix(".tmp")
    temporary.write_text(card.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(CUSTOM_CARD)


def reset_card() -> CharacterCard:
    CUSTOM_CARD.unlink(missing_ok=True)
    return load_card()
