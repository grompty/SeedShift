"""JSON API at /api. Mutating requests need Content-Type: application/json.
Errors look like {"error": {"code", "message"}}. Secrets are never returned."""

from flask import Blueprint, jsonify, request

import engine
import search

bp = Blueprint("api", __name__, url_prefix="/api")

PER_PAGE = (10, 25, 50, 100, 250)
# "need" = everything that isn't seeding on the target as one full torrent.
STATUS_FILTERS = {
    "need": {"not_seeding", "missing", "target_stopped", "partial", "singles"},
    "missing": {"missing"},
    "not_seeding": {"not_seeding"},
    "target_stopped": {"target_stopped"},
    "partial": {"partial", "singles"},
    "on_target": {"on_target"},
}


def error(code, message, status=400):
    return jsonify({"error": {"code": code, "message": message}}), status


@bp.before_request
def require_json():
    if request.method in ("POST", "PUT", "DELETE") and not request.is_json:
        return error("unsupported_media_type", "Send JSON with Content-Type: application/json.", 415)


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.errorhandler(ValueError)
def value_error(e):
    return error("invalid", str(e))


@bp.errorhandler(engine.ServiceError)
def service_error(e):
    return error("service", str(e), 502)


@bp.get("/overview")
def overview():
    return jsonify(engine.overview())


@bp.get("/scan")
def scan_status():
    return jsonify({"scan": engine.scan_state(), "scanned_at": (engine.last_scan() or {}).get("scanned_at")})


@bp.post("/scan")
def scan_start():
    if not engine.library_connections():
        return error("not_configured", "Add a Radarr or Sonarr connection first.", 409)
    if not engine.start_scan("manual"):
        return error("scan_running", "A scan is already running.", 409)
    return jsonify({"scan": engine.scan_state()}), 202


@bp.get("/items")
def items():
    kind = "season" if request.args.get("type") == "series" else "movie"
    q = (request.args.get("q") or "").strip().lower()
    connection = request.args.get("connection") or ""
    status = request.args.get("status") or "need"
    hide_airing = request.args.get("airing") != "show"
    sort = request.args.get("sort") or "size"
    try:
        per_page = int(request.args.get("per_page") or 25)
        page = max(1, int(request.args.get("page") or 1))
    except ValueError:
        per_page, page = 25, 1
    if per_page not in PER_PAGE:
        per_page = 25

    all_items = engine.evaluated_items(kind)
    connections = sorted({(i["connection_id"], i["connection_name"]) for i in all_items}, key=lambda c: c[1].lower())

    rows = all_items
    if connection:
        rows = [i for i in rows if i["connection_id"] == connection]
    if status == "ignored":
        rows = [i for i in rows if i["ignored"]]
    else:
        rows = [i for i in rows if not i["ignored"]]
        if status in STATUS_FILTERS:
            rows = [i for i in rows if i["status"] in STATUS_FILTERS[status]]
    if kind == "season" and hide_airing and status not in ("on_target", "ignored"):
        rows = [i for i in rows if not i["airing"]]
    if q:
        rows = [i for i in rows if q in i["title"].lower() or q in i["sort_title"]]

    if sort == "title":
        rows.sort(key=lambda i: (i["sort_title"], i.get("season") or 0))
    elif sort == "year":
        rows.sort(key=lambda i: (-(int(i["year"]) if str(i["year"]).isdigit() else 0), i["sort_title"]))
    else:
        rows.sort(key=lambda i: (-i["size"], i["sort_title"]))

    total = len(rows)
    pages = max(1, -(-total // per_page))
    page = min(page, pages)
    start = (page - 1) * per_page
    return jsonify({
        "items": rows[start:start + per_page],
        "total": total,
        "total_size": sum(i["size"] for i in rows),
        "page": page,
        "per_page": per_page,
        "filters": {"connections": [{"id": c[0], "name": c[1]} for c in connections]},
        "has_scan": engine.last_scan() is not None,
        "scan": engine.scan_state(),
        "targets": engine.target_hosts(),
    })


@bp.get("/items/<path:key>")
def item(key):
    details = engine.item_details(key)
    if not details:
        return error("not_found", "That title isn't in the last scan.", 404)
    return jsonify(details)


@bp.post("/ignore")
def ignore():
    data = body()
    key = str(data.get("key") or "")
    if not key:
        return error("invalid", "Missing key.")
    engine.set_ignored(key, bool(data.get("ignored", True)))
    return jsonify({"key": key, "ignored": bool(data.get("ignored", True))})


@bp.get("/settings")
def settings_get():
    return jsonify(engine.public_settings())


@bp.put("/settings")
def settings_put():
    return jsonify(engine.apply_settings_patch(body()))


@bp.post("/connections/test")
def test_connection():
    conn, version = engine.test_connection(body())
    return jsonify({"message": f"{conn['name']} connected (version {version}). Saved.",
                    "connection": engine.connection_public(conn)})


@bp.get("/trackers")
def trackers():
    """Tracker hosts from the last scan, to pick the target from."""
    return jsonify({"trackers": engine.overview()["trackers"], "targets": engine.target_hosts()})


@bp.get("/history")
def history():
    try:
        limit = max(1, min(500, int(request.args.get("limit") or 200)))
    except ValueError:
        limit = 200
    entries = engine.grab_history()
    return jsonify({"entries": entries[:limit], "total": len(entries)})


@bp.get("/indexers")
def indexers():
    """Indexers in the Arrs and Prowlarr, to choose the target indexer from."""
    return jsonify(search.list_indexers())


@bp.post("/search")
def search_start():
    key = str(body().get("key") or "")
    return jsonify({"search": search.start(key)}), 202


@bp.get("/search/<job_id>")
def search_get(job_id):
    try:
        return jsonify({"search": search.get(job_id)})
    except KeyError:
        return error("not_found", "This search has expired. Search again.", 404)


@bp.post("/grab")
def grab():
    data = body()
    index = data.get("index")
    message = search.grab(str(data.get("search_id") or ""), index if isinstance(index, int) else -1)
    return jsonify({"message": message})
