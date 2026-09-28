"""Một lượt phát: ffmpeg giải mã nguồn (URL, tệp) → PCM S16LE → ghi vào cổng phát của từng loa.

Python thuần, không phụ thuộc Home Assistant. Chạy trong một luồng riêng: ghi vào fd của
bluez-alsa là ghi chặn, nhịp thời gian thực do chính loa quyết (bluez-alsa chỉ nhận khi đã gửi
đi được). Nhiều loa: CÙNG một luồng giải mã ghi lần lượt vào từng fd — các loa tiêu thụ cùng
tốc độ nên đi cùng nhau; loa nào rớt (ghi lỗi) thì bỏ loa đó, các loa khác phát tiếp.
"""

from __future__ import annotations

import logging
import os
import select
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

_LOGGER = logging.getLogger(__name__)

#: Mỗi lần ghi 100 ms tiếng (48 kHz, 2 kênh, 16 bit = 19 200 byte).
_KHUC_GIAY = 0.1
#: Hết tiếng: chờ loa phát nốt phần bluez-alsa đang đệm tối đa ngần này giây.
_DRAIN_GIAY = 5.0


@dataclass
class Dich:
    """Một loa nhận tiếng trong lượt phát."""

    ten: str
    fd: int
    fd_ctl: int
    loi: str = field(default="")


class LuotPhat:
    """``bat_dau()`` chạy nền; ``dung()`` cắt ngang; ``xong`` báo khi hết (tự nhiên hay bị cắt)."""

    def __init__(self, ffmpeg: str, nguon: str, dich: list[Dich], *, sampling: int = 48000,
                 channels: int = 2, khi_xong: Callable[[LuotPhat], None] | None = None) -> None:
        self.ffmpeg, self.nguon, self.dich = ffmpeg, nguon, dich
        self.sampling, self.channels = sampling, channels
        self._khi_xong = khi_xong
        self._proc: subprocess.Popen | None = None
        self._dung = threading.Event()
        self.xong = threading.Event()
        self.giay = 0.0
        self._luong = threading.Thread(target=self._chay, name="bluetooth-speaker", daemon=True)

    def bat_dau(self) -> None:
        self._luong.start()

    def dung(self) -> None:
        self._dung.set()
        p = self._proc
        if p is not None and p.poll() is None:
            p.kill()

    def cho(self, timeout: float | None = None) -> bool:
        return self.xong.wait(timeout)

    def _lenh(self) -> list[str]:
        return [self.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
                "-i", self.nguon, "-vn", "-ac", str(self.channels), "-ar", str(self.sampling),
                "-f", "s16le", "pipe:1"]

    def _chay(self) -> None:
        khuc = int(self.sampling * self.channels * 2 * _KHUC_GIAY)
        con = list(self.dich)
        for d in con:
            os.set_blocking(d.fd, True)
        try:
            self._proc = subprocess.Popen(self._lenh(), stdin=subprocess.DEVNULL,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            while con and not self._dung.is_set():
                b = self._proc.stdout.read(khuc)
                if not b:
                    break
                for d in list(con):
                    try:
                        _ghi_het(d.fd, b)
                    except OSError as exc:              # loa rớt: bỏ loa đó, loa khác chạy tiếp
                        d.loi = str(exc)
                        con.remove(d)
                        _LOGGER.warning("%s: speaker dropped out: %s", d.ten, exc)
                self.giay += len(b) / (self.sampling * self.channels * 2)
            if self._proc.poll() is None and self._dung.is_set():
                self._proc.kill()
            loi = (self._proc.stderr.read() or b"").decode("utf-8", "replace").strip()
            if self._proc.wait() and not self._dung.is_set() and loi:
                _LOGGER.warning("cannot play %s: %s", self.nguon[:120], loi.splitlines()[-1][:200])
            if not self._dung.is_set():
                _drain([d.fd_ctl for d in con])
        except OSError as exc:
            _LOGGER.warning("cannot start ffmpeg: %s", exc)
        finally:
            for d in self.dich:
                for fd in (d.fd, d.fd_ctl):
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            self.xong.set()
            if self._khi_xong is not None:
                self._khi_xong(self)


def _ghi_het(fd: int, b: bytes) -> None:
    view, da = memoryview(b), 0
    while da < len(b):
        da += os.write(fd, view[da:])


def _drain(fds_ctl: list[int]) -> None:
    """Chờ bluez-alsa phát nốt phần đang đệm ở MỌI loa: gửi ``Drain`` cho tất cả rồi chờ
    chung một hạn — loa nào không trả lời không làm các loa khác chờ thêm."""
    cho: list[int] = []
    for fd in fds_ctl:
        try:
            os.write(fd, b"Drain")
            cho.append(fd)
        except OSError:
            pass
    han = time.monotonic() + _DRAIN_GIAY
    while cho and (con := han - time.monotonic()) > 0:
        try:
            r, _w, _x = select.select(cho, [], [], con)
        except OSError:
            return
        for fd in r:
            try:
                os.read(fd, 32)
            except OSError:
                pass
            cho.remove(fd)
