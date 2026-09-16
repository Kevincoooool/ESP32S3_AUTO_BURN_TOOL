import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { save, open as openDialog } from "@tauri-apps/plugin-dialog";
import { SerialDataEvent, SerialClosedEvent, SerialOpenParams } from "./types";
import { AnsiStreamRenderer, stripAnsi } from "./ansi-render";

const params = new URLSearchParams(window.location.search);
const initialPort = params.get("port") ?? "";
const initialBaud = Number(params.get("baud") ?? "115200");

const BAUD_RATES = ["9600", "115200", "230400", "460800", "921600", "1500000", "2000000"];
const DATA_BITS = ["5", "6", "7", "8"];
const STOP_BITS = ["1", "2"];
const PARITY = ["None", "Odd", "Even"];
const MAX_RX_CHARS = 512 * 1024;
const TRIM_TO_CHARS = 384 * 1024;

const els = {
  portSelect: document.getElementById("port-select") as HTMLSelectElement,
  baudrate: document.getElementById("baudrate") as HTMLSelectElement,
  dataBits: document.getElementById("data-bits") as HTMLSelectElement,
  stopBits: document.getElementById("stop-bits") as HTMLSelectElement,
  parity: document.getElementById("parity") as HTMLSelectElement,
  btnToggle: document.getElementById("btn-toggle") as HTMLButtonElement,
  btnRefresh: document.getElementById("btn-refresh") as HTMLButtonElement,
  autoScroll: document.getElementById("auto-scroll") as HTMLInputElement,
  timestamp: document.getElementById("timestamp") as HTMLInputElement,
  hexDisplay: document.getElementById("hex-display") as HTMLInputElement,
  dtr: document.getElementById("dtr") as HTMLInputElement,
  rts: document.getElementById("rts") as HTMLInputElement,
  fontFamily: document.getElementById("font-family") as HTMLSelectElement,
  fontSize: document.getElementById("font-size") as HTMLSelectElement,
  btnSave: document.getElementById("btn-save") as HTMLButtonElement,
  btnClearRx: document.getElementById("btn-clear-rx") as HTMLButtonElement,
  hexSend: document.getElementById("hex-send") as HTMLInputElement,
  appendNewline: document.getElementById("append-newline") as HTMLInputElement,
  lineEnding: document.getElementById("line-ending") as HTMLSelectElement,
  timedSend: document.getElementById("timed-send") as HTMLInputElement,
  timedInterval: document.getElementById("timed-interval") as HTMLInputElement,
  txInput: document.getElementById("tx-input") as HTMLInputElement,
  btnSend: document.getElementById("btn-send") as HTMLButtonElement,
  btnSendFile: document.getElementById("btn-send-file") as HTMLButtonElement,
  btnClearTx: document.getElementById("btn-clear-tx") as HTMLButtonElement,
  rxView: document.getElementById("rx-view") as HTMLDivElement,
  statusDot: document.getElementById("status-dot") as HTMLSpanElement,
  statusText: document.getElementById("status-text") as HTMLSpanElement,
  txCount: document.getElementById("tx-count") as HTMLSpanElement,
  rxCount: document.getElementById("rx-count") as HTMLSpanElement,
  clock: document.getElementById("clock") as HTMLSpanElement,
};

let connected = false;
let txBytes = 0;
let rxBytes = 0;
let rxRawBuffer = "";
const ansiRenderer = new AnsiStreamRenderer();
let utf8Decoder = new TextDecoder("utf-8", { fatal: false });
let rxPendingChunks: Uint8Array[] = [];
let rxFlushScheduled = false;
let sendHistory: string[] = [];
let historyIndex = -1;
let timedTimer: ReturnType<typeof setInterval> | null = null;
let sendChain: Promise<void> = Promise.resolve();
let sending = false;

function fillSelect(select: HTMLSelectElement, options: string[], selected?: string) {
  select.innerHTML = "";
  for (const opt of options) {
    const el = document.createElement("option");
    el.value = opt;
    el.textContent = opt;
    select.appendChild(el);
  }
  if (selected) select.value = selected;
}

function currentPort(): string {
  return els.portSelect.value;
}

function decodeBase64(data: string): Uint8Array {
  const binary = atob(data);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function encodeBase64(bytes: Uint8Array): string {
  if (!bytes.length) return "";
  let binary = "";
  const step = 0x8000;
  for (let i = 0; i < bytes.length; i += step) {
    binary += String.fromCharCode(...bytes.subarray(i, i + step));
  }
  return btoa(binary);
}

function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0").toUpperCase())
    .join(" ");
}

