from midi_visualize import config


def test_serial_defaults_match_the_verified_wled_baseline():
    assert config.SERIAL_PORT == "COM4"
    assert config.SERIAL_BAUD == 921600
    assert config.SERIAL_CHUNK_SIZE == 128
    assert config.SERIAL_CHUNK_DELAY == 0.001
    assert config.SERIAL_KEEPALIVE == 1.0


def test_keyboard_calibration_matches_measured_span():
    assert config.LED_OFFSET == 97
    assert config.KEYBOARD_LED_COUNT == 196
    assert config.LED_OFFSET + config.KEYBOARD_LED_COUNT - 1 == 292
    assert not hasattr(config, "LEDS_PER_KEY")


def _assert_valid_hsl(hsl):
    assert len(hsl) == 3, f"{hsl} 不是 (H, S, L) 三元组"
    h, s, l = hsl
    assert 0 <= h <= 360, f"色相 {h} 越界"
    assert 0 <= s <= 100, f"饱和度 {s} 越界"
    assert 0 <= l <= 100, f"亮度 {l} 越界"


def test_colors_are_configured_in_hsl_not_rgb():
    # 旧的 RGB 常量已废弃，留着会让人以为还能分别配黑白键
    assert not hasattr(config, "COLOR_WHITE_KEY")
    assert not hasattr(config, "COLOR_BLACK_KEY")


def test_default_color_is_the_agreed_hsl():
    assert config.COLOR_DEFAULT_HSL == (216, 69, 50)
    _assert_valid_hsl(config.COLOR_DEFAULT_HSL)


def test_pitch_table_has_exactly_twelve_valid_entries():
    """少一行会让 note % 12 直接 IndexError，这里提前拦住。"""
    assert len(config.PITCH_COLORS_HSL) == 12
    for hsl in config.PITCH_COLORS_HSL:
        _assert_valid_hsl(hsl)


def test_octave_rainbow_params_are_valid():
    assert 0 < config.OCTAVE_HUE_STEP <= 360
    assert 0 <= config.OCTAVE_SATURATION <= 100
    assert 0 <= config.OCTAVE_LIGHTNESS <= 100
