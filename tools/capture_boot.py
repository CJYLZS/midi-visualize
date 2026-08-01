"""Capture ESP32 boot log over serial to diagnose boot loops / reconnect loops.

Usage:
    uv run python tools/capture_boot.py COM4 --seconds 60

Opens the port WITHOUT DTR/RTS reset, then prints every byte read with a
relative timestamp. When the device vanishes (RST pressed / re-plug / boot
loop), the tool closes the port, retries opening it until it comes back,
and prints enumeration markers. Each successful open = one USB enumeration.

Keys to read in the output:
- "connection lost" after pressing RST is EXPECTED (device reset).
- "reconnected" marks a new enumeration. Many of them = reconnect loop.
- ROM messages (ESP-ROM: ... rst:0x...) tell the reset reason:
    Brownout detector was triggered  -> power problem
    rst:0x7 (TG0WDT_SYS_RST)         -> firmware crash loop
    invalid header / SHA-256 failed  -> wrong firmware variant
"""

import argparse
import time

import serial

from midi_visualize import config
from midi_visualize.adalight import open_serial_without_reset


def open_with_retry(port_name: str, baud: int, give_up: float) -> tuple[serial.Serial, bool]:
    """Try to open the port until it appears again or give_up seconds pass."""
    started = time.monotonic()
    while time.monotonic() - started < give_up:
        try:
            port = open_serial_without_reset(port_name, baud)
            return port, True
        except (serial.SerialException, OSError):
            time.sleep(0.3)
    return None, False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("port", nargs="?", default="COM4")
    parser.add_argument("--baud", type=int, default=config.SERIAL_BAUD)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--out", help="also append raw bytes to a file")
    args = parser.parse_args()

    start = time.monotonic()
    elapsed = lambda: time.monotonic() - start
    out_file = open(args.out, "ab") if args.out else None
    enumeration = 0

    def open_port() -> serial.Serial | None:
        nonlocal enumeration
        port, ok = open_with_retry(args.port, args.baud, give_up=5.0)
        if ok:
            enumeration += 1
            print(f"[{elapsed():6.2f}s] ---- enumeration #{enumeration} ----", flush=True)
            port.reset_input_buffer()
        return port

    print(f"Opening {args.port} at {args.baud} baud (no DTR/RTS reset)")
    port = open_port()
    if port is None:
        raise SystemExit("Cannot open port")
    print("Capturing... press RST / re-plug now. Ctrl+C to stop early.\n")

    buf = bytearray()
    _last_data = 0.0
    try:
        while elapsed() < args.seconds:
            try:
                chunk = port.read(1024)
            except (serial.SerialException, OSError) as exc:
                print(f"[{elapsed():6.2f}s] connection lost: {exc!r}", flush=True)
                port.close()
                port = open_port()
                if port is None:
                    print(f"[{elapsed():6.2f}s] port never came back; stopping.", flush=True)
                    break
                continue
            if not chunk:
                if buf and elapsed() - _last_data >= 0.3:
                    print(f"[{_last_data:6.2f}s] {bytes(buf)!r}", flush=True)
                    buf.clear()
                time.sleep(0.01)
                continue
            buf.extend(chunk)
            _last_data = elapsed()
            if out_file:
                out_file.write(chunk)
                out_file.flush()
    except KeyboardInterrupt:
        pass
    finally:
        if buf:
            print(f"[{_last_data:6.2f}s] {bytes(buf)!r}", flush=True)
        port.close()
        if out_file:
            out_file.close()
        print(f"\nDone. {enumeration} enumerations seen.", flush=True)


if __name__ == "__main__":
    main()
