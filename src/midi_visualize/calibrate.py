"""校准工具。硬件到货后按顺序用这几个命令。

    uv run python -m midi_visualize.calibrate ping        点亮第 0 颗灯（验证当前传输通路）
    uv run python -m midi_visualize.calibrate ends        只点亮 A0 和 C8（校准两端）
    uv run python -m midi_visualize.calibrate sweep       逐键扫描（看整体对齐）
    uv run python -m midi_visualize.calibrate all         全部点亮（看覆盖范围）
    uv run python -m midi_visualize.calibrate off         全部熄灭

校准顺序:
    1. ping  —— 确认能通。不亮时检查串口、WLED 和灯条供电。
    2. ends  —— 调 config.LED_OFFSET 让 A0 对准第一个键。
    3. ends  —— 调 config.KEYBOARD_LED_COUNT 让 C8 对准最后一个键。
    4. sweep —— 整体验收。
"""

import argparse
import time

from . import config, mapping
from .transport import describe, make_sender

_RED = (255, 0, 0)
_GREEN = (0, 255, 0)
_BLUE = (0, 80, 255)


def cmd_ping(sender) -> None:
    print(f"点亮 LED 0 为红色，其余全灭。目标 {describe()}")
    print("如果没反应，检查 COM4、两个 USB 连接、WLED 状态和灯条供电。")
    sender.send_exclusive([(0, _RED)])


def cmd_ends(sender) -> None:
    low = mapping.note_to_leds(21)    # A0
    high = mapping.note_to_leds(108)  # C8
    sender.send_exclusive(
        [(led, _GREEN) for led in low] + [(led, _RED) for led in high]
    )
    print(f"绿 = A0 → LED {low}")
    print(f"红 = C8 → LED {high}")
    last = config.LED_OFFSET + config.KEYBOARD_LED_COUNT - 1
    print(
        f"当前参数: LED_OFFSET={config.LED_OFFSET}  "
        f"KEYBOARD_LED_COUNT={config.KEYBOARD_LED_COUNT}  "
        f"范围 LED {config.LED_OFFSET}..{last}"
    )
    print()
    print("绿灯没对准最低音键 → 调 LED_OFFSET")
    print("红灯没对准最高音键 → 调 KEYBOARD_LED_COUNT")


def cmd_sweep(sender, delay: float) -> None:
    print(f"从 A0 扫到 C8，每键 {delay}s。观察灯是否跟着琴键位置走。")
    for note in range(config.FIRST_NOTE, config.FIRST_NOTE + config.KEY_COUNT):
        leds = mapping.note_to_leds(note)
        if not leds:
            continue
        color = _BLUE if not mapping.is_black_key(note) else _RED
        sender.send([(led, color) for led in leds])
        time.sleep(delay)
        sender.send([(led, (0, 0, 0)) for led in leds])


def cmd_all(sender) -> None:
    updates = []
    for note in range(config.FIRST_NOTE, config.FIRST_NOTE + config.KEY_COUNT):
        color = _RED if mapping.is_black_key(note) else _BLUE
        for led in mapping.note_to_leds(note):
            updates.append((led, color))
    sender.send(updates)
    covered = len({led for led, _ in updates})
    print(f"88 键共覆盖 {covered} 颗灯（LED_COUNT={config.LED_COUNT}）")
    print("蓝 = 白键，红 = 黑键。检查是否覆盖整个键盘宽度。")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["ping", "ends", "sweep", "all", "off"])
    parser.add_argument("--ip", help=f"WLED IP，默认 {config.ESP32_IP}")
    parser.add_argument("--delay", type=float, default=0.15, help="sweep 每键停留秒数")
    args = parser.parse_args()

    # 这些命令需要灯保持亮着，所以不用 context manager（否则退出就全灭了）
    sender = make_sender(ip=args.ip)
    if not sender.prepare():
        print("警告：设备准备失败，灯可能不响应。")
    try:
        if args.command == "ping":
            cmd_ping(sender)
        elif args.command == "ends":
            cmd_ends(sender)
        elif args.command == "sweep":
            cmd_sweep(sender, args.delay)
        elif args.command == "all":
            cmd_all(sender)
        elif args.command == "off":
            sender.all_off()
            print("已全部熄灭。")
    finally:
        sender.close()


if __name__ == "__main__":
    main()
