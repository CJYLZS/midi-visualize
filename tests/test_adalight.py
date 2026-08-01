import threading

import pytest

from midi_visualize import adalight, config


class RecordingSerial:
    def __init__(self):
        self.events = []

    def __setattr__(self, name, value):
        if name != "events" and "events" in self.__dict__:
            self.events.append((name, value))
        super().__setattr__(name, value)

    def open(self):
        self.events.append(("open", None))

    def write(self, data):
        self.events.append(("write", data))
        return len(data)

    def flush(self):
        self.events.append(("flush", None))


class WledSerial(RecordingSerial):
    def __init__(self, reply=b"WLED 2606301\r\n"):
        super().__init__()
        self.reply = reply
        self.closed = False

    def reset_input_buffer(self):
        self.events.append(("reset_input_buffer", None))

    def read(self, _size):
        reply, self.reply = self.reply, b""
        return reply

    def close(self):
        self.closed = True
        self.events.append(("close", None))


class ShortWriteSerial(WledSerial):
    def __init__(self):
        super().__init__()
        self.short_write = False

    def write(self, data):
        self.events.append(("write", data))
        if self.short_write:
            return len(data) - 1
        return len(data)


class BlockingSerial(WledSerial):
    def __init__(self):
        super().__init__()
        self.first_chunk_written = threading.Event()
        self.release_first_frame = threading.Event()
        self._blocked = False

    def write(self, data):
        self.events.append(("write", data))
        if threading.current_thread().name == "first-frame" and not self._blocked:
            self._blocked = True
            self.first_chunk_written.set()
            assert self.release_first_frame.wait(1.0)
        return len(data)


class SignalingLock:
    def __init__(self):
        self._lock = threading.Lock()
        self.second_waiting = threading.Event()

    def __enter__(self):
        if threading.current_thread().name == "second-frame":
            self.second_waiting.set()
        self._lock.acquire()
        return self

    def __exit__(self, *_exc_info):
        self._lock.release()


def test_open_serial_sets_control_lines_before_open():
    open_serial = getattr(adalight, "open_serial_without_reset", None)
    assert open_serial is not None, "adalight needs a shared safe serial opener"

    serial_port = RecordingSerial()
    result = open_serial("COM4", 115200, serial_factory=lambda: serial_port)

    assert result is serial_port
    open_index = serial_port.events.index(("open", None))
    assert serial_port.events.index(("dtr", False)) < open_index
    assert serial_port.events.index(("rts", False)) < open_index
    assert serial_port.port == "COM4"
    assert serial_port.baudrate == 115200
    assert serial_port.timeout == 0.1
    assert serial_port.write_timeout == 0.5


def test_write_frame_sends_all_bytes_in_paced_chunks():
    write_frame = getattr(adalight, "write_frame", None)
    assert write_frame is not None, "adalight needs a shared paced frame writer"

    serial_port = RecordingSerial()
    delays = []
    frame = bytes(range(40))

    write_frame(
        serial_port,
        frame,
        chunk_size=16,
        chunk_delay=0.003,
        sleep=delays.append,
    )

    writes = [value for event, value in serial_port.events if event == "write"]
    assert writes == [frame[:16], frame[16:32], frame[32:]]
    assert serial_port.events.count(("flush", None)) == 3
    assert delays == [0.003, 0.003]


def test_serial_sender_verifies_wled_on_the_open_connection():
    serial_port = WledSerial()

    sender = adalight.SerialSender(
        port="COM4",
        baudrate=115200,
        led_count=2,
        serial_factory=lambda: serial_port,
        probe_timeout=0.01,
        sleep=lambda _seconds: None,
    )

    writes = [value for event, value in serial_port.events if event == "write"]
    assert writes == [b"v"]
    assert not serial_port.closed
    sender.close()


def test_serial_sender_closes_port_when_wled_probe_fails():
    serial_port = WledSerial(reply=b"not WLED")

    with pytest.raises(adalight.WledConnectionError, match="restart WLED"):
        adalight.SerialSender(
            port="COM4",
            baudrate=115200,
            led_count=2,
            serial_factory=lambda: serial_port,
            probe_timeout=0.01,
            sleep=lambda _seconds: None,
        )

    assert serial_port.closed


def test_serial_sender_flush_uses_paced_complete_frame_write():
    serial_port = WledSerial()
    delays = []
    sender = adalight.SerialSender(
        port="COM4",
        baudrate=115200,
        led_count=12,
        serial_factory=lambda: serial_port,
        probe_timeout=0.01,
        chunk_size=16,
        chunk_delay=0.003,
        sleep=delays.append,
        monotonic=lambda: 123.0,
    )
    serial_port.events.clear()
    colors = [(1, 2, 3)] + [(0, 0, 0)] * 11
    sender.set_leds([(0, (1, 2, 3))], flush=False)

    sender.flush()

    frame = adalight.build_frame(colors)
    writes = [value for event, value in serial_port.events if event == "write"]
    assert writes == [frame[:16], frame[16:32], frame[32:]]
    assert delays == [0.003, 0.003]
    assert sender.last_sent == 123.0
    sender.close()


