// Kính giả lập trên trình duyệt: có nút bật camera, nút bật micro và nút giữ để nói. Nối `WS /v2/session`
// đúng như firmware (hello KHÔNG khai debug: kính thật cũng không khai) nên server coi đây là một cái kính.
// Trang giám sát của giám khảo (index.html) chỉ xem lại qua `WS /v2/observe`.
//
//   kính -> server  hello | turn_start | 0x01 ảnh lượt | 0x03 WAV PCM16 stream | turn_end | 0x04 khung live | ping
//   server -> kính  hello_ok | reply | 0x02 ADPCM | reply_end | cam/capture/hazard/end | pong
//
// Logic nặng chỉ có ba chỗ: thu âm đẩy dần lên WS, phát ADPCM liên tục bằng WebAudio, gửi khung live theo lệnh
// `cam`/`capture`. Mọi chữ hiển thị đi qua textContent, không innerHTML.

import { TARGET_RATE, StreamDownsampler, streamingWavHeader, rms } from "./wav.js";
import { decodeBlocks, BLOCK_ALIGN, SAMPLE_RATE } from "./adpcm.js";

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------------------
// Cấu hình
// ---------------------------------------------------------------------------

const DEFAULTS = { base: "/api", token: "", device: "", facing: "environment" };
// Mã kính hiện tại do serve.py đọc từ .env: trang này đóng vai chính kính đó. Token thì proxy tự gắn, trang không thấy.
let serverDevice = "";
const deviceId = () => settings.device || serverDevice || "demo-client";
const MAX_HOLD_MS = 25000; // server cắt ở 30 s; dừng sớm hơn để lượt vẫn hợp lệ
const PING_MS = 20000;
const FRAME_MAX_BYTES = 290 * 1024; // trần server 300 KB (LIVE_MAX_FRAME_BYTES)
const IMAGE_MAX_W = 1280;

function loadSettings() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem("seevia-client") || "{}") };
  } catch {
    return { ...DEFAULTS };
  }
}
function saveSettings() {
  try {
    localStorage.setItem("seevia-client", JSON.stringify(settings));
  } catch {
    /* chế độ riêng tư: dùng được, chỉ không nhớ lần sau */
  }
}
const settings = loadSettings();

const fmtNum = (x, d = 1) => Number(x).toLocaleString("vi-VN", { minimumFractionDigits: d, maximumFractionDigits: d });

function setNote(text) {
  $("note").textContent = text || "";
  $("note").hidden = !text;
}
function setStatus(text) {
  $("status").textContent = text;
}

// ---------------------------------------------------------------------------
// Camera và micro: bật/tắt riêng bằng hai nút
// ---------------------------------------------------------------------------

const media = { cam: null, mic: null, ctx: null, node: null, src: null, graphReady: false, rate: 48000 };

// Worklet dựng từ Blob để khỏi cần thêm file; mỗi khối 128 mẫu chuyển nguyên buffer sang luồng chính.
const WORKLET = `
class Capture extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0][0];
    if (ch) { const copy = ch.slice(0); this.port.postMessage(copy, [copy.buffer]); }
    return true;
  }
}
registerProcessor("capture", Capture);`;

function audioCtx() {
  media.ctx ??= new (window.AudioContext || window.webkitAudioContext)();
  return media.ctx;
}

function renderToggle(kind, on) {
  const label = kind === "cam" ? "camera" : "micro";
  $(`btn-${kind}`).dataset.on = on ? "1" : "0";
  $(`${kind}-text`).textContent = on ? `Tắt ${label}` : `Bật ${label}`;
  $(`${kind}-icon`).setAttribute("href", `#i-${kind === "cam" ? "camera" : "mic"}${on ? "" : "-off"}`);
}

const NO_HTTPS =
  "Trình duyệt chặn camera/micro vì trang không chạy trên https. Chạy serve.py với --lan trên máy đặt server rồi mở địa chỉ https nó in ra.";