function bytesToText(bytes: Uint8Array): string {
  return utf8Decoder.decode(bytes, { stream: true });
}

function resetUtf8Decoder() {
  utf8Decoder = new TextDecoder("utf-8", { fatal: false });
}

function formatTimestamp(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `[${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}] `;
}

function applyRxFont() {
  els.rxView.style.fontFamily = els.fontFamily.value;
  els.rxView.style.fontSize = `${els.fontSize.value}px`;
}

function trimRxIfNeeded() {
  if (rxRawBuffer.length <= MAX_RX_CHARS) return;
  rxRawBuffer = rxRawBuffer.slice(-TRIM_TO_CHARS);
  rxBytes = Math.min(rxBytes, rxRawBuffer.length);
  els.rxCount.textContent = String(rxBytes);
  if (els.hexDisplay.checked) {
    els.rxView.textContent = rxRawBuffer;
  } else {
    ansiRenderer.renderAll(rxRawBuffer, els.rxView);
  }
}

function flushRxPending() {
  rxFlushScheduled = false;
  if (!rxPendingChunks.length) return;

  const chunks = rxPendingChunks;
  rxPendingChunks = [];

  for (const bytes of chunks) {
    processRxChunk(bytes);
  }
  trimRxIfNeeded();

  if (els.autoScroll.checked) {
    els.rxView.scrollTop = els.rxView.scrollHeight;
  }
}

function queueRxBytes(bytes: Uint8Array) {
  if (!bytes.length) return;
  rxBytes += bytes.length;
  els.rxCount.textContent = String(rxBytes);
  rxPendingChunks.push(bytes);
  if (!rxFlushScheduled) {
    rxFlushScheduled = true;
    requestAnimationFrame(flushRxPending);
  }
}

function processRxChunk(bytes: Uint8Array) {
  if (els.hexDisplay.checked) {
    const chunk = bytesToHex(bytes) + " ";
    rxRawBuffer += chunk;
    if (els.timestamp.checked) {
      const ts = document.createElement("span");
      ts.className = "rx-ts";
      ts.textContent = formatTimestamp();
      els.rxView.appendChild(ts);
    }
    els.rxView.append(document.createTextNode(chunk));
    return;
  }

  const chunk = bytesToText(bytes);
  if (!chunk) return;
  rxRawBuffer += chunk;
  if (els.timestamp.checked) {
    const ts = document.createElement("span");
    ts.className = "rx-ts";
    ts.textContent = formatTimestamp();
    els.rxView.appendChild(ts);
  }
  ansiRenderer.append(chunk, els.rxView);
}

function appendRx(bytes: Uint8Array) {
  queueRxBytes(bytes);
}

function clearRxView() {
  rxRawBuffer = "";
  rxPendingChunks = [];
  rxFlushScheduled = false;
  ansiRenderer.reset();
  resetUtf8Decoder();
  els.rxView.innerHTML = "";
  rxBytes = 0;
  els.rxCount.textContent = "0";
}

function rerenderRxView() {
  const raw = rxRawBuffer;
  clearRxView();
  rxRawBuffer = raw;
  rxBytes = raw.length;
  els.rxCount.textContent = String(rxBytes);
  if (!raw) return;

  if (els.hexDisplay.checked) {
    els.rxView.textContent = raw;
  } else {
    resetUtf8Decoder();
    ansiRenderer.renderAll(raw, els.rxView);
  }
  if (els.autoScroll.checked) {
    els.rxView.scrollTop = els.rxView.scrollHeight;
  }
}

function setConnected(open: boolean) {
  connected = open;
  els.btnToggle.textContent = open ? "关闭串口" : "打开串口";
  els.btnToggle.classList.toggle("connected", open);
  els.statusDot.classList.toggle("connected", open);
  els.statusText.textContent = open ? `已连接 ${currentPort()}` : "未连接";

  const disabled = !open;
  els.dtr.disabled = disabled;
  els.rts.disabled = disabled;
  els.btnSend.disabled = disabled || sending;
  els.btnSendFile.disabled = disabled || sending;
  els.timedSend.disabled = disabled;

  if (!open && timedTimer) {
    clearInterval(timedTimer);
    timedTimer = null;
    els.timedSend.checked = false;
  }
}

