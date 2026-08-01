import importlib.util
from pathlib import Path


_SCRIPT = Path(__file__).parents[1] / "tools" / "dot_test.py"
_SPEC = importlib.util.spec_from_file_location("dot_test", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
dot_test = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(dot_test)


class RecordingSerial:
    def __init__(self):
        self.writes = []
        self.flush_count = 0

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def flush(self):
        self.flush_count += 1


def test_write_frame_sends_complete_data_in_paced_chunks():
    write_frame = getattr(dot_test, "write_frame", None)
    assert write_frame is not None, "dot_test needs a paced frame writer"

    serial_port = RecordingSerial()
    delays = []
    frame = bytes(range(40))

    write_frame(serial_port, frame, chunk_size=16, chunk_delay=0.003, sleep=delays.append)

    assert serial_port.writes == [frame[:16], frame[16:32], frame[32:]]
    assert serial_port.flush_count == 3
    assert delays == [0.003, 0.003]
