# WLED 原生 USB CDC Adalight 排查复盘

日期：2026-08-01  
状态：已完成最小点灯链路验证；正式发送器已迁移到 921600 基线

> **当前基线（后续调试一律使用，勿回退 115200）**
>
> - 波特率：**921600**（WLED Sync Interfaces → Baud rate 与 `config.SERIAL_BAUD` 一致）
> - 分块：128 字节 / 1 ms 间隔（`SERIAL_CHUNK_SIZE=128`、`SERIAL_CHUNK_DELAY=0.001`）
> - 实测 ~80 FPS（工具：`tools/bench_fps.py`）
> - **两个 USB 口必须同时连接**（COM4 原生 USB + COM5 CH340）。只插 COM4 单口时 USB 反复重连、WLED-AP 不出现——根因是单口供电裕量不足，详见文末"供电与双 USB 口"章节
> - 本文档下文带 115200 的内容均为历史排查过程，数值已过时，仅保留推导思路

## 摘要

本轮目标是在不修改 WLED 串口波特率的前提下，通过 ESP32-S3 原生 USB CDC 串口向 WLED 发送 Adalight 数据，点亮 320 颗灯条中每隔 10 颗的一颗白灯，保持 10 秒后关闭。

最终完成了端到端目视验证：

```text
Windows / pyserial
  -> COM4 原生 USB CDC
  -> WLED Adalight 解析器
  -> GPIO16
  -> WS2812B 灯条
```

首次脚本没有报错，但灯完全不亮。排查确认，不是灯条、电源、GPIO、颜色、Adalight 帧格式或 WLED 设置开关的问题，而是该脚本一次性写入 966 字节整帧的方式不可靠，执行后 WLED 串口解析器停留在未完成的 Adalight payload 中。

操作层面的根因已经由对照实验确认：

- 首版脚本对亮帧和黑帧都采用一次性写入；灯没有点亮，脚本结束后 `v` 版本查询也无响应。该结果能确认至少有一个整帧突发没有被解析器完整消费，但不能仅凭此结果确定具体是哪一帧、哪一层丢失了数据。
- 补入足够的零字节后，`v` 响应恢复，说明 WLED 此前停留在 Adalight 像素数据状态，仍在等待未收完的数据。
- 同一份帧改为每次 16 字节、块间等待 3 ms 后，后续 `v` 正常响应。
- WLED JSON 状态显示 `live=true`、`lm="USB Adalight/TPM2"`，证明帧已被完整识别。
- 用户目视确认 32 颗白灯正常点亮并在 10 秒后关闭。

底层没有加入固件级丢包计数，因此不能指出字节具体丢在 USB 驱动、CDC RX 缓冲还是 WLED 主循环的哪一层。可以确定的是：主机端 `write()` 成功不等于 WLED 解析器已完整消费数据；原生 USB CDC 不能依赖 `115200` 这个配置值自动提供传统 UART 的逐字节节流效果。

当前经过实机验证的安全发送参数是：

```text
端口：COM4
波特率设置：921600（后续统一基线，详见文首警示块）
LED 数：320
Adalight 帧长度：966 字节
分块大小：128 字节
块间等待：1 ms
亮灯续帧间隔：1 秒
实测帧率：~80 FPS（bench_fps 扫描确认）
```

> 历史基线（已废弃）：首版验证使用 115200 / 16 字节分块 / 3 ms 间隔，一帧约 180 ms、约 5.3 KB/s，只适合最小链路验证。正式发送器已统一到 921600 基线，不再回退。

## 当前硬件与固件基线

### 灯条与供电

| 项目 | 实测或当前配置 |
|---|---|
| 灯条 | WS2812B，5V，160 LED/m，2m，共 320 颗 |
| 数据输出 | ESP32-S3 GPIO16 |
| 数据线串联电阻 | 470 ohm |
| 灯条电源 | 独立 5V 6A |
| 接地 | 灯条电源与 ESP32-S3 共地 |
| WLED LED count | 320 |
| WLED segment | `0..320` |
| WLED Maximum Current | 5000 mA |

