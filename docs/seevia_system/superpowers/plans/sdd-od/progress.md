# SDD ledger — plan: SeeVia_system/docs/superpowers/plans/2026-10-21-vat-can-du-doan-quy-dao.md

Workspace: docs/superpowers/plans/sdd-od/ (SeeVia_system không phải repo git; code ở worktree vh-od nhánh od-du-doan, base 110c642)

## Pre-flight scan
| Cặp/Task | Chia sẻ | Kết quả |
|---|---|---|
| T1↔T3 | config keys, hazard._CLASSES (T1 nạp JSON) ↔ T3 dùng | khớp |
| T2↔T3 | TrackSet.update(dets, ests, t, ego_shift_x_m) ↔ PredictTracker đổi shift_x sang mét theo Z track — nhưng update nhận 1 shift chung (mét) | XUNG ĐỘT nhỏ → Ruling 2 |
| T3↔T5 | PredictParams, AntiAnnoy(l3_vote, down_hold, bypass_vote), Hazard.urgent, Ego | khớp |
| T4↔T5 | Scenario.times/ego/group/t_visible_frame | khớp |
| T4 | bench không trong git → Step 5 ghi nhật ký thay commit | tự nhất quán |
| T6 | copy bench vào vh-od/evaluations/bench | khớp T4/T5 file list |
| T7 | HAZARD_CLASSES_JSON cần T1 | khớp (đã thêm) |

