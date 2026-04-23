# Architektur

Snoke besteht aus drei Teilen, die alle in Python geschrieben sind:

1. **Backend** (`backend/`) – FastAPI-Server, der:
   - Events speichert (SQLite)
   - die **Craving-Engine** und den **Weaning-Planner** hostet
   - eine **Web-UI** (Jinja + HTMX + Tailwind via CDN) ausliefert
2. **Tracker** (`tracker/`) – lokaler Daemon, der auf deinem Laptop läuft und
   Desktop-Aktivitätssignale als Kontext-Events an das Backend meldet.
3. **Web-UI** – Teil des Backends, im Browser unter `http://localhost:8000`
   oder unter deiner Domain erreichbar.

```
┌──────────────────────────┐     ┌──────────────────────────────────────┐
│        Tracker           │     │              Backend                 │
│                          │     │                                      │
│  collectors:             │     │  /users/register                     │
│   - active_window (X11)  │     │  /events/batch          ──┐          │
│   - idle_seconds         │     │  /me/summary              │          │
│   - input_rate (pynput)  │     │  /me/probability          │          │
│                          │     │  /me/recommendation       │          │
│  poster ── batched POST ─┼────▶│                           ▼          │
│  (retry, local buffer)   │     │      ┌──────────────────────────┐    │
│                          │     │      │  CravingEngine           │    │
│  notifier (libnotify)    │◀────┤      │   - FeatureExtractor     │    │
│                          │nudge│      │   - RuleLayer            │    │
└──────────────────────────┘     │      │   - BayesianUpdater      │    │
                                 │      │   - WeaningPlanner       │    │
                                 │      └──────────────────────────┘    │
                                 │                                      │
                                 │  Web-UI (Jinja + HTMX + Tailwind)    │
                                 │   /           Dashboard              │
                                 │   /onboarding Baseline eintragen     │
                                 │   /progress   Verlauf                │
                                 │                                      │
                                 │  SQLite: users, events               │
                                 └──────────────────────────────────────┘
```

## Backend-Struktur

```
backend/app/
├── main.py              FastAPI-App, Router-Registrierung, Lifespan
├── core/
│   ├── config.py        Pydantic-Settings (.env)
│   └── security.py      JWT (anonymous, device-bound)
├── db/
│   └── session.py       SQLAlchemy-Engine + Base
├── models/              ORM: User, Event
├── schemas/             Pydantic-Schemas
├── api/                 REST-Router (users, events, summary, probability, recommendation)
├── model/               Craving-Engine (FeatureExtractor, RuleLayer, BayesianUpdater, WeaningPlanner)
└── web/                 Server-rendered UI (Jinja + HTMX)
    ├── routes.py
    ├── templates/       HTML-Templates
    └── static/          Mini-CSS-Overrides, Favicon
```

## Tracker-Struktur

```
tracker/snoke_tracker/
├── __main__.py         Entry-Point `snoke-tracker`
├── config.py           CLI/ENV-Konfiguration
├── collectors.py       Active-Window (X11), Idle, Input-Rate, Hostname-Fallback
├── buffer.py           Lokaler JSONL-Buffer bei Netzwerkausfall
├── poster.py           Batch-Upload zum Backend
└── notifier.py         Desktop-Notifications via `notify-send` / dbus
```

## Event-Modell

Im Backend gibt es nur eine Tabelle `events` mit den Feldern
`kind ∈ {cigarette, craving, context, nudge}` und einem freien
JSON-Payload. So können wir neue Tracker-Signale aufnehmen, ohne das
Schema zu migrieren.

Typische Payloads:

```jsonc
// kind=cigarette
{ "trigger": "coffee" }

// kind=craving
{ "intensity": 7, "resisted": true, "trigger": "stress" }

// kind=context  (vom Tracker, alle 60s)
{
  "active_app": "Firefox",
  "active_title_class": "social",
  "idle_seconds": 12,
  "kbd_per_min": 85,
  "mouse_per_min": 140,
  "hostname": "limi-laptop"
}

// kind=nudge  (vom Backend ausgespielt)
{ "type": "breathing_478", "accepted": true }
```

## Datenfluss: Craving-Berechnung

1. Tracker schickt alle ~60 s einen `context`-Event.
2. Web-UI pollt (HTMX, alle 30 s) `/me/probability`.
3. `CravingEngine.compute(user)` lädt die letzten Events, leitet den
   aktuellen Bucket ab, holt Posterior-Stats, wendet den Rule-Layer an und
   liefert `P_now`, `next_peak_at`, `top_triggers`.
4. Bei `P_now ≥ Schwelle` und noch nicht kürzlich gesendeter Nudge:
   `/me/recommendation` liefert den nächsten Nudge, der Tracker ruft
   diesen ab und feuert `notify-send`.
