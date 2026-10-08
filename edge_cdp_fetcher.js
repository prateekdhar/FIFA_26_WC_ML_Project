const { spawn } = require("node:child_process");
const crypto = require("node:crypto");
const http = require("node:http");
const net = require("node:net");
const readline = require("node:readline");

function argValue(name, fallback = null) {
  const index = process.argv.indexOf(name);
  if (index === -1 || index + 1 >= process.argv.length) return fallback;
  return process.argv[index + 1];
}

const browserPath = argValue("--browser-path");
const profileDir = argValue("--profile-dir");
const port = Number(argValue("--port", "9222"));
const timeoutMs = Number(argValue("--timeout-ms", "60000"));
const debug = process.env.DEBUG_EDGE_CDP === "1";

function logDebug(message) {
  if (debug) console.error(message);
}

if (!browserPath || !profileDir) {
  console.log(JSON.stringify({ status: "error", error: "Missing browser path or profile dir" }));
  process.exit(1);
}

let browserProcess = null;
let ws = null;
let nextId = 1;
const pending = new Map();

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function getJson(path) {
  return new Promise((resolve, reject) => {
    const req = http.get({ host: "127.0.0.1", port, path, timeout: 3000 }, (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (chunk) => {
        body += chunk;
      });
      res.on("end", () => {
        try {
          resolve(JSON.parse(body));
        } catch (error) {
          reject(error);
        }
      });
    });
    req.on("error", reject);
    req.on("timeout", () => {
      req.destroy(new Error("HTTP timeout"));
    });
  });
}

async function waitForPageTarget() {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const targets = await getJson("/json/list");
      const page = targets.find((target) => target.type === "page" && target.webSocketDebuggerUrl);
      if (page) return page.webSocketDebuggerUrl;
    } catch (_) {
      // Edge may still be starting.
    }
    await sleep(500);
  }
  throw new Error("No Edge page target became available");
}

class RawWebSocket {
  constructor(url) {
    this.url = new URL(url);
    this.socket = null;
    this.buffer = Buffer.alloc(0);
    this.handshakeDone = false;
  }

  connect() {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("WebSocket open timeout")), timeoutMs);
      this.socket = net.createConnection(Number(this.url.port), this.url.hostname, () => {
        const key = crypto.randomBytes(16).toString("base64");
        const request = [
          `GET ${this.url.pathname}${this.url.search} HTTP/1.1`,
          `Host: ${this.url.host}`,
          "Upgrade: websocket",
          "Connection: Upgrade",
          "Origin: devtools://devtools",
          `Sec-WebSocket-Key: ${key}`,
          "Sec-WebSocket-Version: 13",
          "",
          "",
        ].join("\r\n");
        this.socket.write(request);
      });
      this.socket.on("data", (chunk) => {
        this.buffer = Buffer.concat([this.buffer, chunk]);
        if (!this.handshakeDone) {
          const marker = this.buffer.indexOf("\r\n\r\n");
          if (marker === -1) return;
          const header = this.buffer.slice(0, marker).toString("utf8");
          this.buffer = this.buffer.slice(marker + 4);
          if (!header.includes(" 101 ")) {
            clearTimeout(timer);
            reject(new Error(header.split("\r\n")[0]));
            return;
          }
          logDebug("websocket handshake complete");
          this.handshakeDone = true;
          clearTimeout(timer);
          resolve(this);
        }
        this.readFrames();
      });
      this.socket.on("error", (error) => {
        clearTimeout(timer);
        reject(error);
      });
    });
  }

  sendFrame(opcode, payloadText) {
    const payload = Buffer.from(payloadText || "", "utf8");
    const length = payload.length;
    const header = [];
    header.push(0x80 | opcode);
    if (length < 126) {
      header.push(0x80 | length);
    } else if (length < 65536) {
      header.push(0x80 | 126, (length >> 8) & 255, length & 255);
    } else {
      header.push(0x80 | 127);
      const lengthBuffer = Buffer.alloc(8);
      lengthBuffer.writeBigUInt64BE(BigInt(length));
      header.push(...lengthBuffer);
    }
    const mask = crypto.randomBytes(4);
    const masked = Buffer.alloc(length);
    for (let i = 0; i < length; i += 1) masked[i] = payload[i] ^ mask[i % 4];
    this.socket.write(Buffer.concat([Buffer.from(header), mask, masked]));
  }

  send(text) {
    this.sendFrame(1, text);
  }

  readFrames() {
    while (this.buffer.length >= 2) {
      const first = this.buffer[0];
      const second = this.buffer[1];
      const opcode = first & 0x0f;
      let length = second & 0x7f;
      let offset = 2;
      if (length === 126) {
        if (this.buffer.length < offset + 2) return;
        length = this.buffer.readUInt16BE(offset);
        offset += 2;
      } else if (length === 127) {
        if (this.buffer.length < offset + 8) return;
        length = Number(this.buffer.readBigUInt64BE(offset));
        offset += 8;
      }
      const masked = Boolean(second & 0x80);
      let mask = null;
      if (masked) {
        if (this.buffer.length < offset + 4) return;
        mask = this.buffer.slice(offset, offset + 4);
        offset += 4;
      }
      if (this.buffer.length < offset + length) return;
      let payload = this.buffer.slice(offset, offset + length);
      this.buffer = this.buffer.slice(offset + length);
      if (masked) {
        payload = Buffer.from(payload.map((byte, index) => byte ^ mask[index % 4]));
      }
      if (opcode === 1) this.onText(payload.toString("utf8"));
      if (opcode === 8) this.socket.end();
      if (opcode === 9) this.sendFrame(10, payload.toString("utf8"));
    }
  }

  onText(text) {
    logDebug(`recv ${text.slice(0, 160)}`);
    const message = JSON.parse(text);
    if (message.id && pending.has(message.id)) {
      const { resolve, reject } = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) reject(new Error(JSON.stringify(message.error)));
      else resolve(message.result || {});
    }
  }

  close() {
    try {
      this.sendFrame(8, "");
      this.socket.end();
    } catch (_) {}
  }
}

