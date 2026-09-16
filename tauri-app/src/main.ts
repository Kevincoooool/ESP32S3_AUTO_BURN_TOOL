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
  FlashArgsImport,
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
let busyPortCount = 0;
const portLogs = new Map<string, string[]>();
const flashingPorts = new Set<string>();

interface PortProgressState {
  percent: number;
  indeterminate: boolean;
  label: string;
  visible: boolean;
}

const portProgressState = new Map<string, PortProgressState>();

function parseFlashProgress(line: string): number | null {
  const match = line.match(/(\d+(?:\.\d+)?)\s*%/);
  if (!match) return null;
  return Math.min(100, Math.max(0, parseFloat(match[1])));
}

function parseFlashStage(line: string): string | null {
  if (/writing at|write_flash|write-flash/i.test(line)) return "写入中";
  if (/erasing|erase.flash|erase_flash/i.test(line)) return "擦除中";
  if (/connecting|detecting chip|uploading stub|running stub|changing baud/i.test(line)) return "连接中";
  if (/hash of data verified|hard resetting|烧录完成|所有固件/i.test(line)) return "完成";
  return null;
}

function findPortSlotByPort(port: string): HTMLElement | null {
  for (const slot of els.portList.querySelectorAll<HTMLElement>(".port-slot")) {
    const sel = slot.querySelector<HTMLSelectElement>("select[data-port-index]");
    if (sel?.value === port) return slot;
  }
  return null;
}

function applyPortProgressUi(port: string) {
  const state = portProgressState.get(port);
  const slot = findPortSlotByPort(port);
  if (!slot) return;

  const bar = slot.querySelector<HTMLElement>(".port-progress");
  const fill = slot.querySelector<HTMLElement>(".port-progress-fill");
  const text = slot.querySelector<HTMLElement>(".port-progress-text");
  const stage = slot.querySelector<HTMLElement>(".port-progress-stage");
  if (!bar || !fill || !text || !stage) return;

  if (!state?.visible) {
    bar.classList.remove("active", "indeterminate", "done", "failed");
    fill.style.width = "0%";
    text.textContent = "";
    stage.textContent = "";
    return;
  }

  bar.classList.add("active");
  bar.classList.toggle("indeterminate", state.indeterminate);
  bar.classList.toggle("done", !state.indeterminate && state.percent >= 100);
  stage.textContent = state.label;

  if (state.indeterminate) {
    text.textContent = "…";
    fill.style.width = "35%";
  } else {
    fill.style.width = `${state.percent}%`;
    text.textContent = `${state.percent.toFixed(1)}%`;
  }
}

function setPortProgress(
  port: string,
  update: Partial<PortProgressState> & { visible?: boolean }
) {
  const prev = portProgressState.get(port) ?? {
    percent: 0,
    indeterminate: true,
    label: "准备中",
    visible: true,
  };
  portProgressState.set(port, { ...prev, ...update, visible: update.visible ?? true });
  applyPortProgressUi(port);
}

function hidePortProgress(port: string, delayMs = 0) {
  const hide = () => {
    portProgressState.delete(port);
    applyPortProgressUi(port);
  };
  if (delayMs > 0) {
    window.setTimeout(hide, delayMs);
  } else {
    hide();
  }
}

function syncAllPortProgress() {
  for (const port of portProgressState.keys()) {
    applyPortProgressUi(port);
  }
}

function handlePortLogProgress(port: string, line: string) {
  if (!flashingPorts.has(port)) return;

  const stage = parseFlashStage(line);
  const percent = parseFlashProgress(line);

  if (percent !== null) {
    setPortProgress(port, {
      percent,
      indeterminate: false,
      label: stage ?? "写入中",
      visible: true,
    });
    return;
  }

  if (stage) {
    if (stage === "完成") {
      setPortProgress(port, { percent: 100, indeterminate: false, label: "完成", visible: true });
      return;
    }
    setPortProgress(port, { indeterminate: true, label: stage, visible: true });
  }
}

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
  historyEmpty: document.getElementById("history-empty")!,
  statSuccess: document.getElementById("stat-success")!,
  statFail: document.getElementById("stat-fail")!,
  statTotal: document.getElementById("stat-total")!,
  statusBar: document.getElementById("status-bar")!,
  statusDot: document.getElementById("status-dot")!,
  esptoolInfo: document.getElementById("esptool-info")!,
};

