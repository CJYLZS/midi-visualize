"""可调参数集中在这里。硬件到货后主要调这个文件。"""

# --- 传输方式 ---
# "serial" = USB 串口 Adalight（当前可靠基线约 180ms/完整帧）
# "udp"    = WiFi UDP DNRGB（实测该网络中位 46ms、尖峰 2038ms，会卡顿）
TRANSPORT = "serial"

# --- USB 串口 ---
SERIAL_PORT = "COM4"   # ESP32-S3 原生 USB (VID_303A) 的 CDC 口。
                        # 注意：双口板上的 CH340 口(COM5) 没有 WLED 串口响应，
                        # 没接 UART0 数据线，串口命令完全无响应。必须用原生 USB 口。
SERIAL_BAUD = 921600   # 必须与 WLED 的 Sync Interfaces → Baud Rate 一致。
SERIAL_CHUNK_SIZE = 128
SERIAL_CHUNK_DELAY = 0.001
SERIAL_KEEPALIVE = 1.0

# --- WiFi（TRANSPORT = "udp" 时才用到）---
ESP32_IP = "192.168.31.153"
WLED_PORT = 21324           # WLED UDP realtime 默认端口

# --- 灯条几何 ---
LED_COUNT = 320       # WLED 里声明的 LED 数（须与 WLED 设置一致）
                      # 全条 2m × 160/m。键盘只用其中一部分，
                      # 剩下的留作以后扩展。用 DNRGB 协议才能寻址 >255。
LED_OFFSET = 97       # 最低音 A0 左边缘对应的 LED 索引
KEYBOARD_LED_COUNT = 196  # 琴键覆盖的 LED 数，包含 LED_OFFSET
REVERSED = False      # 灯条方向：True 表示数据线在琴的右侧

# --- 键盘 ---
FIRST_NOTE = 21   # A0
KEY_COUNT = 88    # 到 C8 (108)

# --- 配色 (R, G, B) ---
COLOR_WHITE_KEY = (255, 255, 255)   # 所有键统一白色
COLOR_BLACK_KEY = (255, 255, 255)

# --- 力度 ---
VELOCITY_TO_BRIGHTNESS = True
MIN_BRIGHTNESS = 0.3   # 最轻触时的亮度系数，避免看不见

# --- WARLS ---
# byte1 = 距最后一包多少秒后退出 realtime 模式。
#
# 不要用 255（永不超时）：那会把 WLED 永久锁在 realtime 模式，程序异常退出后
# 只能靠 web 界面或重启才能恢复，调试期间很难缠。
# 用 2 秒：弹钢琴时事件间隔远小于 2 秒，不会中途退出；停手后自动放开控制。
WARLS_TIMEOUT = 2
