"""Terminal output for the sync: a progress bar pinned to the bottom line,
and an error log that captures everything printed that isn't already
recorded in sync_audit.log (status lines, warnings, tracebacks)."""

import atexit
import logging
import shutil
import sys
import threading
import time
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler

error_logger = logging.getLogger("errors")
error_logger.setLevel(logging.INFO)
error_logger.propagate = False

_CLEAR_LINE = "\r\x1b[2K"


class _Bar:
    def __init__(self):
        self.label = None
        self.total = None
        self.done = 0
        self.started = 0.0
        self.last_draw = 0.0

    @property
    def active(self):
        return self.label is not None

    def render(self, width):
        elapsed = time.monotonic() - self.started
        stats = f"{self.done:,}"
        if self.total:
            pct = min(self.done / self.total, 1.0)
            stats = f"{pct:4.0%}  {self.done:,}/{self.total:,}"
            if 0 < self.done < self.total:
                eta = elapsed / self.done * (self.total - self.done)
                stats += f"  ETA {_fmt_time(eta)}"
        stats += f"  {_fmt_time(elapsed)}"

        head = f"{self.label} "
        bar_width = width - len(head) - len(stats) - 4
        if self.total and bar_width >= 10:
            filled = int(bar_width * min(self.done / self.total, 1.0))
            bar = "█" * filled + "░" * (bar_width - filled)
            line = f"{head}[{bar}] {stats}"
        else:
            line = f"{head}{stats}"
        return line[: width - 1]


def _fmt_time(seconds):
    seconds = int(seconds)
    if seconds >= 3600:
        return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"
    if seconds >= 60:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds}s"


class _Stream:
    """Wraps stdout/stderr: keeps the bar below all output and mirrors
    lines into the error log."""

    def __init__(self, console, real):
        self._console = console
        self._real = real
        self._pending = ""

    def write(self, text):
        with self._console.lock:
            self._pending += text
            if "\n" not in self._pending:
                return len(text)
            *lines, self._pending = self._pending.split("\n")
            self._console._emit(self._real, lines)
        return len(text)

    def flush(self):
        with self._console.lock:
            if self._pending:
                self._console._clear_bar()
                self._real.write(self._pending)
                self._console._log_lines([self._pending])
                self._pending = ""
            self._real.flush()

    def isatty(self):
        return self._real.isatty()

    def fileno(self):
        return self._real.fileno()

    def __getattr__(self, name):
        return getattr(self._real, name)


class Console:
    def __init__(self):
        self.lock = threading.RLock()
        self.bar = _Bar()
        self._real_out = sys.stdout
        self._interactive = False
        self._bar_shown = False
        self._audited = False

    def install(self, error_log_path="errors.log"):
        handler = RotatingFileHandler(
            error_log_path, maxBytes=10 * 1024 * 1024, backupCount=2
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(message)s", "%Y-%m-%d %H:%M:%S")
        )
        error_logger.addHandler(handler)
        error_logger.info("=" * 20 + " Run started " + "=" * 20)

        self._real_out = sys.stdout
        self._interactive = sys.stdout.isatty()
        sys.stdout = _Stream(self, sys.stdout)
        sys.stderr = _Stream(self, sys.stderr)
        atexit.register(self.finish)

    def phase(self, label, total=None):
        """Switches the bar to a new task. total=None shows a plain counter."""
        with self.lock:
            self.bar.label = label
            self.bar.total = total
            self.bar.done = 0
            self.bar.started = time.monotonic()
            self._draw(force=True)

    def advance(self, n=1):
        with self.lock:
            if not self.bar.active:
                return
            self.bar.done += n
            self._draw()

    def finish(self):
        """Removes the bar (e.g. before prompting the user)."""
        with self.lock:
            self._clear_bar()
            self.bar.label = None

    @contextmanager
    def audited(self):
        """Lines printed inside this block are already in sync_audit.log,
        so they are kept out of the error log."""
        with self.lock:
            prev, self._audited = self._audited, True
            try:
                yield
            finally:
                self._audited = prev

    def action(self, msg):
        with self.audited():
            print(msg)

    def _emit(self, real, lines):
        self._clear_bar()
        for line in lines:
            real.write(line + "\n")
        real.flush()
        self._log_lines(lines)
        self._draw(force=True)

    def _log_lines(self, lines):
        if self._audited:
            return
        for line in lines:
            if line.strip():
                error_logger.info(line)

    def _clear_bar(self):
        if self._bar_shown:
            self._real_out.write(_CLEAR_LINE)
            self._real_out.flush()
            self._bar_shown = False

    def _draw(self, force=False):
        if not (self._interactive and self.bar.active):
            return
        now = time.monotonic()
        if not force and now - self.bar.last_draw < 0.1:
            return
        self.bar.last_draw = now
        width = shutil.get_terminal_size((100, 20)).columns
        self._real_out.write(_CLEAR_LINE + self.bar.render(width))
        self._real_out.flush()
        self._bar_shown = True


console = Console()
