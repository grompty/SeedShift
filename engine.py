"""Seedshift engine: settings, qBittorrent/Radarr/Sonarr clients, scanning and matching.

No Flask in here. api.py and app.py import this module; nothing here imports them.

How a scan works
----------------
1. qBittorrent: every torrent, its tracker host and the files it seeds. Files are read from
   disk (stat gives inode + size) when the content path is visible in this container, else
   their sizes come from the qBittorrent API.
2. Radarr/Sonarr: every movie file and every episode file, grouped into seasons.
3. Each library file is linked to torrents by inode (hardlinks share one) with exact file
   size as the fallback. Nothing is written anywhere except /config.
4. The raw links are stored; statuses ("on target", "missing", ...) are computed on read,
   so changing the target tracker never needs a new scan.
"""

import concurrent.futures
import datetime as dt
import http.cookiejar
import json
import logging
import os
import posixpath
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from copy import deepcopy

logging.basicConfig(level=logging.INFO, format="[seedshift] %(message)s")
log = logging.getLogger("seedshift")

APP_VERSION = "0.2.6"

CONFIG_DIR = os.environ.get("CONFIG_DIR", "/config")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")
SCAN_FILE = os.path.join(CONFIG_DIR, "scan.json")
TRACKER_CACHE_FILE = os.path.join(CONFIG_DIR, "tracker-cache.json")
HISTORY_FILE = os.path.join(CONFIG_DIR, "history.jsonl")
HISTORY_KEEP = 500

USER_AGENT = f"seedshift/{APP_VERSION}"
HTTP_TIMEOUT = 30
WORKERS = 4

DEFAULT_SETTINGS = {
    "target_trackers": os.environ.get("TARGET_TRACKERS", ""),
    "match_mode": "auto",            # auto | inode | size
    "min_match_size_mb": "50",       # size matching ignores files smaller than this
    "include_specials": "off",
    "scan_interval_minutes": "360",  # 0 = manual only
    "search_via": "arr",             # arr | prowlarr
    "auto_replace": "off",           # on: after a grab, have the Arr import it even when it isn't an upgrade
}
CONNECTION_TYPES = ("qbittorrent", "radarr", "sonarr", "prowlarr")
TYPE_NAMES = {"qbittorrent": "qBittorrent", "radarr": "Radarr", "sonarr": "Sonarr", "prowlarr": "Prowlarr"}
DEFAULT_URLS = {"qbittorrent": "http://qbittorrent:8080", "radarr": "http://radarr:7878",
                "sonarr": "http://sonarr:8989", "prowlarr": "http://prowlarr:9696"}
MATCH_MODES = ("auto", "inode", "size")
SCAN_INTERVALS = (0, 30, 60, 180, 360, 720, 1440)

SETTINGS_LOCK = threading.RLock()


def utc_now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


# ── Settings ──────────────────────────────────────────────────────────────

def _read_json(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, type(fallback)) else fallback
    except FileNotFoundError:
        return fallback
    except Exception as e:
        log.warning(f"Could not read {path}: {e}")
        return fallback


