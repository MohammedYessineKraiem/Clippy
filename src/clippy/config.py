from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

APP_NAME = "Clippy"


def app_data_dir() -> Path:
    override = os.environ.get("CLIPPY_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / APP_NAME


def bundled_model_dir() -> Path:
    override = os.environ.get("CLIPPY_MODEL_PATH")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).parent / "resources" / "models" / "all-MiniLM-L6-v2"


def bundled_logo_path() -> Path:
    packaged = Path(__file__).parent / "resources" / "Clippy Logo.png"
    if packaged.exists():
        return packaged
    return Path(__file__).parents[2] / "resources" / "Clippy Logo.png"


@dataclass(slots=True)
class AppSettings:
    hotkey: str = "<ctrl>+<alt>+v"
    pin_open: bool = False
    sounds_enabled: bool = False
    sound_volume: float = 0.25
    vault_auto_lock_seconds: int = 60


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or app_data_dir() / "config.json"

    def load(self) -> AppSettings:
        if not self.path.exists():
            return AppSettings()
        try:
            raw: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
            allowed = AppSettings.__dataclass_fields__.keys()
            return AppSettings(**{key: value for key, value in raw.items() if key in allowed})
        except (OSError, ValueError, TypeError):
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
        temporary.replace(self.path)
