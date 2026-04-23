# Deployment

## Lokal auf dem Laptop (Standard im MVP)

Kein Deployment nötig. Siehe [`README.md`](../README.md) Schnellstart.

Optional als systemd-User-Service (damit Backend und Tracker beim Login
automatisch starten): Vorlagen liegen in [`deploy/systemd/`](../deploy/systemd).

```bash
mkdir -p ~/.config/systemd/user
cp deploy/systemd/snoke-backend.service ~/.config/systemd/user/
cp deploy/systemd/snoke-tracker.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now snoke-backend.service
systemctl --user enable --now snoke-tracker.service
```

## Auf eigene Domain (einfacher VPS)

### 1. Docker-Compose auf dem Server

```bash
git clone https://github.com/<you>/snoke.git
cd snoke/deploy
cp ../backend/.env.example .env
# SNOKE_JWT_SECRET unbedingt auf einen langen Zufallswert setzen!
docker compose up -d
```

Das Backend läuft dann auf Port `8000`, persistiert in `./data/snoke.db`.

### 2. nginx + Let's Encrypt

Beispielkonfiguration in [`deploy/nginx.conf.example`](../deploy/nginx.conf.example).

```bash
sudo apt install nginx certbot python3-certbot-nginx
sudo cp deploy/nginx.conf.example /etc/nginx/sites-available/snoke
# darin `server_name` auf deine Domain anpassen
sudo ln -s /etc/nginx/sites-available/snoke /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d deine-domain.tld
```

### 3. Tracker weiter auf dem Laptop

Der Tracker bleibt auf deinem Laptop und zeigt auf die Server-URL:

```bash
snoke-tracker --backend https://deine-domain.tld --token "$SNOKE_TOKEN"
```

Den Token bekommst du beim Onboarding auf der Web-UI angezeigt
(einmalig) bzw. über `POST /users/register`.
