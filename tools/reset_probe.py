"""通过 DTR/RTS 复位 ESP32，捕获启动日志。

ESP32 的 ROM bootloader 固定用 115200 输出启动信息。
如果复位后收不到任何数据，说明 CH340 的 RX 没有连到 ESP32 的 UART0 TX
（有些开发板的 CH340 仅用于烧写，或需要跳线/拨码开关切换）。
"""

import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM3"

ser = serial.Serial(PORT, 115200, timeout=0.3)
print(f"打开 {PORT} @ 115200（ESP32 ROM bootloader 固定波特率）")

# esptool 的经典复位序列：EN=DTR, IO0=RTS
print("发送复位序列...")
ser.setDTR(False)
ser.setRTS(True)
time.sleep(0.1)
ser.setDTR(True)
ser.setRTS(False)
time.sleep(0.05)
ser.setDTR(False)

ser.reset_input_buffer()
print("监听 5 秒，捕获启动日志...\n")

buf = b""
deadline = time.time() + 5
while time.time() < deadline:
    chunk = ser.read(512)
    if chunk:
        buf += chunk

ser.close()

if buf:
    print(f"收到 {len(buf)} 字节：")
    print("-" * 60)
    try:
        print(buf.decode("utf-8", errors="replace")[:1500])
    except Exception:
        print(buf[:500])
    print("-" * 60)
    print("\n结论：CH340 ↔ ESP32 UART 通信正常。")
else:
    print("收到 0 字节。")
    print("\n结论：CH340 的 RX 收不到 ESP32 的输出。可能原因：")
    print("  1. 板子有两个 USB 口，WLED 的串口在原生 USB 那个口上")
    print("  2. 该 CH340 仅接了烧写所需的信号，未接 UART0 TX")
    print("  3. 板子上有跳线/拨码开关需要切换")
