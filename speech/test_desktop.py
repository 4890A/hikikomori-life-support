import asyncio
import json

import pytest

import desktop


def collect(states: list[dict], count: int) -> list[str]:
    feed = iter(states)

    async def run() -> list[str]:
        stream = desktop.updates(lambda: next(feed))
        return [await anext(stream) for _ in range(count)]

    return asyncio.run(run())


def test_sends_only_when_something_moved(monkeypatch):
    monkeypatch.setattr(desktop, "POLL_SECONDS", 0)
    first, second = {"cursor": [1, 2]}, {"cursor": [3, 4]}
    events = collect([first, first, first, second], 2)
    assert [json.loads(event.removeprefix("data: ")) for event in events] == [first, second]


def test_keeps_the_connection_alive_when_nothing_moves(monkeypatch):
    monkeypatch.setattr(desktop, "POLL_SECONDS", 0)
    monkeypatch.setattr(desktop, "KEEP_ALIVE_SECONDS", 0)
    state = {"cursor": [1, 2]}
    assert collect([state, state], 2)[1] == ": alive\n\n"


@pytest.mark.skipif(not desktop.AVAILABLE, reason="Windows only")
def test_a_window_that_does_not_exist_has_no_position():
    assert desktop.window_rect(0) is None
    assert desktop.window_rect(1) is None


@pytest.mark.skipif(not desktop.AVAILABLE, reason="Windows only")
def test_reads_the_cursor_and_finds_no_page_for_an_unknown_title():
    reader = desktop.DesktopReader("no window has this title 8c1f", 0)
    state = reader.read()
    assert len(state["cursor"]) == 2
    assert state["page"] is None
    assert state["target"] is None
