# Snoke Tracker

Lokaler Hintergrund-Daemon, der deine Desktop-Aktivität zusammenfasst und
an das Snoke-Backend schickt.

## Installation

```bash
cd tracker
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

Auf Linux/X11 nutzt der Tracker `python-xlib` (wird via Dependency
automatisch installiert), auf anderen Plattformen fällt er sanft auf
"nur Input-Zähler" zurück.

## Starten

```bash
snoke-tracker --backend http://127.0.0.1:8000 --token <DEIN_TOKEN>
```

Den Token findest du nach dem Onboarding unter `/settings` in der Web-UI.
Alternativ kannst du Umgebungsvariablen setzen:

```bash
export SNOKE_BACKEND=http://127.0.0.1:8000
export SNOKE_TOKEN=...
snoke-tracker
```

## Was wird gesammelt?

Alle 60 Sekunden wird *ein* Kontext-Event erzeugt mit:

- `active_app` – Name/Class des aktiven Fensters (nicht dessen Inhalt!)
- `active_title` – Fenstertitel, *gekürzt auf max. 80 Zeichen*, URLs entfernt
- `idle_seconds` – Sekunden seit letzter Tastatur-/Mausaktivität
- `kbd_per_min`, `mouse_per_min` – Zähler (nicht Inhalt!)

Es werden **keine** Tastendrücke, Screenshots oder Clipboard-Inhalte
aufgezeichnet. Die Payload wird direkt verworfen, falls du auf Netzwerk-
oder Backend-Probleme stößt (kurzer lokaler JSONL-Buffer).

## Systemd (optional)

Siehe [../deploy/systemd/snoke-tracker.service](../deploy/systemd/snoke-tracker.service).
