from __future__ import annotations

from pathlib import Path

from snoke_tracker.buffer import EventBuffer


def test_append_read_clear(tmp_path: Path) -> None:
    buf = EventBuffer(tmp_path / "b.jsonl")
    buf.append({"a": 1})
    buf.append({"a": 2})
    assert buf.read_all() == [{"a": 1}, {"a": 2}]
    buf.clear()
    assert buf.read_all() == []


def test_replace_atomic(tmp_path: Path) -> None:
    buf = EventBuffer(tmp_path / "b.jsonl")
    for i in range(5):
        buf.append({"i": i})
    buf.replace_with([{"i": 9}])
    assert buf.read_all() == [{"i": 9}]
