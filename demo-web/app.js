// Trang demo cho ban giám khảo: CHỈ HIỂN THỊ. Không bật camera/micro, không gửi lượt nào.
// Nó nối `WS /v2/observe` của server kính và vẽ lại những gì kính gửi lên và server làm.
//
//   server -> trang  hello_ok | glasses | turn_start | turn_end | 0x01 ảnh lúc bấm nút
//                    trace | say | mode | reply | reply_end | 0x02 ADPCM tiếng trả lời
//                    cam | capture | end | hazard         (lệnh server gửi kính)
//                    0x04 JPEG + det | ocr                 (khung server vừa xử lý + box của chính nó)
//   trang -> server  hello | ping
//
// Hợp đồng ở docs/FIRMWARE_ENDPOINTS.md (mục "Xem"). Khung `det`/`ocr` luôn đi ngay sau JPEG nó được tính trên,
// nên box vẽ đúng lên đúng khung dù server xử lý chậm hơn kính gửi.

import { decodeBlocks, BLOCK_ALIGN, SAMPLE_RATE } from "./adpcm.js";

const $ = (id) => document.getElementById(id);

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

const DEFAULTS = { base: "/api", token: "", device: "", sound: true };
const PING_MS = 20000;
const STALE_MS = 3000; // quá chừng này không có khung mới thì coi là kính đã ngừng gửi

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
// Mã kính hiện tại do serve.py đọc từ .env (không bí mật). Token thì proxy tự gắn, trang không bao giờ thấy.
let serverDevice = "";

