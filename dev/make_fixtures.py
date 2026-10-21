"""Builds a fake data share with hardlinks plus the JSON the mock services serve.

    python dev/make_fixtures.py /tmp/ss-data

The share is laid out like a TRaSH-style /data mount: torrents/ and media/ on one filesystem.
Files are sparse, so they take no real disk space."""
import json
import os
import shutil
import sys

root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "/tmp/ss-data")
shutil.rmtree(root, ignore_errors=True)
MB = 1024 * 1024
size_counter = [70 * MB]


def mkfile(path, size=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    size = size or size_counter[0]
    size_counter[0] += 1234567
    with open(path, "wb") as f:
        f.truncate(size)
    return size


def link(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    os.link(src, dst)


def remote(p):        # how qBittorrent/Radarr/Sonarr see the share
    return "/data" + p[len(root):]


T = root + "/torrents"
M = root + "/media/movies"
TV = root + "/media/tv"
torrents, trackers, files = [], {}, {}


def torrent(h, name, host, content, save, file_list, tracker_field=True, state="stalledUP", client=None):
    torrents.append({"hash": h, "name": name, "size": sum(s for _, s in file_list), "state": state, "client": client,
                     "tracker": f"https://{host}/announce/PASSKEY" if host and tracker_field else "",
                     "content_path": remote(content), "save_path": remote(save), "category": "radarr"})
    trackers[h] = [{"url": "** [DHT] **"}, {"url": f"https://{host}/announce/PASSKEY"}] if host else [{"url": "** [DHT] **"}]
    files[h] = [{"name": n, "size": s, "priority": 1} for n, s in file_list]


# Movie A: stopped on the target, seeding on another tracker (same inode).
sa = mkfile(f"{T}/Alpha.2019.1080p-GRP/alpha.mkv")
link(f"{T}/Alpha.2019.1080p-GRP/alpha.mkv", f"{M}/Alpha (2019)/Alpha (2019).mkv")
torrent("a1", "Alpha.2019.1080p-GRP", "tracker.target.org", f"{T}/Alpha.2019.1080p-GRP", T, [("Alpha.2019.1080p-GRP/alpha.mkv", sa)], state="stoppedUP")
torrent("a2", "Alpha.2019.1080p-GRP", "t.other.net", f"{T}/Alpha.2019.1080p-GRP", T, [("Alpha.2019.1080p-GRP/alpha.mkv", sa)])

# Movie B: only on another tracker, single-file torrent, stopped (empty tracker field).
sb = mkfile(f"{T}/Bravo.2020.2160p.mkv")
link(f"{T}/Bravo.2020.2160p.mkv", f"{M}/Bravo (2020)/Bravo (2020).mkv")
# It lives in the second qBittorrent (/qbit2).
torrent("b1", "Bravo.2020.2160p.mkv", "t.other.net", f"{T}/Bravo.2020.2160p.mkv", T, [("Bravo.2020.2160p.mkv", sb)], tracker_field=False, client="2")

# Movie C: in the library, no torrent at all.
mkfile(f"{M}/Charlie (2021)/Charlie (2021).mkv")

# Movie D: copied, not hardlinked; same size torrent on the target -> size match.
sd = mkfile(f"{T}/Delta.2018.720p/delta.mkv")
mkfile(f"{M}/Delta (2018)/Delta (2018).mkv", sd)
torrent("d1", "Delta.2018.720p", "tracker.target.org", f"{T}/Delta.2018.720p", T, [("Delta.2018.720p/delta.mkv", sd)])

# Show S1: full pack on target.
s1 = []
for e in (1, 2, 3):
    size = mkfile(f"{T}/Show.S01.1080p/Show.S01E0{e}.mkv")
    link(f"{T}/Show.S01.1080p/Show.S01E0{e}.mkv", f"{TV}/Show/Season 01/Show - S01E0{e}.mkv")
    s1.append((f"Show.S01.1080p/Show.S01E0{e}.mkv", size))
torrent("s1", "Show.S01.1080p", "tracker.target.org", f"{T}/Show.S01.1080p", T, s1)

# Show S2: pack on other tracker, one episode also as a single on the target.
s2 = []
for e in (1, 2, 3):
    size = mkfile(f"{T}/Show.S02.1080p/Show.S02E0{e}.mkv")
    link(f"{T}/Show.S02.1080p/Show.S02E0{e}.mkv", f"{TV}/Show/Season 02/Show - S02E0{e}.mkv")
    s2.append((f"Show.S02.1080p/Show.S02E0{e}.mkv", size))
torrent("s2", "Show.S02.1080p", "t.other.net", f"{T}/Show.S02.1080p", T, s2)
link(f"{T}/Show.S02.1080p/Show.S02E01.mkv", f"{T}/single/Show.S02E01.mkv")
torrent("s2e1", "Show.S02E01.mkv", "tracker.target.org", f"{T}/single/Show.S02E01.mkv", f"{T}/single", [("Show.S02E01.mkv", s2[0][1])])

# Show S3: airing, 2 of 3 episodes, singles on other tracker.
for e in (1, 2):
    size = mkfile(f"{T}/Show.S03E0{e}.mkv")
    link(f"{T}/Show.S03E0{e}.mkv", f"{TV}/Show/Season 03/Show - S03E0{e}.mkv")
    torrent(f"s3e{e}", f"Show.S03E0{e}.mkv", "t.other.net", f"{T}/Show.S03E0{e}.mkv", T, [(f"Show.S03E0{e}.mkv", size)])

# An orphan torrent with no library title.
so = mkfile(f"{T}/Orphan.2010/orphan.mkv")
torrent("o1", "Orphan.2010", "old.tracker.io", f"{T}/Orphan.2010", T, [("Orphan.2010/orphan.mkv", so)])


def mf(path):
    return {"path": remote(path), "size": os.path.getsize(path), "quality": {"quality": {"name": "Bluray-1080p"}}, "sceneName": ""}


movies = [
    {"id": 1, "title": "Alpha", "year": 2019, "titleSlug": "alpha-2019", "imdbId": "tt001", "tmdbId": 11, "hasFile": True, "movieFile": mf(f"{M}/Alpha (2019)/Alpha (2019).mkv")},
    {"id": 2, "title": "Bravo", "year": 2020, "titleSlug": "bravo-2020", "imdbId": "tt002", "tmdbId": 12, "hasFile": True},   # no movieFile -> moviefile endpoint
    {"id": 3, "title": "Charlie", "year": 2021, "titleSlug": "charlie-2021", "hasFile": True, "movieFile": mf(f"{M}/Charlie (2021)/Charlie (2021).mkv")},
    {"id": 4, "title": "Delta", "year": 2018, "titleSlug": "delta-2018", "hasFile": True, "movieFile": mf(f"{M}/Delta (2018)/Delta (2018).mkv")},
    {"id": 5, "title": "Echo", "year": 2022, "titleSlug": "echo-2022", "hasFile": False},
]
moviefiles = {"2": [mf(f"{M}/Bravo (2020)/Bravo (2020).mkv")]}
series = [{"id": 10, "title": "Show", "year": 2015, "titleSlug": "show", "tvdbId": 999, "imdbId": "tt010",
           "statistics": {"episodeFileCount": 8},
           "seasons": [
               {"seasonNumber": 1, "statistics": {"episodeCount": 3, "totalEpisodeCount": 4, "episodeFileCount": 3}},
               {"seasonNumber": 2, "statistics": {"episodeCount": 3, "totalEpisodeCount": 3, "episodeFileCount": 3}},
               {"seasonNumber": 3, "statistics": {"episodeCount": 2, "totalEpisodeCount": 3, "episodeFileCount": 2, "nextAiring": "2026-11-01T00:00:00Z"}}]}]
episodefiles = {"10": [{"seasonNumber": int(p.split("Season 0")[1][0]), "path": remote(os.path.join(dp, f)), "size": os.path.getsize(os.path.join(dp, f))}
                       for dp, _, fs in os.walk(f"{TV}/Show") for f in fs for p in [dp]]}

with open(os.path.join(root, "mock.json"), "w") as f:
    json.dump({"torrents": torrents, "trackers": trackers, "files": files, "movies": movies,
               "moviefiles": moviefiles, "series": series, "episodefiles": episodefiles}, f, indent=1)
print(root)
