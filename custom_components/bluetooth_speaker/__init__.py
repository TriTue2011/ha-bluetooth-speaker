"""Bluetooth Speaker — phát ra loa Bluetooth (A2DP) từ Home Assistant, không cần add-on.

Máy có Bluetooth chạy BlueZ + bluez-alsa; HA nói chuyện với cả hai qua D-Bus hệ thống
(container HA gắn ``/run/dbus``). Mỗi loa đã ghép đôi thành một ``media_player``; thêm một
``media_player`` nhóm phát cùng lúc ra mọi loa đang kết nối. Quét / ghép đôi / quên ở mục
Configure của tích hợp; Bật / Tắt ``media_player`` của loa = kết nối / ngắt.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import timedelta

from homeassistant.components.ffmpeg import get_ffmpeg_manager
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers.event import async_track_time_interval

from .bluez import BluezClient, BluezError, Loa, Pcm
from .stream import Dich, LuotPhat

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.MEDIA_PLAYER]
#: Tín hiệu D-Bus tới dồn (một lần kết nối = vài tín hiệu) — gom lại rồi mới làm mới.
_GOM_GIAY = 1.0
#: Làm mới định kỳ phòng khi lỡ tín hiệu.
_DINH_KY = timedelta(seconds=30)

type BluetoothSpeakerConfigEntry = ConfigEntry[Hub]


class Hub:
    """Trạng thái chung: loa BlueZ biết, cổng phát bluez-alsa, lượt đang phát."""

    def __init__(self, hass: HomeAssistant, client: BluezClient, ffmpeg: str) -> None:
        self.hass, self.client, self.ffmpeg = hass, client, ffmpeg
        self.loa: dict[str, Loa] = {}
        self.pcm: dict[str, Pcm] = {}
        #: address (hoặc "nhom") → lượt đang phát ra loa đó
        self.luot: dict[str, LuotPhat] = {}
        self._nghe: list[Callable[[], None]] = []
        self._hen = None
        self._bao_thieu_bluealsa = False
        self.them_loa: Callable[[list[str]], None] | None = None

    # ── làm mới ─────────────────────────────────────────────────────────────

    async def async_refresh(self) -> None:
        try:
            loa = await self.client.speakers()
        except BluezError as exc:
            _LOGGER.warning("cannot read speakers from BlueZ: %s", exc)
            return
        try:
            pcm = await self.client.pcms()
            self._bao_thieu_bluealsa = False
        except BluezError as exc:
            if not self._bao_thieu_bluealsa:
                _LOGGER.warning("bluez-alsa not reachable (is the bluealsa service running?): %s",
                                exc)
                self._bao_thieu_bluealsa = True
            pcm = []
        moi = [x.address for x in loa if x.paired and x.address not in self.loa]
        self.loa = {x.address: x for x in loa}
        self.pcm = {x.address: x for x in pcm}
        if moi and self.them_loa is not None:
            self.them_loa(moi)
        for cb in list(self._nghe):
            cb()

    @callback
    def async_schedule_refresh(self) -> None:
        if self._hen is None:
            self._hen = self.hass.loop.call_later(_GOM_GIAY, self._chay_hen)

    @callback
    def _chay_hen(self) -> None:
        self._hen = None
        self.hass.async_create_task(self.async_refresh(), eager_start=False)

    @callback
    def async_listen(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._nghe.append(cb)
        return lambda: self._nghe.remove(cb)

    # ── phát ────────────────────────────────────────────────────────────────

    def dang_phat(self, key: str) -> bool:
        return key in self.luot and not self.luot[key].xong.is_set()

    async def async_play(self, key: str, addresses: list[str], url: str) -> None:
        """Phát ``url`` ra các loa ``addresses``; ``key`` = thực thể sở hữu lượt ("nhom" / địa chỉ).

        Loa đang ở lượt khác thì lượt đó dừng trước (một loa một lúc một nguồn)."""
        for k, l in list(self.luot.items()):
            if k == key or any(d.ten in addresses for d in l.dich):
                l.dung()
                await self.hass.async_add_executor_job(l.cho, 3)
        pcms = [self.pcm[a] for a in addresses if a in self.pcm]
        if not pcms:
            raise HomeAssistantError("no connected Bluetooth speaker to play to")
        mau = pcms[0]
        dich: list[Dich] = []
        try:
            for p in pcms:
                if (p.sampling, p.channels) != (mau.sampling, mau.channels):
                    _LOGGER.warning("%s: %s Hz/%s ch differs from %s — skipped in this group",
                                    p.address, p.sampling, p.channels, mau.address)
                    continue
                fd, fd_ctl = await self.client.open_pcm(p.path)
                dich.append(Dich(ten=p.address, fd=fd, fd_ctl=fd_ctl))
        except BluezError as exc:
            _dong(dich)
            if "busy" in str(exc).lower():
                raise HomeAssistantError(
                    "speaker is in use by another program (e.g. MPD, bluealsa-aplay) — "
                    "stop it and try again") from exc
            raise HomeAssistantError(f"cannot open speaker: {exc}") from exc

        def _xong(_l: LuotPhat) -> None:
            self.hass.loop.call_soon_threadsafe(self._het_luot, key, _l)

        luot = LuotPhat(self.ffmpeg, url, dich, sampling=mau.sampling, channels=mau.channels,
                        khi_xong=_xong)
        self.luot[key] = luot
        luot.bat_dau()
        for cb in list(self._nghe):
            cb()

    @callback
    def _het_luot(self, key: str, luot: LuotPhat) -> None:
        if self.luot.get(key) is luot:
            del self.luot[key]
        for cb in list(self._nghe):
            cb()

    async def async_stop(self, key: str | None = None, address: str | None = None) -> None:
        for k, l in list(self.luot.items()):
            if k == key or (address and any(d.ten == address for d in l.dich)):
                l.dung()
                await self.hass.async_add_executor_job(l.cho, 3)

    async def async_set_volume(self, address: str, volume: int) -> None:
        if address in self.pcm:
            await self.client.set_volume(self.pcm[address].path, volume)
            self.async_schedule_refresh()


def _dong(dich: list[Dich]) -> None:
    for d in dich:
        for fd in (d.fd, d.fd_ctl):
            try:
                os.close(fd)
            except OSError:
                pass


async def async_setup_entry(hass: HomeAssistant, entry: BluetoothSpeakerConfigEntry) -> bool:
    client = BluezClient()
    try:
        await client.connect()
        await client.adapter()
    except BluezError as exc:
        client.close()
        raise ConfigEntryNotReady(str(exc)) from exc
    hub = Hub(hass, client, get_ffmpeg_manager(hass).binary)
    await client.watch(hub.async_schedule_refresh)
    await hub.async_refresh()
    entry.runtime_data = hub
    @callback
    def _dinh_ky(_now) -> None:
        hub.async_schedule_refresh()

    entry.async_on_unload(async_track_time_interval(hass, _dinh_ky, _DINH_KY))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BluetoothSpeakerConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hub = entry.runtime_data
        await hub.async_stop()
        for l in list(hub.luot.values()):
            l.dung()
        if hub._hen is not None:
            hub._hen.cancel()
        hub.client.close()
    return ok
