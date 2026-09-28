"""Thêm tích hợp (kiểm máy đủ BlueZ + bluez-alsa) và Configure: quét / ghép đôi / quên loa."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr

from .bluez import BluezClient, BluezError
from .const import DOMAIN, QUET_GIAY


async def _kiem_may() -> str | None:
    """Mã lỗi (khoá trong strings.json) hoặc None nếu máy đủ điều kiện."""
    c = BluezClient()
    try:
        await c.connect()
    except BluezError:
        return "no_dbus"
    try:
        try:
            await c.adapter()
        except BluezError:
            return "no_adapter"
        try:
            await c.pcms()
        except BluezError:
            return "no_bluealsa"
        return None
    finally:
        c.close()


class BluetoothSpeakerConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None
                              ) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors: dict[str, str] = {}
        if user_input is not None:
            if loi := await _kiem_may():
                errors["base"] = loi
            else:
                return self.async_create_entry(title="Bluetooth Speaker", data={})
        return self.async_show_form(step_id="user", data_schema=vol.Schema({}), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return BluetoothSpeakerOptionsFlow()


class BluetoothSpeakerOptionsFlow(OptionsFlow):
    """Configure: menu Quét & kết nối / Quên loa."""

    def __init__(self) -> None:
        self._tim_thay: dict[str, str] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None
                              ) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["scan", "forget"])

    async def async_step_scan(self, user_input: dict[str, Any] | None = None
                              ) -> ConfigFlowResult:
        """Bước 1: dặn bật chế độ ghép đôi; bấm Gửi thì quét."""
        if user_input is None:
            return self.async_show_form(step_id="scan", data_schema=vol.Schema({}),
                                        description_placeholders={"giay": str(QUET_GIAY)})
        hub = self.config_entry.runtime_data
        try:
            loa = await hub.client.scan(QUET_GIAY)
        except BluezError as exc:
            return self.async_abort(reason="scan_failed",
                                    description_placeholders={"loi": str(exc)[:200]})
        self._tim_thay = {x.address: f"{'✓ ' if x.paired else ''}{x.name} ({x.address})"
                          for x in loa if not x.connected}
        if not self._tim_thay:
            return self.async_abort(reason="nothing_found")
        return await self.async_step_pick()

    async def async_step_pick(self, user_input: dict[str, Any] | None = None
                              ) -> ConfigFlowResult:
        """Bước 2: chọn loa → ghép đôi (nếu chưa) + tin cậy + kết nối."""
        hub = self.config_entry.runtime_data
        errors: dict[str, str] = {}
        loi = ""
        if user_input is not None:
            dia_chi = user_input["speaker"]
            try:
                loa = hub.loa.get(dia_chi)
                if not (loa and loa.paired):
                    await hub.client.pair(dia_chi)
                await hub.client.connect_device(dia_chi)
            except BluezError as exc:
                errors["base"] = "connect_failed"
                loi = str(exc)[:200]
            else:
                await hub.async_refresh()
                return self.async_create_entry(data=dict(self.config_entry.options))
        return self.async_show_form(
            step_id="pick", errors=errors, description_placeholders={"loi": loi},
            data_schema=vol.Schema({vol.Required("speaker"): vol.In(self._tim_thay)}))

    async def async_step_forget(self, user_input: dict[str, Any] | None = None
                                ) -> ConfigFlowResult:
        """Quên (xoá ghép đôi) một loa."""
        hub = self.config_entry.runtime_data
        da_ghep = {a: f"{x.name} ({a})" for a, x in hub.loa.items() if x.paired}
        if not da_ghep:
            return self.async_abort(reason="nothing_paired")
        if user_input is not None:
            dia_chi = user_input["speaker"]
            await hub.async_stop(address=dia_chi)
            try:
                await hub.client.remove(dia_chi)
            except BluezError as exc:
                return self.async_abort(reason="forget_failed",
                                        description_placeholders={"loi": str(exc)[:200]})
            reg = dr.async_get(self.hass)
            if dev := reg.async_get_device(identifiers={(DOMAIN, dia_chi)}):
                reg.async_remove_device(dev.id)
            # Nạp lại cho sạch: ghép lại loa này sau thì thực thể được tạo mới.
            self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
            return self.async_create_entry(data=dict(self.config_entry.options))
        return self.async_show_form(
            step_id="forget",
            data_schema=vol.Schema({vol.Required("speaker"): vol.In(da_ghep)}))