def test_serial_sender_uses_shared_pacing_defaults(monkeypatch):
    monkeypatch.setattr(config, "SERIAL_CHUNK_SIZE", 23)
    monkeypatch.setattr(config, "SERIAL_CHUNK_DELAY", 0.007)
    serial_port = WledSerial()
    sender = adalight.SerialSender(
        port="COM4",
        baudrate=115200,
        led_count=2,
        serial_factory=lambda: serial_port,
        probe_timeout=0.01,
    )

    assert sender._chunk_size == 23
    assert sender._chunk_delay == 0.007
    sender.close()


def test_serial_sender_becomes_unusable_after_partial_frame_failure():
    serial_port = ShortWriteSerial()
    sender = adalight.SerialSender(
        port="COM4",
        baudrate=115200,
        led_count=12,
        serial_factory=lambda: serial_port,
        probe_timeout=0.01,
        chunk_size=16,
        chunk_delay=0.003,
        sleep=lambda _seconds: None,
        monotonic=lambda: 123.0,
    )
    serial_port.events.clear()
    serial_port.short_write = True

    with pytest.raises(adalight.FrameWriteError, match="restart WLED"):
        sender.flush()

    assert sender.last_sent == 0.0
    writes_after_failure = len(
        [value for event, value in serial_port.events if event == "write"]
    )
    serial_port.short_write = False

    with pytest.raises(adalight.FrameWriteError, match="restart WLED"):
        sender.flush()

    writes_after_retry = len(
        [value for event, value in serial_port.events if event == "write"]
    )
    assert writes_after_retry == writes_after_failure
    sender.close()


def test_concurrent_flushes_never_interleave_frame_chunks():
    serial_port = BlockingSerial()
    sender = adalight.SerialSender(
        port="COM4",
        baudrate=115200,
        led_count=12,
        serial_factory=lambda: serial_port,
        probe_timeout=0.01,
        chunk_size=16,
        chunk_delay=0,
        sleep=lambda _seconds: None,
    )
    serial_port.events.clear()
    red = [(10, 0, 0)] + [(0, 0, 0)] * 11
    blue = [(0, 0, 20)] + [(0, 0, 0)] * 11
    sender.set_exclusive([(0, red[0])], flush=False)

    first = threading.Thread(target=sender.flush, name="first-frame")
    first.start()
    assert serial_port.first_chunk_written.wait(1.0)

    sender.set_exclusive([(0, blue[0])], flush=False)
    second = threading.Thread(target=sender.flush, name="second-frame")
    second.start()
    second.join(timeout=0.1)
    serial_port.release_first_frame.set()
    first.join(timeout=1.0)
    second.join(timeout=1.0)

    assert not first.is_alive()
    assert not second.is_alive()
    writes = b"".join(
        value for event, value in serial_port.events if event == "write"
    )
    assert writes == adalight.build_frame(red) + adalight.build_frame(blue)
    sender.close()


def test_waiting_flush_takes_snapshot_after_acquiring_write_lock():
    serial_port = BlockingSerial()
    sender = adalight.SerialSender(
        port="COM4",
        baudrate=115200,
        led_count=12,
        serial_factory=lambda: serial_port,
        probe_timeout=0.01,
        chunk_size=16,
        chunk_delay=0,
        sleep=lambda _seconds: None,
    )
    sender._write_lock = SignalingLock()
    serial_port.events.clear()
    red = [(10, 0, 0)] + [(0, 0, 0)] * 11
    blue = [(0, 0, 20)] + [(0, 0, 0)] * 11
    green = [(0, 30, 0)] + [(0, 0, 0)] * 11
    sender.set_exclusive([(0, red[0])], flush=False)

    first = threading.Thread(target=sender.flush, name="first-frame")
    first.start()
    assert serial_port.first_chunk_written.wait(1.0)

    sender.set_exclusive([(0, blue[0])], flush=False)
    second = threading.Thread(target=sender.flush, name="second-frame")
    second.start()
    assert sender._write_lock.second_waiting.wait(1.0)
    sender.set_exclusive([(0, green[0])], flush=False)
    serial_port.release_first_frame.set()
    first.join(timeout=1.0)
    second.join(timeout=1.0)

    assert not first.is_alive()
    assert not second.is_alive()
    writes = b"".join(
        value for event, value in serial_port.events if event == "write"
    )
    assert writes == adalight.build_frame(red) + adalight.build_frame(green)
    sender.close()
