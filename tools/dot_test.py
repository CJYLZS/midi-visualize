"""最小点灯测试：每隔 10 颗点亮一颗白灯，持续 10 秒后全灭。

用法：
    uv run python tools/dot_test.py

前提：
    - WLED 串口波特率为 921600（与 config.SERIAL_BAUD 一致）
    - COM4 为 ESP32-S3 原生 USB CDC 口
    - 两个 USB 口均已连接（CH340 侧供电，原生 USB 侧通信）
"""

import os
import sys
import time

# 让 src 下的包可以直接 import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from midi_visualize.adalight import (  # noqa: E402
    build_frame,
    open_serial_without_reset as open_safe,
    write_frame,
)
from midi_visualize import config  # noqa: E402

PORT  = "COM4"
BAUD  = config.SERIAL_BAUD
COUNT = config.LED_COUNT
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
STEP  = 10       # 每隔几颗点一颗
HOLD  = 10.0     # 亮灯持续秒数
REFRESH = 1.0    # 在 WLED realtime 超时前续帧
CHUNK_SIZE = config.SERIAL_CHUNK_SIZE
CHUNK_DELAY = config.SERIAL_CHUNK_DELAY


def make_frame(lit: bool) -> bytes:
    if lit:
        colors = [WHITE if i % STEP == 0 else BLACK for i in range(COUNT)]
    else:
        colors = [BLACK] * COUNT
    return build_frame(colors)

def main() -> None:
    lit_count = len(range(0, COUNT, STEP))
    lit_frame = make_frame(True)
    off_frame = make_frame(False)
    print(f"打开 {PORT} @ {BAUD} bps ...")
    with open_safe(PORT, BAUD) as ser:
        print(f"发送亮灯帧：{lit_count} 颗白灯（索引 0, 10, 20, ...）")
        write_frame(ser, lit_frame, chunk_size=CHUNK_SIZE, chunk_delay=CHUNK_DELAY)

        print(f"等待 {HOLD:.0f} 秒 ...")
        deadline = time.monotonic() + HOLD
        next_refresh = time.monotonic() + REFRESH
        while time.monotonic() < deadline:
            now = time.monotonic()
            time.sleep(min(next_refresh - now, deadline - now))
            if time.monotonic() < deadline:
                write_frame(ser, lit_frame, chunk_size=CHUNK_SIZE, chunk_delay=CHUNK_DELAY)
                next_refresh = time.monotonic() + REFRESH

        print("发送全灭帧 ...")
        write_frame(ser, off_frame, chunk_size=CHUNK_SIZE, chunk_delay=CHUNK_DELAY)

    print("完成。")


if __name__ == "__main__":
    main()
