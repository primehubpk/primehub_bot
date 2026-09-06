"""Repair product categories from local folder paths without re-uploading images."""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from rehan_bot.config import Settings
from rehan_bot.primehub.catalog_state import CatalogState, TrackedProduct
from rehan_bot.primehub.categories import (
    category_from_path,
    infer_assets_root,
    match_category,
    wholesale_from_path,
)
from rehan_bot.primehub.firestore_sync import FirestoreStore, store_from_settings
from rehan_bot.primehub.pacing import emit


def _normalize(text: str) -> str:
    return " ".join((text or "").lower().replace("-", " ").replace("_", " ").split())


def _is_wholesale_category(value: str) -> bool:
    return _normalize(value) == "wholesale"


@dataclass
class RepairReport:
    scanned: int = 0
    updated: int = 0
    skipped: int = 0
    relocated: int = 0
    errors: list[str] | None = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


def _recorded_ids(recorded: TrackedProduct) -> list[str]:
    seen: set[str] = set()
    ids: list[str] = []
    for image in recorded.images:
        ident = str(image.product_id or "").strip()
        if ident and ident not in seen:
            seen.add(ident)
            ids.append(ident)
    root = str(recorded.product_id or "").strip()
    if root and root not in seen:
        ids.append(root)
    return ids


def _index_leaf_folders(root: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    if not root.is_dir():
        return index
    for candidate in [root, *root.rglob("*")]:
        if not candidate.is_dir():
            continue
        index.setdefault(candidate.name.lower(), []).append(candidate)
    return index


def _resolve_folder(
    recorded: TrackedProduct,
    index: dict[str, list[Path]],
) -> Path:
    stored = Path(recorded.folder)
    if stored.is_dir():
        return stored
    leaf = (recorded.folder_name or stored.name).lower()
    matches = [path for path in index.get(leaf) or [] if path.is_dir()]
    return matches[0] if matches else stored


def folder_paths_differ(left: Path, right: Path) -> bool:
    try:
        return left.resolve() != right.resolve()
    except OSError:
        return str(left) != str(right)


def repair_storefront_products(
    settings: Settings,
    *,
    dry_run: bool = False,
    store: FirestoreStore | None = None,
    state: CatalogState | None = None,
    assets_root: Path | None = None,
) -> RepairReport:
    client = store if store is not None else store_from_settings(settings)
    if client is None:
        raise RuntimeError("Firebase credentials are not configured.")

    memory = state or CatalogState(settings.catalog_state_path)
    recorded_items = memory.products()
    root = assets_root or infer_assets_root(
        [Path(item.folder) for item in recorded_items],
        getattr(settings, "primehub_products_dir", "") or "",
    )
    index = _index_leaf_folders(root) if root is not None else {}

    live_titles: list[str] = []
    try:
        live_titles = client.live_categories()
    except Exception as exc:
        emit(f"  live categories unavailable ({exc}); using folder names")

    report = RepairReport()
    for recorded in recorded_items:
        report.scanned += 1
        stored = Path(recorded.folder)
        resolved = _resolve_folder(recorded, index)
        planned = category_from_path(resolved, default=recorded.category)
        category = (
            match_category(planned, live_titles, default=recorded.category)
            or recorded.category
        )
        path_changed = resolved.is_dir() and folder_paths_differ(stored, resolved)
        wholesale = wholesale_from_path(resolved) or _is_wholesale_category(category) or _is_wholesale_category(planned)
        fields: dict[str, Any] = {}
        if category and category != recorded.category:
            fields["category"] = category
        if wholesale:
            fields["isWholesale"] = True

        if not fields and not path_changed:
            report.skipped += 1
            continue

        product_ids = _recorded_ids(recorded)
        if fields:
            emit(f"  repair {recorded.folder_name}: {fields} ({len(product_ids)} product(s))")
        if path_changed:
            emit(f"  relocate {stored} -> {resolved}")
        if not dry_run:
            try:
                if fields:
                    for product_id in product_ids:
                        client.update_fields(product_id, fields)
                if path_changed:
                    memory.relocate(stored, resolved, category=category or recorded.category)
                    report.relocated += 1
                elif fields.get("category"):
                    memory.remember(replace(recorded, category=category))
            except Exception as exc:
                report.errors.append(f"{recorded.folder_name}: {exc}")
                continue
        elif path_changed:
            report.relocated += 1
        report.updated += 1

    try:
        for product_id, data in client.list_products():
            category = str(data.get("category") or "")
            should = _is_wholesale_category(category) or _is_wholesale_category(
                str(data.get("categoryId") or "")
            )
            if not should or data.get("isWholesale") is True:
                continue
            fields = {"isWholesale": True}
            emit(f"  tag wholesale {product_id}: {fields} category={category}")
            if not dry_run:
                try:
                    client.update_fields(product_id, fields)
                except Exception as exc:
                    report.errors.append(f"{product_id}: {exc}")
                    continue
            report.updated += 1
    except Exception as exc:
        emit(f"  product list skipped ({exc})")
        report.errors.append(str(exc))

    return report
