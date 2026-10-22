"""Finish import: have Sonarr import a target season pack that's already in qBittorrent over the
library episodes that come from other releases.

1. preview(key): find the season's target pack (engine.season_packs), ask Sonarr which files in it
   match which episodes (/api/v3/manualimport, by download id, else by the torrent's folder), and
   list the episodes whose current file isn't from the pack. Kept server-side; the browser only
   sends back which ones to import (by index).
2. run(id, indices): one ManualImport command with importMode "copy", which hardlinks when Sonarr
   has hardlinks on and never moves the pack's files, so the torrent keeps seeding. The grab
   history records it, and replace.py follows the command to the end.

Nothing is written to qBittorrent. Sonarr replaces (or recycles) the old library files itself.
"""

import re
import threading
import time
import urllib.parse
import uuid

import engine
from engine import ServiceError, arr_get, arr_request, get_connection
from search import parse_key

KEEP_SECONDS = 15 * 60
JOBS = {}
LOCK = threading.Lock()


def _find_season(scan, key):
    for item in scan.get("seasons", []):
        if item["key"] == key:
            return item
    raise ValueError("That season isn't in the last scan. Scan again and retry.")


def _reasons(mi):
    return [str(r.get("reason") if isinstance(r, dict) else r) for r in mi.get("rejections") or []]


def _source(f, torrents, targets):
    hs = [h for h in f.get("torrents", []) if h in torrents]
    if not hs:
        return "not seeding"
    t = sorted((torrents[h] for h in hs), key=lambda t: (not t.get("seeding", True), not engine.host_is_target(t["host"], targets)))[0]
    return t["host"] or "no tracker"


def _same_path(a, b):
    return bool(a and b) and a.rstrip("/").lower() == b.rstrip("/").lower()


def _manual_import_items(conn, torrent, series_id):
    """Sonarr's view of the pack: by download id while Sonarr still tracks it, else by its folder."""
    did = torrent["hash"].upper()
    try:
        items = arr_get(conn, f"/api/v3/manualimport?downloadId={did}&seriesId={series_id}&filterExistingFiles=false") or []
    except ServiceError:
        items = []
    if any(mi.get("episodes") for mi in items):
        return items, did
    query = urllib.parse.urlencode({"folder": torrent["content_path"], "seriesId": series_id, "filterExistingFiles": "false"})
    return arr_get(conn, f"/api/v3/manualimport?{query}", timeout=60) or [], None


