"""MIDI note → LED 索引映射。纯函数，无副作用，无硬件依赖。

每个键映射到以其位置为中心的 3 颗 LED 窗口，相邻键窗口允许重叠。
颜色按 COLOR_MODES 里的模式决定（默认白色），可选力度调亮度。
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


def hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    """HSV → RGB。h ∈ [0, 360)，s, v ∈ [0, 1]。返回 0..255 整数三元组。"""
    h = h % 360.0
    c = v * s
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = v - c
    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    return (int(round((r + m) * 255)), int(round((g + m) * 255)), int(round((b + m) * 255)))


def _scale_for_velocity(base: tuple[int, int, int], velocity: int) -> tuple[int, int, int]:
    """按力度缩放颜色亮度。velocity 1..127 → MIN_BRIGHTNESS..1.0。"""
    if not config.VELOCITY_TO_BRIGHTNESS:
        return base
    v = max(1, min(127, velocity))
    scale = config.MIN_BRIGHTNESS + (1.0 - config.MIN_BRIGHTNESS) * (v - 1) / 126
    return tuple(int(c * scale) for c in base)


def note_to_color(note: int, velocity: int) -> tuple[int, int, int]:
    """统一白色，可选用力度调亮度。"""
    return _scale_for_velocity(config.COLOR_WHITE_KEY, velocity)


def note_to_color_rainbow(note: int, velocity: int) -> tuple[int, int, int]:
    """八度彩虹：每个八度一个颜色（45°/八度，钢琴 7 个八度正好 7 色）。"""
    octave = note // 12
    return _scale_for_velocity(hsv_to_rgb(octave * 45, 1.0, 1.0), velocity)


def note_to_color_hue(note: int, velocity: int) -> tuple[int, int, int]:
    """音高色相环：12 音高各占 30° 色相，同名音同色。"""
    hue = (note % 12) * 30
    return _scale_for_velocity(hsv_to_rgb(hue, 1.0, 1.0), velocity)


COLOR_MODES = {
    "white": note_to_color,
    "rainbow": note_to_color_rainbow,
    "hue": note_to_color_hue,
}
