# Changelog

## v0.2.6

- Sidebar: the heading now reads **Target tracker** (or **Target trackers**), with no status next to it. Connection health has its own line above the services: **All connected**, **N failed** or **Not scanned yet**.
- README: the ratio warning is also shown under Usage, next to the first mention of Search.

## v0.2.5

- New color scheme, Dusk: violet accent on cool gray, so Seedshift no longer looks identical to Trailarr Parrk. The icon follows it.
- Ratio warning: every Grab confirm notes that downloading counts against your ratio on the target unless it's freeleech, and the README explains why to grab a few titles at a time.

## v0.2.4

- **History page:** every grab made through Seedshift, with its result. Grabbed titles get a **Grabbed** tag on Titles.
- README screenshots, made from a demo library with made-up titles.
- **Replace my file after a grab** (off by default, with a warning and a confirm): Seedshift follows each grab in Radarr/Sonarr's queue, and when it's blocked as "not an upgrade" it has the Arr run a manual import over your current file. Other blocks are left alone and shown on History.

- New icon: two database stacks with arrows circling between them, in the sidebar and as the browser tab icon.
- The sidebar shows the version next to the name, and the subtitle now reads "Focus your seed size".
- Fixed a horizontal scrollbar at the bottom of the sidebar, caused by the collapse button.
- Search no longer calls a release "the one you already have" from size alone. **Possible match** now also needs the same release group as your file. Run a new scan to get the group information.

## v0.2.3

- New README, plus CONTRIBUTING.md (building from source, development, releasing) and an MIT license.
- The example compose file uses port 8095, since 8080 is qBittorrent's default, and the Docker network is now optional.
- **Search with** lists Radarr / Sonarr first again, the default.

## v0.2.2

- Fixed the sidebar service tooltips being cut off at the sidebar's edge.

## v0.2.1

- Removed the site search URL settings and the **Site** button.
- When a Radarr/Sonarr search finds nothing on the target because the Arr has temporarily disabled that indexer after failures, the search window says so and until when.

## v0.2.0

- **Search the target from each title.** A Search button opens a window with interactive search results from the target indexer only. Seasons show packs first.
- **Grab, with a confirm.** Radarr or Sonarr does the download, so your quality profile, category and tags apply. Releases the Arr would reject show the reason and a **Force grab** button.
- **Search with Radarr/Sonarr or Prowlarr** (Settings → Target tracker). Prowlarr only hits the target; Radarr/Sonarr hits every indexer but can force grab.
- **Target indexer** setting, picked automatically when an indexer's site matches the target tracker.
- **Multiple qBittorrent clients.** Settings → Connections now has Download clients, Libraries and Search groups. A file seeded from any client counts.
- Your existing qBittorrent settings move into the new list automatically.
- The tracker site link is now a smaller **Site** button next to Search.
- README: states up front that the project is built by AI, and notes that search results can differ between Radarr/Sonarr and Prowlarr.

## v0.1.3

- Stopped, errored, "missing files" and still-downloading torrents no longer count as seeding. A title whose only target torrent is stopped shows as **On target, but not seeding**, and those trackers appear crossed out in the list.
- Seeding by tracker counts seeding torrents only, with stopped ones noted separately.
- "Incomplete season" now compares against aired episodes, so announced episodes that haven't aired don't flag a season.
- The Open in Radarr/Sonarr button is hidden when the only address is a Docker name like `http://radarr:7878`. Set **Browser URL** on the connection to get it back.

## v0.1.2

- qBittorrent moved into Settings → Connections, above Radarr and Sonarr. Old `?section=qbittorrent` links still work.
- Adding a Radarr or Sonarr that's already connected (same type and URL) updates it instead of creating a duplicate.

## v0.1.1

- Fixed qBittorrent login failing with correct credentials on versions that don't reply `Ok.`. Seedshift now checks that the session works instead of reading the reply.
- Login errors now say what qBittorrent answered.

## v0.1.0

First release.

- Lists every Radarr movie and Sonarr season that isn't seeding on your target tracker.
- Reads qBittorrent, Radarr and Sonarr through their APIs. Read-only: nothing is paused, removed, grabbed or changed.
- Links library files to torrents by hardlink (same inode), with exact file size as the fallback.
- Seasons are judged as packs: one torrent on the target must cover every episode file, otherwise the season shows as partly on target, on target as singles, or not on target.
- Flags airing and incomplete seasons. Airing seasons are hidden by default.
- Seeding-by-tracker overview with one-click "Make target".
- Optional search links for the target tracker, with `{query}`, `{title}`, `{year}`, `{imdb}`, `{tmdb}`, `{tvdb}` and `{season}`.
- Ignore titles the target doesn't have.
- Path mappings for setups where the apps mount the share at different paths.
- Automatic scans (default every 6 hours) or manual only.
- Interface built on the Trailarr Parrk v0.8.0 design system.
