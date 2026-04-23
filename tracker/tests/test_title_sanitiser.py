from __future__ import annotations

from snoke_tracker.collectors import _sanitise_title


def test_strips_urls() -> None:
    raw = "Browse — https://example.com/path?x=1 — tab"
    out = _sanitise_title(raw)
    assert out is not None
    assert "https://" not in out
    assert "[url]" in out


def test_truncates_long_titles() -> None:
    out = _sanitise_title("x" * 500)
    assert out is not None
    assert len(out) <= 80
    assert out.endswith("…")


def test_none_in_none_out() -> None:
    assert _sanitise_title(None) is None
    assert _sanitise_title("") is None
