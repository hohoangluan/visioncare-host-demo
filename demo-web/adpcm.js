// Giải mã IMA ADPCM 4-bit, mono, khối 256 byte, KHÔNG header — đúng định dạng
// server trả trên WS (khung 0x02) và `pipeline/adpcm.py::decode_blocks`.
//
// Bố cục một khối (xem docstring của pipeline/adpcm.py):
//   byte 0-1  int16 LE  mẫu đầu (predictor khởi tạo)
//   byte 2    uint8     step index khởi tạo (0..88)
//   byte 3    dự trữ
//   byte 4..  nibble    mỗi byte 2 mẫu, nibble THẤP đi trước
// Mỗi khối tự đủ nên giải từng khối độc lập; 256 byte = 505 mẫu.

export const BLOCK_ALIGN = 256;
export const SAMPLE_RATE = 16000;
export const SAMPLES_PER_BLOCK = 1 + (BLOCK_ALIGN - 4) * 2;

// Bảng chuẩn IMA/DVI: đổi một số là hai đầu lệch nhau và ra nhiễu.
const STEP = new Int32Array([
  7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45,
  50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230,
  253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876, 963,
  1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024,
  3327, 3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493,
  10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086,
  29794, 32767,
]);
const INDEX = new Int8Array([-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8]);

/** Byte ADPCM (bội của 256) -> Float32 [-1, 1]. Phần dư lẻ khối bị bỏ qua. */
export function decodeBlocks(bytes, blockAlign = BLOCK_ALIGN) {
  const nBlocks = Math.floor(bytes.length / blockAlign);
  const perBlock = 1 + (blockAlign - 4) * 2;
  const out = new Float32Array(nBlocks * perBlock);
  let o = 0;
  for (let b = 0; b < nBlocks; b++) {
    const base = b * blockAlign;
    let pred = (bytes[base] | (bytes[base + 1] << 8)) << 16 >> 16; // int16 LE có dấu
    let index = Math.min(88, bytes[base + 2]);
    out[o++] = pred / 32768;
    for (let i = base + 4; i < base + blockAlign; i++) {
      const byte = bytes[i];
      for (let half = 0; half < 2; half++) {
        const code = half === 0 ? byte & 0x0f : byte >> 4;
        const step = STEP[index];
        let diff = step >> 3;
        if (code & 1) diff += step >> 2;
        if (code & 2) diff += step >> 1;
        if (code & 4) diff += step;
        pred += code & 8 ? -diff : diff;
        pred = pred > 32767 ? 32767 : pred < -32768 ? -32768 : pred;
        index += INDEX[code];
        index = index < 0 ? 0 : index > 88 ? 88 : index;
        out[o++] = pred / 32768;
      }
    }
  }
  return out;
}
