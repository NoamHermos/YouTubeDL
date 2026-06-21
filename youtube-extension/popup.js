const DEFAULT_WEB_APP_BASE = "http://127.0.0.1:8080/";
const SERVER_URL_KEY = "webAppBase";
const statusEl = document.querySelector("#status");
const serverUrlInput = document.querySelector("#server-url");
const youtubeUrlInput = document.querySelector("#youtube-url");
const jobsEl = document.querySelector("#jobs");

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

function serverPermissionPattern(serverUrl) {
  const url = new URL(serverUrl);
  return `${url.protocol}//${url.hostname}/*`;
}

async function getWebAppBase() {
  const stored = await chrome.storage.sync.get({[SERVER_URL_KEY]: DEFAULT_WEB_APP_BASE});
  return normalizeServerUrl(stored[SERVER_URL_KEY]);
}

async function saveWebAppBase() {
  try {
    const normalized = normalizeServerUrl(serverUrlInput.value);
    const allowed = await chrome.permissions.request({origins: [serverPermissionPattern(normalized)]});
    if (!allowed) {
      throw new Error("Allow access to the downloader server to continue.");
    }
    await chrome.storage.sync.set({[SERVER_URL_KEY]: normalized});
    serverUrlInput.value = normalized;
    statusEl.textContent = "Server saved.";
  } catch (error) {
    statusEl.textContent = error.message;
  }
}

function cleanYouTubeUrl(rawUrl) {
  const url = new URL(rawUrl);
  if (url.pathname === "/watch" && url.searchParams.get("v")) {
    return `https://www.youtube.com/watch?v=${url.searchParams.get("v")}`;
  }
  throw new Error("Enter a YouTube video URL.");
}

function renderJobs(jobs) {
  jobsEl.textContent = "";
  if (!jobs.length) {
    jobsEl.innerHTML = '<div class="muted">No active downloads.</div>';
    return;
  }
  for (const job of jobs) {
    const row = document.createElement("div");
    row.className = "job";
    const title = document.createElement("div");
    title.className = "job-title";
    title.textContent = job.title || job.sourceUrl;
    title.title = job.sourceUrl;
    const meta = document.createElement("div");
    meta.className = "job-meta";
    const suffix = job.error ? ` - ${job.error}` : "";
    meta.textContent = `${job.status} - ${Math.round(job.progress || 0)}%${suffix}`;
    const track = document.createElement("div");
    track.className = "progress-track";
    const value = document.createElement("div");
    value.className = "progress-value";
    value.style.width = `${Math.max(0, Math.min(100, job.progress || 0))}%`;
    track.appendChild(value);
    row.append(title, meta, track);
    jobsEl.appendChild(row);
  }
}

async function refreshJobs() {
  const response = await chrome.runtime.sendMessage({type: "get-jobs"});
  renderJobs(response.jobs || []);
}

async function startTxtDownload() {
  try {
    const url = cleanYouTubeUrl(youtubeUrlInput.value.trim());
    const response = await chrome.runtime.sendMessage({type: "start-txt-download", url});
    if (!response?.ok) {
      throw new Error(response?.error || "Could not start download.");
    }
    statusEl.textContent = "TXT download added.";
    youtubeUrlInput.value = "";
    await refreshJobs();
  } catch (error) {
    statusEl.textContent = error.message;
  }
}

document.querySelector("#save-server").addEventListener("click", saveWebAppBase);
document.querySelector("#download-txt").addEventListener("click", startTxtDownload);
youtubeUrlInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    startTxtDownload();
  }
});
chrome.runtime.onMessage.addListener((message) => {
  if (message?.type === "jobs-updated") {
    renderJobs(message.jobs || []);
  }
});

getWebAppBase()
  .then((url) => {
    serverUrlInput.value = url;
  })
  .catch((error) => {
    statusEl.textContent = error.message;
  });

refreshJobs();
window.setInterval(refreshJobs, 2000);
