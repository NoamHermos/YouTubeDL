const form = document.querySelector("#job-form");
    const logEl = document.querySelector("#log");
    const jobTitle = document.querySelector("#job-title");
    const cancelButton = document.querySelector("#cancel-job");
    const filesEl = document.querySelector("#files");
    const fileCount = document.querySelector("#file-count");
    const qualityBox = document.querySelector("#quality-box");
    const withSubtitlesBox = document.querySelector("#with-subtitles-box");
    const formatSelect = document.querySelector("#format-id");
    const formatStatus = document.querySelector("#format-status");
    const loadFormatsButton = document.querySelector("#load-formats");
    const jobActions = document.querySelector("#job-actions");
    const openOutputButton = document.querySelector("#open-output");
    const openOutputLocationButton = document.querySelector("#open-output-location");
    const copyOutputButton = document.querySelector("#copy-output");
    let currentJobId = null;
    let currentOutput = null;
    let pollTimer = null;

    function setLog(text) {
      logEl.textContent = text || "";
      logEl.scrollTop = logEl.scrollHeight;
    }

    async function refreshFiles() {
      const res = await fetch("/api/files");
      const data = await res.json();
      fileCount.textContent = `${data.files.length} files`;
      filesEl.innerHTML = "";
      if (!data.files.length) {
        filesEl.innerHTML = '<div class="muted">No downloads yet.</div>';
        return;
      }
      for (const file of data.files) {
        const row = document.createElement("div");
        row.className = "file-row";
        const link = document.createElement("a");
        link.href = "#";
        link.textContent = file.name;
        link.addEventListener("click", async (event) => {
          event.preventDefault();
          try {
            await openFile(file);
          } catch (error) {
            alert(error.message);
          }
        });
        const size = document.createElement("span");
        size.className = "muted";
        size.textContent = file.size;
        const modified = document.createElement("span");
        modified.className = "muted";
        modified.textContent = file.modified;
        const locationButton = document.createElement("button");
        locationButton.type = "button";
        locationButton.className = "secondary";
        locationButton.textContent = "Location";
        locationButton.addEventListener("click", async () => {
          locationButton.disabled = true;
          try {
            await openFileLocation(file);
          } catch (error) {
            alert(error.message);
          } finally {
            locationButton.disabled = false;
          }
        });
        row.append(link, size, modified, locationButton);
        filesEl.appendChild(row);
      }
    }

    function updateQualityVisibility() {
      const downloadType = form.elements.download_type.value;
      qualityBox.hidden = downloadType !== "video";
      withSubtitlesBox.hidden = !["video", "audio"].includes(downloadType);
    }

    function applyUrlParams() {
      const params = new URLSearchParams(window.location.search);
      const url = params.get("url");
      const type = params.get("type") || params.get("download_type");
      const source = params.get("source");
      const range = params.get("range");
      const workers = params.get("workers");
      const withSubtitles = params.get("with_subtitles");
      const action = params.get("action") || "";

      if (url) {
        form.elements.url.value = url;
      }
      if (source && form.elements.source.querySelector(`option[value="${CSS.escape(source)}"]`)) {
        form.elements.source.value = source;
      }
      if (type && form.elements.download_type.querySelector(`option[value="${CSS.escape(type)}"]`)) {
        form.elements.download_type.value = type;
      }
      if (range !== null) {
        form.elements.range.value = range;
      }
      if (workers && form.elements.workers.querySelector(`option[value="${CSS.escape(workers)}"]`)) {
        form.elements.workers.value = workers;
      }
      if (withSubtitles !== null) {
        form.elements.with_subtitles.checked = ["1", "true", "yes", "on"].includes(withSubtitles.toLowerCase());
      }
      return action;
    }

    function filePayload(file) {
      if (typeof file === "string") {
        return {name: file};
      }
      return {id: file.id, name: file.name, path: file.path};
    }

    async function openFile(file) {
      const res = await fetch("/api/files/open", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(filePayload(file))
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || "Could not open file");
      }
    }

    async function openFileLocation(file) {
      const res = await fetch("/api/files/open-location", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(filePayload(file))
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || "Could not open file location");
      }
    }

    async function copyFile(file) {
      const res = await fetch("/api/files/copy", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(filePayload(file))
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || "Could not copy file");
      }
    }

    function renderJobActions(job) {
      currentOutput = job.outputs && job.outputs.length ? job.outputs[0] : null;
      jobActions.hidden = !(job.status === "finished" && currentOutput);
      if (!currentOutput) return;
      openOutputButton.textContent = "Open File";
      openOutputButton.title = currentOutput.name;
      openOutputLocationButton.textContent = "Open File Location";
      openOutputLocationButton.title = currentOutput.path || currentOutput.name;
      copyOutputButton.textContent = "Copy File";
      copyOutputButton.title = currentOutput.name;
    }

    async function loadQualities() {
      const url = form.elements.url.value.trim();
      if (!url) {
        formatStatus.textContent = "Enter a URL first.";
        return;
      }

      loadFormatsButton.disabled = true;
      formatStatus.textContent = "Fetching qualities...";
      const payload = {
        url,
        source: form.elements.source.value,
        range: form.elements.range.value
      };

      try {
        const res = await fetch("/api/formats", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!res.ok) {
          formatStatus.textContent = `ERROR: ${data.error || "Could not fetch qualities"}`;
          return;
        }

        formatSelect.innerHTML = "";
        for (const fmt of data.formats) {
          const option = document.createElement("option");
          option.value = fmt.format_id;
          option.textContent = fmt.label;
          formatSelect.appendChild(option);
        }
        formatStatus.textContent = `Loaded ${data.formats.length} qualities from: ${data.title}`;
      } catch (error) {
        formatStatus.textContent = `ERROR: ${error.message}`;
      } finally {
        loadFormatsButton.disabled = false;
      }
    }

    async function startJobFromForm() {
      const data = Object.fromEntries(new FormData(form).entries());
      data.with_subtitles = ["video", "audio"].includes(form.elements.download_type.value) && form.elements.with_subtitles.checked;
      jobActions.hidden = true;
      currentOutput = null;
      setLog("Starting job...\n");
      const res = await fetch("/api/jobs", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(data)
      });
      const payload = await res.json();
      if (!res.ok) {
        setLog(`ERROR: ${payload.error || "Could not start job"}\n`);
        return;
      }
      currentJobId = payload.id;
      cancelButton.hidden = false;
      await pollJob();
      clearInterval(pollTimer);
      pollTimer = setInterval(pollJob, 1200);
    }

    async function pollJob() {
      if (!currentJobId) return;
      const res = await fetch(`/api/jobs/${currentJobId}`);
      const job = await res.json();
      jobTitle.textContent = `${job.status} | ${job.download_type} | ${job.url}`;
      setLog(job.log.join(""));
      renderJobActions(job);
      cancelButton.hidden = job.status !== "running";
      if (job.status !== "running") {
        clearInterval(pollTimer);
        pollTimer = null;
        await refreshFiles();
      }
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      await startJobFromForm();
    });

    cancelButton.addEventListener("click", async () => {
      if (!currentJobId) return;
      await fetch(`/api/jobs/${currentJobId}/cancel`, {method: "POST"});
      await pollJob();
    });

    document.querySelector("#refresh-files").addEventListener("click", refreshFiles);
    form.elements.download_type.addEventListener("change", updateQualityVisibility);
    loadFormatsButton.addEventListener("click", loadQualities);
    openOutputButton.addEventListener("click", async () => {
      if (!currentOutput) return;
      openOutputButton.disabled = true;
      try {
        await openFile(currentOutput);
      } finally {
        openOutputButton.disabled = false;
      }
    });
    openOutputLocationButton.addEventListener("click", async () => {
      if (!currentOutput) return;
      openOutputLocationButton.disabled = true;
      try {
        await openFileLocation(currentOutput);
      } finally {
        openOutputLocationButton.disabled = false;
      }
    });
    copyOutputButton.addEventListener("click", async () => {
      if (!currentOutput) return;
      copyOutputButton.disabled = true;
      const oldText = copyOutputButton.textContent;
      try {
        await copyFile(currentOutput);
        copyOutputButton.textContent = "Copied";
        setTimeout(() => copyOutputButton.textContent = oldText, 1400);
      } catch (error) {
        try {
          await navigator.clipboard.writeText(currentOutput.path || currentOutput.name);
          copyOutputButton.textContent = "Path Copied";
          setTimeout(() => copyOutputButton.textContent = oldText, 1400);
        } finally {
          copyOutputButton.disabled = false;
        }
        return;
      }
      copyOutputButton.disabled = false;
    });
    const startupAction = applyUrlParams();
    updateQualityVisibility();
    refreshFiles();
    if (startupAction === "fetch_qualities") {
      window.setTimeout(loadQualities, 250);
    } else if (startupAction === "start") {
      window.setTimeout(startJobFromForm, 250);
    }
