"""Shelf-life rules and fixed lists.

The numbers below are starter values in the spirit of USDA FoodKeeper guidance.
They are served to the web app via /api/config so there is one source of truth.
`fridge`, `freezer` and `pantry` are days of shelf life counted from the
purchase date; 0 means that location is not recommended. `open` is how many
days the item keeps after it has been opened.
"""

LOCS = ("Fridge", "Kitchen freezer", "Chest freezer 1", "Chest freezer 2", "Pantry")
CATS = (
    "Dairy", "Produce", "Meat & Seafood", "Deli", "Frozen meals",
    "Bakery", "Canned goods", "Dry goods", "Leftovers",
)
LEVELS = ("full", "half", "low")

RULES = {
    "Dairy":          {"fridge": 14,  "freezer": 90,  "pantry": 0,   "open": 7,  "loc": "Fridge",          "type": "carton", "col": "#4F8FD6"},
    "Produce":        {"fridge": 7,   "freezer": 240, "pantry": 4,   "open": 3,  "loc": "Fridge",          "type": "bag",    "col": "#4FA35F"},
    "Meat & Seafood": {"fridge": 3,   "freezer": 180, "pantry": 0,   "open": 2,  "loc": "Fridge",          "type": "tray",   "col": "#C95B55"},
    "Deli":           {"fridge": 7,   "freezer": 60,  "pantry": 0,   "open": 4,  "loc": "Fridge",          "type": "tray",   "col": "#D98C6B"},
    "Frozen meals":   {"fridge": 3,   "freezer": 150, "pantry": 0,   "open": 3,  "loc": "Kitchen freezer", "type": "box",    "col": "#3E6FB5"},
    "Bakery":         {"fridge": 7,   "freezer": 90,  "pantry": 5,   "open": 5,  "loc": "Pantry",          "type": "loaf",   "col": "#C69A57"},
    "Canned goods":   {"fridge": 700, "freezer": 0,   "pantry": 700, "open": 4,  "loc": "Pantry",          "type": "can",    "col": "#B8872F"},
    "Dry goods":      {"fridge": 365, "freezer": 0,   "pantry": 365, "open": 90, "loc": "Pantry",          "type": "jar",    "col": "#8A6BB0"},
    "Leftovers":      {"fridge": 4,   "freezer": 90,  "pantry": 0,   "open": 4,  "loc": "Fridge",          "type": "tub",    "col": "#7E8F86"},
}
THAW_DAYS = 3


def loc_key(loc: str) -> str:
    if loc == "Pantry":
        return "pantry"
    if loc == "Fridge":
        return "fridge"
    return "freezer"


def is_freezer(loc: str) -> bool:
    return loc_key(loc) == "freezer"
