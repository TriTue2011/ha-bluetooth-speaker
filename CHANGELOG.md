# Changelog

## 0.2.0 - 2026-11-02

- **Tua được.** Loa Bluetooth (và nhóm loa) nay khai báo `SEEK` và báo `media_position` / `media_position_updated_at`.
  Trước đây thiếu `SEEK` nên thẻ YouTube (chỉ gửi `media_seek` cho loa có tính năng này) báo «Loa đang phát không hỗ trợ tua».
  Loa Bluetooth không tự tua được vì nguồn do Home Assistant giải mã rồi đẩy sang, nên tua = chạy lại CÙNG nguồn, cùng các
  loa còn nối, từ giây yêu cầu (`ffmpeg -ss` đặt trước `-i`). Có một quãng ngắt khi chuyển. Tua một loa đang phát theo nhóm thì tua cả nhóm.
  Tua khi không phát gì báo lỗi rõ. Thanh tiến độ chạy theo cặp (vị trí, thời điểm) của lượt phát.

## 0.1.2 - 2026-10-24

- Icon riêng cho tích hợp trong Home Assistant (`brand/`: loa hộp kèm huy hiệu Bluetooth, có bản cho nền tối).
  Home Assistant có hỗ trợ thư mục `brand/` tự nạp (đã thấy trong 2026.10.3; bản cũ hơn chưa kiểm). Không đổi mã.

## 0.1.1 - 2026-09-28

- Chuyển bài không còn làm playlist dừng hẳn: bài cũ vừa dừng thì bluez-alsa nhả loa chậm hơn
  một chút, mở ngay báo "Device or resource busy" (gặp thật khi playlist YouTube tự sang bài).
  Nay loa còn bận thì chờ rồi mở lại, tối đa 2 giây; quá hạn mới báo lỗi.

## 0.1.0 - 2026-09-28

- Bản đầu: mỗi loa Bluetooth (A2DP) đã ghép đôi là một `media_player`; `media_player` nhóm
  phát cùng lúc ra mọi loa đang kết nối. Phát thẳng qua bluez-alsa (fd qua D-Bus), không cần
  MPD / PulseAudio / add-on.
- Configure: quét, ghép đôi (agent NoInputNoOutput), kết nối, quên loa. Bật / Tắt loa =
  kết nối / ngắt. Âm lượng và tắt tiếng thật trên loa.
- Đã chạy thật: HA Container trong LXC trên Proxmox, USB TP-Link UB500, loa D50s.
