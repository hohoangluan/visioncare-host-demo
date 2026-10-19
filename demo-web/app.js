import { TARGET_RATE, downsample, encodeWav, mergeChunks, rms } from "./wav.js";
import { SAMPLES } from "./mock.js";

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------------------
// Cấu hình
// ---------------------------------------------------------------------------

const DEFAULTS = { mode: "live", base: "/api", facing: "environment", format: "audio/mpeg" };
// Quá 15 giây là không còn là một câu lệnh: STT của server tốn thời gian tỉ lệ
// với độ dài audio, và quên bấm dừng sẽ treo cả lượt demo.
const MAX_RECORD_MS = 15000;
const MIN_RECORD_MS = 500;

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
    /* chế độ riêng tư / bị chặn: dùng được, chỉ không nhớ lần sau */
  }
}
const settings = loadSettings();
const isMock = () => settings.mode === "mock";

const fmtMs = (ms) =>
  ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toLocaleString("vi-VN", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} s`;
const fmtClock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

// ---------------------------------------------------------------------------
// Trạng thái
// ---------------------------------------------------------------------------

let phase = "idle";
let mockIndex = 0;

const CHIP = {
  idle: "Sẵn sàng",
  arming: "Đang bật micro…",
  recording: "Đang nghe bạn",
  sending: "Đang gửi lên server",
  processing: "Server đang xử lý",
  speaking: "Đang đọc câu trả lời",
  done: "Xong",
  error: "Có lỗi",
};

function setPhase(next, text) {
  phase = next;
  $("stage").dataset.state = next;
  $("chip-text").textContent = text ?? CHIP[next];

  const busy = ["arming", "sending", "processing", "speaking"].includes(next);
  const cta = $("cta");
  cta.disabled = busy;
  cta.setAttribute("aria-pressed", String(next === "recording"));
  $("cta-text").textContent = next === "recording" ? "Dừng và gửi" : next === "arming" ? "Đang bật micro…" : busy ? "Đang xử lý…" : "Ghi âm";
  $("cta-icon").setAttribute("href", next === "recording" ? "#i-stop" : "#i-mic");
  if (next !== "recording") cta.style.setProperty("--lvl", "0");
}

// Thông báo chỉ hiện khi có chuyện cần người dùng biết (lỗi); bình thường để trống.
function setNote(text) {
  $("note").textContent = text || "";
  $("note").hidden = !text;
}

// ---------------------------------------------------------------------------
// Kiểm tra server
// ---------------------------------------------------------------------------

async function checkHealth() {
  const dot = $("server-dot"), text = $("server-text");
  $("mock-tag").hidden = !isMock();
  if (isMock()) {
    dot.dataset.state = "ok";
    text.textContent = "Không gọi server";
    return;
  }
  const t0 = performance.now();
  try {
    const res = await fetch(`${settings.base}/health`, { cache: "no-store", signal: AbortSignal.timeout(4000) });
    if (!res.ok) throw new Error(String(res.status));
    dot.dataset.state = "ok";
    text.textContent = `Server sẵn sàng · ${Math.round(performance.now() - t0)} ms`;
  } catch {
    dot.dataset.state = "down";
    text.textContent = "Không kết nối được server";
  }
}
setInterval(() => !document.hidden && phase !== "sending" && checkHealth(), 10000);

// ---------------------------------------------------------------------------
// Camera & micro
// ---------------------------------------------------------------------------

const media = { stream: null, ctx: null, node: null, mic: null, micStream: null, graphReady: false, chunks: [], rate: 48000, t0: 0, level: 0, onSamples: null };

// Worklet dựng từ Blob để không cần thêm file; mỗi khối 128 mẫu được chuyển
// nguyên buffer (không sao chép) sang luồng chính.
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
      media.stream = await navigator.mediaDevices.getUserMedia({
        audio,
        video: { facingMode: { ideal: settings.facing }, width: { ideal: 1280 }, height: { ideal: 720 } },
      });
    } catch (err) {
      if (err.name === "NotAllowedError") throw err;
      // Máy không có camera vẫn thu được giọng nói để thử.
      media.stream = await navigator.mediaDevices.getUserMedia({ audio });
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

// Dựng đồ thị thu âm ngay khi có quyền mic, không đợi bấm ghi âm. Ngữ cảnh vẫn
// bị treo tới khi có cử chỉ người dùng (`resume` trong startRecording).
async function buildAudioGraph() {
  const ctx = audioCtx();
  if (!media.node) {
    const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
    await ctx.audioWorklet.addModule(url);
    URL.revokeObjectURL(url);
    media.node = new AudioWorkletNode(ctx, "capture");
    media.node.port.onmessage = (e) => {
      media.onSamples?.(); // báo cho `waitForSamples` biết mic đã thật sự chạy
      media.onSamples = null;
      if (phase !== "recording") return;
      media.chunks.push(e.data);
      media.level = rms(e.data);
    };
    const mute = ctx.createGain();
    mute.gain.value = 0; // worklet chỉ được kéo chạy khi nối vào đồ thị; gain 0 để khỏi nghe lại tiếng mình
    media.node.connect(mute).connect(ctx.destination);
    media.rate = ctx.sampleRate;
  }
  // Đổi camera dựng lại luồng getUserMedia, nên nguồn mic cũ đã chết: nối lại.
  if (media.micStream !== media.stream) {
    media.mic?.disconnect();
    media.mic = ctx.createMediaStreamSource(new MediaStream(media.stream.getAudioTracks()));
    media.mic.connect(media.node);
    media.micStream = media.stream;
  }
  media.graphReady = true;
}

// `resume()` báo xong trước khi luồng âm thanh thật sự chạy: đo thấy bấm ghi
// âm ngay lần đầu thì mất ~0,45 giây đầu, đúng lúc giao diện đã hiện "Đang nghe".
// Chờ mẫu đầu tiên về rồi mới vào trạng thái ghi để giao diện không báo nghe khi
// thực ra chưa nghe. Các lần sau mẫu về liên tục nên chờ này gần như bằng 0.
function waitForSamples(timeoutMs = 2000) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => { media.onSamples = null; resolve(false); }, timeoutMs);
    media.onSamples = () => { clearTimeout(timer); resolve(true); };
  });
}

// Chụp khung hình đang xem, tối đa 1280 px: đủ nét cho OCR/VLM mà không đẩy
// vài MB lên đường truyền như ảnh gốc của camera điện thoại.
function grabFrame() {
  const el = $("video");
  const w = el.videoWidth, h = el.videoHeight;
  if (!w || !h) return Promise.resolve(null);
  const scale = Math.min(1, 1280 / w);
  const c = document.createElement("canvas");
  c.width = Math.round(w * scale);
  c.height = Math.round(h * scale);
  c.getContext("2d").drawImage(el, 0, 0, c.width, c.height);
  return new Promise((resolve) => c.toBlob(resolve, "image/jpeg", 0.85));
}

// ---------------------------------------------------------------------------
// Âm thanh server trả về: luôn phát cho người dùng, và phát dần theo từng gói
// ---------------------------------------------------------------------------

// Trình duyệt (nhất là Safari/iOS) chỉ cho một phần tử audio tự phát nếu nó đã
// được "mở khoá" bằng một lệnh play() ngay trong cú bấm của người dùng. Câu trả
// lời về sau vài giây — lúc đó không còn cú bấm nào nữa — nên không mở khoá trước
// thì âm thanh server trả về sẽ bị chặn, mất tiếng. Đoạn im lặng phải có mẫu thật
// (không phải file rỗng) thì trình duyệt mới coi là đã phát.
const SILENCE_URL = URL.createObjectURL(encodeWav(new Float32Array(800), TARGET_RATE));

const player = (() => {
  const el = $("player");
  let chunks = [], queue = [], mse = null, sb = null;
  let streaming = false, ended = false, started = false, mime = "audio/mpeg";
  let resolveFinished = () => {};
  const api = {
    finished: Promise.resolve(),
    blocked: false,

    unlock() {
      el.src = SILENCE_URL;
      el.play().catch(() => {});
    },
    begin(contentType) {
      chunks = []; queue = []; ended = false; started = false; api.blocked = false;
      mime = (contentType || "audio/mpeg").split(";")[0].trim();
      api.finished = new Promise((r) => (resolveFinished = r));
      // Chỉ MP3 phát dần được qua MediaSource; WAV (và trình duyệt không hỗ
      // trợ, như Safari) phải chờ đủ dữ liệu rồi mới phát.
      streaming = mime === "audio/mpeg" && "MediaSource" in window && MediaSource.isTypeSupported("audio/mpeg");
      if (streaming) {
        mse = new MediaSource();
        el.src = URL.createObjectURL(mse);
        mse.addEventListener("sourceopen", () => {
          sb = mse.addSourceBuffer("audio/mpeg");
          sb.addEventListener("updateend", pump);
          pump();
        }, { once: true });
      }
    },
    push(bytes) {
      chunks.push(bytes);
      if (!streaming) return;
      queue.push(bytes);
      pump();
      if (!started) {
        started = true;
        el.play().catch(() => { api.blocked = true; });
      }
    },
    end() {
      ended = true;
      if (streaming) return pump();
      el.src = URL.createObjectURL(new Blob(chunks, { type: mime }));
      el.play().catch(() => { api.blocked = true; resolveFinished(); });
    },
    stop() { el.pause(); },
  };
  function pump() {
    if (!sb || sb.updating) return;
    if (queue.length) {
      sb.appendBuffer(queue.shift());
    } else if (ended && mse.readyState === "open") {
      try { mse.endOfStream(); } catch { /* đã đóng */ }
    }
  }
  el.addEventListener("ended", () => resolveFinished());
  el.addEventListener("error", () => resolveFinished());
  return api;
})();

// ---------------------------------------------------------------------------
// Một lượt chạy
// ---------------------------------------------------------------------------

async function runLive(wav, frame) {
  const form = new FormData();
  form.append("audio", wav, "request.wav");
  if (frame) form.append("image", frame, "frame.jpg");

  const t0 = performance.now();
  let res;
  try {
    res = await fetch(`${settings.base}/process`, {
      method: "POST",
      body: form,
      headers: { Accept: settings.format },
    });
  } catch {
    throw new Error("Không kết nối được server. Kiểm tra server đang chạy hoặc đổi sang chế độ Mô phỏng.");
  }
  if (!res.ok) throw new Error(`Server trả về lỗi ${res.status}.`);

  const reader = res.body.getReader();
  player.begin(res.headers.get("content-type"));
  let last = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    if (!last) setPhase("processing"); // gói đầu về: server đã nhận và đang nói/làm tiếp
    last = performance.now();
    player.push(value);
  }
  if (!last) throw new Error("Server không trả về âm thanh nào.");

  setPhase("speaking");
  player.end();
  // Chặn trên 60 giây: nếu trình duyệt không bao giờ bắn 'ended' (luồng MSE
  // hỏng giữa chừng) thì lượt demo không được treo vĩnh viễn.
  if (!player.blocked) await Promise.race([player.finished, sleep(60000)]);
  if (player.blocked) setNote("Trình duyệt chặn tự phát âm thanh — bấm vào trang một lần rồi thử lại.");
  return last - t0;
}

// Chế độ mô phỏng không có server nên không có âm thanh thật: dùng giọng đọc của
// trình duyệt để tập dượt luồng bấm — nghe — xong.
function speak(text) {
  return new Promise((resolve) => {
    if (!("speechSynthesis" in window)) return setTimeout(resolve, 2500);
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "vi-VN";
    u.onend = u.onerror = () => resolve();
    speechSynthesis.cancel();
    speechSynthesis.speak(u);
    setTimeout(resolve, 20000); // không có giọng tiếng Việt thì onend có thể không bao giờ tới
  });
}

async function runMock() {
  const t0 = performance.now();
  await sleep(400);
  setPhase("processing");
  await sleep(800);
  setPhase("speaking");
  await speak(SAMPLES[mockIndex++ % SAMPLES.length].answer);
  return performance.now() - t0;
}

async function startRecording() {
  setPhase("arming"); // khoá nút ngay: các bước await bên dưới mở ra kẽ hở bấm đúp
  player.unlock(); // phải gọi đồng bộ trong cú bấm, trước mọi `await`
  setNote("");
  if (!isMock() && !media.stream && !(await initMedia())) return setPhase("idle");
  if (media.stream) {
    await buildAudioGraph().catch(() => {}); // đã dựng sẵn thì trả về ngay
    await audioCtx().resume().catch(() => {});
    await waitForSamples();
  }
  if (!isMock() && !media.graphReady) {
    setPhase("error");
    return setNote("Không khởi tạo được micro. Tải lại trang rồi thử lại.");
  }

  media.chunks = [];
  media.level = 0;
  media.t0 = performance.now();
  media.frame = grabFrame(); // chụp ngay lúc bấm, như nút chụp trên kính
  setPhase("recording");
  media.timeout = setTimeout(() => phase === "recording" && stopRecording(), MAX_RECORD_MS);
  animate();
}

async function stopRecording() {
  clearTimeout(media.timeout);
  setPhase("sending");

  const samples = mergeChunks(media.chunks);
  const wav = encodeWav(downsample(samples, media.rate), TARGET_RATE);
  const frame = await media.frame;
  // Độ dài tính từ số mẫu thật sự thu được, không phải đồng hồ treo tường:
  // mẫu là thứ server nhận, và hai con số này có thể lệch nhau.
  const recordMs = (samples.length / media.rate) * 1000;

  if (!isMock() && recordMs < MIN_RECORD_MS) {
    setPhase("error");
    return setNote("Ghi âm quá ngắn — hãy nói hết câu rồi mới bấm dừng.");
  }

  try {
    const ms = isMock() ? await runMock() : await runLive(wav, frame);
    setPhase("done", `Xong · ${fmtMs(ms)}`);
  } catch (err) {
    player.stop();
    setPhase("error");
    setNote(err.message);
  }
}

// Vòng cập nhật khi đang ghi: đồng hồ trên nhãn trạng thái và vòng sáng quanh nút
// theo mức âm lượng thật của micro.
function animate() {
  const loop = () => {
    if (phase !== "recording") return;
    $("chip-text").textContent = `${CHIP.recording} · ${fmtClock((performance.now() - media.t0) / 1000)}`;
    $("cta").style.setProperty("--lvl", String(Math.min(1, media.level * 6)));
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
}

// ---------------------------------------------------------------------------
// Gắn sự kiện
// ---------------------------------------------------------------------------

$("cta").addEventListener("click", () => (phase === "recording" ? stopRecording() : startRecording()));
$("btn-enable-media").addEventListener("click", initMedia);

// Space = nút ghi âm. Bỏ qua khi đang gõ hoặc đang focus nút (nút tự nhận Space).
document.addEventListener("keydown", (e) => {
  if (e.code !== "Space" || e.repeat) return;
  if (document.querySelector("dialog[open]")) return;
  if (e.target.closest("input, select, textarea, button, a, label")) return;
  e.preventDefault();
  if (!$("cta").disabled) $("cta").click();
});

const dlg = $("dlg-settings");
document.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => b.closest("dialog").close()));
$("btn-settings").addEventListener("click", () => {
  dlg.querySelector(`input[name="mode"][value="${settings.mode}"]`).checked = true;
  $("set-base").value = settings.base;
  $("set-facing").value = settings.facing;
  $("set-format").value = settings.format;
  dlg.showModal();
});
$("set-save").addEventListener("click", () => {
  const facingChanged = $("set-facing").value !== settings.facing;
  settings.mode = dlg.querySelector('input[name="mode"]:checked').value;
  settings.base = $("set-base").value.trim().replace(/\/+$/, "") || DEFAULTS.base;
  settings.facing = $("set-facing").value;
  settings.format = $("set-format").value;
  saveSettings();
  checkHealth();
  if (facingChanged && media.stream) initMedia();
});

// ---------------------------------------------------------------------------
// Khởi động
// ---------------------------------------------------------------------------

setPhase("idle");
checkHealth();
initMedia();
