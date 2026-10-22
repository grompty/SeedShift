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


def torrent(h, name, host, content, flist, state="stalledUP", **extra):
    torrents.append({"hash": h, "name": name, "size": sum(s for _, s in flist), "state": state, "progress": 1,
                     "tracker": f"https://{host}/announce/KEY" if host and state != "stoppedUP" else "",
                     "content_path": remote(content), "save_path": remote(T), "category": "radarr", "client": None, **extra})
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
    ("Nordlys", 2021, 16.4, "NORDiC", [OTHER]),
    ("Fjellvind", 2019, 10.9, "NORDiC", []),
]
NORDIC = {"Nordlys", "Fjellvind"}
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
                   "tmdbId": 500 + i, "hasFile": True, "qualityProfileId": 2 if title in NORDIC else 1,
                   "movieFile": {"path": remote(lib), "size": size, "quality": {"quality": {"name": "Bluray-1080p"}},
                                 "sceneName": rel, "releaseGroup": group}})

# (show, seasons: [(number, episodes, total, airing, where)])
SHOWS = [
    ("Harbor Lights", 2018, [(1, 8, 8, False, "target"), (2, 8, 8, False, "other"), (3, 10, 10, False, "mixed"), (4, 3, 10, True, "other")]),
    ("Deep Field", 2020, [(1, 6, 6, False, "other"), (2, 6, 6, False, "unimported")]),
    ("Night Market", 2021, [(1, 10, 10, False, "packpartial")]),
]
QUALITY = {"WEBDL-1080p": ("web", 1080), "Bluray-1080p": ("bluray", 1080), "WEBRip-1080p": ("webRip", 1080)}


def quality(name):
    source, res = QUALITY[name]
    return {"quality": {"id": 3, "name": name, "source": source, "resolution": res}, "revision": {"version": 1, "real": 0}}


efid = [100]
episodes = {}
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
            plist.append((f"{pack}/{dot}.S{number:02d}E{e:02d}.mkv", size))
            q, group = "WEBDL-1080p", "NTb"
            if where == "packpartial" and e == 5:
                continue        # E05 is in the pack but missing from the library

            # "unimported": the pack is on disk, but the library holds other copies (never imported from it).
            # "packpartial": E01-E06 come from the pack; E07-E08 from single torrents elsewhere; E09-E10 a later Bluray.
            if where == "unimported" or (where == "packpartial" and e >= 7):
                lsize = size + 7_000_000 * e
                q, group = ("Bluray-1080p", "SPARKS") if e >= 9 else ("WEBRip-1080p", "FLUX")
                if where == "unimported":
                    q, group = "WEBRip-1080p", "FLUX"
                if where == "packpartial" and e in (7, 8):
                    single = f"{T}/singles/{dot}.S{number:02d}E{e:02d}.1080p.WEBRip-FLUX.mkv"
                    mkfile(single, lsize)
                    link(single, lib)
                    torrent(f"s{sid}{number}x{e}", os.path.basename(single), OTHER, single, [(os.path.basename(single), lsize)])
                else:
                    mkfile(lib, lsize)
                size = lsize
            else:
                link(src, lib)
            efid[0] += 1
            efiles.append({"id": efid[0], "seasonNumber": number, "path": remote(lib), "relativePath": os.path.relpath(lib, f"{TV}/{show}"),
                           "size": size, "releaseGroup": group, "quality": quality(q)})
        if where in ("target", "other", "mixed", "unimported", "packpartial"):
            torrent(f"s{sid}{number}", pack, OTHER if where in ("other", "mixed") else TARGET, f"{T}/{pack}", plist,
                    series_id=sid, category="tv-sonarr" if where != "unimported" else "cross-seed")
        if where == "mixed":
            for k, (n, s) in enumerate(plist[:4]):
                single = f"{T}/singles/{os.path.basename(n)}"
                link(f"{T}/{n}", single)
                torrent(f"s{sid}{number}e{k}", os.path.basename(n), TARGET, single, [(os.path.basename(n), s)])
        meta.append({"seasonNumber": number, "statistics": {"episodeCount": eps if airing else total, "totalEpisodeCount": total,
                                                            "episodeFileCount": eps, **({"nextAiring": "2026-11-01T00:00:00Z"} if airing else {})}})
    # Sonarr's episode list: every episode of each season, with its file when there is one.
    eplist = []
    for number, eps, total, airing, where in seasons:
        for e in range(1, total + 1):
            ef = next((x for x in efiles if x["seasonNumber"] == number and f"S{number:02d}E{e:02d}" in x["path"]), None)
            eplist.append({"id": sid * 10000 + number * 100 + e, "seasonNumber": number, "episodeNumber": e,
                           "episodeFileId": ef["id"] if ef else 0, "hasFile": bool(ef),
                           "airDateUtc": "2026-12-01T00:00:00Z" if airing and e > eps else f"{year}-01-{min(e, 28):02d}T00:00:00Z"})
    episodes[str(sid)] = eplist
    series.append({"id": sid, "title": show, "year": year, "titleSlug": dot.lower(), "tvdbId": 70000 + sid, "imdbId": f"tt{8000000 + sid}",
                   "qualityProfileId": 1,
                   "statistics": {"episodeFileCount": len(efiles)}, "seasons": meta})
    episodefiles[str(sid)] = efiles

with open(os.path.join(root, "mock.json"), "w") as f:
    json.dump({"torrents": torrents, "trackers": trackers, "files": files, "movies": movies,
               "moviefiles": moviefiles, "series": series, "episodefiles": episodefiles, "episodes": episodes}, f, indent=1)
print(root)
