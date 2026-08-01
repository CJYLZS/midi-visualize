# MIDI 钢琴灯条可视化设计文档

创建日期：2026-07-30  
更新日期：2026-08-01  
状态：USB CDC Adalight 最小链路已验证；正式发送器待迁移验证

## 目标

Yamaha CLP-785 产生 MIDI note 事件时，Windows PC 将对应的 RGB 像素帧通过 USB 串口发送给 WLED，由 ESP32-S3 驱动琴键上方的 WS2812B 灯条。

核心目标：

- 按键到灯光的延迟稳定且足够低。
- 不依赖当前抖动明显的 WiFi 网络传输实时灯光。
- 不编写或维护自定义 ESP32 固件，继续使用 WLED。
- DAW 的 MIDI 和录音工作流不受影响。
- 所有映射、配色和力度逻辑留在 PC 侧。

## 当前架构

```text
Yamaha CLP-785
  -> USB TO HOST
  -> Windows PC
     -> DAW
     -> midi-visualize
        -> COM4 / USB CDC / Adalight
        -> ESP32-S3 / WLED
        -> GPIO16
        -> WS2812B
```

WiFi 只用于 WLED 配置、状态查询和诊断，不用于正常 MIDI 实时灯光数据。

项目仍保留 UDP/DNRGB 实现用于对照和回退，但 `config.TRANSPORT` 当前选择 `serial`。早期以 UDP/WARLS 为主的设计已经被 USB CDC Adalight 取代。

## 硬件基线

| 项目 | 当前值 |
|---|---|
| 电钢琴 | Yamaha CLP-785 |
| MCU | ESP32-S3 QFN56 rev0.2，16 MB Flash，8 MB octal PSRAM |
| 灯条 | WS2812B，5V，160 LED/m，2m，共 320 颗 |
| WLED LED count | 320 |
| 键盘预计覆盖 | 约 195 颗；其余灯珠保留扩展 |
| 数据输出 | GPIO16 -> 470 ohm -> DIN |
| 灯条电源 | 独立 5V 6A |
| 接地 | MCU 与灯条电源共地 |
| WLED 电流上限 | 5000 mA |

320 颗灯全白理论电流约为 19.2 A，因此 5000 mA 软件限流是必要安全约束。校准和诊断图案也应优先使用少量灯珠，避免在故障排查时制造额外的电源变量。

## 固件基线

| 项目 | 当前值 |
|---|---|
| WLED | 16.0.1-dev |
| 串口版本 | `WLED 2606301` |
| release | `ESP32-S3_16MB_opi` |
| 构建类型 | `ESP32-S3_16MB_opi` / `qio_opi` |
| Serial baud rate | 115200 |

固件必须使用与 16 MB Flash 和 8 MB octal PSRAM 匹配的完整构建。app-only release bin 不能直接刷到 `0x0`。本次已通过 WLED Web Installer 完整重装恢复。

## USB 连接

当前板上有两个物理 USB 接口：

| Windows 端口 | 设备 | 用途 |
|---|---|---|
| COM4 | ESP32-S3 原生 USB Serial/JTAG，`VID_303A/PID_1001` | WLED 命令、JSON 和 Adalight 实时数据 |
| COM5 | CH340，`VID_1A86/PID_7523` | 当前未发现可用的 WLED UART 数据响应 |

当前可靠启动条件是两个 USB 口同时连接。仅连接原生 USB 时出现过反复重连和 AP 不出现；该启动问题仍未定位。

打开 COM4 时，DTR 和 RTS 必须在 `open()` 之前设为非激活，避免控制线切换触发 ESP32-S3 复位。

## 串口配置状态

WLED 当前实际串口设置是 115200。最小验证脚本 `tools/dot_test.py` 固定使用该值，并已实机通过。

`src/midi_visualize/config.py` 当前仍为：

```python
SERIAL_BAUD = 921600
```

这是明确的待办而不是当前有效配置。正式 MIDI 主程序运行前，程序和 WLED 必须统一到同一个值。

115200 是当前故障排查基线，不是最终性能目标。320 颗全量 Adalight 帧有 966 字节，传统 115200 8N1 线速下也只能达到约 12 FPS。

## Adalight 协议

每帧发送 320 颗灯的完整 RGB 快照：

```text
'A' 'd' 'a'
count_hi
count_lo
count_hi XOR count_lo XOR 0x55
R G B x 320
```

