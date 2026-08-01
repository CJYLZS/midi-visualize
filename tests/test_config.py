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
