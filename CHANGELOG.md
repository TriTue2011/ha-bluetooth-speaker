# Changelog

## 0.1.0 - 2026-09-28

- Bản đầu: mỗi loa Bluetooth (A2DP) đã ghép đôi là một `media_player`; `media_player` nhóm
  phát cùng lúc ra mọi loa đang kết nối. Phát thẳng qua bluez-alsa (fd qua D-Bus), không cần
  MPD / PulseAudio / add-on.
- Configure: quét, ghép đôi (agent NoInputNoOutput), kết nối, quên loa. Bật / Tắt loa =
  kết nối / ngắt. Âm lượng và tắt tiếng thật trên loa.
- Đã chạy thật: HA Container trong LXC trên Proxmox, USB TP-Link UB500, loa D50s.