function openParams(): SerialOpenParams {
  return {
    port: currentPort(),
    baudrate: Number(els.baudrate.value),
    dataBits: Number(els.dataBits.value),
    stopBits: Number(els.stopBits.value),
    parity: els.parity.value,
    dtr: els.dtr.checked,
    rts: els.rts.checked,
  };
}

async function refreshPorts() {
  const ports = await invoke<string[]>("list_ports");
  const prev = els.portSelect.value;
  els.portSelect.innerHTML = "";
  for (const port of ports) {
    const opt = document.createElement("option");
    opt.value = port;
    opt.textContent = port;
    els.portSelect.appendChild(opt);
  }
  if (initialPort && ports.includes(initialPort)) {
    els.portSelect.value = initialPort;
  } else if (prev && ports.includes(prev)) {
    els.portSelect.value = prev;
  } else if (ports.length) {
    els.portSelect.value = ports[0];
  }
}

async function togglePort() {
  const port = currentPort();
  if (!port) {
    showError("请选择串口");
    return;
  }

  if (connected) {
    try {
      await invoke("serial_monitor_close", { port });
      setConnected(false);
    } catch (e) {
      showError(`关闭失败: ${e}`);
    }
    return;
  }

  els.btnToggle.disabled = true;
  els.statusText.textContent = "正在打开...";
  try {
    await invoke("serial_monitor_open", { params: openParams() });
    setConnected(true);
  } catch (e) {
    showError(`打开失败: ${e}`);
    setConnected(false);
  } finally {
    els.btnToggle.disabled = false;
  }
}

function parseHexInput(text: string): Uint8Array {
  const cleaned = text.replace(/[^0-9a-fA-F]/g, "");
  if (!cleaned || cleaned.length % 2 !== 0) {
    throw new Error("HEX 格式无效");
  }
  const bytes = new Uint8Array(cleaned.length / 2);
  for (let i = 0; i < bytes.length; i++) {
    bytes[i] = parseInt(cleaned.slice(i * 2, i * 2 + 2), 16);
  }
  return bytes;
}

function lineEndingBytes(): Uint8Array {
  switch (els.lineEnding.value) {
    case "lf":
      return new Uint8Array([0x0a]);
    case "cr":
      return new Uint8Array([0x0d]);
    case "crlf":
      return new Uint8Array([0x0d, 0x0a]);
    default:
      return new Uint8Array();
  }
}

function setSending(active: boolean) {
  sending = active;
  els.btnSend.disabled = !connected || active;
  els.btnSendFile.disabled = !connected || active;
}

function enqueueSend(task: () => Promise<void>): Promise<void> {
  sendChain = sendChain
    .then(async () => {
      if (!connected) return;
      setSending(true);
      try {
        await task();
      } finally {
        setSending(false);
      }
    })
    .catch((e) => {
      setSending(false);
      showError(String(e));
    });
  return sendChain;
}

function buildSendPayload(text: string): Uint8Array {
  let payload: Uint8Array;
  if (els.hexSend.checked) {
    payload = parseHexInput(text);
    if (els.appendNewline.checked) {
      const ending = lineEndingBytes();
      const merged = new Uint8Array(payload.length + ending.length);
      merged.set(payload);
      merged.set(ending, payload.length);
      payload = merged;
    }
  } else {
    payload = new TextEncoder().encode(text);
    if (els.appendNewline.checked) {
      const ending = lineEndingBytes();
      const merged = new Uint8Array(payload.length + ending.length);
      merged.set(payload);
      merged.set(ending, payload.length);
      payload = merged;
    }
  }
  return payload;
}

async function sendBytes(data: Uint8Array) {
  if (!connected || !data.length) return;
  const port = currentPort();
  const sent = await invoke<number>("serial_monitor_write", {
    port,
    dataB64: encodeBase64(data),
  });
  txBytes += sent;
  els.txCount.textContent = String(txBytes);
}

async function sendText(text: string) {
  const payload = buildSendPayload(text);
  await sendBytes(payload);
}

async function sendCommand() {
  const text = els.txInput.value;
  if (!text.trim() || sending) return;
  await enqueueSend(async () => {
    await sendText(text);
    if (sendHistory[sendHistory.length - 1] !== text) {
      sendHistory.push(text);
      if (sendHistory.length > 50) sendHistory.shift();
    }
    historyIndex = sendHistory.length;
  });
}

async function espHardwareReset() {
  if (!connected) return;
  await enqueueSend(async () => {
    const port = currentPort();
    await invoke("serial_monitor_pulse_reset", { port });
    await syncLines();
  });
}

