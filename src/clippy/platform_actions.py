from __future__ import annotations

import os
import re
import subprocess
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
WINDOWS_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|\\\\)[^\r\n]+")


def extract_url(text: str) -> str | None:
    match = URL_RE.search(text)
    if not match:
        return None
    value = match.group(0).rstrip('.,;:!?)"]}')
    parsed = urlparse(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else None


def extract_path(text: str) -> Path | None:
    match = WINDOWS_PATH_RE.search(text)
    if not match:
        return None
    return Path(match.group(0).strip().strip('"'))


def open_url(text: str) -> bool:
    url = extract_url(text)
    return bool(url and webbrowser.open(url, new=2))


def reveal_path(text: str) -> bool:
    path = extract_path(text)
    if not path or not path.exists():
        return False
    if path.is_dir():
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["explorer.exe", "/select,", str(path)], close_fds=True)
    return True
