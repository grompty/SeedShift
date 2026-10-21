# Seedshift

Shows which titles in Radarr and Sonarr aren't seeding on the tracker you want to consolidate on.

Current release: **v0.2.2**

> [!IMPORTANT]
> **This project is built by AI.** All of the code, the interface and this documentation were written by an AI model, through conversation with the maintainer. The maintainer decides what gets built, tests every release on a real server and publishes it, but doesn't write the code by hand. Read the code before you trust it with your setup, and report anything that looks wrong.

Seedshift reads one or more qBittorrent clients, Radarr and Sonarr, links every library file to the torrents that seed it, and lists the movies and seasons that have no torrent on your target tracker. From each title you can search the target and grab a release.

Scanning only reads. The one thing that changes anything is **Grab**, after a confirm: it asks Radarr or Sonarr to download the release, exactly as their own Grab button does. Seedshift never touches qBittorrent or your files itself.

---

## How it decides

- **Movies:** on target if any torrent seeding the movie file is on the target tracker.
- **Seasons:** on target only if **one** torrent on the target covers every episode file in the season (a season pack). Otherwise the season is:
  - **On target as singles:** every episode is on the target, but as separate torrents.
  - **Partly on target:** some episodes are on the target.
  - **Not on target:** seeding, but only elsewhere.
- **On target, but not seeding:** the target torrent exists but is stopped, errored or missing files.
- **Not seeding:** no torrent in qBittorrent seeds the file at all (usenet imports, removed torrents). Only torrents qBittorrent reports as seeding count; stopped and errored ones don't.
- **Airing** seasons (Sonarr has a next airing date) are hidden by default, since no pack exists yet. **Incomplete** seasons are flagged.

### Linking files to torrents

1. **Hardlink:** a library file and the torrent's file share an inode. This is exact and needs the data share mounted in the container.
2. **File size:** the exact byte size of the file matches a torrent file. This catches copies and works without the share mounted. Files under the minimum size (default 50 MB) are skipped.

Cross-seeds count automatically: every torrent pointing at the same files is seen.

### Trackers

A torrent's tracker is the host of its announce URL, such as `tracker.example.org`. Stopped torrents report no tracker in qBittorrent's list, so Seedshift asks for their tracker list instead. Passkeys are never stored or shown.

### Searching the target

The **Search** button on a title runs an interactive search limited to the target indexer and shows the results in a window. For shows it searches the whole season, so packs come first; single episodes are behind a checkbox.

Choose how under **Settings → Target tracker → Search with**:

| | Radarr / Sonarr | Prowlarr |
| --- | --- | --- |
| Who gets a search hit | Every indexer in the Arr (results are filtered afterwards) | Only the target |
| Quality, custom format score | The Arr's | The Arr's (each title is parsed by it) |
| Releases the Arr rejects | Shown with the reason; **Force grab** downloads them anyway | Pushed to the Arr, which refuses them |
| Download, category, tags | The Arr's | The Arr's |

**Results can differ between the two.** Searching through Radarr or Sonarr only finds what the indexer *as set up in that Arr* returns, and a few things can narrow that down: the indexer being temporarily disabled in the Arr after failures (Seedshift tells you when), interactive search turned off for the indexer, a sync profile or tags that keep the target out of that Arr, the Arr's category or minimum-seeder settings, or the Arr searching by an ID the tracker doesn't index. Prowlarr asks the tracker directly and falls back to a title search when an ID search finds nothing. If one finds nothing, try the other. Use Radarr/Sonarr mode when you need **Force grab**.

**Target indexer** tells Seedshift which indexer is the target tracker. If you don't pick one, it uses the indexer whose site address matches the target tracker.

**Not an upgrade:** to move seed size you often grab the same quality from the target. Radarr and Sonarr download it but won't replace an equal file on their own; it waits in **Activity → Queue**. Finish it there with **Manual Import**.

**Same size as your file** marks a release within 1% of what you have: almost certainly the exact same release. cross-seed can usually add that one without downloading anything.

---

## Docker Compose

