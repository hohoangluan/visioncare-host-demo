#!/usr/bin/env bash
# measure_chunked_end.sh — đo G10: miếng kết thúc chunked "0\r\n\r\n" có tới
# client hay không, khi gọi POST /process.
#
# Đo, không sửa. Không kết luận thay người đọc — script chỉ in bằng chứng thô
# (toàn bộ output --trace-ascii của curl, dump byte thật trên dây) rồi tự tìm
# terminator trong đó, nhưng người đọc báo cáo phải tự nhìn raw output để xác
# nhận, không tin lời script.
#
# Cách dùng:
#   bash tools/measure_chunked_end.sh <endpoint> [audio_file] [image_file]
#
# Ví dụ:
#   bash tools/measure_chunked_end.sh http://localhost:8000/process
#   bash tools/measure_chunked_end.sh https://api.visioncare-host.uk/process
#
# Ghi chú BẮT BUỘC (HUONG_DAN_SERVER.md:177, task file 2.1 KHÔNG có cờ này):
#   -H "Expect:"  — curl tự thêm "Expect: 100-continue" cho body > 1KB.
#   Server này không bao giờ trả "100 Continue" nên thiếu cờ này curl sẽ TREO
#   tới hết timeout, và một lần treo dễ bị đọc nhầm thành "terminator không
#   tới" — đó là kết luận SAI (false negative), không phải cùng hiện tượng.

set -u

ENDPOINT="${1:?usage: measure_chunked_end.sh <endpoint> [audio_file] [image_file]}"
AUDIO="${2:-warm_melodic.wav}"
IMAGE="${3:-tests/fixtures/space_room.jpg}"

if [[ ! -f "$AUDIO" ]]; then
  echo "LỖI: không thấy file audio '$AUDIO'" >&2
  exit 2
fi
if [[ ! -f "$IMAGE" ]]; then
  echo "LỖI: không thấy file ảnh '$IMAGE'" >&2
  exit 2
fi

echo "=================================================================="
echo "G10 — đo miếng kết thúc chunked"
echo "Endpoint : $ENDPOINT"
echo "Audio    : $AUDIO"
echo "Image    : $IMAGE"
echo "Thời điểm: $(date -u +'%Y-%m-%dT%H:%M:%SZ') (UTC)"
echo "=================================================================="

RAW_FILE="$(mktemp)"
BODY_FILE="$(mktemp)"

# Trần: Cloudflare tự ngắt ở 100s (lỗi 524), header board tự bỏ cuộc ở 90s.
# Đặt --max-time dưới cả hai mốc đó để không bao giờ đợi tới khi tunnel tự cắt
# — một 524 do chính script này gây ra sẽ làm nhiễu kết quả.
MAX_TIME=95

echo
echo "--- Lệnh curl thật sự chạy ---"
# LƯU Ý (đã kiểm chứng lại — sửa hiểu nhầm trước đó): '-v' một mình KHÔNG in
# byte khung chunked ra stderr, nó chỉ in header/metadata. Cờ '--raw' KHÔNG
# tắt việc đọc khung chunked; nó tắt "transfer decoding" — dùng
# '-v --raw -o file' thì libcurl GIỮ NGUYÊN byte khung chunked (kể cả
# '0\r\n\r\n') Ở CUỐI FILE BODY thay vì tự giải mã/loại bỏ chúng đi. Vậy lệnh
# mẫu 'curl -v --raw ... -o /dev/null' ở task file 2.1 sai ở chỗ khác: nó đổ
# body (và cả terminator) vào /dev/null. Chỉ cần đổi thành '-o somefile' rồi
# soi đuôi file đó (vd. 'tail -c 8 somefile | xxd') là thấy terminator, không
# cần đổi cờ nào cả. Script này chọn '--trace-ascii' vì nó gom cả header,
# chunk-size và terminator vào MỘT chỗ dễ đọc — không phải vì '-v --raw'
# không làm được việc này.
CMD=(curl --trace-ascii "$RAW_FILE" -X POST "$ENDPOINT" \
     -H 'Expect:' \
     -H 'Accept: audio/wav;codec=ima_adpcm, audio/mpeg, audio/wav' \
     -F "audio=@${AUDIO};type=audio/wav" \
     -F "image=@${IMAGE};type=image/jpeg" \
     --max-time "$MAX_TIME" \
     -o "$BODY_FILE")
printf '%q ' "${CMD[@]}"
echo
echo "-------------------------------"
echo

