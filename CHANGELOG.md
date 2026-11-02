# Changelog

## 0.2.1 - 2026-11-02

- **Nhạc dài không còn tự ngắt im lặng.** Nguồn HTTP (luồng YouTube qua máy phát) nay chạy ffmpeg với `-reconnect 1 -reconnect_streamed 1
  -reconnect_delay_max 5`: kết nối rớt giữa bài thì nối lại từ đúng byte đã đọc thay vì kết thúc bài. Loa đọc luồng đúng tốc độ phát nên một
  kết nối sống hàng chục phút (bài dài hơn 1 giờ báo ngắt sau 3–4 phút), khác với Cast/DLNA tải hết trong vài giây.
- **Loa khai `idle_reason`** (`finished` hết bài · `stopped` dừng · `interrupted` bị bài khác thay · `error` luồng đứt hoặc mọi loa rớt), cho cả loa
  lẻ và nhóm. Trước đây thiếu thuộc tính này nên tích hợp YouTube coi «loa im giữa bài» là người dùng bấm Dừng và gỡ loa khỏi phiên.
- Mỗi lượt phát ghi một dòng nhật ký khi kết thúc (loa nào, lý do, số giây đã phát) để biết vì sao một bài dừng.

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
