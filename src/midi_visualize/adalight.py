"""Adalight over USB 串口 —— 把灯珠数据推给 WLED。

为什么用串口而不是 WiFi UDP：
    实测该网络的 HTTP 往返中位 46ms、尖峰 2038ms，抖动足以让灯明显卡顿。
    USB Full-Speed 的 1ms 帧长是延迟地板，且无抖动。

为什么用 Adalight 而不是自写固件：
    WLED 0.13+ 原生支持 Adalight 和 tpm2 两种串口协议，可直接流式推送
    灯珠数据。零固件开发。
    见 kno.wled.ge/interfaces/serial/

Adalight 帧格式：
    'A' 'd' 'a'          魔术头
    count_hi             (LED数 - 1) 高字节
    count_lo             (LED数 - 1) 低字节
    checksum             count_hi XOR count_lo XOR 0x55
    R G B × N            像素数据，全量

带宽核算（320 颗 = 966 字节/帧）：
    115200  bps →  11.5 KB/s →  12 FPS   ← WLED 默认值，不够用，勿用
    921600  bps →  92   KB/s →  95 FPS   ← 当前基线，需在 WLED Sync 设置里改一致
    1500000 bps → 150   KB/s → 155 FPS   ← CH340 桥片可能不稳
实测（921600 + 128 字节分块 / 1 ms）：约 80 FPS
"""

import threading
import time

import serial

from . import config

_MAGIC = b"Ada"

Color = tuple[int, int, int]
_BLACK: Color = (0, 0, 0)


class WledConnectionError(RuntimeError):
    """The serial endpoint did not identify itself as WLED."""


class FrameWriteError(RuntimeError):
    """A partial frame may have left WLED waiting for more pixel data."""


def open_serial_without_reset(
    port: str,
    baudrate: int,
    serial_factory=serial.Serial,
):
    """Open a serial port with CDC control lines inactive from the start."""
    serial_port = serial_factory()
    serial_port.port = port
    serial_port.baudrate = baudrate
    serial_port.timeout = 0.1
    serial_port.write_timeout = 0.5
    serial_port.dtr = False
    serial_port.rts = False
    serial_port.open()
    return serial_port


def write_frame(
    serial_port,
    frame: bytes,
    chunk_size: int,
    chunk_delay: float,
    sleep=time.sleep,
) -> None:
    """Write one complete frame in paced chunks."""
    for offset in range(0, len(frame), chunk_size):
        chunk = frame[offset : offset + chunk_size]
        written = serial_port.write(chunk)
        if written != len(chunk):
            raise serial.SerialTimeoutException(
                f"serial short write: {written}/{len(chunk)} bytes"
            )
        serial_port.flush()
        if offset + chunk_size < len(frame):
            sleep(chunk_delay)


def read_wled_version(serial_port, timeout: float = 3.0) -> bytes:
    """Return WLED's version reply from an already-open serial connection."""
    serial_port.reset_input_buffer()
    written = serial_port.write(b"v")
    if written != 1:
        raise serial.SerialTimeoutException(f"serial short write: {written}/1 bytes")
    serial_port.flush()

    reply = bytearray()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        reply.extend(serial_port.read(4096))
        if reply.startswith(b"WLED"):
            return bytes(reply)
    return bytes(reply)


def build_frame(colors: list[Color]) -> bytes:
    """组装一个完整的 Adalight 帧。"""
    n = len(colors) - 1
    hi, lo = (n >> 8) & 0xFF, n & 0xFF
    frame = bytearray(_MAGIC)
    frame.extend((hi, lo, hi ^ lo ^ 0x55))
    for r, g, b in colors:
        frame.extend((r & 0xFF, g & 0xFF, b & 0xFF))
    return bytes(frame)


class SerialSender:
    """维护帧缓冲的串口发送器。

    接口与 warls.WledSender 保持一致，方便两种传输方式互换。
    """

    def __init__(
        self,
        port: str | None = None,
        baudrate: int | None = None,
        led_count: int | None = None,
        serial_factory=serial.Serial,
        probe_timeout: float = 3.0,
        chunk_size: int | None = None,
        chunk_delay: float | None = None,
        sleep=time.sleep,
        monotonic=time.monotonic,
    ):
        self.port = config.SERIAL_PORT if port is None else port
        self.baudrate = config.SERIAL_BAUD if baudrate is None else baudrate
        self.led_count = config.LED_COUNT if led_count is None else led_count
        self._frame: list[Color] = [_BLACK] * self.led_count
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._chunk_size = (
            config.SERIAL_CHUNK_SIZE if chunk_size is None else chunk_size
        )
        self._chunk_delay = (
            config.SERIAL_CHUNK_DELAY if chunk_delay is None else chunk_delay
        )
        self._failed_error: FrameWriteError | None = None
        self.last_sent = 0.0
        self._sleep = sleep
        self._monotonic = monotonic
        self._ser = open_serial_without_reset(
            self.port, self.baudrate, serial_factory=serial_factory
        )
        try:
            version = read_wled_version(self._ser, timeout=probe_timeout)
            if not version.startswith(b"WLED"):
                raise WledConnectionError(
                    f"{self.port} did not return a valid WLED version response; "
                    "check both USB connections and restart WLED before retrying"
                )
        except BaseException:
            self._ser.close()
            raise

    def prepare(self, brightness: int = 200, timeout: float = 5.0) -> bool:
        """串口方式无需预处理。保留此方法以兼容 WledSender 的调用点。

        注意：串口的 Adalight 数据会直接覆盖显示，不受 WLED 的
        realtime override(lor) 影响，所以不存在 UDP 那个坑。
        """
        return True

    # --- 帧缓冲操作 ---

    def set_leds(self, updates: list[tuple[int, Color]], flush: bool = True) -> None:
        with self._lock:
            for index, color in updates:
                if 0 <= index < self.led_count:
                    self._frame[index] = color
        if flush:
            self.flush()

    def set_exclusive(
        self, updates: list[tuple[int, Color]], flush: bool = True
    ) -> None:
        """只让指定的灯亮，其余置黑。清帧与写入在同一个锁内完成。"""
        with self._lock:
            self._frame = [_BLACK] * self.led_count
            for index, color in updates:
                if 0 <= index < self.led_count:
                    self._frame[index] = color
        if flush:
            self.flush()

    def clear(self, flush: bool = True) -> None:
        with self._lock:
            self._frame = [_BLACK] * self.led_count
        if flush:
            self.flush()

    def flush(self) -> None:
        """把当前帧作为不可交错的分块写推给 WLED。"""
        with self._write_lock:
            if self._failed_error is not None:
                raise self._failed_error
            with self._lock:
                snapshot = list(self._frame)
            try:
                write_frame(
                    self._ser,
                    build_frame(snapshot),
                    chunk_size=self._chunk_size,
                    chunk_delay=self._chunk_delay,
                    sleep=self._sleep,
                )
            except (serial.SerialException, OSError) as exc:
                self._failed_error = FrameWriteError(
                    f"serial frame write failed on {self.port}; restart WLED before retrying"
                )
                raise self._failed_error from exc
            self.last_sent = self._monotonic()

    # --- 兼容 WledSender 接口 ---

    def send(self, updates: list[tuple[int, Color]]) -> None:
        self.set_leds(updates)

    def send_exclusive(self, updates: list[tuple[int, Color]]) -> None:
        self.set_exclusive(updates)

    def all_off(self) -> None:
        self.clear()

    # --- 生命周期 ---

    def close(self) -> None:
        self._ser.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        try:
            self.all_off()
        finally:
            self.close()
        return False