320 颗灯全白的理论电流约为 19.2 A，明显超过 6 A 电源能力。WLED 的 5000 mA 电流限制必须保留。本轮仅点亮 32 颗白灯，理论 LED 电流约 1.92 A，适合作为安全的最小验证图案。

### MCU 与 WLED

| 项目 | 值 |
|---|---|
| MCU | ESP32-S3 QFN56 rev0.2 |
| Flash | 16 MB |
| PSRAM | 8 MB octal PSRAM |
| 芯片 MAC | `28:84:85:46:cd:00` |
| WLED | 16.0.1-dev |
| 串口版本响应 | `WLED 2606301` |
| release | `ESP32-S3_16MB_opi` |
| 对应构建类型 | `ESP32-S3_16MB_opi` / `qio_opi` |
| WLED-AP BSSID | `28:84:85:46:cd:01` |

WLED-AP 的 BSSID 与芯片 MAC 连号，确认这个 AP 就是当前 ESP32-S3 创建的。

### 两个物理 USB 接口

| 端口 | USB 标识 | 当前结论 |
|---|---|---|
| COM4 | `VID_303A/PID_1001` | ESP32-S3 原生 USB Serial/JTAG；WLED 串口命令和 Adalight 实时数据使用此端口 |
| COM5 | `VID_1A86/PID_7523` | CH340；发送 `v` 没有收到 WLED 响应，不作为实时数据端口 |

当前可靠运行方式是两个物理 USB 口同时连接：

- 只连接 CH340 一侧时，WLED 可以稳定启动并出现 AP，但该 COM 口没有返回 WLED 串口数据。
- 只连接原生 USB 一侧时，曾观察到 USB 反复重连且 WLED-AP 不出现。
- 两个接口同时连接时，WLED 能稳定启动，并可通过 COM4 通信和发送 Adalight。

原生 USB 单独连接无法稳定启动的根因已实锤为供电裕量不足：两个 USB 口并联为板子供电，等效内阻减半，启动瞬间电流尖峰（flash 突发读取 + 射频校准）不再把 3.3V 拉低到 brownout 阈值以下。详见文末"供电与双 USB 口"章节。它与"完整 Adalight 帧一次性写入失败"是两个不同问题，不能混为一个根因。

## 固件恢复经验

### 失败原因

早期曾把 WLED release 中的 app-only 二进制文件直接刷到 `0x0`，随后设备进入 boot loop。

app-only 文件不是完整 Flash 镜像。ESP32-S3 启动所需的 bootloader、partition table 和 `boot_app0` 不会由这个文件补齐，把它当成完整镜像刷到 `0x0` 会破坏启动布局。

### 已验证的恢复方式

使用 WLED Web Installer 的高级安装方式，安装匹配 N16R8 硬件的完整 `ESP32-S3_16MB_opi` 镜像：<https://wled-install.github.io/>。

本次恢复使用的完整布局为：

| 地址 | 内容 |
|---|---|
| `0x0` | bootloader |
| `0x8000` | partition table |
| `0xe000` | `boot_app0` |
| `0x10000` | WLED application |

恢复后，串口版本、Flash、PSRAM 和 release 标识均与硬件匹配。

经验：在没有确认二进制类型之前，不要仅根据文件名把 release bin 刷到 `0x0`。对于 WLED，优先使用官方或匹配硬件的 Web Installer 完整安装流程。

## 串口基础链路验证

### 为什么先做只读探测

在发送实时灯光数据之前，先证明以下事项：

- COM4 是正确的数据端口。
- 当前 WLED 串口波特率是 921600（与 `config.SERIAL_BAUD` 一致；调试命令一律用 921600）。
- 打开串口不会触发 ESP32-S3 复位。
- WLED 可以同时接收文本命令并返回数据。

项目增加了：

```text
src/midi_visualize/serial_probe.py
tests/test_probe_wled_serial.py
```

安全打开串口的关键顺序是：

```python
serial_port = serial.Serial()
serial_port.port = "COM4"
serial_port.baudrate = 921600
serial_port.dtr = False
serial_port.rts = False
serial_port.open()
```

