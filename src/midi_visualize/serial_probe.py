"""Read-only WLED serial probe that does not reset ESP32-S3 on open."""

import argparse
import json
import time

import serial

from .adalight import open_serial_without_reset


open_without_reset = open_serial_without_reset


def read_reply(serial_port, payload, timeout=3.0):
    serial_port.reset_input_buffer()
    serial_port.write(payload)
    serial_port.flush()

    reply = bytearray()
    deadline = time.monotonic() + timeout
    last_data = None
    while time.monotonic() < deadline:
        chunk = serial_port.read(4096)
        if chunk:
            reply.extend(chunk)
            last_data = time.monotonic()
        elif last_data is not None and time.monotonic() - last_data >= 0.2:
            break
    return bytes(reply)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("port", nargs="?", default="COM4")
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args()

    print(f"Opening {args.port} at {args.baud} baud without DTR/RTS reset")
    serial_port = open_without_reset(args.port, args.baud)
    try:
        version = read_reply(serial_port, b"v")
        print(f"version reply: {version!r}")
        if not version.startswith(b"WLED"):
            raise SystemExit("No valid WLED version response")

        raw_info = read_reply(serial_port, b'{"v":true}\n')
        print(f"JSON reply: {len(raw_info)} bytes")
        start = raw_info.find(b"{")
        end = raw_info.rfind(b"}")
        if start < 0 or end < start:
            raise SystemExit(f"No JSON object in response: {raw_info[:200]!r}")
        response = json.loads(raw_info[start : end + 1])
        print(json.dumps(response, indent=2, ensure_ascii=True))
    finally:
        serial_port.close()


if __name__ == "__main__":
    main()
