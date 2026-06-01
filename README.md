# YouTube Downloader Web UI

A local web UI for downloading YouTube media and subtitles with `yt-dlp`.

This project is a local wrapper around `yt-dlp`. It is intended for personal
use with media you own, control, created yourself, have permission to download,
or that is available under a license that allows downloading.

## Features

- Download MP4 video, with optional subtitles.
- Download MP3 audio, with optional subtitles.
- Download fixed SRT subtitles.
- Download TXT transcripts as continuous text.
- Choose video quality from the same cleaned quality list used by the CLI.
- View live job logs with a single updating progress line and download speed.
- Open downloaded files, reveal their folder location, or copy files to the clipboard.
- Open the web UI directly from YouTube using the included browser extension.
- Run locally with Python or package as a Docker container.

## Run Locally

```bash
python -m pip install -r requirements.txt
python web_app.py
```

Open:

```text
http://127.0.0.1:8080
```

## Run With Docker Compose

```bash
docker compose up --build
```

Open:

```text
http://127.0.0.1:8080
```

Downloaded files are written to `./downloads` on the host.

## YouTube Browser Extension

The `youtube-extension/` folder contains an unpacked Chrome/Edge extension.

To load it:

1. Open `chrome://extensions` or `edge://extensions`.
2. Enable Developer mode.
3. Click "Load unpacked".
4. Select the `youtube-extension/` folder.

When you open a YouTube video or playlist, the extension adds buttons for MP4,
MP3, SRT, and TXT. MP3, SRT, and TXT start the job immediately in the local web
UI. MP4 opens the local web UI and automatically fetches the available qualities
so you can choose before starting. Keep the local web app running at:

```text
http://127.0.0.1:8080
```

## Cookies

Public videos usually work without cookies.

For videos that require authentication, create a local `cookies.txt` file next to
`docker-compose.yml`, then uncomment the cookies volume in `docker-compose.yml`:

```yaml
# - ./cookies.txt:/app/cookies.txt:ro
```

Do not commit cookies or credential files. The included `.gitignore` excludes
common cookie, session, credential, log, and download artifacts.

## Responsible Use

This application is a neutral local tool and does not grant permission to
download or redistribute copyrighted material. You are responsible for making
sure your use complies with copyright law, platform terms of service, and any
licenses that apply to the media you access.

Recommended use cases include:

- Downloading your own uploaded videos.
- Backing up content you created or have explicit permission to store.
- Downloading public domain or Creative Commons content when the license allows it.
- Exporting subtitles or transcripts for content you are allowed to process.

Do not use this project to infringe copyright, bypass access restrictions, or
redistribute media without permission. The maintainers are not responsible for
misuse of the tool.

This repository does not include sample links to copyrighted media, cookies,
account credentials, downloaded videos, or downloaded audio files.

## License Notes

This project uses `yt-dlp`, which is distributed under the Unlicense. The
existence of an open-source license for the software does not change the legal
status of third-party media downloaded with it.

## Project Files

- `web_app.py` - small Flask entrypoint.
- `youtube_downloader_web/` - organized web app package.
  - `routes.py` - HTTP routes and API endpoints.
  - `job_service.py` - job state, subprocess worker handling, live logs.
  - `file_service.py` - downloaded file listing, opening, reveal-in-folder, clipboard copy.
  - `format_service.py` - quality lookup and format option building.
  - `templates/` and `static/` - web UI HTML, CSS, and JavaScript.
- `web_worker.py` - background download worker used by the web UI.
- `ytdl.py` - core download and subtitle-fixing logic, plus the legacy CLI.
- `Dockerfile` / `docker-compose.yml` - container packaging.
- `requirements.txt` - Python dependencies.
- `youtube-extension/` - unpacked browser extension for YouTube.