START_TS=$(date +%s)
"${CMD[@]}"
CURL_EXIT=$?
END_TS=$(date +%s)
ELAPSED=$((END_TS - START_TS))

echo "curl exit code : $CURL_EXIT"
echo "Thời gian chạy : ${ELAPSED}s (trần đặt: ${MAX_TIME}s)"
echo

echo "=================================================================="
echo "RAW TRACE (--trace-ascii, byte thật trên dây) — 80 dòng cuối"
echo "=================================================================="
tail -80 "$RAW_FILE"
echo "=================================================================="
echo "RAW TRACE (--trace-ascii) — TOÀN BỘ (để đối chiếu)"
echo "=================================================================="
cat "$RAW_FILE"
echo "=================================================================="

echo
echo "Kích thước body đã tải về: $(wc -c < "$BODY_FILE") bytes"
echo
if grep -q 'left intact' "$RAW_FILE" 2>/dev/null; then
  echo "Ghi chú: trace có dòng 'Connection ... left intact' — curl coi kết nối"
  echo "vẫn dùng lại được (không phải bị TCP RST/FIN đóng từ phía server)."
fi
echo

echo "=================================================================="
echo "KẾT QUẢ TÌM TERMINATOR"
echo "=================================================================="
# --trace-ascii chỉ in offset + phần ASCII giải mã được (không in cột hex).
# Miếng kết thúc chunked trên dây là đúng 5 byte: '0' CR LF CR LF (= chunk-size
# "0" rồi tới CRLF rồi tới CRLF trailer rỗng). Trong trace nó hiện thành một
# khối riêng "<= Recv data, 5 bytes (0x5)" mà dòng offset 0000 chỉ có ký tự
# "0" (CR/LF không in được nên bị cắt cụt ngay sau đó). Đây là chữ ký duy nhất
# — không khối dữ liệu âm thanh thật nào chỉ có 5 byte và bắt đầu bằng "0".
if grep -A2 -E '<= Recv data, 5 bytes \(0x5\)' "$RAW_FILE" 2>/dev/null | grep -qE '^0000: 0[[:space:]]*$'; then
  echo "TÌM THẤY: khối 5 byte '0\\r\\n\\r\\n' (miếng kết thúc chunked) xuất hiện"
  echo "trong trace thô ở trên dây — xem khối '<= Recv data, 5 bytes (0x5)' ở"
  echo "cuối phần trace phía trên."
  FOUND=yes
elif grep -q 'Transfer-Encoding: chunked' "$RAW_FILE" && [[ $CURL_EXIT -eq 0 ]]; then
  echo "GIÁN TIẾP (không thấy hex trực tiếp nhưng có bằng chứng mạnh):"
  echo "response dùng chunked encoding, curl thoát mã 0 (thành công, KHÔNG"
  echo "phải do --max-time ${MAX_TIME}s cắt ngang — xem 'Thời gian chạy' ở trên,"
  echo "nếu << ${MAX_TIME}s thì chắc chắn không phải timeout)."
  echo "libcurl chỉ coi một response chunked là ĐÃ NHẬN ĐỦ khi tự đọc được"
  echo "khối 0-length cuối; nếu không có terminator, curl phải đợi server tự"
  echo "đóng TCP hoặc đợi tới --max-time rồi báo lỗi (exit != 0, thường 28)."
  echo "\"Connection # left intact\" (nếu có ở trace) càng củng cố: curl coi"
  echo "response đã đọc xong và giữ kết nối lại để tái dùng — hành vi này chỉ"
  echo "xảy ra sau khi đọc được terminator, không xảy ra khi phải đợi TCP close."
  FOUND=yes-inferred
else
  echo "KHÔNG kết luận được terminator có tới hay không từ log này."
  FOUND=unknown
fi

if [[ $CURL_EXIT -eq 28 ]]; then
  echo "CHÚ Ý: curl exit=28 = timeout (--max-time ${MAX_TIME}s hết hạn)."
  echo "Đây là dấu hiệu MẠNH rằng terminator KHÔNG tới — curl phải đợi tới khi"
  echo "hết giờ thay vì server tự đóng luồng."
  FOUND=no
fi

echo
echo "Kết luận sơ bộ của script: $FOUND"
echo "(Đây là gợi ý, KHÔNG phải phán quyết cuối — đọc raw output ở trên để tự"
echo " xác nhận có \"0\\r\\n\\r\\n\" hay curl có tự đóng gọn không.)"
echo "=================================================================="

rm -f "$RAW_FILE" "$BODY_FILE"
