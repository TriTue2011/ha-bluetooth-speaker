"""BlueZ (quét, ghép đôi, kết nối) và bluez-alsa (cổng phát tiếng) qua D-Bus hệ thống.

Python thuần + ``dbus_fast`` (Home Assistant có sẵn) — không phụ thuộc HA, thử được riêng.

bluez-alsa (dịch vụ ``bluealsa`` trên máy có Bluetooth) mở cho mỗi loa A2DP đang kết nối một
"PCM" trên D-Bus. ``Open()`` trả hai fd qua D-Bus: fd tiếng (ghi PCM S16LE thẳng vào) và fd điều
khiển (``Drain``…). fd đi được qua D-Bus cả khi HA nằm trong container hay LXC mượn D-Bus của
máy — đo thật trên Proxmox → LXC → Docker: mở mất 0,4 giây.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass

from dbus_fast import BusType, Message, MessageType, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.service import ServiceInterface, method

BLUEZ = "org.bluez"
BLUEALSA = "org.bluealsa"
#: A2DP Audio Sink — thiết bị nhận tiếng (loa, tai nghe, soundbar).
A2DP_SINK = "0000110b-0000-1000-8000-00805f9b34fb"
AGENT_PATH = "/bluetooth_speaker/agent"
_DIA_CHI = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")


class BluezError(Exception):
    """Lỗi từ BlueZ / bluez-alsa — thông điệp đọc được."""


@dataclass
class Loa:
    """Một loa (thiết bị A2DP Sink) BlueZ biết."""

    address: str
    name: str
    paired: bool
    connected: bool
    path: str


@dataclass
class Pcm:
    """Cổng phát tiếng bluez-alsa của một loa đang kết nối."""

    path: str
    address: str
    channels: int
    sampling: int
    volume: int          # bluez-alsa: (trái << 8) | phải, mỗi kênh 0–127, bit 7 = tắt tiếng


def muc_am_luong(volume: int) -> tuple[float, bool]:
    """Số ``Volume`` của bluez-alsa → (mức 0–1, tắt tiếng?) theo kênh trái."""
    trai = (volume >> 8) & 0xFF
    return (trai & 0x7F) / 127, bool(trai & 0x80)


def so_am_luong(muc: float, tat: bool) -> int:
    """(mức 0–1, tắt tiếng?) → số ``Volume`` cho cả hai kênh."""
    kenh = max(0, min(127, round(muc * 127))) | (0x80 if tat else 0)
    return (kenh << 8) | kenh


def _la_loa(dev: dict) -> bool:
    uuids = dev["UUIDs"].value if "UUIDs" in dev else []
    lop = dev["Class"].value if "Class" in dev else 0
    # Có A2DP Sink; hoặc lớp thiết bị Audio/Video (major 0x04) khi chưa đọc được UUID (lúc quét).
    return A2DP_SINK in uuids or (lop >> 8) & 0x1F == 0x04


class _Agent(ServiceInterface):
    """Agent NoInputNoOutput: loa không có bàn phím — nhận ghép đôi kiểu Just Works."""

    def __init__(self) -> None:
        super().__init__("org.bluez.Agent1")

    @method()
    def Release(self):  # noqa: N802
        pass

    @method()
    def RequestConfirmation(self, device: "o", passkey: "u"):  # noqa: F821,N802
        pass

    @method()
    def RequestAuthorization(self, device: "o"):  # noqa: F821,N802
        pass

    @method()
    def AuthorizeService(self, device: "o", uuid: "s"):  # noqa: F821,N802
        pass

    @method()
    def RequestPinCode(self, device: "o") -> "s":  # noqa: F821,N802
        return "0000"

    @method()
    def RequestPasskey(self, device: "o") -> "u":  # noqa: F821,N802
        return 0

    @method()
    def Cancel(self):  # noqa: N802
        pass


class BluezClient:
    """Một kết nối D-Bus hệ thống tới BlueZ và bluez-alsa."""

    def __init__(self) -> None:
        self.bus: MessageBus | None = None

    async def connect(self) -> None:
        try:
            self.bus = await MessageBus(bus_type=BusType.SYSTEM, negotiate_unix_fd=True).connect()
        except (OSError, EOFError) as exc:
            raise BluezError(f"cannot reach system D-Bus: {exc}") from exc

    def close(self) -> None:
        if self.bus is not None:
            self.bus.disconnect()
            self.bus = None

    async def _call(self, path: str, iface: str, member: str, sig: str = "",
                    body: list | None = None, *, dest: str = BLUEZ,
                    timeout: float = 30) -> Message:
        if self.bus is None:
            raise BluezError("not connected")
        try:
            r = await asyncio.wait_for(self.bus.call(Message(
                destination=dest, path=path, interface=iface, member=member,
                signature=sig, body=body or [])), timeout)
        except TimeoutError as exc:
            raise BluezError(f"{member}: timed out after {timeout:g} s") from exc
        if r.message_type == MessageType.ERROR:
            raise BluezError(f"{r.error_name}: {r.body[0] if r.body else ''}")
        return r

    async def _objects(self) -> dict:
        r = await self._call("/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects")
        return r.body[0]

    async def adapter(self) -> str:
        """Đường D-Bus của bộ Bluetooth đầu tiên."""
        for path, ifaces in (await self._objects()).items():
            if "org.bluez.Adapter1" in ifaces:
                return path
        raise BluezError("no Bluetooth adapter")

    async def speakers(self) -> list[Loa]:
        ra = []
        for path, ifaces in (await self._objects()).items():
            d = ifaces.get("org.bluez.Device1")
            if not d or not _la_loa(d):
                continue
            addr = d["Address"].value
            ra.append(Loa(address=addr, name=d["Alias"].value if "Alias" in d else addr,
                          paired=bool(d["Paired"].value) if "Paired" in d else False,
                          connected=bool(d["Connected"].value) if "Connected" in d else False,
                          path=path))
        return sorted(ra, key=lambda x: (not x.connected, not x.paired, x.name))

    async def scan(self, seconds: float) -> list[Loa]:
        """Quét Bluetooth cổ điển ``seconds`` giây rồi trả danh sách loa."""
        ad = await self.adapter()
        await self._call(ad, "org.bluez.Adapter1", "SetDiscoveryFilter", "a{sv}",
                         [{"Transport": Variant("s", "bredr")}])
        await self._call(ad, "org.bluez.Adapter1", "StartDiscovery")
        try:
            await asyncio.sleep(seconds)
        finally:
            await self._call(ad, "org.bluez.Adapter1", "StopDiscovery")
        return await self.speakers()

    async def _duong(self, address: str) -> str:
        address = address.upper()
        if not _DIA_CHI.match(address):
            raise BluezError(f"invalid address {address}")
        return f"{await self.adapter()}/dev_{address.replace(':', '_')}"

    async def pair(self, address: str) -> None:
        """Ghép đôi (agent NoInputNoOutput) và đánh dấu tin cậy — lần sau tự nối lại được."""
        p = await self._duong(address)
        self.bus.export(AGENT_PATH, _Agent())
        await self._call("/org/bluez", "org.bluez.AgentManager1", "RegisterAgent", "os",
                         [AGENT_PATH, "NoInputNoOutput"])
        try:
            try:
                await self._call(p, "org.bluez.Device1", "Pair", timeout=40)
            except BluezError as exc:
                if "AlreadyExists" not in str(exc):
                    raise
        finally:
            await self._call("/org/bluez", "org.bluez.AgentManager1", "UnregisterAgent", "o",
                             [AGENT_PATH])
            self.bus.unexport(AGENT_PATH)
        await self._call(p, "org.freedesktop.DBus.Properties", "Set", "ssv",
                         ["org.bluez.Device1", "Trusted", Variant("b", True)])

    async def connect_device(self, address: str) -> None:
        await self._call(await self._duong(address), "org.bluez.Device1", "Connect", timeout=40)

    async def disconnect_device(self, address: str) -> None:
        await self._call(await self._duong(address), "org.bluez.Device1", "Disconnect")

    async def remove(self, address: str) -> None:
        ad = await self.adapter()
        await self._call(ad, "org.bluez.Adapter1", "RemoveDevice", "o",
                         [await self._duong(address)])

    # ── bluez-alsa ──────────────────────────────────────────────────────────

    async def pcms(self) -> list[Pcm]:
        """Cổng phát A2DP (máy → loa) của các loa đang kết nối."""
        r = await self._call("/org/bluealsa", "org.bluealsa.Manager1", "GetPCMs", dest=BLUEALSA)
        ra = []
        for path, p in r.body[0].items():
            if p["Mode"].value != "sink" or not str(p["Transport"].value).startswith("A2DP"):
                continue
            m = re.search(r"dev_([0-9A-F_]{17})", path)
            if not m:
                continue
            ra.append(Pcm(path=path, address=m.group(1).replace("_", ":"),
                          channels=int(p["Channels"].value), sampling=int(p["Sampling"].value),
                          volume=int(p["Volume"].value)))
        return ra

    async def open_pcm(self, path: str) -> tuple[int, int]:
        """(fd tiếng, fd điều khiển). Người gọi phải đóng cả hai."""
        r = await self._call(path, "org.bluealsa.PCM1", "Open", dest=BLUEALSA, timeout=10)
        return r.unix_fds[r.body[0]], r.unix_fds[r.body[1]]

    async def set_volume(self, path: str, volume: int) -> None:
        await self._call(path, "org.freedesktop.DBus.Properties", "Set", "ssv",
                         ["org.bluealsa.PCM1", "Volume", Variant("q", volume)], dest=BLUEALSA)

    # ── thay đổi ────────────────────────────────────────────────────────────

    async def watch(self, callback: Callable[[], None]) -> None:
        """Gọi ``callback`` khi loa kết nối / ngắt / cổng phát xuất hiện / mất."""
        for rule in ("type='signal',sender='org.bluealsa',interface='org.bluealsa.Manager1'",
                     # KHÔNG nghe ObjectManager của BlueZ: HA quét BLE làm thiết bị hiện/mất
                     # liên tục (hàng trăm tín hiệu/giờ). Ghép đôi, kết nối đổi thuộc tính;
                     # quên loa do chính tích hợp gọi rồi tự làm mới.
                     "type='signal',sender='org.bluez',"
                     "interface='org.freedesktop.DBus.Properties',arg0='org.bluez.Device1'"):
            await self._call("/org/freedesktop/DBus", "org.freedesktop.DBus", "AddMatch", "s",
                             [rule], dest="org.freedesktop.DBus")

        def _nhan(msg: Message) -> None:
            if msg.message_type != MessageType.SIGNAL:
                return
            if msg.interface == "org.freedesktop.DBus.Properties":
                doi = msg.body[1] if len(msg.body) > 1 else {}
                if not any(k in doi for k in ("Connected", "Paired", "Alias", "UUIDs")):
                    return
            callback()

        self.bus.add_message_handler(_nhan)
