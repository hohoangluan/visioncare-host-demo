# C4 — Đồng thuận giám khảo: Gemma-chấm vs Codex-chấm (VizWiz-VQA)

Codex `gpt-6-luna` chấm **mù** (không thấy phán quyết của Gemma), **có nhìn ảnh**, 143/143 dòng: 50 mẫu kiểm tay + toàn bộ câu unanswerable của mẫu 300. Codex là giám khảo độc lập thứ hai (khác họ model với Gemma), **không thay được người chấm**.

| Chỉ số | Giá trị [CI 95 %] |
|---|---|
| Đồng thuận 'từ chối' Gemma vs Codex | 61.5 % [53.8; 69.2] (n=143) · κ = 0.29 |
| VQA acc theo Gemma-chấm | 56.6 % [48.3; 64.1] (n=143) |
| VQA acc theo Codex-chấm (cùng dòng) | 81.8 % [76.2; 87.2] (n=143) · Δ +25.2 đ.% [+17.2; +34.3] |
| **Bịa thật trên câu unanswerable** (Codex nhìn ảnh: khẳng định điều ảnh không cho thấy) | **8.7 % [3.8; 14.4] (n=104)** |
| Không từ chối trên câu unanswerable (Codex) | 28.8 % [20.2; 37.5] (n=104) |
| Codex cho rằng ảnh VẪN trả lời được dù nhãn đa số 'unanswerable' | 40.4 % [30.8; 50.0] (n=104) |
| Bịa trên câu trả lời được (Codex) | 5.1 % [0.0; 12.8] (n=39) |

Đọc: số bịa của bench (`VQA.md`, 'không khớp người nào' 41,3 %) là cận trên vì gộp cả câu né tránh; số Codex ở đây đo **bịa thật** bằng cách nhìn ảnh.

## Đối chứng âm (Codex có thật sự nhìn ảnh không)

Codex chấm thêm 30 dòng không biết trước: 20 dòng câu trả lời bị **tráo sang ảnh khác** và 10 dòng thật.
- Dòng tráo bị đánh bịa: **100 %** (cần ≥ 80 %) · dòng thật bị đánh bịa: **0 %** (cần ≤ 20 %)
- Kết luận: **ĐẠT — tin được phán quyết nhìn ảnh của Codex**.
