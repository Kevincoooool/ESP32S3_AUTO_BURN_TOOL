import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { open, save } from "@tauri-apps/plugin-dialog";
import {
  AppConfig,
  BAUD_RATES,
  DEFAULT_CONFIG,
  FLASH_FREQS,
  FLASH_MODES,
  FlashCompleteEvent,
  FlashLogEvent,
  FlashRecord,
  FirmwareItem,
  PortsChangedEvent,
} from "./types";

const SLOT_COUNT = 8;

let config: AppConfig = structuredClone(DEFAULT_CONFIG);
let availablePorts: string[] = [];
let knownPorts = new Set<string>();
let records: FlashRecord[] = [];
let successCount = 0;
let failCount = 0;
let activePortLog = "";
const portLogs = new Map<string, string[]>();

const els = {
  portList: document.getElementById("port-list")!,
  firmwareList: document.getElementById("firmware-list")!,
  baudrate: document.getElementById("baudrate") as HTMLSelectElement,
  flashMode: document.getElementById("flash-mode") as HTMLSelectElement,
  flashFreq: document.getElementById("flash-freq") as HTMLSelectElement,
  eraseFlash: document.getElementById("erase-flash") as HTMLInputElement,
  autoFlash: document.getElementById("auto-flash") as HTMLInputElement,
  mainLog: document.getElementById("main-log")!,
  portLog: document.getElementById("port-log")!,
  portLogTabs: document.getElementById("port-log-tabs")!,
  historyBody: document.getElementById("history-body")!,
  statSuccess: document.getElementById("stat-success")!,
  statFail: document.getElementById("stat-fail")!,
  statTotal: document.getElementById("stat-total")!,
  statusBar: document.getElementById("status-bar")!,
  esptoolInfo: document.getElementById("esptool-info")!,
};

function nowTime(short = false): string {
  const d = new Date();
  if (short) {
    return d.toLocaleTimeString("zh-CN", { hour12: false });
  }
  return d.toLocaleString("zh-CN", { hour12: false });
}

function appendMainLog(message: string) {
  els.mainLog.textContent += `[${nowTime(true)}] ${message}\n`;
  els.mainLog.scrollTop = els.mainLog.scrollHeight;
}

function appendPortLog(port: string, line: string) {
  if (!portLogs.has(port)) {
    portLogs.set(port, []);
  }
  portLogs.get(port)!.push(line);
  renderPortLogTabs();
  if (activePortLog === port || !activePortLog) {
    activePortLog = port;
    renderActivePortLog();
  }
}

function renderPortLogTabs() {
  els.portLogTabs.innerHTML = "";
  for (const port of portLogs.keys()) {
    const btn = document.createElement("button");
    btn.className = `port-tab${port === activePortLog ? " active" : ""}`;
    btn.textContent = port;
    btn.onclick = () => {
      activePortLog = port;
      renderPortLogTabs();
      renderActivePortLog();
    };
    els.portLogTabs.appendChild(btn);
  }
}

function renderActivePortLog() {
  const lines = portLogs.get(activePortLog) ?? [];
  els.portLog.textContent = lines.join("\n");
  els.portLog.scrollTop = els.portLog.scrollHeight;
}

function setStatus(text: string) {
  els.statusBar.textContent = text;
}

function updateStats() {
  els.statSuccess.textContent = String(successCount);
  els.statFail.textContent = String(failCount);
  els.statTotal.textContent = String(records.length);
}

function fillSelect(select: HTMLSelectElement, values: string[], selected?: string | number) {
  select.innerHTML = "";
  for (const value of values) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = value;
    select.appendChild(opt);
  }
  if (selected !== undefined) {
    select.value = String(selected);
  }
}

async function persistConfig() {
  readConfigFromUi();
  await invoke("set_config", { config });
}

