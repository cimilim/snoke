PY ?= python3

BACKEND_VENV := backend/.venv
TRACKER_VENV := tracker/.venv

.PHONY: help install install-backend install-tracker test test-backend test-tracker \
        run-backend run-tracker register clean

help:
	@echo "Snoke – make targets"
	@echo "  make install         venvs für Backend und Tracker anlegen + installieren"
	@echo "  make test            alle Tests ausführen"
	@echo "  make run-backend     FastAPI + Web-UI im LAN auf http://<deine-ip>:8000"
	@echo "  make run-tracker     Desktop-Tracker starten (braucht SNOKE_TOKEN)"
	@echo "  make register        einmalig anonymen User registrieren und Token speichern"

install: install-backend install-tracker

install-backend:
	$(PY) -m venv $(BACKEND_VENV)
	$(BACKEND_VENV)/bin/pip install --upgrade pip
	$(BACKEND_VENV)/bin/pip install -e "backend[dev]"

install-tracker:
	$(PY) -m venv $(TRACKER_VENV)
	$(TRACKER_VENV)/bin/pip install --upgrade pip
	$(TRACKER_VENV)/bin/pip install -e "tracker[dev]"

test: test-backend test-tracker

test-backend:
	cd backend && .venv/bin/pytest -q

test-tracker:
	cd tracker && .venv/bin/pytest -q

run-backend:
	cd backend && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

register:
	$(TRACKER_VENV)/bin/snoke-tracker register

run-tracker:
	$(TRACKER_VENV)/bin/snoke-tracker

clean:
	rm -rf $(BACKEND_VENV) $(TRACKER_VENV)
	rm -rf backend/snoke_backend.egg-info tracker/snoke_tracker.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
