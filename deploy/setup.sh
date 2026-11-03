#!/usr/bin/env bash
# Sets up Home Groceries on a fresh Debian or Ubuntu VM.
# Run as root from inside a copy of this repository:   sudo ./deploy/setup.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then echo "Run with sudo."; exit 1; fi
SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP=/opt/home-groceries
DATA=/var/lib/groceries
BACKUPS=/var/backups/groceries

echo "==> Installing packages"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip sqlite3 rsync

echo "==> Creating service user and folders"
id groceries &>/dev/null || useradd --system --home "$APP" --shell /usr/sbin/nologin groceries
mkdir -p "$APP" "$DATA" "$BACKUPS"

echo "==> Copying the app to $APP"
rsync -a --delete --exclude '.git' --exclude 'data' --exclude '.venv' --exclude '__pycache__' "$SRC"/ "$APP"/

echo "==> Installing Python dependencies"
python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install -q --upgrade pip
"$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"
chown -R groceries:groceries "$APP" "$DATA" "$BACKUPS"

echo "==> Installing the service and the nightly backup"
install -m 644 "$APP/deploy/groceries.service" /etc/systemd/system/groceries.service
install -m 755 "$APP/deploy/groceries-admin" /usr/local/bin/groceries-admin
cat > /etc/cron.d/groceries-backup <<CRON
# Nightly copy of the database, newest 30 kept.
15 3 * * * groceries cd $APP && GROCERIES_DB=$DATA/groceries.db $APP/.venv/bin/python manage.py backup $BACKUPS --keep 30
CRON
chmod 644 /etc/cron.d/groceries-backup
systemctl daemon-reload
systemctl enable --now groceries

echo
echo "Done. The app is listening on port 8000."
echo "Next, create the two logins. With --no-password you just tap your name to sign in;"
echo "leave that flag off to be asked for a password instead:"
echo "  groceries-admin add-user ken \"Ken\" --no-password"
echo "  groceries-admin add-user lynette \"Lynette\" --no-password"
echo "Then open http://$(hostname -I | awk '{print $1}'):8000 from a phone on the same network."
