"""Catalog of interventions and context-aware selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.model.engine import CravingResult
from app.model.features import AppCategory, StressLevel
from app.model.weaning import BudgetState, WeaningStatus


@dataclass(slots=True)
class Nudge:
    id: str
    title: str
    body: str
    duration_seconds: int
    kind: str  # breathing | delay | move | hydrate | reflect


_CATALOG: dict[str, Nudge] = {
    n.id: n for n in [
        Nudge("breathing_478",
              "4-7-8-Atmung",
              "4 Sekunden einatmen, 7 Sekunden halten, 8 Sekunden ausatmen. "
              "Viermal wiederholen.",
              150, "breathing"),
        Nudge("delay_2min",
              "2-Minuten-Delay",
              "Stell dir einen Timer auf 2 Minuten. Wenn das Verlangen "
              "danach noch da ist, entscheide neu.",
              120, "delay"),
        Nudge("move_5min",
              "Kurzer Bewegungsbreak",
              "Steh auf, 5 Minuten gehen — Flur, Balkon oder einmal ums Haus.",
              300, "move"),
        Nudge("hydrate",
              "Ein großes Glas Wasser",
              "Trink ein Glas Wasser in Ruhe. Oft verschwindet das "
              "Verlangen damit allein.",
              60, "hydrate"),
        Nudge("reflect_trigger",
              "Kurzer Trigger-Check",
              "Was ist gerade passiert? Notier den Auslöser in Snoke — "
              "du trainierst damit dein Modell.",
              60, "reflect"),
        Nudge("social_detach",
              "Weg vom Feed",
              "Social-Scrollen triggert dich gerade. Schließ den Tab für "
              "5 Minuten.",
              300, "delay"),
    ]
}


def choose_nudge(result: CravingResult, weaning: WeaningStatus) -> Nudge | None:
    """Return a nudge for the current moment, or None if no nudge is warranted."""
    p = result.p_now

    if p < 0.25 and weaning.state == BudgetState.on_track:
        return None

    # Budget-based escalation.
    if weaning.state == BudgetState.over_budget and p >= 0.2:
        return _CATALOG["reflect_trigger"]

    # Inspect bucket composition from the bucket key (a|b|activity|stress|app).
    parts = result.bucket_key.split("|")
    stress = parts[3] if len(parts) >= 4 else StressLevel.unknown.value
    app = parts[4] if len(parts) >= 5 else AppCategory.other.value

    if p >= 0.55:
        if stress == StressLevel.high.value:
            return _CATALOG["breathing_478"]
        if app == AppCategory.social.value:
            return _CATALOG["social_detach"]
        return _CATALOG["delay_2min"]

    if p >= 0.35:
        if app == AppCategory.social.value:
            return _CATALOG["social_detach"]
        return _CATALOG["hydrate"]

    # 0.25 .. 0.35 — soft hint
    return _CATALOG["hydrate"]


def all_nudges() -> Sequence[Nudge]:
    return list(_CATALOG.values())


def get_nudge(nudge_id: str) -> Nudge | None:
    return _CATALOG.get(nudge_id)