def _write_json(path, data, private=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        if private:
            json.dump(data, f, ensure_ascii=False, indent=2)
        else:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    if private:
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def load_settings():
    saved = _read_json(SETTINGS_FILE, {})
    settings = dict(DEFAULT_SETTINGS)
    for key in DEFAULT_SETTINGS:
        if key in saved:
            settings[key] = str(saved[key])
    connections = saved.get("connections") if isinstance(saved.get("connections"), list) else []
    # v0.1.x kept one qBittorrent in qbit_url/qbit_username/qbit_password. Move it into the list.
    legacy_url = saved.get("qbit_url") or os.environ.get("QBIT_URL", "")
    legacy_used = saved.get("qbit_username") or saved.get("qbit_password") or os.environ.get("QBIT_URL")
    if legacy_url and legacy_used and not any(c.get("type") == "qbittorrent" for c in connections):
        connections.insert(0, {
            "id": "qbittorrent-1", "name": "qBittorrent", "type": "qbittorrent",
            "url": str(legacy_url).rstrip("/"), "link_url": "",
            "username": saved.get("qbit_username") or os.environ.get("QBIT_USERNAME", ""),
            "password": saved.get("qbit_password") or os.environ.get("QBIT_PASSWORD", ""),
        })
    settings["connections"] = connections
    settings["target_indexers"] = saved.get("target_indexers") if isinstance(saved.get("target_indexers"), list) else []
    settings["path_mappings"] = saved.get("path_mappings") if isinstance(saved.get("path_mappings"), list) else []
    settings["ignored"] = saved.get("ignored") if isinstance(saved.get("ignored"), list) else []
    return settings


SETTINGS = load_settings()


def cfg(key):
    with SETTINGS_LOCK:
        return deepcopy(SETTINGS.get(key, DEFAULT_SETTINGS.get(key, "")))


def save_settings(updated):
    with SETTINGS_LOCK:
        SETTINGS.update(deepcopy(updated))
        _write_json(SETTINGS_FILE, SETTINGS, private=True)


def get_connections(conn_type=None):
    conns = cfg("connections")
    return [c for c in conns if c.get("type") == conn_type] if conn_type else conns


def library_connections():
    return [c for c in cfg("connections") if c.get("type") in ("radarr", "sonarr")]


def get_connection(connection_id):
    return next((c for c in get_connections() if c.get("id") == connection_id), None)


def slugify(value, fallback="item"):
    value = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return value or fallback


def clean_url(url, what):
    url = str(url or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"{what} needs a full URL such as http://host:port.")
    return url


def normalize_host(value):
    """'https://tracker.example.org/announce/abc' or 'tracker.example.org' -> 'tracker.example.org'."""
    value = str(value or "").strip().lower()
    if not value:
        return ""
    if "://" not in value:
        value = "x://" + value
    try:
        return (urllib.parse.urlparse(value).hostname or "").strip(".")
    except ValueError:
        return ""


def target_hosts(raw=None):
    raw = cfg("target_trackers") if raw is None else raw
    hosts = []
    for part in re.split(r"[,\s]+", str(raw or "")):
        host = normalize_host(part)
        if host and host not in hosts:
            hosts.append(host)
    return hosts


def host_is_target(host, targets):
    return bool(host) and any(host == t or host.endswith("." + t) for t in targets)


def validate_connection(raw, existing=None):
    if not isinstance(raw, dict):
        raise ValueError("Invalid connection.")
    existing = existing or {}
    conn_type = str(existing.get("type") or raw.get("type") or "").lower()
    if conn_type not in CONNECTION_TYPES:
        raise ValueError("Connection type must be qBittorrent, Radarr, Sonarr or Prowlarr.")
    name = str(raw.get("name") or "").strip() or TYPE_NAMES[conn_type]
    conn_id = str(raw.get("id") or existing.get("id") or f"{conn_type}-{slugify(name)}-{uuid.uuid4().hex[:6]}")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", conn_id):
        raise ValueError("Connection ID contains invalid characters.")
    url = clean_url(raw.get("url") or DEFAULT_URLS[conn_type], name)
    link_url = str(raw.get("link_url") or "").strip().rstrip("/")
    if link_url:
        link_url = clean_url(link_url, f"{name} browser URL")
    conn = {"id": conn_id, "name": name, "type": conn_type, "url": url, "link_url": link_url}
    if conn_type == "qbittorrent":
        conn["username"] = str(raw.get("username") or "").strip()
        password = str(raw.get("password") or "")
        conn["password"] = "" if raw.get("clear_password") else (password or str(existing.get("password") or ""))
    else:
        api_key = str(raw.get("api_key") or "").strip() or str(existing.get("api_key") or "")
        if not api_key:
            raise ValueError(f"{name} needs an API key.")
        conn["api_key"] = api_key
    return conn


def validate_mappings(raw):
    if not isinstance(raw, list):
        raise ValueError("Path mappings must be a list.")
    out = []
    for m in raw:
        if not isinstance(m, dict):
            raise ValueError("Invalid path mapping.")
        remote = str(m.get("remote") or "").strip()
        local = str(m.get("local") or "").strip()
        if not remote and not local:
            continue
        if not remote.startswith("/") or not local.startswith("/"):
            raise ValueError("Path mappings need absolute paths on both sides, such as /downloads → /data/torrents.")
        out.append({"remote": posixpath.normpath(remote), "local": posixpath.normpath(local)})
    return out


def apply_settings_patch(patch):
    """Partial update from the Settings page. Returns the public settings."""
    if not isinstance(patch, dict):
        raise ValueError("Settings must be an object.")
    updated = {}
    for key, value in patch.items():
        if key == "target_trackers":
            updated[key] = ", ".join(target_hosts(value))
        elif key == "match_mode":
            if value not in MATCH_MODES:
                raise ValueError("Unknown match mode.")
            updated[key] = value
        elif key == "min_match_size_mb":
            try:
                n = int(str(value).strip())
            except ValueError:
                raise ValueError("Minimum size must be a whole number of MB.")
            if not 1 <= n <= 100000:
                raise ValueError("Minimum size must be between 1 and 100000 MB.")
            updated[key] = str(n)
        elif key == "include_specials":
            updated[key] = "on" if value in ("on", True, "true") else "off"
        elif key == "scan_interval_minutes":
            try:
                n = int(value)
            except (TypeError, ValueError):
                raise ValueError("Invalid scan interval.")
            if n not in SCAN_INTERVALS:
                raise ValueError("Invalid scan interval.")
            updated[key] = str(n)
        elif key == "auto_replace":
            updated[key] = "on" if value in ("on", True, "true") else "off"
        elif key == "search_via":
            if value not in ("arr", "prowlarr"):
                raise ValueError("Search must go through the Arrs or Prowlarr.")
            updated[key] = value
        elif key == "target_indexers":
            if not isinstance(value, list):
                raise ValueError("Target indexers must be a list.")
            names = []
            for v in value:
                v = str(v or "").strip()[:120]
                if v and v.lower() not in [n.lower() for n in names]:
                    names.append(v)
            updated[key] = names
        elif key == "path_mappings":
            updated[key] = validate_mappings(value)
        elif key == "connections":
            # Used for removals/reordering only; keys of kept connections stay as saved.
            current = {c["id"]: c for c in get_connections()}
            keep = []
            for c in value if isinstance(value, list) else []:
                cid = str((c or {}).get("id") or "")
                if cid in current:
                    keep.append(current[cid])
            updated[key] = keep
        else:
            raise ValueError(f"Unknown setting: {key}")
    save_settings(updated)
    return public_settings()


def public_settings():
    with SETTINGS_LOCK:
        s = deepcopy(SETTINGS)
    return {
        "settings": {k: s.get(k, "") for k in DEFAULT_SETTINGS},
        "target_indexers": s.get("target_indexers", []),
        "connections": [connection_public(c) for c in s.get("connections", [])],
        "path_mappings": s.get("path_mappings", []),
        "settings_file": SETTINGS_FILE,
    }


def connection_public(c):
    """Everything except secrets (API keys, passwords)."""
    out = {k: c.get(k, "") for k in ("id", "name", "type", "url", "link_url")}
    if c.get("type") == "qbittorrent":
        out["username"] = c.get("username", "")
        out["has_password"] = bool(c.get("password"))
    return out


def set_ignored(key, ignored):
    with SETTINGS_LOCK:
        current = list(SETTINGS.get("ignored", []))
        if ignored and key not in current:
            current.append(key)
        if not ignored:
            current = [k for k in current if k != key]
        save_settings({"ignored": current})


# ── HTTP clients ──────────────────────────────────────────────────────────

class ServiceError(RuntimeError):
    pass


def _describe_http_error(name, e):
    if isinstance(e, urllib.error.HTTPError):
        if e.code in (401, 403):
            return f"{name} rejected the credentials (HTTP {e.code})."
        return f"{name} returned HTTP {e.code}."
    if isinstance(e, urllib.error.URLError):
        return f"Can't reach {name}: {e.reason}."
    return f"{name}: {e}"


def arr_request(connection, method, path, body=None, timeout=HTTP_TIMEOUT):
    """JSON call to Radarr/Sonarr (/api/v3) or Prowlarr (/api/v1); path includes the version."""
    url = f"{connection['url']}{path}"
    headers = {"X-Api-Key": connection.get("api_key", ""), "Accept": "application/json", "User-Agent": USER_AGENT}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    name = connection.get("name", "Arr")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as e:
        # Arrs explain validation failures in the body; pass the first message on.
        detail = ""
        try:
            payload = json.loads(e.read() or b"null")
            if isinstance(payload, list) and payload:
                payload = payload[0]
            if isinstance(payload, dict):
                detail = str(payload.get("errorMessage") or payload.get("message") or "")[:200]
        except Exception:
            pass
        msg = _describe_http_error(name, e)
        raise ServiceError(f"{msg} {detail}".strip()) from None
    except Exception as e:
        raise ServiceError(_describe_http_error(name, e)) from None


def arr_get(connection, path, timeout=HTTP_TIMEOUT):
    return arr_request(connection, "GET", path, timeout=timeout)


class QBit:
    """qBittorrent Web API v2 with a cookie session. Logs in again once on 403."""

    def __init__(self, url, username, password, name="qBittorrent"):
        self.name = name
        self.url = url.rstrip("/")
        self.username = username
        self.password = password
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.logged_in = False

    def _open(self, path, data=None, params=None):
        url = self.url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body, headers={
            "Referer": self.url + "/", "User-Agent": USER_AGENT,
        })
        with self.opener.open(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.read().decode("utf-8", "replace")

    def login(self):
        if not self.username:
            self.logged_in = True     # auth bypassed for this network in qBittorrent
            return
        try:
            text = self._open("/api/v2/auth/login", data={"username": self.username, "password": self.password}).strip()
        except Exception as e:
            raise ServiceError(_describe_http_error(self.name, e)) from None
        if text == "Fails.":
            raise ServiceError(f"{self.name} refused the username or password.")
        # Versions differ in what a successful login returns ("Ok.", empty, other text),
        # so trust the session, not the reply: a protected call must work now.
        try:
            self._open("/api/v2/app/version")
        except urllib.error.HTTPError as e:
            reply = f' It replied "{text[:80]}".' if text else ""
            raise ServiceError(f"{self.name} login didn't give a session (HTTP {e.code} afterwards).{reply}") from None
        except Exception as e:
            raise ServiceError(_describe_http_error(self.name, e)) from None
        self.logged_in = True

    def get(self, path, params=None):
        if not self.logged_in:
            self.login()
        try:
            return self._open(path, params=params)
        except urllib.error.HTTPError as e:
            if e.code == 403:
                if not self.username:
                    raise ServiceError(f"{self.name} needs a login. Add the username and password.") from None
                self.login()
                try:
                    return self._open(path, params=params)
                except Exception as e2:
                    raise ServiceError(_describe_http_error(self.name, e2)) from None
            raise ServiceError(_describe_http_error(self.name, e)) from None
        except Exception as e:
            raise ServiceError(_describe_http_error(self.name, e)) from None

    def json(self, path, params=None):
        text = self.get(path, params)
        try:
            return json.loads(text)
        except ValueError:
            raise ServiceError(f"{self.name} returned something that isn't JSON.") from None

    def version(self):
        return self.get("/api/v2/app/version").strip()


def qbit_client(conn):
    return QBit(conn["url"], conn.get("username", ""), conn.get("password", ""), conn.get("name") or "qBittorrent")


API_ROOT = {"radarr": "/api/v3", "sonarr": "/api/v3", "prowlarr": "/api/v1"}


def check_connection(conn):
    """Talk to the service once. Returns its version or raises ServiceError."""
    if conn["type"] == "qbittorrent":
        client = qbit_client(conn)
        version = client.version()
        if not isinstance(client.json("/api/v2/torrents/info", {"limit": 1}), list):
            raise ServiceError(f"{conn['name']} answered, but not with a torrent list.")
        return version
    status = arr_get(conn, f"{API_ROOT[conn['type']]}/system/status")
    app_name = str((status or {}).get("appName") or "").lower()
    if app_name and app_name != conn["type"]:
        raise ServiceError(f"That URL is {status.get('appName')}, not {TYPE_NAMES[conn['type']]}.")
    return (status or {}).get("version", "unknown")


def test_connection(payload):
    """Test with the submitted values (blank secret keeps the saved one) and save on success."""
    existing = get_connection(str(payload.get("id") or "")) or {}
    if not existing:
        # Adding the same service twice updates it instead of making a duplicate.
        url = str(payload.get("url") or "").strip().rstrip("/")
        existing = next((c for c in get_connections()
                         if c["type"] == str(payload.get("type") or "").lower() and c["url"] == url), {})
        if existing:
            payload = {**payload, "id": existing["id"]}
    conn = validate_connection(payload, existing)
    if conn["type"] == "prowlarr" and any(c["id"] != conn["id"] for c in get_connections("prowlarr")):
        raise ValueError("Only one Prowlarr connection is supported.")
    version = check_connection(conn)
    connections = get_connections()
    for i, c in enumerate(connections):
        if c["id"] == conn["id"]:
            connections[i] = conn
            break
    else:
        connections.append(conn)
    save_settings({"connections": connections})
    return conn, version


# ── Paths ─────────────────────────────────────────────────────────────────

def map_path(path, mappings):
    """Translate a path as qBittorrent/Radarr/Sonarr see it into this container's view."""
    if not path:
        return ""
    path = posixpath.normpath(str(path).replace("\\", "/"))
    for m in sorted(mappings, key=lambda m: len(m["remote"]), reverse=True):
        remote = m["remote"].rstrip("/") or "/"
        if path == remote:
            return m["local"]
        if remote == "/" or path.startswith(remote + "/"):
            rest = path[len(remote):].lstrip("/") if remote != "/" else path.lstrip("/")
            return posixpath.join(m["local"], rest)
    return path


def stat_file(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st


# ── Scan state ────────────────────────────────────────────────────────────

SCAN_LOCK = threading.Lock()
SCAN_STATE = {"running": False, "phase": "", "done": 0, "total": 0, "started_at": None, "error": None}
SCAN_STATE_LOCK = threading.Lock()
SCAN_RESULT = _read_json(SCAN_FILE, {}) or None
SCAN_RESULT_LOCK = threading.Lock()
TRACKER_CACHE = _read_json(TRACKER_CACHE_FILE, {})


def scan_state():
    with SCAN_STATE_LOCK:
        return dict(SCAN_STATE)


def _progress(phase=None, done=None, total=None):
    with SCAN_STATE_LOCK:
        if phase is not None:
            SCAN_STATE["phase"] = phase
        if done is not None:
            SCAN_STATE["done"] = done
        if total is not None:
            SCAN_STATE["total"] = total


def last_scan():
    with SCAN_RESULT_LOCK:
        return SCAN_RESULT


def start_scan(reason="manual"):
    """Start a scan in the background. Returns False if one is already running."""
    if not SCAN_LOCK.acquire(blocking=False):
        return False
    _last_attempt[0] = time.time()
    with SCAN_STATE_LOCK:
        SCAN_STATE.update({"running": True, "phase": "Starting", "done": 0, "total": 0,
                           "started_at": utc_now(), "error": None, "reason": reason})

    def worker():
        global SCAN_RESULT
        try:
            result = run_scan()
            with SCAN_RESULT_LOCK:
                SCAN_RESULT = result
            _write_json(SCAN_FILE, result)
            log.info(f"Scan finished in {result['duration']}s: {len(result['torrents'])} torrents, "
                     f"{len(result['movies'])} movies, {len(result['seasons'])} seasons.")
        except Exception as e:
            log.exception("Scan failed")
            with SCAN_STATE_LOCK:
                SCAN_STATE["error"] = str(e)
        finally:
            with SCAN_STATE_LOCK:
                SCAN_STATE["running"] = False
                SCAN_STATE["phase"] = ""
            SCAN_LOCK.release()

    threading.Thread(target=worker, name="scan", daemon=True).start()
    return True


# ── Scanning ──────────────────────────────────────────────────────────────

# qBittorrent states that mean the torrent is complete and seeding (or about to, when queued).
# Everything else (stopped/paused, error, missing files, still downloading) doesn't count.
SEEDING_STATES = {"uploading", "stalledUP", "forcedUP", "queuedUP", "checkingUP"}
STATE_LABELS = {
    "pausedUP": "stopped", "stoppedUP": "stopped", "error": "error", "missingFiles": "missing files",
    "moving": "moving", "unknown": "unknown state",
}


def torrent_is_seeding(state):
    return not state or state in SEEDING_STATES      # no state = scan from before v0.1.3


def state_label(state):
    if torrent_is_seeding(state):
        return "seeding"
    return STATE_LABELS.get(state, "downloading" if state.endswith("DL") or state in ("metaDL", "allocating") else state)


def tracker_host_from_url(url):
    url = str(url or "")
    if not url or url.startswith("**"):      # ** [DHT] **, ** [PeX] **, ** [LSD] **
        return ""
    return normalize_host(url)


def _torrent_host(qb, t):
    host = tracker_host_from_url(t.get("tracker"))
    if host:
        return host
    cached = TRACKER_CACHE.get(t["hash"])
    if cached:
        return cached
    # Stopped torrents and trackers that are down report an empty tracker; ask for the list.
    try:
        for tr in qb.json("/api/v2/torrents/trackers", {"hash": t["hash"]}):
            host = tracker_host_from_url(tr.get("url"))
            if host:
                return host
    except ServiceError:
        pass
    return ""


def _torrent_files(qb, t, mappings, stats):
    """[(dev, ino, size)] for every file of a torrent. dev/ino are None when not on disk."""
    save = map_path(t.get("save_path"), mappings)
    content = map_path(t.get("content_path") or posixpath.join(t.get("save_path") or "", t.get("name") or ""), mappings)

    st = stat_file(content) if content else None
    if st is not None and os.path.isfile(content):
        stats["disk"] += 1
        return [(st.st_dev, st.st_ino, st.st_size)]
    if st is not None and os.path.isdir(content) and posixpath.normpath(content) != posixpath.normpath(save or "/"):
        out = []
        for root, _dirs, files in os.walk(content):
            for name in files:
                fst = stat_file(os.path.join(root, name))
                if fst is not None:
                    out.append((fst.st_dev, fst.st_ino, fst.st_size))
        stats["disk"] += 1
        return out

    # Not visible here, or files sit loose in the save folder: ask qBittorrent for the list.
    try:
        listing = qb.json("/api/v2/torrents/files", {"hash": t["hash"]})
    except ServiceError:
        stats["unreadable"] += 1
        return []
    out = []
    seen_on_disk = False
    for f in listing:
        if f.get("priority") == 0:          # not downloaded, so not seeded
            continue
        fst = stat_file(posixpath.join(save, f.get("name") or "")) if save else None
        if fst is not None:
            seen_on_disk = True
            out.append((fst.st_dev, fst.st_ino, fst.st_size))
        else:
            out.append((None, None, int(f.get("size") or 0)))
    stats["disk" if seen_on_disk else "api"] += 1
    return out


def _scan_qbit(mappings, errors):
    """Read every qBittorrent client into one torrent table and one set of indexes.

    Torrents are keyed "<client id>/<hash>", so the same torrent in two clients stays two rows.
    """
    torrents = {}
    inode_index = {}
    size_index = {}
    stats = {"disk": 0, "api": 0, "unreadable": 0}
    clients = get_connections("qbittorrent")
    if not clients:
        errors.append({"source": "qbittorrent", "message": "No qBittorrent connection. Add one in Settings → Connections."})
        return torrents, inode_index, size_index, stats

    lock = threading.Lock()
    seen_hashes = set()
    for conn in clients:
        _progress(f"Reading {conn['name']}", 0, 0)
        try:
            qb = qbit_client(conn)
            listing = qb.json("/api/v2/torrents/info")
        except (ServiceError, ValueError) as e:
            errors.append({"source": conn["id"], "message": str(e)})
            continue

        _progress(f"Reading {conn['name']} files", 0, len(listing))
        done = [0]
        local = {"disk": 0, "api": 0, "unreadable": 0}

        def one(t):
            host = _torrent_host(qb, t)
            counts = {"disk": 0, "api": 0, "unreadable": 0}
            files = _torrent_files(qb, t, mappings, counts)
            with lock:
                for k in counts:
                    local[k] += counts[k]
                done[0] += 1
                if done[0] % 25 == 0:
                    _progress(done=done[0])
            return t, host, files

        with concurrent.futures.ThreadPoolExecutor(WORKERS) as pool:
            for t, host, files in pool.map(one, listing):
                h = t["hash"]
                key = f"{conn['id']}/{h}"
                seen_hashes.add(h)
                if host:
                    TRACKER_CACHE[h] = host
                torrents[key] = {
                    "hash": h,
                    "client": conn["id"],
                    "name": t.get("name", ""),
                    "host": host,
                    "size": int(t.get("size") or t.get("total_size") or 0),
                    "category": t.get("category", ""),
                    "state": t.get("state", ""),
                    "seeding": torrent_is_seeding(t.get("state", "")),
                }
                for dev, ino, size in files:
                    if dev is not None:
                        inode_index.setdefault(f"{dev}:{ino}", set()).add(key)
                    if size:
                        size_index.setdefault(size, set()).add(key)
        for k in stats:
            stats[k] += local[k]
        _progress(done=len(listing))

    # Forget cached trackers for torrents that no longer exist in any client.
    if not any(e["source"] in {c["id"] for c in clients} for e in errors):
        for h in [h for h in TRACKER_CACHE if h not in seen_hashes]:
            TRACKER_CACHE.pop(h, None)
    try:
        _write_json(TRACKER_CACHE_FILE, TRACKER_CACHE)
    except OSError as e:
        log.warning(f"Could not save tracker cache: {e}")
    return torrents, inode_index, size_index, stats


def _scan_radarr(conn, errors):
    items = []
    try:
        movies = arr_get(conn, "/api/v3/movie")
    except ServiceError as e:
        errors.append({"source": conn["id"], "message": str(e)})
        return items
    for m in movies:
        if not m.get("hasFile"):
            continue
        mf = m.get("movieFile")
        if not mf:
            try:
                files = arr_get(conn, f"/api/v3/moviefile?movieId={m['id']}")
                mf = files[0] if files else None
            except ServiceError:
                mf = None
        if not mf or not mf.get("path"):
            continue
        items.append({
            "key": f"{conn['id']}:m{m['id']}",
            "kind": "movie",
            "connection_id": conn["id"],
            "title": m.get("title") or "",
            "sort_title": m.get("sortTitle") or (m.get("title") or "").lower(),
            "year": m.get("year") or "",
            "imdb": m.get("imdbId") or "",
            "tmdb": m.get("tmdbId") or "",
            "slug": m.get("titleSlug") or "",
            "quality": ((mf.get("quality") or {}).get("quality") or {}).get("name", ""),
            "release": mf.get("sceneName") or mf.get("releaseGroup") or "",
            "group": mf.get("releaseGroup") or "",
            "files": [{"path": mf["path"], "size": int(mf.get("size") or 0)}],
        })
    return items


def _scan_sonarr(conn, include_specials, errors):
    items = []
    try:
        series_list = arr_get(conn, "/api/v3/series")
    except ServiceError as e:
        errors.append({"source": conn["id"], "message": str(e)})
        return items

    def files_for(series):
        try:
            return series, arr_get(conn, f"/api/v3/episodefile?seriesId={series['id']}")
        except ServiceError as e:
            return series, e

    with_files = [s for s in series_list if ((s.get("statistics") or {}).get("episodeFileCount", 1) or 0) > 0]
    with concurrent.futures.ThreadPoolExecutor(WORKERS) as pool:
        for series, files in pool.map(files_for, with_files):
            if isinstance(files, Exception):
                errors.append({"source": conn["id"], "message": f"{series.get('title')}: {files}"})
                continue
            seasons_meta = {s.get("seasonNumber"): s for s in series.get("seasons") or []}
            by_season = {}
            groups = {}
            for ef in files:
                number = ef.get("seasonNumber")
                if number is None or (number == 0 and not include_specials):
                    continue
                if ef.get("path"):
                    by_season.setdefault(number, []).append({"path": ef["path"], "size": int(ef.get("size") or 0)})
                    groups.setdefault(number, set()).add(str(ef.get("releaseGroup") or "").lower())
            for number, season_files in sorted(by_season.items()):
                stats = (seasons_meta.get(number) or {}).get("statistics") or {}
                total = int(stats.get("totalEpisodeCount") or 0)
                aired = int(stats.get("episodeCount") or 0)
                airing = bool(stats.get("nextAiring"))
                items.append({
                    "key": f"{conn['id']}:s{series['id']}:{number}",
                    "kind": "season",
                    "connection_id": conn["id"],
                    "title": series.get("title") or "",
                    "sort_title": series.get("sortTitle") or (series.get("title") or "").lower(),
                    "year": series.get("year") or "",
                    "season": number,
                    "imdb": series.get("imdbId") or "",
                    "tvdb": series.get("tvdbId") or "",
                    "tmdb": series.get("tmdbId") or "",
                    "slug": series.get("titleSlug") or "",
                    "episodes": len(season_files),
                    "total_episodes": max(total, len(season_files)),
                    "aired_episodes": aired,
                    "airing": airing,
                    "files": season_files,
                    # One group for the whole season only when every episode file has the same one.
                    "group": next(iter(groups.get(number, set()))) if len(groups.get(number, set())) == 1 else "",
                })
    return items


def run_scan():
    started = time.time()
    mappings = cfg("path_mappings")
    mode = cfg("match_mode") if cfg("match_mode") in MATCH_MODES else "auto"
    min_size = int(cfg("min_match_size_mb") or 50) * 1024 * 1024
    include_specials = cfg("include_specials") == "on"
    errors = []

    torrents, inode_index, size_index, qstats = _scan_qbit(mappings, errors)

    _progress("Reading Radarr and Sonarr", 0, 0)
    library = []
    for conn in library_connections():
        if conn["type"] == "radarr":
            library.extend(_scan_radarr(conn, errors))
        else:
            library.extend(_scan_sonarr(conn, include_specials, errors))

    _progress("Matching files", 0, len(library))
    match_counts = {"inode": 0, "size": 0, "none": 0}
    lib_on_disk = 0
    lib_files = 0
    example_missing_path = ""

    for i, item in enumerate(library):
        for f in item["files"]:
            lib_files += 1
            local = map_path(f["path"], mappings)
            st = stat_file(local)
            if st is not None:
                lib_on_disk += 1
            elif not example_missing_path:
                example_missing_path = local
            hashes, how = set(), "none"
            if st is not None and mode in ("auto", "inode"):
                hashes = inode_index.get(f"{st.st_dev}:{st.st_ino}", set())
                if hashes:
                    how = "inode"
            if not hashes and mode in ("auto", "size"):
                size = st.st_size if st is not None else f["size"]
                if size >= min_size:
                    hashes = size_index.get(size, set())
                    if hashes:
                        how = "size"
            match_counts[how] += 1
            f["torrents"] = sorted(hashes)
            f["match"] = how
            f["size"] = st.st_size if st is not None else f["size"]
        item["size"] = sum(f["size"] for f in item["files"])
        if i % 200 == 0:
            _progress(done=i)

    movies = [x for x in library if x["kind"] == "movie"]
    seasons = [x for x in library if x["kind"] == "season"]

    return {
        "version": APP_VERSION,
        "scanned_at": utc_now(),
        "duration": round(time.time() - started, 1),
        "match_mode": mode,
        "torrents": torrents,
        "movies": movies,
        "seasons": seasons,
        "errors": errors,
        "diagnostics": {
            "torrents_total": len(torrents),
            "torrents_on_disk": qstats["disk"],
            "torrents_api_only": qstats["api"],
            "torrents_unreadable": qstats["unreadable"],
            "library_files": lib_files,
            "library_files_on_disk": lib_on_disk,
            "example_missing_path": example_missing_path,
            "matched_inode": match_counts["inode"],
            "matched_size": match_counts["size"],
            "unmatched": match_counts["none"],
        },
    }


# ── Evaluation (runs on every read; cheap) ────────────────────────────────

def _seeding(torrents, h):
    return torrents[h].get("seeding", True)


def evaluate_movie(item, torrents, targets):
    hashes = [h for h in (item["files"][0].get("torrents", []) if item["files"] else []) if h in torrents]
    active = [h for h in hashes if _seeding(torrents, h)]
    hosts = sorted({torrents[h]["host"] for h in active if torrents[h]["host"]})
    inactive_hosts = sorted({torrents[h]["host"] for h in hashes if h not in active and torrents[h]["host"]} - set(hosts))
    if any(host_is_target(h, targets) for h in hosts):
        status = "on_target"
    elif any(host_is_target(h, targets) for h in inactive_hosts):
        status = "target_stopped"
    elif active:
        status = "missing"
    else:
        status = "not_seeding"
    return status, hosts, inactive_hosts, hashes


def evaluate_season(item, torrents, targets):
    per_file_target = []
    stopped_target = False
    all_hashes, active = set(), set()
    for f in item["files"]:
        hs = [h for h in f.get("torrents", []) if h in torrents]
        all_hashes.update(hs)
        act = {h for h in hs if _seeding(torrents, h)}
        active |= act
        per_file_target.append({h for h in act if host_is_target(torrents[h]["host"], targets)})
        stopped_target |= any(host_is_target(torrents[h]["host"], targets) for h in hs if h not in act)
    hosts = sorted({torrents[h]["host"] for h in active if torrents[h]["host"]})
    inactive_hosts = sorted({torrents[h]["host"] for h in all_hashes - active if torrents[h]["host"]} - set(hosts))
    if per_file_target and all(per_file_target):
        status = "on_target" if set.intersection(*per_file_target) else "singles"
    elif any(per_file_target):
        status = "partial"
    elif stopped_target:
        status = "target_stopped"
    elif active:
        status = "missing"
    else:
        status = "not_seeding"
    on_target_files = sum(1 for x in per_file_target if x)
    return status, hosts, inactive_hosts, sorted(all_hashes), on_target_files


def arr_link(conn, item):
    if not conn or not item.get("slug"):
        return ""
    base = conn.get("link_url")
    if not base:
        host = urllib.parse.urlparse(conn.get("url") or "").hostname or ""
        is_ip = bool(re.fullmatch(r"[0-9.]+|[0-9a-f:]+", host))
        if host in ("localhost", "127.0.0.1", "::1") or (not is_ip and "." not in host):
            return ""      # a Docker-internal name; the browser can't open it
        base = conn["url"]
    return f"{base}/{'movie' if item['kind'] == 'movie' else 'series'}/{item['slug']}"


STATUS_ORDER = {"not_seeding": 0, "missing": 1, "target_stopped": 2, "partial": 3, "singles": 4, "on_target": 5}


# ── Grab history ──────────────────────────────────────────────────────────
# One JSON object per line in /config/history.jsonl, oldest first. Entries get updated in place
# while an automatic replace is in progress, so the file is rewritten (it's capped at HISTORY_KEEP).

HISTORY_LOCK = threading.Lock()


def _read_history_unlocked():
    out = []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning(f"Could not read history: {e}")
    return out


def _write_history_unlocked(entries):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = HISTORY_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for e in entries[-HISTORY_KEEP:]:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        os.replace(tmp, HISTORY_FILE)
    except OSError as e:
        log.warning(f"Could not save history: {e}")


def record_grab(entry):
    """Add one grab attempt, successful or not. Returns the stored entry."""
    entry = {"id": uuid.uuid4().hex[:12], "ts": utc_now(), **entry}
    with HISTORY_LOCK:
        entries = _read_history_unlocked()
        entries.append(entry)
        _write_history_unlocked(entries)
    return entry


def update_grab(entry_id, **changes):
    with HISTORY_LOCK:
        entries = _read_history_unlocked()
        for e in entries:
            if e.get("id") == entry_id:
                e.update(changes)
                break
        else:
            return
        _write_history_unlocked(entries)


def grab_history():
    """All history entries, newest first."""
    with HISTORY_LOCK:
        return list(reversed(_read_history_unlocked()))


def last_grabs():
    """{title key: its newest successful grab}."""
    latest = {}
    for e in grab_history():
        if e.get("ok") and e.get("key") not in latest:
            latest[e["key"]] = {"ts": e["ts"], "release": e.get("release", ""), "replace": (e.get("replace") or {}).get("state")}
    return latest


def evaluated_items(kind):
    """All movies or seasons from the last scan with status for the current target."""
    scan = last_scan()
    if not scan:
        return []
    torrents = scan.get("torrents", {})
    targets = target_hosts()
    ignored = set(cfg("ignored"))
    connections = {c["id"]: c for c in get_connections()}
    grabs = last_grabs()
    out = []
    for item in scan.get("movies" if kind == "movie" else "seasons", []):
        if kind == "movie":
            status, hosts, inactive_hosts, hashes = evaluate_movie(item, torrents, targets)
            on_target_files = 1 if status == "on_target" else 0
        else:
            status, hosts, inactive_hosts, hashes, on_target_files = evaluate_season(item, torrents, targets)
        conn = connections.get(item["connection_id"])
        matches = {f.get("match") for f in item["files"]}
        out.append({
            "key": item["key"],
            "kind": item["kind"],
            "connection_id": item["connection_id"],
            "connection_name": conn["name"] if conn else item["connection_id"],
            "title": item["title"],
            "sort_title": item.get("sort_title") or item["title"].lower(),
            "year": item.get("year") or "",
            "season": item.get("season"),
            "episodes": item.get("episodes"),
            "total_episodes": item.get("total_episodes"),
            "airing": item.get("airing", False),
            "complete": kind == "movie" or (item.get("episodes", 0) >= (item.get("aired_episodes") or item.get("total_episodes", 0)) and not item.get("airing")),
            "quality": item.get("quality", ""),
            "size": item.get("size", 0),
            "status": status,
            "hosts": hosts,
            "target_hosts": [h for h in hosts + inactive_hosts if host_is_target(h, targets)],
            "inactive_hosts": inactive_hosts,
            "torrent_count": len(hashes),
            "on_target_files": on_target_files,
            "match": "inode" if "inode" in matches else "size" if "size" in matches else "none",
            "ignored": item["key"] in ignored,
            "arr_url": arr_link(conn, item),
            "last_grab": grabs.get(item["key"]),
        })
    return out


def item_details(key):
    scan = last_scan()
    if not scan:
        return None
    torrents = scan.get("torrents", {})
    targets = target_hosts()
    for item in scan.get("movies", []) + scan.get("seasons", []):
        if item["key"] != key:
            continue
        files = []
        seen = {}
        for f in item["files"]:
            files.append({"path": f.get("path", ""), "size": f.get("size", 0), "match": f.get("match", "none"),
                          "torrents": f.get("torrents", [])})
            for h in f.get("torrents", []):
                if h in torrents:
                    seen.setdefault(h, 0)
                    seen[h] += 1
        clients = {c["id"]: c["name"] for c in get_connections("qbittorrent")}
        tlist = [{
            "hash": torrents[h].get("hash", h),
            "client": clients.get(torrents[h].get("client"), "") if len(clients) > 1 else "",
            "name": torrents[h]["name"],
            "host": torrents[h]["host"],
            "size": torrents[h]["size"],
            "files_covered": n,
            "is_target": host_is_target(torrents[h]["host"], targets),
            "state": state_label(torrents[h].get("state", "")),
            "seeding": torrents[h].get("seeding", True),
        } for h, n in sorted(seen.items(), key=lambda kv: (-kv[1], torrents[kv[0]]["name"]))]
        return {"key": key, "title": item["title"], "season": item.get("season"), "files": files,
                "file_count": len(item["files"]), "torrents": tlist}
    return None


def overview():
    scan = last_scan()
    targets = target_hosts()
    state = scan_state()
    result = {
        "version": APP_VERSION,
        "targets": targets,
        "scan": state,
        "has_scan": bool(scan),
        "scanned_at": scan.get("scanned_at") if scan else None,
        "duration": scan.get("duration") if scan else None,
        "next_scan_at": next_scan_at(),
        "connections": [connection_public(c) for c in get_connections()],
        "search_via": cfg("search_via"),
        "errors": scan.get("errors", []) if scan else [],
        "diagnostics": scan.get("diagnostics", {}) if scan else {},
        "trackers": [],
        "totals": None,
    }
    if not scan:
        return result

    trackers = {}
    for t in scan["torrents"].values():
        host = t["host"] or "(no tracker)"
        row = trackers.setdefault(host, {"host": host, "count": 0, "size": 0, "stopped": 0, "stopped_size": 0,
                                         "is_target": host_is_target(t["host"], targets)})
        if t.get("seeding", True):
            row["count"] += 1
            row["size"] += t["size"]
        else:
            row["stopped"] += 1
            row["stopped_size"] += t["size"]
    result["trackers"] = sorted(trackers.values(), key=lambda r: -r["size"])

    def summarize(items):
        live = [i for i in items if not i["ignored"]]
        need = [i for i in live if i["status"] != "on_target"]
        return {
            "total": len(live),
            "on_target": len(live) - len(need),
            "need": len(need),
            "need_size": sum(i["size"] for i in need),
            "on_target_size": sum(i["size"] for i in live if i["status"] == "on_target"),
            "ignored": len(items) - len(live),
            "by_status": {s: sum(1 for i in live if i["status"] == s) for s in STATUS_ORDER},
        }

    movies = evaluated_items("movie")
    seasons = evaluated_items("season")
    result["totals"] = {"movies": summarize(movies), "seasons": summarize(seasons)}
    return result


# ── Background scheduler ──────────────────────────────────────────────────

_next_scan = [None]
_last_attempt = [0.0]


def next_scan_at():
    if _next_scan[0] is None:
        return None
    return dt.datetime.fromtimestamp(_next_scan[0], dt.timezone.utc).replace(microsecond=0).isoformat()


def scheduler():
    while True:
        try:
            minutes = int(cfg("scan_interval_minutes") or 0)
            if minutes <= 0:
                _next_scan[0] = None
            else:
                scan = last_scan()
                last = None
                if scan and scan.get("scanned_at"):
                    try:
                        last = dt.datetime.fromisoformat(scan["scanned_at"]).timestamp()
                    except ValueError:
                        last = None
                due = max(last or 0, _last_attempt[0]) + minutes * 60
                _next_scan[0] = max(due, time.time())
                if time.time() >= due and not scan_state()["running"] and library_connections():
                    _last_attempt[0] = time.time()
                    start_scan("scheduled")
        except Exception as e:
            log.warning(f"Scheduler: {e}")
        time.sleep(30)


_started = [False]


def start_background():
    if _started[0]:
        return
    _started[0] = True
    threading.Thread(target=scheduler, name="scheduler", daemon=True).start()
