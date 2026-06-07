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
    const selectAllFilesButton = document.querySelector("#select-all-files");
    const clearSelectionButton = document.querySelector("#clear-selection");
    const deleteSelectedFilesButton = document.querySelector("#delete-selected-files");
    const deleteAllFilesButton = document.querySelector("#delete-all-files");
    const workersStorageKey = "youtubeDownloaderWorkers";
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
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.className = "file-checkbox";
        checkbox.dataset.fileId = file.id;
        checkbox.title = "Select file";
        const link = document.createElement("a");
        link.href = file.url;
        link.download = file.name.split("/").pop();
        link.textContent = file.name;
        const size = document.createElement("span");
        size.className = "muted";
        size.textContent = file.size;
        const modified = document.createElement("span");
        modified.className = "muted";
        modified.textContent = file.modified;
        row.append(checkbox, link, size, modified);
        filesEl.appendChild(row);
      }
    }

    function applySavedPreferences() {
      const savedWorkers = localStorage.getItem(workersStorageKey);
      if (savedWorkers && form.elements.workers.querySelector(`option[value="${CSS.escape(savedWorkers)}"]`)) {
        form.elements.workers.value = savedWorkers;
      }
    }

    function saveWorkersPreference() {
      localStorage.setItem(workersStorageKey, form.elements.workers.value);
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
        saveWorkersPreference();
      }
      if (withSubtitles !== null) {
        form.elements.with_subtitles.checked = ["1", "true", "yes", "on"].includes(withSubtitles.toLowerCase());
      }
      return action;
    }

    function downloadFile(file) {
      const url = file.url || `/files/${encodeURIComponent(file.name)}`;
      const link = document.createElement("a");
      link.href = url;
      link.download = (file.name || "download").split("/").pop();
      document.body.appendChild(link);
      link.click();
      link.remove();
    }

    async function deleteFiles(fileIds) {
      const res = await fetch("/api/files/delete", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ids: fileIds})
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || "Could not delete files");
      }
      return data;
    }

    function selectedFileIds() {
      return Array.from(document.querySelectorAll(".file-checkbox:checked"))
        .map((checkbox) => checkbox.dataset.fileId)
        .filter(Boolean);
    }

    async function deleteSelectedFiles() {
      const ids = selectedFileIds();
      if (!ids.length) {
        alert("Select at least one file first.");
        return;
      }
      if (!confirm(`Delete ${ids.length} selected file(s)?`)) {
        return;
      }
      await deleteFiles(ids);
      await refreshFiles();
    }

    async function deleteAllFiles() {
      if (!confirm("Delete all listed download files?")) {
        return;
      }
      await deleteFiles(["*"]);
      await refreshFiles();
    }

    function renderJobActions(job) {
      currentOutput = job.outputs && job.outputs.length ? job.outputs[0] : null;
      jobActions.hidden = !(job.status === "finished" && currentOutput);
      if (!currentOutput) return;
      openOutputButton.textContent = "Download File";
      openOutputButton.title = currentOutput.name;
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
    form.elements.workers.addEventListener("change", saveWorkersPreference);
    loadFormatsButton.addEventListener("click", loadQualities);
    openOutputButton.addEventListener("click", async () => {
      if (!currentOutput) return;
      openOutputButton.disabled = true;
      try {
        downloadFile(currentOutput);
      } finally {
        openOutputButton.disabled = false;
      }
    });
    selectAllFilesButton.addEventListener("click", () => {
      document.querySelectorAll(".file-checkbox").forEach((checkbox) => {
        checkbox.checked = true;
      });
    });
    clearSelectionButton.addEventListener("click", () => {
      document.querySelectorAll(".file-checkbox").forEach((checkbox) => {
        checkbox.checked = false;
      });
    });
    deleteSelectedFilesButton.addEventListener("click", async () => {
      deleteSelectedFilesButton.disabled = true;
      try {
        await deleteSelectedFiles();
      } catch (error) {
        alert(error.message);
      } finally {
        deleteSelectedFilesButton.disabled = false;
      }
    });
    deleteAllFilesButton.addEventListener("click", async () => {
      deleteAllFilesButton.disabled = true;
      try {
        await deleteAllFiles();
      } catch (error) {
        alert(error.message);
      } finally {
        deleteAllFilesButton.disabled = false;
      }
    });
    applySavedPreferences();
    const startupAction = applyUrlParams();
    updateQualityVisibility();
    refreshFiles();
    if (startupAction === "fetch_qualities") {
      window.setTimeout(loadQualities, 250);
    } else if (startupAction === "start") {
      window.setTimeout(startJobFromForm, 250);
    }
