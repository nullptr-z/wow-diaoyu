const { invoke } = window.__TAURI__.tauri;
const { listen } = window.__TAURI__.event;

const configPathInput = document.getElementById("config-path");
const pythonCmdInput = document.getElementById("python-cmd");
const runOnceInput = document.getElementById("run-once");
const startBtn = document.getElementById("start-btn");
const stopBtn = document.getElementById("stop-btn");
const loadBtn = document.getElementById("load-btn");
const saveBtn = document.getElementById("save-btn");
const devicesBtn = document.getElementById("devices-btn");
const recordBtn = document.getElementById("record-btn");
const captureBtn = document.getElementById("capture-btn");
const pickRegionBtn = document.getElementById("pick-region-btn");
const regionLeftInput = document.getElementById("region-left");
const regionTopInput = document.getElementById("region-top");
const regionWidthInput = document.getElementById("region-width");
const regionHeightInput = document.getElementById("region-height");
const clearLogsBtn = document.getElementById("clear-logs");
const recordSecondsInput = document.getElementById("record-seconds");
const recordOutputInput = document.getElementById("record-output");
const captureSizeInput = document.getElementById("capture-size");
const captureOutputInput = document.getElementById("capture-output");
const captureTimeoutInput = document.getElementById("capture-timeout");
const statusDot = document.getElementById("status-dot");
const statusLabel = document.getElementById("status-label");
const logOutput = document.getElementById("log-output");
const logMeta = document.getElementById("log-meta");
const formInputs = Array.from(document.querySelectorAll("[data-path]"));

const logLines = [];
const settingsKey = "wow-fishing-ui-settings";

function setRunning(running) {
  statusLabel.textContent = running ? "Running" : "Idle";
  statusDot.classList.toggle("active", running);
  startBtn.disabled = running;
  stopBtn.disabled = !running;
  recordBtn.disabled = running;
  captureBtn.disabled = running;
}

function updateLogMeta() {
  logMeta.textContent = `${logLines.length} lines`;
}

function appendLog(line) {
  const time = new Date().toLocaleTimeString();
  logLines.push(`[${time}] ${line}`);
  if (logLines.length > 400) {
    logLines.splice(0, logLines.length - 400);
  }
  logOutput.textContent = logLines.join("\n");
  logOutput.scrollTop = logOutput.scrollHeight;
  updateLogMeta();
}

function appendLogLines(text) {
  if (!text) {
    return;
  }
  text.split(/\r?\n/).forEach((line) => {
    if (line.trim()) {
      appendLog(line);
    }
  });
}

function getByPath(obj, path) {
  return path.split(".").reduce((acc, key) => {
    if (acc && Object.prototype.hasOwnProperty.call(acc, key)) {
      return acc[key];
    }
    return undefined;
  }, obj);
}

function setByPath(obj, path, value) {
  const keys = path.split(".");
  let cursor = obj;
  keys.forEach((key, index) => {
    if (index === keys.length - 1) {
      cursor[key] = value;
      return;
    }
    if (!cursor[key] || typeof cursor[key] !== "object") {
      cursor[key] = {};
    }
    cursor = cursor[key];
  });
}

function setInputValue(input, value) {
  if (input.type === "checkbox") {
    input.checked = Boolean(value);
    return;
  }
  input.value = value ?? "";
}

function getInputValue(input) {
  if (input.type === "checkbox") {
    return input.checked;
  }
  const raw = input.value.trim();
  if (!raw) {
    return input.dataset.nullable ? null : "";
  }
  if (input.dataset.type === "int") {
    return Number.parseInt(raw, 10);
  }
  if (input.dataset.type === "float") {
    return Number.parseFloat(raw);
  }
  return raw;
}

function fillForm(config) {
  formInputs.forEach((input) => {
    setInputValue(input, getByPath(config, input.dataset.path));
  });
}

