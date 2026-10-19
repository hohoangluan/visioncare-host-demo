# App server — kiến trúc và bản đồ mã nguồn

Dành cho session sau: hệ thống có **hai server riêng biệt**, ở hai repo, hai cổng.
Repo này (`Sever_test`) chỉ là một nửa. File này mô tả nửa còn lại — app server —
và chỉ rõ chỗ nào sửa chức năng nào.

`HUONG_DAN_SERVER.md` mô tả hợp đồng board ↔ voice server. File này mô tả tầng trên nó.

---

## 1. Hai server

| | Voice server | App server |
|---|---|---|
| Repo | `d:\Study\innostar\Sever_test` (repo này) | `D:\Study\innostar\app_demo_backend\apps\backend` |
| Cổng | **8000** | **8001** |
| Entry | `app.py` | `app.main:app`, chạy với `--app-dir src` |
| Việc | STT → phân loại ý định → TTS, trả audio stream cho kính | Nhận lệnh điều khiển, đẩy xuống điện thoại qua FCM |
| Ngôn ngữ | Python / FastAPI | Python / FastAPI + SQLAlchemy + Postgres |

Chạy app server:

```powershell
cd D:\Study\innostar\app_demo_backend\apps\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir src --host 0.0.0.0 --port 8001
```

Hai chỗ dễ vấp:

- `.env` của app server ghi `HTTP_PORT=8000`, nhưng cờ `--port 8001` trên dòng lệnh
  mới có hiệu lực. **Đừng sửa `.env` cho khớp** — voice server đang giữ cổng 8000.
- `[WinError 10048] only one usage of each socket address` = **đã có instance chạy ở
  8001**, không phải lỗi code. Kiểm tra: `Get-NetTCPConnection -LocalPort 8001 -State Listen`

---

## 2. Đường đi một lệnh điều khiển

```
Kính ESP32
   │  POST /process   (ảnh + audio)
   ▼
Voice server :8000                          repo Sever_test
   │  pipeline/stt.py           giọng nói -> text
   │  pipeline/intent_local.py  text      -> intent + tham số
   │  handlers/<action>.py      hỏi thêm nếu thiếu tham số
   │  handlers/action_flow.py   run_action() gửi lệnh đi
   │  POST api/v1/service/...   {"song": ..., "request_id": ...}
   ▼
App server :8001                            repo app_demo_backend
   │  api/service.py            nhận, chuẩn hoá tham số
   │  services/operation.py     ghi DB, trả 202 + request_id
   │  workers/delivery.py       đẩy xuống điện thoại qua FCM
   ▼
Android                                     apps/android
   │  actions/ActionRegistry.kt  chọn handler theo action
   │  media/SpotifyRemoteManager.kt (nhạc), ...
   ▼
Điện thoại thực thi, rồi callback ngược
   │  workers/callback.py
   ▼
Voice server  POST /internal/action-results  -> đọc kết quả thành lời
```

**Voice server không tự làm gì trên điện thoại.** Nó chỉ gửi lệnh và đọc kết quả.

---

## 3. Bản đồ app server — sửa gì ở đâu

Gốc: `D:\Study\innostar\app_demo_backend\apps\backend\src\app\`

| Cần sửa | File |
|---|---|
| Thêm/đổi endpoint điều khiển | `api/service.py` |
| Danh sách action + timeout mỗi action | `actions.py` |
| Kiểu dữ liệu request gửi lên | `schemas/service_requests.py` |
| Kiểu dữ liệu kết quả trả về | `schemas/service_results.py` |
| **Đổi tên bài hát thành URI Spotify** | `services/spotify.py` |
| Vòng đời một lệnh (nhận, trùng lặp, trạng thái) | `services/operation.py` |
| Đẩy lệnh xuống điện thoại | `workers/delivery.py`, `adapters/delivery.py` |
| Nhận callback từ điện thoại | `workers/callback.py`, `adapters/callback.py` |
| Hết giờ một lệnh | `workers/timeout.py` |
| Cấu hình, biến môi trường | `config.py` + `.env` |
| Xác thực token Public/Device API | `auth.py`, `security.py` |
| Bảng dữ liệu | `models/`, migration ở `alembic/` |

Phía Android (`D:\Study\innostar\app_demo_backend\apps\android\app\src\main\java\com\youreyes\app\`):

| Cần sửa | File |
|---|---|
| Định tuyến action → handler | `actions/ActionRegistry.kt` |
| Mở Spotify, phát/dừng nhạc | `media/SpotifyRemoteManager.kt` |
| Mở app khi màn hình tắt | `launch/CommandLaunchActivity.kt` |

---

## 4. Các endpoint điều khiển

Khai báo trong `actions.py`, tất cả đều `POST`, trả **202** + `request_id`.

| Đường dẫn | operation | Timeout |
|---|---|---|
| `/api/v1/service/ride/quote` | `ride_quote` | 60s |
| `/api/v1/service/ride/confirm` | `ride_confirm` | 90s |
| `/api/v1/service/music/play` | `music_play` | 45s |
| `/api/v1/service/music/stop` | `music_stop` | 30s |
| `/api/v1/service/music/volume` | `music_volume` | 30s |
| `/api/v1/service/navigation/start` | `navigation_start` | 90s |
| `/api/v1/service/navigation/stop` | `navigation_stop` | 45s |
| `/api/v1/service/emergency/call` | `emergency_call` | 21 phút |
| `/api/v1/service/contact/call` | `contact_call` | 60s |
| `/api/v1/service/location/get` | `location_get` | 30s |

Tra trạng thái: `GET /api/v1/requests/{request_id}`.
Chi tiết tham số từng endpoint: xem `endpoint.md` trong repo này.

---

## 5. Riêng luồng nhạc (Spotify)

Đo và dựng lại ngày 2026-08-18. Đường duy nhất chạy được là **Spotify App Remote SDK**.

### 5.1. Luồng

```
api/service.py::post_music_play
   │  services/spotify.py::resolve_track_uri()   "Lạc Trôi - Sơn Tùng M-TP"
   │                                          -> "spotify:track:0XaY8eVU9eZO4OdIV6agx1"
   ▼  FCM