async function enableCam() {
  if (!navigator.mediaDevices?.getUserMedia) return setNote(NO_HTTPS);
  try {
    // 4:3 như camera kính; xin lớn để lệnh `capture` có ảnh ≥ 1000 px rộng.
    media.cam = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: settings.facing }, width: { ideal: 1600 }, height: { ideal: 1200 } },
    });
  } catch (err) {
    return setNote(err.name === "NotAllowedError"
      ? "Bạn đã từ chối quyền camera. Cấp quyền trong thanh địa chỉ rồi bấm lại."
      : "Không tìm thấy camera.");
  }
  setNote("");
  const v = $("video");
  v.srcObject = media.cam;
  v.play().catch(() => {});
  renderToggle("cam", true);
}

function disableCam() {
  media.cam?.getTracks().forEach((t) => t.stop());
  media.cam = null;
  $("video").srcObject = null;
  $("stage").dataset.video = "0";
  renderToggle("cam", false);
}
$("video").addEventListener("loadeddata", () => ($("stage").dataset.video = "1"));

async function enableMic() {
  if (!navigator.mediaDevices?.getUserMedia) return setNote(NO_HTTPS);
  try {
    media.mic = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
  } catch (err) {
    return setNote(err.name === "NotAllowedError"
      ? "Bạn đã từ chối quyền micro. Cấp quyền trong thanh địa chỉ rồi bấm lại."
      : "Không tìm thấy micro. Cắm micro rồi bấm lại.");
  }
  setNote("");
  try {
    await buildAudioGraph();
  } catch {
    disableMic();
    return setNote("Chưa khởi tạo được micro. Tải lại trang rồi thử lại.");
  }
  renderToggle("mic", true);
  uiRecording(false);
}

function disableMic() {
  rec.abort();
  media.src?.disconnect();
  media.src = null;
  media.mic?.getTracks().forEach((t) => t.stop());
  media.mic = null;
  renderToggle("mic", false);
  uiRecording(false);
}

async function buildAudioGraph() {
  const ctx = audioCtx();
  await ctx.resume().catch(() => {});
  if (!media.node) {
    const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
    await ctx.audioWorklet.addModule(url);
    URL.revokeObjectURL(url);
    media.node = new AudioWorkletNode(ctx, "capture");
    media.node.port.onmessage = (e) => rec.active && rec.onSamples(e.data);
    const mute = ctx.createGain();
    mute.gain.value = 0; // worklet chỉ chạy khi nối vào đồ thị; gain 0 để khỏi nghe lại tiếng mình
    media.node.connect(mute).connect(ctx.destination);
    media.rate = ctx.sampleRate;
  }
  media.src?.disconnect();
  media.src = ctx.createMediaStreamSource(media.mic);
  media.src.connect(media.node);
  media.graphReady = true;
}

/**
 * Cắt giữa video theo tỉ lệ 4:3 (khung kính) rồi vẽ ra canvas `w`x`h`, trả JPEG.
 * Khung xem trước cũng cắt đúng 4:3 nên người xem ở bảng giám sát thấy đúng cái server nhận.
 */
function grabJpeg(w, quality, maxBytes = Infinity) {
  const el = $("video");
  const vw = el.videoWidth, vh = el.videoHeight;
  if (!media.cam || !vw || !vh) return Promise.resolve(null);
  let sw = vw, sh = vh, sx = 0, sy = 0;
  if (vw / vh > 4 / 3) { sw = Math.round(vh * 4 / 3); sx = Math.round((vw - sw) / 2); }
  else { sh = Math.round(vw * 3 / 4); sy = Math.round((vh - sh) / 2); }
  const outW = Math.min(w, sw), outH = Math.round(outW * 3 / 4);
  const c = document.createElement("canvas"); // mỗi lần một canvas: mã hoá lại bên dưới là bất đồng bộ
  c.width = outW;
  c.height = outH;
  c.getContext("2d").drawImage(el, sx, sy, sw, sh, 0, 0, outW, outH);
  const encode = (q) => new Promise((resolve) => c.toBlob(resolve, "image/jpeg", q));
  return (async () => {
    let q = quality, blob = await encode(q);
    // Ảnh lớn có thể vượt trần khung: giảm chất lượng dần cho tới khi vừa.
    while (blob && blob.size > maxBytes && q > 0.3) blob = await encode((q -= 0.12));
    return blob ? { blob, w: outW, h: outH } : null;
  })();
}

