const DEFAULT_WEB_APP_BASE = "http://127.0.0.1:8080/";
const SERVER_URL_KEY = "webAppBase";
const JOBS_KEY = "txtDownloadJobs";
const POLL_ALARM = "poll-txt-downloads";
const MAX_SAVED_JOBS = 12;

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

function serverPermissionPattern(serverUrl) {
  const url = new URL(serverUrl);
  return `${url.protocol}//${url.hostname}/*`;
}

async function ensureServerPermission(serverUrl) {
  const granted = await chrome.permissions.contains({origins: [serverPermissionPattern(serverUrl)]});
  if (!granted) {
    throw new Error("Open the extension popup and click Save Server to allow access to the downloader server.");
  }
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

async function startTxtDownload(rawUrl) {
  const url = cleanYouTubeUrl(rawUrl);
  const serverUrl = await getWebAppBase();
  await ensureServerPermission(serverUrl);
  let response;
  try {
    response = await fetch(new URL("api/jobs", serverUrl), {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        url,
        source: "single",
        download_type: "txt",
        workers: 4,
      }),
    });
  } catch {
    throw new Error("Cannot reach the downloader server. Open the extension and click Save Server.");
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || `Downloader server returned ${response.status}.`);
  }

  const jobs = await getJobs();
  jobs.unshift({
    id: payload.id,
    sourceUrl: url,
    title: titleForUrl(url),
    serverUrl,
    status: "queued",
    progress: 0,
    createdAt: Date.now(),
  });
  await saveJobs(jobs);
  await ensurePolling();
  await notifyJobsChanged();
  return payload.id;
}

function downloadUrl(serverUrl, file) {
  return new URL(file.url || `files/${encodeURIComponent(file.name)}`, serverUrl).toString();
}

async function pollJobs() {
  const jobs = await getJobs();
  let changed = false;

  for (const entry of jobs) {
    if (!["queued", "running", "cancelling"].includes(entry.status)) {
      continue;
    }

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
        entry.error = "The server could not create the TXT file.";
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
}

async function ensurePolling() {
  await chrome.alarms.create(POLL_ALARM, {periodInMinutes: 0.5});
  await pollJobs();
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
  if (message?.type === "start-txt-download") {
    startTxtDownload(message.url)
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
