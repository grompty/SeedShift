"""Interactive search for one title, limited to the target indexers, and grabbing a result.

Two ways to search (Settings → Target tracker → Search with):
- "arr":      Radarr/Sonarr's own interactive search. Hits every indexer the Arr has; results
              are filtered to the target here. Grab works like the Arr's Grab button, so it
              also downloads releases the Arr marked as rejected (force grab).
- "prowlarr": Prowlarr searches only the target indexers. Grab pushes the release to
              Radarr/Sonarr (release/push), which applies its own rules and may refuse it.

Either way the Arr does the download, so quality profile, category and tags are its own.
Searches run in a background thread; the browser polls for the result.
"""

import concurrent.futures
import re
import threading
import time
import urllib.parse
import uuid

import engine
from engine import ServiceError, arr_get, arr_request, cfg, get_connection, get_connections

SEARCH_TIMEOUT = 180          # Arr interactive searches wait on every indexer
KEEP_SECONDS = 30 * 60        # Radarr/Sonarr keep search results about this long, too
MAX_RESULTS = 60

SEARCHES = {}
LOCK = threading.Lock()


# ── Indexers ──────────────────────────────────────────────────────────────

def clean_name(name):
    """'Tracker (Prowlarr)' -> 'tracker'. Arrs synced from Prowlarr add that suffix."""
    name = str(name or "").strip()
    if name.lower().endswith("(prowlarr)"):
        name = name[: -len("(prowlarr)")].strip()
    return name.lower()


def base_domain(host):
    parts = [p for p in str(host or "").lower().split(".") if p]
    return ".".join(parts[-2:]) if len(parts) >= 2 else ".".join(parts)


def list_indexers():
    """Indexers known to the Arrs and Prowlarr, with a guess at which ones are the target."""
    targets = {base_domain(h) for h in engine.target_hosts()}
    found = {}
    errors = []

    def add(name, source, urls=()):
        if not name:
            return
        key = clean_name(name)
        row = found.setdefault(key, {"name": name[: -len("(Prowlarr)")].strip() if key != name.lower() else name,
                                     "sources": [], "suggested": False})
        if source not in row["sources"]:
            row["sources"].append(source)
        for u in urls:
            host = engine.normalize_host(u)
            if host and base_domain(host) in targets:
                row["suggested"] = True

    for conn in get_connections():
        try:
            if conn["type"] in ("radarr", "sonarr"):
                for ix in arr_get(conn, "/api/v3/indexer") or []:
                    if ix.get("protocol") != "torrent":
                        continue
                    urls = [f.get("value") for f in ix.get("fields") or [] if f.get("name") == "baseUrl" and f.get("value")]
                    add(ix.get("name"), conn["name"], urls)
            elif conn["type"] == "prowlarr":
                for ix in arr_get(conn, "/api/v1/indexer") or []:
                    if ix.get("protocol") != "torrent":
                        continue
                    add(ix.get("name"), conn["name"], ix.get("indexerUrls") or [])
        except ServiceError as e:
            errors.append(str(e))

    chosen = {clean_name(n) for n in cfg("target_indexers")}
    rows = sorted(found.values(), key=lambda r: (not r["suggested"], r["name"].lower()))
    for r in rows:
        r["chosen"] = clean_name(r["name"]) in chosen
    return {"indexers": rows, "chosen": cfg("target_indexers"), "errors": errors}


def target_indexer_names():
    """(display names, guessed). Chosen target indexers, or the suggested ones when none are chosen."""
    chosen = list(cfg("target_indexers"))
    if chosen:
        return chosen, False
    return [r["name"] for r in list_indexers()["indexers"] if r["suggested"]], True


# ── Item lookup ───────────────────────────────────────────────────────────

def parse_key(key):
    """'<conn>:m<movieId>' or '<conn>:s<seriesId>:<season>'."""
    parts = str(key or "").split(":")
    try:
        if len(parts) == 2 and parts[1].startswith("m"):
            return parts[0], "movie", int(parts[1][1:]), None
        if len(parts) == 3 and parts[1].startswith("s"):
            return parts[0], "season", int(parts[1][1:]), int(parts[2])
    except ValueError:
        pass
    raise ValueError("Unknown title.")


def find_item(key):
    scan = engine.last_scan() or {}
    for item in scan.get("movies", []) + scan.get("seasons", []):
        if item["key"] == key:
            return item
    raise ValueError("That title isn't in the last scan. Scan again and retry.")