// ---------------------------------------------------------------------------
// Phát âm thanh server trả về: ADPCM 0x02 -> WebAudio, nối liên tục không khe hở
// ---------------------------------------------------------------------------

const speaker = (() => {
  let next = 0; // thời điểm (đồng hồ ctx) mà khối kế tiếp được bắt đầu
  let leftover = new Uint8Array(0);
  const live = new Set();
  const PREROLL = 0.2; // như firmware: dựng đệm 0,2 s trước khi phát khối đầu
  return {
    push(bytes) {
      const ctx = audioCtx();
      if (ctx.state === "suspended") ctx.resume().catch(() => {});
      let data = bytes;
      if (leftover.length) { data = new Uint8Array(leftover.length + bytes.length); data.set(leftover); data.set(bytes, leftover.length); }
      const usable = data.length - (data.length % BLOCK_ALIGN);
      leftover = data.slice(usable);
      if (!usable) return;
      const pcm = decodeBlocks(data.subarray(0, usable));
      const buf = ctx.createBuffer(1, pcm.length, SAMPLE_RATE);
      buf.copyToChannel(pcm, 0);
      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.connect(ctx.destination);
      const now = ctx.currentTime;
      if (next < now + 0.02) next = now + PREROLL; // hết hàng đợi: câu mới, dựng lại đệm
      src.start(next);
      next += buf.duration;
      live.add(src);
      src.onended = () => live.delete(src);
    },
    /** Bấm nút = dừng mọi thứ đang phát. */
    stop() {
      for (const s of live) { try { s.stop(); } catch { /* đã dừng */ } }
      live.clear();
      leftover = new Uint8Array(0);
      next = 0;
    },
    /** Bíp cảnh báo thay cho clip cục bộ trên kính: số tiếng bíp = mức, nghiêng theo hướng. */
    beep(level, dir) {
      const ctx = audioCtx();
      if (ctx.state === "suspended") return;
      const pan = ctx.createStereoPanner?.();
      if (pan) { pan.pan.value = dir === "left" ? -0.8 : dir === "right" ? 0.8 : 0; pan.connect(ctx.destination); }
      const freq = [0, 660, 880, 1100][Math.min(3, Math.max(1, level))];
      for (let i = 0; i < Math.min(3, level); i++) {
        const osc = ctx.createOscillator(), g = ctx.createGain();
        osc.frequency.value = freq;
        const t = ctx.currentTime + i * 0.16;
        g.gain.setValueAtTime(0.0001, t);
        g.gain.exponentialRampToValueAtTime(0.18, t + 0.01);
        g.gain.exponentialRampToValueAtTime(0.0001, t + 0.11);
        osc.connect(g).connect(pan || ctx.destination);
        osc.start(t);
        osc.stop(t + 0.13);
      }
    },
  };
})();

// ---------------------------------------------------------------------------
// Khung live gửi lên theo lệnh `cam` / `capture`
// ---------------------------------------------------------------------------

const SIZES = { qqvga: 160, qvga: 320, hqvga: 240, vga: 640, svga: 800, xga: 1024, sxga: 1280, uxga: 1600 };
const sizeW = (name, fallback) => SIZES[String(name).toLowerCase()] || fallback;