const fmtNum = (x, d = 1) => Number(x).toLocaleString("vi-VN", { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtMs = (ms) => (ms < 1000 ? `${Math.round(ms)} ms` : `${fmtNum(ms / 1000)} s`);
const fmtSec = (s) => fmtMs(s * 1000);
const clock = () => new Date().toLocaleTimeString("vi-VN", { hour12: false });

function setNote(text) {
  $("note").textContent = text || "";
  $("note").hidden = !text;
}

// ---------------------------------------------------------------------------
// Phát âm thanh server trả về kính: ADPCM 0x02 -> WebAudio, nối liên tục không khe hở
// ---------------------------------------------------------------------------

const media = { ctx: null };
function audioCtx() {
  media.ctx ??= new (window.AudioContext || window.webkitAudioContext)();
  return media.ctx;
}

const speaker = (() => {
  let next = 0; // thời điểm (đồng hồ ctx) mà khối kế tiếp được bắt đầu
  let leftover = new Uint8Array(0);
  const live = new Set();
  const PREROLL = 0.2; // như firmware: dựng đệm 0,2 s trước khi phát khối đầu
  return {
    push(bytes) {
      if (!settings.sound) return;
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
    /** Kính bấm nút = dừng mọi thứ đang phát. */
    stop() {
      for (const s of live) { try { s.stop(); } catch { /* đã dừng */ } }
      live.clear();
      leftover = new Uint8Array(0);
      next = 0;
    },
    /** Bíp cảnh báo thay cho clip cục bộ trên kính: số tiếng bíp = mức, nghiêng theo hướng. */
    beep(level, dir) {
      if (!settings.sound) return;
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

function renderSound() {
  const on = settings.sound;
  $("btn-sound").setAttribute("aria-pressed", String(on));
  $("sound-text").textContent = on ? "Âm thanh kính: bật" : "Âm thanh kính: tắt";
  $("sound-icon").setAttribute("href", on ? "#i-volume" : "#i-volume-off");
}

// ---------------------------------------------------------------------------
// Dòng thời gian "server xử lý lượt hiện tại"
// ---------------------------------------------------------------------------

const STEP_HINT = { listen: "Chờ kính bấm nút", stt: "Chờ giọng nói", intent: "", action: "", reply: "" };

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
// Lệnh gửi điện thoại (làn D): mô hình dùng chung cho thẻ lượt và ô "Điện thoại"
// ---------------------------------------------------------------------------

const SVGNS = "http://www.w3.org/2000/svg";
function icon(id, cls = "i") {
  const s = document.createElementNS(SVGNS, "svg");
  s.setAttribute("class", cls);
  s.setAttribute("aria-hidden", "true");
  const u = document.createElementNS(SVGNS, "use");
  u.setAttribute("href", `#${id}`);
  s.append(u);
  return s;
}

const CMD_STATE = {
  wait: ["i-help", "Chờ bạn trả lời"],
  sent: ["i-send", "Đã gửi lệnh"],
  doing: ["i-loader", "Đang làm"],
  done: ["i-check", "Xong"],
  error: ["i-warn", "Lỗi"],
  late: ["i-clock", "Chưa có kết quả"],
  cancelled: ["i-x", "Đã bỏ"],
};
function stateChip(state) {
  const [ic, text] = CMD_STATE[state] || CMD_STATE.sent;
  const c = h("span", "chip", icon(ic), text);
  c.dataset.state = state;
  return c;
}

// intent làn D -> [tên hiển thị, icon, hàm lấy tham số chính]
const PHONE_INTENTS = {
  nav_start: ["Chỉ đường", "i-route", (p) => p.destination],
  nav_stop: ["Dừng chỉ đường", "i-route"],
  contact_call: ["Gọi điện", "i-phone", (p) => p.contact_name],
  call: ["Gọi điện", "i-phone", (p) => p.contact_name || p.contact],
  emergency_call: ["Gọi khẩn cấp", "i-siren"],
  message_send: ["Nhắn tin", "i-msg", (p) => [p.contact_name, p.text].filter(Boolean).join(": ")],
  message_read: ["Đọc tin nhắn", "i-msg"],
  ride_quote: ["Tìm xe", "i-car", (p) => p.destination],
  ride_confirm: ["Xác nhận chuyến xe", "i-car"],
  music_play: ["Phát nhạc", "i-music", (p) => p.song || p.query],
  music_stop: ["Dừng nhạc", "i-music"],
  music_volume: ["Chỉnh âm lượng", "i-music", (p) => p.level ?? p.volume ?? p.direction],
};
const GENERIC_ANSWER = new Set(["confirm", "yes", "no", "cancel", "deny", "reject"]);
const NEGATIVE_ANSWER = new Set(["no", "cancel", "deny", "reject"]);
const ERROR_RE = /lỗi|thất bại|không thể|không thực hiện|không tìm thấy|không kết nối|không liên lạc|hết thời gian|hết giờ|từ chối|chưa gọi được|chưa gửi được/i;
const LATE_MS = 25000;

function mainArg(intent, params) {
  const spec = PHONE_INTENTS[intent];
  const v = spec?.[2]?.(params);
  if (v != null && v !== "") return String(v);
  for (const k of ["contact_name", "contact", "destination", "song", "query", "text", "name"]) if (params[k]) return String(params[k]);
  const first = Object.values(params)[0];
  return first == null || typeof first === "object" ? "" : String(first);
}

const tasks = (() => {
  const list = []; // mới nhất ở cuối
  const open = (t) => t.state === "sent" || t.state === "doing";
  const emit = (t) => { for (const id of t.turns) history.cmd(id, t); renderPhone(); };
  return {
    list,
    /** Khung `trace` của lượt: chỉ làn D là lệnh điện thoại. */
    trace(f) {
      if (f.lane !== "D" || !f.intent) return;
      const params = f.params && typeof f.params === "object" ? f.params : {};
      const waiting = list.findLast?.((t) => t.state === "wait") ?? [...list].reverse().find((t) => t.state === "wait");
      let t = null;
      if (waiting && (GENERIC_ANSWER.has(f.intent) || waiting.intent === f.intent)) {
        t = waiting; // trả lời câu hỏi treo: cùng một lệnh
        t.turns.push(f.turn);
        if (NEGATIVE_ANSWER.has(f.intent)) { t.state = "cancelled"; clearTimeout(t.timer); return emit(t); }
        t.args = mainArg(t.intent, { ...t.params, ...params }) || t.args;
        t.params = { ...t.params, ...params };
        t.turn = f.turn;
      } else {
        if (waiting) { waiting.state = "cancelled"; emit(waiting); }
        const spec = PHONE_INTENTS[f.intent];
        t = { id: f.turn, turn: f.turn, turns: [f.turn], intent: f.intent, name: spec?.[0] || f.intent, icon: spec?.[1] || "i-smartphone", params, args: mainArg(f.intent, params), result: "", at: Date.now(), state: "sent" };
        list.push(t);
        while (list.length > 8) list.shift();
      }
      t.state = f.pending ? "wait" : "sent";
      t.sentAt = performance.now();
      clearTimeout(t.timer);
      if (t.state === "sent") t.timer = setTimeout(() => { if (open(t)) { t.state = "late"; emit(t); } }, LATE_MS);
      emit(t);
    },
    /** `reply_end` của lượt đã gửi lệnh: server đã đọc xong câu mở đầu, điện thoại đang làm. */
    replyEnd(turn) {
      for (const t of list) if (t.turns.at(-1) === turn && t.state === "sent") { t.state = "doing"; emit(t); }
    },
    /** Câu `result-*`: kết quả của lệnh mở lâu nhất. */
    result(text) {
      const t = list.find(open) ?? list.find((x) => x.state === "late");
      if (!t) return;
      clearTimeout(t.timer);
      t.result = t.result ? `${t.result} ${text}` : text;
      t.state = ERROR_RE.test(text) ? "error" : "done";
      emit(t);
    },
    callState(f) {
      const t = [...list].reverse().find((x) => x.intent === "contact_call" || x.intent === "call" || x.intent === "emergency_call");
      if (!t) return;
      const peer = f.peer ? ` · ${f.peer}` : "";
      if (f.state === "ended") {
        clearTimeout(t.timer);
        const failed = f.reason && /fail|reject|busy|timeout|error|declin/i.test(f.reason);
        t.state = failed ? "error" : "done";
        t.result = failed ? `Cuộc gọi không thành (${f.reason})` : t.result || "Cuộc gọi đã kết thúc";
        t.live = failed ? "" : "Cuộc gọi đã kết thúc";
      } else if (f.state) {
        clearTimeout(t.timer);
        t.state = f.state === "active" ? "done" : "doing";
        t.live = f.state === "active" ? `Đang trong cuộc gọi${peer}` : `Đang đổ chuông${peer}`;
      }
      emit(t);
    },
  };
})();

// ---------------------------------------------------------------------------
// Ảnh thu nhỏ của đúng khung hình (cảnh báo vật cản / chữ vừa đọc / ảnh lượt)
// ---------------------------------------------------------------------------

const THUMB_W = 240, THUMB_H = 180;
/** JPEG nhỏ của khung `bmp`; `paint(ctx, rect)` vẽ thêm box trong hệ toạ độ của thumb. */
function makeThumb(bmp, paint) {
  if (!bmp) return "";
  try {
    const c = document.createElement("canvas");
    c.width = THUMB_W;
    c.height = THUMB_H;
    const x = c.getContext("2d");
    x.fillStyle = STAGE_BG;
    x.fillRect(0, 0, THUMB_W, THUMB_H);
    const R = fitRect(THUMB_W, THUMB_H, bmp.width, bmp.height);
    x.drawImage(bmp, R.x, R.y, R.w, R.h);
    x.lineJoin = "round";
    paint?.(x, R);
    return c.toDataURL("image/jpeg", 0.72);
  } catch {
    return "";
  }
}
function paintDet(boxes) {
  return (x, R) => {
    const strong = boxes.filter((b) => (b.level || 0) >= 2);
    for (const b of strong.length ? strong : boxes) {
      const [x0, y0, x1, y1] = b.box.map((v, i) => (i % 2 ? R.y + v * R.h : R.x + v * R.w));
      const st = lvStyle(b.level || 0);
      x.strokeStyle = "rgba(2,10,59,.7)"; x.lineWidth = 5; x.strokeRect(x0, y0, x1 - x0, y1 - y0);
      x.strokeStyle = st.color; x.lineWidth = 2.5; x.strokeRect(x0, y0, x1 - x0, y1 - y0);
    }
  };
}
function paintOcr(o) {
  return (x, R) => {
    for (const [a, b, c, d] of o.boxes) {
      const x0 = R.x + (a / o.w) * R.w, x1 = R.x + (c / o.w) * R.w, y0 = R.y + (b / o.h) * R.h, y1 = R.y + (d / o.h) * R.h;
      x.strokeStyle = "rgba(2,10,59,.7)"; x.lineWidth = 4; x.strokeRect(x0, y0, x1 - x0, y1 - y0);
      x.strokeStyle = OCR_INK; x.lineWidth = 2; x.strokeRect(x0, y0, x1 - x0, y1 - y0);
    }
  };
}
// Bằng chứng gần nhất: thumbnail khung vừa cảnh báo / vừa chụp để đọc chữ.
const evidence = { hazard: null, ocr: null };
const EVIDENCE_TTL = 12000;
function freshEvidence() {
  const now = performance.now();
  return [evidence.hazard, evidence.ocr].filter((e) => e && now - e.at < EVIDENCE_TTL).sort((a, b) => b.at - a.at)[0] || null;
}

// ---------------------------------------------------------------------------
// Dòng hội thoại: mỗi lượt là một thẻ (người dùng nói, ý định, kính trả lời, độ trễ, lệnh điện thoại)
// ---------------------------------------------------------------------------

const history = (() => {
  const root = $("history");
  const jump = $("jump");
  const groups = new Map(); // id -> nhóm của lượt (hoặc kết quả)
  let pendingGroup = null; // lượt đang chờ trả lời ở lượt sau
  let liveGroup = null;
  let seq = 0;

  // Bám đáy khi người xem chưa cuộn lên; cuộn lên đọc lượt cũ thì không giật về, hiện nút "Lượt mới nhất".
  // Sự kiện scroll tới trễ một nhịp: chỉ cuộn LÊN mới bỏ bám.
  let pinned = true;
  let unseen = false;
  let prevTop = 0;
  const syncJump = () => { jump.hidden = pinned || !unseen; };
  root.addEventListener("scroll", () => {
    const atBottom = root.scrollHeight - root.scrollTop - root.clientHeight < 40;
    if (root.scrollTop < prevTop) pinned = atBottom;
    else if (atBottom) pinned = true;
    if (pinned) unseen = false;
    prevTop = root.scrollTop;
    syncJump();
  });
  new ResizeObserver(() => { if (pinned) root.scrollTop = root.scrollHeight; }).observe(root);
  jump.addEventListener("click", () => { pinned = true; unseen = false; root.scrollTop = root.scrollHeight; syncJump(); root.focus({ preventScroll: true }); });
  const stick = (fn) => {
    fn();
    if (pinned) root.scrollTop = root.scrollHeight;
    else { unseen = true; syncJump(); }
  };
  const add = (el) => {
    $("history-empty")?.remove();
    root.append(el);
    const n = root.querySelectorAll(".turn").length;
    $("turn-count").hidden = false;
    $("turn-count").textContent = `${n} mục`;
  };

  const row = (cls, label, body) => {
    const r = h("div", `row row-${cls}`, h("span", "row-label", label), body);
    return r;
  };

  function newGroup(kind, title) {
    const badges = h("span", "grow");
    const head = h("div", "turn-head", h("span", "turn-no", title), h("span", "turn-time mono", clock()), badges);
    const el = h("article", `turn is-new${kind === "live" ? " is-live" : kind === "result" ? " is-result" : ""}`, head);
    el.addEventListener("animationend", () => el.classList.remove("is-new"), { once: true });
    return { el, head, badges, kind, thumbs: null, thumbCount: 0, thumbAt: 0, sv: null, svBody: null, user: null, intentRow: null, cmdRow: null, pending: null, ended: false };
  }
  function ensureSv(g, label) {
    if (g.sv) return;
    g.svBody = h("div", "row-body");
    g.sv = row("sv", label, g.svBody);
    // đặt trước ảnh thu nhỏ / lệnh / câu chờ nếu đã có
    const after = g.cmdRow || g.thumbs || g.pending;
    after ? g.el.insertBefore(g.sv, after) : g.el.append(g.sv);
  }
  function addThumb(g, url, caption) {
    if (!url) return;
    if (!g.thumbs) {
      g.thumbs = h("div", "thumbs");
      g.pending ? g.el.insertBefore(g.thumbs, g.pending) : g.el.append(g.thumbs);
    }
    const img = h("img");
    img.src = url;
    img.alt = `Khung hình lúc đó: ${caption}`;
    img.width = THUMB_W;
    img.height = THUMB_H;
    g.thumbs.append(h("figure", "thumb", img, h("figcaption", "", caption)));
    g.thumbAt = performance.now();
    if (++g.thumbCount > 3) { g.thumbs.firstElementChild.remove(); g.thumbCount--; }
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
        const g = newGroup("turn", `Lượt ${++seq}`);
        g.userBody = h("p", "", "Đang nghe…");
        g.userBodyWrap = h("div", "row-body dim", g.userBody);
        g.user = row("user", "Người dùng nói", g.userBodyWrap);
        g.el.append(g.user);
        add(g.el);
        groups.set(id, g);
        liveGroup = null;
      });
    },
    /** Khung `trace`: transcript + ý định/làn + câu đang chờ. */
    trace(f) {
      const g = groups.get(f.turn);
      if (!g || !g.user) return;
      stick(() => {
        g.userBodyWrap.classList.toggle("dim", !f.transcript);
        g.userBody.textContent = f.transcript || "(không nhận ra lời nói)";
        const pills = h("div", "row-body");
        if (f.intent) pills.append(pill(f.intent, true));
        if (f.lane) pills.append(pill(`làn ${f.lane}`));
        if (f.source) pills.append(pill(f.source));
        if (typeof f.confidence === "number") pills.append(pill(`${fmtNum(f.confidence * 100, 1)}%`));
        if (!pills.childNodes.length) pills.append(h("span", "quote dim", "Chưa xác định ý định"));
        const r = row("intent", "Ý định", pills);
        g.intentRow ? g.intentRow.replaceWith(r) : g.user.after(r);
        g.intentRow = r;
        g.intent = f.intent || "";
        g.lane = f.lane || "";
        if (f.pending) {
          g.pending = h("p", "pending", `Đang chờ trả lời: ${f.pending}`);
          g.el.append(g.pending);
          pendingGroup = g;
        }
        if (g.photo && wantsPhoto(g)) { addThumb(g, g.photo, "Ảnh lúc bấm nút"); g.photo = null; }
      });
    },
    /** Ảnh kính chụp lúc bấm nút: chỉ gắn vào thẻ của lượt cần nhìn (hỏi cảnh, đọc chữ...). */
    photo(id, url) {
      const g = groups.get(id);
      if (!g || !url) return;
      g.photo = url;
      if (g.intent !== undefined && wantsPhoto(g)) stick(() => { addThumb(g, url, "Ảnh lúc bấm nút"); g.photo = null; });
    },
    latency(id, ms) {
      const g = groups.get(id);
      if (!g || g.latChip) return;
      g.latChip = h("span", "chip lat", icon("i-clock"), `Tiếng đầu ${fmtMs(ms)}`);
      g.latChip.title = "Từ lúc kính nhả nút tới lúc tiếng trả lời đầu tiên tới (đo ở trang xem)";
      g.badges.append(g.latChip);
    },
    /** Trạng thái lệnh gửi điện thoại của lượt (khung `trace` làn D, `reply_end`, kết quả `result-*`). */
    cmd(id, t) {
      const g = groups.get(id);
      if (!g || !g.user) return;
      stick(() => {
        const body = h("div", "row-body", stateChip(t.state), h("span", "cmd-text", [t.name, t.args].filter(Boolean).join(" · ")));
        if (t.result) body.append(h("span", "cmd-text quote", `“${t.result}”`));
        const r = row("cmd", "Điện thoại", body);
        if (g.cmdRow) g.cmdRow.replaceWith(r);
        else (g.sv && g.sv.after(r)) || (g.intentRow || g.user).after(r);
        g.cmdRow = r;
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
        // Live mang id lượt đã mở nó: sau reply_end phải sang thẻ riêng, nếu không
        // nó chui lên thẻ cũ (sai thứ tự thời gian) và phình mãi.
        if (g && g.ended && !result) g = null;
        if (!g) {
          if (!result && liveGroup && liveGroup.turn === base) g = liveGroup;
          else {
            g = newGroup(result ? "result" : "live", result ? "Kết quả từ điện thoại" : "Kính nói · trực tiếp");
            g.turn = base;
            add(g.el);
            if (result) groups.set(base, g); else liveGroup = g;
          }
        }
        ensureSv(g, g.kind === "turn" ? "Kính trả lời" : g.kind === "live" ? "Kính nói" : "Kết quả");
        // Cue lặp liền nhau ("Quay sang trái." mỗi khung) gộp thành một dòng có số lần.
        const last = g.svBody.lastElementChild;
        if (last && last.dataset.text === text) {
          const n = (Number(last.dataset.n) || 1) + 1;
          last.dataset.n = String(n);
          last.textContent = `${text} ×${n}`;
        } else {
          const p = h("p", "", text);
          p.dataset.text = text;
          g.svBody.append(p);
          if (g.kind === "live") {
            const ev = freshEvidence();
            if (ev && ev.at > g.thumbAt) addThumb(g, ev.url, ev.label);
          }
        }
        if (result) tasks.result(text);
      });
    },
  };
})();

const wantsPhoto = (g) => g.lane === "B" || /ocr|read|describe|find|money|scene|space/i.test(g.intent || "");

// ---------------------------------------------------------------------------
// Ô "Điện thoại": ảnh thật (adb, tuỳ chọn) hoặc khung vẽ bằng HTML theo lệnh server gửi
// ---------------------------------------------------------------------------

function taskCard(t) {
  const card = h("article", "task",
    h("div", "task-head", icon(t.icon), h("span", "task-name", t.name), stateChip(t.state)));
  card.dataset.state = t.state;
  if (t.args) card.append(h("p", "task-arg", t.args));
  if (t.result) card.append(h("p", "task-res", `“${t.result}”`));
  if (t.live) card.append(h("p", "ph-live", t.live));
  const when = new Date(t.at).toLocaleTimeString("vi-VN", { hour12: false });
  card.append(h("p", "task-meta mono", `${when} · ${CMD_STATE[t.state]?.[1] || ""}`));
  return card;
}

function renderPhone() {
  const box = $("ph-tasks");
  box.replaceChildren();
  if (!tasks.list.length) {
    box.append(h("p", "ph-empty", "Chưa có lệnh nào gửi điện thoại. Thử nói “Dẫn đường”, “Gọi cho mẹ” hoặc “Phát nhạc”."));
    return;
  }
  for (const t of [...tasks.list].reverse()) box.append(taskCard(t));
}
setInterval(() => { $("ph-clock").textContent = new Date().toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit", hour12: false }); }, 5000);
$("ph-clock").textContent = new Date().toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit", hour12: false });

/** Luồng màn hình thật: bật khi serve.py chạy với --phone-mirror và điện thoại nối adb. Lỗi/mất thì về khung vẽ. */
const phoneMirror = (() => {
  const img = $("phone-img"), root = $("phone"), tasksBox = $("ph-tasks");
  let retry = 0, active = false, enabled = false;
  const place = (real) => {
    root.dataset.mirror = real ? "on" : "off";
    $("ph-sub").textContent = real ? "màn hình thật (adb)" : "mô phỏng theo lệnh server gửi";
    // Có ảnh thật: thẻ tác vụ nằm dưới khung. Không có: nằm trong màn hình vẽ.
    if (real) $("phone-frame").after(tasksBox); else $("phone-screen").append(tasksBox);
  };
  const off = () => {
    active = false;
    img.hidden = true;
    img.removeAttribute("src");
    place(false);
  };
  const schedule = () => { clearTimeout(retry); if (enabled && !document.hidden) retry = setTimeout(probe, 20000); };
  img.addEventListener("load", () => { if (!active) { active = true; img.hidden = false; place(true); } });
  img.addEventListener("error", () => { off(); schedule(); });
  document.addEventListener("visibilitychange", () => {
    if (!enabled) return;
    if (document.hidden) { clearTimeout(retry); off(); } else probe(); // tab ẩn: ngắt luồng để điện thoại khỏi quay vô ích
  });
  async function probe() {
    try {
      const c = await (await fetch("config.json", { cache: "no-store" })).json();
      enabled = !!c.phone_mirror;
    } catch { enabled = false; }
    if (!enabled) return off();
    img.src = `phone/stream.mjpg?ts=${Date.now()}`;
    schedule();
  }
  return { probe };
})();
renderPhone();

// ---------------------------------------------------------------------------
// Chế độ hiện tại + thống kê khung live
// ---------------------------------------------------------------------------

let lastModes = null;
function showMode(f) {
  const on = { obstacle: !!f.obstacle, ocr: !!f.ocr, nav: !!f.navigating, music: !!f.music, call: !!f.call };
  for (const li of document.querySelectorAll("#modes .mode")) {
    const k = li.dataset.mode;
    li.dataset.on = on[k] ? "1" : "0";
    li.querySelector(".sr").textContent = on[k] ? "đang bật" : "đang tắt";
    if (k === "call") $("call-who").textContent = typeof f.call === "string" && f.call ? ` · ${f.call}` : "";
  }
  const names = [...document.querySelectorAll('#modes .mode[data-on="1"] .mode-name')].map((e) => e.textContent.trim());
  const sig = names.join("|");
  if (sig !== lastModes) {
    lastModes = sig;
    $("modes-live").textContent = names.length ? `Chế độ đang bật: ${names.join(", ")}` : "Không có chế độ nào đang bật";
  }
}
function resetMode() {
  showMode({});
}

// ---------------------------------------------------------------------------
// Thống kê khung live: tốc độ server xử lý + lệnh server đang yêu cầu kính
// ---------------------------------------------------------------------------

const stats = {
  recv: [], // thời điểm nhận kết quả det/ocr (mỗi kết quả là một khung server vừa xử lý)
  cmd: "", // lệnh `cam` server đang yêu cầu kính, vd. "qvga · 8 fps"
  trim(now) {
    while (this.recv.length && now - this.recv[0] > 3000) this.recv.shift();
  },
  onResult() {
    this.recv.push(performance.now());
  },
  clear() {
    this.recv = [];
    this.cmd = "";
  },
  render() {
    const now = performance.now();
    this.trim(now);
    const fpsEl = $("stat-fps");
    const fps = this.recv.length > 1 ? (this.recv.length - 1) / ((this.recv[this.recv.length - 1] - this.recv[0]) / 1000) : 0;
    const active = this.cmd !== "" || this.recv.length > 0;
    fpsEl.dataset.stale = active ? "0" : "1";
    fpsEl.textContent = !active ? "live: tắt" : `live${this.cmd ? ` ${this.cmd}` : ""} · server xử lý ${fmtNum(fps)} fps`;
    renderSource();
  },
};
setInterval(() => stats.render(), 500);

// ---------------------------------------------------------------------------
// POV: khung kính gửi lên + box server trả về, vẽ chung một canvas
// ---------------------------------------------------------------------------

// `det`/`ocr` đi cùng khung JPEG nó được tính trên nên box gắn với khung chứ không có hạn dùng riêng.
const pov = { bmp: null, src: "", at: 0, det: null, ocr: null };
const overlay = $("overlay");
let dpr = 1;

const decodeJpeg = (bytes) => createImageBitmap(new Blob([bytes], { type: "image/jpeg" })).catch(() => null);

function sizeOverlay() {
  dpr = window.devicePixelRatio || 1;
  const r = overlay.getBoundingClientRect();
  overlay.width = Math.max(1, Math.round(r.width * dpr));
  overlay.height = Math.max(1, Math.round(r.height * dpr));
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
const INK = cssVar("--on-warn"), OCR_INK = cssVar("--cyan"), STAGE_BG = cssVar("--stage-bg");
const lvStyle = (level) => (level >= 3 ? LV[3] : level === 2 ? LV[2] : LV.low);

/** Vùng ảnh trong canvas: vừa khung (không cắt) để box khớp từng pixel ảnh kính đã gửi. */
function fitRect(W, H, iw, ih) {
  const s = Math.min(W / iw, H / ih);
  const w = iw * s, h2 = ih * s;
  return { x: (W - w) / 2, y: (H - h2) / 2, w, h: h2 };
}

function drawOverlay() {
  const ctx = overlay.getContext("2d");
  const W = overlay.width, H = overlay.height, d = dpr;
  ctx.fillStyle = STAGE_BG;
  ctx.fillRect(0, 0, W, H);
  ctx.lineJoin = "round";
  if (!pov.bmp) return;
  const R = fitRect(W, H, pov.bmp.width, pov.bmp.height);
  ctx.drawImage(pov.bmp, R.x, R.y, R.w, R.h);

  if (pov.det) {
    // Vẽ box mức thấp trước để box cảnh báo nằm trên cùng.
    const boxes = [...pov.det.boxes].sort((a, b) => (a.level || 0) - (b.level || 0));
    for (const b of boxes) {
      const [x0, y0, x1, y1] = b.box.map((v, i) => (i % 2 ? R.y + v * R.h : R.x + v * R.w));
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
      const ly = y0 - th >= R.y ? y0 - th : y0;
      ctx.fillStyle = st.color;
      ctx.fillRect(x0, ly, tw, th);
      ctx.fillStyle = INK;
      ctx.textBaseline = "middle";
      ctx.fillText(label, x0 + 6 * d, ly + th / 2 + d);
    }
    ctx.globalAlpha = 1;
  }

  if (pov.ocr) {
    for (const [x0p, y0p, x1p, y1p] of pov.ocr.boxes) {
      const x0 = R.x + (x0p / pov.ocr.w) * R.w, x1 = R.x + (x1p / pov.ocr.w) * R.w;
      const y0 = R.y + (y0p / pov.ocr.h) * R.h, y1 = R.y + (y1p / pov.ocr.h) * R.h;
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

/** Đặt khung mới (kèm box của nó nếu có). `src`: "turn" = ảnh lúc bấm nút, "live" = khung server vừa xử lý. */
function setPov(bmp, src, extra = {}) {
  if (bmp) {
    pov.bmp?.close?.();
    pov.bmp = bmp;
    pov.src = src;
    pov.at = performance.now();
    pov.det = pov.ocr = null;
    $("stage").dataset.frame = "1";
    $("stat-size").textContent = `${bmp.width}×${bmp.height}`;
  }
  Object.assign(pov, extra);
  drawOverlay();
  renderSource();
}

function renderSource() {
  const stale = !!pov.bmp && pov.src === "live" && performance.now() - pov.at > STALE_MS;
  $("stage").dataset.stale = stale ? "1" : "0";
  $("stat-size").hidden = !pov.bmp;
  const el = $("stat-src");
  el.hidden = !pov.bmp;
  el.textContent = stale ? "Khung cuối, kính đã ngừng gửi" : pov.src === "turn" ? "Ảnh kính gửi lúc bấm nút" : "Khung live server vừa xử lý";
}

function clearPov() {
  pov.bmp?.close?.();
  Object.assign(pov, { bmp: null, src: "", at: 0, det: null, ocr: null });
  $("stage").dataset.frame = "0";
  $("stat-size").textContent = "--";
  drawOverlay();
  renderSource();
}

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

function onDet(f, bmp) {
  stats.onResult();
  setPov(bmp, "live", { det: { boxes: Array.isArray(f.boxes) ? f.boxes : [] } });
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
    const url = makeThumb(pov.bmp, paintDet(pov.det?.boxes || []));
    if (url) evidence.hazard = { url, at: performance.now(), label: `Cảnh báo mức ${level} · ${kind} ${DIR_VI[dir] || ""}`.trim() };
    hazardLog(f.hazard, url);
  }
}

function hazardLog({ level, dir, kind }, thumb) {
  const list = $("hlog");
  list.querySelector(".empty")?.remove();
  let pic;
  if (thumb) {
    pic = h("img", "hthumb");
    pic.src = thumb;
    pic.alt = `Khung hình lúc cảnh báo ${kind}`;
  } else pic = h("span", "hthumb none");
  list.prepend(
    h("li", "", pic, h("span", "t", clock()), h("span", `lv lv-${level}`, `L${level}`), h("span", "what", `${kind} · ${DIR_VI[dir] || dir}`)),
  );
  while (list.children.length > 30) list.lastChild.remove();
}

function onOcr(f, bmp) {
  stats.onResult();
  setPov(bmp, "live", { ocr: { w: f.w || 1, h: f.h || 1, boxes: Array.isArray(f.boxes) ? f.boxes : [] } });
  if (f.cue) ocrChip(f.cue);
  if (f.capture) {
    const url = makeThumb(pov.bmp, pov.ocr ? paintOcr(pov.ocr) : undefined);
    if (url) evidence.ocr = { url, at: performance.now(), label: "Ảnh chụp để đọc chữ" };
    retrigger($("flash"), "go", 400);
    if (!f.cue) ocrChip("captured");
  }
}

// ---------------------------------------------------------------------------
// Trạng thái kết nối + kính
// ---------------------------------------------------------------------------

function setConn(state, text) {
  $("conn-dot").dataset.state = state;
  $("conn-text").textContent = text;
  $("banner").hidden = state !== "down";
  $("banner-text").textContent = state === "down" ? text : "";
  renderEmpty();
}

const glasses = { online: false, device: "" };

function setGlasses(online, device = "") {
  glasses.online = online;
  glasses.device = online ? device : glasses.device;
  const el = $("glasses");
  el.dataset.state = online ? "on" : "off";
  el.querySelector(".dot").dataset.state = online ? "ok" : "off";
  $("glasses-text").textContent = online ? `Kính đã kết nối${device ? ` · ${device}` : ""}` : "Kính chưa kết nối";
  renderEmpty();
}

/** Chữ hướng dẫn khi chưa có hình: nói rõ đang thiếu mắt xích nào (server hay kính). */
function renderEmpty() {
  const msg = !session.ready
    ? "Chưa nối server. Kiểm tra Cài đặt."
    : !glasses.online
      ? "Kính chưa kết nối. Bật kính để bắt đầu."
      : "Kính đã kết nối. Bấm nút trên kính để gửi hình.";
  $("stage-empty-msg").textContent = msg;
  const hmsg = $("history-empty-msg");
  if (hmsg) {
    hmsg.textContent = !session.ready
      ? "Chưa nối server nên chưa có hội thoại. Kiểm tra Cài đặt."
      : !glasses.online
        ? "Kính chưa kết nối. Khi kính bật và bấm nút, từng lượt hội thoại hiện ở đây."
        : "Chưa có lượt nào. Bấm nút trên kính và nói.";
  }
}

// Trạng thái lượt hiện tại: id do KÍNH sinh (turn_start), trang chỉ quan sát.
const cur = { id: null, pressAt: 0, releaseAt: 0, firstAudio: false, said: 0, listening: false, tick: 0 };

function listening(on) {
  cur.listening = on;
  clearInterval(cur.tick);
  $("rec-badge").hidden = !on;
  $("stage").dataset.rec = on ? "1" : "0";
  if (!on) return;
  const update = () => {
    const secs = (performance.now() - cur.pressAt) / 1000;
    $("rec-time").textContent = `${fmtNum(secs)} s`;
    timeline.el("listen").querySelector(".ms").textContent = `${fmtNum(secs)} s`;
  };
  update();
  cur.tick = setInterval(update, 100);
}

function resetGlassesState() {
  listening(false);
  stats.clear();
  resetMode();
  speaker.stop();
}

// ---------------------------------------------------------------------------
// Phiên WebSocket xem
// ---------------------------------------------------------------------------

function wsUrl() {
  const b = settings.base.trim();
  const tail = "/v2/observe";
  if (/^wss?:\/\//i.test(b)) return b.replace(/\/+$/, "") + tail;
  if (/^https?:\/\//i.test(b)) return b.replace(/^http/i, "ws").replace(/\/+$/, "") + tail;
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.host}${b.startsWith("/") ? b : `/${b}`}${tail}`;
}

let pendingFrame = null; // JPEG 0x04 đang giải mã: JSON det/ocr ngay sau nó là của khung này
let frameChain = Promise.resolve(); // det/ocr xử lý lần lượt theo đúng thứ tự tới

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
      const hello = { t: "hello", token: settings.token }; // token rỗng: proxy gắn token cấu hình sẵn
      const device = settings.device || serverDevice;
      if (device) hello.device = device;
      ws.send(JSON.stringify(hello));
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
    setGlasses(false);
    resetGlassesState();
    if (this.stopped) return;
    if (code === 4401) return setConn("down", "Token sai hoặc thiếu. Mở Cài đặt để nhập token");
    if (code === 4400) return setConn("down", "Server từ chối khung hello (lỗi giao thức)");
    // Lùi dần 0,5 -> 8 s, nhiễu ±20%.
    const wait = Math.min(8000, 500 * 2 ** this.retry++) * (0.8 + Math.random() * 0.4);
    setConn("down", `Mất kết nối. Thử lại sau ${fmtNum(wait / 1000)} s`);
    this.retryTimer = setTimeout(() => this.connect(), wait);
  },

  sendJson(obj) {
    if (this.open) this.ws.send(JSON.stringify(obj));
  },

  onBinary(buf) {
    if (buf.length < 2) return;
    switch (buf[0]) {
      case 0x01: // ảnh kính gửi lúc bấm nút
        decodeJpeg(buf.subarray(1)).then((bmp) => {
          if (!bmp) return;
          setPov(bmp, "turn");
          history.photo(cur.id, makeThumb(bmp));
        });
        break;
      case 0x04: // khung live server vừa xử lý; JSON det/ocr của nó đến ngay sau
        pendingFrame = decodeJpeg(buf.subarray(1));
        break;
      case 0x02: // tiếng server trả về kính
        if (!cur.firstAudio && cur.releaseAt) {
          cur.firstAudio = true;
          const d = timeline.el("reply").querySelector(".step-detail");
          const ttfa = performance.now() - cur.releaseAt;
          const tp = pill(`tiếng đầu sau ${fmtMs(ttfa)}`, true);
          tp.title = "Đo ở trang xem, từ lúc kính nhả nút";
          d.append(tp);
          history.latency(cur.id, ttfa);
        }
        speaker.push(buf.subarray(1));
        if (settings.sound && media.ctx?.state === "suspended") setNote("Chạm vào trang một lần để bật âm thanh.");
        break;
      default: break;
    }
  },

  onText(raw) {
    let f;
    try { f = JSON.parse(raw); } catch { return; }
    switch (f.t) {
      case "hello_ok":
        this.ready = true;
        this.retry = 0;
        setConn("ok", "Đã nối server · đang xem");
        setGlasses(!!f.glasses);
        clearInterval(this.pingTimer);
        this.pingTimer = setInterval(() => this.sendJson({ t: "ping" }), PING_MS);
        break;
      case "glasses":
        setGlasses(!!f.online, f.device);
        if (!f.online) { resetGlassesState(); renderSource(); }
        break;
      case "turn_start": { // kính vừa bấm nút
        speaker.stop();
        Object.assign(cur, { id: f.turn, pressAt: performance.now(), releaseAt: 0, firstAudio: false, said: 0 });
        timeline.reset();
        timeline.set("listen", "active", "Kính đang nghe người dùng…");
        history.startTurn(f.turn);
        listening(true);
        break;
      }
      case "turn_end":
        if (f.turn !== cur.id) break;
        listening(false);
        cur.releaseAt = performance.now();
        timeline.set("listen", "done", `Đã nghe ${fmtNum((cur.releaseAt - cur.pressAt) / 1000)} s`, "");
        timeline.set("stt", "active", "Server đang nhận dạng…");
        break;
      case "trace":
        history.trace(f);
        tasks.trace(f);
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
        tasks.replyEnd(f.turn);
        if (f.turn === cur.id) timeline.el("reply").dataset.state = "done";
        break;
      case "det":
      case "ocr": {
        const frame = pendingFrame;
        pendingFrame = null;
        frameChain = frameChain.then(async () => {
          const bmp = frame ? await frame : null;
          if (f.t === "det") onDet(f, bmp); else onOcr(f, bmp);
        });
        break;
      }
      case "mode": showMode(f); break;
      case "cam": stats.cmd = `${f.size || "?"} · ${f.fps || "?"} fps`; stats.render(); break;
      case "end": stats.cmd = ""; stats.render(); break;
      case "call_state": tasks.callState(f); break;
      case "capture": case "hazard": case "reply": case "cue": case "pong": break; // đã thể hiện qua det/ocr/say
      case "error": setNote(`Server báo lỗi: ${f.code}`); setTimeout(() => setNote(""), 4000); break;
      default: break;
    }
  },
};

// ---------------------------------------------------------------------------
// Gắn sự kiện
// ---------------------------------------------------------------------------

// Chạm lần đầu mở khoá âm thanh (trình duyệt chặn phát tự động trước cử chỉ).
document.addEventListener("pointerdown", () => {
  if (!settings.sound) return;
  audioCtx().resume().then(() => $("note").textContent.startsWith("Chạm vào trang") && setNote("")).catch(() => {});
}, { passive: true });

$("btn-sound").addEventListener("click", () => {
  settings.sound = !settings.sound;
  saveSettings();
  if (!settings.sound) speaker.stop();
  renderSound();
});

const dlg = $("dlg-settings");
document.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => b.closest("dialog").close()));
$("btn-settings").addEventListener("click", () => {
  $("set-base").value = settings.base;
  $("set-token").value = settings.token;
  $("set-device").value = settings.device;
  $("set-device").placeholder = serverDevice ? `để trống = ${serverDevice}` : "để trống = xem kính đang nối";
  dlg.showModal();
});
$("set-save").addEventListener("click", () => {
  settings.base = $("set-base").value.trim().replace(/\/+$/, "") || DEFAULTS.base;
  settings.token = $("set-token").value.trim();
  settings.device = $("set-device").value.trim();
  saveSettings();
  session.close();
  clearPov();
  session.connect();
});

// ---------------------------------------------------------------------------
// Khởi động
// ---------------------------------------------------------------------------

renderSound();
renderSource();
renderEmpty();
fetch("config.json", { cache: "no-store" })
  .then((r) => (r.ok ? r.json() : {}))
  .then((c) => { serverDevice = typeof c.device === "string" ? c.device : ""; })
  .catch(() => {}) // mở bằng file:// hoặc server cũ: dùng giá trị nhập ở Cài đặt
  .finally(() => { session.connect(); phoneMirror.probe(); });
