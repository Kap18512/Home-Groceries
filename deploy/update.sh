#!/usr/bin/env bash
# Pull the latest code and restart. Run as root from the repository copy:  sudo ./deploy/update.sh
set -euo pipefail

# Everything lives in a function so bash has read the whole script before `git pull` can replace this file.
main() {
  local SRC APP
  SRC="$(cd "$(dirname "$0")/.." && pwd)"
  APP=/opt/home-groceries
  git -C "$SRC" pull --ff-only
  rsync -a --delete --exclude '.git' --exclude 'data' --exclude '.venv' --exclude '__pycache__' "$SRC"/ "$APP"/
  "$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"
  install -m 755 "$APP/deploy/groceries-admin" /usr/local/bin/groceries-admin
  chown -R groceries:groceries "$APP"
  systemctl restart groceries
  echo "Updated and restarted."
}
main "$@"
exit