def release_group(title):
    """'Movie.2020.1080p.BluRay.x264-GRP' -> 'grp'. Ignores a trailing file extension or [tag]."""
    t = re.sub(r"\[[^\]]*\]$|\.(mkv|mp4|avi|torrent)$", "", str(title or "").strip(), flags=re.I).strip()
    m = re.search(r"-([A-Za-z0-9][A-Za-z0-9._]*)$", t)
    return m.group(1).lower() if m else ""


def same_release(title, release_size, item):
    """Same release group as your file and nearly the same size: very likely the exact release you have.

    Size alone isn't enough, since different groups' encodes can land within a percent of each other.
    """
    mine = str(item.get("group") or "").lower()
    theirs = release_group(title)
    if not mine or not theirs or not (mine == theirs or mine.endswith("-" + theirs)):    # D-Z0N3 parses as z0n3
        return False
    size = item.get("size") or 0
    return bool(release_size and size) and abs(release_size - size) <= size * 0.01


def quality_name(q):
    return (((q or {}).get("quality") or {}).get("name")) or ""


# ── Searching ─────────────────────────────────────────────────────────────

def _arr_search(job, conn, kind, arr_id, season, wanted):
    if kind == "movie":
        releases = arr_get(conn, f"/api/v3/release?movieId={arr_id}", timeout=SEARCH_TIMEOUT) or []
    else:
        releases = arr_get(conn, f"/api/v3/release?seriesId={arr_id}&seasonNumber={season}", timeout=SEARCH_TIMEOUT) or []
    job["total"] = len(releases)
    out = []
    for r in releases:
        if r.get("protocol") != "torrent" or clean_name(r.get("indexer")) not in wanted:
            continue
        out.append({
            "title": r.get("title", ""),
            "indexer": r.get("indexer", ""),
            "size": int(r.get("size") or 0),
            "seeders": r.get("seeders"),
            "leechers": r.get("leechers"),
            "age_hours": r.get("ageHours") if r.get("ageHours") is not None else (r.get("age") or 0) * 24,
            "quality": quality_name(r.get("quality")),
            "cf_score": r.get("customFormatScore"),
            "rejected": bool(r.get("rejected")),
            "rejections": [str(x.get("reason") if isinstance(x, dict) else x) for x in r.get("rejections") or []],
            "full_season": bool(r.get("fullSeason")) if kind == "season" else None,
            "info_url": r.get("infoUrl") or "",
            "_grab": {"guid": r.get("guid"), "indexerId": r.get("indexerId")},
        })
    if not out:
        job["warning"] = _backoff_note(conn, wanted)
    # Approved first, then the Arr's own ranking (custom format score), then seeders.
    out.sort(key=lambda x: (x["rejected"], -(x["cf_score"] or 0), -(x["seeders"] or 0)))
    return out


def _backoff_note(conn, wanted):
    """Why an Arr search may have skipped the target: the indexer is in failure backoff."""
    try:
        names = {ix["id"]: ix.get("name") for ix in arr_get(conn, "/api/v3/indexer") or []}
        for st in arr_get(conn, "/api/v3/indexerstatus") or []:
            name = names.get(st.get("indexerId"))
            if name and clean_name(name) in wanted and st.get("disabledTill"):
                until = str(st["disabledTill"]).replace("T", " ")[:16]
                return (f"{name} is temporarily disabled in {engine.TYPE_NAMES[conn['type']]} after failures "
                        f"(until {until} UTC), so this search skipped it. Try Prowlarr, or wait.")
    except ServiceError:
        pass
    return None


def _prowlarr_ids(prowlarr, wanted):
    ids = [ix["id"] for ix in arr_get(prowlarr, "/api/v1/indexer") or [] if clean_name(ix.get("name")) in wanted]
    if not ids:
        raise ServiceError("None of the target indexers exist in Prowlarr. Check Settings → Target tracker.")
    return ids


def _prowlarr_query(prowlarr, ids, query, search_type, categories):
    params = [("query", query), ("type", search_type), ("limit", "100")]
    params += [("indexerIds", str(i)) for i in ids] + [("categories", str(c)) for c in categories]
    return arr_get(prowlarr, "/api/v1/search?" + urllib.parse.urlencode(params), timeout=SEARCH_TIMEOUT) or []