必须在 `open()` 之前设置 DTR 和 RTS。先用默认参数打开再修改控制线，仍可能在打开瞬间触发自动复位。

`tests/test_probe_wled_serial.py` 使用假的 serial factory 记录调用顺序，验证 `dtr=False` 和 `rts=False` 均发生在 `open()` 之前。

仓库中的 `tools/probe_serial.py` 是较早的诊断脚本，尚未采用这套安全打开顺序，不应作为当前串口探测基线。

运行命令（`--baud` 已默认取 `config.SERIAL_BAUD`，可省略）：

```powershell
uv run python -m midi_visualize.serial_probe COM4 --baud 921600
```

首次成功结果：

```text
v                    -> b'WLED 2606301\r\n'
{"v":true}\n       -> 1624 字节有效 JSON
```

JSON 同时确认：

```text
leds.count = 320
maxpwr = 5000
segment = 0..320
```

探测完成后 COM4、COM5 和 WLED-AP 均仍存在，没有观察到串口打开导致的重启或掉线。

## 关于 WLED Serial 页面

WLED 16.0.1-dev 的 `Config -> Sync Interfaces -> Serial` 页面只显示波特率：

```text
Baud rate: 921600
```

页面中没有单独的“启用 Adalight”或“Protocol = Adalight”选项。这不是配置缺失。

常规 WLED 构建在编译时启用 `WLED_ENABLE_ADALIGHT` 后，版本查询、JSON over Serial、Adalight 和 TPM2 共用同一个串口解析器。解析器根据输入首字节识别协议：

- `v`：版本查询
- `{`：JSON API
- `Ada`：Adalight
- `0xC9`：TPM2

因此，本轮无需在 Web UI 中寻找或打开一个不存在的 Adalight 开关。波特率匹配和完整传输正确的二进制帧即可。

## Adalight 帧核算

WLED 接收的 Adalight 帧格式：

```text
'A' 'd' 'a'
count_hi
count_lo
count_hi XOR count_lo XOR 0x55
R G B x LED_COUNT
```

计数字段保存的是 `LED_COUNT - 1`。对于 320 颗灯：

```text
LED_COUNT - 1 = 319 = 0x013F
count_hi = 0x01
count_lo = 0x3F
checksum = 0x01 XOR 0x3F XOR 0x55 = 0x6B
```

完整帧头为：

```text
41 64 61 01 3F 6B
 A  d  a
```

完整长度为：

```text
6 字节帧头 + 320 * 3 字节 RGB = 966 字节
```

`src/midi_visualize/adalight.py` 中的 `build_frame()` 与该格式一致。分块前后发送的是完全相同的 966 字节内容，所以最终修复没有改变协议和颜色数据，只改变了传输节奏。

## 首次最小点灯实验

### 目标图案

`tools/dot_test.py` 首版生成以下图案：

- LED 索引 `0, 10, 20, ..., 310` 为 `(255, 255, 255)`。
- 其余 LED 为 `(0, 0, 0)`。
- 共点亮 32 颗白灯。
- 发送一次亮灯帧，等待 10 秒，再发送一次全黑帧。

脚本固定使用 `COM4 @ 115200`（历史值，已废弃；现读取 `config.SERIAL_BAUD`，即 921600）。

### 失败现象

脚本完整运行并打印：

```text
打开 COM4 @ 115200 bps ...
发送亮灯帧：32 颗白灯（索引 0, 10, 20, ...）
等待 10 秒 ...
发送全灭帧 ...
完成。
```

没有 Python 异常，没有写超时，但灯条完全没有点亮。

同时，通过 WLED-AP Web UI 的电源按钮仍可以开关灯条。这条对照证据排除了以下方向：

- 灯条没有供电。
- GPIO16 或 DIN 完全接错。
- 灯条本身损坏。
- WLED LED 输出配置完全无效。

`pyserial.write()` 没有抛异常只能证明操作系统接受了待发送数据，不能证明 ESP32-S3 上的 WLED 已完整收到并解析这一帧。

