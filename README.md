# 🔊 Bluetooth Speaker — phát ra loa Bluetooth từ Home Assistant, không cần add-on

Tích hợp tuỳ chỉnh (HACS) biến **mỗi loa Bluetooth** (A2DP: loa, soundbar, tai nghe) thành một
`media_player` của Home Assistant, cộng một `media_player` **nhóm phát cùng lúc ra nhiều loa**.
Không cần add-on, không cần MPD, PulseAudio hay PipeWire — chạy với **HA Container** (Docker),
kể cả HA trong **LXC trên Proxmox**.

- Quét, ghép đôi, kết nối, quên loa ngay trong **Settings → Devices & services → Bluetooth
  Speaker → Configure**.
- Loa: **Bật** = kết nối, **Tắt** = ngắt. Phát URL, TTS (`tts.speak`), media source, YouTube…
  Âm lượng chỉnh thật trên loa.
- **Tất cả loa Bluetooth**: giải mã một lần, chia ra mọi loa đang kết nối.

## Cách nó chạy

```
Home Assistant ──D-Bus──► BlueZ        (quét, ghép đôi, kết nối)
      │
      └─ ffmpeg (giải mã) ──fd qua D-Bus──► bluez-alsa ──► loa 1, loa 2, …
```

Máy có bộ Bluetooth chạy **BlueZ** và **bluez-alsa**. bluez-alsa mở cho mỗi loa đang kết nối
một "cổng phát"; tích hợp xin cổng đó qua D-Bus, nhận lại một fd và ghi thẳng tiếng PCM vào.
ffmpeg có sẵn trong Home Assistant.

## Yêu cầu

