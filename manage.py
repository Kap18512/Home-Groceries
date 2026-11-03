#!/usr/bin/env python3
"""Admin commands. Run from the project folder with the virtualenv active.

  python manage.py add-user ken "Ken"          # prompts for a password
  python manage.py add-user ken "Ken" --no-password   # signs in by tapping the name
  python manage.py set-password ken            # change a password (add --no-password to remove it)
  python manage.py list-users
  python manage.py backup /var/backups/groceries   # consistent copy of the database
  python manage.py seed-demo                   # sample items, only into an empty inventory
"""
import argparse
import getpass
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

from app import db
from app.rules import RULES


def read_password(args) -> str:
    if getattr(args, "no_password", False):
        return ""
    if args.password:
        return args.password
    pw = getpass.getpass("Password: ")
    if len(pw) < 8:
        sys.exit("Use at least 8 characters.")
    if pw != getpass.getpass("Again: "):
        sys.exit("Passwords did not match.")
    return pw


def cmd_add_user(args):
    db.init()
    conn = db.connect()
    pw = read_password(args)
    try:
        conn.execute("INSERT INTO users (username, display, pw_hash) VALUES (?,?,?)",
                     (args.username, args.display or args.username, db.hash_password(pw) if pw else ""))
    except sqlite3.IntegrityError:
        sys.exit(f"User {args.username!r} already exists. Use set-password to change it.")
    conn.commit()
    print(f"Added {args.username}.")


def cmd_set_password(args):
    db.init()
    conn = db.connect()
    pw = read_password(args)
    cur = conn.execute("UPDATE users SET pw_hash=? WHERE username=?", (db.hash_password(pw) if pw else "", args.username))
    if not cur.rowcount:
        sys.exit(f"No user named {args.username!r}.")
    conn.execute("DELETE FROM sessions WHERE user_id=(SELECT id FROM users WHERE username=?)", (args.username,))
    conn.commit()
    print("Password removed." if not pw else "Password changed.", "Existing sign-ins for that user were ended.")


def cmd_list_users(args):
    db.init()
    for r in db.connect().execute("SELECT username, display, created_at, pw_hash = '' AS nopw FROM users ORDER BY id"):
        print(f"{r['username']:<16} {r['display']:<20} {'no password' if r['nopw'] else 'password'}  since {r['created_at']}")


def cmd_backup(args):
    db.init()
    dest = Path(args.folder)
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / f"groceries-{date.today().isoformat()}.db"
    src = db.connect()
    out = sqlite3.connect(target)
    with out:
        src.backup(out)  # safe while the app is running
    out.close()
    keep = sorted(dest.glob("groceries-*.db"))[:-args.keep]
    for old in keep:
        old.unlink()
    print(f"Wrote {target} (kept the newest {args.keep}).")


DEMO = [
    # name, brand, cat, loc, mode, qty/level, pkg, bought days ago, exp days from today, opened days ago
    ("Cream cheese brick", "Philadelphia", "Dairy", "Fridge", "count", 1, "8 oz", 12, 9, 4),
    ("Cream cheese brick", "Philadelphia", "Dairy", "Fridge", "count", 2, "8 oz", 3, 40, None),
    ("Whole milk ricotta", "Galbani", "Dairy", "Fridge", "count", 1, "15 oz", 9, 2, 5),
    ("Heavy cream", "Publix", "Dairy", "Fridge", "level", "half", "1 pint", 10, 4, 6),
    ("Ribeye steak", "Whole Foods", "Meat & Seafood", "Fridge", "count", 2, "12 oz", 1, 2, None),
    ("Ribeye steak", "BJ's", "Meat & Seafood", "Chest freezer 1", "count", 4, "12 oz", 40, 140, None),
    ("Ground beef 80/20", "BJ's", "Meat & Seafood", "Chest freezer 2", "count", 5, "1 lb", 60, 120, None),
    ("Pepperoni pizza", "DiGiorno", "Frozen meals", "Kitchen freezer", "count", 2, "1 pizza", 20, 160, None),
    ("Baby carrots", "Bolthouse", "Produce", "Fridge", "count", 1, "1 lb bag", 2, 5, None),
    ("Sandwich bread", "Dave's Killer Bread", "Bakery", "Pantry", "level", "low", "loaf", 5, 3, 2),
    ("Black beans", "Goya", "Canned goods", "Pantry", "count", 4, "15.5 oz can", 45, 520, None),
    ("Rotel tomatoes", "Rotel", "Canned goods", "Pantry", "count", 2, "10 oz can", 45, 400, None),
]


def cmd_seed_demo(args):
    db.init()
    conn = db.connect()
    if conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]:
        sys.exit("Inventory is not empty, so nothing was added.")
    today = date.today()
    for name, brand, cat, loc, mode, q, pkg, bought, exp, opened in DEMO:
        r = RULES[cat]
        cur = conn.execute(
            """INSERT INTO items (name, brand, cat, loc, mode, qty, level, pkg, bought, exp, opened, ol, type, col, created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, brand, cat, loc, mode, q if mode == "count" else 1, q if mode == "level" else "full", pkg,
             (today - timedelta(days=bought)).isoformat(), (today + timedelta(days=exp)).isoformat(),
             (today - timedelta(days=opened)).isoformat() if opened is not None else None,
             r["open"], r["type"], r["col"], "demo"))
        conn.execute("INSERT INTO events (item_id, item_name, cat, loc, username, action, note) VALUES (?,?,?,?,?,?,?)",
                     (cur.lastrowid, name, cat, loc, "demo", "Added", loc))
    conn.commit()
    print(f"Added {len(DEMO)} demo items.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add-user"); a.add_argument("username"); a.add_argument("display", nargs="?"); a.add_argument("--password"); a.add_argument("--no-password", action="store_true"); a.set_defaults(fn=cmd_add_user)
    s = sub.add_parser("set-password"); s.add_argument("username"); s.add_argument("--password"); s.add_argument("--no-password", action="store_true"); s.set_defaults(fn=cmd_set_password)
    sub.add_parser("list-users").set_defaults(fn=cmd_list_users)
    b = sub.add_parser("backup"); b.add_argument("folder"); b.add_argument("--keep", type=int, default=30); b.set_defaults(fn=cmd_backup)
    sub.add_parser("seed-demo").set_defaults(fn=cmd_seed_demo)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
