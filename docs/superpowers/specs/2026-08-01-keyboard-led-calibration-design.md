# Keyboard LED Calibration Design

## Goal

Represent the measured keyboard position using two directly measurable settings:

```python
LED_OFFSET = 97
KEYBOARD_LED_COUNT = 196
```

The count includes the starting LED, so the keyboard occupies LED indices 97
through 292 inclusive. `LED_COUNT = 320` continues to describe the complete
physical strip.

## Mapping

Remove the manually calibrated `LEDS_PER_KEY` setting. The mapping derives its
scale as `KEYBOARD_LED_COUNT / KEY_COUNT`, currently `196 / 88`, and retains the
existing rounding and narrower black-key behavior. Forward mapping must keep
every keyboard LED within the inclusive calibrated range. Reversed mapping must
mirror that range across the full strip using the existing `REVERSED` behavior.

## Calibration Output

`calibrate ends` reports `LED_OFFSET`, `KEYBOARD_LED_COUNT`, and the resulting
inclusive physical range. Its guidance tells the user to adjust the offset for
the A0 edge and the keyboard LED count for the C8 edge.

## Verification

Automated tests cover the configured values, derived mapping boundaries, all 88
keys staying inside the calibrated span, and reversed mapping. Hardware
verification uses `calibrate ends`: A0 must align with the left edge at LED 97,
and C8 must align with the right edge of the 196-LED span.