def preview(key):
    scan = engine.last_scan()
    if not scan:
        raise ValueError("No scan yet.")
    conn_id, kind, series_id, season = parse_key(key)
    if kind != "season":
        raise ValueError("Finish import is for seasons.")
    conn = get_connection(conn_id)
    if not conn or conn["type"] != "sonarr":
        raise ServiceError("That season's Sonarr connection no longer exists.")
    item = _find_season(scan, key)
    torrents = scan.get("torrents", {})
    targets = engine.target_hosts()
    packs = engine.season_packs(item, torrents, targets, engine.pack_name_index(torrents, targets))
    if not packs:
        raise ValueError("There's no complete target season pack for this season in qBittorrent.")
    pack_key = packs[0]
    pack = torrents[pack_key]
    if "content_path" not in pack:
        raise ValueError("Run a scan first. This needs a scan from Seedshift v0.3.0 or later.")

    items, download_id = _manual_import_items(conn, pack, series_id)
    by_id = {f.get("id"): f for f in item["files"] if f.get("id")}
    by_episode = {n: f for f in item["files"] for n in f.get("episodes") or []}
    candidates, already, skipped = [], 0, 0
    for mi in items:
        eps = [e for e in mi.get("episodes") or [] if e.get("seasonNumber", season) == season and e.get("id")]
        reasons = _reasons(mi)
        if not eps or any(re.search(r"sample", r, re.I) for r in reasons):
            skipped += 1
            continue
        current = next((by_id[e["episodeFileId"]] for e in eps if e.get("episodeFileId") in by_id), None) or \
            next((by_episode[e.get("episodeNumber")] for e in eps if e.get("episodeNumber") in by_episode), None)
        if current and pack_key in current.get("torrents", []):
            already += 1
            continue
        # Never offer a library file as its own replacement.
        if current and mi.get("path") and _same_path(mi["path"], current.get("path")):
            skipped += 1
            continue
        numbers = sorted(int(e.get("episodeNumber") or 0) for e in eps)
        new_quality, new_rank = engine.quality_info(mi.get("quality"))
        lower = bool(current and current.get("rank") and new_rank and new_rank < current["rank"])
        same = bool(current and new_quality and new_quality == current.get("quality")
                    and (mi.get("releaseGroup") or "").lower() == (current.get("group") or "").lower())
        payload = {"path": mi.get("path"), "seriesId": series_id, "episodeIds": [e["id"] for e in eps],
                   "quality": mi.get("quality"), "languages": mi.get("languages") or [],
                   "releaseGroup": mi.get("releaseGroup") or "", "indexerFlags": mi.get("indexerFlags") or 0}
        if mi.get("releaseType"):
            payload["releaseType"] = mi["releaseType"]
        if download_id:
            payload["downloadId"] = download_id
        candidates.append({
            "episode": engine.episode_label(numbers), "order": numbers[0] if numbers else 9999,
            "current": {"quality": current.get("quality", ""), "group": current.get("group", ""),
                        "source": _source(current, torrents, targets)} if current else None,
            "new": {"quality": new_quality, "group": mi.get("releaseGroup") or ""},
            "lower": lower, "same": same, "checked": not lower and not same,
            "path": mi.get("path") or "", "current_path": current.get("path", "") if current else "",
            "_file": payload,
        })
    candidates.sort(key=lambda c: c["order"])
    # Episodes that share one current file (a multi-episode file) go together: importing only some of
    # them would make Sonarr remove that file and leave the others without one.
    shared = {}
    for i, c in enumerate(candidates):
        if c["current_path"]:
            shared.setdefault(c["current_path"], []).append(i)
    for i, c in enumerate(candidates):
        group = shared.get(c["current_path"], []) if c["current_path"] else []
        c["together"] = group if len(group) > 1 else []
        if c["together"]:
            c["checked"] = not any(candidates[j]["same"] or candidates[j]["lower"] for j in group)

    job = {"id": uuid.uuid4().hex[:12], "key": key, "created": time.time(), "connection_id": conn["id"],
           "title": item["title"], "year": item.get("year", ""), "season": season,
           "pack": {"name": pack["name"], "host": pack["host"], "size": pack.get("size", 0)},
           "candidates": candidates, "already": already, "skipped": skipped,
           "via_folder": download_id is None}
    with LOCK:
        now = time.time()
        for jid in [j for j, v in JOBS.items() if now - v["created"] > KEEP_SECONDS]:
            JOBS.pop(jid, None)
        JOBS[job["id"]] = job
    return public(job)


def public(job):
    return {
        "id": job["id"], "key": job["key"], "title": job["title"], "season": job["season"], "pack": job["pack"],
        "already": job["already"], "skipped": job["skipped"], "via_folder": job["via_folder"],
        "candidates": [{**{k: v for k, v in c.items() if not k.startswith("_") and k != "order"}, "index": i}
                       for i, c in enumerate(job["candidates"])],
    }


def run(job_id, indices):
    with LOCK:
        job = JOBS.get(job_id)
    if not job or time.time() - job["created"] > KEEP_SECONDS:
        raise ValueError("This has expired. Open Finish import again.")
    wanted = {i for i in indices if isinstance(i, int) and 0 <= i < len(job["candidates"])}
    if not wanted:
        raise ValueError("Choose at least one episode.")
    conn = get_connection(job["connection_id"])
    if not conn:
        raise ServiceError("That Sonarr connection no longer exists.")
    files = [c["_file"] for i, c in enumerate(job["candidates"]) if i in wanted]
    count = len(files)
    entry = {
        "key": job["key"], "kind": "season", "title": job["title"], "year": job["year"], "season": job["season"],
        "release": job["pack"]["name"], "indexer": job["pack"]["host"], "size": job["pack"]["size"], "quality": "",
        "via": "import", "action": "import", "forced": False, "connection_id": conn["id"], "connection": conn["name"],
    }
    try:
        # "copy" hardlinks when Sonarr has hardlinks on, and never moves the pack out of the torrent.
        reply = arr_request(conn, "POST", "/api/v3/command", {"name": "ManualImport", "files": files, "importMode": "copy"}, timeout=60)
    except ServiceError as e:
        engine.record_grab({**entry, "ok": False, "message": str(e)})
        raise
    with LOCK:
        JOBS.pop(job_id, None)
    message = f"Sent to Sonarr: import {count} episode{'s' if count != 1 else ''} from the pack."
    engine.record_grab({**entry, "ok": True, "message": message,
                        "replace": {"state": "importing", "message": "Sonarr is importing the episodes.",
                                    "command_id": (reply or {}).get("id"), "updated": engine.utc_now()}})
    engine.log.info(f"Finish import: {count} episode(s) of {job['title']} S{job['season']:02d} from {job['pack']['name']}")
    return message
