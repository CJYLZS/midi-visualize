"""按 config.TRANSPORT 选择传输方式。

两种发送器接口一致（set_leds / set_exclusive / clear / flush / prepare /
all_off / close / context manager），调用方无需关心用的是哪个。
"""

from . import config


def make_sender(**kwargs):
    """创建发送器。

    kwargs 里与当前传输方式无关的键会被忽略，方便命令行统一传参：
        led_count  两者都用
        ip         仅 udp
        port       仅 serial（串口名）
        baudrate   仅 serial
    """
    led_count = kwargs.get("led_count")

    if config.TRANSPORT == "serial":
        from .adalight import SerialSender

        return SerialSender(
            port=kwargs.get("serial_port"),
            baudrate=kwargs.get("baudrate"),
            led_count=led_count,
        )

    if config.TRANSPORT == "udp":
        from .warls import WledSender

        return WledSender(ip=kwargs.get("ip"), led_count=led_count)

    raise ValueError(
        f"config.TRANSPORT 无效: {config.TRANSPORT!r}（应为 'serial' 或 'udp'）"
    )


def describe() -> str:
    """返回当前传输方式的可读描述，用于日志。"""
    if config.TRANSPORT == "serial":
        return f"串口 {config.SERIAL_PORT} @ {config.SERIAL_BAUD} baud (Adalight)"
    return f"UDP {config.ESP32_IP}:{config.WLED_PORT} (DNRGB)"
