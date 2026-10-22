# Contributing to Seedshift

Thanks for helping out. Questions, bugs and ideas go to [GitHub Issues](https://github.com/grompty/seedshift/issues). Pull requests are welcome; for bigger changes, open an issue first so we can agree on it before you put in the work.

Never include API keys, passwords, tracker passkeys or your own media paths in issues, logs or commits.

## Project layout

| Path | What it is |
| --- | --- |
| `engine.py` | Settings, qBittorrent/Radarr/Sonarr/Prowlarr clients, scanning, matching and statuses. No Flask. |
| `search.py` | Search on the target indexer (through the Arr or Prowlarr) and Grab. |
| `replace.py` | Follows grabs in the Arr's queue and runs the manual import for **Replace my file after a grab**. Also follows Finish imports. |
| `importer.py` | **Finish import**: lists a season's episodes that aren't from the target pack and has Sonarr import them. |
| `api.py` | The JSON API under `/api`. |
| `app.py` | The HTML shell and `/health`. |
| `templates/`, `static/ui/` | The whole front end: vanilla ES modules, no build step. |
| `dev/` | Fake data share with real hardlinks, and mock services for testing. |
| `.github/workflows/docker.yml` | Builds and publishes the Docker image. |

## Build the image yourself

Clone the repo, then in `docker-compose.yml` replace the `image:` line with:

```yaml
    build: .
```

Build and start:

```bash
docker compose up -d --build
```

Run the same command after every code change.

## Develop without real services

```bash
python3 dev/make_fixtures.py /tmp/ss-data
python3 dev/mock_services.py /tmp/ss-data/mock.json 9797
```

This builds a fake data share with real hardlinks and runs mock services on port 9797:

| Service | Address | Login |
| --- | --- | --- |
| qBittorrent | `http://127.0.0.1:9797/qbit` and `/qbit2` | user `admin`, password `secret` |
| Radarr | `http://127.0.0.1:9797/radarr` | API key `testkey` |
| Sonarr | `http://127.0.0.1:9797/sonarr` | API key `testkey` |
| Prowlarr | `http://127.0.0.1:9797/prowlarr` | API key `testkey` |

Grabs sent to the mocks are listed at `http://127.0.0.1:9797/_grabs`.

For the README screenshots there's a demo library with made-up titles and example tracker names:

```bash
python3 dev/make_demo.py /tmp/ss-demo
python3 dev/mock_services.py /tmp/ss-demo/mock.json 9797
```

The screenshots are taken at 1280×800 and saved in `docs/screenshots/`.

The demo also covers Finish import (Night Market season 1 and Deep Field season 2) and an excludable Nordic quality profile in Radarr.

Start Seedshift against them:

```bash
pip install flask waitress
CONFIG_DIR=/tmp/ss-config waitress-serve --port=8095 app:app
```

Open `http://localhost:8095`, add the mock connections, and map `/data` to `/tmp/ss-data` under **Settings → Paths**.

## Checking a change

- `python3 -m py_compile engine.py search.py replace.py importer.py api.py app.py`
- Scan, open **Titles**, and run a **Search** against the mocks.
- Check the interface at desktop and phone width, with no errors in the browser console.

Things that must keep working:

- Scans only read. Seedshift never writes to qBittorrent or your files.
- Grabs only go through Radarr or Sonarr, always after a confirm.
- Finish import only goes through Sonarr's manual import, after a confirm, with `importMode: copy` so the pack is never moved.
- Passkeys are never stored or shown, only tracker host names.
- A season only counts as on target when one target torrent covers every episode.

## Releasing

Images are built by GitHub Actions and published to `ghcr.io/grompty/seedshift`:

- A tag such as `v0.3.0` publishes `0.3.0`, `0.2` and `latest`.
- A push to `main` publishes `edge`, for testing.

To release:

1. Update `APP_VERSION` in `engine.py`.
2. Add the changes to `CHANGELOG.md`.
3. Commit, tag and push:

```bash
git commit -am "v0.3.0" && git tag v0.3.0 && git push && git push --tags
```