async function syncLines() {
  if (!connected) return;
  await invoke("serial_monitor_set_lines", {
    port: currentPort(),
    dtr: els.dtr.checked,
    rts: els.rts.checked,
  });
}

async function saveLog() {
  if (!rxRawBuffer) return;
  const path = await save({
    defaultPath: `串口日志_${currentPort()}_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "")}.txt`,
    filters: [{ name: "Text", extensions: ["txt", "log"] }],
  });
  if (!path) return;
  const content = els.hexDisplay.checked ? rxRawBuffer : stripAnsi(rxRawBuffer);
  await invoke("write_text_file", { path, content });
}

async function sendFile() {
  if (!connected || sending) return;
  const path = await openDialog({ multiple: false });
  if (!path || typeof path !== "string") return;

  await enqueueSend(async () => {
    const dataB64 = await invoke<string>("read_binary_file", { path });
    const bytes = decodeBase64(dataB64);
    if (!bytes.length) {
      showError("文件为空");
      return;
    }
    await sendBytes(bytes);
  });
}

function updateClock() {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  els.clock.textContent = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
}

function setupTimedSend() {
  if (timedTimer) {
    clearInterval(timedTimer);
    timedTimer = null;
  }
  if (!els.timedSend.checked || !connected) return;
  const interval = Math.max(100, Number(els.timedInterval.value) || 1000);
  timedTimer = setInterval(() => {
    void sendCommand();
  }, interval);
}

function showError(message: string) {
  appendRx(new TextEncoder().encode(`${message}\n`));
  els.statusText.textContent = message;
}

async function init() {
  fillSelect(els.baudrate, BAUD_RATES, String(initialBaud));
  fillSelect(els.dataBits, DATA_BITS, "8");
  fillSelect(els.stopBits, STOP_BITS, "1");
  fillSelect(els.parity, PARITY, "None");
  applyRxFont();

  els.btnToggle.onclick = () => void togglePort();
  els.btnRefresh.onclick = () => void refreshPorts();
  els.btnSend.onclick = () => void sendCommand();
  els.btnClearRx.onclick = () => clearRxView();
  els.btnClearTx.onclick = () => {
    els.txInput.value = "";
  };
  els.btnSave.onclick = () => void saveLog();
  els.btnSendFile.onclick = () => void sendFile();
  els.hexDisplay.onchange = () => rerenderRxView();
  els.dtr.onchange = () => void syncLines();
  els.rts.onchange = () => void syncLines();
  els.fontFamily.onchange = applyRxFont;
  els.fontSize.onchange = applyRxFont;
  els.timedSend.onchange = setupTimedSend;
  els.timedInterval.onchange = setupTimedSend;

  setInterval(updateClock, 1000);
  updateClock();
  setConnected(false);

  try {
    await listen<SerialDataEvent>("serial-data", (event) => {
      if (event.payload.port !== currentPort()) return;
      queueRxBytes(decodeBase64(event.payload.data));
    });

    await listen<SerialClosedEvent>("serial-closed", (event) => {
      if (event.payload.port !== currentPort()) return;
      setConnected(false);
    });

    await refreshPorts();
    if (initialPort) {
      els.portSelect.value = initialPort;
    }

    const openOnLoad = params.get("open") === "1";
    if (openOnLoad && initialPort) {
      try {
        await invoke("serial_monitor_open", { params: openParams() });
        setConnected(true);
      } catch (e) {
        showError(`打开失败: ${e}`);
      }
    }
  } catch (e) {
    showError(`初始化失败: ${e}`);
  }

  els.txInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      void sendCommand();
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      if (!sendHistory.length) return;
      historyIndex = Math.max(0, historyIndex - 1);
      els.txInput.value = sendHistory[historyIndex] ?? "";
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!sendHistory.length) return;
      historyIndex = Math.min(sendHistory.length, historyIndex + 1);
      els.txInput.value = sendHistory[historyIndex] ?? "";
    }
  });

  document.querySelectorAll<HTMLButtonElement>(".quick").forEach((btn) => {
    btn.onclick = () => {
      if (btn.dataset.reset === "1") {
        void espHardwareReset();
        return;
      }
      els.txInput.value = btn.dataset.cmd ?? "";
      void sendCommand();
    };
  });
}

window.addEventListener("DOMContentLoaded", () => {
  void init();
});
