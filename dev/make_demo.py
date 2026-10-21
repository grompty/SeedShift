"""Demo library for README screenshots: invented titles, example tracker names, real hardlinks.

    python dev/make_demo.py /tmp/ss-demo
    python dev/mock_services.py /tmp/ss-demo/mock.json 9797

Files are sparse, so the "large" ones take no real disk space.
"""
import json
import os
import shutil
import sys

root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "/tmp/ss-demo")
shutil.rmtree(root, ignore_errors=True)
GB = 1024 ** 3
T, M, TV = root + "/torrents", root + "/media/movies", root + "/media/tv"
TARGET, OTHER, OLD = "tracker.example.org", "seeds.example.net", "old.example.com"
torrents, trackers, files = [], {}, {}
movies, moviefiles, series, episodefiles = [], {}, [], {}


def remote(p):
    return "/data" + p[len(root):]


def mkfile(path, size):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.truncate(size)


def link(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    os.link(src, dst)


def torrent(h, name, host, content, flist, state="stalledUP"):
    torrents.append({"hash": h, "name": name, "size": sum(s for _, s in flist), "state": state,
                     "tracker": f"https://{host}/announce/KEY" if host and state != "stoppedUP" else "",
                     "content_path": remote(content), "save_path": remote(T), "category": "radarr", "client": None})
    trackers[h] = [{"url": f"https://{host}/announce/KEY"}] if host else []
    files[h] = [{"name": n, "size": s, "priority": 1} for n, s in flist]


# (title, year, size GB, group, where): where = list of hosts seeding it, "" = no torrent, "stopped" = stopped on target
MOVIES = [
    ("The Quiet Harbor", 2019, 58.2, "FRAMESTOR", [OTHER]),
    ("Northbound", 2021, 31.4, "HiFi", [OTHER, OLD]),
    ("Paper Lanterns", 2017, 22.9, "DON", [TARGET]),
    ("Salt and Iron", 2020, 18.6, "CtrlHD", [OLD]),
    ("The Last Orchard", 2016, 14.2, "SPARKS", []),
    ("Glass Mountain", 2022, 12.8, "FLUX", ["stopped"]),
    ("Midnight Ferry", 2018, 11.7, "NTb", [OTHER]),
    ("Copper Sky", 2023, 9.4, "FLUX", [TARGET, OTHER]),
    ("Hollow Creek", 2015, 8.3, "EbP", [OTHER]),
    ("A Winter Fable", 2014, 7.1, "TayTO", [OLD]),
    ("Signal Lost", 2024, 6.2, "NTb", [TARGET]),
]
for i, (title, year, gb, group, where) in enumerate(MOVIES, 1):
    dot = title.replace(" ", ".")
    rel = f"{dot}.{year}.1080p.BluRay.x264-{group}"
    size = int(gb * GB) + i * 4093
    src = f"{T}/{rel}/{dot}.mkv"
    lib = f"{M}/{title} ({year})/{title} ({year}).mkv"
    if where:
        mkfile(src, size)
        link(src, lib)
        for j, host in enumerate(where):
            if host == "stopped":
                torrent(f"m{i}s", rel, TARGET, f"{T}/{rel}", [(f"{rel}/{dot}.mkv", size)], state="stoppedUP")
                torrent(f"m{i}o", rel, OTHER, f"{T}/{rel}", [(f"{rel}/{dot}.mkv", size)])
            else:
                torrent(f"m{i}{j}", rel, host, f"{T}/{rel}", [(f"{rel}/{dot}.mkv", size)])
    else:
        mkfile(lib, size)
    movies.append({"id": i, "title": title, "year": year, "titleSlug": f"{dot.lower()}-{year}", "imdbId": f"tt{9000000 + i}",
                   "tmdbId": 500 + i, "hasFile": True,
                   "movieFile": {"path": remote(lib), "size": size, "quality": {"quality": {"name": "Bluray-1080p"}},
                                 "sceneName": rel, "releaseGroup": group}})

# (show, seasons: [(number, episodes, total, airing, where)])
SHOWS = [
    ("Harbor Lights", 2018, [(1, 8, 8, False, "target"), (2, 8, 8, False, "other"), (3, 10, 10, False, "mixed"), (4, 3, 10, True, "other")]),
    ("Deep Field", 2020, [(1, 6, 6, False, "other"), (2, 6, 6, False, "none")]),
]
for sid, (show, year, seasons) in enumerate(SHOWS, 10):
    dot = show.replace(" ", ".")
    efiles, meta = [], []
    for number, eps, total, airing, where in seasons:
        pack = f"{dot}.S{number:02d}.1080p.WEB-DL-NTb"
        plist = []
        for e in range(1, eps + 1):
            size = int(1.4 * GB) + sid * 1000 + number * 100 + e
            src = f"{T}/{pack}/{dot}.S{number:02d}E{e:02d}.mkv"
            lib = f"{TV}/{show}/Season {number:02d}/{show} - S{number:02d}E{e:02d}.mkv"
            mkfile(src, size)
            link(src, lib)
            plist.append((f"{pack}/{dot}.S{number:02d}E{e:02d}.mkv", size))
            efiles.append({"seasonNumber": number, "path": remote(lib), "size": size, "releaseGroup": "NTb"})
        if where in ("target", "other", "mixed"):
            torrent(f"s{sid}{number}", pack, TARGET if where == "target" else OTHER, f"{T}/{pack}", plist)
        if where == "mixed":
            for k, (n, s) in enumerate(plist[:4]):
                single = f"{T}/singles/{os.path.basename(n)}"
                link(f"{T}/{n}", single)
                torrent(f"s{sid}{number}e{k}", os.path.basename(n), TARGET, single, [(os.path.basename(n), s)])
        meta.append({"seasonNumber": number, "statistics": {"episodeCount": eps if airing else total, "totalEpisodeCount": total,
                                                            "episodeFileCount": eps, **({"nextAiring": "2026-11-01T00:00:00Z"} if airing else {})}})
    series.append({"id": sid, "title": show, "year": year, "titleSlug": dot.lower(), "tvdbId": 70000 + sid, "imdbId": f"tt{8000000 + sid}",
                   "statistics": {"episodeFileCount": len(efiles)}, "seasons": meta})
    episodefiles[str(sid)] = efiles

with open(os.path.join(root, "mock.json"), "w") as f:
    json.dump({"torrents": torrents, "trackers": trackers, "files": files, "movies": movies,
               "moviefiles": moviefiles, "series": series, "episodefiles": episodefiles}, f, indent=1)
print(root)
