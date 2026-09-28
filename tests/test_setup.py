"""Tích hợp trong HA thử: thêm, thực thể, phát, bật/tắt, Configure — BlueZ giả lập."""

from unittest import mock

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bluetooth_speaker.bluez import Loa, Pcm
from custom_components.bluetooth_speaker.const import DOMAIN

D50 = "00:13:EF:A0:08:00"
JBL = "11:22:33:44:55:66"


class ClientGia:
    """BluezClient giả: D50 đã ghép đôi + đang nối; JBL mới thấy khi quét."""

    def __init__(self):
        self.goi: list[tuple] = []
        self.loa = {D50: Loa(D50, "D50s", True, True, "/org/bluez/hci0/dev_00_13_EF_A0_08_00")}
        self.quet_thay = {JBL: Loa(JBL, "JBL Go", False, False, "/org/bluez/hci0/dev_11")}

    async def connect(self): pass
    def close(self): pass
    async def adapter(self): return "/org/bluez/hci0"
    async def watch(self, cb): self.cb = cb
    async def speakers(self): return list(self.loa.values())

    async def pcms(self):
        return [Pcm(f"/org/bluealsa/{a}", a, 2, 48000, 0x7F7F)
                for a, x in self.loa.items() if x.connected]

    async def scan(self, giay):
        self.goi.append(("scan", giay))
        self.loa.update(self.quet_thay)
        return list(self.loa.values())

    async def pair(self, a):
        self.goi.append(("pair", a))
        self.loa[a].paired = True

    async def connect_device(self, a):
        self.goi.append(("connect", a))
        self.loa[a].connected = True

    async def disconnect_device(self, a):
        self.goi.append(("disconnect", a))
        self.loa[a].connected = False

    async def remove(self, a):
        self.goi.append(("remove", a))
        self.loa.pop(a)

    async def open_pcm(self, path):
        self.goi.append(("open", path))
        return 900, 901

    async def set_volume(self, path, v):
        self.goi.append(("volume", path, v))


@pytest.fixture
def client():
    c = ClientGia()
    with mock.patch("custom_components.bluetooth_speaker.BluezClient", return_value=c), \
            mock.patch("custom_components.bluetooth_speaker.config_flow.BluezClient",
                       return_value=c):
        yield c


class LuotGia:
    ds: list = []

    def __init__(self, ffmpeg, url, dich, *, sampling, channels, khi_xong):
        self.url, self.dich = url, dich
        import threading
        self.xong = threading.Event()
        LuotGia.ds.append(self)

    def bat_dau(self): pass

    def dung(self): self.xong.set()

    def cho(self, t=None): return True


async def _nap(hass):
    assert await async_setup_component(hass, "homeassistant", {})
    muc = MockConfigEntry(domain=DOMAIN, title="Bluetooth Speaker", data={}, unique_id=DOMAIN)
    muc.add_to_hass(hass)
    assert await hass.config_entries.async_setup(muc.entry_id)
    await hass.async_block_till_done()
    return muc


async def test_them_tich_hop_kiem_may(hass, client):
    kq = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert kq["type"] is FlowResultType.FORM
    with mock.patch("custom_components.bluetooth_speaker.async_setup_entry", return_value=True):
        kq = await hass.config_entries.flow.async_configure(kq["flow_id"], {})
    assert kq["type"] is FlowResultType.CREATE_ENTRY


async def test_thieu_bluealsa_thi_bao_ro(hass, client):
    from custom_components.bluetooth_speaker.bluez import BluezError

    async def _loi():
        raise BluezError("org.freedesktop.DBus.Error.ServiceUnknown")

    client.pcms = _loi
    kq = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    kq = await hass.config_entries.flow.async_configure(kq["flow_id"], {})
    assert kq["errors"] == {"base": "no_bluealsa"}


async def test_thuc_the_va_phat(hass, client):
    LuotGia.ds.clear()
    with mock.patch("custom_components.bluetooth_speaker.LuotPhat", LuotGia):
        await _nap(hass)
        loa = hass.states.get("media_player.d50s")
        nhom = hass.states.get("media_player.bluetooth_speaker_all_bluetooth_speakers")
        assert loa.state == "idle" and loa.attributes["volume_level"] == 1.0
        assert nhom.state == "idle" and nhom.attributes["speakers"] == ["D50s"]

        await hass.services.async_call("media_player", "play_media", {
            "entity_id": "media_player.d50s", "media_content_id": "http://x/bai.mp3",
            "media_content_type": "music"}, blocking=True)
        assert LuotGia.ds[-1].url == "http://x/bai.mp3"
        assert [d.ten for d in LuotGia.ds[-1].dich] == [D50]
        assert hass.states.get("media_player.d50s").state == "playing"

        await hass.services.async_call("media_player", "volume_set", {
            "entity_id": "media_player.d50s", "volume_level": 0.5}, blocking=True)
        assert ("volume", f"/org/bluealsa/{D50}", (64 << 8) | 64) in client.goi

        await hass.services.async_call("media_player", "turn_off",
                                       {"entity_id": "media_player.d50s"}, blocking=True)
        assert ("disconnect", D50) in client.goi
        assert hass.states.get("media_player.d50s").state == "off"
        assert LuotGia.ds[-1].xong.is_set()                   # tắt loa thì dừng phát


async def test_configure_quet_ghep_doi_ket_noi_them_thuc_the(hass, client):
    with mock.patch("custom_components.bluetooth_speaker.const.QUET_GIAY", 0):
        muc = await _nap(hass)
        kq = await hass.config_entries.options.async_init(muc.entry_id)
        assert kq["type"] is FlowResultType.MENU
        kq = await hass.config_entries.options.async_configure(kq["flow_id"],
                                                               {"next_step_id": "scan"})
        kq = await hass.config_entries.options.async_configure(kq["flow_id"], {})
        assert kq["step_id"] == "pick"
        kq = await hass.config_entries.options.async_configure(kq["flow_id"], {"speaker": JBL})
        assert kq["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
    assert ("pair", JBL) in client.goi and ("connect", JBL) in client.goi
    assert hass.states.get("media_player.jbl_go").state == "idle"


async def test_nhom_phat_ra_moi_loa_dang_noi(hass, client):
    client.loa[JBL] = Loa(JBL, "JBL Go", True, True, "/x")
    LuotGia.ds.clear()
    with mock.patch("custom_components.bluetooth_speaker.LuotPhat", LuotGia):
        await _nap(hass)
        await hass.services.async_call("media_player", "play_media", {
            "entity_id": "media_player.bluetooth_speaker_all_bluetooth_speakers",
            "media_content_id": "http://x/tts.mp3", "media_content_type": "music"},
            blocking=True)
    assert sorted(d.ten for d in LuotGia.ds[-1].dich) == sorted([D50, JBL])
    assert hass.states.get("media_player.jbl_go").state == "playing"
