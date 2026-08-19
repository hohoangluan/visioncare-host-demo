"""IMA ADPCM 4-bit (`WAVE_FORMAT_DVI_ADPCM`, fmt tag 0x0011), khối 256 byte.

Đây là định dạng board ESP32 dùng cho CẢ hai chiều (xem `HUONG_DAN_SERVER.md`):
board gửi lên `record.wav` nén ADPCM, và board đọc được ADPCM trả về.

🔴 KHÔNG dùng `audioop.lin2adpcm()` / `adpcm2lin()` của Python cho việc này.
Đó là biến thể riêng của Python: không có phần đầu 4 byte mỗi khối, không theo
block-align, và không tương thích fmt tag 0x0011. Giải bằng nó ra nhiễu trắng.

Bố cục một khối (mono, `block_align` byte):

    offset 0-1   int16 LE   mẫu đầu tiên (predictor khởi tạo)
    offset 2     uint8      step index khởi tạo (0..88)
    offset 3     uint8      dự trữ, = 0
    offset 4..   nibble     mỗi byte 2 mẫu, nibble THẤP đi trước

Nên một khối chứa `1 + (block_align - 4) * 2` mẫu: với 256 byte là **505** mẫu,
đúng con số `wSamplesPerBlock` trong tài liệu board.
"""

import struct

import numpy as np

# Bảng chuẩn IMA/DVI. Không phải hằng số tự chọn — đổi một số là hai đầu giải mã
# lệch nhau và ra nhiễu.
_STEP_TABLE = [
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45,
    50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230,
    253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876, 963,
    1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024,
    3327, 3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493,
    10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086,
    29794, 32767,
]
_INDEX_TABLE = [-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8]

_STEP = np.array(_STEP_TABLE, dtype=np.int32)
_INDEX = np.array(_INDEX_TABLE, dtype=np.int32)
_MAX_INDEX = len(_STEP_TABLE) - 1

# Giá trị hợp đồng với board.
FORMAT_TAG = 0x0011
BLOCK_ALIGN = 256
SAMPLE_RATE = 16000
SAMPLES_PER_BLOCK = 1 + (BLOCK_ALIGN - 4) * 2  # 505
# Board đọc header ra con số này; tài liệu ghi 8110 nên làm tròn xuống cho khớp.
AVG_BYTES_PER_SEC = int(SAMPLE_RATE * BLOCK_ALIGN / SAMPLES_PER_BLOCK)  # 8110

# Byte-rate THẬT, không làm tròn. Dùng cho phép tính đệm preroll và quy byte ra
# giây khi ghi log: sai số 0.9 byte/giây tích lại thành lệch thấy được ở câu dài.
BYTE_RATE = SAMPLE_RATE * BLOCK_ALIGN / SAMPLES_PER_BLOCK  # 8110.89...

WAV_HEADER_BYTES = 60

# Cỡ khối `data` ghi khi CHƯA biết tổng độ dài (đang stream). Board hiểu là
# "server định dạng dần" và tự chuyển sang phỏng đoán mức đệm.
_UNKNOWN_SIZE = 0xFFFFFFFF


def samples_per_block(block_align: int) -> int:
    return 1 + (block_align - 4) * 2


# ── Giải mã ──────────────────────────────────────────────────────────────


def decode_blocks(data: bytes, block_align: int = BLOCK_ALIGN) -> np.ndarray:
    """Các khối ADPCM -> mảng int16 mono.

    Vector hoá theo CHIỀU KHỐI chứ không theo chiều mẫu: trong một khối, mẫu sau
    phụ thuộc mẫu trước nên không song song được, nhưng mỗi khối lại tự mang
    predictor/index riêng nên các khối độc lập nhau hoàn toàn. Vòng lặp 504 bước
    chạy trên cả trăm khối một lúc, thay vì lặp Python trên từng mẫu.
    """
    n_blocks = len(data) // block_align
    if n_blocks == 0:
        return np.zeros(0, dtype=np.int16)

    blocks = np.frombuffer(
        data[: n_blocks * block_align], dtype=np.uint8
    ).reshape(n_blocks, block_align)

    pred = blocks[:, 0].astype(np.int32) | (blocks[:, 1].astype(np.int32) << 8)
    pred = np.where(pred >= 0x8000, pred - 0x10000, pred)  # int16 LE có dấu
    index = np.clip(blocks[:, 2].astype(np.int32), 0, _MAX_INDEX)

    payload = blocks[:, 4:]
    n_nibbles = payload.shape[1] * 2
    nibbles = np.empty((n_blocks, n_nibbles), dtype=np.int32)
    nibbles[:, 0::2] = payload & 0x0F  # nibble thấp đi trước
    nibbles[:, 1::2] = payload >> 4

    out = np.empty((n_blocks, n_nibbles + 1), dtype=np.int32)
    out[:, 0] = pred

    for i in range(n_nibbles):
        code = nibbles[:, i]
        step = _STEP[index]
        diff = step >> 3
        diff += np.where(code & 1, step >> 2, 0)
        diff += np.where(code & 2, step >> 1, 0)
        diff += np.where(code & 4, step, 0)
        pred = pred + np.where(code & 8, -diff, diff)
        np.clip(pred, -32768, 32767, out=pred)
        index = np.clip(index + _INDEX[code], 0, _MAX_INDEX)
        out[:, i + 1] = pred

    # Khối nối tiếp nhau theo thời gian nên duỗi theo hàng là đúng thứ tự.
    return out.reshape(-1).astype(np.int16)