## 根因定位过程

### 1. 排除不存在的配置开关

检查 WLED Sync setup 后确认 Serial 区域只有 `Baud rate` 一项，没有协议选择或启用复选框。结合 WLED 官方串口文档和 `wled_serial.cpp` 源码，确认 Adalight 与文本命令共享解析器，不需要额外打开。

### 2. 失败后再次发送版本查询

点灯失败后重新运行：

```powershell
uv run python -m midi_visualize.serial_probe COM4 --baud 921600
```

结果变为：

```text
version reply: b''
No valid WLED version response
```

与此同时，Windows 仍能枚举：

```text
COM4  USB VID:PID=303A:1001
COM5  USB VID:PID=1A86:7523
```

这说明 COM4 没有从系统中消失，但 WLED 不再把 `v` 当作版本命令处理。

### 3. 阅读 WLED 串口状态机

WLED 的 `handleSerial()` 使用持续状态机解析 Adalight。关键行为是：

1. 收到 `Ada` 和合法计数、校验后进入 `Data_Red`。
2. 每三个字节依次作为 R、G、B，并把剩余像素计数减一。
3. 只有最后一颗像素的 B 字节到达后，才调用：

```cpp
realtimeLock(realtimeTimeoutMs, REALTIME_MODE_ADALIGHT);
strip.show();
state = AdaState::Header_A;
```

如果帧头已经收到，但像素数据缺少任意字节，状态机不会显示半帧，也不会返回命令起始状态。后续发送的 ASCII `v` 会被当成某颗像素的 R、G 或 B 值，而不是版本查询命令。

这同时解释了两个表面上不同的症状：

- 灯完全不亮：没有收齐 320 颗像素，所以没有执行 `strip.show()`。
- `v` 不响应：解析器仍在像素数据状态。

### 4. 补零实验

为了验证解析器是否停留在未完成帧中，向 COM4 写入 4096 个零字节，再发送 `v`。

结果：

```text
zeros_written = 4096
reply = b'WLED 2606301\r\n'
```

零字节在像素数据状态会被解释为黑色。数量足够时，未完成帧的剩余像素被补齐，WLED 执行帧结束逻辑并回到 `Header_A`；多余的零在头状态被忽略。随后 `v` 恢复响应。

这条证据证明 WLED 整体并未死机，串口解析器此前只是停留在一个未完成的 Adalight 帧里。它不能单独定位字节是在 Windows、USB CDC 驱动、设备端缓冲还是 WLED 调度环节丢失。

日常恢复优先重启 WLED。补零适合作为诊断手段，不应作为正常发送流程的一部分。

### 5. 同帧分块对照实验

保持端口、115200 设置（历史值）、帧内容和 LED 数完全不变，只改变写入节奏：

```text
每块 16 字节
每块 flush
相邻块等待 3 ms
```

966 字节共分成 61 块。发送后立即查询版本：

```text
frame_bytes = 966
chunks = 61
reply = b'WLED 2606301\r\n'
```

这证明状态机在分块发送后正常回到了命令起始状态。

随后发送同一帧并查询 WLED JSON 状态：

```text
frame_bytes = 966
live = True
mode = USB Adalight/TPM2
on = False
brightness = 128
```

`live=True` 和 `mode=USB Adalight/TPM2` 是设备端对完整解析的直接确认。`state.on=False` 不表示实时帧被忽略；WLED 的 realtime 锁可以在原状态关闭时临时使用上次亮度显示实时数据，退出 realtime 后再恢复原状态。

### 6. 丢弃无效实验结果

中途有一条内联 PowerShell/Python 诊断命令因引号转义错误，仅产生 `SyntaxWarning`，没有形成有效实验。该结果没有被用于结论，随后用更窄、无复杂 JSON 引号的命令重新验证。

经验：诊断命令自身没有按预期执行时，它不是“失败证据”，只能作废并重跑。

## 为什么即使 921600 仍必须分块节流

