from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.web.routes import _build_smoking_coach_plan, _smoke_windows


def test_coach_plan_allows_now_when_current_free_window_is_long_enough() -> None:
    now = datetime(2026, 4, 21, 14, 0, tzinfo=UTC)
    local_now = now.astimezone()
    windows = [
        (
            local_now.replace(hour=8, minute=0, second=0, microsecond=0),
            local_now.replace(hour=22, minute=0, second=0, microsecond=0),
        )
    ]
    plan = _build_smoking_coach_plan(
        now=now,
        plan_day=local_now.date(),
        target_today=6,
        smoked_today=0,
        p_now=0.18,
        allowed_windows=windows,
    )
    assert plan["allow_now"] is True
    assert ">= 9 minuten" in plan["message"].lower()


def test_coach_plan_waits_when_not_inside_any_free_window() -> None:
    now = datetime(2026, 4, 21, 14, 0, tzinfo=UTC)
    local_now = now.astimezone()
    ws = (local_now + timedelta(hours=2)).replace(second=0, microsecond=0)
    we = ws + timedelta(hours=2)
    windows = [
        (
            ws,
            we,
        )
    ]
    plan = _build_smoking_coach_plan(
        now=now,
        plan_day=local_now.date(),
        target_today=6,
        smoked_today=3,
        p_now=0.62,
        allowed_windows=windows,
    )
    assert plan["allow_now"] is False
    assert "noch warten" in plan["message"].lower() or "kein weiteres" in plan["message"].lower()
    assert len(plan["slot_times"]) == 3


def test_coach_plan_blocks_when_no_calendar_window() -> None:
    now = datetime(2026, 4, 21, 14, 0, tzinfo=UTC)
    plan = _build_smoking_coach_plan(
        now=now,
        plan_day=now.astimezone().date(),
        target_today=4,
        smoked_today=1,
        p_now=0.7,
        allowed_windows=[],
    )
    assert plan["allow_now"] is False
    assert "kalender blockiert" in plan["message"].lower()


def test_coach_plan_for_future_day_does_not_subtract_today_smoked() -> None:
    now = datetime(2026, 4, 21, 14, 0, tzinfo=UTC)
    local_now = now.astimezone()
    windows = [
        (
            local_now.replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=1),
            local_now.replace(hour=22, minute=0, second=0, microsecond=0) + timedelta(days=1),
        )
    ]
    plan = _build_smoking_coach_plan(
        now=now,
        plan_day=(local_now + timedelta(days=1)).date(),
        target_today=6,
        smoked_today=5,
        p_now=0.25,
        allowed_windows=windows,
    )
    assert plan["remaining"] == 6
    assert len(plan["slot_times"]) == 6


def test_smoke_windows_require_gap_strictly_greater_than_nine_minutes() -> None:
    now = datetime(2026, 4, 21, 8, 0, tzinfo=UTC).astimezone()
    windows = [
        (now, now + timedelta(minutes=9)),
        (now + timedelta(minutes=20), now + timedelta(minutes=30)),
    ]
    out = _smoke_windows(windows, min_minutes=9)
    assert len(out) == 1
    assert out[0][0] == now + timedelta(minutes=20)
