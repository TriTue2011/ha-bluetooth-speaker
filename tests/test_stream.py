"""Phần thuần: âm lượng bluez-alsa, và một lượt phát ra một / nhiều loa.

ffmpeg giả: một script in ra đúng số byte PCM — khỏi cần ffmpeg thật trên máy test. "Loa" là
một ống (pipe): đầu ghi đưa cho lượt phát như fd của bluez-alsa, đầu đọc là test.
"""

import os
import socket
import stat
import sys
import threading
from pathlib import Path

import pytest

from custom_components.bluetooth_speaker.bluez import muc_am_luong, so_am_luong
from custom_components.bluetooth_speaker.stream import Dich, LuotPhat

_LUONG: list[threading.Thread] = []


@pytest.fixture(autouse=True)
def _don_luong():
    """Bộ thử HA đòi không còn luồng nào sót lại sau mỗi test."""
    yield
    for t in _LUONG:
        t.join(5)
    _LUONG.clear()


def test_am_luong_di_ve_nguyen_ven():
    assert muc_am_luong(0x7F7F) == (1.0, False)
    assert muc_am_luong(0xFFFF) == (1.0, True)               # bit 7 = tắt tiếng
    assert so_am_luong(1.0, False) == 0x7F7F
    assert so_am_luong(0.5, True) == ((64 | 0x80) << 8) | (64 | 0x80)
    for m in (0.0, 0.25, 0.5, 0.8, 1.0):
        muc, tat = muc_am_luong(so_am_luong(m, False))
        assert abs(muc - m) < 0.01 and not tat
    assert so_am_luong(3.0, False) == 0x7F7F and so_am_luong(-1, False) == 0


def _ffmpeg_gia(tmp_path: Path, so_byte: int) -> str:
    p = tmp_path / "ffmpeg"
    p.write_text(f"#!{sys.executable}\nimport sys\n"
                 f"sys.stdout.buffer.write(b'\\x01\\x02' * {so_byte // 2})\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def _loa(ten: str):
    """Loa giả: ống nhận tiếng + socket điều khiển trả "OK" cho "Drain" như bluez-alsa."""
    r, w = os.pipe()
    ctl_loa, ctl_ta = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    nhan = bytearray()
    lenh: list[bytes] = []

    def _doc():
        while b := os.read(r, 65536):
            nhan.extend(b)
        os.close(r)

    def _dieu_khien():
        try:
            while b := ctl_loa.recv(64):
                lenh.append(b)
                ctl_loa.send(b"OK")
        except OSError:
            pass

    t = threading.Thread(target=_doc, daemon=True)
    t.start()
    tc = threading.Thread(target=_dieu_khien, daemon=True)
    tc.start()
    _LUONG.append(tc)
    return Dich(ten=ten, fd=w, fd_ctl=ctl_ta.detach()), nhan, t, lenh


def test_phat_ra_nhieu_loa_cung_mot_nguon(tmp_path):
    n = 48000 * 2 * 2                        # 1 giây 48 kHz stereo 16 bit
    ds = [_loa(t) for t in ("A", "B", "C")]
    luot = LuotPhat(_ffmpeg_gia(tmp_path, n), "http://x/bai.mp3", [d[0] for d in ds])
    luot.bat_dau()
    assert luot.cho(10)
    for _d, nhan, t, lenh in ds:
        t.join(2)
        assert bytes(nhan) == b"\x01\x02" * (n // 2)      # mọi loa nhận đủ, đúng thứ tự
        assert lenh == [b"Drain"]                          # hết bài: đợi loa phát nốt
    assert abs(luot.giay - 1.0) < 0.01


def test_mot_loa_rot_cac_loa_khac_van_phat(tmp_path):
    n = 48000 * 2 * 2 * 2
    tot = _loa("tot")
    r, w = os.pipe()
    os.close(r)                              # "loa" đã rớt: ghi vào là EPIPE
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    b.close()
    rot = Dich(ten="rot", fd=w, fd_ctl=a.detach())
    luot = LuotPhat(_ffmpeg_gia(tmp_path, n), "x", [rot, tot[0]])
    luot.bat_dau()
    assert luot.cho(10)
    tot[2].join(2)
    assert len(tot[1]) == n and rot.loi


def test_dung_giua_chung(tmp_path):
    p = tmp_path / "ffmpeg"
    p.write_text(f"#!{sys.executable}\nimport sys, time\n"
                 "while True:\n    sys.stdout.buffer.write(b'\\0' * 19200); sys.stdout.flush()\n"
                 "    time.sleep(0.1)\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    loa = _loa("A")
    xong = []
    luot = LuotPhat(str(p), "x", [loa[0]], khi_xong=xong.append)
    luot.bat_dau()
    assert not luot.cho(0.5)
    luot.dung()
    assert luot.cho(5) and xong == [luot]
    loa[2].join(2)
    assert not loa[2].is_alive()                           # fd loa đã đóng
