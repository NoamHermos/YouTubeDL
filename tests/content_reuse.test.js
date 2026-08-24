const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

test("a reused YouTube card sends the URL visible at click time", async () => {
  let button = null;
  let observerCallback = null;
  const sentMessages = [];

  const host = {
    classList: {add() {}},
    appendChild(element) {
      button = element;
      element.parentElement = host;
    },
    contains(element) {
      return element === button;
    },
  };
  const container = {
    dataset: {},
    querySelector() {
      return button;
    },
    querySelectorAll() {
      return button ? [button] : [];
    },
  };
  const link = {
    href: "https://www.youtube.com/watch?v=firstVideo1",
    parentElement: host,
    closest(selector) {
      if (selector.includes("ytd-playlist-panel-video-renderer")) return container;
      if (selector === "ytd-thumbnail") return host;
      return null;
    },
  };

  function createElement() {
    const listeners = new Map();
    return {
      dataset: {},
      classList: {add() {}},
      appendChild() {},
      setAttribute() {},
      addEventListener(name, callback) {
        const callbacks = listeners.get(name) || [];
        callbacks.push(callback);
        listeners.set(name, callbacks);
      },
      listeners,
      remove() {},
    };
  }

  const location = {origin: "https://www.youtube.com", pathname: "/"};
  const context = {
    URL,
    chrome: {
      runtime: {
        getURL: () => "chrome-extension://test/logo.png",
        sendMessage: async (message) => {
          sentMessages.push(message);
          return {ok: true};
        },
      },
      storage: {sync: {get: async () => ({})}},
    },
    document: {
      documentElement: {},
      addEventListener() {},
      createElement,
      getElementById: () => null,
      querySelector: () => null,
      querySelectorAll: () => [link],
    },
    location,
    MutationObserver: class {
      constructor(callback) {
        observerCallback = callback;
      }
      observe() {}
    },
    window: {
      clearTimeout() {},
      location,
      open() {},
      setTimeout(callback) {
        callback();
        return 1;
      },
    },
  };

  const source = fs.readFileSync(path.resolve("youtube-extension/content.js"), "utf8");
  vm.runInNewContext(source, context);
  assert.equal(button.dataset.videoUrl, "https://www.youtube.com/watch?v=firstVideo1");

  link.href = "https://www.youtube.com/watch?v=secondVideo2";
  observerCallback([]);
  assert.equal(button.dataset.videoUrl, "https://www.youtube.com/watch?v=secondVideo2");

  const clickEvent = {preventDefault() {}, stopPropagation() {}};
  for (const callback of button.listeners.get("click")) {
    await callback(clickEvent);
  }
  assert.equal(sentMessages.at(-1).url, "https://www.youtube.com/watch?v=secondVideo2");
});
