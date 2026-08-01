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
    115200  bps →  11.5 KB/s →  12 FPS   ← WLED 默认值，不够用
    921600  bps →  92   KB/s →  95 FPS   ← 需在 WLED Sync 设置里改成这个
    1500000 bps → 150   KB/s → 155 FPS   ← CH340 桥片可能不稳
"""

import threading
import time

import serial

from . import config

_MAGIC = b"Ada"

Color = tuple[int, int, int]
_BLACK: Color = (0, 0, 0)


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
    ):
        self.port = port or config.SERIAL_PORT
        self.baudrate = baudrate or config.SERIAL_BAUD
        self.led_count = led_count or config.LED_COUNT
        self._frame: list[Color] = [_BLACK] * self.led_count
        self._lock = threading.Lock()
        self.last_sent = 0.0
        # write_timeout 防止串口缓冲满时永久阻塞
        self._ser = serial.Serial(
            self.port, self.baudrate, timeout=0.1, write_timeout=0.5
        )
        # 有些板子打开串口会触发复位，等它起来
        time.sleep(0.3)
        self._ser.reset_output_buffer()

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
        """把当前帧推给 WLED。锁内快照、锁外写串口。"""
        with self._lock:
            snapshot = list(self._frame)
        try:
            self._ser.write(build_frame(snapshot))
        except serial.SerialTimeoutException:
            # 串口写超时通常意味着波特率设得比 WLED 侧低，帧堆积了
            pass
        self.last_sent = time.monotonic()

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
