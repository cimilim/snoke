"""Feature extraction: map a point in time + latest context to a discrete bucket.

A bucket is the coarse identifier under which we accumulate Beta-Bernoulli
statistics. Keeping it deliberately small (order of hundreds) means every
cell gets enough evidence within a few weeks of use.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class Activity(StrEnum):
    still = "still"
    active = "active"
    unknown = "unknown"


class StressLevel(StrEnum):
    low = "low"
    mid = "mid"
    high = "high"
    unknown = "unknown"


class AppCategory(StrEnum):
    """Coarse categorisation of the currently active desktop app."""

    work = "work"
    social = "social"
    media = "media"
    game = "game"
    idle = "idle"
    other = "other"


# Heuristic mapping of active-app strings to categories. Intentionally small
# and readable; users can extend it later in settings.
_APP_CATEGORY_KEYWORDS: dict[AppCategory, tuple[str, ...]] = {
    AppCategory.social: ("twitter", "x.com", "reddit", "instagram", "tiktok",
                         "facebook", "whatsapp", "telegram", "discord", "mastodon"),
    AppCategory.media: ("youtube", "netflix", "spotify", "twitch", "vlc", "mpv"),
    AppCategory.game: ("steam", "lutris", "minecraft", "dota", "league"),
    AppCategory.work: ("code", "vim", "emacs", "terminal", "tmux", "slack",
                       "jira", "gitlab", "github", "intellij", "pycharm",
                       "libreoffice", "docs"),
}


def categorize_app(active_app: str | None, active_title: str | None) -> AppCategory:
    haystack = " ".join(s for s in (active_app, active_title) if s).lower()
    if not haystack:
        return AppCategory.idle
    for cat, keywords in _APP_CATEGORY_KEYWORDS.items():
        if any(k in haystack for k in keywords):
            return cat
    return AppCategory.other


@dataclass(frozen=True, slots=True)
class Bucket:
    hour_block: int         # 0..11, each covers 2 hours
    weekend: bool
    activity: Activity
    stress: StressLevel
    app_category: AppCategory

    @property
    def key(self) -> str:
        return (
            f"{self.hour_block:02d}|{'we' if self.weekend else 'wd'}|"
            f"{self.activity}|{self.stress}|{self.app_category}"
        )

    def __str__(self) -> str:
        return self.key


class FeatureExtractor:
    """Turn a timestamp + optional context payload into a `Bucket`."""

    def extract(
        self,
        now: datetime,
        context: dict[str, Any] | None = None,
    ) -> Bucket:
        ctx = context or {}
        hour_block = now.hour // 2
        weekend = now.weekday() >= 5

        activity = self._activity(ctx)
        stress = self._stress(ctx)
        app_cat = categorize_app(ctx.get("active_app"), ctx.get("active_title"))

        return Bucket(
            hour_block=hour_block,
            weekend=weekend,
            activity=activity,
            stress=stress,
            app_category=app_cat,
        )

    @staticmethod
    def _activity(ctx: dict[str, Any]) -> Activity:
        idle = ctx.get("idle_seconds")
        kbd = ctx.get("kbd_per_min", 0) or 0
        mouse = ctx.get("mouse_per_min", 0) or 0
        if isinstance(idle, (int, float)) and idle > 300:
            return Activity.still
        if kbd + mouse > 30:
            return Activity.active
        if kbd + mouse > 0:
            return Activity.still
        return Activity.unknown

    @staticmethod
    def _stress(ctx: dict[str, Any]) -> StressLevel:
        # Cheap proxy from input bursts: very high input rate over short time
        # correlates with focused work OR anxious scrolling; we combine with
        # manual `stress` tags if present.
        manual = ctx.get("stress")
        if isinstance(manual, str) and manual in (s.value for s in StressLevel):
            return StressLevel(manual)
        kbd = ctx.get("kbd_per_min", 0) or 0
        if kbd > 200:
            return StressLevel.high
        if kbd > 60:
            return StressLevel.mid
        if kbd == 0 and (ctx.get("idle_seconds") or 0) < 60:
            return StressLevel.low
        return StressLevel.unknown