| Chạy HA thế nào | Bluetooth | Làm gì |
|---|---|---|
| Docker trên Debian / Ubuntu (máy thật) | Có sẵn trên mainboard hoặc USB | Cài trên chính máy đó (bước 1) |
| Docker trong **VM** (Proxmox…) | Có sẵn hoặc USB | Cho VM mượn thiết bị Bluetooth (USB passthrough), rồi làm bước 1 trong VM |
| Docker trong **LXC trên Proxmox** | Có sẵn hoặc USB | Máy Proxmox giữ Bluetooth, LXC mượn D-Bus (bước 1 trên Proxmox + bước 2) |
| **HA OS** | — | Không dùng được (không cài được bluez-alsa) — dùng add-on [Bluetooth Audio Manager](https://github.com/scyto/ha-bluetooth-audio-manager) |

Vì sao LXC không passthrough USB được: nhân Linux chỉ cho mở kết nối Bluetooth ở không gian
mạng gốc của máy; LXC có không gian mạng riêng nên bị từ chối (`[Errno 97] Address family not
supported`) kể cả khi thấy USB.

## Cài đặt

### 1. Máy có Bluetooth: BlueZ + bluez-alsa

```bash
apt install -y bluez bluez-alsa-utils
systemctl enable --now bluetooth bluealsa
bluetoothctl list            # ✅ "Controller AA:BB:… [default]"
```

Không thấy Controller: `dmesg | grep -i bluetooth` — thường thiếu firmware (Debian:
`firmware-realtek` hoặc `firmware-iwlwifi`, nhánh `non-free-firmware`).

Khuyên thêm (chỉ phát RA loa, giữ kênh 5 giây giữa hai câu, bỏ dòng gỡ lỗi `D:` bản Debian in
~15.000 dòng/ngày) — tạo `/etc/systemd/system/bluealsa.service.d/loa.conf`:

```ini
[Service]
ExecStart=
ExecStart=/bin/sh -c "/usr/bin/bluealsa --keep-alive=5 -p a2dp-source 2>&1 | grep --line-buffered -v ': D: '"
```

rồi `systemctl daemon-reload && systemctl restart bluealsa`.

### 2. Chỉ khi HA nằm trong LXC: mượn D-Bus của máy Proxmox

Trên Proxmox (thay `102` bằng số LXC của bạn):

```bash
echo 'lxc.mount.entry: /run/dbus mnt/dbus-host none bind,create=dir 0 0' >> /etc/pve/lxc/102.conf
pct reboot 102
pct exec 102 -- ls /mnt/dbus-host        # ✅ system_bus_socket
```

Gắn vào `/mnt`, không phải `/run` — systemd trong LXC phủ `/run` mới lên, che mất chỗ gắn.
LXC cần **privileged** (`unprivileged: 0`).

### 3. Compose của Home Assistant

```yaml
services:
  homeassistant:
    network_mode: host
    volumes:
      - /run/dbus:/run/dbus:ro           # HA trong LXC: /mnt/dbus-host:/run/dbus:ro
```

Kiểm: `docker exec homeassistant ls /run/dbus` → có `system_bus_socket`.

### 4. Cài tích hợp

HACS → ⋮ → **Custom repositories** → `https://github.com/TriTue2011/ha-bluetooth-speaker`,
loại **Integration** → tải **Bluetooth Speaker** → khởi động lại HA.

(Hoặc chép `custom_components/bluetooth_speaker` vào `/config/custom_components/`.)

**Settings → Devices & services → Add integration → Bluetooth Speaker → Submit**. Tích hợp kiểm
máy: thấy D-Bus, có bộ Bluetooth, bluez-alsa đang chạy — thiếu gì báo đúng chỗ đó.

## Sử dụng

### Thêm loa

1. Bật **chế độ ghép đôi** trên loa (giữ nút Bluetooth tới khi đèn nháy nhanh), để gần bộ
   Bluetooth; tắt Bluetooth trên điện thoại đang nối với loa.
2. **Bluetooth Speaker → Configure → Quét và kết nối loa mới → Submit** (quét 12 giây).
3. Chọn loa → **Submit**: lần đầu ghép đôi + đánh dấu tin cậy + kết nối. Loa hiện thành
   `media_player.<tên loa>`.

### Phát

```yaml
action: tts.speak
target:
  entity_id: tts.google_translate_vi_com_vn
data:
  media_player_entity_id: media_player.d50s            # hoặc nhóm: media_player.bluetooth_speaker_all_bluetooth_speakers
  message: "Xin chào, đây là loa Bluetooth."
```

Nhạc, radio, YouTube: chọn loa này như mọi `media_player` khác. Lệnh phát trả về ngay, bài dài
không giữ lệnh gọi.

| Việc | Cách |
|---|---|
| Kết nối loa đã ghép đôi | `media_player.turn_on` (hoặc bấm Bật trên thẻ) |
| Ngắt loa | `media_player.turn_off` |
| Phát ra nhiều loa cùng lúc | Phát vào **Tất cả loa Bluetooth** — mọi loa đang kết nối |
| Quên loa | Configure → Quên một loa |

Phát vào một loa đang **tắt** thì tích hợp tự kết nối rồi phát.

## Giới hạn

- **Không khớp nhịp tuyệt đối giữa các loa.** Mỗi loa Bluetooth trễ khác nhau (thường vài trăm
  mili giây). Loa ở các phòng khác nhau thì ổn; hai loa cùng phòng có thể nghe như vang.
- **Số loa cùng lúc** tuỳ chip Bluetooth — thường 2–3 loa SBC trên một USB Bluetooth. Muốn
  nhiều hơn, cắm thêm bộ Bluetooth (mỗi bộ bluez-alsa quản riêng).
- Một loa một lúc chỉ một nguồn: phát nguồn mới vào loa (hay nhóm có loa đó) thì nguồn cũ dừng.
- Chỉ A2DP (loa nhận tiếng); không nhận tiếng từ điện thoại, không LE Audio.
- Một bộ Bluetooth vừa để HA quét BLE vừa phát A2DP có thể làm tiếng giật: bật *Passive
  scanning* trong tích hợp Bluetooth của HA, hoặc dùng bộ Bluetooth riêng cho loa.

## Gỡ lỗi

| Hiện tượng | Kiểm |
|---|---|
| Thêm tích hợp báo *bluez-alsa is not running* | `systemctl status bluealsa` trên máy có Bluetooth |
| *speaker is in use by another program* | Chương trình khác đang giữ loa (MPD, `bluealsa-aplay`…) — dừng nó |
| Quét không thấy loa | Loa chưa ở chế độ ghép đôi / đang nối với điện thoại |
| Loa `off` dù đã bật | `bluetoothctl devices Connected` trên máy có Bluetooth; `bluealsa-aplay -L` phải liệt kê loa |
| Không ra tiếng | Log HA (`custom_components.bluetooth_speaker`): ffmpeg không mở được nguồn, hay loa rớt giữa chừng |

## Giấy phép

MIT
