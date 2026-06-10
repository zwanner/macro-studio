"""Application-level constants: paths, file types, and default settings."""

import sys
from pathlib import Path


APP_TITLE = "Macro Studio"
CONFIG_PATH = Path.home() / ".macro_studio.json"
APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
ASSETS_DIR = APP_DIR / "assets"
APP_ICON_CANDIDATES = [
    ASSETS_DIR / "macro-logo-150.png",
    ASSETS_DIR / "macro-logo-300.png",
    ASSETS_DIR / "macro-logo-75.png",
    ASSETS_DIR / "macro-studio-logo.png",
]
MACRO_FILETYPES = [
    ("Macro files", "*.macro"),
    ("Legacy macro JSON", "*.macro.json"),
    ("JSON", "*.json"),
]

DEFAULT_SETTINGS = {
    "record_hotkey": "<ctrl>+<shift>+r",
    "play_hotkey": "<ctrl>+<shift>+p",
    "stop_hotkey": "<ctrl>+<shift>+x",
    "playback_countdown": 3,
    "recent_files": [],
}
