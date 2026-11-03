# Home Groceries

A household grocery inventory you open on your phone: what you have, how much, where it is
(fridge, kitchen freezer, two chest freezers, pantry), and when it needs to be used. Built so you can
answer "do we have this?" while standing in the store.

Two people share one inventory. Every change is recorded in an audit log (who, what, when) so
consumption and waste trends are possible later.

## What works now

- Instant search across name, brand, category and location, plus status, location and category filters
- Count or level quantities (count with a −1 button, or Full / Half / Almost out)
- Purchase, package and opened dates. Opening an item starts a shorter "use by" clock
- Moving to a freezer resets the date to the frozen shelf life; moving back starts a thaw clock
- Used up and Tossed with Undo, edit details, "Buy again"
- A shared shopping list tagged by store (Publix, Target, Walmart, BJ's, Whole Foods, Trader Joe's, or any
  store), with an optional note such as "BOGO". Pick a store to see only what to buy there. Stores are
  listed in `app/rules.py`
- Expiring view and a Locations view
- Two logins (a password, or just tap your name), installable to the iPhone home screen
- Full audit history per item (shown in the item screen)

Planned next: barcode and photo capture, receipt scanning, daily expiry alerts, leftovers and
recipe ideas.

## Run it locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py add-user ken "Ken" --no-password       # tap your name to sign in
python manage.py add-user lynette "Lynette" --no-password
# or leave off --no-password to be asked for a password
python manage.py seed-demo                    # optional sample items
uvicorn app.main:app --reload                 # http://127.0.0.1:8000
```

Tests: `pip install -r requirements-dev.txt && pytest`

Data lives in `data/groceries.db` (SQLite). Set `GROCERIES_DB` to put it somewhere else.

## Put it on a Linux VM (Hyper-V)

1. **Create the VM.** A Debian or Ubuntu Server image is plenty: 1 vCPU, 1 GB RAM, 10 GB disk.
   Attach it to an **External** virtual switch so it gets an address on your home network. Give it a
   DHCP reservation on your router so the address does not change.
2. **Copy this repository onto the VM** (for example `git clone` it, or `scp` the folder).
3. **Run the setup script** from inside the copy:
   ```bash
   sudo ./deploy/setup.sh
   ```
   It installs Python, creates a service user, installs the app to `/opt/home-groceries`, keeps the
   database in `/var/lib/groceries`, starts it as a service on port 8000, and schedules a nightly backup.
4. **Create the two logins** (the script prints the exact commands). With `--no-password`, the sign-in
   screen shows a "Who is this?" button for each of you. See "Signing in without a password" below.
5. **Open `http://<vm-address>:8000`** from a phone on the same Wi-Fi.
6. **Install it as an app:** in Safari, Share, then Add to Home Screen.

### Signing in without a password

Users created with `--no-password` sign in by tapping their name, and stay signed in for 30 days per
device. That is convenient, but it means **anyone who can reach the app can open it as either of you**
and see or change the inventory. On a home network that is usually a fair trade, since you would be
exposing grocery lists and not anything sensitive. Keep it that way by:

- never forwarding port 8000 on your router to the internet,
- reaching it from outside the house only through Tailscale (below), and
- adding a password later if guests join your Wi-Fi: `manage.py set-password ken`.

To remove a password and go back to tap-your-name: `manage.py set-password ken --no-password`.

### Reaching it away from home (Tailscale)

Install Tailscale on the VM and on both phones, then on the VM:

```bash
sudo tailscale up
sudo tailscale serve --bg 8000        # gives you an https address on your tailnet
```

Once you use the https address, set `GROCERIES_SECURE_COOKIES=1` in
`/etc/systemd/system/groceries.service`, then `sudo systemctl daemon-reload && sudo systemctl restart groceries`.
HTTPS is also what iPhone needs for the camera and for push notifications later.

### Day-to-day

| Task | Command |
|---|---|
| See logs | `journalctl -u groceries -f` |
| Restart | `sudo systemctl restart groceries` |
| Update to the latest code | `sudo ./deploy/update.sh` |
| Change a password | `sudo -u groceries env GROCERIES_DB=/var/lib/groceries/groceries.db /opt/home-groceries/.venv/bin/python /opt/home-groceries/manage.py set-password ken` |
| Back up now | `sudo -u groceries env GROCERIES_DB=/var/lib/groceries/groceries.db /opt/home-groceries/.venv/bin/python /opt/home-groceries/manage.py backup /var/backups/groceries` |

Backups land in `/var/backups/groceries` (newest 30 kept). Copy that folder to another machine now
and then, since a backup on the same VM does not survive the VM being lost. To restore, stop the
service and replace `/var/lib/groceries/groceries.db` with a backup file.

## Layout

```
app/main.py        API (FastAPI): login, items, actions, audit events, shopping list
app/rules.py       Locations, categories and shelf-life rules (served to the web app)
app/db.py          SQLite schema and password hashing
app/static/        The phone web app (index.html, app.js, manifest, icons)
manage.py          Admin commands: add-user, set-password, backup, seed-demo
deploy/            systemd unit, setup and update scripts
tests/             API tests
prototype/         The original clickable prototype (sample data only)
```

## Notes

- Shelf-life numbers in `app/rules.py` are starter values in the spirit of USDA FoodKeeper. Adjust
  them there; the web app reads them from the server.
- Sign-in sessions last 30 days. Five wrong passwords lock that username for a minute.
- The audit log (`events` table) is append-only. Nothing is ever deleted from the inventory either:
  used and tossed items are marked removed, which keeps the history for trends.
