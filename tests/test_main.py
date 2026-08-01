import mido
import pytest

from midi_visualize import main


class RecordingWriter:
    def __init__(self):
        self.frames = []

    def submit(self, updates):
        self.frames.append(list(updates))


class FailingRunWriter(RecordingWriter):
    def __init__(self):
        super().__init__()
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def wait_for_failure(self, _timeout):
        return True

    def raise_if_failed(self):
        raise OSError("USB disconnected")

    def stop(self):
        self.stopped = True


class CallbackInput:
    def __init__(self, callback):
        self._callback = callback

    def __enter__(self):
        self._callback(mido.Message("note_on", note=60, velocity=90))
        return self

    def __exit__(self, *_exc_info):
        return False


def test_midi_state_adds_note_on_to_complete_active_frame():
    state_class = getattr(main, "MidiLightState", None)
    assert state_class is not None, "main needs a MIDI light state model"
    state = state_class(
        led_mapper=lambda note: [note - 60],
        color_mapper=lambda _note, velocity: (velocity, 0, 0),
    )

    updates = state.handle(mido.Message("note_on", note=60, velocity=90))

    assert updates == [(0, (90, 0, 0))]


def test_midi_state_rebuilds_union_when_notes_are_released():
    state = main.MidiLightState(
        led_mapper=lambda note: [note - 60],
        color_mapper=lambda _note, velocity: (velocity, 0, 0),
    )
    state.handle(mido.Message("note_on", note=60, velocity=90))
    chord = state.handle(mido.Message("note_on", note=64, velocity=70))

    released = state.handle(mido.Message("note_off", note=60, velocity=0))
    velocity_zero = state.handle(mido.Message("note_on", note=64, velocity=0))

    assert chord == [(0, (90, 0, 0)), (4, (70, 0, 0))]
    assert released == [(4, (70, 0, 0))]
    assert velocity_zero == []


def test_midi_state_clears_all_notes_but_ignores_sustain():
    state = main.MidiLightState(
        led_mapper=lambda note: [note - 60],
        color_mapper=lambda _note, velocity: (velocity, 0, 0),
    )
    state.handle(mido.Message("note_on", note=60, velocity=90))

    sustain = state.handle(mido.Message("control_change", control=64, value=127))
    cleared = state.handle(mido.Message("control_change", control=123, value=0))

    assert sustain is None
    assert cleared == []


def test_midi_state_uses_most_recent_active_note_for_shared_led():
    state = main.MidiLightState(
        led_mapper=lambda _note: [7],
        color_mapper=lambda note, _velocity: (note, 0, 0),
    )
    state.handle(mido.Message("note_on", note=60, velocity=90))

    newest = state.handle(mido.Message("note_on", note=64, velocity=70))
    restored = state.handle(mido.Message("note_off", note=64, velocity=0))

    assert newest == [(7, (64, 0, 0))]
    assert restored == [(7, (60, 0, 0))]


def test_midi_callback_submits_only_changed_complete_frames():
    callback_factory = getattr(main, "make_midi_callback", None)
    assert callback_factory is not None, "main needs a non-blocking MIDI callback"
    state = main.MidiLightState(
        led_mapper=lambda note: [note - 60],
        color_mapper=lambda _note, velocity: (velocity, 0, 0),
    )
    writer = RecordingWriter()
    callback = callback_factory(state, writer)

    callback(mido.Message("control_change", control=64, value=127))
    callback(mido.Message("note_on", note=60, velocity=90))
    callback(mido.Message("note_on", note=64, velocity=70))

    assert writer.frames == [
        [(0, (90, 0, 0))],
        [(0, (90, 0, 0)), (4, (70, 0, 0))],
    ]


def test_run_uses_callback_writer_and_propagates_transport_failure():
    writer = FailingRunWriter()
    opened = []

    def open_input(port_name, callback):
        opened.append(port_name)
        return CallbackInput(callback)

    with pytest.raises(OSError, match="USB disconnected"):
        main.run(
            "CLP-785",
            object(),
            writer_factory=lambda _sender, keepalive: writer,
            open_input=open_input,
            poll_interval=0.01,
        )

    assert opened == ["CLP-785"]
    assert writer.started
    assert writer.stopped
    assert writer.frames == [
        [
            (led, main.mapping.note_to_color(60, 90))
            for led in main.mapping.note_to_leds(60)
        ]
    ]
