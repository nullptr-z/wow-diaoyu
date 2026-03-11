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
const captureBlacklistBtn = document.getElementById("capture-blacklist-btn");
const addExtraTemplateBtn = document.getElementById("add-extra-template-btn");
const addBlacklistTemplateBtn = document.getElementById("add-blacklist-template-btn");
const extraTemplatesList = document.getElementById("extra-templates-list");
const blacklistTemplatesList = document.getElementById("blacklist-templates-list");
const blacklistOutputInput = document.getElementById("blacklist-output");
const blacklistSizeInput = document.getElementById("blacklist-size");
const formInputs = Array.from(document.querySelectorAll("[data-path]"));

const logLines = [];
const settingsKey = "wow-fishing-ui-settings";
let sidecarMode = false;

// --- List editor helpers for extra_templates and blacklist_templates ---
function renderListEditor(container, items, onChange) {
  container.innerHTML = "";
  items.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = "list-editor-row";
    const input = document.createElement("input");
    input.type = "text";
    input.value = item;
    input.addEventListener("change", () => {
      items[index] = input.value;
      onChange();
    });
    const removeBtn = document.createElement("button");
    removeBtn.textContent = "\u00d7";
    removeBtn.className = "ghost small";
    removeBtn.addEventListener("click", () => {
      items.splice(index, 1);
      renderListEditor(container, items, onChange);
      onChange();
    });
    row.appendChild(input);
    row.appendChild(removeBtn);
    container.appendChild(row);
  });
}

let extraTemplates = [];
let blacklistTemplates = [];

function setRunning(running) {
  statusLabel.textContent = running ? "运行中" : "空闲";
  statusDot.classList.toggle("active", running);
  startBtn.disabled = running;
  stopBtn.disabled = !running;
  recordBtn.disabled = running;
  captureBtn.disabled = running;
}

function updateLogMeta() {
  logMeta.textContent = `${logLines.length} 行`;
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
  // Fill list editors
  extraTemplates = (getByPath(config, "vision.extra_templates") || []).slice();
  blacklistTemplates = (getByPath(config, "vision.blacklist_templates") || []).slice();
  renderListEditor(extraTemplatesList, extraTemplates, () => {});
  renderListEditor(blacklistTemplatesList, blacklistTemplates, () => {});
}

function readForm() {
  const config = {};
  formInputs.forEach((input) => {
    setByPath(config, input.dataset.path, getInputValue(input));
  });
  // Include list fields
  setByPath(config, "vision.extra_templates", extraTemplates.slice());
  setByPath(config, "vision.blacklist_templates", blacklistTemplates.slice());
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
    appendLog(`设置加载失败: ${err}`);
  }
}

async function loadConfig() {
  const path = configPathInput.value.trim();
  if (!path) {
    appendLog("配置文件路径为空");
    return;
  }
  try {
    const config = await invoke("load_config", { path });
    fillForm(config);
    const templatePath = getByPath(config, "vision.template_path");
    if (templatePath) {
      captureOutputInput.value = templatePath;
    }
    appendLog(`已加载 ${path}`);
  } catch (err) {
    appendLog(`加载失败: ${err}`);
  }
}

async function saveConfig() {
  const path = configPathInput.value.trim();
  if (!path) {
    appendLog("配置文件路径为空");
    return false;
  }
  try {
    const config = readForm();
    await invoke("save_config", { path, config });
    appendLog(`已保存 ${path}`);
    return true;
  } catch (err) {
    appendLog(`保存失败: ${err}`);
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
    appendLog("钓鱼已启动");
  } catch (err) {
    appendLog(`启动失败: ${err}`);
  }
}

async function stopBot() {
  try {
    await invoke("stop_bot");
    setRunning(false);
    appendLog("钓鱼已停止");
  } catch (err) {
    appendLog(`停止失败: ${err}`);
  }
}

async function listDevices() {
  try {
    const output = await invoke("list_audio_devices", {
      pythonCmd: pythonCmdInput.value,
    });
    appendLog("音频设备列表:");
    appendLogLines(output);
  } catch (err) {
    appendLog(`获取设备列表失败: ${err}`);
  }
}

async function recordAudio() {
  const saved = await saveConfig();
  if (!saved) {
    return;
  }
  const seconds = Number.parseFloat(recordSecondsInput.value);
  if (!Number.isFinite(seconds) || seconds <= 0) {
    appendLog("录制时长必须大于 0");
    return;
  }
  const outputPath = recordOutputInput.value.trim();
  if (!outputPath) {
    appendLog("录音保存路径为空");
    return;
  }
  appendLog(`正在录制 ${seconds} 秒到 ${outputPath}`);
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
      appendLog("录制完成");
    }
  } catch (err) {
    appendLog(`录制失败: ${err}`);
  }
}

