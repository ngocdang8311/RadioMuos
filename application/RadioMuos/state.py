"""Persist user state — volume, last station, history, favorites.

Tat ca luu trong cung 1 file JSON: state.json
"""
import json
import os
import time

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")
MAX_HISTORY = 30

DEFAULTS = {
    "volume": 60,
    "last_url": None,
    "last_tab": 0,
    "favorites": [],   # list of URLs
    "favorite_stations": {},  # url -> {url, name, genre, source}
    "history": [],     # list of {url, name, genre, source, last_played_ts}
    "recent_searches": [],  # list of strings
    "cache": {},       # small API cache: key -> {ts, value}
}


def _default_copy(value):
    if isinstance(value, list):
        return list(value)
    if isinstance(value, dict):
        return dict(value)
    return value


def station_snapshot(station):
    """Return the small stable station shape saved in state.json."""
    if not station:
        return None
    url = station.get("url")
    if not url:
        return None
    return {
        "url": url,
        "name": station.get("name") or url,
        "genre": station.get("genre") or "",
        "source": station.get("source") or "unknown",
    }


def load():
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {k: _default_copy(v) for k, v in DEFAULTS.items()}

    for k, v in DEFAULTS.items():
        data.setdefault(k, _default_copy(v))

    if not isinstance(data.get("favorites"), list):
        data["favorites"] = []
    if not isinstance(data.get("favorite_stations"), dict):
        data["favorite_stations"] = {}
    if not isinstance(data.get("history"), list):
        data["history"] = []
    if not isinstance(data.get("recent_searches"), list):
        data["recent_searches"] = []
    if not isinstance(data.get("cache"), dict):
        data["cache"] = {}

    # Backfill metadata for older states that stored only favorite URLs.
    fav_urls = set(favorite_urls(data))
    for item in data["history"]:
        snap = station_snapshot(item)
        if snap and snap["url"] in fav_urls:
            data["favorite_stations"].setdefault(snap["url"], snap)
    return data


def save(state):
    try:
        tmp_file = STATE_FILE + ".tmp"
        with open(tmp_file, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp_file, STATE_FILE)
    except OSError as e:
        print(f"Save state failed: {e}")


def add_to_history(state, station):
    """Them station vao history (MRU order, deduped)."""
    snap = station_snapshot(station)
    if not snap:
        return
    url = snap["url"]
    state["history"] = [h for h in state["history"] if h.get("url") != url]
    state["history"].insert(0, {
        "url": url,
        "name": snap["name"],
        "genre": snap["genre"],
        "source": snap["source"],
        "last_played_ts": int(time.time()),
    })
    state["history"] = state["history"][:MAX_HISTORY]


def favorite_urls(state):
    favs = state.get("favorites") or []
    return [url for url in favs if isinstance(url, str) and url]


def is_favorite(state, url):
    return bool(url) and url in set(favorite_urls(state))


def add_favorite(state, station):
    snap = station_snapshot(station)
    if not snap:
        return False
    favs = favorite_urls(state)
    if snap["url"] not in favs:
        favs.append(snap["url"])
    state["favorites"] = favs
    state.setdefault("favorite_stations", {})[snap["url"]] = snap
    return True


def remove_favorite(state, url):
    if not url:
        return False
    favs = favorite_urls(state)
    if url not in favs:
        return False
    state["favorites"] = [u for u in favs if u != url]
    state.setdefault("favorite_stations", {}).pop(url, None)
    return True


def favorite_station_list(state):
    meta = state.get("favorite_stations") or {}
    items = []
    for url in favorite_urls(state):
        snap = station_snapshot(meta.get(url) or {"url": url, "name": url})
        if snap:
            items.append(snap)
    return items


def add_recent_search(state, query):
    q = query.strip()
    if not q:
        return
    state["recent_searches"] = [s for s in state["recent_searches"] if s != q]
    state["recent_searches"].insert(0, q)
    state["recent_searches"] = state["recent_searches"][:10]


def cache_get(state, key, max_age_sec=None):
    cache = state.get("cache") or {}
    item = cache.get(key)
    if not isinstance(item, dict):
        return None
    if "value" not in item:
        return None
    if max_age_sec is not None:
        age = time.time() - item.get("ts", 0)
        if age > max_age_sec:
            return None
    return item["value"]


def cache_set(state, key, value):
    state.setdefault("cache", {})[key] = {
        "ts": int(time.time()),
        "value": value,
    }
