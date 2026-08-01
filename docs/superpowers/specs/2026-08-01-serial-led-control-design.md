# 串口 LED 控制完成设计

创建日期：2026-08-01
状态：设计已批准，待实施

## 背景

项目已经通过 `tools/dot_test.py` 完成 ESP32-S3 原生 USB CDC 到 WLED
Adalight 的最小实机点灯验证。当前硬件、固件和可靠传输基线为：

| 项目 | 当前值 |
|---|---|
| 串口 | `COM4`，ESP32-S3 原生 USB CDC |
| WLED 串口设置 | 115200 |
| LED 数 | 320 |
| Adalight 帧长度 | 966 字节 |
| 分块大小 | 16 字节 |
| 块间等待 | 3 ms |
| realtime 续帧间隔 | 1 秒 |

一次性写入完整 966 字节帧在当前硬件和固件组合上不可靠。WLED 可能停留在
未完成的 Adalight payload 中，表现为灯不亮且后续 `v` 命令无响应。16 字节
分块、块间等待 3 ms 已经通过 WLED 状态和真实灯条目视验证。

完整证据链见：

```text
docs/troubleshooting/2026-08-01-wled-usb-cdc-adalight.md
```

当前正式 `SerialSender` 尚未迁移这些结论：它使用配置中的 921600，一次性写入
完整帧，打开串口前未可靠关闭 DTR/RTS，吞掉写超时，并且没有覆盖整帧的写锁。
因此 `main`、`calibrate` 和 `locate` 目前不能作为安全的串口 LED 控制入口。

## 本轮目标

将已经实机验证的可靠发送方式迁移到正式程序，并完成以下端到端路径：

```text
Yamaha CLP-785 MIDI
  -> Windows PC / midi-visualize
  -> COM4 / USB CDC / Adalight
  -> ESP32-S3 / WLED
  -> GPIO16 / WS2812B
```

本轮完成标准包括：

- `SerialSender` 安全打开、验证 WLED、可靠发送完整帧并显式报告错误。
- `calibrate` 和 `locate` 通过正式发送器控制真实灯条。
- `main` 能把 CLP-785 的单音、和弦和松键状态发送到灯条。
- 快速 MIDI 输入不形成无界帧队列，而是收敛到最新灯光状态。
- 健康退出时发送完整全黑帧并关闭串口。

## 非目标

本轮不包含：

- 把 WLED 和程序切换到 921600。
- 优化 16 字节和 3 ms 这组已验证参数。
- 实现 fade、拖尾或固定高帧率动画。
- 实现 CC64 延音踏板的灯光语义。
- 校准 `LED_OFFSET`、`REVERSED` 或 `LEDS_PER_KEY` 的最终数值。
- 排查仅连接原生 USB 时反复重连和 WLED-AP 不出现的问题。
- 删除 UDP/DNRGB 回退实现。

115200 下每帧约需 180 ms。本轮接受该性能上限，优先保证帧边界可靠、错误
可见和 MIDI 输入不积压。921600 作为后续独立的性能优化阶段。

## 方案选择

### 采用：同步串口核心加应用层最新状态调度

`SerialSender` 提供同步、可验证的完整帧发送。`calibrate` 直接使用该同步接口；
`main` 和需要 keepalive 的 `locate` 在应用层使用唯一 writer，把快速更新合并为
最新状态。

该方案保持串口协议和调度策略的职责分离：

- 串口层保证一帧要么完整发送，要么明确失败。
- MIDI 层决定在带宽不足时跳过过时的中间状态。
- 不需要让所有发送器调用都承担异步关闭、异常传播和队列排空语义。

### 未采用：`SerialSender` 内置通用后台线程

该方案能让所有调用方自动合并帧，但会让 `calibrate` 的“发送完成”语义、后台
错误传播、关闭排空和 UDP 接口兼容变复杂。本轮没有必要把异步行为扩散到所有
调用方。

### 未采用：逐 MIDI 事件同步发送