const liveTx = {
  timer: null, busy: false, w: 320, fps: 5, q: 0.7, sent: [],
  start({ size, fps, quality }) {
    this.stop();
    this.w = sizeW(size, 320);
    this.fps = Math.max(1, Math.min(15, Number(fps) || 5));
    // `quality` của firmware là thang JPEG ESP32 (nhỏ = nét hơn, 10–63); đổi sang 0..1 của canvas.
    this.q = Math.max(0.4, Math.min(0.9, 1 - (Number(quality) || 12) / 40));
    this.label = `${size || "?"} · ${this.fps} fps`;
    this.timer = setInterval(() => this.tick(), 1000 / this.fps);
    this.render();
  },
  stop() {
    clearInterval(this.timer);
    this.timer = null;
    this.sent = [];
    this.render();
  },
  render() {
    const el = $("live-badge");
    el.hidden = !this.timer;
    if (!this.timer) return;
    const now = performance.now();
    this.sent = this.sent.filter((t) => now - t < 3000);
    const n = this.sent.length;
    const fps = n > 1 ? (n - 1) / ((this.sent[n - 1] - this.sent[0]) / 1000) : 0;
    el.textContent = media.cam ? `đang gửi live ${this.label} · ${fmtNum(fps)} fps` : "server cần hình live nhưng camera đang tắt";
  },
  async tick() {
    if (this.busy || !session.open || session.ws.bufferedAmount > 256 * 1024) return;
    this.busy = true;
    try {
      const img = await grabJpeg(this.w, this.q, FRAME_MAX_BYTES);
      if (img && this.timer && session.open) {
        session.sendFrame(0x04, await img.blob.arrayBuffer());
        this.sent.push(performance.now());
      }
    } finally {
      this.busy = false;
    }
  },
  /** `capture`: một ảnh lớn (≥ 1000 px rộng nếu camera đủ), nén xuống dưới trần khung. */
  async capture(size) {
    const img = await grabJpeg(sizeW(size, 1600), 0.8, FRAME_MAX_BYTES);
    if (img && session.open) session.sendFrame(0x04, await img.blob.arrayBuffer());
  },
};
setInterval(() => liveTx.render(), 500);

// ---------------------------------------------------------------------------
// Phiên WebSocket
// ---------------------------------------------------------------------------

