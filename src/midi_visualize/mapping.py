"""MIDI note → LED 索引映射。纯函数，无副作用，无硬件依赖。

做法沿用 couitchy/PianoLights 已验证的方案：
可调小数 LEDS_PER_KEY + OFFSET + REVERSED，黑键宽度取一半。

为什么不用整数每键：160 LED/m 覆盖 1.22m 键盘 = 2.22 颗/键，
本来就不是整数。有些键分到 2 颗、有些 3 颗是数学必然，不是 bug。
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

    start = round(idx * config.LEDS_PER_KEY)
    end = round((idx + 1) * config.LEDS_PER_KEY)
    if end <= start:
        end = start + 1  # 每键至少占 1 颗

    if is_black_key(note):
        # 黑键物理上比白键窄，占一半宽度。
        # 键盘左半边靠右对齐、右半边靠左对齐，这样黑键视觉上更贴近实际位置。
        half = max(1, (end - start) // 2)
        if idx < config.KEY_COUNT // 2:
            start = end - half
        else:
            end = start + half

    leds = []
    for i in range(start, end):
        led = i + config.LED_OFFSET
        if config.REVERSED:
            led = config.LED_COUNT - 1 - led
        if 0 <= led < config.LED_COUNT:
            leds.append(led)
    return leds


def note_to_color(note: int, velocity: int) -> tuple[int, int, int]:
    """按黑白键选基色，可选用力度调亮度。"""
    base = config.COLOR_BLACK_KEY if is_black_key(note) else config.COLOR_WHITE_KEY

    if not config.VELOCITY_TO_BRIGHTNESS:
        return base

    # velocity 1..127 → MIN_BRIGHTNESS..1.0
    v = max(1, min(127, velocity))
    scale = config.MIN_BRIGHTNESS + (1.0 - config.MIN_BRIGHTNESS) * (v - 1) / 126
    return tuple(int(c * scale) for c in base)