def _prowlarr_search(job, conn, kind, arr_id, season, item, wanted):
    prowlarr = next(iter(get_connections("prowlarr")), None)
    if not prowlarr:
        raise ServiceError("Search is set to Prowlarr, but there's no Prowlarr connection. Add one in Settings → Connections.")
    ids = _prowlarr_ids(prowlarr, wanted)
    if kind == "movie":
        cats = [2000]
        results = _prowlarr_query(prowlarr, ids, f"{{ImdbId:{item['imdb']}}}", "movie", cats) if item.get("imdb") else []
        if not results:
            results = _prowlarr_query(prowlarr, ids, f"{item['title']} {item.get('year') or ''}".strip(), "search", cats)
    else:
        cats = [5000]
        results = []
        if item.get("tvdb"):
            results = _prowlarr_query(prowlarr, ids, f"{{TvdbId:{item['tvdb']}}}{{Season:{season:02d}}}", "tvsearch", cats)
        if not results:
            results = _prowlarr_query(prowlarr, ids, f"{item['title']} S{season:02d}", "search", cats)
    results = [r for r in results if r.get("protocol", "torrent") == "torrent"][:MAX_RESULTS]
    job["total"] = len(results)

    # Let the Arr parse each title so quality and custom format scores match its own view.
    def parse(r):
        try:
            return r, arr_get(conn, "/api/v3/parse?" + urllib.parse.urlencode({"title": r.get("title", "")}))
        except ServiceError:
            return r, None

    out = []
    with concurrent.futures.ThreadPoolExecutor(6) as pool:
        for r, parsed in pool.map(parse, results):
            parsed = parsed or {}
            info = parsed.get("parsedMovieInfo") or parsed.get("parsedEpisodeInfo") or {}
            if kind == "movie" and (parsed.get("movie") or {}).get("id") not in (None, arr_id):
                job["hidden"] += 1
                continue
            if kind == "season":
                if (parsed.get("series") or {}).get("id") not in (None, arr_id) or \
                        (info.get("seasonNumber") is not None and info.get("seasonNumber") != season):
                    job["hidden"] += 1
                    continue
            out.append({
                "title": r.get("title", ""),
                "indexer": r.get("indexer", ""),
                "size": int(r.get("size") or 0),
                "seeders": r.get("seeders"),
                "leechers": r.get("leechers"),
                "age_hours": r.get("ageHours") if r.get("ageHours") is not None else (r.get("age") or 0) * 24,
                "quality": quality_name(info.get("quality")),
                "cf_score": parsed.get("customFormatScore"),
                "rejected": False,
                "rejections": [],
                "full_season": bool(info.get("fullSeason")) if kind == "season" else None,
                "info_url": r.get("infoUrl") or "",
                "_push": {
                    "title": r.get("title"), "downloadUrl": r.get("downloadUrl"), "magnetUrl": r.get("magnetUrl"),
                    "infoUrl": r.get("infoUrl"), "guid": r.get("guid"), "indexer": r.get("indexer"),
                    "protocol": "torrent", "publishDate": r.get("publishDate"), "size": r.get("size"),
                    "seeders": r.get("seeders"), "leechers": r.get("leechers"),
                    **({"movieId": arr_id} if kind == "movie" else {"seriesId": arr_id}),
                },
            })
    out.sort(key=lambda x: (-(x["cf_score"] or 0), -(x["seeders"] or 0)))
    return out


def _run(job_id):
    with LOCK:
        job = SEARCHES[job_id]
    try:
        conn_id, kind, arr_id, season = parse_key(job["key"])
        conn = get_connection(conn_id)
        if not conn:
            raise ServiceError("That title's Radarr/Sonarr connection no longer exists.")
        item = find_item(job["key"])
        names, guessed = target_indexer_names()
        if not names:
            raise ServiceError("No target indexer chosen. Pick it in Settings → Target tracker.")
        job["indexers"] = names
        job["guessed"] = guessed
        wanted = [clean_name(n) for n in names]
        if job["via"] == "prowlarr":
            results = _prowlarr_search(job, conn, kind, arr_id, season, item, set(wanted))
        else:
            results = _arr_search(job, conn, kind, arr_id, season, set(wanted))
        for r in results:
            r["same_release"] = same_release(r["title"], r["size"], item)
        job["results"] = results[:MAX_RESULTS]
        job["hidden"] += max(0, job["total"] - len(results)) if job["via"] == "arr" else 0
        job["status"] = "done"
    except (ServiceError, ValueError) as e:
        job["status"] = "error"
        job["error"] = str(e)
    except Exception as e:
        engine.log.exception("Search failed")
        job["status"] = "error"
        job["error"] = f"Search failed: {e}"
    job["finished_at"] = time.time()