这是改动最少的方案，但每个事件会阻塞约 180 ms。快速和弦和连续弹奏会形成
持续增长的延迟，不符合“最新状态优先”的选择。

## 组件职责

### `src/midi_visualize/adalight.py`

负责：

- 构造 Adalight 完整帧。
- 以 DTR/RTS 非激活状态安全打开串口。
- 在启动时通过 `v` 验证连接的是可响应的 WLED。
- 维护 320 像素帧缓冲。
- 在专用写锁内完成整帧分块传输。
- 检测短写、写超时和 USB 断开。
- 跟踪最近一次完整成功发送的 monotonic 时间。
- 健康关闭时支持同步发送全黑帧。

不负责：

- 创建 MIDI 事件队列。
- 决定是否丢弃过时画面。
- CC64 或其他演奏语义。

### `src/midi_visualize/main.py`

负责：

- 接收 MIDI 消息。
- 维护活动音符及其颜色状态。
- 根据全部活动音符重建最新逻辑画面。
- 通知唯一 writer 有新画面可发送。
- 合并 writer 忙碌期间到达的更新。
- 空闲时每 1 秒续发当前帧。
- 有序停止 MIDI 输入、writer 和串口。

MIDI 输入使用 `mido.open_input(..., callback=...)`。回调只更新活动音符状态并提交
最新画面，不执行串口 I/O。控制线程等待退出信号或 writer 错误，因此即使当前
没有新的 MIDI 消息，后台传输错误也能及时终止程序，而不会卡在阻塞式端口迭代中。
回调使用一个状态锁保护活动音符、按下序号和画面重建，使并发到达的 MIDI 消息
按照取得该锁的顺序形成一致快照。

### `src/midi_visualize/frame_writer.py`

提供 transport-neutral 的 `LatestFrameWriter`，供 `main` 和 `locate` 复用。它只
依赖发送器已有的 `set_exclusive(..., flush=False)`、`flush()` 和 `last_sent` 接口。

最小接口为：

```python
writer.start()
writer.submit(updates)
writer.raise_if_failed()
writer.stop()
```

`submit()` 原子替换待发送的完整逻辑画面并递增 generation，不追加逐事件队列。
后台非 daemon 线程保存最后成功发送的 generation；一帧发送期间出现的新
generation 会使它在当前帧完成后再发送一次当时最新的画面。

writer 保存后台异常并设置错误事件。`raise_if_failed()` 和 `stop()` 在控制线程中
重新抛出该异常；可选错误回调用于让正在等待终端输入的 `locate` 立即打印故障，
但回调本身不执行恢复或再次写串口。

`stop()` 原子地拒绝后续 `submit()`，丢弃尚未开始发送的 generation，并等待当前
完整帧结束后回收线程。它不发送全黑帧；健康退出的控制线程在 writer 完全停止后
同步发送全黑帧。这样退出不会先重放一个已经过时的待发送画面。

### `src/midi_visualize/locate.py`

负责交互式光标和标记图案。它使用与 `main` 相同的“唯一 writer + 最新状态”
原则处理前台光标更新和 keepalive，不再由两个线程直接调用 `flush()`。

### `src/midi_visualize/calibrate.py`

每个校准动作同步发送一个完整画面。它不需要后台队列，但必须使用正式
`SerialSender` 的安全打开、探测和分块写入。

### `src/midi_visualize/config.py`

集中保存实机基线：

```python
SERIAL_PORT = "COM4"
SERIAL_BAUD = 115200
SERIAL_CHUNK_SIZE = 16
SERIAL_CHUNK_DELAY = 0.003
SERIAL_KEEPALIVE = 1.0
```

CH340 注释同步为当前实际 `COM5`。关于 USB CDC 延迟的说明不得再宣称未经验证的
“1~2 ms”；应明确当前可靠帧时间约为 180 ms。

### 诊断入口

