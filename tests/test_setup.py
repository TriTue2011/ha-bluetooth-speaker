"""Tích hợp trong HA thử: thêm, thực thể, phát, bật/tắt, Configure — BlueZ giả lập."""

from datetime import UTC, datetime
from unittest import mock

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
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

    def __init__(self, ffmpeg, url, dich, *, sampling, channels, khi_xong, tu_giay=0.0):
        self.url, self.nguon, self.dich = url, url, dich
        self.khi_xong, self.ly_do = khi_xong, None
        self.vi_tri_goc, self.luc = tu_giay, datetime.now(UTC)
        import threading
        self.xong = threading.Event()
        LuotGia.ds.append(self)

    def bat_dau(self): pass

    def dung(self, ly_do="stopped"):
        """Luồng thật khi bị dừng cũng kết thúc rồi gọi khi_xong; bản giả làm đúng thế."""
        if not self.xong.is_set():
            self.ly_do = self.ly_do or ly_do
            self.xong.set()
            self.khi_xong(self)

    def ket_thuc(self, ly_do):
        """Lượt tự kết thúc (hết bài / lỗi): như luồng phát thật, báo cho hub qua khi_xong."""
        self.ly_do = ly_do
        self.xong.set()
        self.khi_xong(self)

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


async def test_loa_ban_luc_chuyen_bai_thi_cho_roi_mo_lai(hass, client):
    """Bài cũ vừa dừng, bluez-alsa chưa nhả cổng phát: lần mở đầu báo busy, lần sau được."""
    from custom_components.bluetooth_speaker.bluez import BluezError

    lan = []
    goc = client.open_pcm

    async def mo(path):
        lan.append(path)
        if len(lan) < 3:
            raise BluezError("org.freedesktop.DBus.Error.Failed: Device or resource busy")
        return await goc(path)

    client.open_pcm = mo
    LuotGia.ds.clear()
    with mock.patch("custom_components.bluetooth_speaker.LuotPhat", LuotGia):
        await _nap(hass)
        await hass.services.async_call("media_player", "play_media", {
            "entity_id": "media_player.d50s", "media_content_id": "http://x/bai2.mp3",
            "media_content_type": "music"}, blocking=True)
    assert len(lan) == 3 and LuotGia.ds[-1].url == "http://x/bai2.mp3"


async def test_loa_ban_mai_thi_bao_ro(hass, client):
    from custom_components.bluetooth_speaker.bluez import BluezError
    from homeassistant.exceptions import HomeAssistantError

    async def mo(path):
        raise BluezError("org.freedesktop.DBus.Error.Failed: Device or resource busy")

    client.open_pcm = mo
    with mock.patch("custom_components.bluetooth_speaker._CHO_NHA_GIAY", 0.3):
        await _nap(hass)
        with pytest.raises(HomeAssistantError, match="in use by another program"):
            await hass.services.async_call("media_player", "play_media", {
                "entity_id": "media_player.d50s", "media_content_id": "http://x/b.mp3",
                "media_content_type": "music"}, blocking=True)


async def test_tua_khoi_dong_lai_luot_phat_dung_cho_va_bao_vi_tri(hass, client):
    LuotGia.ds.clear()
    with mock.patch("custom_components.bluetooth_speaker.LuotPhat", LuotGia):
        await _nap(hass)
        eid = "media_player.d50s"
        assert hass.states.get(eid).attributes["supported_features"] & 2           # bit 2 = SEEK: thẻ YouTube chỉ gửi media_seek cho loa có bit này
        await hass.services.async_call("media_player", "play_media", {
            "entity_id": eid, "media_content_id": "http://x/bai.m4a", "media_content_type": "music"}, blocking=True)
        cu = LuotGia.ds[-1]
        assert cu.vi_tri_goc == 0.0
        await hass.services.async_call("media_player", "media_seek", {"entity_id": eid, "seek_position": 42}, blocking=True)
        moi = LuotGia.ds[-1]
        assert moi is not cu and cu.xong.is_set()                                   # lượt cũ dừng, lượt mới thay
        assert moi.url == "http://x/bai.m4a" and moi.vi_tri_goc == 42 and [d.ten for d in moi.dich] == [D50]
        a = hass.states.get(eid).attributes
        assert a["media_position"] == 42 and a["media_position_updated_at"] is not None
        assert hass.states.get(eid).state == "playing"


