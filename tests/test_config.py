from midi_visualize import config


def test_serial_defaults_match_the_verified_wled_baseline():
    assert config.SERIAL_PORT == "COM4"
    assert config.SERIAL_BAUD == 115200
    assert config.SERIAL_CHUNK_SIZE == 16
    assert config.SERIAL_CHUNK_DELAY == 0.003
    assert config.SERIAL_KEEPALIVE == 1.0
