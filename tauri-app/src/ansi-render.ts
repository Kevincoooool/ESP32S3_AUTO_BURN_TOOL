/** ESP-IDF / ANSI SGR 颜色解析，流式增量渲染 */

const ANSI_CLASS: Record<number, string> = {
  30: "ansi-black",
  31: "ansi-red",
  32: "ansi-green",
  33: "ansi-yellow",
  34: "ansi-blue",
  35: "ansi-magenta",
  36: "ansi-cyan",
  37: "ansi-white",
  90: "ansi-bright-black",
  91: "ansi-bright-red",
  92: "ansi-bright-green",
  93: "ansi-bright-yellow",
  94: "ansi-bright-blue",
  95: "ansi-bright-magenta",
  96: "ansi-bright-cyan",
  97: "ansi-bright-white",
};

const CSI_PATTERN = /\x1b\[[0-9;?]*[a-zA-Z]/g;
const SGR_PATTERN = /\x1b\[([0-9;]*)m/g;

export function stripAnsi(text: string): string {
  return text.replace(CSI_PATTERN, "");
}

function normalizeSerialText(text: string): string {
  return text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

function isIncompleteEscape(tail: string): boolean {
  if (!tail.startsWith("\x1b")) return false;
  if (tail.length === 1) return true;
  if (tail.startsWith("\x1b[")) {
    return !/[a-zA-Z]/.test(tail.slice(2));
  }
  return false;
}

function codesToClass(codes: number[]): string {
  const classes: string[] = [];

  for (const code of codes) {
    if (code === 0) {
      classes.length = 0;
      continue;
    }
    if (code === 1) {
      classes.push("ansi-bold");
      continue;
    }
    if (code === 2) {
      classes.push("ansi-dim");
      continue;
    }
    if (code === 22) {
      const idx = classes.indexOf("ansi-bold");
      if (idx >= 0) classes.splice(idx, 1);
      continue;
    }
    if (ANSI_CLASS[code]) {
      classes.push(ANSI_CLASS[code]);
    }
  }

  return classes.join(" ");
}

export class AnsiStreamRenderer {
  private pending = "";
  private currentClass = "";
  private lastSpan: HTMLSpanElement | null = null;
  private lastText: Text | null = null;

  reset() {
    this.pending = "";
    this.currentClass = "";
    this.lastSpan = null;
    this.lastText = null;
  }

  renderAll(text: string, container: HTMLElement) {
    container.innerHTML = "";
    this.reset();
    this.append(text, container);
  }

  append(text: string, container: HTMLElement) {
    let input = normalizeSerialText(this.pending + text);
    this.pending = "";

    const escIdx = input.lastIndexOf("\x1b");
    if (escIdx >= 0) {
      const tail = input.slice(escIdx);
      if (isIncompleteEscape(tail)) {
        this.pending = tail;
        input = input.slice(0, escIdx);
      }
    }

    let lastIndex = 0;
    let match: RegExpExecArray | null;
    SGR_PATTERN.lastIndex = 0;

    while ((match = SGR_PATTERN.exec(input)) !== null) {
      this.writePlain(container, input.slice(lastIndex, match.index));
      const codes = match[1]
        ? match[1].split(";").filter(Boolean).map((n) => Number.parseInt(n, 10))
        : [0];
      this.currentClass = codesToClass(codes);
      lastIndex = match.index + match[0].length;
    }

    let rest = input.slice(lastIndex);
    rest = rest.replace(CSI_PATTERN, "");
    this.writePlain(container, rest);
  }

  private writePlain(container: HTMLElement, text: string) {
    if (!text) return;
    if (this.currentClass) {
      if (
        this.lastSpan &&
        this.lastSpan.className === this.currentClass &&
        this.lastSpan.parentNode === container
      ) {
        this.lastSpan.textContent = (this.lastSpan.textContent ?? "") + text;
        return;
      }
      const span = document.createElement("span");
      span.className = this.currentClass;
      span.textContent = text;
      container.appendChild(span);
      this.lastSpan = span;
      this.lastText = null;
      return;
    }

    if (this.lastText && this.lastText.parentNode === container) {
      this.lastText.textContent = (this.lastText.textContent ?? "") + text;
      return;
    }
    const node = document.createTextNode(text);
    container.appendChild(node);
    this.lastText = node;
    this.lastSpan = null;
  }
}