media/SpotifyAppRemoteManager.kt::playTrack()
   │  SpotifyAppRemote.connect()      <- bind SERVICE, không phải activity
   │  playerApi.play(trackUri)
   │  subscribeToPlayerState()        <- chờ Spotify tự báo đúng track + !isPaused
   ▼
báo về đúng cái Spotify nói đang phát
```

Bind service chứ không mở activity là lý do nó **chạy được khi máy khoá, màn tắt** —
không dính hạn chế Background Activity Launch của Android.

### 5.2. Ba đường đã thử và HỎNG — đừng làm lại

| Cách | Kết quả đo trên máy thật |
|---|---|
| `ACTION_VIEW` deep link `spotify:track:` | Chỉ điều hướng giao diện. Đang phát bài khác thì **không đổi bài**, và action sẽ báo nhầm bài |
| `MediaBrowserService` của Spotify | Luôn `onConnectionFailed` — chỉ nhận client được whitelist (Android Auto) |
| `transportControls.playFromSearch()` | Có trong bitmask `actions` nhưng **không đổi được track** |

### 5.3. Bắt buộc trên Spotify Developer Dashboard

Thiếu bất kỳ mục nào → `AUTHENTICATION_SERVICE_UNAVAILABLE`, và Spotify đóng màn
hình cấp quyền trong ~40ms nên **không thấy lỗi gì trên màn hình**.

| Mục | Giá trị |
|---|---|
| APIs/SDKs | Phải tick **Android** (mới hiện ô Android Packages) **và Web API** |
| Android Packages | `com.youreyes.app` + SHA-1 `F9:40:A0:DF:8E:82:59:EE:95:96:19:0A:D2:F2:65:A8:07:F7:19:59` |
| Redirect URI | `youreyes://spotify-callback` |
| User Management | **Email khớp tài khoản Spotify** (tên hiển thị không cần khớp) |

Lấy lại SHA-1 khi đổi máy: `./gradlew signingReport`. Build release có SHA-1 khác,
phải khai thêm.

Khai xong **cần thời gian lan truyền** — đo thực tế mất vài phút mới ăn.

### 5.4. Trên điện thoại

- Một lần duy nhất: mở app → bấm đồng ý màn hình Spotify. `MainActivity` gọi
  `SpotifyAppRemoteManager.ensureAuthorized()` để dựng màn hình đó, vì luồng FCM
  chạy nền không được phép bật UI.
- Appop `USE_FULL_SCREEN_INTENT` phải là `allow`. Trên Android 14 mặc định là
  `ignore`, và `dumpsys package` vẫn báo `granted=true` nên rất dễ tưởng đã có —
  kiểm bằng `cmd appops get com.youreyes.app USE_FULL_SCREEN_INTENT`.
  **Cài lại APK sẽ reset nó về `ignore`.**

### 5.5. Giới hạn phải biết trước khi phát hành

Spotify app mới nằm ở **Development Mode**: tối đa **5 tài khoản**, mỗi tài khoản
phải thêm email thủ công, và chủ app phải có Premium.

Muốn bỏ giới hạn phải xin **Extended Quota Mode**, điều kiện gồm doanh nghiệp đăng
ký hợp pháp, dịch vụ đã ra mắt, và **tối thiểu 250.000 người dùng/tháng** — tức
cần 250k người dùng trước khi được vượt quá 5 người dùng. Không có đường đi từ 5
lên 250k qua Spotify.

**Kết luận: Spotify dùng được cho demo, KHÔNG dùng được cho bản phát hành thật.**
Đo trên chính máy này thì YouTube Music nạp và phát được cùng bài mà không cần
allowlist — là hướng cần cân nhắc cho bản thật.

### 5.6. Nguyên tắc không được phá: không báo bừa "đang phát"

`MusicPlayHandler` **chỉ** trả `playback_state: "playing"` khi Spotify tự xác nhận
đúng track và `isPaused == false`, và trả về **tên bài Spotify đang phát**, không
phải tên bài đã yêu cầu.

Trước đây nó trả `"playing"` vô điều kiện, kể cả khi không có điện thoại — và
`ActionRegistryTest` còn assert đúng hành vi đó với `Context = null`, nên bug ship
được. Người khiếm thị không nhìn màn hình để phát hiện, nên một câu "đang phát" sai
là họ ngồi chờ tiếng nhạc không bao giờ tới.

Mã lỗi `music_play`: `SONG_NOT_FOUND`, `MUSIC_ACCOUNT_NOT_CONNECTED`,
`SUBSCRIPTION_INACTIVE`, `PLAYBACK_FAILED`. Voice server đổi thành lời ở
`handlers/result_speech.py`.
