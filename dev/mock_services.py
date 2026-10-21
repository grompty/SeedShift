"""One Flask app pretending to be two qBittorrents (/qbit, /qbit2), Radarr (/radarr), Sonarr (/sonarr)
and Prowlarr (/prowlarr). Grabs and pushes are recorded and listed at /_grabs.

    python dev/mock_services.py /tmp/ss-data/mock.json 9797
"""
import json
import os
import sys

from flask import Flask, abort, jsonify, request

data = json.load(open(sys.argv[1]))
app = Flask(__name__)
SID = "mock-session"


def arr_auth():
    if request.headers.get("X-Api-Key") != "testkey":
        abort(401)


GRABS = []


def client_torrents(qb):
    want = "2" if qb == "qbit2" else None
    return [t for t in data["torrents"] if t.get("client") == want]


@app.post("/<qb>/api/v2/auth/login")
def login(qb):
    if request.form.get("username") == "admin" and request.form.get("password") == "secret":
        r = app.make_response(os.environ.get("MOCK_LOGIN_REPLY", "Ok."))
        r.set_cookie("SID", SID)
        return r
    return "Fails."


def qauth():
    if request.cookies.get("SID") != SID:
        abort(403)


@app.get("/<qb>/api/v2/app/version")
def version(qb):
    qauth(); return "v5.0.0"


@app.get("/<qb>/api/v2/torrents/info")
def info(qb):
    qauth()
    t = client_torrents(qb)
    return jsonify(t[: int(request.args["limit"])] if "limit" in request.args else t)


@app.get("/<qb>/api/v2/torrents/trackers")
def trackers(qb):
    qauth(); return jsonify(data["trackers"].get(request.args["hash"], []))


@app.get("/<qb>/api/v2/torrents/files")
def files(qb):
    qauth(); return jsonify(data["files"].get(request.args["hash"], []))


@app.get("/radarr/api/v3/system/status")
def rstatus():
    arr_auth(); return jsonify({"appName": "Radarr", "version": "5.9.0"})


@app.get("/radarr/api/v3/movie")
def movies():
    arr_auth(); return jsonify(data["movies"])


@app.get("/radarr/api/v3/moviefile")
def moviefile():
    arr_auth(); return jsonify(data["moviefiles"].get(request.args["movieId"], []))


@app.get("/sonarr/api/v3/system/status")
def sstatus():
    arr_auth(); return jsonify({"appName": "Sonarr", "version": "4.0.9"})


@app.get("/sonarr/api/v3/series")
def series():
    arr_auth(); return jsonify(data["series"])


@app.get("/sonarr/api/v3/episodefile")
def episodefile():
    arr_auth(); return jsonify(data["episodefiles"].get(request.args["seriesId"], []))


# ── Indexers, interactive search, grab, push, parse ──────────────────────

ARR_INDEXERS = [
    {"id": 1, "name": "TargetTracker (Prowlarr)", "protocol": "torrent", "fields": [{"name": "baseUrl", "value": "http://prowlarr:9696/1/"}]},
    {"id": 2, "name": "OtherNet (Prowlarr)", "protocol": "torrent", "fields": [{"name": "baseUrl", "value": "http://prowlarr:9696/2/"}]},
    {"id": 3, "name": "SomeUsenet", "protocol": "usenet", "fields": []},
]
PROWLARR_INDEXERS = [
    {"id": 1, "name": "TargetTracker", "protocol": "torrent", "indexerUrls": ["https://www.target.org/"]},
    {"id": 2, "name": "OtherNet", "protocol": "torrent", "indexerUrls": ["https://other.net/"]},
]


def movie_size(movie_id):
    for m in data["movies"]:
        if m["id"] == movie_id:
            f = m.get("movieFile") or (data["moviefiles"].get(str(movie_id)) or [{}])[0]
            return f.get("size", 0), m["title"], m["year"]
    return 0, "Unknown", 2000


