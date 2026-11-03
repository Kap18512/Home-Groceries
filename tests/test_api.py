import os
import tempfile
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

# Point the app at a throwaway database before it is imported.
_tmp = tempfile.mkdtemp()
os.environ["GROCERIES_DB"] = os.path.join(_tmp, "test.db")

from app import db  # noqa: E402
from app.main import app, _fails  # noqa: E402

TODAY = date.today()


def iso(d):
    return d.isoformat()


@pytest.fixture(scope="module")
def client():
    db.init()
    conn = db.connect()
    conn.execute("INSERT INTO users (username, display, pw_hash) VALUES (?,?,?)", ("kap", "Kap", db.hash_password("correct-horse")))
    conn.execute("INSERT INTO users (username, display, pw_hash) VALUES (?,?,?)", ("wife", "Wife", db.hash_password("battery-staple")))
    conn.commit()
    conn.close()
    with TestClient(app) as c:
        yield c


def login(client, user="kap", pw="correct-horse"):
    client.cookies.clear()
    r = client.post("/api/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    return r


def new_item(client, **kw):
    body = {"name": "Cream cheese", "brand": "Philadelphia", "cat": "Dairy", "loc": "Fridge", "mode": "count",
            "qty": 2, "pkg": "8 oz", "bought": iso(TODAY), "exp": iso(TODAY + timedelta(days=14))}
    body.update(kw)
    r = client.post("/api/items", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def act(client, item_id, action, value=None, today=TODAY):
    return client.post(f"/api/items/{item_id}/action", json={"action": action, "value": value, "today": iso(today)})


def test_requires_login(client):
    client.cookies.clear()
    assert client.get("/api/items").status_code == 401
    assert client.get("/api/config").status_code == 401
    assert client.get("/api/health").status_code == 200


def test_bad_password_and_lockout(client):
    client.cookies.clear()
    _fails.clear()
    for _ in range(5):
        assert client.post("/api/login", json={"username": "kap", "password": "nope"}).status_code == 401
    assert client.post("/api/login", json={"username": "kap", "password": "correct-horse"}).status_code == 429
    _fails.clear()
    login(client)


def test_logout_ends_session(client):
    login(client)
    assert client.post("/api/logout").status_code == 204
    assert client.get("/api/items").status_code == 401
    login(client)


def test_create_list_and_audit(client):
    login(client)
    it = new_item(client)
    assert it["qty"] == 2 and it["type"] == "carton" and it["created_by"] == "kap"
    assert any(i["id"] == it["id"] for i in client.get("/api/items").json())
    ev = client.get(f"/api/items/{it['id']}/events").json()
    assert ev[0]["action"] == "Added" and ev[0]["who"] == "Kap"


def test_exp_defaults_from_rules(client):
    login(client)
    r = client.post("/api/items", json={"name": "Steak", "cat": "Meat & Seafood", "loc": "Fridge", "bought": iso(TODAY)})
    assert r.json()["exp"] == iso(TODAY + timedelta(days=3))


def test_validation(client):
    login(client)
    assert client.post("/api/items", json={"name": "", "cat": "Dairy", "loc": "Fridge", "bought": iso(TODAY)}).status_code == 422
    assert client.post("/api/items", json={"name": "x", "cat": "Nope", "loc": "Fridge", "bought": iso(TODAY)}).status_code == 422
    assert client.post("/api/items", json={"name": "x", "cat": "Dairy", "loc": "Garage", "bought": iso(TODAY)}).status_code == 422


def test_count_changes_and_use_up(client):
    login(client)
    it = new_item(client, qty=2)
    assert act(client, it["id"], "inc").json()["qty"] == 3
    assert act(client, it["id"], "dec").json()["qty"] == 2
    act(client, it["id"], "dec")
    res = act(client, it["id"], "dec").json()  # last one gone
    assert res["removed"] == "Used up"
    assert all(i["id"] != it["id"] for i in client.get("/api/items").json())
    assert act(client, it["id"], "inc").status_code == 404  # removed items cannot be changed


def test_undo_restores(client):
    login(client)
    it = new_item(client)
    assert act(client, it["id"], "tossed").json()["removed"] == "Tossed"
    assert act(client, it["id"], "restore").status_code == 200
    assert any(i["id"] == it["id"] for i in client.get("/api/items").json())
    assert act(client, it["id"], "restore").status_code == 409
    actions = [e["action"] for e in client.get(f"/api/items/{it['id']}/events").json()]
    assert actions[:2] == ["Restored", "Tossed"]


def test_level_items(client):
    login(client)
    bread = new_item(client, name="Bread", cat="Bakery", loc="Pantry", mode="level")
    assert act(client, bread["id"], "level", "low").json()["level"] == "low"
    assert act(client, bread["id"], "level", "bogus").status_code == 400
    assert act(client, bread["id"], "inc").status_code == 400


def test_open_sets_opened_and_open_life(client):
    login(client)
    it = new_item(client, name="Ricotta", opened=None)
    r = act(client, it["id"], "open").json()
    assert r["opened"] == iso(TODAY) and r["ol"] == 7
    assert act(client, it["id"], "open").status_code == 409


def test_freeze_and_thaw(client):
    login(client)
    it = new_item(client, name="Steak", cat="Meat & Seafood", exp=iso(TODAY + timedelta(days=2)))
    frozen = act(client, it["id"], "move", "Chest freezer 1").json()
    assert frozen["loc"] == "Chest freezer 1" and frozen["exp"] == iso(TODAY + timedelta(days=180))
    # Chest freezer to kitchen freezer stays frozen: date unchanged
    assert act(client, it["id"], "move", "Kitchen freezer").json()["exp"] == iso(TODAY + timedelta(days=180))
    thawed = act(client, it["id"], "move", "Fridge").json()
    assert thawed["exp"] == iso(TODAY + timedelta(days=3))
    actions = [e["action"] for e in client.get(f"/api/items/{it['id']}/events").json()]
    assert actions[:3] == ["Thawed", "Moved", "Frozen"]


def test_edit_logs_changes(client):
    login(client)
    it = new_item(client)
    body = {**it, "name": "Cream cheese tub", "exp": iso(TODAY + timedelta(days=5)), "bought": it["bought"]}
    r = client.put(f"/api/items/{it['id']}", json=body)
    assert r.status_code == 200 and r.json()["name"] == "Cream cheese tub"
    ev = client.get(f"/api/items/{it['id']}/events").json()[0]
    assert ev["action"] == "Edited" and "name" in ev["note"] and "exp" in ev["note"]


def test_shared_between_users_and_who_is_recorded(client):
    login(client, "kap")
    it = new_item(client, name="Shared butter")
    login(client, "wife", "battery-staple")
    assert any(i["id"] == it["id"] for i in client.get("/api/items").json())
    act(client, it["id"], "inc")
    ev = client.get(f"/api/items/{it['id']}/events").json()
    assert ev[0]["who"] == "Wife" and ev[1]["who"] == "Kap"


def test_shopping_list(client):
    login(client)
    a = client.post("/api/shopping", json={"name": "Sour cream"}).json()
    again = client.post("/api/shopping", json={"name": "sour cream"}).json()
    assert a["id"] == again["id"]  # no duplicates
    assert any(s["name"] == "Sour cream" for s in client.get("/api/shopping").json())
    assert client.delete(f"/api/shopping/{a['id']}").status_code == 204
    assert all(s["id"] != a["id"] for s in client.get("/api/shopping").json())


def test_recent_includes_removed_products(client):
    login(client)
    it = new_item(client, name="Heavy cream", brand="Publix")
    act(client, it["id"], "used")
    assert any(p["name"] == "Heavy cream" for p in client.get("/api/recent").json())


def test_static_app_served(client):
    client.cookies.clear()
    assert "Home Groceries" in client.get("/").text
    assert client.get("/app.js").status_code == 200
    assert client.get("/manifest.webmanifest").status_code == 200


def test_no_password_users_sign_in_by_name(client):
    conn = db.connect()
    conn.execute("INSERT INTO users (username, display, pw_hash) VALUES (?,?,?)", ("ken", "Ken", ""))
    conn.commit()
    conn.close()
    client.cookies.clear()
    names = client.get("/api/login-users").json()
    assert names == [{"username": "ken", "display": "Ken"}]  # users with passwords are not listed
    assert client.post("/api/login", json={"username": "ken"}).status_code == 200
    assert client.get("/api/items").status_code == 200
    # A user who has a password can never sign in with an empty one.
    client.cookies.clear()
    assert client.post("/api/login", json={"username": "kap", "password": ""}).status_code == 401
    assert client.post("/api/login", json={"username": "nobody"}).status_code == 401