function readConfigFromUi() {
  config.baudrate = Number(els.baudrate.value);
  config.flashMode = els.flashMode.value;
  config.flashFreq = els.flashFreq.value;
  config.eraseFlash = els.eraseFlash.checked;
  config.autoFlash = els.autoFlash.checked;

  const portSelects = els.portList.querySelectorAll<HTMLSelectElement>("select[data-port-index]");
  const portChecks = els.portList.querySelectorAll<HTMLInputElement>("input[data-port-enable]");
  portSelects.forEach((_sel, i) => {
    config.portEnables[i] = portChecks[i]?.checked ?? true;
  });

  const fwPaths = els.firmwareList.querySelectorAll<HTMLInputElement>("input[data-fw-path]");
  const fwAddrs = els.firmwareList.querySelectorAll<HTMLInputElement>("input[data-fw-addr]");
  const fwEnables = els.firmwareList.querySelectorAll<HTMLInputElement>("input[data-fw-enable]");
  fwPaths.forEach((input, i) => {
    config.firmwarePaths[i] = input.value;
    config.firmwareAddresses[i] = fwAddrs[i]?.value ?? "0x0";
    config.firmwareEnables[i] = fwEnables[i]?.checked ?? false;
  });
}

function applyConfigToUi() {
  fillSelect(els.baudrate, BAUD_RATES, String(config.baudrate));
  fillSelect(els.flashMode, FLASH_MODES, config.flashMode);
  fillSelect(els.flashFreq, FLASH_FREQS, config.flashFreq);
  els.eraseFlash.checked = config.eraseFlash;
  els.autoFlash.checked = config.autoFlash;
  renderPortRows();
  renderFirmwareRows();
}

function renderPortRows() {
  els.portList.innerHTML = "";
  for (let i = 0; i < SLOT_COUNT; i++) {
    const row = document.createElement("div");
    row.className = "slot-row";

    const enable = document.createElement("input");
    enable.type = "checkbox";
    enable.checked = config.portEnables[i] ?? true;
    enable.dataset.portEnable = "1";
    enable.onchange = () => void persistConfig();

    const label = document.createElement("label");
    label.className = "index";
    label.textContent = `#${i + 1}`;

    const select = document.createElement("select");
    select.dataset.portIndex = String(i);
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = "(未选择)";
    select.appendChild(empty);
    for (const port of availablePorts) {
      const opt = document.createElement("option");
      opt.value = port;
      opt.textContent = port;
      select.appendChild(opt);
    }
    const preferred = availablePorts[i] ?? "";
    select.value = preferred;
    select.onchange = () => void persistConfig();

    const flashBtn = document.createElement("button");
    flashBtn.className = "btn secondary small flash-btn";
    flashBtn.textContent = "烧录";
    flashBtn.onclick = () => void flashPort(i);

    const eraseBtn = document.createElement("button");
    eraseBtn.className = "btn secondary small";
    eraseBtn.textContent = "擦除";
    eraseBtn.onclick = () => void erasePort(i);

    row.append(enable, label, select, flashBtn, eraseBtn);
    els.portList.appendChild(row);
  }
}

function renderFirmwareRows() {
  els.firmwareList.innerHTML = "";
  for (let i = 0; i < SLOT_COUNT; i++) {
    const row = document.createElement("div");
    row.className = "slot-row firmware-row";

    const enable = document.createElement("input");
    enable.type = "checkbox";
    enable.checked = config.firmwareEnables[i] ?? false;
    enable.dataset.fwEnable = "1";
    enable.onchange = () => void persistConfig();

    const label = document.createElement("label");
    label.className = "index";
    label.textContent = `#${i + 1}`;

    const addr = document.createElement("input");
    addr.type = "text";
    addr.value = config.firmwareAddresses[i] ?? "0x0";
    addr.dataset.fwAddr = "1";
    addr.onchange = () => void persistConfig();

    const path = document.createElement("input");
    path.type = "text";
    path.value = config.firmwarePaths[i] ?? "";
    path.dataset.fwPath = "1";
    path.placeholder = "固件路径";
    path.onchange = () => void persistConfig();

    const browse = document.createElement("button");
    browse.className = "btn secondary small";
    browse.textContent = "浏览";
    browse.onclick = () => void browseFirmware(i);

    row.append(enable, label, addr, path, browse);
    els.firmwareList.appendChild(row);
  }
}

