#!/usr/bin/env bash
# Bật server kính (cổng 18888, sau Cloudflare tunnel: wss://api.visioncare-host.uk/v2/session).
#   ./run.sh          bật nền, chờ sẵn sàng      ./run.sh stop   tắt      ./run.sh log   xem log
# Đổi GPU/cổng: GPU=3 PORT=18888 ./run.sh. Token, khoá đọc từ .env (app tự nạp, không source ở đây).
set -euo pipefail
cd "$(dirname "$0")"
PORT=${PORT:-18888}
LOG=storage/server.log

case "${1:-start}" in
  stop) fuser -k "$PORT/tcp" >/dev/null 2>&1 && echo "Đã tắt cổng $PORT" || echo "Không có gì chạy ở cổng $PORT"; exit 0 ;;
  log)  exec tail -f "$LOG" ;;
  start) ;;
  *) echo "Dùng: ./run.sh [start|stop|log]"; exit 1 ;;
esac

if fuser "$PORT/tcp" >/dev/null 2>&1; then echo "Cổng $PORT đang chạy rồi (./run.sh stop để tắt)"; exit 1; fi

# GPU trống nhất (cần ~2 GB); máy dùng chung nên không lùi về CPU.
if [ -z "${GPU:-}" ]; then
  GPU=$(nvidia-smi --query-gpu=index,memory.free --format=csv,noheader,nounits | sort -t, -k2 -nr | head -1 | cut -d, -f1)
  free=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits -i "$GPU")
  [ "$free" -lt 2500 ] && { echo "Không GPU nào trống đủ 2,5 GB (GPU $GPU còn $free MiB)"; exit 1; }
fi

mkdir -p storage
echo "Bật server trên GPU $GPU, cổng $PORT, log: $LOG"
CUDA_VISIBLE_DEVICES=$GPU ONNX_DEVICE=cuda nohup ~/.venvs/seevia/bin/python -m uvicorn app:app \
  --host 127.0.0.1 --port "$PORT" --loop uvloop --http httptools --ws-max-size 2100000 > "$LOG" 2>&1 &
pid=$!

# Lần đầu ~3 phút (dựng sẵn câu TTS), sau đó ~25 s.
for _ in $(seq 1 300); do
  grep -q "Application startup complete" "$LOG" && break
  kill -0 $pid 2>/dev/null || { echo "Server chết khi khởi động:"; tail -20 "$LOG"; exit 1; }
  sleep 1
done
grep -q "Application startup complete" "$LOG" || { echo "Quá 5 phút chưa sẵn sàng, xem $LOG"; exit 1; }
echo "Sẵn sàng: http://127.0.0.1:$PORT  |  kính: wss://api.visioncare-host.uk/v2/session"
echo "Server lộ ra ngoài qua tunnel — test xong nhớ ./run.sh stop"
