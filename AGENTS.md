# Seedshift: agent notes

Flask + Waitress app that lists Radarr/Sonarr titles not seeding on a chosen tracker, from qBittorrent data. Scans are read-only; the only write is a user-confirmed Grab, sent to Radarr/Sonarr. Owner prefers simple, direct solutions.

## Layout
- `engine.py`: settings, qBittorrent/Arr clients, scan, matching, evaluation. No Flask.
- `search.py`: interactive search (Arr or Prowlarr), limited to the target indexer, and grab.
- `api.py`: JSON API blueprint at `/api`. `app.py`: HTML shell routes and `/health`.
- `templates/shell.html` + `static/ui/` is the whole front end. No build step.
- `dev/`: fixture builder with real hardlinks and mock qBittorrent/Radarr/Sonarr.

## Front end rules
- Same system as Trailarr Parrk v0.8.0: vanilla ES modules, `h()` builder, History router, tokens in `css/tokens.css`, Font Awesome SVGs in `js/icons.js`, native `<dialog>`.
- Seedshift-only styles go in `css/seedshift.css`; keep the shared CSS files identical to Trailarr Parrk so they can be synced.
- Theme is Dusk (`data-theme="dusk"`), defined at the bottom of `css/seedshift.css` by overriding the palette variables only.
- Filters live in the URL.

## Behavior to keep
- Never write to qBittorrent or media. The data share is mounted read-only.
- Automatic replace (setting, off by default) only uses the Arr's own manual import, and only for "not an upgrade" blocks (`replace.py`).
- Finish import (`importer.py`) only uses Sonarr's manual import, after a confirm, with `importMode: copy` so the target pack is never moved. Like search, the preview stays server-side and the browser sends indices.
- Excluded quality profiles work like ignored titles: hidden from Titles' normal views and from the Overview counts.
- Grabs only go through Radarr/Sonarr (release or release/push), always after a confirm in the UI. Search results stay server-side; the browser only sends a result index.
- Connections are one list with types qbittorrent, radarr, sonarr, prowlarr. Torrents are keyed `<client id>/<hash>`.
- Scans store raw links (file → torrent hashes, torrent → host). Status is computed on read, so changing the target never needs a rescan.
- A season is on target only when one target torrent covers every episode file.
- Never store or show announce passkeys; only hosts.
- Screenshot mode (`privacy.py`, cookie `seedshift_private=1`) masks every /api JSON response and blocks saving settings. New fields with titles, hosts or paths get masked by the generic text pass; check new keys that need special handling.

## Checking changes
- `python3 -m py_compile engine.py search.py replace.py importer.py privacy.py api.py app.py`
- Run the mocks from `dev/`, then exercise the API with Flask's test client and the UI in a headless browser at 1280 px and 390 px.