async function browseFirmware(index: number) {
  const selected = await open({
    multiple: false,
    filters: [{ name: "Binary", extensions: ["bin"] }],
  });
  if (!selected) return;
  config.firmwarePaths[index] = selected;
  config.firmwareEnables[index] = true;
  renderFirmwareRows();
  await persistConfig();
}

function getSelectedPorts(): string[] {
  readConfigFromUi();
  const ports: string[] = [];
  const selects = els.portList.querySelectorAll<HTMLSelectElement>("select[data-port-index]");
  const enables = els.portList.querySelectorAll<HTMLInputElement>("input[data-port-enable]");
  selects.forEach((sel, i) => {
    if (enables[i]?.checked && sel.value) {
      ports.push(sel.value);
    }
  });
  return ports;
}

function getSelectedFirmwares(): FirmwareItem[] {
  readConfigFromUi();
  const items: FirmwareItem[] = [];
  for (let i = 0; i < SLOT_COUNT; i++) {
    if (config.firmwareEnables[i] && config.firmwarePaths[i]) {
      items.push({
        path: config.firmwarePaths[i],
        address: config.firmwareAddresses[i] || "0x0",
      });
    }
  }
  return items;
}

async function refreshPorts() {
  availablePorts = await invoke<string[]>("list_ports");
  renderPortRows();
  appendMainLog(`刷新串口列表: ${availablePorts.join(", ") || "(无)"}`);
}

async function startFlash(ports?: string[]) {
  readConfigFromUi();
  const targetPorts = ports ?? getSelectedPorts();
  const firmwares = getSelectedFirmwares();
  if (!targetPorts.length) {
    appendMainLog("错误: 请选择并启用至少一个串口");
    return;
  }
  if (!firmwares.length) {
    appendMainLog("错误: 请选择至少一个固件");
    return;
  }
  setStatus("烧录中...");
  appendMainLog(`开始烧录: ${targetPorts.join(", ")}`);
  await invoke("start_flash", {
    ports: targetPorts,
    firmwares,
    config,
  });
}

async function flashPort(index: number) {
  readConfigFromUi();
  const select = els.portList.querySelectorAll<HTMLSelectElement>("select[data-port-index]")[index];
  const port = select?.value;
  if (!port) {
    appendMainLog(`错误: 端口 #${index + 1} 未选择串口`);
    return;
  }
  const firmwares = getSelectedFirmwares();
  if (!firmwares.length) {
    appendMainLog("错误: 请选择至少一个固件");
    return;
  }
  setStatus("烧录中...");
  appendMainLog(`开始单独烧录 ${port}...`);
  await invoke("start_flash", {
    ports: [port],
    firmwares,
    config,
  });
}

async function erasePort(index: number) {
  readConfigFromUi();
  const select = els.portList.querySelectorAll<HTMLSelectElement>("select[data-port-index]")[index];
  const port = select?.value;
  if (!port) {
    appendMainLog(`错误: 端口 #${index + 1} 未选择串口`);
    return;
  }
  appendMainLog(`开始擦除 ${port}...`);
  await invoke("erase_single_port", { port, baudrate: config.baudrate });
}

