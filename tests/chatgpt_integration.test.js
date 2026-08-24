const assert = require("node:assert/strict");
const test = require("node:test");
const vm = require("node:vm");

const {
  submitTranscriptInChatGPTPage,
} = require("../youtube-extension/chatgpt.js");

const PAYLOAD = {
  fileBase64: Buffer.from("שלום transcript", "utf8").toString("base64"),
  fileName: "transcript.txt",
  mimeType: "text/plain",
  prompt: "סכם את הסרטון",
};

async function runPageSubmission({autoSend = true, busyForMs = 0} = {}) {
  const globalNames = [
    "DataTransfer",
    "Event",
    "File",
    "HTMLInputElement",
    "InputEvent",
    "document",
    "window",
  ];
  const originalGlobals = Object.fromEntries(globalNames.map((name) => [name, global[name]]));
  let attachedFile = null;
  let attachmentVisible = false;
  let uploadBusy = false;
  let inputEvents = 0;
  let promptWrittenWhileBusy = false;
  let sendClicks = 0;
  let composerContent = "";

  class MockInput {
    set files(value) {
      this._files = value;
    }

    get files() {
      return this._files || [];
    }

    dispatchEvent(event) {
      inputEvents += 1;
      if (event.type === "change") {
        attachmentVisible = true;
        uploadBusy = busyForMs > 0;
        if (uploadBusy) {
          setTimeout(() => { uploadBusy = false; }, busyForMs);
        }
      }
    }
  }

  const input = new MockInput();
  const attachment = {
    getAttribute(name) {
      return name === "aria-label" ? "transcript.txt" : null;
    },
    matches() { return false; },
    querySelector(selector) {
      return uploadBusy && selector.includes("progressbar")
        ? {role: "progressbar"}
        : null;
    },
    get textContent() {
      return uploadBusy ? "transcript.txt Uploading" : "transcript.txt Document";
    },
  };
  const form = {
    querySelectorAll() {
      return attachmentVisible ? [attachment] : [];
    },
  };
  const composer = {
    closest(selector) { return selector === "form" ? form : null; },
    dispatchEvent() { inputEvents += 1; },
    focus() {},
    get innerText() { return composerContent; },
    get textContent() { return composerContent; },
    set textContent(value) {
      if (value && uploadBusy) promptWrittenWhileBusy = true;
      composerContent = value;
    },
  };
  const sendButton = {
    disabled: false,
    click() {
      sendClicks += 1;
      composerContent = "";
    },
  };

  try {
    global.DataTransfer = class {
      constructor() {
        this.files = [];
        this.items = {add: (file) => {
          attachedFile = file;
          this.files.push(file);
        }};
      }
    };
    global.Event = class {
      constructor(type) { this.type = type; }
    };
    global.File = class {
      constructor(parts, name, options) {
        this.parts = parts;
        this.name = name;
        this.type = options.type;
      }
    };
    global.HTMLInputElement = MockInput;
    global.InputEvent = class {};
    global.document = {
      createRange: null,
      execCommand: null,
      querySelector(selector) {
        if (selector.includes("prompt-textarea")) return composer;
        if (selector.includes("upload-files")) return input;
        if (selector.includes("send-button")) return sendButton;
        return null;
      },
    };
    global.window = {getSelection: null, setTimeout};

    const result = await submitTranscriptInChatGPTPage({...PAYLOAD, autoSend});
    return {
      attachedFile,
      input,
      inputEvents,
      promptWrittenWhileBusy,
      result,
      sendClicks,
    };
  } finally {
    for (const [name, value] of Object.entries(originalGlobals)) {
      if (value === undefined) delete global[name];
      else global[name] = value;
    }
  }
}

test("ChatGPT page helper rejects a non-TXT attachment", async () => {
  const result = await submitTranscriptInChatGPTPage({...PAYLOAD, fileName: "video.mp4"});
  assert.equal(result.ok, false);
  assert.match(result.error, /Only TXT transcripts/);
});

test("ChatGPT page helper rejects an empty summary prompt", async () => {
  const result = await submitTranscriptInChatGPTPage({...PAYLOAD, prompt: " "});
  assert.equal(result.ok, false);
  assert.match(result.error, /summary prompt/);
});

test("ChatGPT MAIN-world helper remains standalone after Chrome serialization", async () => {
  const serialized = vm.runInNewContext(`(${submitTranscriptInChatGPTPage.toString()})`);
  const result = await serialized({...PAYLOAD, fileName: "video.mp4"});

  assert.equal(result.ok, false);
  assert.match(result.error, /Only TXT transcripts/);
});

test("ChatGPT MAIN-world helper attaches the exact UTF-8 TXT bytes", async () => {
  const run = await runPageSubmission({autoSend: false});

  assert.deepEqual(run.result, {ok: true, attached: true, sent: false});
  assert.equal(run.attachedFile.name, "transcript.txt");
  assert.equal(run.attachedFile.type, "text/plain");
  assert.deepEqual(Buffer.from(run.attachedFile.parts[0]), Buffer.from("שלום transcript", "utf8"));
  assert.equal(run.input.files.length, 1);
  assert.equal(run.sendClicks, 0);
  assert.ok(run.inputEvents >= 2);
});

test("ChatGPT MAIN-world helper waits for upload readiness before sending", async () => {
  const run = await runPageSubmission({busyForMs: 150});

  assert.deepEqual(run.result, {ok: true, attached: true, sent: true});
  assert.equal(run.promptWrittenWhileBusy, false);
  assert.equal(run.sendClicks, 1);
});