async function connectWebSocket(url) {
  const socket = new RawWebSocket(url);
  return socket.connect();
}

function command(method, params = {}) {
  const id = nextId++;
  logDebug(`send ${id} ${method}`);
  const promise = new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`${method} timeout`));
    }, timeoutMs);
    pending.set(id, {
      resolve: (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      reject: (error) => {
        clearTimeout(timer);
        reject(error);
      },
    });
  });
  ws.send(JSON.stringify({ id, method, params }));
  return promise;
}

async function evaluate(expression) {
  const result = await command("Runtime.evaluate", {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  return result.result ? result.result.value : null;
}

async function fetchPage(url, settleSeconds) {
  await command("Page.navigate", { url });
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const ready = await evaluate("document.readyState");
      const bodyLength = await evaluate("(document.body && document.body.innerText || '').length");
      if ((ready === "interactive" || ready === "complete") && bodyLength > 20) break;
    } catch (_) {
      // Navigation may still be replacing the document.
    }
    await sleep(500);
  }
  await sleep(Math.max(0, settleSeconds) * 1000);
  return {
    url: await evaluate("location.href"),
    title: await evaluate("document.title"),
    text: await evaluate("document.body ? document.body.innerText : ''"),
    html: await evaluate("document.documentElement ? document.documentElement.outerHTML : ''"),
  };
}

async function start() {
  browserProcess = spawn(browserPath, [
    `--remote-debugging-port=${port}`,
    "--remote-allow-origins=*",
    `--user-data-dir=${profileDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--new-window",
    "about:blank",
  ], { stdio: "ignore", windowsHide: false });

  const wsUrl = await waitForPageTarget();
  logDebug(`target ${wsUrl}`);
  ws = await connectWebSocket(wsUrl);
  await command("Page.enable");
  await command("Runtime.enable");
  console.log(JSON.stringify({ status: "ready" }));
}

async function close() {
  try {
    if (ws) ws.close();
  } catch (_) {}
  try {
    if (browserProcess && !browserProcess.killed) browserProcess.kill();
  } catch (_) {}
}

start().catch((error) => {
  console.log(JSON.stringify({ status: "error", error: String(error && error.message ? error.message : error) }));
  process.exit(1);
});

const rl = readline.createInterface({ input: process.stdin });
rl.on("line", async (line) => {
  try {
    const request = JSON.parse(line);
    if (request.command === "close") {
      await close();
      console.log(JSON.stringify({ status: "closed" }));
      process.exit(0);
    }
    const page = await fetchPage(request.url, request.settleSeconds || 4);
    console.log(JSON.stringify({ status: "ok", page }));
  } catch (error) {
    console.log(JSON.stringify({ status: "error", error: String(error && error.message ? error.message : error) }));
  }
});
