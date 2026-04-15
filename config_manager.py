"""Cross-platform settings persistence and configuration."""

import json
import platform
import sys
from pathlib import Path
from typing import Any
import logging

logger = logging.getLogger(__name__)

APP_NAME = "GeminiAnalyzer"
APP_VERSION = "1.0.0"


def get_config_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        base = Path.home() / "AppData" / "Local"
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(
            __import__("os").environ.get("XDG_CONFIG_HOME", "")
            or (Path.home() / ".config")
        )
    config_dir = base / APP_NAME
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_log_dir() -> Path:
    log_dir = get_config_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_desktop_path() -> Path:
    desktop = Path.home() / "Desktop"
    if desktop.exists():
        return desktop
    return Path.home()


DEFAULT_CONFIG = {
    "theme": "dark",
    "window_width": 1400,
    "window_height": 900,
    "window_x": None,
    "window_y": None,
    "last_open_path": "",
    "recent_files": [],
    "max_recent_files": 10,
    "font_size": 11,
    "code_font_size": 12,
    "show_timestamps": True,
    "auto_categorize": True,
    "export_format": "json",
    "search_case_sensitive": False,
    "log_level": "INFO",
    "auto_save_state": True,
    "code_wrap_lines": False,
    "show_line_numbers": True,
}


class Config:

    def __init__(self) -> None:
        self._path = get_config_dir() / "settings.json"
        self._data: dict[str, Any] = dict(DEFAULT_CONFIG)
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                if isinstance(saved, dict):
                    self._data.update(saved)
                    logger.info("Loaded config from %s", self._path)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load config: %s", e)

    def save(self) -> None:
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, default=str)
        except OSError as e:
            logger.error("Failed to save config: %s", e)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def add_recent_file(self, path: str) -> None:
        recent = self._data.get("recent_files", [])
        if path in recent:
            recent.remove(path)
        recent.insert(0, path)
        max_recent = self._data.get("max_recent_files", 10)
        self._data["recent_files"] = recent[:max_recent]

    @property
    def theme(self) -> str:
        return self._data.get("theme", "dark")

    @theme.setter
    def theme(self, value: str) -> None:
        self._data["theme"] = value

    def reset(self) -> None:
        self._data = dict(DEFAULT_CONFIG)
        self.save()
