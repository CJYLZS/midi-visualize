# midi-visualize

电钢琴 MIDI 输入 → LED 灯条可视化。通过 USB 串口（Adalight 协议）推送给 WLED（ESP32-S3），灯条随琴键点亮。

## 硬件接线

- 电钢通过 USB 连接电脑，提供 MIDI 输入。
- ESP32-S3 两个 USB 口**都要接电脑**（供电并联，缺一口会反复重连）：
  - **COM4**（原生 USB，VID_303A）：WLED 串口数据，Adalight 实时数据走这里。
  - **COM5**（CH340，VID_1A86）：供电；没有接 UART0 数据线，串口命令无响应。
- 灯条数据线接 ESP32-S3 GPIO16（470Ω 串联电阻），灯条独立 5V 6A 供电，与板子共地。
- 只插 COM4 单口时板子会因供电裕量不足反复重连（按 RST 或首次插电后最明显），**必须双口同插**。长期最稳方案是从灯带 6A 电源引 5V 到板子 5V 引脚，彻底脱离 USB 供电。

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

# 3. 指定颜色模式（default / rainbow / hue，默认 default）
uv run python -m midi_visualize.main --port "Clavinova" --mode rainbow
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
| `SERIAL_PORT` / `SERIAL_BAUD` | 串口名 / 波特率（**必须与 WLED Sync 设置一致，921600**；调低会显著增加帧延迟） |
| `SERIAL_CHUNK_SIZE` / `SERIAL_CHUNK_DELAY` | 分块大小 / 块间间隔，防止原生 USB CDC 突发丢字节 |
| `LED_COUNT` | WLED 灯条总 LED 数（320） |
| `LED_OFFSET` | A0 左边缘 LED 索引 |
| `KEYBOARD_LED_COUNT` | 琴键覆盖 LED 数（含 LED_OFFSET） |
| `REVERSED` | 灯条反向（数据线在琴右侧时设 True） |
| `COLOR_MODE` | 默认颜色模式：`default` / `rainbow` / `hue`（可用 `--mode` 覆盖） |
| `COLOR_DEFAULT_HSL` | 单色模式的颜色，HSL 三元组（当前 `(216, 69, 50)`） |
| `PITCH_COLORS_HSL` | 十二音色表，12 组 HSL，索引 = `note % 12`（C 到 B） |
| `OCTAVE_HUE_STEP` / `OCTAVE_SATURATION` / `OCTAVE_LIGHTNESS` | 八度彩虹的色相步长与固定饱和度/亮度 |
| `VELOCITY_TO_BRIGHTNESS` / `MIN_BRIGHTNESS` | 力度映射亮度（1~127 → 30%~100%） |

### 波特率与延迟

- 320 颗灯 = 966 字节/帧，**波特率直接决定帧延迟下限**：921600 实测 ~80 FPS（约 12.5ms/帧），115200 只有 ~12 FPS（约 83ms/帧），肉眼可见卡顿。
- **必须把 WLED 的 `Config → Sync Interfaces → Serial → Baud rate` 也改成 921600**，否则 WLED 解析器按错误的线速消费数据，会丢帧或卡死。
- 改波特率后不要回退分块节流：`SERIAL_CHUNK_SIZE=128`、`SERIAL_CHUNK_DELAY=0.001` 是实测平衡点（128/1ms 约 80 FPS；192/0ms 会让 WLED 解析器卡死）。
- 探测工具（`serial_probe`、`wled_json`、`capture_boot`、`dot_test`）的默认波特率都读 `config.SERIAL_BAUD`，无需手动指定。

## 颜色模式

| 模式 | 说明 |
|---|---|
| `default`（默认） | 所有键同色，取 `COLOR_DEFAULT_HSL`（当前 `hsl(216, 69%, 50%)` = `#286ED7` 蓝） |
| `rainbow` | 八度彩虹：色相按八度递进，反映音域位置 |
| `hue` | 音高色相环：查 `PITCH_COLORS_HSL` 表，同名音同色，能看出和弦构成 |

三种模式都保留力度调亮度。启动时用 `--mode rainbow` 选择，或改 `config.py` 的 `COLOR_MODE` 作为默认。

## 颜色配置（HSL）

所有颜色都在 **HSL** 空间配置，与 SeeMusic 采用同一色彩空间，两边数值可以直接互抄。单位沿用 UI 惯例：**H 为 0-360 度，S / L 为 0-100 百分比**，和你在 SeeMusic 或任意取色器里看到的写法一致，不需要换算。

`mapping.hsl_to_rgb(h, s, l)` 是唯一的色彩转换入口，越界的 S / L 会被裁剪，H 自动取模 360。

### 从 SeeMusic 同步颜色

1. 在 SeeMusic 里调好某个音的颜色，记下它的 H / S / L 三个数。
2. 打开 `src/midi_visualize/config.py`，在 `PITCH_COLORS_HSL` 里找到对应音名那一行（表按 C, C#, D … B 顺序排列）。
3. 把三个数替换进去，注释里的音名不要动，方便下次对照。

```python
PITCH_COLORS_HSL = (
    (216, 69, 50),   # C   ← 改这一行就只改 C 的颜色
    ( 30, 100, 50),  # C#
    ...
)
```

改完直接重启程序即可生效，不需要改代码。单色模式同理，改 `COLOR_DEFAULT_HSL`。

表格必须保持 12 行，少一行会让 `note % 12` 越界；`uv run pytest` 里有一条测试专门拦这个错误。

### 关于亮度均衡

HSL 的 L 不是感知亮度。同样 `L=50%` 的 `hsl(60,100%,50%)`（黄）在 WS2812 上明显比 `hsl(240,100%,50%)`（蓝）刺眼，因为黄色两个通道全开而蓝色只有一个。想让十二色看起来亮度接近，需要逐音微调 L——把偏亮的黄/青调低几个点，把偏暗的蓝/紫调高几个点。这正是可配置色表的用处。

## 映射算法

每个琴键映射到以其位置为中心的 3 颗 LED 窗口（`mapping.py`），相邻键窗口允许重叠，保证每个键至少 3 颗灯。窗口中心 = `LED_OFFSET + round(键序号 × KEYBOARD_LED_COUNT / KEY_COUNT)`。

## 测试

```powershell
uv run pytest
```
