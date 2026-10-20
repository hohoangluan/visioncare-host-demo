// Trình duyệt chỉ thu được webm/opus (MediaRecorder), mà `pipeline/adpcm.py`
// của server chỉ đọc WAV hoặc ADPCM thô — đưa webm vào là mọi request rơi
// xuống câu báo lỗi. Nên trang tự thu mẫu thô rồi đóng gói WAV PCM 16-bit.

// `pipeline/stt.py` cần 16 kHz mono; nó có tự resample nhưng chỉ bằng nội suy
// tuyến tính, nên đưa đúng 16 kHz ngay từ đầu cho khỏi phụ thuộc vào nhánh đó.
export const TARGET_RATE = 16000;

export function mergeChunks(chunks) {
  const total = chunks.reduce((n, c) => n + c.length, 0);
  const out = new Float32Array(total);
  let offset = 0;
  for (const c of chunks) {
    out.set(c, offset);
    offset += c.length;
  }
  return out;
}

// Lấy trung bình trong từng cửa sổ thay vì bỏ bớt mẫu: mic thường ghi 48 kHz,
// bỏ mẫu thô sẽ gấp dải trên 8 kHz xuống thành tiếng rít trong dải giọng nói.
export function downsample(samples, fromRate, toRate = TARGET_RATE) {
  if (fromRate === toRate || samples.length === 0) return samples;
  const ratio = fromRate / toRate;
  const out = new Float32Array(Math.floor(samples.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(samples.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += samples[j];
    out[i] = sum / Math.max(1, end - start);
  }
  return out;
}

export function encodeWav(samples, sampleRate = TARGET_RATE) {
  const dataBytes = samples.length * 2;
  const view = new DataView(new ArrayBuffer(44 + dataBytes));
  const text = (offset, s) => {
    for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i));
  };
  text(0, "RIFF");
  view.setUint32(4, 36 + dataBytes, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true); // cỡ khối fmt
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // byte/giây
  view.setUint16(32, 2, true); // block align
  view.setUint16(34, 16, true); // bit/mẫu
  text(36, "data");
  view.setUint32(40, dataBytes, true);
  for (let i = 0; i < samples.length; i++) {
    // Cắt ở ±1 trước khi nhân: mẫu vượt biên mà không cắt sẽ tràn Int16 và
    // đổi dấu, nghe thành tiếng nổ chứ không phải tiếng méo nhẹ.
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([view], { type: "audio/wav" });
}

// RMS của một khối mẫu, dùng cho thanh mức âm lượng lúc ghi.
export function rms(samples) {
  if (samples.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
  return Math.sqrt(sum / samples.length);
}

// Header WAV cho luồng PCM16 chưa biết độ dài (đang thu): RIFF size và data size
// đều 0xFFFFFFFF. `pipeline/stt_stream.py` dò "RIFF", đọc fmt rồi coi mọi byte
// sau chunk `data` là mẫu, nên gửi header + khối PCM đầu trong cùng một khung 0x03.
export function streamingWavHeader(sampleRate = TARGET_RATE) {
  const view = new DataView(new ArrayBuffer(44));
  const text = (offset, s) => {
    for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i));
  };
  text(0, "RIFF");
  view.setUint32(4, 0xffffffff, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, 0xffffffff, true);
  return new Uint8Array(view.buffer);
}

// Hạ mẫu theo luồng: giữ phần dư giữa các lần gọi để biên khối không lệch pha.
// Cùng cách lấy trung bình cửa sổ như `downsample`, nhưng cửa sổ thứ i luôn là
// [floor(i*ratio), floor((i+1)*ratio)) tính từ mẫu đầu của cả luồng.
export class StreamDownsampler {
  constructor(fromRate, toRate = TARGET_RATE) {
    this.ratio = fromRate / toRate;
    this.buf = new Float32Array(0); // mẫu chưa dùng hết
    this.consumed = 0; // số mẫu đã bỏ khỏi đầu luồng
    this.outIndex = 0; // số mẫu ra đã sinh
  }

  /** Nhận Float32, trả Int16Array (có thể rỗng). `final` = xả nốt phần dư. */
  push(samples, final = false) {
    if (samples && samples.length) {
      const merged = new Float32Array(this.buf.length + samples.length);
      merged.set(this.buf);
      merged.set(samples, this.buf.length);
      this.buf = merged;
    }
    const total = this.consumed + this.buf.length;
    const out = [];
    for (;;) {
      const start = Math.floor(this.outIndex * this.ratio);
      let end = Math.floor((this.outIndex + 1) * this.ratio);
      if (end > total) {
        if (!final || start >= total) break;
        end = total; // cửa sổ cuối thiếu: lấy phần còn lại
      }
      let sum = 0;
      for (let j = start; j < end; j++) sum += this.buf[j - this.consumed];
      const s = Math.max(-1, Math.min(1, sum / Math.max(1, end - start)));
      out.push(s < 0 ? s * 0x8000 : s * 0x7fff);
      this.outIndex++;
    }
    const keepFrom = Math.floor(this.outIndex * this.ratio);
    if (keepFrom > this.consumed) {
      this.buf = this.buf.slice(keepFrom - this.consumed);
      this.consumed = keepFrom;
    }
    return Int16Array.from(out);
  }
}
