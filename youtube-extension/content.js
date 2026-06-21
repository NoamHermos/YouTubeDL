(function () {
  const BUTTON_SELECTOR = ".ytdl-txt-thumbnail-button";

  function cleanYouTubeUrl(rawUrl) {
    const url = new URL(rawUrl, window.location.origin);
    if (url.pathname !== "/watch" || !url.searchParams.get("v")) {
      return null;
    }
    return `https://www.youtube.com/watch?v=${url.searchParams.get("v")}`;
  }

  function createTextButton(videoUrl) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ytdl-txt-thumbnail-button";
    button.textContent = "TXT";
    button.title = "Download transcript as TXT";
    button.setAttribute("aria-label", button.title);
    button.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      button.disabled = true;
      button.textContent = "...";
      try {
        const result = await chrome.runtime.sendMessage({type: "start-txt-download", url: videoUrl});
        button.textContent = result?.ok ? "Added" : "Error";
      } catch {
        button.textContent = "Error";
      }
      window.setTimeout(() => {
        button.disabled = false;
        button.textContent = "TXT";
      }, 1400);
    });
    return button;
  }

  function injectTextButtons() {
    document.querySelectorAll("ytd-thumbnail").forEach((thumbnail) => {
      if (thumbnail.querySelector(BUTTON_SELECTOR)) {
        return;
      }
      const link = thumbnail.querySelector("a#thumbnail[href*='/watch']");
      const videoUrl = link && cleanYouTubeUrl(link.href);
      if (!videoUrl) {
        return;
      }
      thumbnail.appendChild(createTextButton(videoUrl));
    });
  }

  let injectTimer = null;
  function scheduleInject() {
    window.clearTimeout(injectTimer);
    injectTimer = window.setTimeout(injectTextButtons, 250);
  }

  scheduleInject();
  document.addEventListener("yt-navigate-finish", scheduleInject);
  new MutationObserver(scheduleInject).observe(document.documentElement, {
    childList: true,
    subtree: true
  });
})();
