(function () {
  const DEFAULT_WEB_APP_BASE = "http://127.0.0.1:8080/";
  const SERVER_URL_KEY = "webAppBase";
  const TOOLBAR_ID = "ytdl-local-toolbar";
  const TYPES = [
    {type: "video", label: "MP4"},
    {type: "audio", label: "MP3"},
    {type: "srt", label: "SRT"},
    {type: "txt", label: "TXT"}
  ];

  function currentYouTubeUrl() {
    const url = new URL(window.location.href);
    if (url.pathname === "/watch" && url.searchParams.get("v")) {
      return `https://www.youtube.com/watch?v=${url.searchParams.get("v")}`;
    }
    if (url.pathname.startsWith("/playlist") && url.searchParams.get("list")) {
      return `https://www.youtube.com/playlist?list=${url.searchParams.get("list")}`;
    }
    return window.location.href;
  }

  function currentSource() {
    const url = new URL(window.location.href);
    return url.pathname.startsWith("/playlist") ? "playlist" : "single";
  }

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

  async function getWebAppBase() {
    const stored = await chrome.storage.sync.get({[SERVER_URL_KEY]: DEFAULT_WEB_APP_BASE});
    return normalizeServerUrl(stored[SERVER_URL_KEY]);
  }

  async function openDownloader(type) {
    const target = new URL(await getWebAppBase());
    target.searchParams.set("url", currentYouTubeUrl());
    target.searchParams.set("type", type);
    target.searchParams.set("source", currentSource());
    target.searchParams.set("action", type === "video" ? "fetch_qualities" : "start");
    if (type === "video" || type === "audio") {
      target.searchParams.set("with_subtitles", "true");
    }
    window.open(target.toString(), "_blank", "noopener,noreferrer");
  }

  async function openApp() {
    window.open(await getWebAppBase(), "_blank", "noopener,noreferrer");
  }

  function createToolbar() {
    const toolbar = document.createElement("div");
    toolbar.id = TOOLBAR_ID;
    toolbar.className = "ytdl-local-toolbar";

    const logo = document.createElement("img");
    logo.className = "ytdl-local-logo";
    logo.alt = "";
    logo.src = chrome.runtime.getURL("logo.png");
    toolbar.appendChild(logo);

    for (const item of TYPES) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "ytdl-local-button";
      button.textContent = `Download ${item.label}`;
      button.addEventListener("click", () => openDownloader(item.type));
      toolbar.appendChild(button);
    }

    const openButton = document.createElement("button");
    openButton.type = "button";
    openButton.className = "ytdl-local-button secondary";
    openButton.textContent = "Open Downloader";
    openButton.addEventListener("click", openApp);
    toolbar.appendChild(openButton);
    return toolbar;
  }

  function findHost() {
    return (
      document.querySelector("#above-the-fold #title") ||
      document.querySelector("ytd-watch-metadata #title") ||
      document.querySelector("#primary #title") ||
      document.querySelector("ytd-playlist-header-renderer #title") ||
      document.querySelector("#header-description")
    );
  }

  function injectToolbar() {
    if (!location.hostname.includes("youtube.com")) {
      return;
    }

    if (!["/watch", "/playlist"].some((prefix) => location.pathname.startsWith(prefix))) {
      document.getElementById(TOOLBAR_ID)?.remove();
      return;
    }

    const host = findHost();
    if (!host || document.getElementById(TOOLBAR_ID)) {
      return;
    }

    host.insertAdjacentElement("afterend", createToolbar());
  }

  let lastUrl = "";
  function scheduleInject() {
    if (lastUrl !== location.href) {
      lastUrl = location.href;
      document.getElementById(TOOLBAR_ID)?.remove();
    }
    window.setTimeout(injectToolbar, 350);
  }

  scheduleInject();
  document.addEventListener("yt-navigate-finish", scheduleInject);
  new MutationObserver(scheduleInject).observe(document.documentElement, {
    childList: true,
    subtree: true
  });
})();
