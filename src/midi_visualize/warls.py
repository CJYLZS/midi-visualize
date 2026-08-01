"""DNRGB 协议组包与 UDP 发送。

为什么用 DNRGB 而不是 WARLS：
    WARLS 每灯带 1 字节索引，寻址上限 255 颗。灯条声明 320 颗时，
    第 256~319 颗无法触及，会永久保留 realtime 之前的残留颜色。
    DNRGB 用 2 字节起始索引，可寻址 65535 颗。

包格式（WLED 官方文档 kno.wled.ge/interfaces/udp-realtime）：
    byte 0     = 4        协议标识 DNRGB
    byte 1     = timeout  距最后一包多少秒后退出 realtime
    byte 2     = 起始索引 高字节
    byte 3     = 起始索引 低字节
    byte 4+n*3 = R
    byte 5+n*3 = G
    byte 6+n*3 = B

DNRGB 是连续区间语义，不带每灯索引，所以无法"只发变化的几颗"。
本模块维护一份完整帧缓冲，每次变更后重发整帧。
320 颗 = 960 字节负载，单包装得下，一次 sendto 即可。
"""

import json
import socket
import threading
import time
import urllib.error
import urllib.request

from . import config

_PROTOCOL_DNRGB = 4

# 单包最大灯数：以太网 MTU 1500 - IP/UDP 头 28 - DNRGB 头 4，每灯 3 字节
MAX_LEDS_PER_PACKET = (1500 - 28 - 4) // 3

Color = tuple[int, int, int]
_BLACK: Color = (0, 0, 0)


def build_packet(start_index: int, colors: list[Color]) -> bytes:
    """把一段连续的颜色组装成 DNRGB 包。"""
    packet = bytearray(
        [
            _PROTOCOL_DNRGB,
            config.WARLS_TIMEOUT,
            (start_index >> 8) & 0xFF,
            start_index & 0xFF,
        ]
    )
    for r, g, b in colors:
        packet.extend((r & 0xFF, g & 0xFF, b & 0xFF))
    return bytes(packet)


class WledSender:
    """维护帧缓冲的 UDP 发送器。

    DNRGB 是全量协议，所以这里保存完整帧状态。调用 set_leds() 修改缓冲，
    然后 flush() 推送。set_leds() 默认自动 flush。

    用作 context manager 可保证退出时熄灭所有灯。
    """

    def __init__(
        self,
        ip: str | None = None,
        port: int | None = None,
        led_count: int | None = None,
    ):
        self.ip = ip or config.ESP32_IP
        self.port = port or config.WLED_PORT
        self.led_count = led_count or config.LED_COUNT
        self._frame: list[Color] = [_BLACK] * self.led_count
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # 保护 _frame。后台 keepalive 线程与主线程会并发访问：
        # 没有锁时 set_exclusive() 清帧和写入之间可能被 flush() 插入，
        # 导致发出全黑帧 —— 表现为"连按多次只有一次生效"。
        self._lock = threading.Lock()
        # 上次实际发包的时刻，供 keepalive 判断是否需要补发
        self.last_sent = 0.0

    def prepare(self, brightness: int = 200, timeout: float = 5.0) -> bool:
        """通过 HTTP API 把 WLED 调成能接收 realtime 的状态。

        必须处理三个会让 UDP 包被静默丢弃的状态：

        lor  — realtime override。**2 = 永久覆盖 realtime**，这是 web 界面上
               "always override" 按钮设的值。语义与直觉相反：它让 WLED 继续
               显示本地效果、忽略收到的 realtime 数据。必须设为 0。
        on   — 电源。关闭时所有 realtime 数据都不会显示。
        bri  — 全局亮度。过低时看起来像没生效。

        返回 True 表示成功。失败不抛异常（UDP 本身仍可尝试），只返回 False。
        """
        payload = json.dumps({"lor": 0, "on": True, "bri": brightness}).encode()
        req = urllib.request.Request(
            f"http://{self.ip}/json/state",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout):
                return True
        except (urllib.error.URLError, OSError):
            return False

    # --- 帧缓冲操作 ---

    def set_leds(self, updates: list[tuple[int, Color]], flush: bool = True) -> None:
        """更新若干颗灯的颜色。越界索引静默忽略。"""
        with self._lock:
            for index, color in updates:
                if 0 <= index < self.led_count:
                    self._frame[index] = color
        if flush:
            self.flush()

    def set_exclusive(self, updates: list[tuple[int, Color]], flush: bool = True) -> None:
        """只让指定的灯亮，其余全部置黑。用于定位/校准。

        清帧和写入在同一个锁里完成，避免 keepalive 线程看到中间的全黑状态。
        """
        with self._lock:
            self._frame = [_BLACK] * self.led_count
            for index, color in updates:
                if 0 <= index < self.led_count:
                    self._frame[index] = color
        if flush:
            self.flush()

    def clear(self, flush: bool = True) -> None:
        """帧缓冲全部置黑。"""
        with self._lock:
            self._frame = [_BLACK] * self.led_count
        if flush:
            self.flush()

    def flush(self) -> None:
        """把当前帧缓冲推送给 WLED。超过单包上限时自动分包。

        在锁内快照帧，锁外发送 —— 避免持锁做网络 IO 阻塞其他线程。
        """
        with self._lock:
            snapshot = list(self._frame)
        for offset in range(0, self.led_count, MAX_LEDS_PER_PACKET):
            chunk = snapshot[offset : offset + MAX_LEDS_PER_PACKET]
            self._sock.sendto(build_packet(offset, chunk), (self.ip, self.port))
        self.last_sent = time.monotonic()

    # --- 兼容旧接口 ---

    def send(self, updates: list[tuple[int, Color]]) -> None:
        """增量更新并推送。语义等同 set_leds()。"""
        self.set_leds(updates)

    def send_exclusive(self, updates: list[tuple[int, Color]]) -> None:
        """语义等同 set_exclusive()。"""
        self.set_exclusive(updates)

    def all_off(self) -> None:
        """熄灭所有灯。程序退出前必须调用。"""
        self.clear()

    # --- 生命周期 ---

    def close(self) -> None:
        self._sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        try:
            self.all_off()
        finally:
            self.close()
        return False
