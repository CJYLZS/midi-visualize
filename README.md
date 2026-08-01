# midi-visualize

电钢琴 MIDI 输入 → LED 灯条可视化。通过 USB 串口（Adalight 协议）推送给 WLED（ESP32-S3），灯条随琴键点亮。

## 硬件接线

- 电钢通过 USB 连接电脑，提供 MIDI 输入。
- ESP32-S3 两个 USB 口都要接电脑：
  - **COM4**（原生 USB，VID_303A）：WLED 串口数据，Adalight 实时数据走这里。
  - **COM5**（CH340，VID_1A86）：供电；没有接 UART0 数据线，串口命令无响应。
- 灯条数据线接 ESP32-S3 GPIO16（470Ω 串联电阻），灯条独立 5V 6A 供电，与板子共地。

## 安装

```powershell
uv sync
```

## 快速开始

```powershell
# 1. 列出 MIDI 输入口
uv run python -m midi_visualize.main --list

# 2. 指定端口启动（支持部分匹配）
uv run python -m midi_visualize.main --port "Clavinova"
```

Ctrl+C 退出，程序会自动熄灭所有灯。

## 硬件检测

确认 COM4 与 WLED 通信正常（波特率 921600，与 WLED Sync 设置一致）：

```powershell
uv run python -m midi_visualize.serial_probe COM4 --baud 921600
```

正常输出：

```text
version reply: b'WLED 2606301\r\n'
JSON reply: ... bytes
```

### 排查

- 打开串口会自动复位板子 → 不需要处理，probe 使用 DTR/RTS 非激活的打开方式，不会触发复位。
- 如果 `v` 无响应（`version reply: b''`）：WLED 串口解析器可能停留在未完成的 Adalight 帧里。先重启 WLED（按板子 Reset 或重插 USB）；仍不行可以用零字节补齐残帧恢复（诊断用，不要作为正常流程）：

```powershell
uv run python -c "from midi_visualize.adalight import open_serial_without_reset, write_frame, read_wled_version; s=open_serial_without_reset('COM4',921600); write_frame(s,bytes(4096),128,0.001); print(read_wled_version(s)); s.close()"
```

## 琴键定位

用 `locate` 找到最低音 A0 左边缘对应的 LED 索引：

```powershell
uv run python -m midi_visualize.locate --marks
```

交互按键：`a`/`d` 移动 1 颗，`w`/`s` 移动 5 颗，`A`/`D` 移动 10 颗，数字直接跳转，`q` 退出并打印 LED_OFFSET。

把结果写进 `src/midi_visualize/config.py`：

```python
LED_OFFSET = 97              # A0 左边缘对应的 LED 索引
KEYBOARD_LED_COUNT = 196     # 琴键覆盖的 LED 数（含 LED_OFFSET，实测数）
```

## 验证定位结果

```powershell
# 只点亮 A0 和 C8（绿=A0，红=C8），检查两端对齐
uv run python -m midi_visualize.calibrate ends

# 逐键扫描，观察灯是否跟着琴键走
uv run python -m midi_visualize.calibrate sweep

# 全部点亮，检查覆盖范围
uv run python -m midi_visualize.calibrate all

# 全部熄灭
uv run python -m midi_visualize.calibrate off
```

- 绿灯没对准最低音键 → 调 `LED_OFFSET`。
- 红灯没对准最高音键 → 调 `KEYBOARD_LED_COUNT`。

## 性能测试

测量 Adalight 帧吞吐（实测 ~80 FPS @ 921600 / 128 字节分块 / 1ms 间隔）：

```powershell
uv run python tools/bench_fps.py
```

## 灯条点灯测试

点亮每隔 10 颗一颗白灯，保持 10 秒后全灭（最低风险图案，验证整条链路）：

```powershell
uv run python tools/dot_test.py
```

## 配置说明

`src/midi_visualize/config.py`：

| 参数 | 说明 |
|---|---|
| `TRANSPORT` | `"serial"` = 串口 Adalight（推荐）；`"udp"` = WiFi UDP DNRGB（该网络实测抖动大） |
| `SERIAL_PORT` / `SERIAL_BAUD` | 串口名 / 波特率（必须与 WLED Sync 设置一致，921600） |
| `SERIAL_CHUNK_SIZE` / `SERIAL_CHUNK_DELAY` | 分块大小 / 块间间隔，防止原生 USB CDC 突发丢字节 |
| `LED_COUNT` | WLED 灯条总 LED 数（320） |
| `LED_OFFSET` | A0 左边缘 LED 索引 |
| `KEYBOARD_LED_COUNT` | 琴键覆盖 LED 数（含 LED_OFFSET） |
| `REVERSED` | 灯条反向（数据线在琴右侧时设 True） |
| `COLOR_WHITE_KEY` / `COLOR_BLACK_KEY` | 键色（当前统一白色） |
| `VELOCITY_TO_BRIGHTNESS` / `MIN_BRIGHTNESS` | 力度映射亮度（1~127 → 30%~100%） |

## 映射算法

每个琴键映射到以其位置为中心的 3 颗 LED 窗口（`mapping.py`），相邻键窗口允许重叠，保证每个键至少 3 颗灯。窗口中心 = `LED_OFFSET + round(键序号 × KEYBOARD_LED_COUNT / KEY_COUNT)`。

## 测试

```powershell
uv run pytest
```
