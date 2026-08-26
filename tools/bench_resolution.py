"""F5 — chọn độ phân giải bằng SỐ ĐO, không bằng lập luận.

Câu hỏi phải trả lời
--------------------
Hôm nay board chụp VGA cho mọi lượt và chỉ lên HD khi server xin thêm một
khung (`frame_request` tier=high). Vòng xin đó tốn một lượt đi-về qua SSE.
Câu hỏi là có tồn tại MỘT độ phân giải dùng chung đủ tốt cho mọi chức năng
đọc ảnh hay không — và nếu không, chức năng nào thật sự cần tầng riêng.

Ba trục phải cân, không được bỏ trục nào:

    độ chính xác   ảnh nhỏ hơn thì OCR đọc sai — nhưng sai bao nhiêu thì
                   CHƯA AI ĐO. T15/H1 chỉnh trên 1280x720.
    tốc độ         mỗi KB thêm là thời gian đẩy thêm. Board đo được 24.3 KB/s
                   với gói 512 B + NoDelay (đúng cách `/process` đang ghi),
                   34.3 KB/s với gói 4096 B.
    RAM            đệm JPEG nằm ở PSRAM (6.29 MB rảnh) nên độ phân giải KHÔNG
                   đụng tới trần 2 phiên TLS. Trục này ghi ra để khỏi ai đó
                   dùng nhầm nó làm lý do — nút thắt RAM nằm chỗ khác.

Vì sao lái camera thật thay vì thu nhỏ ảnh bằng PIL
---------------------------------------------------
Thu nhỏ một ảnh HD xuống 640x480 KHÔNG cho ra thứ mà cảm biến sinh ra ở
FRAMESIZE_VGA. Sensor đổi cả binning, thời gian phơi sáng và mức gain theo
độ phân giải, còn bộ nén JPEG thì làm việc trên dữ liệu khác hẳn. Đo trên ảnh
thu nhỏ là đo một thiết bị không tồn tại.

Nên tool này lái ĐÚNG con camera trên kính, qua LAN:

    GET /status                        -> đọc framesize đang đặt
    GET /control?var=framesize&val=N   -> đổi tầng
    GET /capture                       -> lấy một khung JPEG

Cách chạy
---------
Chĩa kính vào cảnh thử rồi GIỮ YÊN. Mỗi cảnh chạy một lần:

    python tools/bench_resolution.py --board 192.168.2.88 --scene bien-hieu
    python tools/bench_resolution.py --score --scene bien-hieu --functions hazard
    python tools/bench_resolution.py --score --scene bien-hieu --functions ocr,space
    python tools/bench_resolution.py --report

`hazard` chạy YOLO cục bộ: miễn phí, chạy lại bao nhiêu lần cũng được.
`ocr`/`space`/`find`/`money` gọi Gemini thật nên TỐN HẠN MỨC — tách riêng cờ
để đừng đốt hạn mức mỗi lần chỉnh tool.

🔴 Một điều tool này KHÔNG làm được
-----------------------------------
Nó không biết câu trả lời đúng là gì. Nó in ra thứ mỗi chức năng nói ở mỗi
tầng, cạnh nhau, để NGƯỜI đối chiếu với cảnh thật. "Độ chính xác" của một câu
mô tả không gian không có thước đo tự động nào trung thực cả.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# 🔴 stdout của Windows là cp1252. Không có dòng này thì tool chạy XONG việc
# rồi chết ở lệnh `print` cuối, nhìn từ ngoài giống hệt "tool hỏng".
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

# ─── các tầng cảm biến ────────────────────────────────────────────────────
#
# Giá trị `framesize_t` của esp32-camera. Chỉ liệt kê những tầng có ý nghĩa
# cho thiết bị này: dưới VGA thì chữ vỡ hết, trên UXGA thì cảm biến không có.


@dataclass(frozen=True)
class Tier:
    name: str
    value: int
    width: int
    height: int

    @property
    def pixels(self) -> int:
        return self.width * self.height


# 🔴 Số thứ tự KHÔNG phải thứ tự "hiển nhiên" của các tên quen thuộc. Bản
# esp32-camera đi kèm core 3.3.10 chèn thêm `FRAMESIZE_128X128` (chỉ số 2) và
# `FRAMESIZE_320X320` (chỉ số 7) vào giữa, nên mọi tầng từ QCIF trở lên bị
# đẩy lùi HAI bậc so với bảng cũ mà phần lớn ví dụ trên mạng đang chép.
#
# Đã dính đúng bẫy này lần đầu chạy tool: xin VGA nhận về 400x296 (CIF), xin
# UXGA nhận về 1280x720 (HD) — lệch đều hai bậc ở cả sáu tầng. Nguồn sự thật:
# `tools/esp32s3-libs/<ver>/include/espressif__esp32-camera/driver/include/sensor.h`.
#
# Vì vậy `capture_sweep()` LUÔN đọc lại kích thước thật từ JPEG nhận được và
# kêu lên khi lệch, thay vì tin con số xin đi.
TIERS: tuple[Tier, ...] = (
    Tier("VGA", 10, 640, 480),
    Tier("SVGA", 11, 800, 600),
    Tier("XGA", 12, 1024, 768),
    Tier("HD", 13, 1280, 720),
    Tier("SXGA", 14, 1280, 1024),
    Tier("UXGA", 15, 1600, 1200),
)

TIERS_BY_NAME = {t.name: t for t in TIERS}
TIERS_BY_VALUE = {t.value: t for t in TIERS}

# Board đo được 2026-08-26 bằng phím 'i' (gói 512 B + NoDelay, đúng cách
# `/process` ghi). Phím 'u' với gói 4096 B cho 34.3 KB/s — chênh 29%, và đó là
# một việc phải sửa riêng, không phải giả định của bảng này.
DEFAULT_UPLOAD_KBPS = 24.3

DEFAULT_OUT = Path("storage") / "resolution_bench"
REPORT_PATH = Path("docs") / "tasks" / "measurements" / "F5-resolution.md"

# Câu lệnh mặc định cho từng chức năng. Đổi được bằng --ask.
DEFAULT_ASK = {
    "ocr": "đọc chữ trong ảnh",
    "space": "trước mặt tôi có gì",
    "find": "tìm giúp tôi cái cốc",
    "money": "đây là tờ bao nhiêu",
}

ALL_FUNCTIONS = ("hazard", "ocr", "space", "find", "money")

# Chức năng gọi Gemini -> tốn hạn mức. `hazard` chạy ONNX cục bộ nên không.
BILLED_FUNCTIONS = frozenset({"ocr", "space", "find", "money"})


# ─── nói chuyện với board ─────────────────────────────────────────────────


class Board:
    """Camera trên kính, điều khiển qua web server có sẵn của firmware."""

    def __init__(self, host: str, timeout: float = 15.0) -> None:
        self._base = f"http://{host}"
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def framesize(self) -> int | None:
        """Tầng board đang đặt, hoặc None nếu không đọc được."""
        try:
            data = self._client.get(f"{self._base}/status").json()
        except Exception as exc:  # noqa: BLE001
            print(f"  không đọc được /status: {exc}")
            return None
        value = data.get("framesize")
        return int(value) if isinstance(value, int) else None

    def set_framesize(self, tier: Tier) -> bool:
        try:
            resp = self._client.get(
                f"{self._base}/control", params={"var": "framesize", "val": tier.value}
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  đổi sang {tier.name} hỏng: {exc}")
            return False
        return resp.status_code == 200

    def capture(self) -> tuple[bytes, float] | None:
        """Một khung JPEG + số mili giây board mất để trả về."""
        started = time.monotonic()
        try:
            resp = self._client.get(f"{self._base}/capture")
        except Exception as exc:  # noqa: BLE001
            print(f"  chụp hỏng: {exc}")
            return None
        if resp.status_code != 200 or not resp.content:
            print(f"  chụp trả HTTP {resp.status_code}, {len(resp.content)} byte")
            return None
        return resp.content, (time.monotonic() - started) * 1000.0


# ─── đo trên chính ảnh ────────────────────────────────────────────────────


@dataclass
class Shot:
    tier: str
    index: int
    path: str
    jpeg_bytes: int
    capture_ms: float
    width: int = 0
    height: int = 0
    sharpness: float = 0.0
    brightness: float = 0.0
    scores: dict = field(default_factory=dict)


def _measure_image(data: bytes) -> tuple[int, int, float, float]:
    """(rộng, cao, độ nét, độ sáng) — dùng ĐÚNG hàm cổng chất lượng đang dùng.

    Cố ý gọi `image_quality.measure()` chứ không tự viết lại: con số phải so
    sánh được với `IMAGE_MIN_SHARPNESS`, và nếu công thức ở kia đổi thì bảng
    này phải đổi theo, không được lệch âm thầm.
    """
    from PIL import Image

    from pipeline import image_quality

    with Image.open(io.BytesIO(data)) as img:
        width, height = img.size

    measured = image_quality.measure(data)
    if measured is None:
        return width, height, 0.0, 0.0
    sharpness, brightness = measured
    return width, height, sharpness, brightness


# ─── giai đoạn 1: quét tầng, chụp ─────────────────────────────────────────


def capture_sweep(
    board: Board,
    scene: str,
    out_dir: Path,
    tiers: list[Tier],
    shots: int,
    settle_shots: int,
) -> list[Shot]:
    """Quét từng tầng trên CÙNG một cảnh. Giữ kính yên suốt quá trình."""
    scene_dir = out_dir / scene
    scene_dir.mkdir(parents=True, exist_ok=True)

    original = board.framesize()
    if original is not None:
        name = TIERS_BY_VALUE[original].name if original in TIERS_BY_VALUE else str(original)
        print(f"Tầng board đang đặt: {name} — sẽ trả về sau khi đo xong")

    collected: list[Shot] = []
    try:
        for tier in tiers:
            print(f"\n── {tier.name} {tier.width}x{tier.height} ──")
            if not board.set_framesize(tier):
                print("  bỏ qua tầng này")
                continue

            # Bỏ vài khung đầu: đổi độ phân giải là sensor phải chỉnh lại AEC
            # và cân bằng trắng. Khung ngay sau lệnh đổi thường tối hoặc ám
            # màu, và nó sẽ kéo lệch cả cột độ sáng lẫn cột độ nét.
            #
            # 🔴 Ba khung KHÔNG đủ — đo được ở lần chạy đầu: độ sáng còn nhảy
            # 35 → 121 giữa hai ảnh liên tiếp của cùng một tầng, mà độ nét thì
            # đi theo độ sáng. Cột nào cũng vô nghĩa khi AEC chưa đứng. Nếu
            # bảng vẫn thấy độ sáng lệch nhiều giữa các ảnh cùng tầng thì tăng
            # `--settle` tiếp, đừng đọc bảng đó.
            for _ in range(settle_shots):
                board.capture()
                time.sleep(0.15)

            for index in range(shots):
                got = board.capture()
                if got is None:
                    continue
                data, capture_ms = got
                width, height, sharpness, brightness = _measure_image(data)

                path = scene_dir / f"{tier.name}-{index}.jpg"
                path.write_bytes(data)

                shot = Shot(
                    tier=tier.name,
                    index=index,
                    path=str(path),
                    jpeg_bytes=len(data),
                    capture_ms=capture_ms,
                    width=width,
                    height=height,
                    sharpness=sharpness,
                    brightness=brightness,
                )
                collected.append(shot)
                print(
                    f"  [{index}] {width}x{height}  {len(data):>7,} B  "
                    f"chụp {capture_ms:>6.0f} ms  nét {sharpness:>8.1f}  "
                    f"sáng {brightness:>5.1f}"
                )

                if (width, height) != (tier.width, tier.height):
                    # Sensor từ chối tầng này (một số module không có đủ mọi
                    # tầng). Ghi ra chứ không nuốt: bảng sẽ có hai dòng cùng
                    # kích thước và người đọc phải biết vì sao.
                    print(
                        f"      ⚠ xin {tier.width}x{tier.height} nhưng nhận "
                        f"{width}x{height} — sensor không có tầng này"
                    )
    finally:
        if original is not None and original in TIERS_BY_VALUE:
            board.set_framesize(TIERS_BY_VALUE[original])
            print(f"\nĐã trả board về {TIERS_BY_VALUE[original].name}")

    _save_meta(scene_dir, collected)
    return collected


def _meta_path(scene_dir: Path) -> Path:
    return scene_dir / "meta.json"


def _save_meta(scene_dir: Path, shots: list[Shot]) -> None:
    payload = [
        {
            "tier": s.tier,
            "index": s.index,
            "path": s.path,
            "jpeg_bytes": s.jpeg_bytes,
            "capture_ms": s.capture_ms,
            "width": s.width,
            "height": s.height,
            "sharpness": s.sharpness,
            "brightness": s.brightness,
            "scores": s.scores,
        }
        for s in shots
    ]
    _meta_path(scene_dir).write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def _load_meta(scene_dir: Path) -> list[Shot]:
    path = _meta_path(scene_dir)
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Shot(**item) for item in raw]


# ─── giai đoạn 2: cho từng chức năng đọc từng ảnh ─────────────────────────


def _run_hazard(data: bytes) -> dict:
    """YOLO cục bộ + đúng bộ luật chấm điểm của vòng canh thật.

    🔴 Con số đáng nhìn nhất ở đây là số vật phát hiện được, KHÔNG phải mức
    nguy hiểm. Detector letterbox mọi ảnh về cạnh dài 640 trước khi suy luận
    (`YoloOnnxDetector.__init__`, `input_size=640`), nên từ VGA trở lên phần
    pixel thừa bị vứt đi ngay ở bước tiền xử lý. Nếu cột này phẳng từ VGA tới
    UXGA thì đó không phải trùng hợp — đó là trần của model.
    """
    from services.hazard_detector import load_default
    from services.hazard_risk import RiskEngine

    detector = load_default()
    if detector is None:
        return {"error": "chưa có model — chạy tools/fetch_hazard_model.py"}

    started = time.monotonic()
    boxes = detector.detect(data)
    detect_ms = (time.monotonic() - started) * 1000.0

    # Engine RIÊNG cho mỗi lần chấm: engine thật giữ lịch sử "vật đang tiến
    # lại gần" giữa các khung. Dùng chung một engine cho cả bảng thì tầng đo
    # sau sẽ ăn điểm approach của tầng đo trước — mỗi ảnh ở đây là một cảnh
    # đứng yên, không phải một chuỗi khung liên tiếp.
    engine = RiskEngine(detector)
    score = engine.score_boxes("bench", boxes)
    level, _ = engine.update("bench", score)

    return {
        "detect_ms": round(detect_ms, 1),
        "boxes": len(boxes),
        "labels": sorted({b.label for b in boxes}),
        "top_conf": round(max((b.confidence for b in boxes), default=0.0), 3),
        "score": round(score, 3),
        "level": level,
    }


def _run_vlm(function: str, data: bytes, ask: str) -> dict:
    """Một chức năng đọc ảnh qua Gemini. Trả cả câu nói lẫn độ trễ."""
    from handlers import describe_space, find_object, ocr, read_money

    handlers = {
        "ocr": lambda: ocr.handle(data, ask, {}),
        "space": lambda: describe_space.handle(data, ask, {}),
        "find": lambda: find_object.handle(data, ask),
        "money": lambda: read_money.handle(data, ask),
    }

    started = time.monotonic()
    try:
        text = "".join(handlers[function]())
    except Exception as exc:  # noqa: BLE001 - một chức năng hỏng không được chặn bảng
        return {"error": f"{type(exc).__name__}: {exc}"}
    elapsed = (time.monotonic() - started) * 1000.0

    return {"ms": round(elapsed, 1), "chars": len(text), "text": text.strip()}


def score_scene(
    scene_dir: Path, functions: list[str], asks: dict[str, str], shot_index: int
) -> list[Shot]:
    shots = _load_meta(scene_dir)
    if not shots:
        print(f"Chưa có ảnh nào ở {scene_dir} — chạy bước chụp trước")
        return []

    # Mỗi tầng chỉ chấm MỘT ảnh: gọi Gemini nhiều lần cho cùng một tầng chỉ đo
    # độ dao động của model, không đo độ phân giải, mà vẫn tốn hạn mức thật.
    chosen = [s for s in shots if s.index == shot_index]
    if not chosen:
        print(f"Không có ảnh index={shot_index}; có {sorted({s.index for s in shots})}")
        return shots

    for shot in chosen:
        data = Path(shot.path).read_bytes()
        print(f"\n── {shot.tier} {shot.width}x{shot.height} ──")
        for function in functions:
            if function == "hazard":
                result = _run_hazard(data)
            else:
                result = _run_vlm(function, data, asks.get(function, DEFAULT_ASK[function]))
            shot.scores[function] = result

            if "error" in result:
                print(f"  {function:<7} LỖI: {result['error']}")
            elif function == "hazard":
                print(
                    f"  {function:<7} {result['boxes']} vật  conf {result['top_conf']}  "
                    f"điểm {result['score']}  mức {result['level']}  "
                    f"({result['detect_ms']} ms)"
                )
            else:
                preview = result["text"].replace("\n", " ")
                if len(preview) > 90:
                    preview = preview[:90] + "…"
                print(f"  {function:<7} {result['ms']:>7.0f} ms  {preview}")

    _save_meta(scene_dir, shots)
    return shots


# ─── giai đoạn 3: bảng ────────────────────────────────────────────────────


def build_report(out_dir: Path, kbps: float) -> str:
    scenes = sorted(p for p in out_dir.iterdir() if p.is_dir()) if out_dir.is_dir() else []
    if not scenes:
        return "Chưa có cảnh nào được đo.\n"

    lines: list[str] = [
        "# F5 — độ phân giải ảnh, đo trên camera thật",
        "",
        f"Sinh bằng `python tools/bench_resolution.py --report`. "
        f"Thời gian đẩy quy đổi ở **{kbps} KB/s** — tốc độ board đo được với gói "
        "512 B + NoDelay, đúng cách `/process` ghi lên socket.",
        "",
        "🔴 Cột kết quả chức năng là để NGƯỜI đối chiếu với cảnh thật. Tool "
        "không biết câu trả lời đúng là gì.",
        "",
    ]

    for scene_dir in scenes:
        shots = _load_meta(scene_dir)
        if not shots:
            continue
        lines += [f"## Cảnh `{scene_dir.name}`", ""]

        by_tier: dict[str, list[Shot]] = {}
        for shot in shots:
            by_tier.setdefault(shot.tier, []).append(shot)

        lines += [
            "| tầng | pixel | JPEG | đẩy @%.1f KB/s | chụp | độ nét | độ sáng |" % kbps,
            "|---|---|---|---|---|---|---|",
        ]
        for tier in TIERS:
            group = by_tier.get(tier.name)
            if not group:
                continue
            avg_bytes = sum(s.jpeg_bytes for s in group) / len(group)
            avg_capture = sum(s.capture_ms for s in group) / len(group)
            avg_sharp = sum(s.sharpness for s in group) / len(group)
            avg_bright = sum(s.brightness for s in group) / len(group)
            upload_ms = avg_bytes / (kbps * 1024) * 1000
            lines.append(
                f"| {tier.name} | {group[0].width}x{group[0].height} | "
                f"{avg_bytes:,.0f} B | {upload_ms:,.0f} ms | "
                f"{avg_capture:,.0f} ms | {avg_sharp:,.1f} | {avg_bright:,.1f} |"
            )
        lines.append("")

        functions = sorted({f for s in shots for f in s.scores})
        for function in functions:
            lines += [f"### `{function}`", ""]
            if function == "hazard":
                lines += [
                    "| tầng | số vật | nhãn | conf cao nhất | điểm | mức | suy luận |",
                    "|---|---|---|---|---|---|---|",
                ]
                for tier in TIERS:
                    group = by_tier.get(tier.name) or []
                    scored = [s for s in group if function in s.scores]
                    if not scored:
                        continue
                    r = scored[0].scores[function]
                    if "error" in r:
                        lines.append(f"| {tier.name} | — | LỖI: {r['error']} | | | | |")
                        continue
                    lines.append(
                        f"| {tier.name} | {r['boxes']} | {', '.join(r['labels']) or '—'} | "
                        f"{r['top_conf']} | {r['score']} | {r['level']} | "
                        f"{r['detect_ms']} ms |"
                    )
            else:
                lines += ["| tầng | độ trễ | số ký tự | trả lời |", "|---|---|---|---|"]
                for tier in TIERS:
                    group = by_tier.get(tier.name) or []
                    scored = [s for s in group if function in s.scores]
                    if not scored:
                        continue
                    r = scored[0].scores[function]
                    if "error" in r:
                        lines.append(f"| {tier.name} | — | — | LỖI: {r['error']} |")
                        continue
                    text = r["text"].replace("\n", " ").replace("|", "\\|")
                    lines.append(
                        f"| {tier.name} | {r['ms']:,.0f} ms | {r['chars']} | {text} |"
                    )
            lines.append("")

    return "\n".join(lines) + "\n"


# ─── vào ───────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--board", default="192.168.2.88", help="IP LAN của kính")
    parser.add_argument("--scene", help="tên cảnh thử, dùng làm thư mục")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="thư mục lưu ảnh")
    parser.add_argument("--tiers", default=",".join(t.name for t in TIERS))
    parser.add_argument("--shots", type=int, default=2, help="số ảnh mỗi tầng")
    parser.add_argument("--settle", type=int, default=8, help="số khung bỏ sau khi đổi tầng")
    parser.add_argument("--kbps", type=float, default=DEFAULT_UPLOAD_KBPS)
    parser.add_argument("--score", action="store_true", help="chấm ảnh ĐÃ chụp")
    parser.add_argument("--functions", default="hazard", help=",".join(ALL_FUNCTIONS))
    parser.add_argument("--shot-index", type=int, default=0, help="chấm ảnh thứ mấy mỗi tầng")
    parser.add_argument("--ask", action="append", default=[], metavar="fn=câu hỏi")
    parser.add_argument("--report", action="store_true", help="in bảng ra file")
    args = parser.parse_args()

    out_dir = Path(args.out)

    if args.report:
        text = build_report(out_dir, args.kbps)
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(text, encoding="utf-8")
        print(text)
        print(f"Đã ghi {REPORT_PATH}")
        return 0

    if not args.scene:
        parser.error("cần --scene (hoặc --report)")

    if args.score:
        functions = [f.strip() for f in args.functions.split(",") if f.strip()]
        unknown = [f for f in functions if f not in ALL_FUNCTIONS]
        if unknown:
            parser.error(f"chức năng lạ: {', '.join(unknown)}")

        asks = dict(DEFAULT_ASK)
        for item in args.ask:
            key, _, value = item.partition("=")
            if key not in DEFAULT_ASK:
                parser.error(f"--ask cho chức năng lạ: {key}")
            asks[key] = value

        billed = [f for f in functions if f in BILLED_FUNCTIONS]
        if billed:
            print(f"⚠ {', '.join(billed)} gọi Gemini thật — sẽ tốn hạn mức.")
        score_scene(out_dir / args.scene, functions, asks, args.shot_index)
        return 0

    names = [n.strip().upper() for n in args.tiers.split(",") if n.strip()]
    unknown = [n for n in names if n not in TIERS_BY_NAME]
    if unknown:
        parser.error(f"tầng lạ: {', '.join(unknown)}. Có: {', '.join(TIERS_BY_NAME)}")
    tiers = [TIERS_BY_NAME[n] for n in names]

    print(f"Cảnh `{args.scene}` — GIỮ YÊN kính cho tới khi quét xong.")
    board = Board(args.board)
    try:
        shots = capture_sweep(board, args.scene, out_dir, tiers, args.shots, args.settle)
    finally:
        board.close()

    if not shots:
        print("\nKhông chụp được khung nào.")
        return 1

    print(f"\nĐã lưu {len(shots)} ảnh vào {out_dir / args.scene}")
    print("Chấm tiếp bằng:")
    print(f"  python tools/bench_resolution.py --score --scene {args.scene} --functions hazard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
