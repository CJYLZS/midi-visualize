from midi_visualize import serial_probe


class FakeSerial:
    def __init__(self):
        self.events = []

    def __setattr__(self, name, value):
        if name != "events" and "events" in self.__dict__:
            self.events.append((name, value))
        super().__setattr__(name, value)

    def open(self):
        self.events.append(("open", None))


def test_control_lines_are_inactive_before_open():
    serial_port = FakeSerial()

    result = serial_probe.open_without_reset(
        "COM4", 115200, serial_factory=lambda: serial_port
    )

    assert result is serial_port
    open_index = serial_port.events.index(("open", None))
    assert serial_port.events.index(("dtr", False)) < open_index
    assert serial_port.events.index(("rts", False)) < open_index


def test_probe_reuses_shared_safe_serial_opener():
    assert serial_probe.open_without_reset is serial_probe.open_serial_without_reset
