# Snoke Backend

Schlankes FastAPI-Backend für anonyme Event-Annahme und spätere Server-seitige
Analysen. Für das MVP reicht SQLite.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Dann lokal: http://127.0.0.1:8000/docs  
Im WLAN (z. B. iPad Safari): http://<LAPTOP-IP>:8000

## Endpunkte

| Methode | Pfad                 | Beschreibung                                |
| ------- | -------------------- | ------------------------------------------- |
| `GET`   | `/healthz`           | Liveness-Check                              |
| `POST`  | `/users/register`    | Anonyme Device-Registrierung, JWT-Token     |
| `POST`  | `/events/batch`      | Events hochladen (Idempotenz per Client-UUID) |
| `GET`   | `/me/summary`        | Aggregierte Werte (heute, Woche)            |

## Tests

```bash
pytest
```

## Wissenschaft & Validierung

- Methodik, Metriken, Baselines, Ablationen und Quellen:
  - `docs/model-validation.md`
