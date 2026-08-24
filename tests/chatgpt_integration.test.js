const assert = require("node:assert/strict");
const test = require("node:test");

const {
  attachmentIsReady,
  decodeBase64,
  findAttachmentCard,
  submitTranscript,
  validatePayload,
  waitForAttachmentReady,
} = require("../youtube-extension/chatgpt.js");

test("ChatGPT payload keeps only a safe TXT filename and the requested prompt", () => {
  const payload = validatePayload({
    fileBase64: Buffer.from("transcript", "utf8").toString("base64"),
    fileName: "job/output/video transcript.txt",
    prompt: "  סכם את הסרטון  ",
  });

  assert.deepEqual(payload, {
    fileName: "video transcript.txt",
    prompt: "סכם את הסרטון",
  });
});

test("ChatGPT payload rejects non-TXT files", () => {
  assert.throws(() => validatePayload({
    fileBase64: "dGVzdA==",
    fileName: "video.mp4",
    prompt: "סכם את הסרטון",
  }), /Only TXT transcripts/);
});

test("ChatGPT payload decodes UTF-8 transcript bytes without changing them", () => {
  const source = Buffer.from("שלום transcript", "utf8");
  const decoded = decodeBase64(source.toString("base64"));
  assert.deepEqual(Buffer.from(decoded), source);
});

test("ChatGPT attachment helper requires the matching composer file tile", () => {
  const readyCard = {
    getAttribute(name) {
      return name === "aria-label" ? "transcript.txt" : null;
    },
    matches() { return false; },
    querySelector() { return null; },
    textContent: "transcript.txt Document",
  };
  const unrelatedCard = {
    ...readyCard,
    getAttribute(name) {
      return name === "aria-label" ? "older.txt" : null;
    },
    textContent: "older.txt Document",
  };
  const root = {
    querySelectorAll() { return [unrelatedCard, readyCard]; },
  };

  assert.equal(findAttachmentCard(root, "transcript.txt"), readyCard);
  assert.equal(attachmentIsReady(readyCard), true);
});

test("ChatGPT attachment helper waits while the upload is busy", () => {
  const busyCard = {
    getAttribute() { return "transcript.txt"; },
    matches() { return false; },
    querySelector(selector) {
      return selector.includes("progressbar") ? {role: "progressbar"} : null;
    },
    textContent: "transcript.txt Uploading",
  };

  assert.equal(attachmentIsReady(busyCard), false);
});

test("ChatGPT attachment timeout stops before a prompt can be sent", async () => {
  const originalWindow = global.window;
  const root = {querySelectorAll() { return []; }};
  const composer = {closest() { return root; }};
  global.window = {setTimeout};

  try {
    await assert.rejects(
      waitForAttachmentReady(composer, "transcript.txt", 20),
      /prompt was not sent/,
    );
  } finally {
    if (originalWindow === undefined) delete global.window;
    else global.window = originalWindow;
  }
});

test("ChatGPT page helper attaches the TXT, writes the prompt, and clicks Send", async () => {
  const originalGlobals = {
    DataTransfer: global.DataTransfer,
    Event: global.Event,
    File: global.File,
    HTMLInputElement: global.HTMLInputElement,
    InputEvent: global.InputEvent,
    document: global.document,
    window: global.window,
  };
  let sendClicks = 0;
  let inputEvents = 0;
  let attachedFile = null;
  let attachmentVisible = false;

  class MockInput {
    set files(value) {
      this._files = value;
    }
    get files() {
      return this._files || [];
    }
    dispatchEvent(event) {
      inputEvents += 1;
      if (event.type === "change") attachmentVisible = true;
    }
  }
  const input = new MockInput();
  const attachment = {
    isConnected: true,
    getAttribute(name) {
      return name === "aria-label" ? "transcript.txt" : null;
    },
    matches() { return false; },
    querySelector() { return null; },
    textContent: "transcript.txt Document",
  };
  const form = {
    querySelectorAll() {
      return attachmentVisible ? [attachment] : [];
    },
  };
  const composer = {
    textContent: "",
    get innerText() { return this.textContent; },
    closest(selector) { return selector === "form" ? form : null; },
    dispatchEvent() { inputEvents += 1; },
    focus() {},
  };
  const sendButton = {
    disabled: false,
    click() {
      sendClicks += 1;
      composer.textContent = "";
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

    const result = await submitTranscript({
      fileBase64: Buffer.from("transcript", "utf8").toString("base64"),
      fileName: "transcript.txt",
      mimeType: "text/plain",
      prompt: "סכם את הסרטון",
    });

    assert.deepEqual(result, {ok: true});
    assert.equal(attachedFile.name, "transcript.txt");
    assert.equal(attachedFile.type, "text/plain");
    assert.equal(input.files.length, 1);
    assert.equal(sendClicks, 1);
    assert.ok(inputEvents >= 3);
  } finally {
    for (const [name, value] of Object.entries(originalGlobals)) {
      if (value === undefined) delete global[name];
      else global[name] = value;
    }
  }
});