```yaml
services:
  seedshift:
    image: ghcr.io/grompty/seedshift:latest
    container_name: seedshift
    networks:
      - media-network
    volumes:
      - /path/to/data:/data:ro
      - ./config:/config
    ports:
      - "8080:8080"
    restart: unless-stopped

networks:
  media-network:
    external: true
```

The image runs on amd64 and arm64. Use a version tag such as `ghcr.io/grompty/seedshift:0.2.2` instead of `latest` to stay on one release.

Mount the **same share** qBittorrent, Radarr and Sonarr use, at the **same path** they use. With the usual hardlink layout that's one share at `/data` holding both `torrents/` and `media/`. On Unraid:

```yaml
    volumes:
      - /mnt/user/data:/data:ro
      - /mnt/user/appdata/seedshift/config:/config
```

`:ro` is deliberate: Seedshift never writes to your media. Downloads go through Radarr and Sonarr.

To find the right `user:` on Synology or other hosts, run:

```bash
id
```

### Start and update

```bash
docker compose up -d
docker compose logs -f seedshift
```

To update to the newest release:

```bash
docker compose pull && docker compose up -d
```

To build from source instead, replace the `image:` line with `build: .` and run `docker compose up -d --build`.

Open `http://HOST:8080`.

---

## Setup

1. **Settings → Connections → Download clients:** add each qBittorrent you run, with its Web UI URL, username and password, then **Test and save**. Leave the username blank if qBittorrent bypasses auth for this network. Torrents from every client count.
2. **Settings → Connections → Libraries:** add each Radarr and Sonarr with its API key. Multiple instances are fine, such as an anime Sonarr. **Browser URL** is optional; set it if the base URL is a Docker name like `http://radarr:7878` that your browser can't open.
3. Optional: **Settings → Connections → Search:** add Prowlarr if you want searches to hit only the target.
4. Press **Scan now**.
5. Pick the target: **Make target** on the Overview, or **Settings → Target tracker**. Changing the target doesn't need a new scan. Check **Target indexer** on the same page.

### Path mappings

Only needed when an app sees the share at a different path than this container. Example: qBittorrent saves to `/downloads`, and that folder is `/data/torrents` here:

| Path in the app | Path in Seedshift |
| --- | --- |
| `/downloads` | `/data/torrents` |

The Overview warns when no library files are visible, and shows a path it looked for.

---

## Settings reference

| Setting | Default | Notes |
| --- | --- | --- |
| Target tracker | none | Announce host. Comma-separate several hosts of one site. Subdomains match. |
| Matching | Hardlink, then size | Or hardlink only, or size only. |
| Size match minimum | 50 MB | Smaller files only match by hardlink. |
| Automatic scan | 6 hours | Or manual only. |
| Include specials | off | Counts Sonarr season 0. |
| Target indexer | matches target | Which indexer the Search button keeps results from. |
| Search with | Radarr / Sonarr | Or Prowlarr, which only searches the target. |

Everything is stored in `/config`:

| File | Contents |
| --- | --- |
| `settings.json` | Settings, API keys and qBittorrent passwords (mode 600) |
| `scan.json` | The last scan |
| `tracker-cache.json` | Tracker hosts for stopped torrents |

There is no built-in login. Don't expose Seedshift to the internet.

---

## Releasing

Images are built by GitHub Actions (`.github/workflows/docker.yml`) and published to `ghcr.io/grompty/seedshift`:

- A tag such as `v0.2.1` publishes `0.2.1`, `0.2` and `latest`.
- A push to `main` publishes `edge`, for testing.

To release, update `APP_VERSION` in `engine.py` and the changelog, then:

```bash
git commit -am "v0.2.1" && git tag v0.2.1 && git push && git push --tags
```

## Development

```bash
python3 dev/make_fixtures.py /tmp/ss-data
python3 dev/mock_services.py /tmp/ss-data/mock.json 9797
```

This builds a fake share with real hardlinks and serves two mock qBittorrents (`/qbit` and `/qbit2`, user `admin`, password `secret`), Radarr (`/radarr`), Sonarr (`/sonarr`) and Prowlarr (`/prowlarr`) on port 9797, API key `testkey`. Grabs sent to the mocks are listed at `/_grabs`. Map `/data` to `/tmp/ss-data` in **Settings → Paths**.
