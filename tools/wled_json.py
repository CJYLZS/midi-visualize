"""Send a JSON API command to WLED over serial, retrying across re-enumerations.

The device may be in a reconnect loop. WLED only accepts serial commands
after its firmware finished booting (it prints "Ada" once serial RX/TX are
ready), so this tool first WAITS for "Ada" (or any output), then sends the
payload, then collects the reply. On connection loss it re-opens the port
and starts over until success or the overall timeout.

Usage:
    uv run python tools/wled_json.py '{"wifi":{"on":false}}'
    uv run python tools/wled_json.py '{"ssid":"","pass":""}'
    uv run python tools/wled_json.py '{"v":true}'
"""

import argparse
import json
import time

import serial

from midi_visualize import config
from midi_visualize.adalight import open_serial_without_reset

REPLY_TIMEOUT = 4.0


def exchange(port, payload) -> bytes:
    """Wait for firmware-ready output, send payload, collect the reply."""
    deadline = time.monotonic() + REPLY_TIMEOUT
    boot_buf = bytearray()
    last_data = None
    while time.monotonic() < deadline:
        chunk = port.read(1024)
        if chunk:
            boot_buf.extend(chunk)
            last_data = time.monotonic()
            if b"Ada" in boot_buf or b"\r\n" in boot_buf:
                break
        elif last_data is not None and time.monotonic() - last_data >= 0.5:
            break
        else:
            time.sleep(0.01)
    port.reset_input_buffer()
    port.write(payload)
    port.flush()

    reply = bytearray()
    deadline = time.monotonic() + REPLY_TIMEOUT
    last_data = None
    while time.monotonic() < deadline:
        chunk = port.read(4096)
        if chunk:
            reply.extend(chunk)
            last_data = time.monotonic()
        elif last_data is not None and time.monotonic() - last_data >= 0.3:
            break
        else:
            time.sleep(0.01)
    return bytes(reply)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("payload", help="JSON command, e.g. '{\"wifi\":{\"on\":false}}'")
    parser.add_argument("port", nargs="?", default="COM4")
    parser.add_argument("--baud", type=int, default=config.SERIAL_BAUD)
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()

    payload = args.payload.encode()
    start = time.monotonic()
    attempts = 0
    while time.monotonic() - start < args.timeout:
        attempts += 1
        try:
            port = open_serial_without_reset(args.port, args.baud)
        except (serial.SerialException, OSError):
            print(f"[{time.monotonic() - start:5.1f}s] port not ready, retrying...")
            time.sleep(0.5)
            continue
        try:
            reply = exchange(port, payload)
            if reply.strip():
                print(f"[{time.monotonic() - start:5.1f}s] attempt #{attempts} reply: {reply!r}")
                try:
                    start_idx = reply.find(b"{")
                    end_idx = reply.rfind(b"}")
                    if start_idx >= 0 and end_idx > start_idx:
                        obj = json.loads(reply[start_idx : end_idx + 1])
                        print(json.dumps(obj, indent=2, ensure_ascii=True)[:4000])
                except (ValueError, TypeError):
                    pass
                return
            print(f"[{time.monotonic() - start:5.1f}s] attempt #{attempts}: no reply, retrying...")
        except (serial.SerialException, OSError) as exc:
            print(f"[{time.monotonic() - start:5.1f}s] attempt #{attempts}: connection lost ({exc!r}), retrying...")
        finally:
            try:
                port.close()
            except Exception:
                pass
        time.sleep(0.4)
    raise SystemExit("Timed out: command was never acknowledged.")


if __name__ == "__main__":
    main()