async function captureBobber() {
  const saved = await saveConfig();
  if (!saved) {
    return;
  }
  const size = Number.parseInt(captureSizeInput.value, 10);
  if (!Number.isFinite(size) || size <= 0) {
    appendLog("截图大小必须大于 0");
    return;
  }
  const timeout = Number.parseFloat(captureTimeoutInput.value);
  if (!Number.isFinite(timeout) || timeout <= 0) {
    appendLog("等待时间必须大于 0");
    return;
  }
  const outputPath = captureOutputInput.value.trim();
  if (!outputPath) {
    appendLog("截图保存路径为空");
    return;
  }
  const wasRunning = startBtn.disabled;
  captureBtn.disabled = true;
  appendLog(`截取鱼漂: 请在 ${timeout} 秒内点击鱼漂`);
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
      appendLog("截取完成");
    }
  } catch (err) {
    appendLog(`截取失败: ${err}`);
  } finally {
    captureBtn.disabled = wasRunning;
  }
}

async function pickRegion() {
  const timeout = Number.parseFloat(captureTimeoutInput.value) || 15;
  pickRegionBtn.disabled = true;
  appendLog(`框选区域: 拖拽鼠标画出搜索范围，松开确认，ESC 取消`);
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
    appendLog(`区域已设置: 左=${region.left}, 上=${region.top}, 宽=${region.width}, 高=${region.height}`);
  } catch (err) {
    appendLog(`框选区域失败: ${err}`);
  } finally {
    pickRegionBtn.disabled = false;
  }
}

async function captureBlacklist() {
  const saved = await saveConfig();
  if (!saved) return;
  const size = Number.parseInt(blacklistSizeInput.value, 10);
  if (!Number.isFinite(size) || size <= 0) {
    appendLog("黑名单截图大小必须大于 0");
    return;
  }
  const timeout = Number.parseFloat(captureTimeoutInput.value);
  if (!Number.isFinite(timeout) || timeout <= 0) {
    appendLog("等待时间必须大于 0");
    return;
  }
  const outputPath = blacklistOutputInput.value.trim();
  if (!outputPath) {
    appendLog("黑名单保存路径为空");
    return;
  }
  captureBlacklistBtn.disabled = true;
  appendLog(`截取黑名单图标: 请在 ${timeout} 秒内点击要排除的图标`);
  try {
    const output = await invoke("capture_blacklist", {
      pythonCmd: pythonCmdInput.value,
      configPath: configPathInput.value,
      size,
      outputPath,
      timeout,
    });
    if (output) appendLogLines(output);
    // Auto-add to blacklist templates list
    if (!blacklistTemplates.includes(outputPath)) {
      blacklistTemplates.push(outputPath);
      renderListEditor(blacklistTemplatesList, blacklistTemplates, () => {});
      appendLog(`已添加 '${outputPath}' 到黑名单模板`);
    }
  } catch (err) {
    appendLog(`黑名单截取失败: ${err}`);
  } finally {
    captureBlacklistBtn.disabled = false;
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
  captureBlacklistBtn.addEventListener("click", captureBlacklist);
  addExtraTemplateBtn.addEventListener("click", () => {
    extraTemplates.push("assets/bobber_angle.png");
    renderListEditor(extraTemplatesList, extraTemplates, () => {});
  });
  addBlacklistTemplateBtn.addEventListener("click", () => {
    blacklistTemplates.push("assets/blacklist_cursor.png");
    renderListEditor(blacklistTemplatesList, blacklistTemplates, () => {});
  });
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

  // Check if sidecar (bundled exe) is available
  try {
    sidecarMode = await invoke("check_sidecar");
  } catch (_) {
    sidecarMode = false;
  }
  if (sidecarMode) {
    const pythonRow = pythonCmdInput.closest(".field-row") || pythonCmdInput.parentElement;
    if (pythonRow) pythonRow.style.display = "none";
    appendLog("已检测到内置引擎，无需配置 Python");
  }

  await listen("bot-log", (event) => {
    appendLogLines(String(event.payload));
  });

  await listen("bot-exit", (event) => {
    appendLog(`钓鱼已退出: ${event.payload}`);
    setRunning(false);
  });

  await loadConfig();
}

init();