`serial_probe` 和 `dot_test` 继续保留。安全打开和节流写入应复用生产代码中的
共享函数，避免最小验证脚本与正式发送器再次漂移。

## 安全打开与启动验证

串口必须按以下顺序建立：

1. 创建尚未打开的 `serial.Serial()`。
2. 设置 `port`、`baudrate`、读超时和写超时。
3. 设置 `dtr=False`、`rts=False`。
4. 调用 `open()`。
5. 清理陈旧的输入数据。
6. 发送 `v` 并等待有限时间。
7. 仅当响应以 `WLED` 开头时返回可用连接。

探测失败时必须关闭串口并抛出包含端口和修复建议的明确异常。程序不得在没有
有效 WLED 响应时继续发送 Adalight 数据。建议应包含：检查两个 USB 口、COM4
占用、WLED 启动状态，以及在解析器可能卡在 payload 时重启 WLED。

启动探测与 Adalight 数据使用同一个串口对象，避免“探测通过后关闭，再次打开时
控制线状态不同”的竞态。

## 完整帧发送

### 锁模型

使用两个职责不同的锁：

- 帧缓冲锁保护 `_frame` 的更新和复制。
- 整帧写锁保护从快照到最后一块写完的整个发送过程。

`flush()` 的顺序为：

1. 获取整帧写锁。
2. 在帧缓冲锁内复制当前帧。
3. 构造完整 Adalight 帧。
4. 分块发送全部字节。
5. 仅在完整成功后更新 `last_sent`。
6. 释放整帧写锁。

快照必须在取得写锁后创建。如果在等待写锁前先创建快照，旧调用可能在新画面
发送后取得写锁，并用较旧快照覆盖它。

### 分块规则

对于默认 320 LED：

```text
完整帧：966 字节
块大小：16 字节
块数量：61
最后一块：6 字节
```

每块处理规则：

1. 调用 `write(chunk)`。
2. 要求返回值等于 `len(chunk)`；否则视为短写。
3. 调用 `flush()`。
4. 如果不是最后一块，等待 3 ms。
5. 最后一块后不额外等待。

整个帧的块不可被另一个 `flush()`、keepalive 或关闭帧交错。

## 失败语义

下列情况均视为帧发送失败：

- `SerialTimeoutException`。
- `SerialException` 或操作系统断开错误。
- `write()` 返回值小于当前块长度。
- 串口已经关闭或发送器此前已经失败。

帧中途失败后，WLED 可能停留在未完成 payload 中，无法安全假设下一帧的 `Ada`
头会被当成新帧头。因此发送器进入不可恢复的 failed 状态：

- 不更新 `last_sent`。
- 后续发送立即失败，不再向端口写入。
- writer 停止接受工作并把错误传回控制线程。
- 程序明确提示重启 WLED 后重试。
- 不尝试在同一连接上发送全黑帧或自动补零。

补零只保留为诊断手段，不进入正式恢复流程。

## MIDI 最新状态调度

### 状态模型

MIDI 接收路径维护活动音符及其颜色，而不是保存一列待发送帧：

- `note_on` 且 velocity > 0：加入或更新该音符。
- `note_off`：移除该音符。
- `note_on` 且 velocity = 0：等同 `note_off`。
- CC120 或 CC123：清空所有活动音符。
- CC64：本轮明确忽略。

每次状态变化后，根据全部活动音符重建 320 像素逻辑画面。这样重叠按键或相邻
映射不会因一个音符松开而错误熄灭仍由另一个活动音符占用的 LED。

活动音符保存颜色和单调递增的按下序号。当多个活动音符映射到同一颗 LED 时，
最近按下的音符决定该 LED 的颜色；释放它后，仍活动的较早音符颜色重新显现。
重复收到同一音符的非零 `note_on` 会更新其颜色和按下序号。

### 唯一 writer

MIDI 接收路径不得直接执行约 180 ms 的串口写入。它只更新最新画面并调用
`writer.submit(updates)`。唯一 writer 执行：

