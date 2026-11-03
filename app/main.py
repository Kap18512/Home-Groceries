import os
import secrets
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Literal, Optional

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db
from .rules import CATS, LEVELS, LOCS, RULES, THAW_DAYS, is_freezer, loc_key

SESSION_DAYS = 30
COOKIE = "hg_session"
SECURE_COOKIES = os.environ.get("GROCERIES_SECURE_COOKIES", "") == "1"

app = FastAPI(title="Home Groceries", docs_url=None, redoc_url=None, openapi_url=None)
db.init()


# ---------------------------------------------------------------- plumbing

def get_conn() -> Iterator[sqlite3.Connection]:
    conn = db.connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def current_user(
    conn: sqlite3.Connection = Depends(get_conn),
    hg_session: Optional[str] = Cookie(default=None),
) -> sqlite3.Row:
    if not hg_session:
        raise HTTPException(401, "Not signed in")
    row = conn.execute(
        """SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token_hash = ? AND s.expires_at > datetime('now')""",
        (db.token_hash(hg_session),),
    ).fetchone()
    if not row:
        raise HTTPException(401, "Not signed in")
    return row


# Simple brute-force guard: 5 misses per (client, username) locks for a minute.
_fails: dict[tuple[str, str], list[float]] = {}


def _check_lock(key: tuple[str, str]) -> None:
    now = time.time()
    recent = [t for t in _fails.get(key, []) if now - t < 60]
    _fails[key] = recent
    if len(recent) >= 5:
        raise HTTPException(429, "Too many attempts. Wait a minute and try again.")


def log_event(conn, item, user, action: str, note: str = "") -> None:
    conn.execute(
        "INSERT INTO events (item_id, item_name, cat, loc, username, action, note) VALUES (?,?,?,?,?,?,?)",
        (item["id"], item["name"], item["cat"], item["loc"], user["username"], action, note),
    )


def fmt(d: date) -> str:
    return d.strftime("%b %-d")


def item_out(r: sqlite3.Row) -> dict:
    keys = ("id", "name", "brand", "cat", "loc", "mode", "qty", "level", "pkg", "bought",
            "exp", "opened", "ol", "type", "col", "created_by")
    return {k: r[k] for k in keys}


def get_item(conn, item_id: int, include_removed: bool = False) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if not row or (row["removed_at"] and not include_removed):
        raise HTTPException(404, "Item not found")
    return row


# ------------------------------------------------------------------ models

Cat = Literal[CATS]  # type: ignore[valid-type]
Loc = Literal[LOCS]  # type: ignore[valid-type]
Level = Literal[LEVELS]  # type: ignore[valid-type]


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=60)
    password: str = Field(default="", max_length=200)


class ItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    brand: str = Field(default="", max_length=80)
    cat: Cat
    loc: Loc
    mode: Literal["count", "level"] = "count"
    qty: int = Field(default=1, ge=1, le=999)
    level: Level = "full"
    pkg: str = Field(default="", max_length=60)
    bought: date
    exp: Optional[date] = None
    opened: Optional[date] = None


class ActionIn(BaseModel):
    action: Literal["inc", "dec", "level", "open", "move", "used", "tossed", "restore"]
    value: Optional[str] = None
    today: date


class ShoppingIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


# -------------------------------------------------------------------- auth

@app.post("/api/login")
def login(body: LoginIn, request: Request, response: Response, conn: sqlite3.Connection = Depends(get_conn)):
    key = (request.client.host if request.client else "?", body.username.lower())
    _check_lock(key)
    user = conn.execute("SELECT * FROM users WHERE username = ?", (body.username,)).fetchone()
    # A user created with --no-password has an empty hash and signs in by name alone.
    ok = bool(user) and (user["pw_hash"] == "" or db.verify_password(body.password, user["pw_hash"]))
    if not ok:
        _fails.setdefault(key, []).append(time.time())
        raise HTTPException(401, "That username and password do not match.")
    _fails.pop(key, None)
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?,?,?)",
        (db.token_hash(token), user["id"], expires.strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.execute("DELETE FROM sessions WHERE expires_at < datetime('now')")
    response.set_cookie(
        COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax",
        secure=SECURE_COOKIES, path="/",
    )
    return {"username": user["username"], "display": user["display"]}


@app.get("/api/login-users")
def login_users(conn: sqlite3.Connection = Depends(get_conn)):
    """Names of users who sign in without a password, for the tap-your-name screen."""
    rows = conn.execute("SELECT username, display FROM users WHERE pw_hash = '' ORDER BY id").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/logout", status_code=204)
def logout(response: Response, conn: sqlite3.Connection = Depends(get_conn),
           hg_session: Optional[str] = Cookie(default=None)):
    if hg_session:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (db.token_hash(hg_session),))
    response.delete_cookie(COOKIE, path="/")


