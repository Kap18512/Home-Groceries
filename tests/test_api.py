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


def test_shopping_by_store(client):
    login(client)
    cheese = client.post("/api/shopping", json={"name": "Shredded cheese", "store": "Target"}).json()
    paper = client.post("/api/shopping", json={"name": "Paper towels", "store": "BJ's Wholesale"}).json()
    soda = client.post("/api/shopping", json={"name": "Soda", "store": "Publix", "note": "BOGO"}).json()
    anywhere = client.post("/api/shopping", json={"name": "Bananas"}).json()
    by_name = {i["name"]: i for i in client.get("/api/shopping").json()}
    assert by_name["Shredded cheese"]["store"] == "Target"
    assert by_name["Soda"]["note"] == "BOGO" and by_name["Bananas"]["store"] == ""
    # same item may be on two stores' lists, but not twice on the same one
    again = client.post("/api/shopping", json={"name": "shredded cheese", "store": "Target"}).json()
    assert again["id"] == cheese["id"]
    other = client.post("/api/shopping", json={"name": "Shredded cheese", "store": "Walmart"}).json()
    assert other["id"] != cheese["id"]
    # move to another store and change the note
    r = client.patch(f"/api/shopping/{soda['id']}", json={"store": "Walmart", "note": ""})
    assert r.json()["store"] == "Walmart" and r.json()["note"] == ""
    assert client.patch(f"/api/shopping/{soda['id']}", json={"store": "Costco"}).status_code == 422
    assert client.patch("/api/shopping/99999", json={"store": "Target"}).status_code == 404
    assert "Target" in client.get("/api/config").json()["stores"]
    for i in (cheese, paper, soda, anywhere, other):
        client.delete(f"/api/shopping/{i['id']}")


def test_database_upgrade_adds_store_columns():
    import sqlite3
    path = os.path.join(_tmp, "old.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE shopping (id INTEGER PRIMARY KEY, name TEXT NOT NULL, added_by TEXT NOT NULL, "
                 "created_at TEXT NOT NULL DEFAULT (datetime('now')))")
    conn.execute("INSERT INTO shopping (name, added_by) VALUES ('Old item', 'kap')")
    conn.commit(); conn.close()
    old = db.DB_PATH
    db.DB_PATH = type(old)(path)
    try:
        db.init()
        row = db.connect().execute("SELECT name, store, note FROM shopping").fetchone()
        assert (row["name"], row["store"], row["note"]) == ("Old item", "", "")
    finally:
        db.DB_PATH = old


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


# ------------------------------------------------------------------ barcodes and photos
import base64  # noqa: E402

from app import off  # noqa: E402

# A tiny valid-looking JPEG (starts with the JPEG signature); the server only checks the signature and size.
JPEG = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe0" + b"0" * 200).decode()
FAKE_PRODUCTS = {
    "0021000614505": {"name": "Cream Cheese Brick", "brand": "Philadelphia", "pkg": "8 oz (226 g)",
                      "cat": "Dairy", "image_url": "https://images.example/cc.jpg"},
    "0041331021025": {"name": "Black Beans", "brand": "Goya", "pkg": "15.5 oz", "cat": None, "image_url": ""},
    "0049000028911": {"name": "Ginger Ale", "brand": "Canada Dry", "pkg": "12 pack", "cat": "Dry goods",
                      "image_url": "https://images.example/ga.jpg"},
}


@pytest.fixture()
def fake_off(monkeypatch):
    calls = []

    def lookup(code):
        calls.append(code)
        return FAKE_PRODUCTS.get(code)

    monkeypatch.setattr(off, "lookup", lookup)
    monkeypatch.setattr(off, "fetch_image", lambda url: (b"\xff\xd8\xff" + b"x" * 50, "image/jpeg") if url else None)
    return calls


def test_normalize():
    assert off.normalize("021000614505") == "0021000614505"        # UPC-A padded to EAN-13
    assert off.normalize("0 21000 61450 5") == "0021000614505"      # spaces ignored
    assert off.normalize("00021000614505") == "0021000614505"       # GTIN-14 trimmed
    assert off.normalize("12345670") == "12345670"                  # EAN-8
    assert off.normalize("123") is None and off.normalize("abc") is None


def test_guess_category():
    g = off.guess_category
    assert g(["en:dairies", "en:cheeses", "en:cream-cheeses"]) == "Dairy"
    assert g(["en:canned-foods", "en:canned-vegetables", "en:legumes"]) == "Canned goods"
    assert g(["en:frozen-foods", "en:pizzas"]) == "Frozen meals"
    assert g(["en:frozen-desserts", "en:ice-creams"]) == "Frozen meals"   # not Dairy
    assert g(["en:spreads", "en:peanut-butters"]) == "Dry goods"          # not Dairy
    assert g(["en:meats", "en:poultries", "en:chicken"]) == "Meat & Seafood"
    assert g(["en:cold-cuts", "en:meats"]) == "Deli"
    assert g(["en:breads"]) == "Bakery"
    assert g(["en:something-unusual"]) is None and g(None) is None


def test_barcode_lookup_caches_product_and_photo(client, fake_off):
    login(client)
    r = client.get("/api/barcode/021000614505").json()
    assert r["found"] and r["product"]["name"] == "Cream Cheese Brick" and r["product"]["cat"] == "Dairy"
    assert r["product"]["photo_v"] == 1 and r["barcode"] == "0021000614505"
    again = client.get("/api/barcode/0021000614505").json()
    assert again["product"]["id"] == r["product"]["id"]
    assert fake_off == ["0021000614505"]  # second time came from our own catalog, no network call
    assert client.get(f"/api/products/{r['product']['id']}/photo").content.startswith(b"\xff\xd8\xff")