def releases_for_movie(movie_id):
    size, title, year = movie_size(movie_id)
    t = title.replace(" ", ".")
    return [
        {"guid": f"g{movie_id}-1", "indexerId": 1, "indexer": "TargetTracker (Prowlarr)", "title": f"{t}.{year}.2160p.UHD.BluRay.REMUX-GRP",
         "size": size + 4096, "seeders": 42, "leechers": 1, "ageHours": 17000, "protocol": "torrent", "quality": {"quality": {"name": "Remux-2160p"}},
         "customFormatScore": 150, "rejected": False, "rejections": [], "infoUrl": "https://www.target.org/t/1"},
        {"guid": f"g{movie_id}-2", "indexerId": 1, "indexer": "TargetTracker (Prowlarr)", "title": f"{t}.{year}.1080p.BluRay.x264-GRP2",
         "size": 10_400_000_000, "seeders": 9, "leechers": 0, "ageHours": 35000, "protocol": "torrent", "quality": {"quality": {"name": "Bluray-1080p"}},
         "customFormatScore": 0, "rejected": True, "rejections": ["Existing file on disk is of equal or higher preference: Remux-2160p", "Not an upgrade"]},
        {"guid": f"g{movie_id}-3", "indexerId": 2, "indexer": "OtherNet (Prowlarr)", "title": f"{t}.{year}.2160p.WEB-DL-OTHER",
         "size": 17_900_000_000, "seeders": 118, "leechers": 3, "ageHours": 2000, "protocol": "torrent", "quality": {"quality": {"name": "WEBDL-2160p"}},
         "customFormatScore": 40, "rejected": False, "rejections": []},
        {"guid": f"g{movie_id}-4", "indexerId": 3, "indexer": "SomeUsenet", "title": f"{t}.{year}.NZB", "size": 1, "protocol": "usenet",
         "quality": {"quality": {"name": "Unknown"}}, "rejected": False, "rejections": []},
    ]


def releases_for_season(series_id, season):
    return [
        {"guid": f"s{series_id}-{season}-1", "indexerId": 1, "indexer": "TargetTracker (Prowlarr)", "title": f"Show.S{season:02d}.1080p.WEB-DL-GRP",
         "size": 9_000_000_000, "seeders": 12, "ageHours": 900, "protocol": "torrent", "quality": {"quality": {"name": "WEBDL-1080p"}},
         "customFormatScore": 20, "rejected": False, "rejections": [], "fullSeason": True},
        {"guid": f"s{series_id}-{season}-2", "indexerId": 1, "indexer": "TargetTracker (Prowlarr)", "title": f"Show.S{season:02d}E01.1080p.WEB-DL-GRP",
         "size": 3_000_000_000, "seeders": 5, "ageHours": 900, "protocol": "torrent", "quality": {"quality": {"name": "WEBDL-1080p"}},
         "customFormatScore": 20, "rejected": False, "rejections": [], "fullSeason": False},
    ]


@app.get("/<arr>/api/v3/indexer")
def arr_indexers(arr):
    arr_auth(); return jsonify(ARR_INDEXERS)


@app.get("/radarr/api/v3/release")
def radarr_release():
    arr_auth()
    rel = releases_for_movie(int(request.args["movieId"]))
    if os.environ.get("MOCK_BACKOFF"):      # the Arr skips an indexer in failure backoff
        rel = [r for r in rel if r["indexerId"] != 1]
    return jsonify(rel)


@app.get("/sonarr/api/v3/release")
def sonarr_release():
    arr_auth(); return jsonify(releases_for_season(int(request.args["seriesId"]), int(request.args["seasonNumber"])))


@app.post("/<arr>/api/v3/release")
def arr_grab(arr):
    arr_auth()
    body = request.get_json()
    GRABS.append({"arr": arr, "kind": "grab", **body})
    return jsonify({"guid": body.get("guid")})


@app.post("/<arr>/api/v3/release/push")
def arr_push(arr):
    arr_auth()
    body = request.get_json()
    GRABS.append({"arr": arr, "kind": "push", **body})
    if "1080p.BluRay" in (body.get("title") or ""):
        return jsonify([{"title": body["title"], "rejected": True, "rejections": [{"reason": "Not an upgrade"}]}])
    return jsonify([{"title": body["title"], "rejected": False, "rejections": []}])