function addRecord(event: FlashCompleteEvent) {
  if (event.chipType === "Erase") {
    appendMainLog(event.success ? `${event.port} 擦除完成` : `${event.port} 擦除失败: ${event.errorMsg}`);
    return;
  }

  const record: FlashRecord = {
    time: nowTime(),
    port: event.port,
    chipType: event.chipType,
    macAddress: event.macAddress,
    success: event.success,
    errorMsg: event.errorMsg,
  };
  records.unshift(record);
  if (event.success) successCount += 1;
  else failCount += 1;
  updateStats();

  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td>${nowTime(true)}</td>
    <td>${record.port}</td>
    <td>${record.macAddress}</td>
    <td>${record.chipType}</td>
    <td class="${record.success ? "status-ok" : "status-fail"}">${record.success ? "成功" : "失败"}</td>
  `;
  els.historyBody.prepend(tr);

  appendMainLog(
    `${event.port} ${record.chipType} ${record.macAddress} - ${record.success ? "成功" : "失败"}`
  );
  setStatus(record.success ? "完成" : "错误");
}

async function exportRecords() {
  if (!records.length) {
    appendMainLog("暂无烧录记录");
    return;
  }
  const path = await save({
    defaultPath: `烧录记录_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "")}.csv`,
    filters: [{ name: "CSV", extensions: ["csv"] }],
  });
  if (!path) return;

  await invoke("export_records", { path, records });
  appendMainLog(`记录已导出到: ${path}`);
}

function clearRecords() {
  if (!records.length) {
    appendMainLog("暂无烧录记录");
    return;
  }
  records = [];
  successCount = 0;
  failCount = 0;
  els.historyBody.innerHTML = "";
  updateStats();
  appendMainLog("已清空所有烧录记录");
}

async function handleAutoFlash(newPorts: string[]) {
  if (!config.autoFlash) return;
  const inserted = newPorts.filter((p) => !knownPorts.has(p));
  if (!inserted.length) return;

  appendMainLog(`检测到新端口: ${inserted.join(", ")}，1 秒后自动烧录...`);
  setTimeout(() => void startFlash(inserted), 1000);
}

async function init() {
  fillSelect(els.baudrate, BAUD_RATES);
  fillSelect(els.flashMode, FLASH_MODES);
  fillSelect(els.flashFreq, FLASH_FREQS);

  try {
    config = await invoke<AppConfig>("get_config");
  } catch {
    config = structuredClone(DEFAULT_CONFIG);
  }
  applyConfigToUi();
  await refreshPorts();
  knownPorts = new Set(availablePorts);

  try {
    const esptool = await invoke<string>("check_esptool");
    els.esptoolInfo.textContent = `esptool: ${esptool}`;
  } catch (e) {
    els.esptoolInfo.textContent = String(e);
    appendMainLog(String(e));
  }

  await listen<FlashLogEvent>("flash-log", (event) => {
    appendPortLog(event.payload.port, event.payload.line);
    if (event.payload.line.includes("错误") || event.payload.line.includes("失败")) {
      appendMainLog(`[${event.payload.port}] ${event.payload.line}`);
    }
  });

  await listen<FlashCompleteEvent>("flash-complete", (event) => {
    addRecord(event.payload);
  });

  await listen<PortsChangedEvent>("ports-changed", async (event) => {
    const ports = event.payload.ports;
    await handleAutoFlash(ports);
    availablePorts = ports;
    renderPortRows();
    knownPorts = new Set(ports);
  });

  document.getElementById("btn-refresh-ports")!.onclick = () => void refreshPorts();
  document.getElementById("btn-start-flash")!.onclick = () => void startFlash();
  document.getElementById("btn-stop-all")!.onclick = () => void invoke("stop_flash", { port: null });
  document.getElementById("btn-clear-log")!.onclick = () => {
    els.mainLog.textContent = "";
    setStatus("就绪");
  };
  document.getElementById("btn-export")!.onclick = () => void exportRecords();
  document.getElementById("btn-clear-records")!.onclick = () => clearRecords();

  els.baudrate.onchange = () => void persistConfig();
  els.flashMode.onchange = () => void persistConfig();
  els.flashFreq.onchange = () => void persistConfig();
  els.eraseFlash.onchange = () => void persistConfig();
  els.autoFlash.onchange = () => void persistConfig();

  appendMainLog("Tauri 版 ESP32 烧录工具已启动");
  setStatus("就绪");
}

window.addEventListener("DOMContentLoaded", () => {
  void init();
});
