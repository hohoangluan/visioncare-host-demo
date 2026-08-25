"""Kho firmware cho OTA kéo qua internet — kính khác mạng với server.

Vì sao có file này
------------------
`ArduinoOTA` (đường ĐẨY qua mDNS) chỉ chạy khi máy nạp và kính ở **cùng một
LAN**. Kính thật thì ở nhà người dùng, server ở chỗ khác, hai bên chỉ gặp nhau
qua Cloudflare tunnel. Nên đường phát hành thật phải ngược lại: **kính tự hỏi
và tự kéo về**, đúng tên miền và cổng nó vẫn đang gọi (`/process`, `/frame`,
`/events`) — không mở thêm gì trên mạng người dùng, không cần địa chỉ tĩnh.

Ba nguyên tắc, mỗi cái trả giá cho một cách hỏng cụ thể
-------------------------------------------------------
1. **Fail-closed.** Không có `latest.json` → không có bản mới, chấm hết. Thư
   mục firmware có file `.bin` lạc vào KHÔNG tự trở thành bản phát hành. Đẩy
   nhầm một bản dựng dở xuống kính của người khiếm thị là hỏng thiết bị mà
   họ không nhìn thấy một dòng log nào để biết vì sao.
2. **`sha256` là bắt buộc, tính từ chính file trên đĩa.** Ảnh firmware đứt
   giữa chừng vẫn "ghi thành công" vào slot OTA — nó chỉ chết lúc khởi động
   lại, và lúc đó kính đã ở trong túi người dùng. Board đối chiếu digest
   TRƯỚC `Update.end()` (xem `src/net/ota_manager.cpp`).
3. **So sánh phiên bản bằng `!=`, không phải `>`.** `FW_VERSION` là chuỗi
   ngày-tháng do người viết đặt (`2026.08.24-ota1`), không phải semver — mọi
   phép "lớn hơn" ở đây đều là đoán. `!=` cho phép cả hạ cấp (rollback), mà
   rollback là thứ ta cần nhất khi một bản phát hành hỏng.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import threading

import config


@dataclass(frozen=True)
class FirmwareBuild:
    """Một bản dựng có thật trên đĩa, đã băm xong."""

    version: str
    path: Path
    size: int
    sha256: str

    def as_manifest(self) -> dict[str, object]:
        return {
            "update": True,
            "version": self.version,
            # Đường dẫn TƯƠNG ĐỐI: board ghép với `API_HOST`/`API_PORT` nó
            # đang dùng. Trả URL tuyệt đối ở đây thì đổi tên miền một lần là
            # mọi kính đang chạy trỏ vào chỗ chết.
            "url": f"/firmware/bin?version={self.version}",
            "size": self.size,
            "sha256": self.sha256,
        }


class FirmwareRegistry:
    """Đọc thư mục firmware, băm có nhớ, trả manifest cho một kính cụ thể."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._lock = threading.Lock()
        # (đường dẫn, mtime_ns, size) -> sha256. Băm 1.35 MB tốn ~10 ms, không
        # đắt; nhưng mỗi kính hỏi manifest lúc khởi động và mỗi 6 giờ, nên
        # nhớ lại vẫn hơn. Khoá có mtime nên sửa file là tự băm lại.
        self._digest_cache: dict[tuple[str, int, int], str] = {}

    # ------------------------------------------------------------ đọc đĩa

    def _pointer(self) -> dict[str, object] | None:
        """Nội dung `latest.json`, hoặc None nếu chưa phát hành gì."""
        pointer = self._root / "latest.json"
        if not pointer.is_file():
            return None
        try:
            data = json.loads(pointer.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        return data

    def _sha256(self, path: Path) -> str:
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        with self._lock:
            cached = self._digest_cache.get(key)
        if cached is not None:
            return cached

        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 16), b""):
                digest.update(chunk)
        value = digest.hexdigest()
        with self._lock:
            self._digest_cache[key] = value
        return value

    def _build_from(self, version: str, filename: str) -> FirmwareBuild | None:
        # `Path(filename).name` chặn `../` — tên file đi từ latest.json và từ
        # query string của kính, cả hai đều không phải nguồn đáng tin để ghép
        # thẳng vào đường dẫn.
        path = self._root / Path(str(filename)).name
        if not path.is_file():
            return None
        return FirmwareBuild(
            version=str(version),
            path=path,
            size=path.stat().st_size,
            sha256=self._sha256(path),
        )

    # ------------------------------------------------------------ công khai

    def latest(self) -> FirmwareBuild | None:
        """Bản đang phát hành, hoặc None. Không có `latest.json` là None."""
        pointer = self._pointer()
        if not pointer:
            return None
        version = pointer.get("version")
        filename = pointer.get("file")
        if not version or not filename:
            return None
        return self._build_from(str(version), str(filename))

    def get(self, version: str) -> FirmwareBuild | None:
        """Một bản cụ thể theo tên phiên bản (dùng cho rollback có chủ đích)."""
        if not version:
            return None
        latest = self.latest()
        if latest is not None and latest.version == version:
            return latest

        # Bản không phải "latest" vẫn phục vụ được, miễn là file tồn tại theo
        # đúng quy ước tên `<version>.bin`. Cần cho ca: server vừa phát hành
        # bản mới trong lúc một kính đang tải dở bản trước.
        return self._build_from(version, f"{version}.bin")

    def manifest_for(self, current_version: str | None) -> dict[str, object]:
        """Manifest trả về cho một kính đang chạy `current_version`.

        Board đọc đúng bốn trường: `update`, `version`, `url`, `size`,
        `sha256`. Khi `update` là false thì các trường kia chỉ để đọc log.
        """
        build = self.latest()
        if build is None:
            return {"update": False, "reason": "NO_RELEASE"}

        # `!=` chứ không `>`: xem nguyên tắc 3 ở đầu file.
        if current_version and current_version == build.version:
            return {"update": False, "version": build.version, "reason": "UP_TO_DATE"}

        return build.as_manifest()


firmware = FirmwareRegistry(config.FIRMWARE_DIR)