```text
收到 dirty
  -> 获取当下最新画面
  -> 同步发送一个完整帧
  -> 如果发送期间再次 dirty，读取最新画面并再发一帧
  -> 不重放中间的过时画面
```

如果 20 个 MIDI 事件在一帧发送期间到达，下一次只发送第 20 个事件之后的最新
完整状态。极短中间状态可能不显示，这是预期的拥塞策略；最终灯光状态必须与
当前活动音符一致。

writer 在第一次 `submit()` 之前保持空闲，不为了初始全黑状态进入 WLED realtime。

### Keepalive

当没有状态变化且距上次成功发送达到 1 秒时，writer 续发当前最新画面，保持
WLED realtime 模式。keepalive 与状态更新使用同一个 writer，不创建第二条串口
写路径。

`last_sent` 只表示完整成功发送的时刻。失败发送不能推迟下一次错误处理或伪装成
有效 keepalive。

## 生命周期

### 正常启动

```text
打开并验证 COM4
  -> 创建全黑逻辑状态
  -> 启动唯一 writer
  -> 使用 callback 打开 MIDI 输入
  -> 接收事件
```

### 健康退出

```text
停止接收新的 MIDI 事件
  -> 请求 writer 停止
  -> 等待正在发送的完整帧结束
  -> 同步发送完整全黑帧
  -> 关闭 COM4
```

`Ctrl+C` 由控制线程处理，不直接中断 writer 的块间发送。这样不会因为 Python
异步中断恰好发生在帧中间而把 WLED 留在 payload 状态。

`SerialSender.close()` 只释放端口，不隐式改变灯光。`main` 的健康退出流程显式
发送全黑帧；`calibrate` 和 `locate` 可以按各自命令语义保留最后画面，随后由 WLED
realtime timeout 恢复原状态。发送器 context manager 仍用于需要“退出即全灭”的
调用路径。

### 故障退出

如果 writer 遇到帧发送失败：

```text
记录原始异常
  -> 标记发送器 failed
  -> 停止 MIDI 输入和 writer
  -> 不再发送全黑帧
  -> 关闭串口
  -> 向用户报告需要重启 WLED
```

程序不应无限阻塞等待线程；正常情况下 writer 至多在完成当前约 180 ms 帧后退出。
如果线程未在有界时间内结束，应报告关闭失败而不是静默退出。

## 校准和定位行为

`calibrate` 和 `locate` 的帮助文本、docstring 和故障提示必须从早期 UDP/WARLS
描述更新为当前 transport-neutral 或串口描述。

校准命令行为：

- `ping`：LED 0 为红色，其余全黑。
- `ends`：A0 为绿色、C8 为红色，其余全黑。
- `sweep`：逐键显示并熄灭，使用同步完整帧。
- `all`：显示当前 88 键映射覆盖。
- `off`：发送全黑帧。

`locate` 前台移动光标时更新最新画面；后台 keepalive 只能唤醒唯一 writer，不能
直接调用 `sender.flush()`。`--at` 模式保持约 3 秒后关闭连接；是否熄灭由命令
现有语义决定，不通过异常退出隐式改变。

## 自动化测试

### Adalight 帧

- 320 像素帧长度为 966。
- 帧头为 `41 64 61 01 3F 6B`。
- RGB 顺序、掩码和完整 payload 正确。

### 安全打开和探测

- DTR/RTS 均在 `open()` 前设置为 `False`。
- 端口属性和超时设置正确。
- `WLED ...` 响应允许启动。
- 空响应或非 WLED 响应关闭端口并失败。
- 探测异常也关闭端口。

### 分块写入

- 966 字节按 60 个 16 字节块和一个 6 字节块发送。
- 拼接全部写入等于原始帧，无遗漏和重复。
- 每块调用 `flush()`。
- 只在相邻块之间等待 3 ms。
- 短写、超时和断开显式传播。
- 失败后拒绝后续发送。
- 失败发送不更新 `last_sent`。

