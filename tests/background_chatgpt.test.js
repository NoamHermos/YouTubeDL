const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function loadBackground(overrides = {}) {
  const listeners = {};
  const calls = {createdTabs: [], messages: []};
  const chrome = {
    action: {openPopup: async () => {}},
    alarms: {
      create: async () => {},
      onAlarm: {addListener(callback) { listeners.alarm = callback; }},
    },
    downloads: {download: async () => 1},
    runtime: {
      id: "test-extension",
      onInstalled: {addListener(callback) { listeners.installed = callback; }},
      onMessage: {addListener(callback) { listeners.message = callback; }},
      onStartup: {addListener(callback) { listeners.startup = callback; }},
      sendMessage: async () => {},
    },
    storage: {
      local: {get: async () => ({txtDownloadJobs: []}), set: async () => {}},
      sync: {get: async () => ({})},
    },
    tabs: {
      async create(options) {
        calls.createdTabs.push(options);
        return {id: 42};
      },
      async sendMessage(tabId, message) {
        calls.messages.push({tabId, message});
        return {ok: true};
      },
    },
    ...overrides,
  };
  const context = {
    URL,
    Uint8Array,
    btoa,
    chrome,
    console,
    fetch: async () => ({ok: true, arrayBuffer: async () => new ArrayBuffer(0)}),
    setTimeout,
  };
  vm.createContext(context);
  const source = fs.readFileSync(path.resolve("youtube-extension/background.js"), "utf8");
  vm.runInContext(source, context);
  return {calls, context, listeners};
}

test("background chooses the TXT output from an isolated job", () => {
  const {context} = loadBackground();
  const selected = context.transcriptOutput([
    {name: "job/video.mp4"},
    {name: "job/transcript.txt"},
  ]);

  assert.equal(selected.name, "job/transcript.txt");
});

test("background opens ChatGPT and sends the attachment with the summary prompt", async () => {
  const {calls, context} = loadBackground();
  await context.openChatGPTAndSubmit({
    fileBase64: "dGVzdA==",
    fileName: "transcript.txt",
    mimeType: "text/plain",
    prompt: "סכם את הסרטון",
  });

  assert.equal(calls.createdTabs.length, 1);
  assert.equal(calls.createdTabs[0].url, "https://chatgpt.com/");
  assert.equal(calls.createdTabs[0].active, true);
  assert.equal(calls.messages.length, 1);
  assert.equal(calls.messages[0].tabId, 42);
  assert.equal(calls.messages[0].message.type, "submit-txt-summary");
  assert.equal(calls.messages[0].message.prompt, "סכם את הסרטון");
  assert.equal(calls.messages[0].message.fileName, "transcript.txt");
});
