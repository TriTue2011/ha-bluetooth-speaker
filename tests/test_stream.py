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


def _ffmpeg_ghi_doi_so(tmp_path: Path, so_byte: int) -> tuple[str, Path]:
    """ffmpeg giả ghi lại dòng lệnh nó được gọi, rồi in đúng ``so_byte`` byte PCM."""
    nhat_ky = tmp_path / "doi_so.txt"
    p = tmp_path / "ffmpeg"
    p.write_text(f"#!{sys.executable}\nimport sys\nopen({str(nhat_ky)!r}, 'w').write(' '.join(sys.argv[1:]))\n"
                 f"sys.stdout.buffer.write(b'\\x01\\x02' * {so_byte // 2})\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p), nhat_ky


def test_tua_dua_ss_truoc_nguon_va_nho_vi_tri_bat_dau(tmp_path):
    ffmpeg, nhat_ky = _ffmpeg_ghi_doi_so(tmp_path, 9600)
    loa = _loa("A")
    luot = LuotPhat(ffmpeg, "http://x/bai.m4a", [loa[0]], tu_giay=42.5)
    luot.bat_dau()
    assert luot.cho(10)
    lenh = nhat_ky.read_text().split()
    assert lenh[lenh.index("-ss") + 1] == "42.500" and lenh.index("-ss") < lenh.index("-i")   # tua theo đầu vào: nhanh, không giải mã đoạn bỏ qua
    loa[2].join(2)
    assert luot.vi_tri_goc == 42.5 and luot.luc is not None


def test_khong_tua_thi_khong_co_ss(tmp_path):
    ffmpeg, nhat_ky = _ffmpeg_ghi_doi_so(tmp_path, 9600)
    loa = _loa("A")
    luot = LuotPhat(ffmpeg, "x", [loa[0]])
    luot.bat_dau()
    assert luot.cho(10)
    loa[2].join(2)
    assert "-ss" not in nhat_ky.read_text().split() and luot.vi_tri_goc == 0.0


def test_nguon_http_tu_noi_lai_khi_dut_giua_chung_con_tep_cuc_bo_thi_khong(tmp_path):
    """Luồng HTTP rớt giữa bài mà ffmpeg không nối lại thì bài kết thúc im lặng («YouTube tự ngắt»)."""
    for nguon, co in (("http://x/bai.m4a", True), ("https://x/bai.m4a", True), ("/tmp/bai.mp3", False)):
        ffmpeg, nhat_ky = _ffmpeg_ghi_doi_so(tmp_path, 9600)
        loa = _loa("A")
        luot = LuotPhat(ffmpeg, nguon, [loa[0]])
        luot.bat_dau()
        assert luot.cho(10)
        loa[2].join(2)
        lenh = nhat_ky.read_text().split()
        assert ("-reconnect" in lenh) is co, nguon
        if co:
            assert lenh[lenh.index("-reconnect_streamed") + 1] == "1" and "-reconnect_delay_max" in lenh
            assert lenh.index("-reconnect") < lenh.index("-i")                    # tuỳ chọn đầu vào phải đứng trước -i


def _ffmpeg_thoat(tmp_path: Path, ma: int, loi: str = "") -> str:
    p = tmp_path / "ffmpeg"
    p.write_text(f"#!{sys.executable}\nimport sys\nsys.stdout.buffer.write(b'\\x01\\x02' * 4800)\n"
                 f"sys.stderr.write({loi!r})\nsys.exit({ma})\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def test_ly_do_ket_thuc_het_bai_loi_dung_va_bi_thay(tmp_path):
    loa = _loa("A")
    het = LuotPhat(_ffmpeg_thoat(tmp_path, 0), "x", [loa[0]])
    het.bat_dau()
    assert het.cho(10) and het.ly_do == "finished"
    loa[2].join(2)

    loa = _loa("B")
    hong = LuotPhat(_ffmpeg_thoat(tmp_path, 1, "Connection reset by peer"), "x", [loa[0]])
    hong.bat_dau()
    assert hong.cho(10) and hong.ly_do == "error"                      # ffmpeg thoát mã khác 0 giữa chừng = luồng đứt, không phải hết bài
    loa[2].join(2)

    p = tmp_path / "lau"
    p.write_text(f"#!{sys.executable}\nimport sys, time\nwhile True:\n    sys.stdout.buffer.write(b'\\0' * 19200); sys.stdout.flush(); time.sleep(0.1)\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    for cach, mong in ((None, "stopped"), ("interrupted", "interrupted")):
        loa = _loa("C")
        luot = LuotPhat(str(p), "x", [loa[0]])
        luot.bat_dau()
        assert not luot.cho(0.3)
        luot.dung() if cach is None else luot.dung(cach)
        assert luot.cho(5) and luot.ly_do == mong
        loa[2].join(2)


def test_moi_loa_rot_het_thi_la_loi_khong_phai_het_bai(tmp_path):
    r, w = os.pipe()
    os.close(r)
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    b.close()
    luot = LuotPhat(_ffmpeg_thoat(tmp_path, 0), "x", [Dich(ten="rot", fd=w, fd_ctl=a.detach())])
    luot.bat_dau()
    assert luot.cho(10) and luot.ly_do == "error"