对于 320 颗灯：

```text
LED_COUNT - 1 = 319 = 0x013F
header = 41 64 61 01 3F 6B
payload = 960 bytes
total = 966 bytes
```

WLED 只有收齐完整帧后才会进入 `USB Adalight/TPM2` realtime 模式并调用 `strip.show()`。

## USB CDC 发送约束

原生 USB CDC 不保证根据设置的 115200 值自动模拟传统 UART 的逐字节物理节奏。首版脚本对亮帧和黑帧都一次性调用 `write(966-byte frame)`，并在当前硬件和固件上复现以下故障：

- WLED 解析器最终停留在一个未完成帧中；现有证据不定位具体丢字节层。
- 灯不显示。
- 解析器继续等待 RGB 数据，后续 `v` 被当作像素字节而不再响应。

当前经过实机验证的发送方式：

```text
chunk size = 16 bytes
chunk delay = 3 ms
realtime refresh = 1 s
```

同一帧的全部块必须串行发送，不允许 MIDI 事件线程和 keepalive 线程交错写入。

完整排查证据见：

```text
docs/troubleshooting/2026-08-01-wled-usb-cdc-adalight.md
```

## 映射模型

当前起始参数：

```python
FIRST_NOTE = 21
KEY_COUNT = 88
LED_COUNT = 320
LEDS_PER_KEY = 2.22
LED_OFFSET = 0
REVERSED = False
```

映射公式：

```text
start = round(key_index * LEDS_PER_KEY)
end = round((key_index + 1) * LEDS_PER_KEY)
led = logical_index + LED_OFFSET
```

黑键使用对应逻辑区间的一半宽度。键盘左半边的黑键靠右，右半边的黑键靠左，以接近物理键位。

`LED_COUNT=320` 表示 WLED 和协议可寻址的完整灯条长度，不表示 88 键会占满全部灯珠。按 `2.22 LED/key` 估算，琴键区域仍约覆盖 195 颗。

校准顺序：

1. 用单灯定位确定最低音 A0 对应的 `LED_OFFSET`。
2. 确定灯条方向并设置 `REVERSED`。
3. 用 A0 和 C8 两端调整 `LEDS_PER_KEY`。
4. 从 A0 到 C8 逐键扫描，检查局部误差和黑键位置。

## PC 侧模块

| 文件 | 职责 | 当前状态 |
|---|---|---|
| `config.py` | 传输、串口、灯条、映射和配色参数 | 串口波特率仍与 WLED 不一致；CH340 端口注释仍为旧 COM3 |
| `mapping.py` | MIDI note 到 LED 和颜色的纯函数 | 离线测试通过，待实机校准 |
| `adalight.py` | Adalight 帧构造和 `SerialSender` | 帧构造正确；打开方式和整帧写入待修复 |
| `serial_probe.py` | 安全、只读的 WLED 串口探测 | COM4 @ 115200 实机通过 |
| `tools/probe_serial.py` | 早期串口诊断脚本 | 未采用安全打开顺序，不作为当前基线 |
| `transport.py` | 在 serial 与 udp 发送器之间选择 | 当前选择 serial |
| `dot_test.py` | 115200 分块节流的最小点灯验证 | 实机通过 |
| `calibrate.py` | 两端、扫键、全亮和关闭校准 | 调用正式发送器，暂不应作为串口验收基线 |
| `locate.py` | 交互式单灯定位 | 调用正式发送器，暂不应作为串口验收基线 |
| `main.py` | MIDI 端口选择和事件循环 | 尚未完成串口实机验收 |
| `warls.py` | UDP/DNRGB 回退实现 | 保留，不是当前实时主路径 |

部分模块 docstring 仍保留早期 UDP/WARLS 描述。它们属于后续同步工作，不改变当前架构决策。

## 正式 `SerialSender` 的设计要求

正式发送器迁移本轮结果时必须满足：

- 复用统一的安全串口打开逻辑。
- 在 `open()` 前设置 `dtr=False`、`rts=False`。
- 使用有界分块发送，而不是一次性写完整帧。
- 使用专门的写锁覆盖一整帧的全部块。
- 快照锁只负责帧缓冲一致性，不能代替串口写锁。
- 对 `SerialTimeoutException` 给出可观察错误，不能静默丢帧。
- 通过 monotonic 时间维护 realtime keepalive。
- 保证退出时发送完整全黑帧后再关闭串口。
- 波特率提升后重新测量安全 chunk、delay、FPS 和端到端延迟。

