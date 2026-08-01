"""MIDI note → LED 索引映射。纯函数，无副作用，无硬件依赖。

每个键映射到以其位置为中心的 3 颗 LED 窗口，相邻键窗口允许重叠。
颜色统一白色，可选力度调亮度。
"""

from . import config

# 一个八度内的黑键位置（相对 C）
_BLACK_KEY_OFFSETS = frozenset({1, 3, 6, 8, 10})


def is_black_key(note: int) -> bool:
    """判断 MIDI note 是否为黑键。"""
    return note % 12 in _BLACK_KEY_OFFSETS


def note_to_leds(note: int) -> list[int]:
    """把 MIDI note 映射成 LED 索引列表。

    超出键盘范围或落在灯条外的索引会被丢弃，返回空列表也是合法结果。
    """
    idx = note - config.FIRST_NOTE
    if not 0 <= idx < config.KEY_COUNT:
        return []

    center = round(idx * config.KEYBOARD_LED_COUNT / config.KEY_COUNT)
    start = center - 1
    end = center + 1
    last = config.KEYBOARD_LED_COUNT - 1
    if start < 0:
        start, end = 0, 2
    elif end > last:
        start, end = last - 2, last

    leds = []
    for i in range(start, end + 1):
        led = i + config.LED_OFFSET
        if config.REVERSED:
            led = config.LED_COUNT - 1 - led
        if 0 <= led < config.LED_COUNT:
            leds.append(led)
    return leds


def note_to_color(note: int, velocity: int) -> tuple[int, int, int]:
    """统一白色，可选用力度调亮度。"""
    base = config.COLOR_WHITE_KEY

    if not config.VELOCITY_TO_BRIGHTNESS:
        return base

    # velocity 1..127 → MIN_BRIGHTNESS..1.0
    v = max(1, min(127, velocity))
    scale = config.MIN_BRIGHTNESS + (1.0 - config.MIN_BRIGHTNESS) * (v - 1) / 126
    return tuple(int(c * scale) for c in base)