### 并发和最新状态

- 两个并发 `flush()` 的块不交错。
- 等待写锁的调用在取得锁后复制最新帧。
- 快速状态更新不会创建逐事件帧积压。
- writer 完成当前帧后只发送最新状态。
- 空闲 1 秒触发 keepalive。
- 有状态更新时不额外发送重复 keepalive。
- 停止时等待当前完整帧结束。
- 停止时拒绝新提交并丢弃尚未开始发送的 generation。
- writer 异常能到达控制线程。
- 第一次提交前不发送 keepalive。

### MIDI 状态

- 单个 `note_on` 点亮映射 LED。
- 多个活动音符形成联合画面。
- `note_off` 只移除对应音符。
- velocity 0 的 `note_on` 等同 `note_off`。
- CC120 和 CC123 清空画面。
- CC64 不改变画面。
- 两个音符共享 LED 时，释放其中一个不会熄灭另一个仍占用的 LED。
- 两个音符共享 LED 时，最近按下且仍活动的音符决定颜色。

### 回归

现有 mapping、UDP/DNRGB、serial probe 和最小分块测试继续通过。测试不得访问真实
COM4；串口对象、时钟、sleep 和 writer 同步点通过依赖注入或 fake 控制。

## 实机验收

按顺序执行，每一步只增加一个变量。

### 1. 基础探测

```powershell
uv run python -m midi_visualize.serial_probe COM4 --baud 115200
```

必须收到 `WLED 2606301` 和有效 JSON。

### 2. 正式发送器最小点灯

```powershell
uv run python -m midi_visualize.calibrate ping
```

必须看到 LED 0 红色、其余全黑。命令结束后再次运行 `serial_probe`，必须仍能收到
版本响应，证明正式发送器没有把解析器留在未完成帧中。

### 3. 定位与 keepalive

```powershell
uv run python -m midi_visualize.locate --at 10
uv run python -m midi_visualize.locate --marks
```

`--at` 图案保持约 3 秒；交互移动时光标最终位置必须追上输入，不持续回跳到旧帧，
空闲时不得因 realtime timeout 消失。

### 4. 映射工具

```powershell
uv run python -m midi_visualize.calibrate ends
uv run python -m midi_visualize.calibrate sweep
```

本轮只验证控制链路和扫描连续性，不要求立即确定最终几何参数。

### 5. Yamaha MIDI 闭环

```powershell
uv run python -m midi_visualize.main --list
uv run python -m midi_visualize.main --port "CLP-785"
```

实机检查：

- 单音按下后对应区域点亮，松开后熄灭。
- 和弦显示所有当前按下的音。
- 快速弹奏时允许跳过短暂中间画面，但停止输入后最终画面必须追上当前按键状态。
- velocity 0 的 note-on 正常熄灭。
- CC123 清空全部灯。
- CC64 不改变当前灯光语义。
- `Ctrl+C` 在当前完整帧结束后发送全黑帧并退出。

### 6. 稳定性

连续弹奏和运行校准期间不得出现：

- WLED 解析器卡帧。
- 灯光长期冻结在过时状态。
- 帧队列持续积压。
- USB 反复重连。
- 健康退出后灯仍保持点亮。
- 重新运行 `serial_probe` 时 `v` 无响应。

### 7. 自动化验证

```powershell
uv run pytest -q
```

全部测试必须通过。自动化测试不能替代真实 USB CDC 和灯条目视验收。

## 完成边界

满足自动化测试和上述实机验收后，串口 LED 控制部分视为在 115200 可靠基线上
完成。后续工作按独立阶段处理：

1. 校准 `LED_OFFSET`、`REVERSED` 和 `LEDS_PER_KEY`。
2. 把 WLED 与程序统一切换到 921600。
3. 重新实测安全 chunk、delay、持续 FPS 和端到端延迟。
4. 根据实际演奏体验决定是否实现 CC64、fade 和拖尾。