@app.get("/<arr>/api/v3/parse")
def arr_parse(arr):
    arr_auth()
    title = request.args.get("title", "")
    q = "Remux-2160p" if "REMUX" in title else "Bluray-1080p" if "BluRay" in title else "WEBDL-1080p"
    if arr == "radarr":
        return jsonify({"parsedMovieInfo": {"quality": {"quality": {"name": q}}}, "movie": None, "customFormatScore": 99 if "REMUX" in title else 5})
    season = int(title.split(".S")[1][:2]) if ".S" in title else None
    return jsonify({"parsedEpisodeInfo": {"quality": {"quality": {"name": q}}, "seasonNumber": season, "fullSeason": "E0" not in title},
                    "series": {"id": 10}, "customFormatScore": 10})


@app.get("/prowlarr/api/v1/system/status")
def pstatus():
    arr_auth(); return jsonify({"appName": "Prowlarr", "version": "1.24.0"})


@app.get("/prowlarr/api/v1/indexer")
def pindexers():
    arr_auth(); return jsonify(PROWLARR_INDEXERS)


@app.get("/prowlarr/api/v1/search")
def psearch():
    arr_auth()
    ids = [int(i) for i in request.args.getlist("indexerIds")]
    query = request.args.get("query", "")
    out = []
    if 1 in ids:
        if "{ImdbId:" in query or ("{" not in query and "S0" not in query):
            out = [{"title": "Bravo.2020.2160p.UHD.BluRay.REMUX-GRP", "size": 58_000_000_000, "indexerId": 1, "indexer": "TargetTracker",
                    "seeders": 42, "ageHours": 17000, "guid": "p1", "downloadUrl": "http://127.0.0.1:9797/prowlarr/1/download?x=1", "protocol": "torrent",
                    "publishDate": "2024-01-01T00:00:00Z"},
                   {"title": "Bravo.2020.1080p.BluRay.x264-GRP2", "size": 10_400_000_000, "indexerId": 1, "indexer": "TargetTracker",
                    "seeders": 9, "ageHours": 35000, "guid": "p2", "downloadUrl": "http://127.0.0.1:9797/prowlarr/1/download?x=2", "protocol": "torrent",
                    "publishDate": "2023-01-01T00:00:00Z"}]
        elif "{TvdbId:" in query or "S0" in query:
            out = [{"title": "Show.S02.1080p.WEB-DL-GRP", "size": 9_000_000_000, "indexerId": 1, "indexer": "TargetTracker", "seeders": 12,
                    "ageHours": 900, "guid": "p3", "downloadUrl": "http://127.0.0.1:9797/prowlarr/1/download?x=3", "protocol": "torrent", "publishDate": "2026-01-01T00:00:00Z"},
                   {"title": "Show.S05.1080p.WEB-DL-GRP", "size": 9_000_000_000, "indexerId": 1, "indexer": "TargetTracker", "seeders": 12,
                    "ageHours": 900, "guid": "p4", "downloadUrl": "http://127.0.0.1:9797/prowlarr/1/download?x=4", "protocol": "torrent", "publishDate": "2026-01-01T00:00:00Z"}]
    return jsonify(out)


@app.get("/<arr>/api/v3/downloadclient")
def arr_clients(arr):
    arr_auth()
    return jsonify([{"id": 1, "enable": True, "protocol": "torrent", "implementation": "QBittorrent", "priority": 1,
                     "fields": [{"name": "host", "value": "127.0.0.1"}, {"name": "port", "value": 9797},
                                {"name": "movieCategory", "value": "radarr"}, {"name": "tvCategory", "value": "tv-sonarr"},
                                {"name": "initialState", "value": 0}, {"name": "contentLayout", "value": 0}]}])


@app.get("/<arr>/api/v3/indexerstatus")
def arr_indexer_status(arr):
    arr_auth()
    return jsonify([{"indexerId": 1, "disabledTill": "2026-10-21T22:30:00Z"}] if os.environ.get("MOCK_BACKOFF") else [])


@app.get("/prowlarr/1/download")
def pdownload():
    if request.args.get("x") == "magnet":
        return "", 302, {"Location": "magnet:?xt=urn:btih:abc"}
    return b"d8:announce3:xyz4:infod4:name4:testee", 200, {"Content-Type": "application/x-bittorrent"}


@app.get("/_grabs")
def grabs():
    return jsonify(GRABS)


if __name__ == "__main__":
    app.run(port=int(sys.argv[2]) if len(sys.argv) > 2 else 9797)