def test_barcode_not_found_and_offline(client, fake_off, monkeypatch):
    login(client)
    assert client.get("/api/barcode/0000000000017").json() == {"found": False, "barcode": "0000000000017"}
    assert client.get("/api/barcode/banana").status_code == 422

    def down(code):
        raise off.Unavailable("no route")

    monkeypatch.setattr(off, "lookup", down)
    r = client.get("/api/barcode/0000000000024").json()
    assert r == {"found": False, "offline": True, "barcode": "0000000000024"}


def test_scan_to_item_links_product_and_remembers_corrections(client, fake_off):
    login(client)
    p = client.get("/api/barcode/0041331021025").json()["product"]
    assert p["cat"] is None  # unknown category: the app asks instead of guessing
    it = new_item(client, name="Black Beans", brand="Goya", cat="Canned goods", loc="Pantry", pkg="15.5 oz can",
                  product_id=p["id"], barcode="0041331021025")
    assert it["product_id"] == p["id"] and it["photo_v"] is None
    assert client.get("/api/barcode/0041331021025").json()["product"]["cat"] == "Canned goods"  # remembered


def test_unknown_barcode_is_learned_on_save(client, fake_off):
    login(client)
    it = new_item(client, name="Mystery Sauce", brand="Store", cat="Canned goods", loc="Pantry", barcode="0000000000031")
    assert it["product_id"]
    again = client.get("/api/barcode/0000000000031").json()
    assert again["found"] and again["product"]["name"] == "Mystery Sauce" and again["product"]["id"] == it["product_id"]


def test_photo_upload_links_every_purchase_of_the_same_thing(client):
    login(client)
    a = new_item(client, name="Shredded Mozzarella", brand="Kraft", cat="Dairy")
    b = new_item(client, name="shredded mozzarella", brand="kraft", cat="Dairy")
    assert a["product_id"] is None
    r = client.post(f"/api/items/{a['id']}/photo", json={"image": JPEG})
    assert r.status_code == 200 and r.json()["photo_v"] == 1
    items = {i["id"]: i for i in client.get("/api/items").json()}
    assert items[a["id"]]["photo_v"] == 1 and items[b["id"]]["photo_v"] == 1  # the other purchase shares it
    assert client.get(f"/api/products/{r.json()['product_id']}/photo").status_code == 200
    # a later purchase of the same thing picks the photo up automatically
    c = new_item(client, name="Shredded Mozzarella", brand="Kraft", cat="Dairy")
    assert c["product_id"] == r.json()["product_id"]
    assert client.post(f"/api/items/{a['id']}/photo", json={"image": JPEG}).json()["photo_v"] == 2
    assert client.get(f"/api/items/{a['id']}/events").json()[0]["action"] == "Photo"


def test_photo_validation(client):
    login(client)
    it = new_item(client, name="Photo test")
    bad_type = "data:image/png;base64," + base64.b64encode(b"\x89PNG").decode()
    not_jpeg = "data:image/jpeg;base64," + base64.b64encode(b"hello world").decode()
    huge = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff" + b"0" * 450_000).decode()
    for body in (bad_type, not_jpeg, "data:image/jpeg;base64,@@@"):
        assert client.post(f"/api/items/{it['id']}/photo", json={"image": body}).status_code == 422
    assert client.post(f"/api/items/{it['id']}/photo", json={"image": huge}).status_code in (413, 422)
    client.cookies.clear()
    assert client.post(f"/api/items/{it['id']}/photo", json={"image": JPEG}).status_code == 401
    assert client.get("/api/products/1/photo").status_code == 401


def test_database_upgrade_adds_product_column():
    import sqlite3
    path = os.path.join(_tmp, "old2.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL, brand TEXT NOT NULL DEFAULT '', "
                 "cat TEXT NOT NULL, loc TEXT NOT NULL, mode TEXT NOT NULL, qty INTEGER NOT NULL DEFAULT 1, "
                 "level TEXT NOT NULL DEFAULT 'full', pkg TEXT NOT NULL DEFAULT '', bought TEXT NOT NULL, exp TEXT NOT NULL, "
                 "opened TEXT, ol INTEGER NOT NULL DEFAULT 0, type TEXT NOT NULL, col TEXT NOT NULL, created_by TEXT NOT NULL, "
                 "created_at TEXT NOT NULL DEFAULT (datetime('now')), removed_at TEXT, removed_reason TEXT)")
    conn.execute("INSERT INTO items (name,cat,loc,mode,bought,exp,type,col,created_by) VALUES ('Old','Dairy','Fridge','count','2026-01-01','2026-01-10','carton','#fff','kap')")
    conn.commit(); conn.close()
    old = db.DB_PATH
    db.DB_PATH = type(old)(path)
    try:
        db.init()
        row = db.connect().execute("SELECT name, product_id FROM items").fetchone()
        assert row["name"] == "Old" and row["product_id"] is None
    finally:
        db.DB_PATH = old


def test_scanning_gives_existing_rows_the_product_photo(client, fake_off):
    login(client)
    old = new_item(client, name="Ginger Ale", brand="Canada Dry", cat="Dry goods", loc="Pantry")  # bought before scanning
    assert old["product_id"] is None
    p = client.get("/api/barcode/0049000028911").json()["product"]
    new_item(client, name="Ginger Ale", brand="Canada Dry", cat="Dry goods", loc="Pantry", product_id=p["id"], barcode="0049000028911")
    rows = {i["id"]: i for i in client.get("/api/items").json()}
    assert rows[old["id"]]["product_id"] == p["id"] and rows[old["id"]]["photo_v"] == 1
