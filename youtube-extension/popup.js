const WEB_APP_BASE = "http://127.0.0.1:8080/";
const statusEl = document.querySelector("#status");

function sourceForUrl(rawUrl) {
  try {
    const url = new URL(rawUrl);
    return url.pathname.startsWith("/playlist") ? "playlist" : "single";
  } catch {
    return "single";
  }
}

function cleanYouTubeUrl(rawUrl) {
  const url = new URL(rawUrl);
  if (url.pathname === "/watch" && url.searchParams.get("v")) {
    return `https://www.youtube.com/watch?v=${url.searchParams.get("v")}`;
  }
  if (url.pathname.startsWith("/playlist") && url.searchParams.get("list")) {
    return `https://www.youtube.com/playlist?list=${url.searchParams.get("list")}`;
  }
  return rawUrl;
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  return tab;
}

async function openDownloader(type) {
  const tab = await activeTab();
  if (!tab?.url || !tab.url.includes("youtube.com")) {
    statusEl.textContent = "Open a YouTube video or playlist first.";
    return;
  }

  const target = new URL(WEB_APP_BASE);
  target.searchParams.set("url", cleanYouTubeUrl(tab.url));
  target.searchParams.set("type", type);
  target.searchParams.set("source", sourceForUrl(tab.url));
  target.searchParams.set("action", type === "video" ? "fetch_qualities" : "start");
  if (type === "video" || type === "audio") {
    target.searchParams.set("with_subtitles", "true");
  }
  await chrome.tabs.create({url: target.toString()});
}

document.querySelectorAll("[data-type]").forEach((button) => {
  button.addEventListener("click", () => openDownloader(button.dataset.type));
});

document.querySelector("#open-app").addEventListener("click", async () => {
  await chrome.tabs.create({url: WEB_APP_BASE});
});