def _riff_chunks(data: bytes):
    """Duyệt các chunk RIFF, trả (id, payload). Bỏ qua byte đệm lẻ của chunk."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("không phải file RIFF/WAVE")
    pos = 12
    while pos + 8 <= len(data):
        chunk_id = data[pos : pos + 4]
        size = struct.unpack_from("<I", data, pos + 4)[0]
        body = data[pos + 8 : pos + 8 + size]
        yield chunk_id, body
        pos += 8 + size + (size & 1)


def decode_wav(data: bytes) -> tuple[np.ndarray, int, int]:
    """WAV (PCM 16-bit HOẶC IMA ADPCM) -> (mẫu int16 interleaved, sample_rate, channels).

    Tự đọc RIFF thay vì dùng module `wave` của Python: `wave` chỉ mở được
    `WAVE_FORMAT_PCM` và ném `wave.Error: unknown format: 17` ngay khi gặp file
    board gửi lên. Tự đọc còn lấy được khối `fact` để cắt đuôi cho đúng.
    """
    fmt_tag = channels = sample_rate = bits = 0
    block_align = BLOCK_ALIGN
    fact_samples: int | None = None
    payload = b""

    for chunk_id, body in _riff_chunks(data):
        if chunk_id == b"fmt " and len(body) >= 16:
            fmt_tag, channels, sample_rate, _, block_align, bits = struct.unpack_from(
                "<HHIIHH", body, 0
            )
        elif chunk_id == b"fact" and len(body) >= 4:
            fact_samples = struct.unpack_from("<I", body, 0)[0]
        elif chunk_id == b"data":
            payload = body

    if not channels:
        raise ValueError("WAV thiếu khối fmt")

    if fmt_tag == FORMAT_TAG:
        if channels != 1:
            # ADPCM stereo cài răng nibble theo kênh; tách ra là việc khác hẳn
            # và board cũng không sinh ra file như vậy.
            raise ValueError("chỉ hỗ trợ IMA ADPCM mono")
        samples = decode_blocks(payload, block_align)
        if fact_samples is not None and 0 < fact_samples <= samples.size:
            # Khối cuối được đệm cho tròn `block_align`. ffmpeg KHÔNG cắt theo
            # `fact` nên trả dư tới 504 mẫu; đọc `fact` thì cắt đúng.
            samples = samples[:fact_samples]
        return samples, sample_rate, 1

    if fmt_tag in (0x0001, 0xFFFE) and bits == 16:
        return np.frombuffer(payload, dtype="<i2"), sample_rate, channels

    raise ValueError(f"định dạng WAV chưa hỗ trợ: tag=0x{fmt_tag:04x} bits={bits}")


# ── Mã hoá ───────────────────────────────────────────────────────────────


class Encoder:
    """PCM 16-bit mono -> khối ADPCM, giữ trạng thái để nén được theo luồng.

    Vòng lặp Python trên từng mẫu, không vector hoá được: `index` mang qua giữa
    các khối (đặt lại về 0 mỗi 31 ms sinh ra tiếng lách tách ở biên khối), mà
    mang qua thì khối sau phụ thuộc khối trước. Đo được ~1 µs/mẫu ≈ 60 lần thời
    gian thực, trong khi TTS chỉ sinh nhanh ~2,5 lần — nên khâu này không phải
    chỗ tốn thời gian.
    """

    def __init__(self, block_align: int = BLOCK_ALIGN) -> None:
        self._block_align = block_align
        self._samples_per_block = samples_per_block(block_align)
        self._pending: list[int] = []
        self._index = 0
        self._odd = b""  # nửa mẫu lẻ còn treo ở cuối mảnh trước

    def encode(self, pcm: bytes) -> bytes:
        """Nhận PCM 16-bit LE, trả các khối ĐẦY ĐỦ nén được từ đó.

        Mẫu dư chưa đủ một khối được giữ lại cho lần gọi sau, nên nối các lần
        trả về lại là đúng một luồng khối liên tục — không mẫu nào rơi ở biên.

        Mảnh vào không bắt buộc chẵn byte. Nguồn hiện tại luôn đưa số byte chẵn,
        nhưng một mảnh lẻ mà ném `ValueError` thì nó nổ ở GIỮA luồng — lúc header
        200 đã gửi và không đổi thành câu báo lỗi được nữa. Giữ lại nửa mẫu treo
        và ghép vào mảnh sau thì rẻ hơn hẳn cái rủi ro đó.
        """
        if pcm:
            data = self._odd + pcm if self._odd else pcm
            usable = len(data) - (len(data) & 1)
            self._odd = data[usable:]
            if usable:
                self._pending.extend(np.frombuffer(data[:usable], dtype="<i2").tolist())
        return self._drain()

    def flush(self) -> bytes:
        """Khối cuối, đệm cho tròn `block_align`.

        Đệm bằng một đoạn dốc từ mẫu cuối về 0, không phải nhảy thẳng về 0 và
        cũng không giữ nguyên mẫu cuối. Nhảy về 0 là một bậc thang phải mã hoá,
        nghe thành tiếng "tách"; giữ nguyên mẫu cuối thì để lại tới 31 ms lệch
        một mức DC rồi mới cắt, cũng là một bậc thang y như vậy nhưng ở cuối.
        Dốc dần thì cả hai đều không xảy ra.
        """
        if not self._pending:
            return b""
        remainder = len(self._pending) % self._samples_per_block
        if remainder:
            pad = self._samples_per_block - remainder
            last = self._pending[-1]
            self._pending.extend(
                int(last * (pad - i) / (pad + 1)) for i in range(pad)
            )
        return self._drain()

    def _drain(self) -> bytes:
        per_block = self._samples_per_block
        pending = self._pending
        n_blocks = len(pending) // per_block
        if n_blocks == 0:
            return b""

        step_table = _STEP_TABLE
        index_table = _INDEX_TABLE
        out = bytearray()
        index = self._index

        for b in range(n_blocks):
            block = pending[b * per_block : (b + 1) * per_block]
            pred = block[0]
            out += struct.pack("<hBB", pred, index, 0)

            nibbles = bytearray()
            for sample in block[1:]:
                step = step_table[index]
                diff = sample - pred
                if diff < 0:
                    sign = 8
                    diff = -diff
                else:
                    sign = 0

                delta = 0
                vpdiff = step >> 3
                if diff >= step:
                    delta = 4
                    diff -= step
                    vpdiff += step
                if diff >= step >> 1:
                    delta |= 2
                    diff -= step >> 1
                    vpdiff += step >> 1
                if diff >= step >> 2:
                    delta |= 1
                    vpdiff += step >> 2

                pred = pred - vpdiff if sign else pred + vpdiff
                if pred > 32767:
                    pred = 32767
                elif pred < -32768:
                    pred = -32768

                delta |= sign
                index += index_table[delta]
                if index < 0:
                    index = 0
                elif index > _MAX_INDEX:
                    index = _MAX_INDEX
                nibbles.append(delta)

            # Nibble thấp đi trước: gộp từng cặp thành một byte.
            out += bytes(
                nibbles[i] | (nibbles[i + 1] << 4) for i in range(0, len(nibbles), 2)
            )

        self._index = index
        del pending[: n_blocks * per_block]
        return bytes(out)


def encode_blocks(pcm: bytes, block_align: int = BLOCK_ALIGN) -> bytes:
    """Nén trọn một mảng PCM thành các khối ADPCM (tiện cho test/CLI)."""
    encoder = Encoder(block_align)
    return encoder.encode(pcm) + encoder.flush()


def ensure_wav(data: bytes, content_type: str | None = None) -> bytes:
    """Thân phần `audio` của board -> WAV mà `decode_wav()` đọc được.

    Board KHÔNG gửi WAV nữa. Header WAV phải đi trước dữ liệu, mà ba trường của
    nó (`RIFF size`, `data size`, số mẫu trong `fact`) chỉ biết được khi đã thu
    xong — tức phải đợi người dùng nhả nút rồi mới gửi được byte đầu tiên. Trên
    đường lên 9 KB/s thì 26 KB ADPCM của một câu 3 giây là gần 3 giây chết.

    Nên board gửi ADPCM **thô**, đẩy từng khối 256 byte ngay trong lúc còn đang
    thu, và khai tham số codec trong `Content-Type` của phần multipart:

        audio/x-adpcm-ima; rate=16000; channels=1; block=256

    Header dựng lại ở đây tốn vài chục micro giây và tổng độ dài thì lúc này đã
    biết chắc.

    Vẫn nhận WAV như cũ: firmware cũ hơn, và mọi phép thử bằng `curl` với file
    `.wav` sẵn có, đều phải chạy tiếp không sửa gì.
    """
    if data[:4] == b"RIFF":
        return data

    block_align = BLOCK_ALIGN
    sample_rate = SAMPLE_RATE
    for part in (content_type or "").split(";")[1:]:
        key, _, value = part.partition("=")
        key, value = key.strip().lower(), value.strip()
        try:
            if key == "block":
                block_align = int(value)
            elif key == "rate":
                sample_rate = int(value)
        except ValueError:
            # Tham số hỏng thì dùng giá trị hợp đồng, đừng làm hỏng cả request.
            pass

    # 🔴 Cắt cho tròn khối. ADPCM không có mẫu đồng bộ: ranh giới khối do
    # `block_align` và điểm bắt đầu quyết định hoàn toàn, nên một khối cụt ở
    # cuối làm bộ giải đọc 4 byte giữa dữ liệu thành predictor/step index và
    # nhả ra nhiễu thuần. Board luôn đệm khối cuối cho tròn, phần dư ở đây chỉ
    # có thể là byte rơi vãi.
    usable = len(data) // block_align * block_align
    if usable != len(data):
        data = data[:usable]

    return wav_header(len(data), sample_rate, block_align) + data


def wav_header(
    data_bytes: int | None = None,
    sample_rate: int = SAMPLE_RATE,
    block_align: int = BLOCK_ALIGN,
    sample_count: int | None = None,
) -> bytes:
    """60 byte header WAV IMA ADPCM.

    `data_bytes=None` nghĩa là đang stream, chưa biết tổng độ dài: ghi
    `0xFFFFFFFF` để board hiểu "server định dạng dần". Header này phải rời
    server TRƯỚC, đừng giữ lại chờ gom cả file — board đọc nó ngay trên luồng.

    `sample_count` là số mẫu THẬT, ghi vào khối `fact`. Bỏ trống thì suy ra từ
    số khối, tức là tính cả phần đệm của khối cuối — dư tối đa 504 mẫu (~31 ms).
    Đưa vào khi biết chính xác (bên mã hoá có đếm) thì bên giải mã cắt đúng.
    """
    per_block = samples_per_block(block_align)
    if data_bytes is None:
        data_size = _UNKNOWN_SIZE
        fact_samples = _UNKNOWN_SIZE
        riff_size = _UNKNOWN_SIZE
    else:
        data_size = data_bytes
        if sample_count is None:
            fact_samples = data_bytes // block_align * per_block
        else:
            fact_samples = sample_count
        riff_size = WAV_HEADER_BYTES - 8 + data_size

    return b"".join((
        b"RIFF",
        struct.pack("<I", riff_size),
        b"WAVE",
        b"fmt ",
        struct.pack("<I", 20),  # 20, không phải 16: ADPCM có cbSize + wSamplesPerBlock
        struct.pack(
            "<HHIIHHHH",
            FORMAT_TAG,
            1,                                          # nChannels
            sample_rate,
            int(sample_rate * block_align / per_block),  # nAvgBytesPerSec
            block_align,
            4,                                          # wBitsPerSample
            2,                                          # cbSize
            per_block,                                  # wSamplesPerBlock
        ),
        b"fact",
        struct.pack("<I", 4),
        struct.pack("<I", fact_samples),
        b"data",
        struct.pack("<I", data_size),
    ))