## 数据流

按键按下：

```text
MIDI note_on
  -> note_to_leds(note)
  -> note_to_color(note, velocity)
  -> 更新 PC 侧 320 像素帧缓冲
  -> 构造完整 Adalight 帧
  -> 在写锁内分块发送
  -> WLED 收齐全帧并 show
```

按键松开：

```text
MIDI note_off 或 note_on velocity=0
  -> 对应 LED 设为黑色
  -> 构造并发送新完整帧
```

退出：

```text
Ctrl+C / context manager exit
  -> 全帧置黑
  -> 完整发送
  -> 关闭 COM4
```

## 错误处理

| 故障 | 预期处理 |
|---|---|
| COM4 不存在或被占用 | 启动失败并明确报告端口错误 |
| WLED 版本查询无响应 | 停止发送灯光帧，提示检查端口、启动状态或未完成帧 |
| 串口写超时 | 报告丢帧，不把失败发送记为成功 |
| WLED 不进入 realtime | 检查帧完整性、波特率和 WLED build，不先改映射 |
| 中途断开 USB | 停止写入并提示重连；不得无限阻塞 MIDI 线程 |
| 程序退出 | 尽最大努力发送全黑帧，然后释放串口 |

如果未节流发送后出现“灯不亮且 `v` 不响应”，优先重启设备恢复解析器状态。补零可用于证明解析器停在 payload 中，但不作为产品级恢复协议。

## 验证状态

### 已验证

- 正确 WLED 构建可在当前 N16R8 硬件启动。
- COM4 可在 115200 下返回版本和 JSON。
- 安全打开不会让 COM4、COM5 或 AP 消失。
- WLED 配置为 320 LED、GPIO16、5000 mA。
- 320 像素 Adalight 帧格式正确。
- 16 字节分块、3 ms 间隔能进入 `USB Adalight/TPM2` realtime。
- 每隔 10 颗点亮一颗白灯，共 32 颗，保持 10 秒后关闭。
- 用户已经完成真实灯条目视验收。
- 当前完整自动化测试为 39 项，全部通过。

### 尚未验证

- 正式 `SerialSender` 的安全打开和分块写入。
- `main.py` 接 Yamaha CLP-785 的完整实时弹奏。
- 115200 下连续高密度 MIDI 事件的积压行为。
- 921600 下的可靠 chunk 参数和端到端延迟。
- `LED_OFFSET`、`REVERSED` 和 `LEDS_PER_KEY` 的实机校准。
- 延音踏板对应的灯光语义。
- 仅连接原生 USB 时的稳定启动。

## 推荐验收顺序

每一步只增加一个新变量：

1. WLED Web UI 控制灯条，确认供电、GPIO、LED count 和电流限制。
2. `serial_probe` 验证 COM4、115200、版本和 JSON。
3. `dot_test.py` 验证完整 Adalight 路径和分块节流。
4. 把安全打开、写锁和分块发送迁移到 `SerialSender`。
5. 使用 `calibrate ping` 复验正式发送器。
6. 使用 `locate` 校准 A0、方向和偏移。
7. 使用 `calibrate ends` 和 `sweep` 校准整套键盘映射。
8. `main --list` 验证 MIDI 端口。
9. 接入 CLP-785 实弹，测量连续音符和和弦延迟。
10. 在 115200 基线稳定后，再评估 921600。

当前可以执行的基线命令：

```powershell
uv run python -m midi_visualize.serial_probe COM4 --baud 115200
uv run python tools/dot_test.py
uv run pytest -q
```

## 环境

- Windows 11 25H2。
- Python 3.12。
- uv 管理环境和依赖。
- 运行依赖：`mido`、`python-rtmidi`、`pyserial`。
- 测试依赖：`pytest`。

Windows MIDI Services 的 multi-client 能力理论上允许 DAW 和转发程序同时使用 MIDI 设备，但尚未在最终弹奏流程中验收。

## 延后事项

- 拖尾或 fade 需要固定帧率渲染循环，不在当前最小实时路径中实现。
- 延音踏板是否延长灯光保持时间，待观察实际演奏体验后决定。
- UDP/DNRGB 是否继续长期保留，等 USB 串口正式链路稳定后再清理。
- 原生 USB 单接口启动异常单独排查，不与 Adalight 分块发送修复绑定。
