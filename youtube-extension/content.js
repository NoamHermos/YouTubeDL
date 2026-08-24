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

  async function openApp() {
    window.open(await getWebAppBase(), "_blank", "noopener,noreferrer");
  }

  function showButtonResult(button, result, successText, defaultText) {
    if (result?.ok) {
      button.textContent = successText;
      button.title = "Download added to the extension queue";
      return;
    }
    const error = result?.error || "Could not start download";
    button.textContent = error.includes("Save Server") ? "Setup" : "Error";
    button.title = error;
  }

  async function startExtensionDownload(downloadType, button, defaultText) {
    button.disabled = true;
    button.textContent = "Adding...";
    try {
      const result = await chrome.runtime.sendMessage({
        type: "start-download",
        downloadType,
        url: currentYouTubeUrl(),
        options: {showPopup: true, isolatedOutputs: true},
      });
      showButtonResult(button, result, "Added", defaultText);
    } catch (error) {
      showButtonResult(button, {error: error.message}, "Added", defaultText);
    }
    window.setTimeout(() => {
      button.disabled = false;
      button.textContent = defaultText;
      button.title = "";
    }, 2400);
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
      const text = `Download ${item.label}`;
      button.type = "button";
      button.className = "ytdl-local-button";
      button.textContent = text;
      if (item.type === "txt") {
        button.title = "Download TXT, attach it to ChatGPT, and send a summary prompt";
      }
      button.addEventListener("click", () => startExtensionDownload(item.type, button, text));
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

  function stopThumbnailNavigation(event) {
    event.preventDefault();
    event.stopPropagation();
  }

  function createTextButton(videoUrl) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ytdl-txt-thumbnail-button";
    button.dataset.videoUrl = videoUrl;
    button.textContent = "TXT";
    button.title = "Download TXT and send it to ChatGPT for summarization";
    button.setAttribute("aria-label", button.title);
    ["pointerdown", "mousedown", "mouseup", "click"].forEach((eventName) => {
      button.addEventListener(eventName, stopThumbnailNavigation);
    });
    button.addEventListener("click", async () => {
      // YouTube reuses result-card DOM nodes while navigating and scrolling.
      // Read the URL from the button at click time instead of closing over the
      // URL that the card had when this button was first created.
      const currentVideoUrl = button.dataset.videoUrl;
      button.disabled = true;
      button.textContent = "...";
      try {
        if (!currentVideoUrl) {
          throw new Error("Could not find the video URL.");
        }
        const result = await chrome.runtime.sendMessage({
          type: "start-download",
          downloadType: "txt",
          url: currentVideoUrl,
          options: {showPopup: true, isolatedOutputs: true},
        });
        showButtonResult(button, result, "Added", "TXT");
      } catch (error) {
        showButtonResult(button, {error: error.message}, "Added", "TXT");
      }
      window.setTimeout(() => {
        button.disabled = false;
        button.textContent = "TXT";
        button.title = "Download TXT and send it to ChatGPT for summarization";
      }, 2400);
    });
    return button;
  }

  function findVideoContainer(link) {
    return link.closest([
      "ytd-playlist-panel-video-renderer",
      "ytd-playlist-video-renderer",
      "ytd-compact-video-renderer",
      "ytd-video-renderer",
      "ytd-rich-item-renderer",
      "ytd-grid-video-renderer",
      "ytd-reel-item-renderer",
      "ytd-compact-playlist-renderer",
      "ytd-radio-renderer"
    ].join(","));
  }

  function findThumbnailHost(link) {
    return (
      link.closest("ytd-thumbnail") ||
      link.closest("#thumbnail-container") ||
      link.closest("#thumbnail") ||
      link.parentElement ||
      link
    );
  }

  function pruneDuplicateTextButtons(container) {
    const buttons = container.querySelectorAll(BUTTON_SELECTOR);
    buttons.forEach((button, index) => {
      if (index > 0) {
        button.remove();
      }
    });
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
      const container = findVideoContainer(link) || link.closest("ytd-thumbnail") || link.parentElement || link;
      const host = findThumbnailHost(link);
      if (!videoUrl || !host || !container) {
        return;
      }
      const existingButton = container.querySelector(BUTTON_SELECTOR);
      if (existingButton) {
        pruneDuplicateTextButtons(container);
        existingButton.dataset.videoUrl = videoUrl;
        container.dataset.ytdlTxtInjected = videoUrl;
        host.classList.add("ytdl-thumbnail-host");
        if (!host.contains(existingButton)) {
          host.appendChild(existingButton);
        }
        return;
      }
      if (container.dataset.ytdlTxtInjected === videoUrl) {
        return;
      }
      container.dataset.ytdlTxtInjected = videoUrl;
      host.classList.add("ytdl-thumbnail-host");
      host.appendChild(createTextButton(videoUrl));
      pruneDuplicateTextButtons(container);
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
    subtree: true,
    attributes: true,
    attributeFilter: ["href"]
  });
})();
