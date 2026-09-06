"""Persistent catalog memory: folder path, slug, and per-image hashes."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .image_cache import file_sha256

DEFAULT_STATE_PATH = Path("runtime/memory/catalog_state.json")


def folder_key(folder: Path) -> str:
    return str(Path(folder).resolve())


@dataclass
class TrackedImage:
    name: str
    sha256: str
    mtime: float
    size: int
    url: str = ""
    product_id: str = ""
    slug: str = ""
    title: str = ""

    @classmethod
    def from_file(
        cls,
        path: Path,
        url: str = "",
        product_id: str = "",
        slug: str = "",
        title: str = "",
    ) -> TrackedImage:
        stat = path.stat()
        return cls(
            name=path.name,
            sha256=file_sha256(path),
            mtime=stat.st_mtime,
            size=stat.st_size,
            url=url,
            product_id=product_id,
            slug=slug,
            title=title,
        )


@dataclass
class TrackedProduct:
    folder: str
    folder_name: str
    slug: str
    product_id: str = ""
    title: str = ""
    description: str = ""
    category: str = ""
    images: list[TrackedImage] = field(default_factory=list)

    @property
    def image_urls(self) -> list[str]:
        return [item.url for item in self.images if item.url]

    @property
    def hashes(self) -> set[str]:
        return {item.sha256 for item in self.images if item.sha256}

    def image_named(self, name: str) -> TrackedImage | None:
        for item in self.images:
            if item.name == name:
                return item
        return None

    @property
    def is_split(self) -> bool:
        return any(item.product_id for item in self.images)


def lock_recorded_copy(payload: dict[str, Any], recorded: TrackedProduct) -> dict[str, Any]:
    """Keep an already-synced title, description, and slug unchanged."""
    if recorded.title:
        payload["title"] = recorded.title
    if recorded.description:
        payload["description"] = recorded.description
    if recorded.slug:
        payload["slug"] = recorded.slug
    return payload


@dataclass(frozen=True)
class FolderDelta:
    """What changed in one product folder since the last sync."""

    folder: Path
    action: str
    new_files: tuple[Path, ...]
    unchanged_files: tuple[Path, ...]
    recorded: TrackedProduct | None

    @property
    def is_new(self) -> bool:
        return self.action == "create"

    @property
    def is_append(self) -> bool:
        return self.action == "append"

    @property
    def is_skip(self) -> bool:
        return self.action == "skip"


class CatalogState:
    """Read/write ``catalog_state.json`` with atomic replaces."""

    def __init__(self, path: Path | str = DEFAULT_STATE_PATH) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def get(self, folder: Path) -> TrackedProduct | None:
        key = folder_key(folder)
        with self._lock:
            raw = (self._read().get("products") or {}).get(key)
        if not isinstance(raw, dict):
            return None
        return _product_from_dict(raw)

    def find_by_folder_name(self, name: str) -> TrackedProduct | None:
        """Locate a recorded product after its parent folder was renamed."""
        wanted = (name or "").strip().lower()
        if not wanted:
            return None
        matches = [
            item
            for item in self.products()
            if item.folder_name.lower() == wanted
            or Path(item.folder).name.lower() == wanted
        ]
        if not matches:
            return None
        missing = [item for item in matches if not Path(item.folder).is_dir()]
        return (missing or matches)[0]

    def lookup(self, folder: Path) -> TrackedProduct | None:
        return self.get(folder) or self.find_by_folder_name(Path(folder).name)

    def forget(self, folder: Path) -> None:
        key = folder_key(folder)
        with self._lock:
            data = self._read()
            products = dict(data.get("products") or {})
            if key not in products:
                return
            products.pop(key, None)
            data["products"] = products
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._write(data)

    def relocate(self, old_folder: Path, new_folder: Path, **updates: Any) -> TrackedProduct | None:
        recorded = self.get(old_folder) or self.find_by_folder_name(Path(new_folder).name)
        if recorded is None:
            return None
        payload = asdict(recorded)
        payload.update(updates)
        payload["folder"] = folder_key(new_folder)
        payload["folder_name"] = Path(new_folder).name
        moved = _product_from_dict(payload)
        old_key = folder_key(old_folder)
        new_key = folder_key(new_folder)
        with self._lock:
            data = self._read()
            products = dict(data.get("products") or {})
            products.pop(old_key, None)
            products[new_key] = asdict(moved)
            data["version"] = 1
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
            data["products"] = products
            self._write(data)
        return moved

    def products(self) -> list[TrackedProduct]:
        with self._lock:
            raw = self._read().get("products") or {}
        items: list[TrackedProduct] = []
        if not isinstance(raw, dict):
            return items
        for value in raw.values():
            if isinstance(value, dict):
                items.append(_product_from_dict(value))
        return items

    def remember(self, product: TrackedProduct) -> None:
        key = folder_key(Path(product.folder))
        payload = asdict(product)
        with self._lock:
            data = self._read()
            products = dict(data.get("products") or {})
            products[key] = payload
            data["version"] = 1
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
            data["products"] = products
            self._write(data)

    def inspect(self, folder: Path, files: list[Path] | tuple[Path, ...]) -> FolderDelta:
        """Return create / append / skip without opening image bytes when possible."""
        recorded = self.lookup(folder)
        paths = tuple(Path(item) for item in files)
        if recorded is None:
            return FolderDelta(
                folder=Path(folder),
                action="create" if paths else "skip",
                new_files=paths,
                unchanged_files=(),
                recorded=None,
            )
        new_files: list[Path] = []
        unchanged: list[Path] = []
        known_hashes = recorded.hashes
        for path in paths:
            if _file_matches_record(path, recorded, known_hashes):
                unchanged.append(path)
            else:
                new_files.append(path)
        action = "append" if new_files else "skip"
        if action == "skip" and recorded is not None and paths and not recorded.is_split:
            action = "update"
        return FolderDelta(
            folder=Path(folder),
            action=action,
            new_files=tuple(new_files),
            unchanged_files=tuple(unchanged),
            recorded=recorded,
        )

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"version": 1, "products": {}}
        try:
            parsed = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return {"version": 1, "products": {}}
        return parsed if isinstance(parsed, dict) else {"version": 1, "products": {}}

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


def _file_matches_record(
    path: Path, recorded: TrackedProduct, known_hashes: set[str]
) -> bool:
    """True when this file was already synced (mtime/size shortcut, else hash)."""
    if not path.exists():
        return False
    stat = path.stat()
    prior = recorded.image_named(path.name)
    if (
        prior is not None
        and prior.size == stat.st_size
        and abs(prior.mtime - stat.st_mtime) < 0.001
        and prior.sha256
    ):
        return True
    digest = file_sha256(path)
    return digest in known_hashes


def _product_from_dict(raw: dict[str, Any]) -> TrackedProduct:
    images = []
    for item in raw.get("images") or []:
        if not isinstance(item, dict):
            continue
        images.append(
            TrackedImage(
                name=str(item.get("name") or ""),
                sha256=str(item.get("sha256") or ""),
                mtime=float(item.get("mtime") or 0),
                size=int(item.get("size") or 0),
                url=str(item.get("url") or ""),
                product_id=str(item.get("product_id") or ""),
                slug=str(item.get("slug") or ""),
                title=str(item.get("title") or ""),
            )
        )
    return TrackedProduct(
        folder=str(raw.get("folder") or ""),
        folder_name=str(raw.get("folder_name") or ""),
        slug=str(raw.get("slug") or ""),
        product_id=str(raw.get("product_id") or ""),
        title=str(raw.get("title") or ""),
        description=str(raw.get("description") or ""),
        category=str(raw.get("category") or ""),
        images=images,
    )
