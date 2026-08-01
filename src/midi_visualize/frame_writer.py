"""Latest-state frame scheduling for slow full-frame transports."""

import threading
import time


class LatestFrameWriter:
    """Send the newest complete frame without queuing obsolete states."""

    def __init__(self, sender, keepalive: float):
        self._sender = sender
        self._keepalive = keepalive
        self._condition = threading.Condition()
        self._pending = None
        self._latest = None
        self._stopping = False
        self._error = None
        self._failed = threading.Event()
        self._thread = threading.Thread(target=self._run, name="led-frame-writer")

    def start(self) -> None:
        self._thread.start()

    def submit(self, updates) -> None:
        with self._condition:
            if self._stopping:
                raise RuntimeError("frame writer is stopping")
            self._pending = list(updates)
            self._condition.notify()

    def _run(self) -> None:
        while True:
            with self._condition:
                while self._pending is None and not self._stopping:
                    if self._latest is None:
                        self._condition.wait()
                        continue
                    remaining = self._keepalive - (
                        time.monotonic() - self._sender.last_sent
                    )
                    if remaining <= 0:
                        break
                    self._condition.wait(remaining)
                if self._stopping:
                    return
                if self._pending is not None:
                    self._latest = self._pending
                    self._pending = None
                updates = self._latest
            try:
                self._sender.set_exclusive(updates, flush=False)
                self._sender.flush()
            except BaseException as exc:
                with self._condition:
                    self._error = exc
                    self._stopping = True
                    self._failed.set()
                    self._condition.notify_all()
                return

    def wait_for_failure(self, timeout: float | None = None) -> bool:
        return self._failed.wait(timeout)

    def raise_if_failed(self) -> None:
        with self._condition:
            error = self._error
        if error is not None:
            raise error

    def stop(self) -> None:
        with self._condition:
            self._stopping = True
            self._pending = None
            self._condition.notify_all()
        self._thread.join(timeout=2.0)
        if self._thread.is_alive():
            raise RuntimeError("frame writer did not stop")
        self.raise_if_failed()
