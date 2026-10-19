# Voice server v2 trên GPU. Môi trường thật đang chạy: venv ~/.venvs/seevia, Python 3.11,
# torch 2.14.x bản CUDA 13 (kéo theo các gói nvidia-*-cu13), onnxruntime-gpu 1.31.
# Image dưới đây dựng lại đúng thứ tự cài đó; CHƯA build thử trong phiên này (máy dev không có
# docker) — kiểm lại khi build lần đầu.
FROM nvidia/cuda:13.0.0-cudnn-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# libsndfile/espeak-ng: thư viện âm thanh + phonemizer mà TTS (vieneu) cần.
# libglib2.0-0: opencv-python-headless. curl: healthcheck. Ubuntu 24.04 có Python 3.12 (venv dev
# là 3.11): chưa thử các gói với 3.12.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libsndfile1 espeak-ng curl ca-certificates \
       libglib2.0-0 python3 python3-venv python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

# THỨ TỰ CÀI QUAN TRỌNG (đã gặp trên máy dev):
#  1) torch bản CUDA 13 TRƯỚC, từ index riêng của PyTorch. Cài torch sau/thường sẽ hạ 6 gói
#     nvidia-* đang dùng chung với onnxruntime-gpu. vieneu chỉ cần torch cho codec (neucodec).
#  2) requirements.txt (vieneu kéo `onnxruntime` CPU vào).
#  3) gỡ onnxruntime CPU và cài lại onnxruntime-gpu: hai gói cùng tên module, cài sau đè cài trước;
#     nếu để CPU thắng thì text-det/hazard rơi về CPU (vi phạm luật "luôn GPU").
COPY requirements.txt ./
RUN pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu130 \
    && pip install -r requirements.txt \
    && pip uninstall -y onnxruntime onnxruntime-gpu \
    && pip install "onnxruntime-gpu[cuda,cudnn]"

COPY . .

# Trọng số model (models/stt, models/vad, models/hazard, models/text_det, models/.cache) không nằm
# trong image: mount vào /app/models. `certs/uit-ca-bundle.pem` (llm.uit.edu.vn) cũng phải có.
RUN useradd --system --uid 1000 --create-home app \
    && mkdir -p /app/storage /app/models \
    && chown -R app:app /app/storage /app/models
USER app

# Biến môi trường (đặt lúc chạy, không đặt giá trị bí mật ở đây):
#   VISIONCARE_DEVICE_CLIENT_TOKEN  bắt buộc; rỗng = mọi endpoint kính trả 503
#   LLM_API_KEY, CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID   xem .env.example
#   ONNX_DEVICE=cuda  ONNX_GPU_ID=<chỉ số TƯƠNG ĐỐI theo CUDA_VISIBLE_DEVICES>
#   HF_HUB_OFFLINE=1  sau khi models/.cache/huggingface đã đủ file (lần đầu cần mạng)
# GPU dùng chung: chạy với `--gpus device=<id trống>`, server cần ~1,8 GB VRAM.
EXPOSE 18888

HEALTHCHECK --interval=15s --timeout=5s --start-period=240s --retries=5 \
    CMD curl -fsS http://127.0.0.1:18888/health || exit 1

# Khởi động lần đầu ~3 phút (dựng sẵn 113 câu TTS), các lần sau ~25 s.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "18888", "--loop", "uvloop", "--http", "httptools"]
