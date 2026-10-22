# Changelog

## v0.3.3

- Fixed: Finish import showed your library files instead of the pack's. Seedshift asked Sonarr about the pack's folder together with the series, and Sonarr then ignores the folder and returns the series' existing files. It now asks about the folder alone, keeps only files inside the pack's folder that Sonarr matches to the series, and never offers a library file.

## v0.3.2

- Finish import shows Sonarr's custom format score when your current file scores higher ("Lower score: 810 vs your 1410"). Those episodes are unticked by default, like other better files.
- Finish import reads the pack's folder first: the same path in qBittorrent and Sonarr, so Sonarr sees every file in the pack. Before, it asked by download ID first, which can return only part of a pack when Sonarr ties that download to an earlier grab. The download ID is now only a fallback.
- Finish import shows the folder Sonarr read, and lists every file it skipped with the reason (couldn't tell the episode, other season, sample, your own library file).

## v0.3.1

- **Screenshot mode**, in the sidebar: titles, trackers, indexers, paths and addresses are swapped for made-up names, so screenshots can be shared as they are. Settings can't be saved while it's on.
- Finish import shows the file names: your current file and the pack's file for each episode.
- Finish import ticks episodes that share one file (a multi-episode file like E24–E26) together, so none of them is left without a file.
- Finish import never offers a library file as its own replacement, and leaves files that look the same as yours (same quality and group) unticked.

## v0.3.0

Run a new scan after updating. The new features need the quality profiles and episode details it reads.

- **Exclude quality profiles** (#2): titles on chosen Radarr/Sonarr profiles, like a Nordic profile, are left out of Titles and the Overview counts and listed under Ignored. Titles has a quality profile filter too.
- **Finish import** (#3): when the target season pack is already in qBittorrent but some episodes in your library come from other releases, Seedshift lists them and has Sonarr import them from the pack. Better current files are unticked by default. Sonarr copies or hardlinks, never moves, so the pack keeps seeding. Packs Sonarr never imported from are found by name.
- **Details** on a season shows where each episode comes from: the target pack, other torrents, or nothing.
- Titles marks seasons with a **Target pack in qBittorrent**.
- Search marks releases that are **Already in qBittorrent**, since grabbing them again fails as a duplicate.
- History lists Finish imports and follows them until Sonarr is done.

## v0.2.8

- Titles you've grabbed are dimmed until they're on target, so the ones still to do stand out. The **Grabbed** tag and the buttons stay bright.

## v0.2.7

- Titles shows the **Grabbed** tag right after a grab, without refreshing the page.
- The browser tab icon updates after an update, instead of staying cached.

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