function nowTime(short = false): string {
  const d = new Date();
  if (short) {
    return d.toLocaleTimeString("zh-CN", { hour12: false });
  }
  return d.toLocaleString("zh-CN", { hour12: false });
}

function basename(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

function logLevel(message: string): string {
  if (/错误|失败|Error/i.test(message)) return "error";
  if (/警告|Warning/i.test(message)) return "warning";
  if (/成功|完成|✅/i.test(message)) return "success";
  return "info";
}

function appendMainLog(message: string) {
  const line = document.createElement("div");
  line.className = `log-line ${logLevel(message)}`;
  line.innerHTML = `<span class="ts">[${nowTime(true)}]</span>${message}`;
  els.mainLog.appendChild(line);
  els.mainLog.scrollTop = els.mainLog.scrollHeight;
}

function appendPortLogLine(text: string): HTMLElement {
  const line = document.createElement("div");
  line.className = `log-line ${logLevel(text)}`;
  line.textContent = text;
  return line;
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
  if (portLogs.size === 0) {
    const ph = document.createElement("span");
    ph.className = "tab-placeholder";
    ph.textContent = "烧录开始后显示";
    els.portLogTabs.appendChild(ph);
    return;
  }
  for (const port of portLogs.keys()) {
    const btn = document.createElement("button");
    const flashing = flashingPorts.has(port);
    btn.className = `port-tab${port === activePortLog ? " active" : ""}${flashing ? " flashing" : ""}`;
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
  els.portLog.innerHTML = "";
  const lines = portLogs.get(activePortLog) ?? [];
  if (!lines.length) {
    els.portLog.innerHTML = '<div class="log-line info">等待日志输出...</div>';
    return;
  }
  for (const text of lines) {
    els.portLog.appendChild(appendPortLogLine(text));
  }
  els.portLog.scrollTop = els.portLog.scrollHeight;
}

function setStatus(text: string, state: "ready" | "busy" | "error" = "ready") {
  els.statusBar.textContent = text;
  els.statusDot.className = `status-dot ${state}`;
}

function updateBusyState() {
  if (busyPortCount > 0) {
    setStatus(`烧录中 (${busyPortCount} 路)...`, "busy");
  } else {
    setStatus("就绪", "ready");
  }
  updatePortRowStates();
}

function updatePortRowStates() {
  const rows = els.portList.querySelectorAll<HTMLElement>(".port-row");
  rows.forEach((row) => {
    const select = row.querySelector<HTMLSelectElement>("select[data-port-index]");
    const port = select?.value ?? "";
    row.classList.toggle("flashing", !!port && flashingPorts.has(port));
  });
}

function markPortBusy(ports: string[]) {
  for (const p of ports) {
    flashingPorts.add(p);
    setPortProgress(p, { percent: 0, indeterminate: true, label: "准备中", visible: true });
  }
  busyPortCount += ports.length;
  updateBusyState();
}

function markPortDone(port: string, success: boolean, isErase = false) {
  flashingPorts.delete(port);
  busyPortCount = Math.max(0, busyPortCount - 1);
  updateBusyState();

  if (success && !isErase) {
    setPortProgress(port, { percent: 100, indeterminate: false, label: "完成", visible: true });
    hidePortProgress(port, 1500);
  } else if (!success) {
    const slot = findPortSlotByPort(port);
    slot?.querySelector(".port-progress")?.classList.add("failed");
    setPortProgress(port, {
      percent: portProgressState.get(port)?.percent ?? 0,
      indeterminate: false,
      label: "失败",
      visible: true,
    });
    hidePortProgress(port, 2000);
  } else {
    hidePortProgress(port);
  }
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

  const portChecks = els.portList.querySelectorAll<HTMLInputElement>("input[data-port-enable]");
  portChecks.forEach((chk, i) => {
    config.portEnables[i] = chk.checked;
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
    const portForSlot = availablePorts[i] ?? "";

    const slot = document.createElement("div");
    slot.className = "port-slot";

    const row = document.createElement("div");
    row.className = "slot-row port-row";

    const enable = document.createElement("input");
    enable.type = "checkbox";
    enable.checked = config.portEnables[i] ?? true;
    enable.dataset.portEnable = "1";
    enable.title = "批量烧录时启用";
    enable.onchange = () => void persistConfig();

    const label = document.createElement("label");
    label.className = "index";
    label.textContent = `${i + 1}`;

    const select = document.createElement("select");
    select.dataset.portIndex = String(i);
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = "未选择";
    select.appendChild(empty);
    if (portForSlot) {
      const opt = document.createElement("option");
      opt.value = portForSlot;
      opt.textContent = portForSlot;
      select.appendChild(opt);
      select.value = portForSlot;
    }
    select.onchange = () => void persistConfig();

    const flashBtn = document.createElement("button");
    flashBtn.className = "btn small flash-btn";
    flashBtn.textContent = "烧录";
    flashBtn.onclick = () => void flashPort(i);

    const eraseBtn = document.createElement("button");
    eraseBtn.className = "btn ghost small erase-btn";
    eraseBtn.textContent = "擦除";
    eraseBtn.onclick = () => void erasePort(i);

    const monitorBtn = document.createElement("button");
    monitorBtn.className = "btn ghost small monitor-btn";
    monitorBtn.textContent = "查看串口";
    monitorBtn.onclick = () => void openSerialMonitor(i);

    row.append(enable, label, select, flashBtn, eraseBtn, monitorBtn);

    const progress = document.createElement("div");
    progress.className = "port-progress";
    progress.innerHTML = `
      <span class="port-progress-stage"></span>
      <div class="port-progress-track">
        <div class="port-progress-fill"></div>
      </div>
      <span class="port-progress-text"></span>
    `;

    slot.append(row, progress);
    els.portList.appendChild(slot);
  }
  updatePortRowStates();
  syncAllPortProgress();
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
    label.textContent = `${i + 1}`;

    const addr = document.createElement("input");
    addr.type = "text";
    addr.value = config.firmwareAddresses[i] ?? "0x0";
    addr.dataset.fwAddr = "1";
    addr.onchange = () => void persistConfig();
    addr.oninput = () => void persistConfig();

    const fullPath = config.firmwarePaths[i] ?? "";
    const path = document.createElement("input");
    path.type = "text";
    path.value = fullPath;
    path.dataset.fwPath = "1";
    path.placeholder = "选择 .bin 固件";
    path.title = fullPath;
    path.onchange = () => void persistConfig();
    path.oninput = () => {
      path.title = path.value;
    };

    const browse = document.createElement("button");
    browse.className = "btn ghost small";
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
  appendMainLog(`已选择固件 #${index + 1}: ${basename(selected)}`);
}

async function importFlashArgs() {
  const selected = await open({
    multiple: false,
    filters: [{ name: "IDF flash_args", extensions: ["", "txt"] }],
    title: "选择 build/flash_args 文件",
  });
  if (!selected || typeof selected !== "string") return;

  try {
    const result = await invoke<FlashArgsImport>("parse_flash_args", {
      flashArgsPath: selected,
    });
    if (result.entries.length > SLOT_COUNT) {
      appendMainLog(
        `警告: flash_args 含 ${result.entries.length} 项，仅导入前 ${SLOT_COUNT} 项`
      );
    }

    config.firmwarePaths = Array(SLOT_COUNT).fill("");
    config.firmwareAddresses = Array(SLOT_COUNT).fill("0x0");
    config.firmwareEnables = Array(SLOT_COUNT).fill(false);

    result.entries.slice(0, SLOT_COUNT).forEach((entry, i) => {
      config.firmwarePaths[i] = entry.path;
      config.firmwareAddresses[i] = entry.address;
      config.firmwareEnables[i] = true;
    });

    if (result.flashMode && FLASH_MODES.includes(result.flashMode)) {
      config.flashMode = result.flashMode;
    }
    if (result.flashFreq && FLASH_FREQS.includes(result.flashFreq)) {
      config.flashFreq = result.flashFreq;
    }

    applyConfigToUi();
    await persistConfig();

    const names = result.entries
      .slice(0, SLOT_COUNT)
      .map((e) => `${e.address} ${basename(e.path)}`)
      .join(", ");
    appendMainLog(`已从 IDF 导入 ${Math.min(result.entries.length, SLOT_COUNT)} 项: ${names}`);
    appendMainLog("提示: ESP-IDF 工程需烧录 bootloader + 分区表 + app，单独烧 0x0 无法启动");
  } catch (e) {
    appendMainLog(`导入 flash_args 失败: ${e}`);
  }
}

function warnIfIncompleteFlashPlan(firmwares: FirmwareItem[]) {
  if (firmwares.length === 1 && /^0x0+$/i.test(firmwares[0].address.trim())) {
    appendMainLog(
      "警告: 仅烧录单个固件到 0x0，设备可能无法启动。请用「导入 IDF」加载 build/flash_args"
    );
  }
}

function getSelectedPorts(): string[] {
  readConfigFromUi();
  const ports: string[] = [];
  const seen = new Set<string>();
  const selects = els.portList.querySelectorAll<HTMLSelectElement>("select[data-port-index]");
  const enables = els.portList.querySelectorAll<HTMLInputElement>("input[data-port-enable]");
  selects.forEach((sel, i) => {
    if (enables[i]?.checked && sel.value && !seen.has(sel.value)) {
      seen.add(sel.value);
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

async function refreshPorts(log = true) {
  availablePorts = await invoke<string[]>("list_ports");
  renderPortRows();
  if (log) {
    appendMainLog(`刷新串口: ${availablePorts.join(", ") || "无"}`);
  }
}

async function startFlash(ports?: string[]) {
  readConfigFromUi();
  const targetPorts = [...new Set(ports ?? getSelectedPorts())];
  const firmwares = getSelectedFirmwares();
  if (!targetPorts.length) {
    appendMainLog("错误: 请选择并启用至少一个串口");
    return;
  }
  if (!firmwares.length) {
    appendMainLog("错误: 请选择至少一个固件");
    return;
  }
  warnIfIncompleteFlashPlan(firmwares);
  markPortBusy(targetPorts);
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
  warnIfIncompleteFlashPlan(firmwares);
  markPortBusy([port]);
  appendMainLog(`单独烧录 ${port}...`);
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
  appendMainLog(`擦除 ${port}...`);
  markPortBusy([port]);
  setPortProgress(port, { indeterminate: true, label: "擦除中", visible: true });
  await invoke("erase_single_port", { port, baudrate: config.baudrate });
}

const MONITOR_BAUD = 115200;

async function openSerialMonitor(index: number) {
  readConfigFromUi();
  const select = els.portList.querySelectorAll<HTMLSelectElement>("select[data-port-index]")[index];
  const port = select?.value;
  if (!port) {
    appendMainLog(`错误: 端口 #${index + 1} 未选择串口`);
    return;
  }
  if (flashingPorts.has(port)) {
    appendMainLog(`端口 ${port} 正在烧录，请稍后再查看串口`);
    return;
  }

  try {
    await invoke("open_serial_monitor_window", { port, baudrate: MONITOR_BAUD });
    appendMainLog(`已打开串口监视: ${port}`);
  } catch (e) {
    appendMainLog(`打开串口监视失败 (${port}): ${e}`);
  }
}

function hideHistoryEmpty() {
  els.historyEmpty?.remove();
}

function addRecord(event: FlashCompleteEvent) {
  const isErase = event.chipType === "Erase";
  const isCancelled = event.errorMsg === "cancelled";

  if (isCancelled) {
    markPortDone(event.port, false, false);
    setPortProgress(event.port, { indeterminate: false, label: "已停止", visible: true });
    hidePortProgress(event.port, 1500);
    appendMainLog(`${event.port} 烧录已停止，串口已释放`);
    if (busyPortCount === 0) {
      setStatus("就绪", "ready");
    }
    return;
  }

  markPortDone(event.port, event.success, isErase);

  if (isErase) {
    appendMainLog(event.success ? `${event.port} 擦除完成` : `${event.port} 擦除失败: ${event.errorMsg}`);
    return;
  }

  hideHistoryEmpty();

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
    <td><span class="status-badge ${record.success ? "ok" : "fail"}">${record.success ? "成功" : "失败"}</span></td>
  `;
  els.historyBody.prepend(tr);

  appendMainLog(
    `${event.port} · ${record.chipType} · ${record.macAddress} — ${record.success ? "成功" : "失败"}`
  );
  if (!event.success && event.errorMsg) {
    appendPortLog(event.port, `错误: ${event.errorMsg}`);
  }
  if (!event.success) {
    setStatus("存在失败", "error");
  } else if (busyPortCount === 0) {
    setStatus("完成", "ready");
  }
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
  appendMainLog(`记录已导出: ${path}`);
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
  const empty = document.createElement("tr");
  empty.id = "history-empty";
  empty.innerHTML = '<td colspan="5" class="empty-cell">暂无记录</td>';
  els.historyBody.appendChild(empty);
  updateStats();
  appendMainLog("已清空烧录记录");
}

async function handleAutoFlash(newPorts: string[]) {
  if (!config.autoFlash) return;
  const inserted = newPorts.filter((p) => !knownPorts.has(p));
  if (!inserted.length) return;

  appendMainLog(`新端口 ${inserted.join(", ")}，1 秒后自动烧录`);
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
    els.esptoolInfo.textContent = esptool;
  } catch (e) {
    els.esptoolInfo.textContent = String(e);
    appendMainLog(String(e));
  }

  await listen<FlashLogEvent>("flash-log", (event) => {
    appendPortLog(event.payload.port, event.payload.line);
    handlePortLogProgress(event.payload.port, event.payload.line);
    if (/错误|失败|Error/i.test(event.payload.line)) {
      appendMainLog(`[${event.payload.port}] ${event.payload.line}`);
    }
  });

  await listen<FlashCompleteEvent>("flash-complete", (event) => {
    addRecord(event.payload);
  });

  await listen<PortsChangedEvent>("ports-changed", async (event) => {
    const prev = availablePorts.join(",");
    const ports = event.payload.ports;
    availablePorts = ports;
    renderPortRows();
    if (ports.join(",") !== prev) {
      appendMainLog(`串口变化: ${ports.join(", ") || "无"}`);
    }
    await handleAutoFlash(ports);
    knownPorts = new Set(ports);
  });

  document.getElementById("btn-import-flash-args")!.onclick = () => void importFlashArgs();
  document.getElementById("btn-refresh-ports")!.onclick = () => void refreshPorts();
  document.getElementById("btn-start-flash")!.onclick = () => void startFlash();
  document.getElementById("btn-stop-all")!.onclick = () => {
    void invoke("stop_flash", { port: null });
    for (const port of flashingPorts) {
      setPortProgress(port, { indeterminate: true, label: "停止中", visible: true });
    }
    appendMainLog("已发送停止全部指令，等待端口释放...");
  };
  document.getElementById("btn-clear-log")!.onclick = () => {
    els.mainLog.innerHTML = "";
    setStatus("就绪", "ready");
  };
  document.getElementById("btn-export")!.onclick = () => void exportRecords();
  document.getElementById("btn-clear-records")!.onclick = () => clearRecords();

  els.baudrate.onchange = () => void persistConfig();
  els.flashMode.onchange = () => void persistConfig();
  els.flashFreq.onchange = () => void persistConfig();
  els.eraseFlash.onchange = () => void persistConfig();
  els.autoFlash.onchange = () => void persistConfig();

  appendMainLog("ESP32 烧录工具已就绪");
  setStatus("就绪", "ready");
}

window.addEventListener("DOMContentLoaded", () => {
  void init();
});
