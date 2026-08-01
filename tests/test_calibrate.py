from midi_visualize import calibrate


class RecordingSender:
    def __init__(self):
        self.updates = None

    def send_exclusive(self, updates):
        self.updates = updates


def test_ends_reports_measured_keyboard_span(capsys):
    sender = RecordingSender()

    calibrate.cmd_ends(sender)

    output = capsys.readouterr().out
    assert "LED_OFFSET=97" in output
    assert "KEYBOARD_LED_COUNT=196" in output
    assert "LED 97..292" in output
