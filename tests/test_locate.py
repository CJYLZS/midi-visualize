from midi_visualize import locate


class RecordingWriter:
    def __init__(self):
        self.frames = []

    def submit(self, updates):
        self.frames.append(list(updates))


def test_paint_submits_one_complete_cursor_frame():
    writer = RecordingWriter()

    locate._paint(writer, led_count=20, cursor=10, marks=False)

    assert writer.frames == [
        [
            (9, locate._CURSOR_HALO),
            (11, locate._CURSOR_HALO),
            (10, locate._CURSOR),
        ]
    ]
