"""Réglages de l'utilisateur et fichiers récents (%APPDATA%\\DestriPDF)."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

APP_DIR = Path(os.environ.get("APPDATA") or Path.home()) / "DestriPDF"
LOCAL_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "DestriPDF"
SIGNATURE_IMAGE = "signature.png"
MAX_RECENT = 12
MAX_SIGNATURE_IMAGE = 2 * 1024 * 1024

DEFAULTS = {
    "author": "",
    "sign_reason": "",
    "sign_location": "",
    "sign_visible": True,
    "sign_with_image": True,
    "timestamp_url": "",
    "last_dir": "",
    "theme": "auto",
    "recent": [],
}

EDITABLE = {"author", "sign_reason", "sign_location", "sign_visible", "sign_with_image", "timestamp_url", "theme"}


class Settings:
    def __init__(self, directory: Path | None = None):
        self.dir = Path(directory) if directory else APP_DIR
        self._lock = threading.Lock()
        self._data = dict(DEFAULTS)
        self._load()

    @property
    def path(self) -> Path:
        return self.dir / "settings.json"

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        if isinstance(raw, dict):
            for key, default in DEFAULTS.items():
                value = raw.get(key, default)
                if isinstance(value, type(default)):
                    self._data[key] = value
        if not self._data["author"]:
            self._data["author"] = os.environ.get("USERNAME", "")

    def _save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def get(self, key: str):
        with self._lock:
            return self._data.get(key, DEFAULTS.get(key))

    def public(self) -> dict:
        with self._lock:
            data = {k: self._data[k] for k in EDITABLE}
            data["has_signature_image"] = self.signature_image_path.exists()
            return data

    def update(self, changes: dict) -> dict:
        with self._lock:
            for key, value in (changes or {}).items():
                if key not in EDITABLE:
                    continue
                default = DEFAULTS[key]
                if isinstance(default, bool):
                    value = bool(value)
                elif isinstance(default, str):
                    value = str(value or "").strip()[:300]
                    if key == "timestamp_url" and value and not value.lower().startswith(("http://", "https://")):
                        raise ValueError("L'adresse d'horodatage doit commencer par http:// ou https://.")
                    if key == "theme" and value not in ("auto", "light", "dark"):
                        value = "auto"
                self._data[key] = value
            self._save()
        return self.public()

    def remember_dir(self, path: str) -> None:
        with self._lock:
            self._data["last_dir"] = str(Path(path).parent)
            self._save()

    def add_recent(self, path: str) -> None:
        path = str(Path(path))
        with self._lock:
            recent = [r for r in self._data.get("recent", []) if isinstance(r, dict) and r.get("path", "").lower() != path.lower()]
            recent.insert(0, {"path": path, "name": Path(path).name, "opened_at": int(time.time())})
            self._data["recent"] = recent[:MAX_RECENT]
            self._data["last_dir"] = str(Path(path).parent)
            self._save()

    def remove_recent(self, path: str) -> None:
        with self._lock:
            self._data["recent"] = [r for r in self._data.get("recent", []) if r.get("path", "").lower() != str(path).lower()]
            self._save()

    def recent(self) -> list[dict]:
        with self._lock:
            items = list(self._data.get("recent", []))
        return [dict(r, exists=os.path.exists(r.get("path", ""))) for r in items]

    def is_recent(self, path: str) -> bool:
        with self._lock:
            return any(r.get("path", "").lower() == str(Path(path)).lower() for r in self._data.get("recent", []))

    @property
    def signature_image_path(self) -> Path:
        return self.dir / SIGNATURE_IMAGE

    def signature_image(self) -> bytes | None:
        try:
            return self.signature_image_path.read_bytes()
        except OSError:
            return None

    def set_signature_image(self, data: bytes) -> None:
        if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) > MAX_SIGNATURE_IMAGE:
            raise ValueError("Image de signature invalide (PNG de 2 Mo au plus).")
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.signature_image_path.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, self.signature_image_path)

    def delete_signature_image(self) -> None:
        try:
            self.signature_image_path.unlink()
        except FileNotFoundError:
            pass
