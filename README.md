# Snoke

**Snoke** hilft dir schrittweise vom Rauchen wegzukommen. Die Idee: statt
starrer "X Zigaretten pro Tag"-Regeln beobachtet Snoke deine
Dopamin-Aktivitäten (App-Nutzung, Idle-Zeiten, Input-Rate, manuelle
Einträge) und lernt, **in welchen Situationen** dein Rauchverlangen steigt.
Daraus berechnet es laufend eine **Craving-Wahrscheinlichkeit** und spielt
kurz **vor** dem erwarteten Peak eine passende Empfehlung aus (Atemübung,
Verzögerungs-Timer, Wasser, kurzer Spaziergang).

## Komponenten

```
snoke/
├── backend/    FastAPI-Server mit Web-UI, Craving-Modell und Event-Store
├── tracker/    Lokaler Python-Daemon, der Desktop-Aktivität sammelt
├── deploy/     Dockerfile, docker-compose, systemd- und nginx-Beispiele
└── docs/       Architektur- und Modell-Dokumentation
```

```
┌────────────────────────┐   events   ┌──────────────────────────────┐
│  Tracker (Laptop)      │───────────▶│  Backend                     │
│  active window / idle  │            │  FastAPI + SQLite            │
│  input rate / manual   │◀───────────│  Craving-Engine + Nudges     │
└────────────────────────┘  nudges    │  Web-UI (HTMX + Tailwind)    │
         │                            └──────────────┬───────────────┘
         │ Desktop-Notification                      │  HTTP
         ▼                                           ▼
   libnotify                                   Browser (du)
```

## Schnellstart (alles lokal auf deinem Laptop)

```bash
# 1. Backend starten
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
#  → lokal: http://127.0.0.1:8000   (Web-UI)
#  → lokal: http://127.0.0.1:8000/docs   (API-Doku)
#  → iPad im gleichen WLAN: http://<LAPTOP-IP>:8000

# 2. In einem zweiten Terminal: Tracker starten
cd tracker
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
snoke-tracker --backend http://127.0.0.1:8000
```

Beim ersten Aufruf der Web-UI wirst du durch ein kurzes Onboarding geführt
(Baseline-Zigaretten/Tag, Entwöhnungsrate). Danach kannst du mit den großen
Buttons im Dashboard Zigaretten und Cravings eintragen — der Tracker
ergänzt das automatisch um Kontext aus deinem Desktop.

## Später: auf eigene Domain deployen

Siehe [`docs/deploy.md`](docs/deploy.md). Kurzfassung: `docker compose up -d`
im `deploy/`-Verzeichnis, nginx als Reverse-Proxy vor Port 8000, Let's
Encrypt via Certbot für TLS.

## Datenschutz

Alle Daten gehören dir. Der Tracker erfasst **keine Fenster-Inhalte,
Tastendrücke oder Screenshots** — nur den Fenstertitel des aktiven Fensters,
die Leerlaufzeit und Zähler für Tastatur-/Mausereignisse (ohne Inhalt). Im
Single-User-Modus läuft alles lokal; es gibt keinen externen Dienst.

## Dokumentation

- [Architektur](docs/architecture.md)
- [Craving-Wahrscheinlichkeits-Modell](docs/model.md)
- [Deployment](docs/deploy.md)

## iOS App (SwiftUI)

Der iOS-Code liegt unter `ios/SnokeIOS/`. Ein `*.xcodeproj` wird aktuell nicht mit eingecheckt,
du legst es lokal an und haengst die Quellen ein.

Siehe Anleitung in [`ios/README.md`](ios/README.md).
