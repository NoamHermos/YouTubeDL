async function submitTranscriptInChatGPTPage(payload) {
  const COMPOSER_SELECTOR = "#prompt-textarea, [contenteditable='true'][role='textbox']";
  const FILE_INPUT_SELECTOR = "#upload-files, input[type='file']:not([accept='image/*'])";
  const SEND_BUTTON_SELECTORS = [
    "button[data-testid='send-button']",
    "button[aria-label='Send prompt']",
    "button[aria-label='Send message']",
    "button[aria-label='שלח']",
    "form button[type='submit']",
  ];
  const ATTACHMENT_BUSY_SELECTOR = [
    "[aria-busy='true']",
    "[role='progressbar']",
    "[data-state='loading']",
    "[data-state='pending']",
    "[data-testid*='progress']",
    "[data-testid*='loading']",
    "[data-testid*='spinner']",
  ].join(", ");

  function waitFor(check, timeoutMs = 30000, intervalMs = 200) {
    const deadline = Date.now() + timeoutMs;
    return new Promise((resolve, reject) => {
      const attempt = () => {
        let value;
        try {
          value = check();
        } catch {
          value = null;
        }
        if (value) {
          resolve(value);
          return;
        }
        if (Date.now() >= deadline) {
          reject(new Error("Timed out waiting for ChatGPT."));
          return;
        }
        window.setTimeout(attempt, intervalMs);
      };
      attempt();
    });
  }

  function validatePayload(value) {
    if (!value || typeof value.fileBase64 !== "string" || !value.fileBase64) {
      throw new Error("The TXT file data is missing.");
    }
    const fileName = String(value.fileName || "transcript.txt").split(/[\\/]/).pop();
    if (!fileName.toLowerCase().endsWith(".txt")) {
      throw new Error("Only TXT transcripts can be sent automatically.");
    }
    const prompt = String(value.prompt || "").trim();
    if (!prompt) {
      throw new Error("The summary prompt is missing.");
    }
    return {fileName, prompt};
  }

  function decodeBase64(value) {
    const binary = atob(value);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return bytes;
  }

  function attachFile(input, file) {
    const transfer = new DataTransfer();
    transfer.items.add(file);
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "files")?.set;
    if (setter) {
      setter.call(input, transfer.files);
    } else {
      input.files = transfer.files;
    }
    if (input.files?.length !== 1 || input.files[0]?.name !== file.name) {
      throw new Error("ChatGPT did not accept the TXT file selection.");
    }
    input.dispatchEvent(new Event("input", {bubbles: true, composed: true}));
    input.dispatchEvent(new Event("change", {bubbles: true, composed: true}));
  }

  function composerRoot(composer) {
    return composer.closest?.("form")
      || composer.parentElement?.parentElement?.parentElement
      || document;
  }

  function elementDescription(element) {
    return [
      element.getAttribute?.("aria-label"),
      element.getAttribute?.("title"),
      element.textContent,
    ].filter(Boolean).join(" ").trim();
  }

  function findAttachmentCard(root, fileName) {
    if (!root?.querySelectorAll) return null;
    const normalizedName = fileName.trim().toLocaleLowerCase();
    const preferred = root.querySelectorAll([
      "[role='group'][aria-label]",
      "[data-testid*='attachment']",
      "[data-testid*='file']",
      "[class*='file-tile']",
    ].join(", "));
    for (const element of preferred) {
      if (elementDescription(element).toLocaleLowerCase().includes(normalizedName)) {
        return element;
      }
    }

    const fallback = root.querySelectorAll("[aria-label], [title], div, span, p");
    for (let index = fallback.length - 1; index >= 0; index -= 1) {
      const element = fallback[index];
      if (elementDescription(element).toLocaleLowerCase().includes(normalizedName)) {
        return element.closest?.("[role='group'], [class*='file-tile']") || element;
      }
    }
    return null;
  }

  function attachmentIsReady(card) {
    if (!card) return false;
    if (card.matches?.(ATTACHMENT_BUSY_SELECTOR)
        || card.querySelector?.(ATTACHMENT_BUSY_SELECTOR)) {
      return false;
    }
    const stateText = elementDescription(card).toLocaleLowerCase();
    return !/(uploading|processing|מעלה|מעבד)/u.test(stateText);
  }

  async function waitForAttachmentReady(composer, fileName, timeoutMs = 45000) {
    const root = composerRoot(composer);
    let readySince = 0;
    try {
      return await waitFor(() => {
        const card = findAttachmentCard(root, fileName);
        if (!attachmentIsReady(card)) {
          readySince = 0;
          return null;
        }
        if (!readySince) {
          readySince = Date.now();
          return null;
        }
        return Date.now() - readySince >= 500 ? card : null;
      }, timeoutMs, 100);
    } catch {
      throw new Error("ChatGPT did not finish attaching the TXT file; the prompt was not sent.");
    }
  }

  function composerText(composer) {
    return (composer.innerText || composer.textContent || "").trim();
  }

  function writePrompt(composer, prompt) {
    if (composerText(composer)) {
      throw new Error("The new ChatGPT chat already contains an unsent draft.");
    }
    composer.focus();
    const selection = window.getSelection?.();
    if (selection && document.createRange) {
      const range = document.createRange();
      range.selectNodeContents(composer);
      selection.removeAllRanges();
      selection.addRange(range);
    }
    const inserted = typeof document.execCommand === "function"
      && document.execCommand("insertText", false, prompt);
    if (!inserted) {
      composer.textContent = prompt;
      composer.dispatchEvent(new InputEvent("input", {
        bubbles: true,
        composed: true,
        data: prompt,
        inputType: "insertText",
      }));
    }
  }

  function findSendButton() {
    for (const selector of SEND_BUTTON_SELECTORS) {
      const button = document.querySelector(selector);
      if (button && !button.disabled) {
        return button;
      }
    }
    return null;
  }

  try {
    const {fileName, prompt} = validatePayload(payload);
    const composer = await waitFor(() => document.querySelector(COMPOSER_SELECTOR));
    const input = await waitFor(() => document.querySelector(FILE_INPUT_SELECTOR));
    const bytes = decodeBase64(payload.fileBase64);
    const file = new File([bytes], fileName, {type: payload.mimeType || "text/plain"});

    // This function is injected into the page's MAIN world. Creating File,
    // DataTransfer, and the events here keeps them in ChatGPT's own realm.
    attachFile(input, file);
    await waitForAttachmentReady(composer, fileName);

    if (payload.autoSend === false) {
      return {ok: true, attached: true, sent: false};
    }

    writePrompt(composer, prompt);
    await waitFor(() => composerText(composer).includes(prompt), 5000);

    const root = composerRoot(composer);
    const sendButton = await waitFor(() => {
      if (!attachmentIsReady(findAttachmentCard(root, fileName))) {
        return null;
      }
      return findSendButton();
    }, 45000, 250);
    sendButton.click();
    await waitFor(() => !composerText(composer), 10000, 200);
    return {ok: true, attached: true, sent: true};
  } catch (error) {
    return {ok: false, error: error?.message || "ChatGPT attachment failed."};
  }
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {submitTranscriptInChatGPTPage};
}