传统 UART 的波特率会自然限制线上每个字节的发送时间。在常见的 8N1 格式下，一个字节约占 10 bit，966 字节在 921600 下的理论最短时间约为：

```text
966 * 10 / 921600 = 0.0105 秒
```

但 COM4 是 ESP32-S3 原生 USB CDC，不是 PC 通过 USB-UART 桥片连接到真实 UART RX。主机调用 `write(966 bytes)` 时，数据可以按 USB 包突发到设备。设置波特率并不保证 USB 总线按传统 UART 的逐字节物理节奏交付。

WLED 侧必须依赖有限的 USB CDC 接收缓冲和主循环中的 `handleSerial()` 及时取走数据。受控实验表明，这个固件与硬件组合的一次性 966 字节发送路径不可靠，而分块发送已经通过设备状态和目视验证。没有固件级计数器时，不进一步声称具体是哪一层发生了缓冲溢出。

921600 基线下的实测节奏（`tools/bench_fps.py` 扫描确认）：

```text
128 bytes / 1 ms   →  ~80 FPS  ← 当前基线（SERIAL_CHUNK_SIZE / SERIAL_CHUNK_DELAY）
192 bytes / 0 ms   →  解析器卡死（禁止）
64 bytes / 1 ms    →  ~43 FPS（保守备选）
```

早期 115200 最小验证节流约为 5.3 KB/s、一帧 180 ms 以上，只保证链路可靠，不代表低延迟参数。921600 + 128/1ms 是可靠与延迟的平衡点。

## 最小脚本的最终修复

`tools/dot_test.py` 增加了 `write_frame()`：

```python
def write_frame(ser, frame, chunk_size=16, chunk_delay=0.003, sleep=time.sleep):
    for offset in range(0, len(frame), chunk_size):
        ser.write(frame[offset : offset + chunk_size])
        ser.flush()
        if offset + chunk_size < len(frame):
            sleep(chunk_delay)
```

最终行为：

- 安全打开 `COM4 @ 921600`（现读取 `config.SERIAL_BAUD`），在 `open()` 前关闭 DTR/RTS。
- 使用分块节流发送亮灯帧。
- 每 1 秒重新发送当前亮灯帧，直到满 10 秒。
- 使用分块节流发送全黑帧。
- 关闭串口。

必须续帧的原因是 WLED realtime 有超时。仅发送一次，即使帧成功显示，也会在 realtime timeout 后退出，无法保证图案保持满 10 秒。1 秒间隔低于当前 2500 ms realtime timeout。

运行：

```powershell
uv run python tools/dot_test.py
```

最终用户目视确认：每隔 10 颗的一颗白灯正常点亮，保持约 10 秒后关闭。

## 自动化验证

增加 `tests/test_dot_test.py`，验证：

- 完整帧内容没有因分块而改变。
- 40 字节测试帧按 `16 + 16 + 8` 分块。
- 每块都调用 `flush()`。
- 只在相邻块之间等待 3 ms，最后一块后不额外等待。

测试按红绿循环完成：

1. 测试最初因 `tools` 不是 Python package 而收集失败；改为通过文件路径加载脚本。
2. 随后测试按预期因缺少 `write_frame` 失败。
3. 实现最小分块发送后，新增测试通过。
4. 完整测试结果为 `39 passed`。

自动化测试只能验证分块算法。真实 USB CDC 缓冲行为和灯条显示仍必须通过实机验证，本轮已经完成该目视验证。

## 已排除或不成立的假设

