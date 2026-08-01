"""主程序：监听 MIDI 输入，把 note 事件转发成 WARLS UDP 包。

用法:
    uv run python -m midi_visualize.main --list          列出 MIDI 输入口
    uv run python -m midi_visualize.main                 自动选第一个输入口
    uv run python -m midi_visualize.main --port "CLP-785"  指定端口
"""

import argparse
import signal
import sys

import mido

from . import config, mapping
from .transport import describe, make_sender


def list_ports() -> None:
    names = mido.get_input_names()
    if not names:
        print("没有找到 MIDI 输入设备。确认电钢已开机并通过 USB 连接。")
        return
    print("可用的 MIDI 输入口:")
    for i, name in enumerate(names):
        print(f"  [{i}] {name}")


def pick_port(requested: str | None) -> str:
    names = mido.get_input_names()
    if not names:
        sys.exit("没有找到 MIDI 输入设备。用 --list 检查，确认电钢已开机。")

    if requested is None:
        print(f"自动选择: {names[0]}")
        return names[0]

    for name in names:
        if requested.lower() in name.lower():
            print(f"匹配到: {name}")
            return name
    sys.exit(f"找不到匹配 {requested!r} 的输入口。用 --list 查看可用端口。")


def run(port_name: str, sender) -> None:
    """主循环。note on/off 直接在这里转成 UDP 包。

    UDP sendto 是网络 syscall 而非 multimedia 函数，几十微秒返回，
    所以不需要额外的队列和工作线程。
    """
    active: set[int] = set()

    with mido.open_input(port_name) as inport:
        print(f"监听中: {port_name} → {describe()}")
        print("按 Ctrl+C 退出（会自动熄灭所有灯）")

        for msg in inport:
            if msg.type == "note_on" and msg.velocity > 0:
                color = mapping.note_to_color(msg.note, msg.velocity)
                leds = mapping.note_to_leds(msg.note)
                if leds:
                    active.add(msg.note)
                    sender.send([(led, color) for led in leds])

            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                # 有些琴用 velocity=0 的 note_on 代替 note_off
                leds = mapping.note_to_leds(msg.note)
                if leds:
                    active.discard(msg.note)
                    sender.send([(led, (0, 0, 0)) for led in leds])

            elif msg.type == "control_change" and msg.control in (120, 123):
                # CC120 all sound off / CC123 all notes off
                active.clear()
                sender.all_off()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="列出 MIDI 输入口后退出")
    parser.add_argument("--port", help="MIDI 输入口名称（支持部分匹配）")
    parser.add_argument("--ip", help=f"WLED IP，默认 {config.ESP32_IP}")
    args = parser.parse_args()

    if args.list:
        list_ports()
        return

    port_name = pick_port(args.port)

    # SIGINT 交给 KeyboardInterrupt 处理，确保 context manager 的 all_off 能跑到
    signal.signal(signal.SIGINT, signal.default_int_handler)

    with make_sender(ip=args.ip) as sender:
        if not sender.prepare():
            print("警告：设备准备失败，灯可能不响应。")
        try:
            run(port_name, sender)
        except KeyboardInterrupt:
            print("\n退出，熄灭所有灯。")


if __name__ == "__main__":
    main()