@app.get("/api/me")
def me(user=Depends(current_user)):
    return {"username": user["username"], "display": user["display"]}


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/config")
def config(user=Depends(current_user)):
    return {"locs": LOCS, "cats": CATS, "levels": LEVELS, "rules": RULES}


# ------------------------------------------------------------------- items

@app.get("/api/items")
def list_items(conn=Depends(get_conn), user=Depends(current_user)):
    rows = conn.execute("SELECT * FROM items WHERE removed_at IS NULL ORDER BY id").fetchall()
    return [item_out(r) for r in rows]


@app.post("/api/items", status_code=201)
def create_item(body: ItemIn, conn=Depends(get_conn), user=Depends(current_user)):
    rule = RULES[body.cat]
    exp = body.exp
    if exp is None:
        days = rule[loc_key(body.loc)]
        exp = body.bought + timedelta(days=days)
    cur = conn.execute(
        """INSERT INTO items (name, brand, cat, loc, mode, qty, level, pkg, bought, exp, opened, ol,
                              type, col, created_by)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (body.name.strip(), body.brand.strip(), body.cat, body.loc, body.mode,
         body.qty if body.mode == "count" else 1, body.level if body.mode == "level" else "full",
         body.pkg.strip(), body.bought.isoformat(), exp.isoformat(),
         body.opened.isoformat() if body.opened else None, rule["open"],
         rule["type"], rule["col"], user["username"]),
    )
    item = get_item(conn, cur.lastrowid)
    log_event(conn, item, user, "Added", body.loc + (f" · ×{body.qty}" if body.mode == "count" else ""))
    if body.opened:
        log_event(conn, item, user, "Opened", f"Use within {rule['open']} days")
    return item_out(item)


@app.put("/api/items/{item_id}")
def edit_item(item_id: int, body: ItemIn, conn=Depends(get_conn), user=Depends(current_user)):
    old = get_item(conn, item_id)
    rule = RULES[body.cat]
    exp = body.exp or date.fromisoformat(old["exp"])
    ol = rule["open"] if body.cat != old["cat"] else old["ol"]
    conn.execute(
        """UPDATE items SET name=?, brand=?, cat=?, loc=?, mode=?, qty=?, level=?, pkg=?, bought=?, exp=?,
                            opened=?, ol=?, type=?, col=? WHERE id=?""",
        (body.name.strip(), body.brand.strip(), body.cat, body.loc, body.mode,
         body.qty if body.mode == "count" else 1, body.level if body.mode == "level" else "full",
         body.pkg.strip(), body.bought.isoformat(), exp.isoformat(),
         body.opened.isoformat() if body.opened else None, ol, rule["type"], rule["col"], item_id),
    )
    new = get_item(conn, item_id)
    changed = [k for k in ("name", "brand", "cat", "loc", "mode", "qty", "level", "pkg", "bought", "exp", "opened")
               if old[k] != new[k]]
    if changed:
        log_event(conn, new, user, "Edited", ", ".join(changed))
    return item_out(new)


@app.post("/api/items/{item_id}/action")
def item_action(item_id: int, body: ActionIn, conn=Depends(get_conn), user=Depends(current_user)):
    a, today = body.action, body.today
    if a == "restore":
        item = get_item(conn, item_id, include_removed=True)
        if not item["removed_at"]:
            raise HTTPException(409, "Item is already active")
        conn.execute("UPDATE items SET removed_at=NULL, removed_reason=NULL WHERE id=?", (item_id,))
        item = get_item(conn, item_id)
        log_event(conn, item, user, "Restored", "Undo")
        return item_out(item)

    item = get_item(conn, item_id)
    rule = RULES[item["cat"]]

    def remove(reason: str):
        conn.execute("UPDATE items SET removed_at=datetime('now'), removed_reason=? WHERE id=?", (reason, item_id))
        log_event(conn, item, user, reason)
        return {"removed": reason, "id": item_id}

    if a in ("used", "tossed"):
        return remove("Used up" if a == "used" else "Tossed")

    if a in ("inc", "dec"):
        if item["mode"] != "count":
            raise HTTPException(400, "This item is tracked by level, not count")
        if a == "dec" and item["qty"] <= 1:
            return remove("Used up")
        qty = item["qty"] + (1 if a == "inc" else -1)
        conn.execute("UPDATE items SET qty=? WHERE id=?", (qty, item_id))
        log_event(conn, item, user, "Quantity", f"{'+1' if a == 'inc' else '−1'}, now ×{qty}")

    elif a == "level":
        if item["mode"] != "level" or body.value not in LEVELS:
            raise HTTPException(400, "Pick full, half or low for an item tracked by level")
        conn.execute("UPDATE items SET level=? WHERE id=?", (body.value, item_id))
        log_event(conn, item, user, "Level", {"full": "Full", "half": "Half", "low": "Almost out"}[body.value])

    elif a == "open":
        if item["opened"]:
            raise HTTPException(409, "Already marked opened")
        ol = item["ol"] or rule["open"]
        conn.execute("UPDATE items SET opened=?, ol=? WHERE id=?", (today.isoformat(), ol, item_id))
        log_event(conn, item, user, "Opened", f"Use within {ol} days")

    elif a == "move":
        if body.value not in LOCS:
            raise HTTPException(400, "Unknown location")
        if body.value != item["loc"]:
            old_loc, new_loc = item["loc"], body.value
            exp = date.fromisoformat(item["exp"])
            action, note = "Moved", f"{old_loc} to {new_loc}"
            if is_freezer(new_loc) and not is_freezer(old_loc) and rule["freezer"]:
                exp = today + timedelta(days=rule["freezer"])
                action, note = "Frozen", f"Good until {fmt(exp)}"
            elif is_freezer(old_loc) and not is_freezer(new_loc):
                exp = today + timedelta(days=min(rule["fridge"], THAW_DAYS))
                action, note = "Thawed", f"Use by {fmt(exp)}"
            conn.execute("UPDATE items SET loc=?, exp=? WHERE id=?", (new_loc, exp.isoformat(), item_id))
            item = get_item(conn, item_id)
            log_event(conn, item, user, action, note)
            return item_out(item)

    return item_out(get_item(conn, item_id))


@app.get("/api/items/{item_id}/events")
def item_events(item_id: int, conn=Depends(get_conn), user=Depends(current_user)):
    get_item(conn, item_id, include_removed=True)
    rows = conn.execute(
        """SELECT e.ts, e.action, e.note, COALESCE(u.display, e.username) AS who
           FROM events e LEFT JOIN users u ON u.username = e.username
           WHERE e.item_id = ? ORDER BY e.id DESC LIMIT 30""",
        (item_id,),
    ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/recent")
def recent(conn=Depends(get_conn), user=Depends(current_user)):
    """Distinct products you have bought, newest first, for the Buy again chips."""
    rows = conn.execute(
        """SELECT name, brand, cat, pkg, mode, MAX(id) AS last_id FROM items
           GROUP BY name, brand ORDER BY last_id DESC LIMIT 8"""
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- shopping

@app.get("/api/shopping")
def shopping_list(conn=Depends(get_conn), user=Depends(current_user)):
    return [dict(r) for r in conn.execute("SELECT id, name FROM shopping ORDER BY id")]


@app.post("/api/shopping", status_code=201)
def shopping_add(body: ShoppingIn, conn=Depends(get_conn), user=Depends(current_user)):
    name = body.name.strip()
    dup = conn.execute("SELECT id, name FROM shopping WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    if dup:
        return dict(dup)
    cur = conn.execute("INSERT INTO shopping (name, added_by) VALUES (?,?)", (name, user["username"]))
    return {"id": cur.lastrowid, "name": name}


@app.delete("/api/shopping/{sid}", status_code=204)
def shopping_remove(sid: int, conn=Depends(get_conn), user=Depends(current_user)):
    conn.execute("DELETE FROM shopping WHERE id = ?", (sid,))


# ------------------------------------------------------------------ static

STATIC = Path(__file__).resolve().parent / "static"
app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