| 假设 | 结论与证据 |
|---|---|
| 灯条、电源或 GPIO 完全不工作 | 排除；WLED Web UI 电源按钮能正常控制灯条 |
| Python 脚本异常退出 | 排除；首版脚本完整运行，无 traceback 或串口写超时 |
| COM4 端口选错 | 排除；COM4 能返回版本和 JSON，VID/PID 对应 ESP32-S3 原生 USB |
| WLED 波特率不是 115200 | 排除；Sync 页面与 `config.SERIAL_BAUD` 一致（历史 115200 → 现 921600），版本和 JSON 均在该设置下成功 |
| 需要在 Web UI 中额外启用 Adalight | 不成立；当前 WLED 页面无该开关，源码按输入头自动识别协议 |
| Adalight 计数或校验错误 | 排除；帧格式与源码一致，同一帧分块后进入 Adalight realtime |
| WLED 完全死机 | 排除；COM 仍枚举，补零后 `v` 恢复，Web 控制此前也正常 |
| WLED 的 `on=false` 会阻止 realtime 显示 | 排除；设备进入 realtime，随后实机目视点亮成功 |
| 必须先把波特率改成 921600 才能点亮 | 排除；历史 115200 配合应用层节流已经完成端到端验证，正式基线仍统一为 921600 |

## 上游 WLED USB CDC 注意事项

WLED 上游 PR `wled/WLED#4792` 讨论了部分 ESP32-C3/S2/S3 原生 USB CDC 上的 Adalight 问题：WLED 使用传统 UART GPIO 分配状态计算 `serialCanRX` / `serialCanTX`，可能错误禁止 USB CDC 串口处理。

该问题与本轮现象有关联，但不是本次最小点灯失败的直接根因：

- 当前设备在故障前可以通过 COM4 接收 `v` 和 JSON。
- 补齐未完成帧后，同一固件的 `v` 响应立即恢复。
- 分块发送后，同一固件明确进入 `USB Adalight/TPM2` 模式。

因此，本轮没有通过更换固件或应用 PR #4792 来修复问题。该 PR 仍值得保留为“原生 USB CDC 单独启动和后续 WLED 升级兼容性”的参考。

参考：

- WLED Serial 文档：<https://kno.wled.ge/interfaces/serial/>
- WLED USB CDC Adalight PR：<https://github.com/wled/WLED/pull/4792>
- WLED 串口解析器：`wled00/wled_serial.cpp`

## 当前可复用操作流程

### 启动前检查

1. 同时连接当前板上的两个 USB 物理接口（供电要求，见文末"供电与双 USB 口"章节）。
2. 确认灯条 5V 电源开启，ESP32-S3 与灯条共地。
3. 确认没有串口监视器、Web Installer 或其他程序占用 COM4。
4. 确认 WLED Serial baud rate 与 `config.SERIAL_BAUD` 一致（**921600**）。

### 基础串口探测

```powershell
uv run python -m midi_visualize.serial_probe COM4 --baud 921600
```

期望至少看到：

```text
version reply: b'WLED 2606301\r\n'
JSON reply: ... bytes
```

### 最小点灯

```powershell
uv run python tools/dot_test.py
```

期望看到 32 颗等距白灯保持 10 秒后关闭。

### 如果点灯失败后 `v` 也无响应

1. 确认 COM4 仍在 Windows 设备列表中。
2. 优先重启 WLED，使串口状态机回到初始状态。
3. 重启后先运行只读 probe，不要立即重复一次性整帧写入。
4. 若正在做协议诊断，可以用足量零字节补齐可能的未完成帧，再查询 `v`；不要把它做成正式恢复机制。
5. 确认发送路径使用 128 字节分块和 1 ms 间隔（`SERIAL_CHUNK_SIZE` / `SERIAL_CHUNK_DELAY`）。

## 已完成（历史章节，保留供追溯）

### 正式 `SerialSender` 已迁移

`src/midi_visualize/adalight.py` 已与验证基线对齐：

- `open_serial_without_reset()` 保证 DTR/RTS 在 `open()` 前为非激活。
- `flush()` 通过 `write_frame()` 按 128 字节分块、1 ms 间隔发送，并有串口写锁覆盖整帧。
- `tools/dot_test.py` 的经验已外推到 `midi_visualize.main`、`calibrate`、`locate`。

### 波特率配置已统一

```text
WLED Sync Interfaces → Baud rate：921600
config.SERIAL_BAUD：921600
```

所有工具默认读取 `config.SERIAL_BAUD`（`serial_probe`、`wled_json`、`capture_boot`、`dot_test`），不再有硬编码旧波特率。CH340 端口注释已同步为 `COM5`。