async def test_tua_loa_dang_phat_theo_nhom_giu_nguyen_nhom(hass, client):
    LuotGia.ds.clear()
    with mock.patch("custom_components.bluetooth_speaker.LuotPhat", LuotGia):
        await _nap(hass)
        nhom = "media_player.bluetooth_speaker_all_bluetooth_speakers"
        await hass.services.async_call("media_player", "play_media", {
            "entity_id": nhom, "media_content_id": "http://x/b.m4a", "media_content_type": "music"}, blocking=True)
        # tua từ chính loa: lượt đang phát thuộc nhóm nên tua cả lượt, không tách loa ra
        await hass.services.async_call("media_player", "media_seek", {"entity_id": "media_player.d50s", "seek_position": 10}, blocking=True)
        moi = LuotGia.ds[-1]
        assert moi.vi_tri_goc == 10 and [d.ten for d in moi.dich] == [D50]
        assert hass.states.get(nhom).attributes["media_position"] == 10


async def test_tua_khi_khong_phat_gi_thi_bao_loi_ro(hass, client):
    LuotGia.ds.clear()
    with mock.patch("custom_components.bluetooth_speaker.LuotPhat", LuotGia):
        await _nap(hass)
        with pytest.raises(HomeAssistantError, match="nothing"):
            await hass.services.async_call("media_player", "media_seek", {
                "entity_id": "media_player.d50s", "seek_position": 5}, blocking=True)


async def test_tua_sau_khi_bai_vua_het_thi_khong_phat_lai_bai_cu(hass, client):
    """Bài hết (lượt đã xong) nhưng chưa kịp bị gỡ khỏi bảng: bấm tua không được hồi sinh bài đã hết."""
    LuotGia.ds.clear()
    with mock.patch("custom_components.bluetooth_speaker.LuotPhat", LuotGia):
        await _nap(hass)
        eid = "media_player.d50s"
        await hass.services.async_call("media_player", "play_media", {
            "entity_id": eid, "media_content_id": "http://x/b.m4a", "media_content_type": "music"}, blocking=True)
        so_luot = len(LuotGia.ds)
        LuotGia.ds[-1].xong.set()
        with pytest.raises(HomeAssistantError, match="nothing"):
            await hass.services.async_call("media_player", "media_seek", {"entity_id": eid, "seek_position": 5}, blocking=True)
        assert len(LuotGia.ds) == so_luot


async def test_loa_khai_idle_reason_cho_thuc_the_youtube_phan_biet_het_bai_stop_va_loi(hass, client):
    """Không có idle_reason, tích hợp YouTube coi «loa im giữa bài» là Dừng và gỡ loa khỏi phiên (= «YouTube tự ngắt»)."""
    LuotGia.ds.clear()
    with mock.patch("custom_components.bluetooth_speaker.LuotPhat", LuotGia):
        await _nap(hass)
        eid = "media_player.d50s"

        async def phat():
            await hass.services.async_call("media_player", "play_media", {
                "entity_id": eid, "media_content_id": "http://x/b.m4a", "media_content_type": "music"}, blocking=True)

        await phat()
        assert "idle_reason" not in hass.states.get(eid).attributes                    # đang phát: không có
        LuotGia.ds[-1].ket_thuc("finished")
        await hass.async_block_till_done()
        st = hass.states.get(eid)
        assert st.state == "idle" and st.attributes["idle_reason"] == "finished"

        await phat()
        LuotGia.ds[-1].ket_thuc("error")                                                # luồng đứt
        await hass.async_block_till_done()
        assert hass.states.get(eid).attributes["idle_reason"] == "error"

        await phat()
        await hass.services.async_call("media_player", "media_stop", {"entity_id": eid}, blocking=True)
        await hass.async_block_till_done()
        assert hass.states.get(eid).attributes["idle_reason"] == "stopped"

        so_luot = len(LuotGia.ds)
        await phat()
        await phat()                                                                    # bài mới thay bài cũ
        await hass.async_block_till_done()
        assert LuotGia.ds[so_luot].ly_do == "interrupted"                               # lượt cũ biết mình bị thay, không phải Dừng
        assert hass.states.get(eid).state == "playing" and "idle_reason" not in hass.states.get(eid).attributes
        await hass.services.async_call("media_player", "media_stop", {"entity_id": eid}, blocking=True)


async def test_loa_phat_theo_nhom_het_bai_thi_thuc_the_tung_loa_cung_khai_ly_do(hass, client):
    LuotGia.ds.clear()
    with mock.patch("custom_components.bluetooth_speaker.LuotPhat", LuotGia):
        await _nap(hass)
        nhom = "media_player.bluetooth_speaker_all_bluetooth_speakers"
        await hass.services.async_call("media_player", "play_media", {
            "entity_id": nhom, "media_content_id": "http://x/b.m4a", "media_content_type": "music"}, blocking=True)
        LuotGia.ds[-1].ket_thuc("finished")
        await hass.async_block_till_done()
        assert hass.states.get(nhom).attributes["idle_reason"] == "finished"
        assert hass.states.get("media_player.d50s").attributes["idle_reason"] == "finished"      # YouTube theo dõi từng loa, không theo thực thể nhóm