function wsUrl() {
  const b = settings.base.trim();
  const tail = "/v2/session";
  if (/^wss?:\/\//i.test(b)) return b.replace(/\/+$/, "") + tail;
  if (/^https?:\/\//i.test(b)) return b.replace(/^http/i, "ws").replace(/\/+$/, "") + tail;
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.host}${b.startsWith("/") ? b : `/${b}`}${tail}`;
}

function setConn(state, text) {
  $("conn-dot").dataset.state = state;
  $("conn-text").textContent = text;
  $("banner").hidden = state !== "down";
  $("banner-text").textContent = state === "down" ? text : "";
  if (state !== "ok") setStatus(text);
}

const cur = { id: null, releaseAt: 0 };
let turnSeq = 0;

const session = {
  ws: null, ready: false, retry: 0, retryTimer: null, pingTimer: null, stopped: false,
  get open() { return this.ws?.readyState === WebSocket.OPEN; },

  connect() {
    clearTimeout(this.retryTimer);
    this.stopped = false;
    this.ready = false;
    setConn("wait", "Đang kết nối…");
    let ws;
    try {
      ws = new WebSocket(wsUrl());
    } catch {
      return setConn("down", "Địa chỉ server không hợp lệ");
    }
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onopen = () => {
      ws.send(JSON.stringify({
        t: "hello", device: deviceId(), token: settings.token, // token rỗng: proxy gắn token cấu hình sẵn
        // Trang không có clip cục bộ: khai 0 để server đọc cue thành lời.
        cue_version: 0, fw: "demo-client/1", accept: "ima_adpcm",
      }));
    };
    ws.onmessage = (e) => (typeof e.data === "string" ? this.onText(e.data) : this.onBinary(new Uint8Array(e.data)));
    ws.onclose = (e) => {
      if (this.ws !== ws) return;
      this.onClose(e.code);
    };
  },

  close() {
    this.stopped = true;
    clearTimeout(this.retryTimer);
    clearInterval(this.pingTimer);
    const ws = this.ws;
    this.ws = null;
    this.ready = false;
    try { ws?.close(1000); } catch { /* đã đóng */ }
  },

  onClose(code) {
    clearInterval(this.pingTimer);
    this.ready = false;
    this.ws = null;
    liveTx.stop();
    rec.abort();
    if (this.stopped) return;
    if (code === 4401) return setConn("down", "Token sai hoặc thiếu. Mở Cài đặt để nhập token");
    if (code === 4400) return setConn("down", "Server từ chối khung hello (lỗi giao thức)");
    if (code === 4000) return setConn("down", "Một thiết bị khác cùng mã kính đã thay phiên này");
    // Lùi dần 0,5 -> 8 s, nhiễu ±20% như firmware.
    const wait = Math.min(8000, 500 * 2 ** this.retry++) * (0.8 + Math.random() * 0.4);
    setConn("down", `Mất kết nối. Thử lại sau ${fmtNum(wait / 1000)} s`);
    this.retryTimer = setTimeout(() => this.connect(), wait);
  },

  sendJson(obj) {
    if (this.open) this.ws.send(JSON.stringify(obj));
  },
  /** Khung nhị phân = 1 byte loại + dữ liệu. */
  sendFrame(kind, payload) {
    if (!this.open) return;
    const body = payload instanceof Uint8Array ? payload : new Uint8Array(payload);
    const out = new Uint8Array(1 + body.length);
    out[0] = kind;
    out.set(body, 1);
    this.ws.send(out);
  },

  onBinary(buf) {
    if (buf[0] !== 0x02 || buf.length < 2) return;
    if (cur.releaseAt) {
      cur.releaseAt = 0;
      setStatus("Kính đang trả lời, bạn nghe được qua loa của thiết bị này…");
    }
    speaker.push(buf.subarray(1));
    if (media.ctx?.state === "suspended") setNote("Chạm vào trang một lần để bật âm thanh.");
  },

  onText(raw) {
    let f;
    try { f = JSON.parse(raw); } catch { return; }
    switch (f.t) {
      case "hello_ok":
        this.ready = true;
        this.retry = 0;
        setConn("ok", `Đã kết nối · phiên ${f.session || ""}`.trim());
        setStatus("Sẵn sàng. Bật camera và micro rồi giữ nút để nói.");
        clearInterval(this.pingTimer);
        this.pingTimer = setInterval(() => this.sendJson({ t: "ping" }), PING_MS);
        break;
      case "reply":
        if (f.live === "ocr") setStatus("Đang đọc chữ trực tiếp. Đưa chữ vào giữa khung.");
        else if (f.live === "nav") setStatus("Đang bật cảnh báo vật cản.");
        break;
      case "reply_end":
        if (f.turn === cur.id) setStatus("Sẵn sàng.");
        break;
      case "hazard": speaker.beep(f.level, f.dir); break; // kính thật phát clip cục bộ; trang tự bíp
      case "cam": liveTx.start(f); break;
      case "capture": liveTx.capture(f.size); break;
      case "end": liveTx.stop(); break;
      case "error": setNote(`Server báo lỗi: ${f.code}`); setTimeout(() => setNote(""), 4000); break;
      default: break;
    }
  },
};

// ---------------------------------------------------------------------------
// Giữ nút để nói
// ---------------------------------------------------------------------------

const rec = {
  active: false, ds: null, header: true, out: [], outLen: 0, t0: 0, level: 0, raf: 0, timeout: 0,
  onSamples(f32) {
    this.level = rms(f32);
    const pcm = this.ds.push(f32);
    if (!pcm.length) return;
    this.out.push(pcm);
    this.outLen += pcm.length;
    if (this.outLen >= TARGET_RATE / 10) this.flush(); // ~100 ms mỗi khung
  },
  flush() {
    if (!this.outLen) return;
    const pcm = new Uint8Array(this.outLen * 2);
    let o = 0;
    for (const c of this.out) { pcm.set(new Uint8Array(c.buffer, c.byteOffset, c.byteLength), o); o += c.byteLength; }
    this.out = [];
    this.outLen = 0;
    let payload = pcm;
    if (this.header) { // header WAV đi cùng khối PCM đầu, trong cùng khung 0x03
      const hd = streamingWavHeader(TARGET_RATE);
      payload = new Uint8Array(hd.length + pcm.length);
      payload.set(hd);
      payload.set(pcm, hd.length);
      this.header = false;
    }
    session.sendFrame(0x03, payload);
  },
  abort() {
    if (!this.active) return;
    this.active = false;
    clearTimeout(this.timeout);
    cancelAnimationFrame(this.raf);
    uiRecording(false);
  },
};

function uiRecording(on) {
  const b = $("ptt");
  b.setAttribute("aria-pressed", String(on));
  $("ptt-text").textContent = on ? "Đang nghe, thả để gửi" : "Giữ để nói";
  $("stage").dataset.rec = on ? "1" : "0";
  $("rec-badge").hidden = !on;
  $("meter-box").dataset.active = on ? "1" : "0";
  if (!on) {
    b.style.setProperty("--lvl", "0");
    $("meter-fill").style.width = "0%";
    $("meter").setAttribute("aria-valuenow", "0");
    $("meter").setAttribute("aria-valuetext", "Micro đang nghỉ");
    $("meter-state").textContent = media.mic ? "Micro sẵn sàng. Giữ nút Nói hoặc phím Space để nói." : "Micro đang tắt. Bấm “Bật micro” trước.";
  }
}

/** Mức âm micro 0..100 (căn theo RMS: tiếng nói bình thường ~0,05-0,15). */
function renderLevel(level) {
  const pct = Math.round(Math.min(1, level * 6) * 100);
  $("meter-fill").style.width = `${pct}%`;
  $("meter").setAttribute("aria-valuenow", String(pct));
  $("meter-state").textContent = pct < 4 ? "Đang nghe… chưa thấy tiếng nói, hãy nói to hơn hoặc lại gần micro." : pct > 92 ? "Tiếng quá to, có thể bị méo." : "Đang nghe bạn nói.";
}

function tickRecording() {
  if (!rec.active) return;
  $("rec-time").textContent = `${fmtNum((performance.now() - rec.t0) / 1000)} s`;
  $("ptt").style.setProperty("--lvl", String(Math.min(1, rec.level * 6)));
  renderLevel(rec.level);
  rec.raf = requestAnimationFrame(tickRecording);
}

// Người dùng có thể nhả nút trong lúc `pressStart` còn đang chờ: `held` cho biết nút còn giữ hay không để
// khỏi bắt đầu ghi một lượt không bao giờ kết thúc.
let held = false;

async function pressStart() {
  if (held || rec.active) return;
  held = true;
  setNote("");
  audioCtx().resume().catch(() => {});
  if (!session.ready) return setNote("Chưa kết nối server. Kiểm tra Cài đặt."), (held = false);
  if (!media.mic || !media.graphReady) return setNote("Bật micro trước khi nói."), (held = false);
  await audioCtx().resume().catch(() => {});
  if (!held) return; // đã nhả nút trong lúc chờ

  speaker.stop(); // bấm = dừng mọi thứ đang phát
  const id = `w${Date.now().toString(36)}${(turnSeq++).toString(36)}`;
  Object.assign(cur, { id, releaseAt: 0 });
  session.sendJson({ t: "turn_start", turn: id, t_press_ms: Math.round(performance.now()) });

  rec.ds = new StreamDownsampler(media.rate, TARGET_RATE);
  rec.header = true;
  rec.out = [];
  rec.outLen = 0;
  rec.level = 0;
  rec.t0 = performance.now();
  rec.active = true;
  rec.timeout = setTimeout(pressEnd, MAX_HOLD_MS);
  uiRecording(true);
  tickRecording();
  setStatus("Đang nghe bạn…");

  // Ảnh lượt chụp ngay lúc bấm, như nút chụp trên kính; gửi song song với audio. Camera tắt thì lượt không có ảnh.
  grabJpeg(IMAGE_MAX_W, 0.85).then(async (img) => {
    if (img && cur.id === id && session.open) session.sendFrame(0x01, await img.blob.arrayBuffer());
  });
}

function pressEnd() {
  held = false;
  if (!rec.active) return;
  rec.active = false;
  clearTimeout(rec.timeout);
  cancelAnimationFrame(rec.raf);
  rec.out.push(rec.ds.push(null, true));
  rec.outLen = rec.out.reduce((n, c) => n + c.length, 0);
  rec.flush();
  if (rec.header) { // chưa gửi byte nào (nhả quá sớm): vẫn phải mở luồng bằng header rỗng
    session.sendFrame(0x03, streamingWavHeader(TARGET_RATE));
    rec.header = false;
  }
  cur.releaseAt = performance.now();
  session.sendJson({ t: "turn_end", turn: cur.id, t_release_ms: Math.round(cur.releaseAt) });
  uiRecording(false);
  setStatus("Đã gửi, server đang xử lý…");
}

// ---------------------------------------------------------------------------
// Gắn sự kiện
// ---------------------------------------------------------------------------

const ptt = $("ptt");
ptt.addEventListener("pointerdown", (e) => {
  if (e.button > 0 || ptt.disabled) return;
  e.preventDefault();
  try { ptt.setPointerCapture(e.pointerId); } catch { /* một số trình duyệt không cho */ }
  pressStart();
});
for (const ev of ["pointerup", "pointercancel", "lostpointercapture"]) ptt.addEventListener(ev, pressEnd);
ptt.addEventListener("contextmenu", (e) => e.preventDefault());
window.addEventListener("blur", pressEnd);

// Space = giữ để nói (bất kỳ đâu trừ ô nhập); Enter cũng dùng được khi nút đang focus.
const typing = (t) => t.closest?.("input, select, textarea, a, dialog[open], button:not(#ptt)");
document.addEventListener("keydown", (e) => {
  const hold = e.code === "Space" || (e.code === "Enter" && e.target === ptt);
  if (!hold || typing(e.target)) return;
  e.preventDefault();
  if (!e.repeat) pressStart();
});
document.addEventListener("keyup", (e) => {
  if (e.code === "Space" || (e.code === "Enter" && e.target === ptt)) pressEnd();
});
// Chạm lần đầu mở khoá âm thanh (trình duyệt chặn phát tự động trước cử chỉ).
document.addEventListener("pointerdown", () => {
  audioCtx().resume().then(() => $("note").textContent.startsWith("Chạm vào trang") && setNote("")).catch(() => {});
}, { passive: true });

// Bấm bằng chuột xong thì bỏ tiêu điểm khỏi nút, để phím Space ngay sau đó là "giữ để nói" chứ không bật/tắt lại nút.
const afterPointer = (e) => { if (e.detail > 0) e.currentTarget.blur(); };
$("btn-cam").addEventListener("click", (e) => { afterPointer(e); return media.cam ? disableCam() : enableCam(); });
$("btn-mic").addEventListener("click", (e) => { afterPointer(e); return media.mic ? disableMic() : enableMic(); });

const dlg = $("dlg-settings");
document.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => b.closest("dialog").close()));
$("btn-settings").addEventListener("click", () => {
  $("set-base").value = settings.base;
  $("set-token").value = settings.token;
  $("set-device").value = settings.device;
  $("set-device").placeholder = `để trống = ${serverDevice || "demo-client"}`;
  $("set-facing").value = settings.facing;
  dlg.showModal();
});
$("set-save").addEventListener("click", () => {
  const facingChanged = $("set-facing").value !== settings.facing;
  settings.base = $("set-base").value.trim().replace(/\/+$/, "") || DEFAULTS.base;
  settings.token = $("set-token").value.trim();
  settings.device = $("set-device").value.trim();
  settings.facing = $("set-facing").value;
  saveSettings();
  session.close();
  session.connect();
  if (facingChanged && media.cam) { disableCam(); enableCam(); }
});

// ---------------------------------------------------------------------------
// Khởi động
// ---------------------------------------------------------------------------

fetch("config.json", { cache: "no-store" })
  .then((r) => (r.ok ? r.json() : {}))
  .then((c) => { serverDevice = typeof c.device === "string" ? c.device : ""; })
  .catch(() => {}) // mở bằng file:// hoặc server cũ: dùng giá trị nhập ở Cài đặt
  .finally(() => session.connect());
