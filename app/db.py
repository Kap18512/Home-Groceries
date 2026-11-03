import hashlib
import hmac
import os
import secrets
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("GROCERIES_DB", Path(__file__).resolve().parent.parent / "data" / "groceries.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  display TEXT NOT NULL,
  pw_hash TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  expires_at TEXT NOT NULL
);
-- What a thing is, independent of any one purchase: remembers barcode, category and photo.
CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY,
  barcode TEXT UNIQUE,
  name TEXT NOT NULL,
  brand TEXT NOT NULL DEFAULT '',
  cat TEXT,
  pkg TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'user',   -- 'user' or 'openfoodfacts'
  photo BLOB,
  photo_type TEXT,
  photo_v INTEGER,                        -- NULL means no photo; bumps on every change
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  brand TEXT NOT NULL DEFAULT '',
  cat TEXT NOT NULL,
  loc TEXT NOT NULL,
  mode TEXT NOT NULL CHECK (mode IN ('count','level')),
  qty INTEGER NOT NULL DEFAULT 1,
  level TEXT NOT NULL DEFAULT 'full',
  pkg TEXT NOT NULL DEFAULT '',
  bought TEXT NOT NULL,
  exp TEXT NOT NULL,
  opened TEXT,
  ol INTEGER NOT NULL DEFAULT 0,
  type TEXT NOT NULL,
  col TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  removed_at TEXT,
  removed_reason TEXT,
  product_id INTEGER REFERENCES products(id)
);
CREATE INDEX IF NOT EXISTS items_active ON items(removed_at);
-- Append-only audit log: one row per thing that happened to an item.
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL,
  item_name TEXT NOT NULL,
  cat TEXT NOT NULL,
  loc TEXT NOT NULL,
  username TEXT NOT NULL,
  ts TEXT NOT NULL DEFAULT (datetime('now')),
  action TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS events_item ON events(item_id);
CREATE TABLE IF NOT EXISTS shopping (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  added_by TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  store TEXT NOT NULL DEFAULT '',   -- '' means any store
  note TEXT NOT NULL DEFAULT ''
);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # One connection per request, never shared between requests. FastAPI may open it on one
    # worker thread and use it on another within the same request, so allow that.
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        # Upgrade databases created before shopping items had a store and a note.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(shopping)")}
        if "store" not in cols:
            conn.execute("ALTER TABLE shopping ADD COLUMN store TEXT NOT NULL DEFAULT ''")
        if "note" not in cols:
            conn.execute("ALTER TABLE shopping ADD COLUMN note TEXT NOT NULL DEFAULT ''")
        item_cols = {r["name"] for r in conn.execute("PRAGMA table_info(items)")}
        if "product_id" not in item_cols:
            conn.execute("ALTER TABLE items ADD COLUMN product_id INTEGER REFERENCES products(id)")
        conn.execute("CREATE INDEX IF NOT EXISTS items_product ON items(product_id)")
        conn.commit()
    finally:
        conn.close()


# ---- passwords: scrypt with a per-user salt -------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
