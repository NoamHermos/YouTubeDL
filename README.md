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
- Use a saved worker count for future browser sessions. The default is 4 workers.
- View live job logs with a single updating progress line and download speed.
- Download completed files from the browser.
- Delete selected downloaded files, or clear the listed downloads.
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

Downloaded files are written to `./downloads` on the host by default.

On NAS or Portainer deployments, prefer an absolute host path on a large volume
so large MP4 merges have enough working space:

```env
HOST_DOWNLOADS_DIR=/volume1/YouTubeDL/downloads
```

Then redeploy the stack. The container will still see the folder as
`/app/downloads`.

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

If the web app runs on a NAS, server, or Portainer instead of your local
machine, open the extension popup and set `Server URL` to the server address,
for example:

```text
http://192.168.1.50:8080/
```

The popup buttons and the buttons injected into YouTube pages will use the saved
server URL.

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

## Project Structure

Core application:

- `web_app.py` - small Flask entrypoint that creates and runs the web app.
- `web_worker.py` - subprocess worker used by the web UI for download jobs.
- `ytdl.py` - small compatibility entrypoint that re-exports the core helpers and
  keeps the legacy CLI command working.
- `ytdl_core/` - organized core download package.
  - `downloader.py` - single-video processing, media/subtitle download options,
    progress tracking, and output stats.
  - `subtitles.py` - VTT-to-SRT conversion, rolling subtitle cleanup, subtitle
    file matching, and TXT transcript export.
  - `captions.py` - manual/automatic caption language selection.
  - `formats.py` - filename cleanup, playlist URL normalization, quality
    grouping, and format descriptions.
  - `speed.py` - concurrent fragment download mode and fallback handling.
  - `cli.py` and `cli_utils.py` - legacy interactive CLI flow.
  - `config.py` - shared paths for the core package.

Web package:

- `youtube_downloader_web/app.py` - Flask app factory.
- `youtube_downloader_web/routes.py` - HTTP routes and JSON API endpoints.
- `youtube_downloader_web/job_service.py` - job state, subprocess handling, live
  log streaming, cancellation, and output detection.
- `youtube_downloader_web/file_service.py` - downloaded file listing, safe path
  resolution, open file, reveal in folder, and clipboard copy.
- `youtube_downloader_web/format_service.py` - video information lookup and
  quality option building.
- `youtube_downloader_web/settings.py` - runtime paths and environment-backed
  settings.
- `youtube_downloader_web/templates/index.html` - web UI markup.
- `youtube_downloader_web/static/app.js` - web UI behavior.
- `youtube_downloader_web/static/styles.css` - web UI styling.

Browser extension:

- `youtube-extension/manifest.json` - Chrome/Edge Manifest V3 configuration.
- `youtube-extension/content.js` / `content.css` - buttons injected into YouTube
  video and playlist pages.
- `youtube-extension/popup.html` / `popup.js` / `popup.css` - extension popup UI.
- `youtube-extension/logo.png` and `youtube-extension/icons/` - extension logo
  and browser icon sizes.

Packaging and repository files:

- `Dockerfile` and `docker-compose.yml` - container build and local compose setup.
- `requirements.txt` - Python dependencies.
- `.env.example` - example environment variables.
- `.gitignore` and `.dockerignore` - exclude downloads, cookies, logs, local
  credentials, and runtime artifacts.
- `.gitattributes` - keeps repository text files normalized.
