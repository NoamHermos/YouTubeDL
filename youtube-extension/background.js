const DEFAULT_WEB_APP_BASE = "http://127.0.0.1:8080/";
const SERVER_URL_KEY = "webAppBase";
const JOBS_KEY = "txtDownloadJobs";
const POLL_ALARM = "poll-txt-downloads";
const MAX_SAVED_JOBS = 12;
const DOWNLOAD_TYPES = new Set(["video", "audio", "srt", "txt"]);
const FAST_POLL_DELAY_MS = 2000;
let fastPollTimer = null;
let pollPromise = null;

function normalizeServerUrl(rawValue) {
  const raw = (rawValue || "").trim() || DEFAULT_WEB_APP_BASE;
  const url = new URL(raw);
  if (!["http:", "https:"].includes(url.protocol)) {
    throw new Error("Use http:// or https://");
  }
  if (!url.pathname.endsWith("/")) {
    url.pathname += "/";
  }
  url.search = "";
  url.hash = "";
  return url.toString();
}

function cleanYouTubeUrl(rawUrl) {
  const url = new URL(rawUrl);
  if (url.pathname === "/watch" && url.searchParams.get("v")) {
    return `https://www.youtube.com/watch?v=${url.searchParams.get("v")}`;
  }
  throw new Error("Use a YouTube video URL.");
}

function titleForUrl(rawUrl) {
  try {
    return new URL(rawUrl).searchParams.get("v") || rawUrl;
  } catch {
    return rawUrl;
  }
}

async function getWebAppBase() {
  const stored = await chrome.storage.sync.get({[SERVER_URL_KEY]: DEFAULT_WEB_APP_BASE});
  return normalizeServerUrl(stored[SERVER_URL_KEY]);
}

async function getJobs() {
  const stored = await chrome.storage.local.get({[JOBS_KEY]: []});
  return stored[JOBS_KEY];
}

async function saveJobs(jobs) {
  await chrome.storage.local.set({[JOBS_KEY]: jobs.slice(0, MAX_SAVED_JOBS)});
}

function progressFromLog(logLines) {
  const text = Array.isArray(logLines) ? logLines.join("") : "";
  const matches = [...text.matchAll(/(?:Progress|Downloading):[^\n]*?(\d{1,3}(?:\.\d+)?)%/g)];
  if (!matches.length) {
    return 0;
  }
  return Math.min(100, Number(matches.at(-1)[1]));
}

async function notifyJobsChanged() {
  const jobs = await getJobs();
  chrome.runtime.sendMessage({type: "jobs-updated", jobs}).catch(() => {});
}

async function startDownload(rawUrl, downloadType, options = {}) {
  if (!DOWNLOAD_TYPES.has(downloadType)) {
    throw new Error("Unsupported download type.");
  }
  const url = cleanYouTubeUrl(rawUrl);
  const serverUrl = await getWebAppBase();
  const jobs = await getJobs();
  const entry = {
    id: `starting-${Date.now()}`,
    sourceUrl: url,
    title: titleForUrl(url),
    downloadType,
    serverUrl,
    status: "starting",
    progress: 0,
    createdAt: Date.now(),
  };
  jobs.unshift(entry);
  await saveJobs(jobs);
  await notifyJobsChanged();

  let response;
  try {
    response = await fetch(new URL("api/jobs", serverUrl), {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        url,
        source: "single",
        download_type: downloadType,
        workers: 4,
        with_subtitles: Boolean(options.withSubtitles),
      }),
    });
  } catch {
    entry.status = "failed";
    entry.error = "Cannot reach the downloader server. Open the extension and click Save Server.";
    await saveJobs(jobs);
    await notifyJobsChanged();
    throw new Error(entry.error);
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    entry.status = "failed";
    entry.error = payload.error || `Downloader server returned ${response.status}.`;
    await saveJobs(jobs);
    await notifyJobsChanged();
    throw new Error(entry.error);
  }

  entry.id = payload.id;
  entry.status = "queued";
  await saveJobs(jobs);
  await ensurePolling();
  await notifyJobsChanged();
  return payload.id;
}

function downloadUrl(serverUrl, file) {
  return new URL(file.url || `files/${encodeURIComponent(file.name)}`, serverUrl).toString();
}

async function pollJobs() {
  if (pollPromise) {
    return pollPromise;
  }

  pollPromise = pollJobsInternal();
  try {
    return await pollPromise;
  } finally {
    pollPromise = null;
  }
}

async function pollJobsInternal() {
  const jobs = await getJobs();
  let changed = false;
  let hasActiveJobs = false;

  for (const entry of jobs) {
    if (!["queued", "running", "cancelling"].includes(entry.status)) {
      continue;
    }
    hasActiveJobs = true;

    try {
      const response = await fetch(new URL(`api/jobs/${entry.id}`, entry.serverUrl));
      if (!response.ok) {
        throw new Error(`Server returned ${response.status}`);
      }
      const job = await response.json();
      entry.status = job.status;
      entry.progress = job.status === "finished" ? 100 : progressFromLog(job.log);
      entry.title = job.url || entry.title;
      entry.error = "";
      changed = true;

      if (job.status === "finished") {
        for (const file of job.outputs || []) {
          await chrome.downloads.download({
            url: downloadUrl(entry.serverUrl, file),
            filename: (file.name || "download.txt").split("/").pop(),
            conflictAction: "uniquify",
            saveAs: false,
          });
        }
        entry.status = "downloaded";
      } else if (job.status === "failed") {
        entry.error = `The server could not create the ${(entry.downloadType || "file").toUpperCase()} file.`;
      }
    } catch (error) {
      entry.status = "failed";
      entry.error = error.message || "Could not reach the downloader server.";
      changed = true;
    }
  }

  if (changed) {
    await saveJobs(jobs);
    await notifyJobsChanged();
  }

  if (hasActiveJobs) {
    scheduleFastPoll();
  }
}

function scheduleFastPoll() {
  if (fastPollTimer) {
    return;
  }
  fastPollTimer = setTimeout(async () => {
    fastPollTimer = null;
    await pollJobs();
  }, FAST_POLL_DELAY_MS);
}

async function ensurePolling() {
  await chrome.alarms.create(POLL_ALARM, {periodInMinutes: 0.5});
  await pollJobs();
  scheduleFastPoll();
}

chrome.runtime.onInstalled.addListener(() => {
  ensurePolling();
});

chrome.runtime.onStartup.addListener(() => {
  ensurePolling();
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === POLL_ALARM) {
    pollJobs();
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "start-download" || message?.type === "start-txt-download") {
    const downloadType = message.downloadType || "txt";
    startDownload(message.url, downloadType, message.options || {})
      .then((id) => sendResponse({ok: true, id}))
      .catch((error) => sendResponse({ok: false, error: error.message}));
    return true;
  }
  if (message?.type === "get-jobs") {
    pollJobs()
      .catch(() => {})
      .then(getJobs)
      .then((jobs) => sendResponse({jobs}));
    return true;
  }
  return undefined;
});
