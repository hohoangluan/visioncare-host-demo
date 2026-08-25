"""Chấm `hazard_watch` trên bộ ảnh thật và quét ngưỡng.

Vì sao đo bằng hai cột riêng, không bằng "độ chính xác"
--------------------------------------------------------
Hai loại sai của thiết bị này KHÔNG cùng giá:

    BỎ SÓT  người khiếm thị đâm vào cây cột. Không có gì bù lại được.
    BÁO OAN người nghe tiếng cảnh báo lúc đường trống. Nghe lần thứ hai mươi
            trong một buổi sáng thì họ TẮT chế độ canh — và lúc đó tỉ lệ bỏ
            sót thành 100%.

Nên một con số "accuracy" gộp chung là con số vô nghĩa ở đây: nó cho phép đổi
một lần bỏ sót lấy một lần báo oan như thể chúng ngang nhau. Bảng dưới in
tách hai cột và để người đọc tự chốt.

Dùng:
    python tools/eval_hazard.py                # ngưỡng hiện tại trong config
    python tools/eval_hazard.py --sweep        # quét ngưỡng
    python tools/eval_hazard.py --yolo-only    # so với YOLO một mình
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from services.hazard_risk import RiskEngine, level_for  # noqa: E402

# 🔴 Windows: stdout mặc định là cp1252, và MỌI dòng in của tool này đều có
# tiếng Việt. Không có ba dòng dưới thì tool chạy XONG việc rồi chết ở lệnh
# `print` cuối — nhìn từ ngoài giống hệt "tool hỏng", trong khi file đã ghi.
# Đã dính thật với `publish_firmware.py` (bản đã phát hành, chỉ crash lúc in).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


DATA = ROOT / "tests" / "data" / "hazard"


def load_labels() -> dict[str, dict]:
    path = DATA / "labels.json"
    if not path.is_file():
        raise SystemExit(
            f"Chưa có {path}. Tải ảnh bằng tools/fetch_hazard_testset.py rồi "
            "MỞ TỪNG ẢNH XEM và ghi nhãn — nhãn theo từ khoá tìm kiếm sai "
            "khoảng 1/4 số ảnh."
        )
    raw = json.loads(path.read_text("utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def build_detector(mode: str):
    from services.hazard_detector import YoloOnnxDetector

    yolo = YoloOnnxDetector(config.HAZARD_MODEL_PATH)
    if mode == "yolo":
        return yolo

    from services.depth_detector import DepthObstacleDetector, CombinedDetector

    depth = DepthObstacleDetector(config.DEPTH_MODEL_PATH)
    return CombinedDetector(depth, yolo) if mode == "both" else depth


def score_all(detector, labels: dict[str, dict]) -> dict[str, tuple[float, float]]:
    """{tên ảnh: (điểm rủi ro, mili giây)}."""
    out: dict[str, tuple[float, float]] = {}
    for name in sorted(labels):
        path = DATA / name
        if not path.is_file():
            continue
        data = path.read_bytes()
        started = time.perf_counter()
        boxes = detector.detect(data)
        elapsed = (time.perf_counter() - started) * 1000
        # RiskEngine mới cho MỖI ảnh: hysteresis được thiết kế cho một DÒNG
        # khung liên tiếp. Dùng chung một engine cho các ảnh rời rạc thì ảnh
        # thứ hai thừa hưởng trạng thái của ảnh thứ nhất, và bảng đo sẽ phụ
        # thuộc vào THỨ TỰ ảnh — một cách âm thầm.
        engine = RiskEngine(detector)
        out[name] = (engine.score_boxes(name, boxes), elapsed)
    return out


def tally(scores: dict[str, tuple[float, float]], labels: dict[str, dict],
          threshold: float) -> dict:
    hit = miss = false_alarm = quiet = 0
    missed: list[str] = []
    alarmed: list[str] = []
    for name, (score, _) in scores.items():
        truth = labels[name]["label"]
        alarm = score >= threshold
        if truth == "blocked":
            if alarm:
                hit += 1
            else:
                miss += 1
                missed.append(name)
        elif truth == "clear":
            if alarm:
                false_alarm += 1
                alarmed.append(name)
            else:
                quiet += 1
    return {
        "hit": hit, "miss": miss, "false_alarm": false_alarm, "quiet": quiet,
        "missed": missed, "alarmed": alarmed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sweep", action="store_true")
    parser.add_argument("--yolo-only", action="store_true")
    parser.add_argument("--depth-only", action="store_true")
    args = parser.parse_args()

    mode = "yolo" if args.yolo_only else "depth" if args.depth_only else "both"
    labels = load_labels()
    counts: dict[str, int] = {}
    for entry in labels.values():
        counts[entry["label"]] = counts.get(entry["label"], 0) + 1
    print(f"bộ ảnh: {len(labels)} ảnh — " +
          " · ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    print(f"detector: {mode}   DEPTH_INPUT_SIZE={config.DEPTH_INPUT_SIZE}\n")

    if args.sweep:
        # Quét hai ngưỡng của hai tín hiệu. Detector đọc `config` NGAY TRONG
        # `detect()` nên đổi giá trị rồi chạy lại là đủ, không cần dựng lại.
        print(f"{'biên vượt':>10} {'chắn tầm':>9} {'bắt được':>10} "
              f"{'BỎ SÓT':>8} {'BÁO OAN':>9} {'im đúng':>9}")
        print("-" * 60)
        keep = (config.DEPTH_EXCESS_MARGIN, config.DEPTH_BLOCKED_VIEW)
        detector = build_detector(mode)
        for excess in [0.10, 0.13, 0.16, 0.20]:
            for blocked in [0.16, 0.20, 0.26]:
                config.DEPTH_EXCESS_MARGIN = excess
                config.DEPTH_BLOCKED_VIEW = blocked
                scores = score_all(detector, labels)
                t = tally(scores, labels, config.HAZARD_ENTER_LOW)
                print(f"{excess:>10.2f} {blocked:>9.2f} {t['hit']:>10} "
                      f"{t['miss']:>8} {t['false_alarm']:>9} {t['quiet']:>9}")
        config.DEPTH_EXCESS_MARGIN, config.DEPTH_BLOCKED_VIEW = keep
        return 0

    detector = build_detector(mode)
    scores = score_all(detector, labels)
    t = tally(scores, labels, config.HAZARD_ENTER_LOW)

    print(f"{'ảnh':<52}{'thật':>11}{'điểm':>7}{'mức':>8}{'ms':>7}")
    print("-" * 85)
    for name in sorted(scores, key=lambda n: labels[n]["label"]):
        score, ms = scores[name]
        truth = labels[name]["label"]
        level = level_for(score)
        alarm = score >= config.HAZARD_ENTER_LOW
        mark = " "
        if truth == "blocked" and not alarm:
            mark = "✗"       # bỏ sót — loại sai đắt nhất
        elif truth == "clear" and alarm:
            mark = "!"       # báo oan
        print(f"{mark}{name[:51]:<51}{truth:>11}{score:>7.2f}{level:>8}{ms:>7.0f}")

    print("\n" + "=" * 60)
    print(f"  bắt được  {t['hit']:>3} / {t['hit'] + t['miss']}   (ảnh thật sự có vật chắn)")
    print(f"  🔴 BỎ SÓT {t['miss']:>3}        {', '.join(Path(n).name for n in t['missed']) or '—'}")
    print(f"  báo oan   {t['false_alarm']:>3} / {t['false_alarm'] + t['quiet']}   (ảnh đường trống)")
    print(f"            {' ' * 7}{', '.join(Path(n).name for n in t['alarmed']) or '—'}")
    times = [ms for _, ms in scores.values()]
    times.sort()
    print(f"  thời gian trung vị {times[len(times) // 2]:.0f} ms   chậm nhất {times[-1]:.0f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