def start(key):
    parse_key(key)
    now = time.time()
    with LOCK:
        for jid in [j for j, v in SEARCHES.items() if now - v["started_at"] > KEEP_SECONDS]:
            SEARCHES.pop(jid, None)
        running = next((j for j in SEARCHES.values() if j["key"] == key and j["status"] == "running"), None)
        if running:
            return public(running)
        job = {"id": uuid.uuid4().hex[:12], "key": key, "via": cfg("search_via") or "arr", "status": "running",
               "started_at": now, "finished_at": None, "results": [], "total": 0, "hidden": 0,
               "indexers": [], "guessed": False, "error": None, "warning": None, "grabbed": {}}
        SEARCHES[job["id"]] = job
    threading.Thread(target=_run, args=(job["id"],), name=f"search-{job['id']}", daemon=True).start()
    return public(job)


def get(job_id):
    with LOCK:
        job = SEARCHES.get(job_id)
    if not job:
        raise KeyError(job_id)
    return public(job)


def public(job):
    return {
        "id": job["id"], "key": job["key"], "via": job["via"], "status": job["status"], "error": job["error"],
        "warning": job.get("warning"),
        "auto_replace": cfg("auto_replace") == "on",
        "elapsed": round((job["finished_at"] or time.time()) - job["started_at"]),
        "total": job["total"], "hidden": job["hidden"], "indexers": job["indexers"], "guessed": job["guessed"],
        "results": [{**{k: v for k, v in r.items() if not k.startswith("_")}, "index": i,
                     "grabbed": job["grabbed"].get(i)} for i, r in enumerate(job["results"])],
    }


# ── Grabbing ──────────────────────────────────────────────────────────────

def grab(job_id, index):
    with LOCK:
        job = SEARCHES.get(job_id)
    if not job or job["status"] != "done":
        raise ValueError("This search has expired. Search again.")
    if not isinstance(index, int) or not 0 <= index < len(job["results"]):
        raise ValueError("Unknown result.")
    if job["grabbed"].get(index):
        raise ValueError("Already sent.")
    release = job["results"][index]
    conn_id, kind, _arr_id, season = parse_key(job["key"])
    conn = get_connection(conn_id)
    if not conn:
        raise ServiceError("That title's Radarr/Sonarr connection no longer exists.")
    arr = engine.TYPE_NAMES[conn["type"]]
    try:
        item = find_item(job["key"])
    except ValueError:
        item = {}
    entry = {
        "key": job["key"], "kind": kind, "title": item.get("title", ""), "year": item.get("year", ""), "season": season,
        "release": release["title"], "indexer": release.get("indexer", ""), "size": release.get("size", 0),
        "quality": release.get("quality", ""), "via": job["via"], "forced": bool(release.get("rejected")),
        "connection_id": conn["id"], "connection": conn["name"],
    }

    try:
        if "_grab" in release:
            if time.time() - job["started_at"] > KEEP_SECONDS:
                raise ValueError(f"{arr} has forgotten this search. Search again.")
            arr_request(conn, "POST", "/api/v3/release", release["_grab"], timeout=60)
            message = f"Sent to {arr}."
        else:
            reply = arr_request(conn, "POST", "/api/v3/release/push", release["_push"], timeout=60)
            decision = reply[0] if isinstance(reply, list) and reply else reply if isinstance(reply, dict) else {}
            if decision.get("rejected"):
                reasons = [str(x.get("reason") if isinstance(x, dict) else x) for x in decision.get("rejections") or []]
                raise ServiceError(f"{arr} rejected it: " + ("; ".join(reasons) or "no reason given") + ".")
            message = f"{arr} accepted it."
    except (ServiceError, ValueError) as e:
        engine.record_grab({**entry, "ok": False, "message": str(e)})
        raise
    if cfg("auto_replace") == "on":
        entry["replace"] = {"state": "waiting", "message": "Waiting for the download to show up.", "updated": engine.utc_now()}
    engine.record_grab({**entry, "ok": True, "message": message})
    with LOCK:
        job["grabbed"][index] = message
    engine.log.info(f"Grab: {release['title']} via {job['via']} -> {conn['name']}")
    return message
