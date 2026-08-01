"""在真实设备上测量 Adalight 帧吞吐与解析器健康，用于挑选分块参数。"""

import time

from midi_visualize.adalight import (
    SerialSender,
    open_serial_without_reset,
    read_wled_version,
)

PORT = "COM4"
FRAMES = 30


def find_working_baud(candidates):
    for baud in candidates:
        try:
            ser = open_serial_without_reset(PORT, baud)
            try:
                reply = read_wled_version(ser, timeout=1.5)
            finally:
                ser.close()
            if reply.startswith(b"WLED"):
                print(f"WLED 在 {baud} baud 响应: {reply!r}")
                return baud
            print(f"{baud} baud 无 WLED 响应: {reply!r}")
        except Exception as exc:
            print(f"{baud} baud 打开失败: {exc}")
    return None


def bench(baud, chunk_size, chunk_delay):
    sender = SerialSender(
        port=PORT, baudrate=baud, chunk_size=chunk_size, chunk_delay=chunk_delay
    )
    try:
        start = time.perf_counter()
        for i in range(FRAMES):
            sender.set_exclusive([(97 + i % 196, (255, 0, 0))], flush=False)
            sender.flush()
        elapsed = time.perf_counter() - start
        reply = read_wled_version(sender._ser, timeout=1.5)
        ok = reply.startswith(b"WLED")
        print(
            f"chunk={chunk_size:>3} delay={chunk_delay:<6} "
            f"-> {FRAMES/elapsed:6.2f} FPS  parser_ok={ok}"
        )
        return ok
    finally:
        sender.close()


def main() -> None:
    baud = find_working_baud([921600, 912600])
    if baud is None:
        print("两个波特率都无法与 WLED 通信")
        return
    for chunk_size, chunk_delay in (
        (16, 0.003),
        (32, 0.003),
        (64, 0.003),
        (64, 0.001),
        (128, 0.001),
        (192, 0.0),
    ):
        try:
            if not bench(baud, chunk_size, chunk_delay):
                print("  -> 解析器未恢复，停止后续测试")
                break
        except Exception as exc:
            print(f"chunk={chunk_size:>3} delay={chunk_delay:<6} -> 错误 {exc}")


if __name__ == "__main__":
    main()
