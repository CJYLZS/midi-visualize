"""映射与组包的单元测试。全部不依赖硬件。"""

import pytest

from midi_visualize import config, mapping, warls


class TestBlackKey:
    def test_a0_is_white(self):
        assert not mapping.is_black_key(21)

    def test_c8_is_white(self):
        assert not mapping.is_black_key(108)

    def test_middle_c_is_white(self):
        assert not mapping.is_black_key(60)

    def test_c_sharp_is_black(self):
        assert mapping.is_black_key(61)

    # C#4 D#4 F#4 G#4 A#4 — 一个八度内全部 5 个黑键
    @pytest.mark.parametrize("note", [61, 63, 66, 68, 70])
    def test_all_black_keys_in_octave(self, note):
        assert mapping.is_black_key(note)

    def test_octave_invariance(self):
        # 同名音在不同八度黑白属性一致
        for note in range(21, 109 - 12):
            assert mapping.is_black_key(note) == mapping.is_black_key(note + 12)


class TestNoteToLeds:
    def test_lowest_key_maps_to_start(self):
        leds = mapping.note_to_leds(21)
        assert leds
        assert min(leds) == config.LED_OFFSET

    def test_highest_key_reaches_calibrated_end(self):
        leds = mapping.note_to_leds(108)
        assert leds
        assert max(leds) == config.LED_OFFSET + config.KEYBOARD_LED_COUNT - 1

    def test_below_range_returns_empty(self):
        assert mapping.note_to_leds(20) == []

    def test_above_range_returns_empty(self):
        assert mapping.note_to_leds(109) == []

    def test_every_key_gets_at_least_one_led(self):
        for note in range(21, 109):
            assert mapping.note_to_leds(note), f"note {note} got no LED"

    def test_all_indices_within_calibrated_keyboard_span(self):
        first = config.LED_OFFSET
        last = first + config.KEYBOARD_LED_COUNT - 1
        for note in range(21, 109):
            for led in mapping.note_to_leds(note):
                assert first <= led <= last

    def test_reversed_mapping_mirrors_across_full_strip(self, monkeypatch):
        monkeypatch.setattr(config, "REVERSED", False)
        forward = mapping.note_to_leds(21)
        monkeypatch.setattr(config, "REVERSED", True)

        assert mapping.note_to_leds(21) == [
            config.LED_COUNT - 1 - led for led in forward
        ]

    def test_mapping_is_monotonic(self):
        """音高递增，LED 索引不应倒退。黑白键宽度差异允许重叠，但不允许反向。"""
        prev_start = -1
        for note in range(21, 109):
            leds = mapping.note_to_leds(note)
            assert min(leds) >= prev_start, f"note {note} went backwards"
            prev_start = min(leds)

    def test_every_key_gets_at_least_three_leds(self):
        """每个键至少点亮 3 颗灯。"""
        for note in range(21, 109):
            assert len(mapping.note_to_leds(note)) >= 3, f"note {note}"

    def test_black_and_white_keys_same_width(self):
        """映射不再区分黑白键，宽度一致。"""
        assert len(mapping.note_to_leds(60)) == len(mapping.note_to_leds(61))

    def test_coverage_is_reasonable(self):
        """88 键覆盖的 LED 总数应接近预期的 195 颗。"""
        covered = set()
        for note in range(21, 109):
            covered.update(mapping.note_to_leds(note))
        # 黑键只占一半，所以覆盖数会略少于 LED_COUNT
        assert 150 <= len(covered) <= config.LED_COUNT


class TestVelocityColor:
    def test_black_and_white_same_white(self):
        assert mapping.note_to_color(60, 127) == mapping.note_to_color(61, 127) == (255, 255, 255)

    def test_max_velocity_gives_base_color(self):
        assert mapping.note_to_color(60, 127) == config.COLOR_WHITE_KEY

    def test_louder_is_brighter(self):
        soft = sum(mapping.note_to_color(60, 1))
        loud = sum(mapping.note_to_color(60, 127))
        assert loud > soft

    def test_velocity_clamped(self):
        # 越界的 velocity 不应崩溃或产生非法颜色
        for v in (-5, 0, 200):
            for c in mapping.note_to_color(60, v):
                assert 0 <= c <= 255


class TestDnrgbPacket:
    def test_header(self):
        pkt = warls.build_packet(0, [(1, 2, 3)])
        assert pkt[0] == 4                      # DNRGB 协议标识
        assert pkt[1] == config.WARLS_TIMEOUT

    def test_start_index_is_big_endian(self):
        pkt = warls.build_packet(0x0102, [(0, 0, 0)])
        assert pkt[2] == 0x01
        assert pkt[3] == 0x02

    def test_start_index_above_255(self):
        """DNRGB 的关键能力：能寻址 >255 的索引。"""
        pkt = warls.build_packet(300, [(0, 0, 0)])
        assert (pkt[2] << 8) | pkt[3] == 300

    def test_color_payload(self):
        pkt = warls.build_packet(0, [(10, 20, 30), (40, 50, 60)])
        assert pkt[4:10] == bytes([10, 20, 30, 40, 50, 60])

    def test_packet_length(self):
        pkt = warls.build_packet(0, [(0, 0, 0)] * 5)
        assert len(pkt) == 4 + 5 * 3

    def test_empty_colors_gives_header_only(self):
        assert len(warls.build_packet(0, [])) == 4

    def test_values_are_masked_not_crashed(self):
        pkt = warls.build_packet(0, [(256, -1, 999)])
        assert all(0 <= b <= 255 for b in pkt)

    def test_full_strip_fits_one_packet(self):
        """320 颗全量帧应能装进单包，不必分片。"""
        assert config.LED_COUNT <= warls.MAX_LEDS_PER_PACKET


class TestFrameBuffer:
    def _sender(self):
        # 不发真实网络包，只测缓冲逻辑
        return warls.WledSender(ip="127.0.0.1", led_count=320)

    def test_starts_all_black(self):
        s = self._sender()
        assert s._frame == [(0, 0, 0)] * 320
        s.close()

    def test_set_leds_is_incremental(self):
        s = self._sender()
        s.set_leds([(5, (1, 2, 3))], flush=False)
        s.set_leds([(9, (4, 5, 6))], flush=False)
        assert s._frame[5] == (1, 2, 3)
        assert s._frame[9] == (4, 5, 6)   # 前一次的没被清掉
        s.close()

    def test_set_exclusive_clears_others(self):
        s = self._sender()
        s.set_leds([(5, (1, 2, 3))], flush=False)
        s.set_exclusive([(9, (4, 5, 6))])
        assert s._frame[5] == (0, 0, 0)   # 被清掉了
        assert s._frame[9] == (4, 5, 6)
        s.close()

    def test_out_of_range_index_ignored(self):
        s = self._sender()
        s.set_leds([(999, (1, 2, 3)), (-1, (1, 2, 3))], flush=False)
        assert s._frame == [(0, 0, 0)] * 320
        s.close()

    def test_can_address_beyond_255(self):
        """这是换 DNRGB 的根本原因。"""
        s = self._sender()
        s.set_leds([(300, (7, 8, 9))], flush=False)
        assert s._frame[300] == (7, 8, 9)
        s.close()

    def test_clear_resets_all(self):
        s = self._sender()
        s.set_leds([(1, (9, 9, 9)), (300, (9, 9, 9))], flush=False)
        s.clear(flush=False)
        assert s._frame == [(0, 0, 0)] * 320
        s.close()
