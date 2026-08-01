"""诊断 WLED 串口是否响应命令。

WLED 文档（kno.wled.ge/interfaces/serial/）说明串口应当响应：
    'v'          → 返回版本字符串
    'l'          → 返回 LED 数据 JSON
    {"v":true}   → 返回 state + info JSON

如果全部无响应，说明该固件构建没有编译进串口命令处理，
Adalight/tpm2 接收大概率也不可用。
"""

import sys
import time

import serial

from midi_visualize import config

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM4"
BAUD = int(sys.argv[2]) if len(sys.argv) > 2 else config.SERIAL_BAUD

ser = serial.Serial(PORT, BAUD, timeout=1, write_timeout=2)
print(f"打开 {PORT} @ {BAUD}")
time.sleep(0.5)
ser.reset_input_buffer()

for payload, name in [
    (b'{"v":true}\n', "JSON over serial"),
    (b"v", "version query"),
    (b"l", "LED data (JSON)"),
    (b"L", "LED data (tpm2)"),
]:
    ser.reset_input_buffer()
    ser.write(payload)
    time.sleep(1.0)
    resp = ser.read(400)
    flag = "OK " if resp else "-- "
    print(f"  {flag}{name:20}: {len(resp):4d} 字节  {resp[:90]}")

print("\n被动监听 5 秒，看板子有没有主动输出（启动日志等）...")
ser.reset_input_buffer()
buf = b""
deadline = time.time() + 5
while time.time() < deadline:
    buf += ser.read(256)
print(f"  收到 {len(buf)} 字节: {buf[:200] if buf else '(无)'}")

ser.close()
print("\n若以上全部无响应 → 该固件不支持串口控制，需要换固件或换方案。")
