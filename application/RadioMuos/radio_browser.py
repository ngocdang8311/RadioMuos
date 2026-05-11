"""Radio Browser API client.

Free public API: https://api.radio-browser.info/
Multiple servers (all.api.radio-browser.info, de1, de2...) — chon 1 mirror.
Khong can API key.
"""
import json
import socket
import ssl
import threading
import urllib.parse
import urllib.request

API_HOST = "de1.api.radio-browser.info"
USER_AGENT = "RadioMuos/0.2 (muOS handheld)"
TIMEOUT = 8


def _request(path):
    url = f"https://{API_HOST}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, socket.timeout, json.JSONDecodeError, ssl.SSLError) as e:
        return {"_error": str(e)}


def search_by_name(query, limit=30):
    """Search station theo ten."""
    params = urllib.parse.urlencode({
        "name": query,
        "limit": limit,
        "hidebroken": "true",
        "order": "clickcount",
        "reverse": "true",
    })
    result = _request(f"/json/stations/search?{params}")
    if isinstance(result, dict) and "_error" in result:
        return [], result["_error"]
    return [_normalize(s) for s in result if s.get("url_resolved")], None


def search_by_tag(tag, limit=30):
    """Search station theo tag (genre)."""
    params = urllib.parse.urlencode({
        "tag": tag,
        "limit": limit,
        "hidebroken": "true",
        "order": "clickcount",
        "reverse": "true",
    })
    result = _request(f"/json/stations/search?{params}")
    if isinstance(result, dict) and "_error" in result:
        return [], result["_error"]
    return [_normalize(s) for s in result if s.get("url_resolved")], None


def search_by_country(country, limit=30):
    """Search station theo quoc gia."""
    params = urllib.parse.urlencode({
        "country": country,
        "limit": limit,
        "hidebroken": "true",
        "order": "clickcount",
        "reverse": "true",
    })
    result = _request(f"/json/stations/bycountry/{urllib.parse.quote(country)}?{params}")
    if isinstance(result, dict) and "_error" in result:
        return [], result["_error"]
    return [_normalize(s) for s in result if s.get("url_resolved")], None


def top_stations(limit=30):
    """Top stations by clickcount."""
    result = _request(f"/json/stations/topclick/{limit}")
    if isinstance(result, dict) and "_error" in result:
        return [], result["_error"]
    return [_normalize(s) for s in result if s.get("url_resolved")], None


def list_tags(limit=50):
    """List top tags sorted by station count.

    Tra ve list of (tag_name, station_count_str), hoac (None, error_str) khi loi.
    """
    params = urllib.parse.urlencode({
        "order": "stationcount",
        "reverse": "true",
        "limit": limit,
        "hidebroken": "true",
    })
    result = _request(f"/json/tags?{params}")
    if isinstance(result, dict) and "_error" in result:
        return None, result["_error"]
    return [(t.get("name", "?"), f"{t.get('stationcount', 0)} stations")
            for t in result if t.get("name")], None


def list_countries(limit=80):
    """List countries sorted by station count.

    Tra ve list of (country_name, station_count_str), hoac (None, error_str).
    """
    params = urllib.parse.urlencode({
        "order": "stationcount",
        "reverse": "true",
        "limit": limit,
        "hidebroken": "true",
    })
    result = _request(f"/json/countries?{params}")
    if isinstance(result, dict) and "_error" in result:
        return None, result["_error"]
    return [(c.get("name", "?"), f"{c.get('stationcount', 0)} stations")
            for c in result if c.get("name")], None


def _normalize(station):
    """Chuyen format Radio Browser -> format chung cua app."""
    tags = station.get("tags", "")
    genre = (tags.split(",")[0] if tags else "").strip() or "Radio"
    country = station.get("country", "")
    return {
        "name": station.get("name", "?").strip()[:60],
        "genre": (genre + (" · " + country if country else ""))[:50],
        "url": station.get("url_resolved", "").strip(),
        "source": "RadioBrowser",
    }


class AsyncSearch:
    """Tach search ra thread de UI khong bi block khi network cham."""

    def __init__(self):
        self.thread = None
        self.results = []
        self.error = None
        self.in_progress = False
        self.lock = threading.Lock()

    def start(self, search_fn, *args, **kwargs):
        """search_fn: search_by_name / search_by_tag / search_by_country"""
        if self.in_progress:
            return False
        self.in_progress = True
        self.results = []
        self.error = None
        self.thread = threading.Thread(
            target=self._run, args=(search_fn,) + args, kwargs=kwargs, daemon=True
        )
        self.thread.start()
        return True

    def _run(self, search_fn, *args, **kwargs):
        try:
            results, err = search_fn(*args, **kwargs)
            with self.lock:
                self.results = results
                self.error = err
        except Exception as e:
            with self.lock:
                self.error = str(e)
        finally:
            self.in_progress = False