function readForm() {
  const config = {};
  formInputs.forEach((input) => {
    setByPath(config, input.dataset.path, getInputValue(input));
  });
  return config;
}

function saveSettings() {
  const settings = {
    configPath: configPathInput.value,
    pythonCmd: pythonCmdInput.value,
    runOnce: runOnceInput.checked,
    recordSeconds: recordSecondsInput.value,
    recordOutput: recordOutputInput.value,
    captureSize: captureSizeInput.value,
    captureOutput: captureOutputInput.value,
    captureTimeout: captureTimeoutInput.value,
  };
  localStorage.setItem(settingsKey, JSON.stringify(settings));
}

function loadSettings() {
  const raw = localStorage.getItem(settingsKey);
  if (!raw) {
    return;
  }
  try {
    const settings = JSON.parse(raw);
    if (settings.configPath) {
      configPathInput.value = settings.configPath;
    }
    if (settings.pythonCmd) {
      pythonCmdInput.value = settings.pythonCmd;
    }
    if (typeof settings.runOnce === "boolean") {
      runOnceInput.checked = settings.runOnce;
    }
    if (settings.recordSeconds) {
      recordSecondsInput.value = settings.recordSeconds;
    }
    if (settings.recordOutput) {
      recordOutputInput.value = settings.recordOutput;
    }
    if (settings.captureSize) {
      captureSizeInput.value = settings.captureSize;
    }
    if (settings.captureOutput) {
      captureOutputInput.value = settings.captureOutput;
    }
    if (settings.captureTimeout) {
      captureTimeoutInput.value = settings.captureTimeout;
    }
  } catch (err) {
    appendLog(`settings load failed: ${err}`);
  }
}

async function loadConfig() {
  const path = configPathInput.value.trim();
  if (!path) {
    appendLog("config path is empty");
    return;
  }
  try {
    const config = await invoke("load_config", { path });
    fillForm(config);
    const templatePath = getByPath(config, "vision.template_path");
    if (templatePath) {
      captureOutputInput.value = templatePath;
    }
    appendLog(`loaded ${path}`);
  } catch (err) {
    appendLog(`load failed: ${err}`);
  }
}

async function saveConfig() {
  const path = configPathInput.value.trim();
  if (!path) {
    appendLog("config path is empty");
    return false;
  }
  try {
    const config = readForm();
    await invoke("save_config", { path, config });
    appendLog(`saved ${path}`);
    return true;
  } catch (err) {
    appendLog(`save failed: ${err}`);
    return false;
  }
}

async function startBot() {
  const saved = await saveConfig();
  if (!saved) {
    return;
  }
  try {
    await invoke("start_bot", {
      pythonCmd: pythonCmdInput.value,
      configPath: configPathInput.value,
      once: runOnceInput.checked,
    });
    setRunning(true);
    appendLog("bot started");
  } catch (err) {
    appendLog(`start failed: ${err}`);
  }
}

async function stopBot() {
  try {
    await invoke("stop_bot");
    setRunning(false);
    appendLog("bot stopped");
  } catch (err) {
    appendLog(`stop failed: ${err}`);
  }
}

async function listDevices() {
  try {
    const output = await invoke("list_audio_devices", {
      pythonCmd: pythonCmdInput.value,
    });
    appendLog("audio devices:");
    appendLogLines(output);
  } catch (err) {
    appendLog(`device list failed: ${err}`);
  }
}

async function recordAudio() {
  const saved = await saveConfig();
  if (!saved) {
    return;
  }
  const seconds = Number.parseFloat(recordSecondsInput.value);
  if (!Number.isFinite(seconds) || seconds <= 0) {
    appendLog("record seconds must be > 0");
    return;
  }
  const outputPath = recordOutputInput.value.trim();
  if (!outputPath) {
    appendLog("record output path is empty");
    return;
  }
  appendLog(`recording ${seconds}s to ${outputPath}`);
  try {
    const output = await invoke("record_audio", {
      pythonCmd: pythonCmdInput.value,
      configPath: configPathInput.value,
      seconds,
      outputPath,
    });
    if (output) {
      appendLogLines(output);
    } else {
      appendLog("record complete");
    }
  } catch (err) {
    appendLog(`record failed: ${err}`);
  }
}

