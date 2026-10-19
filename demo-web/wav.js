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
