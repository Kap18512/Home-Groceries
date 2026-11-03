#!/usr/bin/env bash
# Pull the latest code and restart. Run as root from the repository copy:  sudo ./deploy/update.sh
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP=/opt/home-groceries
git -C "$SRC" pull --ff-only
rsync -a --delete --exclude '.git' --exclude 'data' --exclude '.venv' --exclude '__pycache__' "$SRC"/ "$APP"/
"$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"
chown -R groceries:groceries "$APP"
systemctl restart groceries
echo "Updated and restarted."
