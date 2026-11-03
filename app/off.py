"""Open Food Facts lookups (https://world.openfoodfacts.org), used to turn a barcode into a name,
brand, package size, category guess and a small product photo.

The data is open (ODbL) and the images are CC-BY-SA, so credit Open Food Facts wherever it is shown.
Network failures raise `Unavailable` so the app can fall back to manual entry instead of breaking.
"""
import json
import re
import urllib.error
import urllib.request
from typing import Optional

USER_AGENT = "HomeGroceries/0.2 (self-hosted household inventory)"
API = ("https://world.openfoodfacts.org/api/v2/product/{code}.json"
       "?fields=product_name,generic_name,brands,quantity,categories_tags,image_front_small_url,image_front_url")
MAX_IMAGE_BYTES = 400_000
TIMEOUT = 6


class Unavailable(Exception):
    """Open Food Facts could not be reached or answered with an error."""


def normalize(code: str) -> Optional[str]:
    """Digits only, UPC-A (12) padded to EAN-13, GTIN-14 trimmed to 13. None if it is not a barcode."""
    digits = re.sub(r"\D", "", code or "")
    if len(digits) == 12:
        digits = "0" + digits
    elif len(digits) == 14 and digits.startswith("0"):
        digits = digits[1:]
    return digits if len(digits) in (8, 13) else None


def _get(url: str, limit: int) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read(limit + 1)
            ctype = resp.headers.get_content_type()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return b"", ""
        raise Unavailable(f"Open Food Facts answered {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise Unavailable(str(e)) from e
    if len(data) > limit:
        raise Unavailable("Response was larger than expected")
    return data, ctype


# Checked in order; the first rule with a matching category tag wins. Unknown returns None on purpose:
# a wrong guess would give a perishable the wrong shelf life, so the app asks instead.
_RULES = [
    ("Frozen meals", ("frozen",)),
    ("Canned goods", ("canned", "tinned")),
    ("Dry goods", ("peanut-butter", "nut-butter")),
    ("Deli", ("cold-cuts", "sausages", "hams", "deli", "lunch-meat", "bacon")),
    ("Meat & Seafood", ("meat", "poultr", "seafood", "fishes", "beef", "pork", "chicken")),
    ("Dairy", ("dairies", "cheese", "milk", "yogurt", "yoghurt", "butter", "cream", "eggs")),
    ("Bakery", ("breads", "bakery", "bagels", "tortillas", "buns")),
    ("Produce", ("fresh-fruits", "fresh-vegetables", "fresh-")),
    ("Dry goods", ("cereals", "pastas", "rice", "flours", "sugars", "spices", "snacks", "biscuits",
                   "crackers", "coffees", "teas", "oils", "sauces", "condiments", "beverages", "sodas", "waters")),
]


def guess_category(tags) -> Optional[str]:
    tags = [str(t).lower() for t in (tags or [])]
    for cat, needles in _RULES:
        if any(n in t for t in tags for n in needles):
            return cat
    return None


def lookup(code: str) -> Optional[dict]:
    """Return {name, brand, pkg, cat, image_url} for a normalized barcode, or None if it is not listed."""
    body, _ = _get(API.format(code=code), 200_000)
    if not body:
        return None
    try:
        data = json.loads(body)
    except ValueError as e:
        raise Unavailable("Unreadable answer") from e
    p = data.get("product") or {}
    if data.get("status") != 1 or not p:
        return None
    name = (p.get("product_name") or p.get("generic_name") or "").strip()
    if not name:
        return None
    brand = (p.get("brands") or "").split(",")[0].strip()
    return {
        "name": name[:120],
        "brand": brand[:80],
        "pkg": (p.get("quantity") or "").strip()[:60],
        "cat": guess_category(p.get("categories_tags")),
        "image_url": p.get("image_front_small_url") or p.get("image_front_url") or "",
    }


def fetch_image(url: str) -> Optional[tuple[bytes, str]]:
    """Download a product photo. Returns (bytes, content_type) or None if it is missing or unsuitable."""
    if not url.startswith("https://"):
        return None
    try:
        data, ctype = _get(url, MAX_IMAGE_BYTES)
    except Unavailable:
        return None
    if not data or ctype not in ("image/jpeg", "image/png", "image/webp"):
        return None
    return data, ctype
