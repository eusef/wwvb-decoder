"""Plain text output mode for --plain flag."""

import datetime
import sys


class PlainDisplay:
    """Simple timestamped log output to stdout.

    Matches the interface of TUIDisplay (start/stop/update) so the
    state machine doesn't need to know which display is active.
    """

    def __init__(self, debug: bool = False):
        self.debug = debug
        self._started = False

    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        self._started = False

    def log(self, category: str, message: str) -> None:
        """Print a timestamped log line.

        Categories: CONNECT, CONFIG, STREAM, SYNC, SIGNAL, DECODE, STATS,
                    ERROR, WARN, DEBUG
        """
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] {category:8s} {message}", flush=True)

    def log_debug(self, message: str) -> None:
        """Print debug output (only when --debug is set)."""
        if self.debug:
            self.log("DEBUG", message)

    def update(self, state) -> None:
        """No-op for plain mode. Events are logged as they happen."""
        pass
