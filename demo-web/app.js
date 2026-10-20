// Trang demo cho ban giám khảo: nối `WS /v2/session` như kính thật (hello có
// `debug:true`) và vẽ lại những gì server thấy / nghĩ / làm.
//
//   kính  -> server  hello | turn_start | 0x01 ảnh lượt | 0x03 WAV PCM16 stream | turn_end | 0x04 khung live | ping
//   server -> kính   hello_ok | reply | 0x02 ADPCM | reply_end | cam/capture/hazard/end | pong
//   khung debug      trace | say | det | ocr | mode   (hợp đồng ở docs/FIRMWARE_ENDPOINTS.md, mục "Debug")
//
// Phần lớn trang là hiển thị; logic nặng chỉ có ba chỗ: thu âm đẩy dần lên WS,
// phát ADPCM liên tục bằng WebAudio, và gửi khung live theo lệnh `cam`/`capture`.

import { TARGET_RATE, StreamDownsampler, streamingWavHeader, rms } from "./wav.js";
import { decodeBlocks, BLOCK_ALIGN, SAMPLE_RATE } from "./adpcm.js";
import { SAMPLES } from "./mock.js";

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Dựng phần tử nhanh. Mọi chữ từ server đi qua `append`/textContent, không innerHTML. */
function h(tag, cls, ...kids) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  for (const k of kids) if (k != null && k !== "") el.append(k);
  return el;
}

// ---------------------------------------------------------------------------
// Cấu hình
// ---------------------------------------------------------------------------

const DEFAULTS = { mode: "live", base: "/api", facing: "environment", token: "" };
const MAX_HOLD_MS = 25000; // server cắt ở 30 s; dừng sớm hơn để lượt vẫn hợp lệ
const PING_MS = 20000;
const FRAME_MAX_BYTES = 290 * 1024; // trần server 300 KB (LIVE_MAX_FRAME_BYTES)
const IMAGE_MAX_W = 1280;

function loadSettings() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem("seevia-demo") || "{}") };
  } catch {
    return { ...DEFAULTS };
  }
}
function saveSettings() {
  try {
    localStorage.setItem("seevia-demo", JSON.stringify(settings));
  } catch {
    /* chế độ riêng tư: dùng được, chỉ không nhớ lần sau */
  }
}
const settings = loadSettings();
const isMock = () => settings.mode === "mock";

