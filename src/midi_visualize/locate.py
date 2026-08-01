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

注意：定位期间由唯一后台 writer 续发最新完整帧，防止 WLED 退出
realtime 模式，并避免前台更新与 keepalive 的串口块交错。
"""

import argparse
import time

from . import config
from .frame_writer import LatestFrameWriter
from .transport import describe, make_sender

# 定位期间用高亮度，灯条裸放时也能一眼看清。
# 贴到琴上、觉得刺眼的话把这几个值调低即可。
_CURSOR = (255, 255, 255)      # 光标中心：亮白，精确指示索引
_CURSOR_HALO = (80, 0, 0)      # 光标两翼：暗红，便于在标记中找到光标
_MARK_10 = (0, 200, 0)         # 每 10 颗：亮绿
_MARK_50 = (255, 0, 0)         # 每 50 颗：亮红


def _paint(writer, led_count: int, cursor: int, marks: bool) -> None:
    """把一帧画进缓冲并推送：全黑 + 可选标记 + 光标。

    光标画成"两侧暗红 + 中心亮白"，这样在一堆绿色标记点里也能一眼找到，
    同时中心那颗白灯仍然精确指示索引位置。
    """
    updates: list[tuple[int, tuple[int, int, int]]] = []
    if marks:
        for i in range(0, led_count, 10):
            updates.append((i, _MARK_50 if i % 50 == 0 else _MARK_10))
    # 先画光标两翼，再画中心，确保中心不被覆盖
    for side in (cursor - 1, cursor + 1):
        if 0 <= side < led_count:
            updates.append((side, _CURSOR_HALO))
    updates.append((cursor, _CURSOR))
    writer.submit(updates)


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
    writer = LatestFrameWriter(sender, keepalive=config.SERIAL_KEEPALIVE)
    writer.start()

    if not sender.prepare():
        print("警告：设备准备失败，灯可能不响应。")

    if args.at is not None:
        try:
            _paint(writer, args.total, args.at, args.marks)
            time.sleep(3.0)
            writer.raise_if_failed()
            print(f"已点亮 LED {args.at}（保持 3 秒）")
        finally:
            writer.stop()
            sender.close()
        return

    cursor = 0
    print(__doc__)
    print(f"目标 {describe()}，灯条 {args.total} 颗")
    print("把白色光标移到最低音 A0 琴键的正上方，然后按 q。\n")

    try:
        while True:
            _paint(writer, args.total, cursor, args.marks)
            writer.raise_if_failed()
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
        try:
            writer.stop()
        finally:
            sender.close()


if __name__ == "__main__":
    main()
