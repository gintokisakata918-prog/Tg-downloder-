/* ClipNest frontend — no framework, no build step. */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const els = {
    form: $("link-form"),
    url: $("url"),
    checkBtn: $("check-btn"),
    error: $("error"),
    result: $("result"),
    thumb: $("thumb"),
    thumbFallback: $("thumb-fallback"),
    title: $("title"),
    sub: $("sub"),
    quality: $("quality"),
    startBtn: $("start-btn"),
    progressWrap: $("progress-wrap"),
    barFill: $("bar-fill"),
    statusText: $("status-text"),
    percent: $("percent"),
    saveLink: $("save-link"),
    cancelBtn: $("cancel-btn"),
    engineNote: $("engine-note"),
  };

  let currentUrl = null;
  let currentJob = null;
  let pollTimer = null;

  function setError(message) {
    if (!message) {
      els.error.hidden = true;
      els.error.textContent = "";
      return;
    }
    els.error.hidden = false;
    els.error.textContent = message;
  }

  function errorMessage(detail, fallback) {
    if (typeof detail === "string" && detail.trim()) return detail;
    if (Array.isArray(detail) && detail.length) {
      return detail.map((item) => item.msg || "Invalid input").join(", ");
    }
    return fallback;
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (response.status === 204) return null;
    let data = null;
    try {
      data = await response.json();
    } catch {
      data = null;
    }
    if (!response.ok) {
      throw new Error(errorMessage(data && data.detail, "Kuch galat ho gaya."));
    }
    return data;
  }

  function formatSize(bytes) {
    if (!bytes) return "";
    const units = ["B", "KB", "MB", "GB"];
    let value = bytes;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
      value /= 1024;
      unit += 1;
    }
    return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
  }

  function formatSpeed(bytesPerSecond) {
    return bytesPerSecond ? `${formatSize(bytesPerSecond)}/s` : "";
  }

  function formatEta(seconds) {
    if (!seconds || seconds < 0) return "";
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const minutes = Math.floor(seconds / 60);
    const rest = Math.round(seconds % 60);
    return `${minutes}m ${rest}s`;
  }

  function formatDuration(seconds) {
    if (!seconds) return "";
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    const pad = (n) => String(n).padStart(2, "0");
    return hours ? `${hours}:${pad(minutes)}:${pad(secs)}` : `${minutes}:${pad(secs)}`;
  }

  function stopPolling() {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  function resetProgress() {
    stopPolling();
    currentJob = null;
    els.progressWrap.hidden = true;
    els.barFill.style.width = "0%";
    els.percent.textContent = "0%";
    els.statusText.textContent = "Taiyari ho rahi hai…";
    els.saveLink.hidden = true;
    els.saveLink.removeAttribute("href");
    els.cancelBtn.hidden = true;
  }

  function clearResult() {
    resetProgress();
    els.result.hidden = true;
    els.quality.replaceChildren();
    currentUrl = null;
    els.thumb.hidden = true;
    els.thumb.removeAttribute("src");
    els.thumbFallback.hidden = false;
  }

  function buildQualityOptions(info) {
    const options = [];
    const hasVideo = info.formats.some((format) => format.kind === "video");

    info.formats
      .filter((format) => format.kind === "video")
      .forEach((format) => {
        const size = format.filesize ? ` · ${formatSize(format.filesize)}` : "";
        options.push({ value: format.id, label: `${format.label}${size}`, height: format.height });
      });

    if (info.audio_available) {
      options.push({
        value: "audio",
        label: hasVideo ? "Audio only (MP3)" : "Audio (best)",
        height: 0,
      });
    }

    if (!options.length) {
      options.push({ value: "best", label: "Best available", height: 0 });
    }

    els.quality.replaceChildren(
      ...options.map((option) => {
        const node = document.createElement("option");
        node.value = option.value;
        node.textContent = option.label;
        return node;
      })
    );

    const preferred = options.find((option) => option.height && option.height <= 1080);
    els.quality.value = (preferred || options[0]).value;
  }

  function renderInfo(info, url) {
    currentUrl = url;
    els.title.textContent = info.title || "Untitled";
    const bits = [];
    if (info.uploader) bits.push(info.uploader);
    if (info.duration) bits.push(formatDuration(info.duration));
    bits.push(info.engine);
    els.sub.textContent = bits.join(" · ");

    if (info.thumbnail) {
      els.thumb.src = info.thumbnail;
      els.thumb.hidden = false;
      els.thumbFallback.hidden = true;
    } else {
      els.thumb.hidden = true;
      els.thumbFallback.hidden = false;
    }

    buildQualityOptions(info);
    els.result.hidden = false;
    els.startBtn.disabled = false;
    els.engineNote.textContent = `Engine: ${info.engine}`;
  }

  async function checkLink(event) {
    event.preventDefault();
    const url = els.url.value.trim();
    if (!url) return;

    setError("");
    clearResult();
    els.checkBtn.disabled = true;
    els.checkBtn.textContent = "Check ho raha hai…";

    try {
      const info = await api("/api/info", {
        method: "POST",
        body: JSON.stringify({ url }),
      });
      renderInfo(info, url);
    } catch (error) {
      setError(error.message);
    } finally {
      els.checkBtn.disabled = false;
      els.checkBtn.textContent = "Check karo";
    }
  }

  function updateProgress(job) {
    const percent = Math.max(0, Math.min(100, job.progress || 0));
    els.barFill.style.width = `${percent}%`;
    els.percent.textContent = job.status === "finished" ? "100%" : `${percent.toFixed(0)}%`;

    if (job.status === "finished") {
      els.statusText.textContent = job.filesize
        ? `Ho gaya · ${formatSize(job.filesize)}`
        : "Ho gaya";
      return;
    }
    if (job.status === "failed") {
      els.statusText.textContent = job.error || "Download fail hua.";
      return;
    }
    if (job.status === "cancelled") {
      els.statusText.textContent = "Cancel ho gaya.";
      return;
    }

    const details = [];
    const speed = formatSpeed(job.speed);
    const eta = formatEta(job.eta);
    if (speed) details.push(speed);
    if (eta) details.push(`${eta} baaki`);
    els.statusText.textContent =
      job.status === "queued"
        ? "Queue mein hai…"
        : details.length
          ? `Download ho raha hai · ${details.join(" · ")}`
          : "Download ho raha hai…";
  }

  async function pollJob() {
    if (!currentJob) return;
    try {
      const job = await api(`/api/jobs/${currentJob}`);
      updateProgress(job);

      if (job.status === "finished") {
        stopPolling();
        els.saveLink.href = job.download_url;
        els.saveLink.download = job.filename || "";
        els.saveLink.hidden = false;
        els.cancelBtn.hidden = true;
        els.startBtn.disabled = false;
        return;
      }

      if (job.status === "failed") {
        stopPolling();
        setError(job.error || "Download fail hua.");
        els.cancelBtn.hidden = true;
        els.startBtn.disabled = false;
        return;
      }

      if (job.status === "cancelled") {
        stopPolling();
        els.cancelBtn.hidden = true;
        els.startBtn.disabled = false;
        return;
      }

      pollTimer = setTimeout(pollJob, 1200);
    } catch (error) {
      stopPolling();
      setError(error.message);
      els.cancelBtn.hidden = true;
      els.startBtn.disabled = false;
    }
  }

  async function startDownload() {
    if (!currentUrl) return;
    const choice = els.quality.value;
    const audioOnly = choice === "audio";

    setError("");
    resetProgress();
    els.startBtn.disabled = true;
    els.startBtn.textContent = "Shuru ho raha hai…";
    els.progressWrap.hidden = false;
    els.statusText.textContent = "Job ban raha hai…";

    try {
      const job = await api("/api/download", {
        method: "POST",
        body: JSON.stringify({
          url: currentUrl,
          format_id: audioOnly || choice === "best" ? null : choice,
          audio_only: audioOnly,
        }),
      });
      currentJob = job.id;
      els.cancelBtn.hidden = false;
      updateProgress(job);
      pollJob();
    } catch (error) {
      setError(error.message);
      els.progressWrap.hidden = true;
      els.startBtn.disabled = false;
    } finally {
      els.startBtn.textContent = "Download shuru karo";
    }
  }

  async function cancelDownload() {
    if (!currentJob) return;
    els.cancelBtn.disabled = true;
    try {
      await api(`/api/jobs/${currentJob}/cancel`, { method: "POST" });
      els.statusText.textContent = "Cancel kar diya.";
    } catch (error) {
      setError(error.message);
    } finally {
      els.cancelBtn.disabled = false;
    }
  }

  els.form.addEventListener("submit", checkLink);
  els.startBtn.addEventListener("click", startDownload);
  els.cancelBtn.addEventListener("click", cancelDownload);
  els.url.addEventListener("input", () => {
    if (currentUrl && els.url.value.trim() !== currentUrl) clearResult();
  });
  window.addEventListener("beforeunload", stopPolling);
})();
