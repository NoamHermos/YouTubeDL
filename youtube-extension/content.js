(function () {
  const DEFAULT_WEB_APP_BASE = "http://127.0.0.1:8080/";
  const SERVER_URL_KEY = "webAppBase";
  const TOOLBAR_ID = "ytdl-local-toolbar";
  const BUTTON_SELECTOR = ".ytdl-txt-thumbnail-button";
  const TYPES = [
    {type: "video", label: "MP4"},
    {type: "audio", label: "MP3"},
    {type: "srt", label: "SRT"},
    {type: "txt", label: "TXT"}
  ];

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

  function cleanYouTubeUrl(rawUrl) {
    const url = new URL(rawUrl, window.location.origin);
    if (url.pathname !== "/watch" || !url.searchParams.get("v")) {
      return null;
    }
    return `https://www.youtube.com/watch?v=${url.searchParams.get("v")}`;
  }

  function currentYouTubeUrl() {
    return cleanYouTubeUrl(window.location.href) || window.location.href;
  }

  function currentSource() {
    return new URL(window.location.href).pathname.startsWith("/playlist") ? "playlist" : "single";
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

  function findToolbarHost() {
    return (
      document.querySelector("#above-the-fold #title") ||
      document.querySelector("ytd-watch-metadata #title") ||
      document.querySelector("#primary #title") ||
      document.querySelector("ytd-playlist-header-renderer #title") ||
      document.querySelector("#header-description")
    );
  }

  function injectToolbar() {
    if (!["/watch", "/playlist"].some((prefix) => location.pathname.startsWith(prefix))) {
      document.getElementById(TOOLBAR_ID)?.remove();
      return;
    }

    const host = findToolbarHost();
    if (host && !document.getElementById(TOOLBAR_ID)) {
      host.insertAdjacentElement("afterend", createToolbar());
    }
  }

  function showTextButtonResult(button, result) {
    if (result?.ok) {
      button.textContent = "Added";
      button.title = "TXT download added";
      return;
    }
    const error = result?.error || "Could not start TXT download";
    button.textContent = error.includes("Save Server") ? "Setup" : "Error";
    button.title = error;
  }

  function stopThumbnailNavigation(event) {
    event.preventDefault();
    event.stopPropagation();
  }

  function createTextButton(videoUrl) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ytdl-txt-thumbnail-button";
    button.textContent = "TXT";
    button.title = "Download transcript as TXT";
    button.setAttribute("aria-label", button.title);
    ["pointerdown", "mousedown", "mouseup", "click"].forEach((eventName) => {
      button.addEventListener(eventName, stopThumbnailNavigation);
    });
    button.addEventListener("click", async () => {
      button.disabled = true;
      button.textContent = "...";
      try {
        const result = await chrome.runtime.sendMessage({type: "start-download", downloadType: "txt", url: videoUrl});
        showTextButtonResult(button, result);
      } catch (error) {
        showTextButtonResult(button, {error: error.message});
      }
      window.setTimeout(() => {
        button.disabled = false;
        button.textContent = "TXT";
        button.title = "Download transcript as TXT";
      }, 2400);
    });
    return button;
  }

  function injectTextButtons() {
    const thumbnailLinks = document.querySelectorAll([
      "ytd-thumbnail a[href*='/watch']",
      "a#thumbnail[href*='/watch']",
      "a#thumbnail-link[href*='/watch']",
      "a[href*='/watch']:has(img)",
      "a[href*='/watch']:has(yt-image)"
    ].join(","));

    thumbnailLinks.forEach((link) => {
      const videoUrl = cleanYouTubeUrl(link.href);
      const host = link.closest("ytd-thumbnail") || link.parentElement || link;
      if (!videoUrl || !host || host.querySelector(BUTTON_SELECTOR)) {
        return;
      }
      host.classList.add("ytdl-thumbnail-host");
      host.appendChild(createTextButton(videoUrl));
    });
  }

  let injectTimer = null;
  function scheduleInject() {
    window.clearTimeout(injectTimer);
    injectTimer = window.setTimeout(() => {
      injectToolbar();
      injectTextButtons();
    }, 250);
  }

  scheduleInject();
  document.addEventListener("yt-navigate-finish", scheduleInject);
  new MutationObserver(scheduleInject).observe(document.documentElement, {
    childList: true,
    subtree: true
  });
})();
