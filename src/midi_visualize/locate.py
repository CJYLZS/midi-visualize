"""交互式定位单颗灯，用来确定 LED_OFFSET。

用法:
    uv run python -m midi_visualize.locate            从 0 开始，键盘控制移动
    uv run python -m midi_visualize.locate --at 30    直接点亮第 30 颗
    uv run python -m midi_visualize.locate --marks    叠加每 10/50 颗的标记点

交互模式按键:
    a / d      左右移动 1 颗
    w / s      左右移动 5 颗
    A / D      左右移动 10 颗
    数字+回车  直接跳到该索引
    q          退出并打印 LED_OFFSET

注意：定位期间需要持续发包，否则 WLED 会在 WARLS_TIMEOUT 秒后
退出 realtime 模式、恢复自身效果。本工具在每次按键后重发整帧。
"""

import argparse
import threading
import time

from . import config
from .transport import describe, make_sender

# 定位期间用高亮度，灯条裸放时也能一眼看清。
# 贴到琴上、觉得刺眼的话把这几个值调低即可。
_CURSOR = (255, 255, 255)      # 光标中心：亮白，精确指示索引
_CURSOR_HALO = (80, 0, 0)      # 光标两翼：暗红，便于在标记中找到光标
_MARK_10 = (0, 200, 0)         # 每 10 颗：亮绿
_MARK_50 = (255, 0, 0)         # 每 50 颗：亮红


def _paint(sender, cursor: int, marks: bool) -> None:
    """把一帧画进缓冲并推送：全黑 + 可选标记 + 光标。

    光标画成"两侧暗红 + 中心亮白"，这样在一堆绿色标记点里也能一眼找到，
    同时中心那颗白灯仍然精确指示索引位置。
    """
    updates: list[tuple[int, tuple[int, int, int]]] = []
    if marks:
        for i in range(0, sender.led_count, 10):
            updates.append((i, _MARK_50 if i % 50 == 0 else _MARK_10))
    # 先画光标两翼，再画中心，确保中心不被覆盖
    for side in (cursor - 1, cursor + 1):
        if 0 <= side < sender.led_count:
            updates.append((side, _CURSOR_HALO))
    updates.append((cursor, _CURSOR))
    sender.set_exclusive(updates)


class _Keepalive:
    """后台重发当前帧，防止 WLED realtime 超时退出。

    只在"距上次发送超过 interval"时才补发。主线程每次移动光标都会
    立即 flush，此时 keepalive 应当保持沉默 —— 否则两个线程同时推
    964 字节的整帧，白白占满带宽并让 WLED 排队，表现为移动卡顿。
    """

    def __init__(self, sender, interval: float = 1.0):
        self._sender = sender
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self) -> None:
        while not self._stop.wait(self._interval / 4):
            if time.monotonic() - self._sender.last_sent >= self._interval:
                self._sender.flush()

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc_info):
        self._stop.set()
        self._thread.join(timeout=2)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--at", type=int, help="直接点亮指定索引后退出")
    parser.add_argument("--marks", action="store_true", help="叠加每 10/50 颗的标记点")
    parser.add_argument("--ip", default=config.ESP32_IP)
    parser.add_argument("--total", type=int, default=config.LED_COUNT)
    args = parser.parse_args()

    sender = make_sender(ip=args.ip, led_count=args.total)

    if not sender.prepare():
        print(f"警告：无法通过 HTTP 配置 {args.ip}。")
        print("如果灯没反应，检查 WLED 里 realtime override 是否为 0、电源是否开启。")

    if args.at is not None:
        _paint(sender, args.at, args.marks)
        # 单次点亮也需要维持几秒，否则立刻超时退出
        for _ in range(6):
            time.sleep(0.5)
            sender.flush()
        print(f"已点亮 LED {args.at}（保持 3 秒）")
        sender.close()
        return

    cursor = 0
    print(__doc__)
    print(f"目标 {describe()}，灯条 {args.total} 颗")
    print("把白色光标移到最低音 A0 琴键的正上方，然后按 q。\n")

    try:
        with _Keepalive(sender):
            while True:
                _paint(sender, cursor, args.marks)
                raw = input(f"当前 LED [{cursor}] > ").strip()

                if not raw:
                    continue
                if raw == "q":
                    break
                if raw.isdigit():
                    cursor = max(0, min(int(raw), args.total - 1))
                    continue

                step = {"a": -1, "d": 1, "A": -10, "D": 10, "w": -5, "s": 5}.get(raw)
                if step is None:
                    print("无效输入。用 a/d(±1) w/s(±5) A/D(±10) 数字 q")
                    continue
                cursor = max(0, min(cursor + step, args.total - 1))
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        print(f"\n最低音 A0 对应 LED_OFFSET = {cursor}")
        print("把这个值写进 src/midi_visualize/config.py 的 LED_OFFSET")
        sender.close()


if __name__ == "__main__":
    main()