Ruling 1: Task 4 chạy SONG SONG với Task 1–3 (file khác hẳn: evaluations/bench vs vh-od), Task 1–3 gộp 1 implementer, review chỉ cuối nhánh — theo memory tiết kiệm token của người dùng — tốn kém nếu sai: lỗi giữa task phát hiện muộn hơn.
Ruling 2: TrackSet.update nhận `ego_shift_rad: float = 0.0` (góc quay đầu giữa 2 khung) thay `ego_shift_x_m`; mỗi track trừ Z·ego_shift_rad vào X trước update. PredictTracker đổi Ego.shift_x (tỉ lệ bề rộng) → rad = shift_x·w/f. Test test_ego_shift_removed: vật đứng yên Z=5, X đo += 5·0.04 mỗi khung, truyền ego_shift_rad=0.04 → |vX|<0.3 — vì quay đầu là dịch GÓC, lượng mét tỉ lệ Z nên một giá trị mét chung cho mọi track là sai — tốn nếu sai: đổi tên tham số.
Ruling 3: Codex không có trên máy (2026-10-21) → Sonnet subagent.
Task 4: complete (evaluations/bench ngoài git; 15 test pass; legacy tái lập đúng 8,3 % / 0,5436 lần/phút; 4 đối chứng cũ đạt)
Ruling 4: chấp nhận sudden_person_behind_car Z lộ diện U(3,5; 4,5) thay [3,5; 5,5] — người dùng 1,2 m/s từ 5,5 m mất 2,9 s tới vùng nguy hiểm, không còn là "đột ngột"; tập test vẫn rộng hơn ở các nhiễu khác — sai thì: nhóm đột ngột thiếu ca lộ diện xa.
Ruling 5: chấp nhận cross_cut_person cắt chéo rồi dừng trong lối — đi thẳng qua ở Z 3–4 gần như không vào vùng < 2 m nên không phải ca nguy hiểm — sai thì: mất ca người cắt ngang rồi đi tiếp.
Ruling 6: chấp nhận sudden_motorbike_alley dừng ở X≈0 (cửa sổ 0,47 s) — định nghĩa kịp thời nhóm đột ngột (≤ 2 khung từ lúc thấy) xử lý đúng ca này; ca bất khả đếm riêng — sai thì: không.
Ngoài plan: đọc tiền v2 (spec 2026-10-21-doc-tien-3-khung-design.md ĐÃ DUYỆT) — agent Sonnet trên vh-ocr/ocr-tien, brief money-retry-brief.md, song song với OD.
Ruling 7: MONEY_BLUR_HINT = phân vị 25 % độ nét ảnh dev đọc đúng ở τ0,999 — chỉ ảnh mờ rõ rệt mới nghe "giữ yên" — sai thì: câu hướng dẫn kém trúng, không ảnh hưởng đúng/sai mệnh giá.
Ruling 8: run_chot_ai.sh đang chạy trên vh-chot @82ea4e0 (ocr-tien cũ, τ0,995) → sau khi money v2 commit: merge lại ocr-tien vào vh-chot, chạy lại RIÊNG phần C3 + pytest — các bàn khác không đổi code.
Phát hiện: lượt chốt 1 (vh-chot @82ea4e0) LẤY LẠI CACHE cũ ở mọi bàn LLM (khoá cache băm prompt/cấu hình, không băm đường code) → không phải lượt đo thật; log giữ ở results/chot/chot_ai_lan1_cache_cu.log, KHÔNG dùng làm số chốt.
Ruling 9: thêm BENCH_CACHE_TAG vào bench/llm_common.Cache (file cache riêng theo tag); run_chot_ai.sh đặt tag chot<ngày> → gọi MỚI toàn bộ — tốn: ~1–2 giờ gọi LLM xa — sai thì: không (cache cũ không đổi).
Ruling 10: chạy lượt chốt thật MỘT lần sau khi money v2 + OD (Task 1–6) cùng gộp vào vh-chot, để số chốt ứng với đúng code cuối — sai thì: chờ lâu hơn.
Money v2: complete b212d38 (ocr-tien) — 577 pass; test 1 khung τ0,999: sai 1,8 % đúng 49,7 %; trễ lượt thành công không đổi (p50 187/p90 200 ms); MONEY_BLUR_HINT=341,4.
Ruling 11: chấp nhận session("ocr", {"mode":"money_retry"}) — app chọn runner/nav theo mode "ocr" — sai thì: không.
Ruling 12: nói kết quả rồi mới `end` (như live OCR); sửa sơ đồ spec §4 cho khớp — sai thì: không.
Ruling 13: giữ MONEY_BLUR_HINT=341,4 dù "Giữ yên tay." chiếm 54 % ca không chắc trên dev 192×144; GHI là phải hiệu chỉnh lại trên khung kính thật (độ phân giải khác) — sai thì: câu hướng dẫn lệch về "giữ yên".
Money v2: minor (deferred): "không có tiền"/lỗi mạng không đọc lại — đúng ý (không bịa), ghi vào báo cáo.
Session 2 (sau restart): agent Task 1–3 bị ngắt. Task 1 complete (f6406a0), Task 2 complete (b991631) — chưa review riêng (review cuối nhánh). Task 3 dở, chưa commit (ego_motion.py, hazard_predict.py, hazard.py, nav_live.py, test).
Money v2: complete b212d38 (DONE_WITH_CONCERNS, 577 pass, dev 1,2/49,1 · test trong nhiễu spec; MONEY_BLUR_HINT=341.4).
Ruling 11: chấp nhận money dùng session("ocr", {"mode":"money_retry"}) thay "money_retry" — runner/nav nhường chọn theo mode=="ocr" — sai thì: không.
Money: Important (sửa ở đợt sửa cuối): lượt đọc CHẮC giờ gửi `reply` sau khi đọc xong (~190 ms) → cue "received" tới kính chậm hơn trước; vi phạm "không tăng trễ" của người dùng. Hướng sửa: trả Reply ngay (stream như cũ) và chỉ khi không chắc mới mở live (vd lượt server chủ động result-* có live:"ocr", hoặc cách khác giữ được thứ tự) — phải kiểm firmware doc + client giả.
Money: minor (deferred): commit ghi Co-Authored-By Sonnet 5.5 thay Opus 5.5.
Ruling 12: hạ "money reply tới sau ~190 ms" từ Important xuống kiểm-bằng-số — lượt money chưa từng gửi cue trong `reply` (tiếng "tíc" kính tự phát khi nhả nút), âm thanh đầu tiên đo 187 vs 200 ms; Task 7 thêm đo ghép đôi thời gian tới âm thanh đầu tiên p50/p90 MONEY_RETRY=0 vs 1 trên cùng ảnh; p90 tăng > 20 ms thì sửa (Reply stream ngay, mở live bằng lượt server đẩy) — sai thì: lượt chắc chậm thêm tối đa ~0,2 s.
Money v2 review (Codex gpt-6-luna, read-only): 3 phát hiện.
Ruling 14: "Cao" MONEY_RETRY=0 không trả τ về 0,995 — CỐ Ý (brief: tắt đọc lại, τ là nút riêng); ghi comment config — sai thì: người bật lại bản cũ phải đặt 2 biến.
Money v2: fix round 1/5 giao agent Sonnet mới: (A) đồng hồ settle/timeout tính sau cam theo lúc nhận khung; (B) giữ top-1 khi thiếu logprobs.
Ruling 10 (sửa): lượt chốt các bàn AI KHÔNG thuộc vật cản chạy NGAY trên vh-chot @ce592ae (vqa + ocr-tien v2 đã gộp; xung đột STATIC_SPEECH giữ cả hai phía) — nhánh OD chỉ đụng live/hazard*, lanes/nav_live.py, config (khoá HAZARD_* mới); khi gộp OD sẽ kiểm `git diff --stat` không chạm file khác rồi chỉ chạy lại pytest + vật cản — sai thì: phải chạy lại bàn bị ảnh hưởng.
Song song: C1a chốt (run_chot_hazard.sh detect, GPU 4); Task 5 agent Sonnet (evaluations/bench, tích hợp khi Task 3 commit).
Money v2: fix round 1/5 (2 addressed, 0 open; commits b212d38..0841dc5) — 580 pass. Không re-review (không có Critical — theo memory tiết kiệm token); nằm trong review cuối.
Ruling 15: chấp nhận đổi assertion test_top_labels_without_alternatives_or_logprobs_is_top1_only — test sinh ở b212d38, ghi đúng hành vi lỗi — sai thì: không.
Money v2: complete (b212d38..0841dc5).
17:13 lượt chốt thật bắt đầu: run_chot_ai.sh (cache tag chot20261021, vh-chot @ce592ae, pytest 704 pass). Kết quả lượt 1 (cache cũ) dời sang results/chot/lan1_cache_cu/.
Sự cố: run_chot_vqa_judge.sh lần đầu vớ file VQA cũ 16:55 → đã dừng trước khi có dòng chấm nào; thêm mốc .start (chỉ nhận file mới hơn) rồi chạy lại. Bài học: script nối đuôi phải lọc theo thời điểm khởi động, không lấy "file mới nhất".
Task 3: complete (commit 9264fea; 671 pass/2 skip vs 658 tại HEAD; 26 test hazard_predict; 4 file test production không sửa). Review dồn về review cuối nhánh.
Task 3: minor (deferred): hazard_geom Camera.f_px thành cached_property + np.nonzero trong ghép IoU (chỉ hiệu năng); test_debug_frames hỏng 1 lần khi 2 pytest chạy chồng — nhạy tải.
Task 6 bước 4 chuẩn bị: bench/hazard_latency.py dùng make_tracker/make_anti + EgoMeter khi predict (VH cũ vẫn chạy). Thử 60 khung yolo11n GPU4: area tổng p90 7,14 ms; predict ego p90 1,09 · assess p90 0,27 · tổng p90 7,26 ms — trong ngân sách (thử, chưa phải số chốt).
Ruling 13: KHÔNG gộp od-du-doan vào vh-chot khi run_chot_ai đang chạy (bàn sau sẽ chạy code khác bàn trước); gộp ngay sau HẾT ok — sai thì: chờ thêm.
Task 5: DONE_WITH_CONCERNS (21 test pass; smoke 216 cấu hình 2 loại×3 seed 2,6 s). Agent lỡ chạy smoke --split test (6 kịch bản, cấu hình mặc định) → sinh HAZARD_PREDICT.md; bắt xoá, lượt test chính thức là lượt duy nhất được báo.
Ruling 14: approach_then_stop — bíp mức 3 lúc đang tiến 1,2 m/s ở ~3 m là ĐÚNG (TTE ~0,8 s); đối chứng sửa thành "từ lúc dừng + 1,0 s: 0 bíp mức 3, mức khung < 3"; nhóm control loại khỏi mọi số báo oan của luật chọn — sai thì: bỏ sót logic kẹt mức 3 khi đứng yên lâu hơn 1 s (vẫn bị bắt).
Ruling 15: shuffle_frames thay bằng reverse_time (vật lùi xa, bỏ 1,0 s đầu, đòi 0 bíp ≥2) — xáo khung tạo vận tốc ảo nên "kịp thời" tăng giả, không kiểm được việc dùng cấu trúc thời gian — sai thì: đối chứng âm yếu hơn mong muốn.
Task 5: fix round 1/5 gửi (2 đối chứng + xoá smoke test).
Task 5 fix round 1: xong (24 pass) nhưng 2 đối chứng predict vẫn hỏng. Controller tự soi approach_then_stop seed 1000 dev: sau khi dừng ở Z thật 3,0 m, track ước Z = 1,0 m, mức 3 kéo dài > 4 s.
GỐC LỖI (plan Task 1 sai): ở Z ≲ 3,3 m chân vật ra khỏi khung (cam 1,6 m, VFOV ~51°) → đáy hộp chạm mép dưới → công thức dự phòng "Z = cam_height·f/(cy − y_top)" kẹp [0,3; 1,5] là SAI vật lý → Z = 1,0. Phụ: bàn đo gán cột = parking_meter (chuẩn 1,2 m) trong khi cột thật 3,0 m → Z thấp ×2,5.
Ruling 16 (VH, sửa logic): khi đáy hộp bị cắt, đo Z bằng TỈ LỆ BỀ RỘNG hộp so với khung trước của cùng track: Z_meas = Z_track·(w_trước/w_nay), σ = 0,1·Z (bất biến với chiều cao vật — đúng đề xuất "TTC từ tốc độ hộp giãn"); track mới bị cắt đáy: bề rộng chuẩn theo lớp, σ lớn; BỎ công thức cạnh trên + cam_height — sai thì: Z lệch khi vật xoay/che một phần bề ngang.
Ruling 17 (bàn đo): split dev/test gán cột kind "pole" (lớp model fine-tune, σ chiều cao 0,5), legacy giữ parking_meter (bit-identical); reverse_time chỉ đếm bíp sau khi Z thật > danger_z + 1 m (vật lùi từ 0,5 m cần ~1,25 s mới ra khỏi vùng, bỏ 1 s đầu là quá ngắn) — sai thì: đối chứng lỏng hơn.
Ruling 18 (yêu cầu người dùng 2026-10-21 "thoát nguy hiểm thì kêu thêm chút rồi dừng"): AntiAnnoy release_s (mặc định 0 = cũ; predict 0,5 s), hết tín hiệu nguy hiểm 2 khung → giữ release_s rồi im hẳn, huỷ nhắc 2 s; bàn đo thêm sidestep_avoid (group release) + chỉ số tail_after_clear_s, lưới release_s {0,25;0,5;1,0} (bỏ coast=2 để giữ ~216 cấu hình), ràng buộc tail p90 ≤ 1,0 s — sai thì: kêu thừa hoặc tắt sớm, thấy được trong báo cáo.
Giao: VH fix (width-ratio + đuôi nhả) → agent Task 3 (resume, 57k); bàn đo (pole, reverse_time, sidestep, tail) → agent MỚI (brief bench-fix-brief.md).
Phiên 4b857f (seevia-system-cf) DỪNG phần OD lúc 17:30 — phát hiện phiên seevia-system-03 chạy cùng plan trên vh-od; đã nhắn bàn giao. Từ đây phiên kia là nguồn duy nhất cho vh-od/Task 3–7.
LƯU Ý SỔ: có HAI phiên ghi chung sổ này. Các dòng Ruling 11–15 ở dòng 30–46 (session_rules về đọc tiền: Codex review, MONEY_RETRY=0, test top_labels…) là của phiên seevia-system-cf [4b857f]; từ dòng 36 trở đi có Ruling 11–18 của phiên này — trùng SỐ, khác nội dung. Từ đây phiên này đánh số tiếp từ Ruling 19.
Phiên cf (tin nhắn 2026-10-21): dừng phần OD, giao lại phiên này; ocr-tien mới nhất @0841dc5 (Codex review + 2 lỗi đã sửa, 580 pass).
Ruling 19: lượt chốt đang chạy trên vh-chot @ce592ae (có b212d38, CHƯA có 0841dc5). 0841dc5 chỉ đổi đồng hồ chỉnh tay live + top-1 khi thiếu logprobs → không đổi số đúng/sai offline C3; sau HẾT ok sẽ merge 0841dc5 + od-du-doan vào vh-chot, chạy lại pytest + money_turn_latency + vật cản; ghi commit từng bàn trong THONG_SO_CHOT.md — sai thì: chạy lại C3.
Phiên cf xác nhận dừng hẳn; vh-ocr cuối = 0841dc5, không đổi τ/đường đọc chắc → số C3 offline trên b212d38 hợp lệ.
VH fix round 1: 5206c82 (đáy cắt → tỉ lệ bề rộng, neo theo Z thô chưa cắt cuối cùng — lệch Ruling 16 được CHẤP NHẬN: dùng Z đã lọc làm cột đứng yên trôi 0,7 m do vòng phản hồi), f270b38 (đuôi nhả release_s; mức 1 cũng im sau nhả tới khi ≥2 quay lại). 677 pass.
Ruling 20: lớp không có chiều cao điển hình (pole, warning_column, traffic_light, stop_sign, plant, parking_meter) KHÔNG dùng nguồn chiều cao — chỉ mặt đất + tỉ lệ/bảng bề rộng; test cột dùng lại kind "pole" H=3 m — sai thì: mất nguồn khoảng cách khi đáy cắt lẫn không có track.
Ruling 21: test_predict_crowded_frame_fast chặn p90 < 2 ms (máy dùng chung làm test chập chờn); ngân sách 1 ms thật kiểm bằng C1c + luật chọn — sai thì: hồi quy hiệu năng 1–2 ms lọt qua unit test (vẫn bị C1c bắt).
VH: fix round 2/5 gửi.
Bàn đo fix: DONE (27 pass, legacy bitwise; lưới 324 cấu hình = 108×3 release_s — chấp nhận, chạy lâu hơn ~1,5×). Smoke: tail p90 ~2,6 s KHÔNG đổi theo release_s.
Controller soi sidestep_avoid seed 1000: đuôi nhả đúng (cur→0 sau 0,5 s); "kêu thừa" là BÁO OAN MỚI khi đi sát qua vật: hộp chạm mép phải → tâm hộp dịch vào → vX ảo −0,49 → mức 3 ở Z≈1,6 m. Chính là nguồn báo oan của pass_by_person.
Ruling 22: hộp chạm mép bên → X từ cạnh trong ± W_lớp/2, phương sai X ×4; cả hai mép cắt → X=0 phương sai lớn — sai thì: vật thật lấn vào từ mép bị báo chậm (có test).
VH: fix round 3/5 xếp hàng.
VH fix round 2/3: 111d84b (NO_HEIGHT_KINDS), e91bd7b (mép bên → cạnh trong). 682 pass. Lo ngại: track mới cắt đáy + mép bên → Z theo bề rộng nhìn thấy → quá XA (báo muộn).
Ruling 23: cắt đáy ⇒ vật gần hơn mặt đất thấy được gần nhất: Z ≤ Z_lim·1,15 (Z_lim = cam_h·f/(h−cy+f·tanθ) ≈ 3,3 m) — áp cho track mới và tỉ lệ bề rộng; giao CODEX (việc cơ học, brief codex-clip-brief.md, controller commit) — sai thì: vật trên bục/xe cao bị cắt đáy ở > 3,8 m bị coi gần hơn (báo sớm, an toàn).
Task 3: minor (deferred): test_v2_messages 10 lỗi event-loop một lần khi chạy full, chạy lại pass — phụ thuộc thứ tự, không do OD.
Ruling 12 ĐÓNG: đo ghép đôi 60 ảnh, lượt đọc chắc Δ trung vị +1,1 ms [−3,1; +3,2] (ce592ae) và −1,2 ms [−2,8; +1,1] (706e08f, có 0841dc5); p90 v2 ≤ cũ → không tăng trễ, không cần sửa. vh-chot @706e08f pytest 707 pass.
VH: complete Codex clip bound 20decde (684 pass; controller rút gọn nhánh chết _ground_z luôn None).
Task 6 bước 1: lưới dev đầy đủ bắt đầu 17:52 — vh-od @20decde, 50 seed/loại, 324 cấu hình, --procs 8, out results/chot/hazard/c1b.
Final review (Sonnet, final-review.md): With fixes — 0 Critical, 2 Important, 7 Minor; area không đổi; fuzz 3000 khung không crash/NaN; an toàn luồng. Lưới dev @20decde DỪNG (kết quả sẽ lỗi thời sau sửa).
Ruling 24 (Important 1): cổng nhoè tương đối — so độ nét khung với EMA độ nét của phiên (nhoè khi < 0,35·EMA, EMA α 0,1, khởi tạo bằng khung đầu); và chặn tối đa 2 khung liên tiếp không cho tạo track — khung thứ 3 luôn cho — sai thì: cảnh nhoè thật thêm track nhiễu (bị phiếu 2/3 lọc).
Ruling 25 (Important 2): góc cúi tự học = TRUNG VỊ 31 mẫu gần nhất (không EMA), kẹp BẤT ĐỐI XỨNG [−0,02; +0,10] rad (chiều làm Z xa hơn chỉ được lệch nhỏ) — sai thì: camera ngẩng thật > 1,1° bị bù thiếu (Z hơi gần hơn thật = báo sớm, an toàn).
Ruling 26 (Minor 4,5,7 sửa cùng đợt): khoảng trống mốc thời gian > 1,0 s → xoá mọi track; bỏ detection có toạ độ không hữu hạn, track có trạng thái không hữu hạn thì xoá; HAZARD_LOGIC lạ → log warning + chạy area.
Ruling 27 (Minor 3,6,8,9 ĐỂ LẠI): 3 an toàn (báo thừa); 6 dùng _Mailbox.received_at sau khi gộp vào vh-chot (nhánh ocr-tien đã thêm) — ghi việc còn treo; 8 tải 30–60 hộp không thực tế; 9 lệch kích thước lớp cố hữu → ghi trong HAZARD_PREDICT.md.
C4 chốt: Codex chấm mù 180/180 (17:46–17:57), đối chứng âm 15/15 tráo + 15/15 y hệt ĐẠT; ask thắng 138/11/1; trực tiếp 98,7 %, thừa 7,3 %, đúng 90 %, VQA acc 83,8 %. reports/VQA_ASK_CHOT.md (sửa nhãn giám khảo: code report ghi cứng 'Claude Sonnet').
Final fix wave: cedaa8a (690 pass, +6 test). Re-review phạm vi giao CODEX (codex-rereview-brief.md). Lưới dev đầy đủ khởi chạy lại 18:02 trên @cedaa8a (song song re-review; dừng nếu có Critical).
Codex biến mất ~18:00 (extension gỡ) → re-review phạm vi chuyển Sonnet. Lưới dev lần đầu khởi chạy sai thư mục (No module bench) — chạy lại 18:0x bằng đường dẫn tuyệt đối.
Final fix wave re-review (Sonnet theo brief Codex): Important 1, 2, Minor 4, 5, 7 đều ADDRESSED; lỗi mới Critical 0 / Important 0; 45 test hazard_predict pass.
Final: parked — PredictTracker không có reset() (EMA nhoè + deque góc cúi chỉ sạch khi tạo tracker mới) — Ruling 28: chấp nhận, nav_live.run tạo tracker MỚI mỗi phiên live nên trạng thái không lọt giữa phiên — sai thì: nếu sau này dùng lại tracker qua phiên thì cần reset().
Session 3 (restart 18:07): lưới dev bị ngắt khi mới bắt đầu; chạy lại bằng setsid nohup (sống qua restart). Codex có lại (người dùng cho dùng lại).
Yêu cầu người dùng (2026-10-21 18:1x): HOÀN TẤT xong thì commit tất cả + push lên GitHub nhóm (origin hohoangluan/visioncare-host-demo) tên LuanLuKim <kimluanlu95@gmail.com>; token người dùng gửi trong chat — KHÔNG ghi vào file/sổ/memory; push 4 nhánh mới, không force; chép evaluations (code+báo cáo, không datas/results lớn) + SeeVia_system/docs vào nhánh chot-ai-2026-10-21.
Task 6 bước 1–2 (18:36): lưới dev @cedaa8a XONG 324/324, selected = null (0/324 thoả). Mọi cấu hình vi phạm CẢ 3 ràng buộc: báo oan/phút thấp nhất 2,476 vs baseline 1,130 (×2,2); % an toàn có bíp ≥ 23,8 vs 13,3; đuôi bíp p90 ≥ 1,88 s > 1 s. Lỗi chính: người đi ngang/cùng chiều/đứng mép (pass_by_person+yaw 94 %, edge_static_person+yaw 86 %, baseline 0 %). Theo Step 2: DỪNG, không chạy test, không ghi tham số vào config.py; chờ người dùng quyết. Báo cáo: evaluations/reports/HAZARD_PREDICT.md.
