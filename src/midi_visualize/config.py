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

# --- 配色 (H, S, L) ---
# 全部用 UI 惯例单位：H 为 0-360 度，S/L 为 0-100 百分比。
# 与 SeeMusic 的取值方式一致，那边调好的数值可以直接抄进来。
COLOR_MODE = "default"   # 默认颜色模式：default / rainbow / hue（可用 --mode 覆盖）

# 单色模式：所有键同一个颜色
COLOR_DEFAULT_HSL = (216, 69, 50)

# 音高色相环：12 音各一组 HSL，按 C, C#, D ... B 顺序，索引 = note % 12。
# 默认是 30° 均分、满饱和、L=50%。从 SeeMusic 抄数值时直接替换对应行。
PITCH_COLORS_HSL = (
    (  0, 100, 50),   # C
    ( 30, 100, 50),   # C#
    ( 60, 100, 50),   # D
    ( 90, 100, 50),   # D#
    (120, 100, 50),   # E
    (150, 100, 50),   # F
    (180, 100, 50),   # F#
    (210, 100, 50),   # G
    (240, 100, 50),   # G#
    (270, 100, 50),   # A
    (300, 100, 50),   # A#
    (330, 100, 50),   # B
)

# 八度彩虹：色相 = 八度序号 × OCTAVE_HUE_STEP，饱和度/亮度固定
OCTAVE_HUE_STEP = 45
OCTAVE_SATURATION = 100
OCTAVE_LIGHTNESS = 50

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