async function captureBobber() {
  const saved = await saveConfig();
  if (!saved) {
    return;
  }
  const size = Number.parseInt(captureSizeInput.value, 10);
  if (!Number.isFinite(size) || size <= 0) {
    appendLog("capture size must be > 0");
    return;
  }
  const timeout = Number.parseFloat(captureTimeoutInput.value);
  if (!Number.isFinite(timeout) || timeout <= 0) {
    appendLog("capture timeout must be > 0");
    return;
  }
  const outputPath = captureOutputInput.value.trim();
  if (!outputPath) {
    appendLog("capture output path is empty");
    return;
  }
  const wasRunning = startBtn.disabled;
  captureBtn.disabled = true;
  appendLog(`capture started: click bobber within ${timeout}s`);
  try {
    const output = await invoke("capture_bobber", {
      pythonCmd: pythonCmdInput.value,
      configPath: configPathInput.value,
      size,
      outputPath,
      timeout,
    });
    if (output) {
      appendLogLines(output);
    } else {
      appendLog("capture complete");
    }
  } catch (err) {
    appendLog(`capture failed: ${err}`);
  } finally {
    captureBtn.disabled = wasRunning;
  }
}

async function pickRegion() {
  const timeout = Number.parseFloat(captureTimeoutInput.value) || 15;
  pickRegionBtn.disabled = true;
  appendLog(`pick region: click TOP-LEFT corner, then BOTTOM-RIGHT corner (${timeout}s per click)`);
  try {
    const output = await invoke("capture_region", {
      pythonCmd: pythonCmdInput.value,
      configPath: configPathInput.value,
      timeout,
    });
    appendLogLines(output);
    // The last line of output is JSON: {"left":..., "top":..., "width":..., "height":...}
    const lines = output.trim().split("\n");
    const jsonLine = lines[lines.length - 1];
    const region = JSON.parse(jsonLine);
    regionLeftInput.value = region.left;
    regionTopInput.value = region.top;
    regionWidthInput.value = region.width;
    regionHeightInput.value = region.height;
    appendLog(`region set: left=${region.left}, top=${region.top}, width=${region.width}, height=${region.height}`);
  } catch (err) {
    appendLog(`pick region failed: ${err}`);
  } finally {
    pickRegionBtn.disabled = false;
  }
}

function bindEvents() {
  loadBtn.addEventListener("click", loadConfig);
  saveBtn.addEventListener("click", saveConfig);
  startBtn.addEventListener("click", startBot);
  stopBtn.addEventListener("click", stopBot);
  devicesBtn.addEventListener("click", listDevices);
  recordBtn.addEventListener("click", recordAudio);
  captureBtn.addEventListener("click", captureBobber);
  pickRegionBtn.addEventListener("click", pickRegion);
  clearLogsBtn.addEventListener("click", () => {
    logLines.length = 0;
    logOutput.textContent = "";
    updateLogMeta();
  });

  [
    configPathInput,
    pythonCmdInput,
    runOnceInput,
    recordSecondsInput,
    recordOutputInput,
    captureSizeInput,
    captureOutputInput,
    captureTimeoutInput,
  ].forEach((input) => {
    input.addEventListener("change", saveSettings);
  });
}

async function init() {
  setRunning(false);
  loadSettings();
  bindEvents();

  await listen("bot-log", (event) => {
    appendLogLines(String(event.payload));
  });

  await listen("bot-exit", (event) => {
    appendLog(`bot exited: ${event.payload}`);
    setRunning(false);
  });

  await loadConfig();
}

init();
