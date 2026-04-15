"""Diagnostic report generation and logging setup."""

import platform
import sys
import os
import time
import traceback
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime
from typing import Optional

from config_manager import APP_NAME, APP_VERSION, get_log_dir, get_desktop_path

logger = logging.getLogger(__name__)

_start_time = time.time()
_error_buffer: list[str] = []
MAX_ERROR_BUFFER = 50


class ErrorCapture(logging.Handler):

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.WARNING:
            entry = self.format(record)
            _error_buffer.append(entry)
            if len(_error_buffer) > MAX_ERROR_BUFFER:
                _error_buffer.pop(0)


def setup_logging(level: str = "INFO") -> None:
    log_dir = get_log_dir()
    log_file = log_dir / f"{APP_NAME.lower()}.log"

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(numeric_level)

    for handler in root.handlers[:]:
        root.removeHandler(handler)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter(
        "[%(levelname)s] %(message)s"
    ))

    error_capture = ErrorCapture()
    error_capture.setLevel(logging.WARNING)
    error_capture.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s\n%(exc_info)s"
        if False else
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))

    root.addHandler(file_handler)
    root.addHandler(console_handler)
    root.addHandler(error_capture)

    logger.info("Logging initialized at %s level, file: %s", level, log_file)


def _get_system_info() -> str:
    lines = [
        f"OS:              {platform.system()} {platform.release()} ({platform.version()})",
        f"Machine:         {platform.machine()}",
        f"Python:          {sys.version}",
        f"Platform:        {platform.platform()}",
        f"Processor:       {platform.processor() or 'N/A'}",
    ]
    try:
        import shutil
        total, used, free = shutil.disk_usage(Path.home())
        lines.append(f"Disk (home):     {free // (1024**3)} GB free / {total // (1024**3)} GB total")
    except Exception:
        lines.append("Disk:            N/A")

    try:
        if platform.system() == "Windows":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            mem = ctypes.c_ulonglong()
            kernel32.GetPhysicallyInstalledSystemMemory(ctypes.byref(mem))
            lines.append(f"RAM:             {mem.value // 1024} MB")
        else:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal"):
                        kb = int(line.split()[1])
                        lines.append(f"RAM:             {kb // 1024} MB")
                        break
    except Exception:
        lines.append("RAM:             N/A")

    return "\n".join(lines)


def _get_dependency_info() -> str:
    deps = ["tkinter", "json", "re", "pathlib", "logging", "zipfile"]
    optional = {
        "ttkbootstrap": "Modern theme (optional)",
        "Pillow": "Image handling (optional)",
    }

    lines = []
    for dep in deps:
        try:
            __import__(dep)
            lines.append(f"  [OK]  {dep}")
        except ImportError:
            lines.append(f"  [MISSING] {dep}")

    for dep, desc in optional.items():
        try:
            mod = __import__(dep)
            ver = getattr(mod, "__version__", "installed")
            lines.append(f"  [OK]  {dep} {ver} — {desc}")
        except ImportError:
            lines.append(f"  [N/A] {dep} — {desc}")

    return "\n".join(lines)


def generate_report(
    app_state: Optional[dict] = None,
    save_to_desktop: bool = True,
) -> str:
    uptime_seconds = time.time() - _start_time
    uptime_min = uptime_seconds / 60

    sections = []

    sections.append(f"""{'=' * 70}
  {APP_NAME} Diagnostic Report
  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
  Version: {APP_VERSION}
{'=' * 70}

To share this report for support, copy the entire contents
and include a description of your issue.
NOTE: This report does NOT contain passwords, API keys, or tokens.
""")

    sections.append(f"""--- SYSTEM INFO ---
{_get_system_info()}
""")

    sections.append(f"""--- APP STATE ---
Uptime:          {uptime_min:.1f} minutes
""")

    if app_state:
        for key, value in app_state.items():
            if any(s in key.lower() for s in ("password", "key", "token", "secret")):
                continue
            sections.append(f"  {key}: {value}")
        sections.append("")

    sections.append(f"""--- DEPENDENCIES ---
{_get_dependency_info()}
""")

    sections.append("--- RECENT ERRORS/WARNINGS ---")
    if _error_buffer:
        for entry in _error_buffer[-50:]:
            sections.append(f"  {entry}")
    else:
        sections.append("  No errors or warnings recorded.")
    sections.append("")

    sections.append(f"""--- PERFORMANCE ---
Startup time:    Recorded in log
Uptime:          {uptime_min:.1f} minutes
Error count:     {len(_error_buffer)}
""")

    report = "\n".join(sections)

    if save_to_desktop:
        desktop = get_desktop_path()
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        filename = f"{APP_NAME}_diagnostic_{timestamp}.txt"
        filepath = desktop / filename
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(report)
            logger.info("Diagnostic report saved to %s", filepath)
        except OSError as e:
            logger.error("Failed to save diagnostic report: %s", e)

    return report