const fmtNum = (x, d = 1) => Number(x).toLocaleString("vi-VN", { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtMs = (ms) => (ms < 1000 ? `${Math.round(ms)} ms` : `${fmtNum(ms / 1000)} s`);
const fmtSec = (s) => fmtMs(s * 1000);
const clock = () => new Date().toLocaleTimeString("vi-VN", { hour12: false });

function setNote(text) {
  $("note").textContent = text || "";
  $("note").hidden = !text;
}

// ---------------------------------------------------------------------------
// Camera, micro, khung hình
// ---------------------------------------------------------------------------

const media = { stream: null, ctx: null, node: null, mic: null, micStream: null, graphReady: false, rate: 48000 };

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

async function initMedia() {
  const gate = $("media-gate");
  if (!navigator.mediaDevices?.getUserMedia) {
    $("media-gate-msg").textContent =
      "Trình duyệt chặn camera/micro vì trang không chạy trên https. Chạy serve.py với --lan trên máy đặt server rồi mở địa chỉ https nó in ra.";
    gate.hidden = false;
    return false;
  }
  media.stream?.getTracks().forEach((t) => t.stop());
  const audio = { channelCount: 1, echoCancellation: true, noiseSuppression: true };
  try {
    try {
      // 4:3 như camera kính; xin lớn để lệnh `capture` có ảnh ≥ 1000 px rộng.
      media.stream = await navigator.mediaDevices.getUserMedia({
        audio,
        video: { facingMode: { ideal: settings.facing }, width: { ideal: 1600 }, height: { ideal: 1200 } },
      });
    } catch (err) {
      if (err.name === "NotAllowedError") throw err;
      media.stream = await navigator.mediaDevices.getUserMedia({ audio }); // máy không có camera vẫn nói được
    }
  } catch (err) {
    $("media-gate-msg").textContent =
      err.name === "NotAllowedError"
        ? "Bạn đã từ chối quyền camera/micro. Cấp quyền trong thanh địa chỉ rồi bấm lại."
        : "Không tìm thấy micro. Cắm micro rồi bấm lại.";
    gate.hidden = false;
    return false;
  }
  gate.hidden = true;
  const v = $("video");
  v.srcObject = media.stream;
  v.play().catch(() => {});
  buildAudioGraph().catch(() => {});
  return true;
}
$("video").addEventListener("loadeddata", () => ($("stage").dataset.video = "1"));

async function buildAudioGraph() {
  const ctx = audioCtx();
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
  // Đổi camera dựng lại luồng getUserMedia nên nguồn mic cũ đã chết: nối lại.
  if (media.micStream !== media.stream) {
    media.mic?.disconnect();
    media.mic = ctx.createMediaStreamSource(new MediaStream(media.stream.getAudioTracks()));
    media.mic.connect(media.node);
    media.micStream = media.stream;
  }
  media.graphReady = true;
}

/**
 * Cắt giữa video theo tỉ lệ 4:3 (khung kính) rồi vẽ ra canvas `w`x`h`, trả JPEG.
 * Màn hình POV cũng cắt đúng 4:3 nên box server trả (chuẩn hoá theo ảnh đã gửi) khớp hình.
 */
function grabJpeg(w, quality, maxBytes = Infinity) {
  const el = $("video");
  const vw = el.videoWidth, vh = el.videoHeight;
  if (!vw || !vh) return Promise.resolve(null);
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
    get busy() { return media.ctx ? next > media.ctx.currentTime : false; },
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
// Dòng thời gian "server xử lý lượt hiện tại"
// ---------------------------------------------------------------------------

const STEP_HINT = { listen: "Giữ nút để nói", stt: "Chờ giọng nói", intent: "", action: "", reply: "" };

const timeline = {
  el: (n) => document.querySelector(`.step[data-step="${n}"]`),
  set(n, state, detail, ms) {
    const el = this.el(n);
    el.dataset.state = state;
    el.querySelector(".ms").textContent = ms == null ? "" : ms;
    const d = el.querySelector(".step-detail");
    d.replaceChildren();
    if (detail != null && detail !== "") d.append(detail);
  },
  reset() {
    for (const n of Object.keys(STEP_HINT)) this.set(n, "wait", STEP_HINT[n]);
  },
};
timeline.reset();

const pill = (text, hl) => h("span", `pill${hl ? " pill-hl" : ""}`, text);
const quote = (text) => (text ? h("span", "quote", `“${text}”`) : h("span", "quote dim", "Không nhận ra lời nói"));

function showTrace(f) {
  const t = f.timings || {};
  const ms = (k) => (typeof t[k] === "number" ? fmtSec(t[k]) : "");

  timeline.set("listen", "done", `Đã nghe${typeof t.audio_s === "number" ? ` ${fmtSec(t.audio_s)} âm thanh` : ""}`, ms("upload_s") && `tải lên ${ms("upload_s")}`);

  timeline.set("stt", "done", quote(f.transcript), ms("final_stt_s"));

  const intent = h("span", "kv");
  if (f.intent) intent.append(pill(f.intent, true));
  else intent.append(h("span", "quote dim", "Chưa xác định ý định"));
  if (f.lane) intent.append(pill(`lane ${f.lane}`));
  if (f.source) intent.append(pill(f.source));
  if (typeof f.confidence === "number") intent.append(pill(`${fmtNum(f.confidence * 100, 1)}%`));
  timeline.set("intent", "done", intent, ms("intent_s"));

  const act = h("span", "kv");
  const params = f.params && typeof f.params === "object" ? Object.entries(f.params) : [];
  for (const [k, v] of params) act.append(pill(`${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`));
  for (const c of f.cues || []) act.append(pill(`cue ${c}`));
  if (f.live) act.append(pill(`live ${f.live}`, true));
  if (!act.childNodes.length) act.append(h("span", "quote dim", "Không có hành động"));
  timeline.set("action", "done", act, ms("route_s"));

  timeline.set("reply", "active", "Đang tạo giọng nói…", ms("release_to_reply_s") && `${ms("release_to_reply_s")} từ lúc nhả`);
}

// ---------------------------------------------------------------------------
// Lịch sử hội thoại
// ---------------------------------------------------------------------------

const history = (() => {
  const root = $("history");
  const groups = new Map(); // id -> {el, user, sv, pending, ended}
  let pendingGroup = null; // lượt đang chờ câu trả lời ở lượt sau
  let liveGroup = null;

  // Bám đáy khi người xem chưa cuộn lên. Ô lịch sử co lại khi thẻ timeline phía trên cao thêm
  // (trace tới sau lượt đầu), mà scrollTop không đổi nên phải bám lại theo kích thước.
  // Sự kiện scroll tới trễ một nhịp, lúc đó nội dung có thể đã dài thêm: chỉ cuộn LÊN mới bỏ bám.
  let pinned = true;
  let prevTop = 0;
  root.addEventListener("scroll", () => {
    const atBottom = root.scrollHeight - root.scrollTop - root.clientHeight < 40;
    if (root.scrollTop < prevTop) pinned = atBottom;
    else if (atBottom) pinned = true;
    prevTop = root.scrollTop;
  });
  new ResizeObserver(() => { if (pinned) root.scrollTop = root.scrollHeight; }).observe(root);
  const stick = (fn) => {
    fn();
    if (pinned) root.scrollTop = root.scrollHeight;
  };
  const add = (el) => {
    $("history-empty")?.remove();
    root.append(el);
  };
  function svBubble(label, cls) {
    return h("div", `bubble sv ${cls || ""}`, h("span", "who", label));
  }

  return {
    startTurn(id) {
      stick(() => {
        if (pendingGroup) {
          // Lượt trước còn câu hỏi treo: nối bằng đường kẻ để thấy đây là một cuộc hội thoại nhiều lượt.
          add(h("div", "link", h("span", "", "Trả lời câu hỏi trên")));
          pendingGroup.pending.dataset.answered = "1";
          pendingGroup = null;
        }
        const user = h("div", "bubble user dim", h("span", "who", "Bạn"), h("p", "", "Đang nghe…"));
        const el = h("article", "turn", user);
        add(el);
        groups.set(id, { el, user, sv: null, pending: null, ended: false });
        liveGroup = null;
      });
    },
    transcript(id, text) {
      const g = groups.get(id);
      if (!g) return;
      stick(() => {
        g.user.classList.toggle("dim", !text);
        g.user.querySelector("p").textContent = text || "(không nhận ra lời nói)";
      });
    },
    pending(id, text) {
      const g = groups.get(id);
      if (!g || !text) return;
      stick(() => {
        g.pending = h("p", "pending", `Đang chờ trả lời: ${text}`);
        g.el.append(g.pending);
        pendingGroup = g;
      });
    },
    /** `reply_end` của lượt: câu nói sau đó mang cùng `turn` là của live (nav/OCR), không phải của lượt này. */
    endTurn(id) {
      const g = groups.get(id);
      if (g) g.ended = true;
    },
    say(turn, text) {
      if (!text) return;
      stick(() => {
        const base = String(turn || "").replace(/\.\d+$/, "");
        const result = base.startsWith("result-");
        let g = groups.get(base) || groups.get(turn);
        // Live mang id lượt đã mở nó: sau reply_end phải sang bong bóng riêng, nếu không
        // nó chui lên bong bóng cũ (sai thứ tự thời gian) và phình mãi.
        if (g && g.ended && !result) g = null;
        if (!g) {
          if (!result && liveGroup && liveGroup.turn === base) g = liveGroup;
          else {
            const sv = svBubble(result ? "Kết quả từ điện thoại" : "SeeVia · trực tiếp", result ? "is-result" : "is-live");
            const el = h("article", "turn", sv);
            add(el);
            g = { el, user: null, sv, turn: base };
            if (result) groups.set(base, g); else liveGroup = g;
          }
        }
        if (!g.sv) {
          g.sv = svBubble("SeeVia");
          g.pending ? g.el.insertBefore(g.sv, g.pending) : g.el.append(g.sv);
        }
        // Cue lặp liền nhau ("Quay sang trái." mỗi khung) gộp thành một dòng có số lần.
        const last = g.sv.lastElementChild;
        if (last && last.tagName === "P" && last.dataset.text === text) {
          const n = (Number(last.dataset.n) || 1) + 1;
          last.dataset.n = String(n);
          last.textContent = `${text} ×${n}`;
        } else {
          const p = h("p", "", text);
          p.dataset.text = text;
          g.sv.append(p);
        }
      });
    },
    sayMock(text) {
      stick(() => {
        const sv = svBubble("SeeVia · mô phỏng", "is-live");
        sv.append(h("p", "", text));
        add(h("article", "turn", sv));
      });
    },
  };
})();

// ---------------------------------------------------------------------------
// Chế độ hiện tại + thống kê khung live
// ---------------------------------------------------------------------------

function showMode(f) {
  const on = { obstacle: !!f.obstacle, ocr: !!f.ocr, nav: !!f.navigating, music: !!f.music, call: !!f.call };
  for (const li of document.querySelectorAll("#modes .mode")) {
    const k = li.dataset.mode;
    li.dataset.on = on[k] ? "1" : "0";
    li.querySelector(".sr").textContent = on[k] ? "đang bật" : "đang tắt";
    if (k === "call") $("call-who").textContent = typeof f.call === "string" && f.call ? ` · ${f.call}` : "";
  }
}
function resetMode() {
  showMode({});
}

const stats = {
  recv: [], // thời điểm nhận kết quả det/ocr
  sent: [], // thời điểm gửi khung 0x04
  inflight: [], // thời điểm gửi các khung chưa thấy kết quả
  lags: [],
  size: "",
  trim(arr, now) {
    while (arr.length && now - arr[0] > 3000) arr.shift();
  },
  onSent() {
    const now = performance.now();
    this.sent.push(now);
    this.inflight.push(now);
    if (this.inflight.length > 6) this.inflight.shift(); // server bỏ bớt khung khi bận: đừng để hàng đợi ước lượng lệch mãi
  },
  onResult() {
    const now = performance.now();
    this.recv.push(now);
    // Server xử lý theo thứ tự nên kết quả đến ứng với khung cũ nhất chưa có kết quả.
    // Chỉ là ước lượng: khung bị server bỏ sẽ làm số này cao hơn thực tế.
    const t0 = this.inflight.shift();
    if (t0 != null) { this.lags.push(now - t0); if (this.lags.length > 10) this.lags.shift(); }
  },
  clear() {
    this.recv = []; this.sent = []; this.inflight = []; this.lags = []; this.size = "";
  },
  render() {
    const now = performance.now();
    this.trim(this.recv, now); this.trim(this.sent, now);
    const fps = (arr) => (arr.length > 1 ? (arr.length - 1) / ((arr[arr.length - 1] - arr[0]) / 1000) : 0);
    const active = this.sent.length > 0 || this.recv.length > 0;
    const fpsEl = $("stat-fps"), lagEl = $("stat-lag");
    if (!active) {
      fpsEl.textContent = "live: tắt";
      lagEl.textContent = "trễ khung: --";
      $("stat-size").textContent = "--";
      fpsEl.dataset.stale = lagEl.dataset.stale = "1";
      return;
    }
    fpsEl.dataset.stale = lagEl.dataset.stale = "0";
    fpsEl.textContent = `gửi ${fmtNum(fps(this.sent))} · xử lý ${fmtNum(fps(this.recv))} fps`;
    const sorted = [...this.lags].sort((a, b) => a - b);
    lagEl.textContent = sorted.length ? `trễ khung ~${Math.round(sorted[Math.floor(sorted.length / 2)])} ms` : "trễ khung: --";
    $("stat-size").textContent = this.size || "--";
  },
};
setInterval(() => stats.render(), 500);

// ---------------------------------------------------------------------------
// Lớp phủ POV: box vật cản, box OCR, hướng dẫn, chớp chụp
// ---------------------------------------------------------------------------

const DET_TTL = 1200, OCR_TTL = 1500;
const overlay = $("overlay");
const ov = { det: null, ocr: null, dpr: 1 };

function sizeOverlay() {
  const dpr = window.devicePixelRatio || 1;
  const r = overlay.getBoundingClientRect();
  overlay.width = Math.max(1, Math.round(r.width * dpr));
  overlay.height = Math.max(1, Math.round(r.height * dpr));
  ov.dpr = dpr;
  drawOverlay();
}
new ResizeObserver(sizeOverlay).observe($("stage"));

// Màu vẽ box lấy từ token CSS (styles.css :root) để canvas và giao diện luôn cùng một bảng màu.
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const LV = {
  low: { color: cssVar("--lv-low"), width: 2, dash: [], alpha: 0.75 },
  2: { color: cssVar("--lv-2"), width: 3, dash: [10, 6], alpha: 1 },
  3: { color: cssVar("--lv-3"), width: 5, dash: [], alpha: 1 },
};
const INK = cssVar("--on-warn"), OCR_INK = cssVar("--cyan");
const lvStyle = (level) => (level >= 3 ? LV[3] : level === 2 ? LV[2] : LV.low);

function drawOverlay() {
  const ctx = overlay.getContext("2d");
  const W = overlay.width, H = overlay.height, d = ov.dpr, now = performance.now();
  ctx.clearRect(0, 0, W, H);
  ctx.lineJoin = "round";

  if (ov.det && now - ov.det.at < DET_TTL) {
    // Vẽ box mức thấp trước để box cảnh báo nằm trên cùng.
    const boxes = [...ov.det.boxes].sort((a, b) => (a.level || 0) - (b.level || 0));
    for (const b of boxes) {
      const [x0, y0, x1, y1] = b.box.map((v, i) => v * (i % 2 ? H : W));
      const st = lvStyle(b.level || 0);
      ctx.globalAlpha = st.alpha;
      ctx.setLineDash(st.dash.map((v) => v * d));
      ctx.strokeStyle = "rgba(2,10,59,.7)"; // viền tối dưới nét màu: đọc được trên mọi nền
      ctx.lineWidth = (st.width + 3) * d;
      ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
      ctx.strokeStyle = st.color;
      ctx.lineWidth = st.width * d;
      ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
      ctx.setLineDash([]);

      const label = `${b.level >= 2 ? `L${b.level} ` : ""}${b.kind} ${fmtNum(b.score, 2)}`;
      ctx.font = `600 ${12 * d}px "JetBrains Mono", monospace`;
      const tw = ctx.measureText(label).width + 12 * d, th = 20 * d;
      const ly = y0 - th >= 0 ? y0 - th : y0;
      ctx.fillStyle = st.color;
      ctx.fillRect(x0, ly, tw, th);
      ctx.fillStyle = INK;
      ctx.textBaseline = "middle";
      ctx.fillText(label, x0 + 6 * d, ly + th / 2 + d);
    }
    ctx.globalAlpha = 1;
  }

  if (ov.ocr && now - ov.ocr.at < OCR_TTL) {
    for (const [x0p, y0p, x1p, y1p] of ov.ocr.boxes) {
      const x0 = (x0p / ov.ocr.w) * W, x1 = (x1p / ov.ocr.w) * W, y0 = (y0p / ov.ocr.h) * H, y1 = (y1p / ov.ocr.h) * H;
      ctx.fillStyle = "rgba(9,187,200,.18)";
      ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
      ctx.strokeStyle = "rgba(2,10,59,.7)";
      ctx.lineWidth = 5 * d;
      ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
      ctx.strokeStyle = OCR_INK; // Cyan chỉ dùng trên nền video tối
      ctx.lineWidth = 2.5 * d;
      ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
    }
  }
}
setInterval(() => (ov.det || ov.ocr) && drawOverlay(), 200); // để box hết hạn tự biến mất

const CUE_VI = {
  look_left: ["Quay trái", "i-arrow-left"],
  look_right: ["Quay phải", "i-arrow-right"],
  look_up: ["Hướng lên", "i-arrow-up"],
  look_down: ["Hướng xuống", "i-arrow-down"],
  look_around: ["Nhìn quanh", "i-eye"],
  move_closer: ["Lại gần", "i-zoom-in"],
  move_away: ["Ra xa", "i-zoom-out"],
  hold_still: ["Giữ yên", "i-hand"],
  ocr_no_text: ["Không thấy chữ", "i-eye"],
  ocr_nothing_to_reread: ["Chưa có gì để đọc lại", "i-eye"],
  captured: ["Đã chụp ảnh nét", "i-camera"],
};
const DIR_VI = { left: "bên trái", center: "phía trước", right: "bên phải" };
const DIR_ICON = { left: "i-arrow-left", center: "i-arrow-up", right: "i-arrow-right" };

const timers = {};
function showFor(key, el, ms, fn) {
  fn?.();
  el.hidden = false;
  clearTimeout(timers[key]);
  timers[key] = setTimeout(() => (el.hidden = true), ms);
}
function retrigger(el, cls, ms) {
  el.className = el.className.replace(/\bgo\d?\b/g, "").trim();
  void el.offsetWidth; // khởi động lại animation
  el.classList.add(cls);
  clearTimeout(timers[`rt-${el.id}`]);
  timers[`rt-${el.id}`] = setTimeout(() => el.classList.remove(cls), ms);
}

function ocrChip(cue) {
  const [text, icon] = CUE_VI[cue] || [cue, "i-eye"];
  showFor("ocr", $("ocr-chip"), 2200, () => {
    $("ocr-text").textContent = text;
    $("ocr-icon").setAttribute("href", `#${icon}`);
  });
}

function onDet(f) {
  ov.det = { at: performance.now(), boxes: Array.isArray(f.boxes) ? f.boxes : [] };
  stats.onResult();
  if (f.w && f.h) stats.size = `${f.w}×${f.h}`;
  drawOverlay();
  if (f.sent && f.hazard) {
    const { level, dir, kind } = f.hazard;
    retrigger($("ring"), `go${Math.min(3, Math.max(1, level))}`, 1500);
    const hz = $("hz");
    showFor("hz", hz, 1800, () => {
      hz.dataset.dir = DIR_VI[dir] ? dir : "center";
      hz.dataset.level = String(level);
      $("hz-icon").setAttribute("href", `#${DIR_ICON[dir] || "i-arrow-up"}`);
      $("hz-text").textContent = `Mức ${level} · ${kind} ${DIR_VI[dir] || ""}`.trim();
    });
    speaker.beep(level, dir);
    hazardLog(f.hazard);
  }
}

function hazardLog({ level, dir, kind }) {
  const list = $("hlog");
  list.querySelector(".empty")?.remove();
  list.prepend(
    h("li", "", h("span", "t", clock()), h("span", `lv lv-${level}`, `L${level}`), h("span", "", `${kind} · ${DIR_VI[dir] || dir}`)),
  );
  while (list.children.length > 30) list.lastChild.remove();
}

function onOcr(f) {
  ov.ocr = { at: performance.now(), w: f.w || 1, h: f.h || 1, boxes: Array.isArray(f.boxes) ? f.boxes : [] };
  stats.onResult();
  if (f.w && f.h) stats.size = `${f.w}×${f.h}`;
  drawOverlay();
  if (f.cue) ocrChip(f.cue);
  if (f.capture) {
    retrigger($("flash"), "go", 400);
    if (!f.cue) ocrChip("captured");
  }
}

// ---------------------------------------------------------------------------
// Khung live gửi lên theo lệnh `cam` / `capture`
// ---------------------------------------------------------------------------

const SIZES = { qqvga: 160, qvga: 320, hqvga: 240, vga: 640, svga: 800, xga: 1024, sxga: 1280, uxga: 1600 };
const sizeW = (name, fallback) => SIZES[String(name).toLowerCase()] || fallback;

const liveTx = {
  timer: null, busy: false, w: 320, fps: 5, q: 0.7,
  start({ size, fps, quality }) {
    this.stop();
    this.w = sizeW(size, 320);
    this.fps = Math.max(1, Math.min(15, Number(fps) || 5));
    // `quality` của firmware là thang JPEG ESP32 (nhỏ = nét hơn, 10–63); đổi sang 0..1 của canvas.
    this.q = Math.max(0.4, Math.min(0.9, 1 - (Number(quality) || 12) / 40));
    this.timer = setInterval(() => this.tick(), 1000 / this.fps);
  },
  stop() {
    clearInterval(this.timer);
    this.timer = null;
    stats.clear();
  },
  async tick() {
    if (this.busy || !session.open || session.ws.bufferedAmount > 256 * 1024) return;
    this.busy = true;
    try {
      const img = await grabJpeg(this.w, this.q, FRAME_MAX_BYTES);
      if (img && this.timer && session.open) {
        session.sendFrame(0x04, await img.blob.arrayBuffer());
        stats.onSent();
        stats.size ||= `${img.w}×${img.h}`;
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
}

// Trạng thái lượt hiện tại — gắn với id do trình duyệt tự sinh, như kính.
const cur = { id: null, pressAt: 0, releaseAt: 0, firstAudio: false, said: 0 };
let turnSeq = 0;

const session = {
  ws: null, ready: false, retry: 0, retryTimer: null, pingTimer: null, stopped: false,
  get open() { return this.ws?.readyState === WebSocket.OPEN; },

  connect() {
    clearTimeout(this.retryTimer);
    this.stopped = false;
    this.ready = false;
    if (isMock()) return setConn("ok", "Mô phỏng: không gọi server");
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
        t: "hello", device: "demo-web", token: settings.token, debug: true,
        // Trang không có clip cục bộ: khai 0 để server đọc cue thành lời (và cue OCR đến qua khung `ocr`).
        cue_version: 0, fw: "demo-web/2", accept: "ima_adpcm",
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
    resetMode();
    if (this.stopped) return;
    if (code === 4401) return setConn("down", "Token sai hoặc thiếu. Mở Cài đặt để nhập token");
    if (code === 4400) return setConn("down", "Server từ chối khung hello (lỗi giao thức)");
    if (code === 4000) return setConn("down", "Một trình duyệt khác đã thay phiên này");
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
    if (!cur.firstAudio && cur.releaseAt) {
      cur.firstAudio = true;
      const ms = performance.now() - cur.releaseAt;
      const d = timeline.el("reply").querySelector(".step-detail");
      d.append(pill(`tiếng đầu sau ${fmtMs(ms)} (đo ở trình duyệt)`, true));
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
        $("debug-tag").hidden = !!f.debug;
        clearInterval(this.pingTimer);
        this.pingTimer = setInterval(() => this.sendJson({ t: "ping" }), PING_MS);
        break;
      case "trace":
        history.transcript(f.turn, f.transcript);
        history.pending(f.turn, f.pending);
        if (f.turn === cur.id) showTrace(f);
        break;
      case "say":
        history.say(f.turn, f.text);
        // Chỉ câu của chính lượt này (trước reply_end); câu live sau đó chỉ vào lịch sử.
        if (f.turn === cur.id && f.text && timeline.el("reply").dataset.state !== "done") {
          const d = timeline.el("reply").querySelector(".step-detail");
          if (d.firstChild && d.firstChild.nodeType === 3) d.replaceChildren();
          cur.said += 1;
          if (cur.said <= 2) d.append(h("span", "quote", `“${f.text}” `));
          else { // câu đọc dài (OCR): timeline chỉ giữ 2 câu đầu, phần còn lại xem ở lịch sử
            let more = d.querySelector(".more");
            if (!more) d.append((more = h("span", "pill more", "")));
            more.textContent = `+${cur.said - 2} câu nữa (xem lịch sử)`;
          }
        }
        break;
      case "reply_end":
        history.endTurn(f.turn);
        if (f.turn === cur.id) {
          const el = timeline.el("reply");
          el.dataset.state = "done";
        }
        break;
      case "det": onDet(f); break;
      case "ocr": onOcr(f); break;
      case "mode": showMode(f); break;
      case "cam": liveTx.start(f); break;
      case "capture": liveTx.capture(f.size); break;
      case "end": liveTx.stop(); break;
      case "hazard": break; // đã thể hiện qua khung `det` có `sent`
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
  if (!on) b.style.setProperty("--lvl", "0");
}

function tickRecording() {
  if (!rec.active && !mock.recording) return;
  const secs = (performance.now() - rec.t0) / 1000;
  $("rec-time").textContent = `${fmtNum(secs)} s`;
  $("ptt").style.setProperty("--lvl", String(Math.min(1, rec.level * 6)));
  if (rec.active) timeline.el("listen").querySelector(".ms").textContent = fmtNum(secs) + " s";
  rec.raf = requestAnimationFrame(tickRecording);
}

// Người dùng có thể nhả nút trong lúc `pressStart` còn đang chờ camera/micro:
// `held` cho biết nút còn giữ hay không để khỏi bắt đầu ghi một lượt không bao giờ kết thúc.
let held = false;

async function pressStart() {
  if (held || rec.active || mock.recording) return;
  held = true;
  setNote("");
  audioCtx().resume().catch(() => {});
  if (isMock()) return mock.start();
  if (!session.ready) return setNote("Chưa kết nối server. Kiểm tra Cài đặt."), (held = false);
  if (!media.stream && !(await initMedia())) return (held = false);
  if (!media.graphReady) return setNote("Chưa khởi tạo được micro. Tải lại trang rồi thử lại."), (held = false);
  await audioCtx().resume().catch(() => {});
  if (!held) return; // đã nhả nút trong lúc chờ

  speaker.stop(); // bấm = dừng mọi thứ đang phát
  const id = `w${Date.now().toString(36)}${(turnSeq++).toString(36)}`;
  Object.assign(cur, { id, pressAt: performance.now(), releaseAt: 0, firstAudio: false, said: 0 });
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
  timeline.reset();
  timeline.set("listen", "active", "Đang nghe bạn…");
  history.startTurn(id);

  // Ảnh lượt chụp ngay lúc bấm, như nút chụp trên kính; gửi song song với audio.
  grabJpeg(IMAGE_MAX_W, 0.85).then(async (img) => {
    if (img && cur.id === id && session.open) session.sendFrame(0x01, await img.blob.arrayBuffer());
  });
}

function pressEnd() {
  held = false;
  if (mock.recording) return mock.end();
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
  const heard = (cur.releaseAt - rec.t0) / 1000;
  timeline.set("listen", "done", `Đã nghe ${fmtNum(heard)} s`, "");
  timeline.set("stt", "active", "Server đang nhận dạng…");
}

// ---------------------------------------------------------------------------
// Chế độ mô phỏng (không server): chỉ tập dượt luồng giữ nút -> nghe -> trả lời
// ---------------------------------------------------------------------------

const mock = {
  recording: false, index: 0,
  start() {
    this.recording = true;
    rec.t0 = performance.now();
    rec.level = 0;
    uiRecording(true);
    tickRecording();
  },
  async end() {
    this.recording = false;
    cancelAnimationFrame(rec.raf);
    uiRecording(false);
    $("ptt").disabled = true;
    $("ptt-text").textContent = "Đang xử lý…";
    await sleep(900);
    const text = SAMPLES[this.index++ % SAMPLES.length].answer;
    history.sayMock(text);
    $("ptt-text").textContent = "Đang đọc câu trả lời";
    await this.speak(text);
    $("ptt").disabled = false;
    $("ptt-text").textContent = "Giữ để nói";
  },
  speak(text) {
    return new Promise((resolve) => {
      if (!("speechSynthesis" in window)) return setTimeout(resolve, 2500);
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "vi-VN";
      u.onend = u.onerror = () => resolve();
      speechSynthesis.cancel();
      speechSynthesis.speak(u);
      setTimeout(resolve, 20000); // không có giọng tiếng Việt thì onend có thể không bao giờ tới
    });
  },
};

function applyMode() {
  $("mock-tag").hidden = !isMock();
  if (isMock()) {
    for (const n of Object.keys(STEP_HINT)) timeline.set(n, "wait", n === "listen" ? "Mô phỏng: không có dữ liệu server" : "");
  } else {
    timeline.reset();
  }
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

$("btn-enable-media").addEventListener("click", initMedia);

const dlg = $("dlg-settings");
document.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => b.closest("dialog").close()));
$("btn-settings").addEventListener("click", () => {
  dlg.querySelector(`input[name="mode"][value="${settings.mode}"]`).checked = true;
  $("set-base").value = settings.base;
  $("set-token").value = settings.token;
  $("set-facing").value = settings.facing;
  dlg.showModal();
});
$("set-save").addEventListener("click", () => {
  const facingChanged = $("set-facing").value !== settings.facing;
  settings.mode = dlg.querySelector('input[name="mode"]:checked').value;
  settings.base = $("set-base").value.trim().replace(/\/+$/, "") || DEFAULTS.base;
  settings.facing = $("set-facing").value;
  settings.token = $("set-token").value.trim();
  saveSettings();
  applyMode();
  session.close();
  session.connect();
  if (facingChanged && media.stream) initMedia();
});

// ---------------------------------------------------------------------------
// Khởi động
// ---------------------------------------------------------------------------

applyMode();
session.connect();
initMedia();
