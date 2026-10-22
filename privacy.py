"""Screenshot mode: API responses with made-up names, so screenshots can be shared as they are.

Turned on per browser (cookie "seedshift_private=1"). Every JSON response from /api is rewritten:
- movie and show titles become invented ones ("Amber Harbor"), also inside release names and paths
- tracker hosts become tracker-xxx.example, indexer names Indexer xxx
- connection addresses become "hidden", qBittorrent usernames "user"
The same real name always gets the same fake one, so a screenshot still makes sense.
Settings can't be saved while it's on, since the page would hold the fake values.
"""

import hashlib
import re
import threading
import urllib.parse

import engine

COOKIE = "seedshift_private"
ADJ = ["Amber", "Silent", "Crimson", "Hollow", "Northern", "Glass", "Velvet", "Iron", "Paper", "Golden", "Quiet", "Distant",
       "Broken", "Hidden", "Electric", "Winter", "Copper", "Lunar", "Savage", "Gentle", "Scarlet", "Restless", "Frozen", "Wild"]
NOUN = ["Harbor", "Signal", "Orchard", "Ferry", "Lantern", "Canyon", "Meridian", "Atlas", "Engine", "Garden", "Comet", "Frontier",
        "Mirror", "Station", "Valley", "Echo", "Cipher", "Horizon", "Tide", "Archive", "Summit", "Circuit", "Lighthouse", "Parade"]

_cache = {"stamp": None, "titles": {}, "regex": None, "repl": {}}
_lock = threading.Lock()


def _h(text, n):
    return int(hashlib.sha1(text.encode("utf-8")).hexdigest(), 16) % n


def fake_host(host):
    return f"tracker-{hashlib.sha1(host.lower().encode()).hexdigest()[:3]}.example"


def fake_indexer(name):
    base = re.sub(r"\s*\(prowlarr\)$", "", str(name), flags=re.I).strip().lower()
    suffix = " (Prowlarr)" if str(name).lower().endswith("(prowlarr)") else ""
    return f"Indexer {hashlib.sha1(base.encode()).hexdigest()[:3].upper()}{suffix}"


def _variants(title):
    """Ways a title shows up in release names and paths: 'Grey's Anatomy', 'Greys.Anatomy', 'Greys Anatomy'."""
    plain = re.sub(r"[^\w\s-]", "", title).strip()
    out = {title, plain}
    for sep in (".", "_", " "):
        out.add(re.sub(r"\s+", sep, plain))
    return {v for v in out if len(v) >= 3}


def _build():
    scan = engine.last_scan() or {}
    stamp = (scan.get("scanned_at"), tuple(engine.target_hosts()), tuple(engine.cfg("target_indexers")),
             tuple(c.get("url", "") for c in engine.get_connections()))
    with _lock:
        if _cache["stamp"] == stamp:
            return _cache
        titles = sorted({i["title"] for i in scan.get("movies", []) + scan.get("seasons", []) if i.get("title")})
        used, fake = set(), {}
        for t in titles:
            n = _h(t, len(ADJ) * len(NOUN))
            name = f"{ADJ[n // len(NOUN)]} {NOUN[n % len(NOUN)]}"
            k = 2
            while name in used:
                name = f"{ADJ[n // len(NOUN)]} {NOUN[n % len(NOUN)]} {k}"
                k += 1
            used.add(name)
            fake[t.lower()] = name
        repl = {}
        for t in titles:
            f = fake[t.lower()]
            for v in _variants(t):
                sep = "." if "." in v and " " not in v else "_" if "_" in v and " " not in v else " "
                repl[v.lower()] = f.replace(" ", sep)
        hosts = {t.get("host") for t in (scan.get("torrents") or {}).values() if t.get("host")} | set(engine.target_hosts())
        for host in hosts:
            repl[host.lower()] = fake_host(host)
        for name in engine.cfg("target_indexers"):
            repl[str(name).lower()] = fake_indexer(name)
        for c in engine.get_connections():
            for key in ("url", "link_url"):
                host = urllib.parse.urlparse(c.get(key) or "").hostname
                if host and len(host) >= 3:
                    repl[host.lower()] = "hidden"
        keys = sorted(repl, key=len, reverse=True)
        regex = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(re.escape(k) for k in keys) + r")(?![A-Za-z0-9])", re.I) if keys else None
        _cache.update(stamp=stamp, titles=fake, regex=regex, repl=repl)
        return _cache


def _text(s, c):
    if not s or c["regex"] is None:
        return s
    return c["regex"].sub(lambda m: c["repl"].get(m.group(0).lower(), m.group(0)), s)


def _url(u):
    p = urllib.parse.urlparse(str(u or ""))
    if not p.scheme:
        return u
    return f"{p.scheme}://hidden{':' + str(p.port) if p.port else ''}"


def mask(data, c=None, key=None):
    c = c or _build()
    if isinstance(data, dict):
        return {k: mask(v, c, k) for k, v in data.items()}
    if isinstance(data, list):
        if key == "indexers":
            return [fake_indexer(x) if isinstance(x, str) else mask(x, c) for x in data]
        return [mask(x, c, key if key in ("hosts", "target_hosts", "inactive_hosts", "targets") else None) for x in data]
    if not isinstance(data, str):
        return data
    if key in ("title", "sort_title") and data.lower() in c["titles"]:
        return c["titles"][data.lower()]
    if key in ("url", "link_url", "arr_url"):
        return _url(data) if key != "arr_url" else data
    if key == "username":
        return "user" if data else data
    if key == "indexer":
        return fake_indexer(data) if data else data
    if key in ("hosts", "target_hosts", "inactive_hosts", "targets", "host") and "." in data:
        return fake_host(data)
    return _text(data, c)


def mask_indexer_list(data):
    """/api/indexers rows carry the indexer in "name"."""
    for row in data.get("indexers", []):
        row["name"] = fake_indexer(row.get("name", ""))
    data["chosen"] = [fake_indexer(n) for n in data.get("chosen", [])]
    return data
