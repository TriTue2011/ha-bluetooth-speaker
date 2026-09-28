"""Mỗi loa đã ghép đôi = một media_player; thêm một media_player nhóm phát ra mọi loa đang nối.

Loa: Bật = kết nối, Tắt = ngắt (dừng phát). Trạng thái: off (chưa nối) / idle / playing.
Phát (``play_media``, ``tts.speak``) trả về ngay khi bắt đầu — bài dài không giữ lệnh gọi.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    async_process_play_media_url,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BluetoothSpeakerConfigEntry, Hub
from .bluez import BluezError, muc_am_luong, so_am_luong
from .const import DOMAIN, NHOM

_LOGGER = logging.getLogger(__name__)

_TINH_NANG_CHUNG = (MediaPlayerEntityFeature.PLAY_MEDIA
                    | MediaPlayerEntityFeature.STOP
                    | MediaPlayerEntityFeature.VOLUME_SET
                    | MediaPlayerEntityFeature.VOLUME_MUTE
                    | MediaPlayerEntityFeature.BROWSE_MEDIA
                    | MediaPlayerEntityFeature.MEDIA_ANNOUNCE)


async def async_setup_entry(hass: HomeAssistant, entry: BluetoothSpeakerConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    hub = entry.runtime_data
    da_co: set[str] = set()

    @callback
    def _them(addresses: list[str]) -> None:
        moi = [a for a in addresses if a not in da_co]
        da_co.update(moi)
        if moi:
            async_add_entities([LoaPlayer(hub, entry, a) for a in moi])

    hub.them_loa = _them
    async_add_entities([NhomPlayer(hub, entry)])
    _them([a for a, x in hub.loa.items() if x.paired])


class _Goc(MediaPlayerEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: Hub, entry: BluetoothSpeakerConfigEntry) -> None:
        self.hub, self._entry = hub, entry

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.hub.async_listen(self.async_write_ha_state))

    async def _url(self, media_id: str) -> str:
        if media_source.is_media_source_id(media_id):
            play = await media_source.async_resolve_media(self.hass, media_id, self.entity_id)
            media_id = play.url
        return async_process_play_media_url(self.hass, media_id)

    async def async_browse_media(self, media_content_type: MediaType | str | None = None,
                                 media_content_id: str | None = None) -> BrowseMedia:
        return await media_source.async_browse_media(
            self.hass, media_content_id,
            content_filter=lambda item: item.media_content_type.startswith("audio/"))


class LoaPlayer(_Goc):
    """Một loa Bluetooth đã ghép đôi."""

    _attr_name = None
    _attr_supported_features = (_TINH_NANG_CHUNG | MediaPlayerEntityFeature.TURN_ON
                                | MediaPlayerEntityFeature.TURN_OFF)

    def __init__(self, hub: Hub, entry: BluetoothSpeakerConfigEntry, address: str) -> None:
        super().__init__(hub, entry)
        self.address = address
        self._attr_unique_id = f"{DOMAIN}-{address.lower()}"
        loa = hub.loa.get(address)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            connections={(CONNECTION_BLUETOOTH, address)},
            name=loa.name if loa else address,
            manufacturer="Bluetooth (A2DP)")

    @property
    def available(self) -> bool:
        loa = self.hub.loa.get(self.address)
        return bool(loa and loa.paired)

    @property
    def state(self) -> MediaPlayerState:
        if self.address not in self.hub.pcm:
            return MediaPlayerState.OFF
        if self.hub.dang_phat(self.address) or (
                self.hub.dang_phat(NHOM)
                and any(d.ten == self.address for d in self.hub.luot[NHOM].dich)):
            return MediaPlayerState.PLAYING
        return MediaPlayerState.IDLE

    @property
    def volume_level(self) -> float | None:
        p = self.hub.pcm.get(self.address)
        return muc_am_luong(p.volume)[0] if p else None

    @property
    def is_volume_muted(self) -> bool | None:
        p = self.hub.pcm.get(self.address)
        return muc_am_luong(p.volume)[1] if p else None

    async def async_turn_on(self) -> None:
        try:
            await self.hub.client.connect_device(self.address)
        except BluezError as exc:
            raise HomeAssistantError(f"cannot connect {self.address}: {exc}") from exc
        await self.hub.async_refresh()

    async def async_turn_off(self) -> None:
        await self.hub.async_stop(address=self.address)
        try:
            await self.hub.client.disconnect_device(self.address)
        except BluezError as exc:
            raise HomeAssistantError(f"cannot disconnect {self.address}: {exc}") from exc
        await self.hub.async_refresh()

    async def async_play_media(self, media_type: MediaType | str, media_id: str,
                               **kwargs: Any) -> None:
        url = await self._url(media_id)
        if self.address not in self.hub.pcm:
            await self.async_turn_on()                  # chưa nối thì nối rồi phát
        await self.hub.async_play(self.address, [self.address], url)

    async def async_media_stop(self) -> None:
        await self.hub.async_stop(address=self.address)

    async def async_set_volume_level(self, volume: float) -> None:
        await self.hub.async_set_volume(self.address, so_am_luong(volume, False))

    async def async_mute_volume(self, mute: bool) -> None:
        muc = self.volume_level or 0.0
        await self.hub.async_set_volume(self.address, so_am_luong(muc, mute))


class NhomPlayer(_Goc):
    """Phát cùng lúc ra MỌI loa đang kết nối (một luồng giải mã, chia ra từng loa)."""

    _attr_translation_key = "all_speakers"
    _attr_supported_features = _TINH_NANG_CHUNG

    def __init__(self, hub: Hub, entry: BluetoothSpeakerConfigEntry) -> None:
        super().__init__(hub, entry)
        self._attr_unique_id = f"{DOMAIN}-{entry.entry_id}-all"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)},
                                            name="Bluetooth Speaker",
                                            manufacturer="Bluetooth (A2DP)")

    @property
    def state(self) -> MediaPlayerState:
        if not self.hub.pcm:
            return MediaPlayerState.OFF
        return MediaPlayerState.PLAYING if self.hub.dang_phat(NHOM) else MediaPlayerState.IDLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"speakers": [self.hub.loa[a].name if a in self.hub.loa else a
                             for a in self.hub.pcm]}

    @property
    def volume_level(self) -> float | None:
        muc = [muc_am_luong(p.volume)[0] for p in self.hub.pcm.values()]
        return max(muc) if muc else None

    @property
    def is_volume_muted(self) -> bool | None:
        tat = [muc_am_luong(p.volume)[1] for p in self.hub.pcm.values()]
        return all(tat) if tat else None

    async def async_play_media(self, media_type: MediaType | str, media_id: str,
                               **kwargs: Any) -> None:
        url = await self._url(media_id)
        await self.hub.async_play(NHOM, list(self.hub.pcm), url)

    async def async_media_stop(self) -> None:
        await self.hub.async_stop(key=NHOM)

    async def async_set_volume_level(self, volume: float) -> None:
        for a in list(self.hub.pcm):
            await self.hub.async_set_volume(a, so_am_luong(volume, False))

    async def async_mute_volume(self, mute: bool) -> None:
        for a, p in list(self.hub.pcm.items()):
            await self.hub.async_set_volume(a, so_am_luong(muc_am_luong(p.volume)[0], mute))
