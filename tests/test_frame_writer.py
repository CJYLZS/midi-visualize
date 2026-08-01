import importlib
import importlib.util
import threading
import time

import pytest


class RecordingSender:
    def __init__(self):
        self.last_sent = 0.0
        self.pending = []
        self.frames = []
        self.sent = threading.Event()
        self._condition = threading.Condition()

    def set_exclusive(self, updates, flush=True):
        assert flush is False
        self.pending = list(updates)

    def flush(self):
        with self._condition:
            self.frames.append(list(self.pending))
            self.last_sent = time.monotonic()
            self._condition.notify_all()
        self.sent.set()

    def wait_for_frames(self, count, timeout=1.0):
        deadline = time.monotonic() + timeout
        with self._condition:
            while len(self.frames) < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
        return True


class FailingSender(RecordingSender):
    def __init__(self):
        super().__init__()
        self.attempted = threading.Event()

    def flush(self):
        self.attempted.set()
        raise OSError("USB disconnected")


class BlockingSender(RecordingSender):
    def __init__(self):
        super().__init__()
        self.first_started = threading.Event()
        self.release_first = threading.Event()

    def flush(self):
        if not self.frames:
            self.first_started.set()
            assert self.release_first.wait(1.0)
        super().flush()


def test_writer_sends_submitted_complete_frame():
    spec = importlib.util.find_spec("midi_visualize.frame_writer")
    assert spec is not None, "latest-frame writer module is missing"
    module = importlib.import_module("midi_visualize.frame_writer")
    writer_class = getattr(module, "LatestFrameWriter", None)
    assert writer_class is not None, "LatestFrameWriter is missing"

    sender = RecordingSender()
    writer = writer_class(sender, keepalive=60.0)
    writer.start()
    writer.submit([(3, (1, 2, 3))])

    assert sender.sent.wait(1.0)
    writer.stop()
    assert sender.frames == [[(3, (1, 2, 3))]]


def test_writer_starts_keepalive_only_after_first_submission():
    from midi_visualize.frame_writer import LatestFrameWriter

    sender = RecordingSender()
    writer = LatestFrameWriter(sender, keepalive=0.03)
    writer.start()
    frame = [(3, (1, 2, 3))]
    try:
        time.sleep(0.06)
        assert sender.frames == []
        writer.submit(frame)
        assert sender.wait_for_frames(2)
    finally:
        writer.stop()
    assert sender.frames[:2] == [frame, frame]


def test_writer_propagates_background_send_failure():
    from midi_visualize.frame_writer import LatestFrameWriter

    sender = FailingSender()
    writer = LatestFrameWriter(sender, keepalive=60.0)
    writer.start()
    writer.submit([(3, (1, 2, 3))])
    assert sender.attempted.wait(1.0)
    assert writer.wait_for_failure(1.0)

    with pytest.raises(OSError, match="USB disconnected"):
        writer.raise_if_failed()

    with pytest.raises(OSError, match="USB disconnected"):
        writer.stop()


def test_writer_coalesces_updates_arriving_during_send():
    from midi_visualize.frame_writer import LatestFrameWriter

    sender = BlockingSender()
    writer = LatestFrameWriter(sender, keepalive=60.0)
    first = [(1, (1, 0, 0))]
    obsolete = [(2, (2, 0, 0))]
    latest = [(3, (3, 0, 0))]
    writer.start()
    try:
        writer.submit(first)
        assert sender.first_started.wait(1.0)
        writer.submit(obsolete)
        writer.submit(latest)
        sender.release_first.set()
        assert sender.wait_for_frames(2)
    finally:
        sender.release_first.set()
        writer.stop()

    assert sender.frames == [first, latest]
