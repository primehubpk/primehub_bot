"""Persistent ImgBB URL cache keyed by file content hash."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_CACHE_PATH = Path("runtime/memory/uploaded_images_cache.json")


def _cache_key(digest: str, variant: str = "") -> str:
    token = (variant or "").strip()
    return f"{digest}:{token}" if token else digest


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ImageUploadCache:
    """Reuse a previously uploaded ImgBB URL when the same bytes appear again."""

    def __init__(self, path: Path | str = DEFAULT_CACHE_PATH) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def lookup(self, image_path: Path, variant: str = "") -> str | None:
        return self.lookup_key(file_sha256(image_path), variant=variant)

    def lookup_bytes(self, data: bytes, variant: str = "") -> str | None:
        return self.lookup_key(hashlib.sha256(data).hexdigest(), variant=variant)

    def lookup_key(self, digest: str, variant: str = "") -> str | None:
        key = _cache_key(digest, variant)
        with self._lock:
            entry = (self._read().get("images") or {}).get(key)
        if not isinstance(entry, dict):
            return None
        url = str(entry.get("url") or "").strip()
        return url or None

    def remember(self, image_path: Path, url: str, variant: str = "") -> None:
        self.remember_key(
            file_sha256(image_path),
            url,
            path=str(image_path),
            name=image_path.name,
            size=image_path.stat().st_size if image_path.exists() else 0,
            variant=variant,
        )

    def remember_bytes(
        self,
        data: bytes,
        url: str,
        *,
        source_path: Path | None = None,
        name: str = "",
        variant: str = "",
    ) -> None:
        path = source_path or Path(name or "image.webp")
        self.remember_key(
            hashlib.sha256(data).hexdigest(),
            url,
            path=str(path),
            name=name or path.name,
            size=len(data),
            variant=variant,
        )

    def remember_key(
        self,
        digest: str,
        url: str,
        *,
        path: str,
        name: str,
        size: int,
        variant: str = "",
    ) -> None:
        key = _cache_key(digest, variant)
        payload = {
            "url": url,
            "path": path,
            "name": name,
            "size": size,
            "variant": variant,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            data = self._read()
            images = dict(data.get("images") or {})
            images[key] = payload
            data["version"] = 1
            data["images"] = images
            self._write(data)

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"version": 1, "images": {}}
        try:
            parsed = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return {"version": 1, "images": {}}
        return parsed if isinstance(parsed, dict) else {"version": 1, "images": {}}

    def _write(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(
            prefix=f".{self._path.name}.",
            suffix=".tmp",
            dir=self._path.parent,
            text=True,
        )
        os.close(handle)
        try:
            Path(temp_name).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temp_name, self._path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
