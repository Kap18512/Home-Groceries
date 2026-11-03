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
- **Barcode scanning:** scan, check the filled-in card, save, and the camera is ready for the next one.
  It tells you what you already have of that product. Unknown barcodes are learned the first time you
  type them in, so they are instant after that
- **Photos:** product photos come with the barcode lookup, or take one yourself. One photo is shared by
  every purchase of the same product. Photos are stored in the database, so backups include them
- Expiring view and a Locations view
- Two logins (a password, or just tap your name), installable to the iPhone home screen
- Full audit history per item (shown in the item screen)

Planned next: receipt scanning, daily expiry alerts, leftovers and
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
4. **Create the two logins** with the `groceries-admin` command the script installed:
   ```bash
   groceries-admin add-user ken "Ken" --no-password
   groceries-admin add-user lynette "Lynette" --no-password
   ``` With `--no-password`, the sign-in
   screen shows a "Who is this?" button for each of you. See "Signing in without a password" below.
5. **Open `http://<vm-address>:8000`** from a phone on the same Wi-Fi.
6. **Install it as an app:** in Safari, Share, then Add to Home Screen.

### Signing in without a password

Users created with `--no-password` sign in by tapping their name, and stay signed in for 30 days per
device. That is convenient, but it means **anyone who can reach the app can open it as either of you**
and see or change the inventory. On a home network that is usually a fair trade, since you would be
exposing grocery lists and not anything sensitive. Keep it that way by:

- never forwarding port 8000 on your router to the internet,
- reaching it from outside the house only through Tailscale (see "Setting up Tailscale" below), and
- adding a password later if guests join your Wi-Fi: `manage.py set-password ken`.

To remove a password and go back to tap-your-name: `manage.py set-password ken --no-password`.

### Barcode scanning needs https and internet

- **Live camera scanning only works over https.** Over plain `http://192.168.x.x:8000` the Scan screen
  switches to "take a photo of the barcode", which uses your phone's camera app and still works.
  Follow "Setting up Tailscale" below to get https and live scanning.
- **The VM needs internet access** to look up new barcodes. Check from the VM with:
  `groceries-admin lookup 0021000614509`
  It prints the product name if the lookup works, or says what is wrong.
- A product only needs to be looked up once. After that it comes from your own catalog.

### Setting up Tailscale (https, live scanning, and use away from home)

Tailscale puts your VM and phones on a private network that only your own devices can join. It gives
the app a proper `https://` address, which is what the iPhone camera needs, and it works from anywhere
without opening anything on your router. It is free for personal use.

1. **Make an account** at [tailscale.com](https://tailscale.com) (sign in with Google, Microsoft or Apple).
2. **Install it on the VM** and connect it:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up
   ```
   `tailscale up` prints a login link. Open it on your laptop or phone and approve the machine. If the
   install script does not recognise your Ubuntu version, see tailscale.com/download/linux.
3. **Install the Tailscale app on both phones** (App Store), sign in to the same account, and switch it on.
4. **Turn on https once, in Tailscale's admin page.** Open
   [login.tailscale.com/admin/dns](https://login.tailscale.com/admin/dns), make sure **MagicDNS** is
   enabled, then under **HTTPS Certificates** click **Enable HTTPS**. Skipping this is the most common
   reason step 5 fails.
5. **Publish the app over https** (run on the VM):
   ```bash
   sudo tailscale serve --bg 8000
   tailscale serve status        # shows your address, like https://groceries.your-tailnet.ts.net
   ```
   This keeps the app private to your devices. Do **not** use `tailscale funnel`, which makes it public.
6. **On each phone**, with Tailscale switched on, open that https address in Safari. Allow the camera
   when asked. Then **Share, Add to Home Screen** again, because an icon saved from the old
   `http://192.168...` address still points there. Live scanning now works.

Good to know:

- The https address only works while Tailscale is switched on on the phone, even at home. The plain
  `http://<vm-address>:8000` address keeps working at home without it (with the photo-of-barcode
  fallback for scanning), so you have a backup way in.
- To get a friendlier name than the machine's hostname: `sudo tailscale set --hostname=groceries`
  (then run `tailscale serve status` again to see the new address).
- `GROCERIES_SECURE_COOKIES` in `/etc/systemd/system/groceries.service` is optional. Leave it at `0` and
  sign-in works on both addresses. Set it to `1` only if you want to *stop* signing in over plain http,
  because browsers refuse to keep a secure cookie on an http page. After changing it:
  `sudo systemctl daemon-reload && sudo systemctl restart groceries`.
- If `tailscale serve` says HTTPS is not enabled, repeat step 4. If the page shows a certificate error
  right after enabling, wait a minute and reload.

### Admin commands

`groceries-admin` runs the admin commands against the live database. It asks for your sudo password when
needed. Run `groceries-admin --help` for the list: `add-user`, `set-password`, `list-users`, `backup`,
`lookup`, `seed-demo`.

### Day-to-day

| Task | Command |
|---|---|
| See logs | `journalctl -u groceries -f` |
| Restart | `sudo systemctl restart groceries` |
| Update to the latest code | `sudo ./deploy/update.sh` |
| Change a password | `groceries-admin set-password ken` |
| Back up now | `groceries-admin backup /var/backups/groceries` |

Backups land in `/var/backups/groceries` (newest 30 kept). Copy that folder to another machine now
and then, since a backup on the same VM does not survive the VM being lost. To restore, stop the
service and replace `/var/lib/groceries/groceries.db` with a backup file.

## Layout

```
app/main.py        API (FastAPI): login, items, actions, audit events, shopping list
app/rules.py       Locations, categories and shelf-life rules (served to the web app)
app/off.py         Open Food Facts barcode lookups and category guessing
app/db.py          SQLite schema and password hashing
app/static/        The phone web app (index.html, app.js, manifest, icons)
app/static/vendor/ ZXing barcode reader (Apache-2.0, license included)
manage.py          Admin commands: add-user, set-password, backup, seed-demo
deploy/            systemd unit, setup and update scripts
tests/             API tests
prototype/         The original clickable prototype (sample data only)
```

## Credits

Product names, categories and photos from barcode lookups come from
[Open Food Facts](https://world.openfoodfacts.org) (data under ODbL, images under CC BY-SA).
Barcodes are read with [ZXing](https://github.com/zxing-js/library).

## Notes

- Shelf-life numbers in `app/rules.py` are starter values in the spirit of USDA FoodKeeper. Adjust
  them there; the web app reads them from the server.
- Sign-in sessions last 30 days. Five wrong passwords lock that username for a minute.
- The audit log (`events` table) is append-only. Nothing is ever deleted from the inventory either:
  used and tossed items are marked removed, which keeps the history for trends.