### 性能已达标

921600 / 128 字节分块 / 1 ms 间隔实测约 80 FPS（`tools/bench_fps.py`），满足高密度 MIDI 事件需求。应用层的有界分块和写串行化仍然保留，不依赖 USB CDC 自动节流。

### 并发写入已串行化

`SerialSender` 内部 `_write_lock` 覆盖整帧所有块的串口写过程，与 `_lock`（内存快照）分离，防止 MIDI 事件发送与 realtime keepalive 的分块交错成损坏帧。

### 校准已完成

- `LED_OFFSET = 97`（`locate` 实测）。
- `KEYBOARD_LED_COUNT = 196`（含 LED_OFFSET，`calibrate ends` 验证）。
- `REVERSED = False` 实测。
- 原 `LEDS_PER_KEY` 方案已废弃，改为固定 3 LED/键窗口映射。

## 后续实现验收标准（历史基线，已完成）

将本轮经验迁移到正式发送器时，至少应满足：

- DTR/RTS 在串口 `open()` 前设为非激活。
- WLED 与程序波特率完全一致（921600）。
- 320 颗的 966 字节帧使用经过实机验证的有界分块发送。
- 同一帧的所有块不可被其他线程或其他帧交错。
- 写超时必须显式报告，不能静默吞掉后继续声称已发送。
- realtime keepalive 小于 WLED timeout，同时避免不必要地占满串口带宽。
- 发送亮灯帧后能通过 JSON 看到 `live=true` 和 `lm="USB Adalight/TPM2"`。
- 发送结束后能立即显示全黑帧。
- 实机连续弹奏时不出现解析器卡帧、灯冻结、USB 重连或帧积压。
- 自动化测试通过，并完成真实灯条目视验收。

以上均已满足：自动化测试 87 passed，实机全流程 MIDI 弹奏验证通过。

## 供电与双 USB 口（重连根因）

### 现象

- 只插原生 USB（COM4）单口时，按 RST 复位或首次插电后，Windows 反复枚举设备（实测 60 秒内 19 次），每次枚举输出 `Ada` 后 0.5~8 秒随机掉线。
- 板子未连接灯带、空载时同样复现，排除灯带干扰。
- 双口同插后不再反复重连。

### 结论

芯片级复位循环，根因是单口 USB 供电裕量不足：

- 启动瞬间电流峰值最大（flash 突发读取 + 射频校准），WiFi 配置为 AP-only 时可排除 WiFi 重试因素。
- 两个 USB 口并联为板子供电，等效内阻减半，压降不再把 3.3V 拉低到 brownout 阈值以下。
- "经常但不总是"是临界裕量的典型特征；稳定后偶尔重连是外部扰动（如灯带地弹）推过阈值。

### 排查工具

`tools/capture_boot.py`：跨枚举重连捕获启动日志（断线自动重开端口，统计枚举次数）。
`tools/wled_json.py`：跨枚举重试发送 JSON API 命令（先等 WLED 打印 `Ada` 再发送）。

### 永久方案

- 当前可靠基线：两个 USB 口同时连接。
- 长期最优：从灯带 6A 电源引 5V 到板子 5V 引脚，彻底脱离 USB 供电。

## 核心经验

1. 将“操作系统接受了串口写入”和“设备完整解析了一帧”视为两个不同事实。
2. 原生 USB CDC 是 USB 数据通道，不应直接套用 USB-UART 的物理线速直觉。
3. 二进制状态机故障后，文本命令可能被当作 payload；`v` 不响应不一定代表设备死机。
4. 设备端状态字段 `live` 和 `lm` 比“Python 没报错”更能证明协议已被识别。
5. 每次实验只改变一个变量。本轮关键对照只改变了写入节奏，帧内容完全相同。
6. 先验证最小、低风险图案，再接 MIDI、提高波特率和优化延迟。
7. 保留已解决问题与未决问题的边界，不用分块修复解释原生 USB 单独启动异常。
8. 双 USB 口是供电并联而非冗余：等效内阻减半解释了单口重连、双口稳定的差异。
