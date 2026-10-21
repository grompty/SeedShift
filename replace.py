"""Automatic replace (Settings → Target tracker → Replace my file after a grab).

For every grab made while the setting is on, follow it in Radarr/Sonarr's download queue:
- the Arr imports it by itself (it was an upgrade)   -> "imported"
- the Arr blocks it as "not an upgrade"              -> run a manual import through the Arr -> "replaced"
- the Arr blocks it for any other reason             -> "blocked", left for a human
Everything goes through the Arr's API. Seedshift never touches files.
"""

import re
import threading
import time
import datetime as dt

import engine
from engine import ServiceError, arr_get, arr_request, get_connection, log

INTERVAL = 60                      # seconds between checks
GIVE_UP_AFTER = 7 * 24 * 3600      # stop following a grab after a week
NOT_SEEN_LIMIT = 2 * 3600          # never showed up in the queue after this long -> lost
ACTIVE = ("waiting", "downloading", "importing")

# Block reasons that mean "the Arr just doesn't consider it better". Only these get replaced.
UPGRADE_BLOCK = re.compile(r"upgrade|equal or higher preference|not a custom format", re.I)


def _age(entry):
    try:
        return time.time() - dt.datetime.fromisoformat(entry["ts"]).timestamp()
    except (KeyError, ValueError):
        return 0


def _set(entry, state, message, **extra):
    replace = {**(entry.get("replace") or {}), "state": state, "message": message, "updated": engine.utc_now(), **extra}
    entry["replace"] = replace
    engine.update_grab(entry["id"], replace=replace)


def _queue(conn):
    unknown = "includeUnknownMovieItems" if conn["type"] == "radarr" else "includeUnknownSeriesItems"
    data = arr_get(conn, f"/api/v3/queue?page=1&pageSize=500&{unknown}=true") or {}
    return data.get("records", []) if isinstance(data, dict) else data


def _messages(record):
    out = []
    for sm in record.get("statusMessages") or []:
        out += [str(m) for m in sm.get("messages") or []] or ([str(sm.get("title"))] if sm.get("title") else [])
    return out


def _manual_import(conn, entry, download_id):
    """Ask the Arr to import the download's files, replacing the current ones. Returns the command id."""
    items = arr_get(conn, f"/api/v3/manualimport?downloadId={download_id}&filterExistingFiles=false") or []
    files = []
    for it in items:
        reasons = " ".join(str(r.get("reason") if isinstance(r, dict) else r) for r in it.get("rejections") or [])
        if re.search(r"sample", reasons, re.I):
            continue
        base = {"path": it.get("path"), "quality": it.get("quality"), "languages": it.get("languages") or [],
                "releaseGroup": it.get("releaseGroup") or "", "downloadId": download_id,
                "indexerFlags": it.get("indexerFlags") or 0}
        if conn["type"] == "radarr":
            movie_id = (it.get("movie") or {}).get("id")
            if movie_id:
                files.append({**base, "movieId": movie_id})
        else:
            series_id = (it.get("series") or {}).get("id")
            episode_ids = [e.get("id") for e in it.get("episodes") or [] if e.get("id")]
            if series_id and episode_ids:
                files.append({**base, "seriesId": series_id, "episodeIds": episode_ids,
                              **({"releaseType": it["releaseType"]} if it.get("releaseType") else {})})
    if not files:
        raise ServiceError(f"{engine.TYPE_NAMES[conn['type']]} found no files it could match in this download.")
    reply = arr_request(conn, "POST", "/api/v3/command", {"name": "ManualImport", "files": files, "importMode": "auto"}, timeout=60)
    return (reply or {}).get("id"), len(files)


def _check(entry, queues):
    rep = entry.get("replace") or {}
    conn = get_connection(entry.get("connection_id", ""))
    arr = engine.TYPE_NAMES.get((conn or {}).get("type"), "Radarr/Sonarr")
    if not conn:
        return _set(entry, "failed", "That Radarr/Sonarr connection no longer exists.")
    if _age(entry) > GIVE_UP_AFTER:
        return _set(entry, "lost", "Stopped following it after a week.")

    if rep.get("state") == "importing" and rep.get("command_id"):
        cmd = arr_get(conn, f"/api/v3/command/{rep['command_id']}") or {}
        status = str(cmd.get("status") or "").lower()
        if status == "completed":
            return _set(entry, "replaced", f"{arr} replaced your file with it.")
        if status in ("failed", "aborted", "cancelled"):
            return _set(entry, "failed", f"{arr}'s import failed: {cmd.get('message') or cmd.get('exception') or status}.")
        return

    if conn["id"] not in queues:
        queues[conn["id"]] = _queue(conn)
    records = queues[conn["id"]]
    did = rep.get("download_id")
    record = next((r for r in records if did and r.get("downloadId") == did), None) or \
        next((r for r in records if str(r.get("title", "")).lower() == entry["release"].lower()), None)

    if not record:
        if did:
            history = arr_get(conn, f"/api/v3/history?page=1&pageSize=50&downloadId={did}") or {}
            events = [str(h.get("eventType", "")) for h in (history.get("records", []) if isinstance(history, dict) else history)]
            if any(e in ("downloadFolderImported", "episodeFileImported", "movieFileImported") for e in events):
                return _set(entry, "imported", f"{arr} imported it by itself, since it was an upgrade.")
            if any(e == "downloadFailed" for e in events):
                return _set(entry, "failed", "The download failed.")
            return _set(entry, "lost", f"It left {arr}'s queue without being imported. It may have been removed.")
        if _age(entry) > NOT_SEEN_LIMIT:
            return _set(entry, "lost", f"It never showed up in {arr}'s queue.")
        return

    did = record.get("downloadId") or did
    state = str(record.get("trackedDownloadState") or "")
    if state in ("importBlocked", "importPending") and str(record.get("trackedDownloadStatus") or "").lower() == "warning":
        messages = _messages(record)
        if messages and all(not UPGRADE_BLOCK.search(m) for m in messages):
            return _set(entry, "blocked", f"{arr} blocked the import: " + "; ".join(messages), download_id=did)
        try:
            command_id, count = _manual_import(conn, entry, did)
        except ServiceError as e:
            return _set(entry, "failed", str(e), download_id=did)
        log.info(f"Replace: manual import of {entry['release']} via {conn['name']} ({count} file(s))")
        return _set(entry, "importing", f"{arr} is importing it over your current file.", download_id=did, command_id=command_id)

    size, left = record.get("size") or 0, record.get("sizeleft") or 0
    pct = f" {round((size - left) / size * 100)}%" if size and state == "downloading" else ""
    _set(entry, "downloading", f"Downloading{pct}." if state == "downloading" else f"In {arr}'s queue ({state or 'waiting'}).", download_id=did)


def tick():
    queues = {}
    for entry in engine.grab_history():
        if (entry.get("replace") or {}).get("state") not in ACTIVE:
            continue
        try:
            _check(entry, queues)
        except ServiceError as e:
            # Arr unreachable for a moment: keep the state, note why, try again next time.
            engine.update_grab(entry["id"], replace={**entry["replace"], "note": str(e), "updated": engine.utc_now()})
        except Exception:
            log.exception("Replace check failed")


def watcher():
    while True:
        try:
            tick()
        except Exception:
            log.exception("Replace watcher")
        time.sleep(INTERVAL)


_started = [False]


def start():
    if not _started[0]:
        _started[0] = True
        threading.Thread(target=watcher, name="replace", daemon=True).start()
