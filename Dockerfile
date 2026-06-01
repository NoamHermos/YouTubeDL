FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PORT=8080 \
    DOWNLOADS_DIR=/app/downloads \
    COOKIE_FILE=/app/cookies.txt

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY ytdl.py web_app.py web_worker.py ./
COPY youtube_downloader_web ./youtube_downloader_web

RUN mkdir -p /app/downloads

EXPOSE 8080

CMD ["python", "web_app.py"]
