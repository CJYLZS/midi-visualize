"""主程序：监听 MIDI 输入，把最新按键画面发送给 WLED。

用法:
    uv run python -m midi_visualize.main --list          列出 MIDI 输入口
    uv run python -m midi_visualize.main                 自动选第一个输入口
    uv run python -m midi_visualize.main --port "CLP-785"  指定端口
"""

import argparse
import signal
import sys
import threading
import time

import mido

from . import config, mapping
from .frame_writer import LatestFrameWriter
from .transport import describe, make_sender


class MidiLightState:
    """Build complete LED updates from the currently active MIDI notes."""

    def __init__(self, led_mapper=mapping.note_to_leds, color_mapper=mapping.note_to_color):
        self._led_mapper = led_mapper
        self._color_mapper = color_mapper
        self._active = {}
        self._sequence = 0
        self._lock = threading.Lock()

    def handle(self, msg) -> list[tuple[int, tuple[int, int, int]]] | None:
        with self._lock:
            if msg.type == "note_on" and msg.velocity > 0:
                self._sequence += 1
                self._active[msg.note] = (
                    self._sequence,
                    self._color_mapper(msg.note, msg.velocity),
                )
            elif msg.type == "note_off" or (
                msg.type == "note_on" and msg.velocity == 0
            ):
                self._active.pop(msg.note, None)
            elif msg.type == "control_change" and msg.control in (120, 123):
                self._active.clear()
            else:
                return None
            return self._build_updates()

    def _build_updates(self) -> list[tuple[int, tuple[int, int, int]]]:
        colors_by_led = {}
        active_by_sequence = sorted(
            self._active.items(), key=lambda item: item[1][0]
        )
        for note, (_sequence, color) in active_by_sequence:
            for led in self._led_mapper(note):
                colors_by_led[led] = color
        return sorted(colors_by_led.items())


def make_midi_callback(state: MidiLightState, writer):
    """Return a callback that only updates memory and schedules the latest frame."""

    def callback(msg) -> None:
        updates = state.handle(msg)
        if updates is not None:
            writer.submit(updates)

    return callback


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


def run(
    port_name: str,
    sender,
    writer_factory=LatestFrameWriter,
    open_input=mido.open_input,
    poll_interval: float = 0.1,
    color_mapper=mapping.note_to_color,
) -> None:
    """Receive MIDI in callbacks while one worker sends only the latest frame."""
    state = MidiLightState(color_mapper=color_mapper)
    writer = writer_factory(sender, keepalive=config.SERIAL_KEEPALIVE)
    writer.start()
    try:
        with open_input(port_name, callback=make_midi_callback(state, writer)):
            print(f"监听中: {port_name} → {describe()}")
            print("按 Ctrl+C 退出（会自动熄灭所有灯）")
            while not writer.wait_for_failure(poll_interval):
                time.sleep(0)
            writer.raise_if_failed()
    finally:
        writer.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="列出 MIDI 输入口后退出")
    parser.add_argument("--port", help="MIDI 输入口名称（支持部分匹配）")
    parser.add_argument("--ip", help=f"WLED IP，默认 {config.ESP32_IP}")
    parser.add_argument(
        "--mode",
        choices=mapping.COLOR_MODES,
        default=config.COLOR_MODE,
        help="颜色模式（默认按配置）",
    )
    args = parser.parse_args()

    if args.list:
        list_ports()
        return

    port_name = pick_port(args.port)
    color_mapper = mapping.COLOR_MODES[args.mode]

    # SIGINT 交给 KeyboardInterrupt 处理，确保 context manager 的 all_off 能跑到
    signal.signal(signal.SIGINT, signal.default_int_handler)

    sender = make_sender(ip=args.ip)
    healthy = False
    try:
        if not sender.prepare():
            print("警告：设备准备失败，灯可能不响应。")
        try:
            run(port_name, sender, color_mapper=color_mapper)
        except KeyboardInterrupt:
            print("\n退出，熄灭所有灯。")
        sender.all_off()
        healthy = True
    finally:
        sender.close()


if __name__ == "__main__":
    main()
