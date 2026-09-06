"""Folder-to-catalog sync: process only new/changed product photos."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from collections.abc import Callable
from typing import Any

from rehan_bot.config import Settings

from .catalog_state import CatalogState, TrackedImage, TrackedProduct, lock_recorded_copy
from .categories import match_category
from .cdn import is_storefront_image_url
from .client import PrimeHubAPIError, PrimeHubClient
from .folder_parser import (
    ParsedFolder,
    discover_product_tree,
    parse_product_folder,
)
from .image_pipeline import process_product_image
from .pacing import (
    emit,
    folder_delay_seconds,
    folder_label,
    image_delay_seconds,
    pause,
)
from .payload import build_product_payload, card_base_title, slugify
from .firestore_sync import FirestoreStore
from .r2 import R2Error
from .sizes import should_use_adult_allsize
from .sync_plan import list_sync_files, prepare_folder_files, product_groups
from .folder_mode import (
    MODE_EDIT_ONLY,
    MODE_ONE_PER_IMAGE,
    MODE_SPLIT_GROUP3,
    folder_needs_collage_edit,
    is_cover_all,
)
from .uploader import _client_from_settings, _enrich_copy, _image_store_from_settings

logger = logging.getLogger("rehan_bot.primehub.catalog_sync")


@dataclass
class FolderSyncResult:
    folder: str
    action: str
    slug: str = ""
    product_id: str = ""
    processed: int = 0
    skipped_images: int = 0
    error: str = ""
    http_status: int = 0
    images: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SyncReport:
    dry_run: bool
    scanned: int = 0
    created: int = 0
    appended: int = 0
    skipped: int = 0
    new_images: int = 0
    errors: list[str] = field(default_factory=list)
    folders: list[FolderSyncResult] = field(default_factory=list)

    def summary_line(self) -> str:
        parts = [f"Scanned {self.scanned} folders"]
        details: list[str] = []
        if self.created:
            details.append(f"{self.created} new folder{'s' if self.created != 1 else ''}")
        if self.appended:
            details.append(
                f"{self.appended} folder{'s' if self.appended != 1 else ''} updated"
            )
        if self.new_images:
            details.append(
                f"{self.new_images} new image{'s' if self.new_images != 1 else ''} processed"
            )
        if self.skipped:
            details.append(
                f"{self.skipped} folder{'s' if self.skipped != 1 else ''} up-to-date"
            )
        if self.errors:
            details.append(f"{len(self.errors)} error{'s' if len(self.errors) != 1 else ''}")
        if not details:
            details.append("nothing to do")
        return f"{parts[0]}: {', '.join(details)}."


def resolve_max_images(settings: Settings, override: int | None = None) -> int | None:
    """Return an optional cap, or ``None`` to process every image in the folder."""
    return settings.split_image_limit(override)


def sync_catalog(
    root: Path,
    settings: Settings,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    base_url: str | None = None,
    state: CatalogState | None = None,
    client: PrimeHubClient | None = None,
    imgbb: Any | None = None,
    fetch_live_metadata: bool = True,
    enricher: Callable[..., Any] | None = None,
    force: bool = False,
    max_images: int | None = None,
    edit_only: bool = False,
) -> SyncReport:
    root_path = Path(root)
    folders = discover_product_tree(root_path)
    max_work = None if limit is None else max(0, int(limit))

    report = SyncReport(dry_run=dry_run)
    emit(f"Discovered {len(folders)} product folder(s) under {folder_label(root_path)}:")
    for folder in folders:
        count = len(list_sync_files(folder))
        emit(f"  - {folder_label(folder)} ({count} image(s))")
    memory = state or CatalogState(settings.catalog_state_path)
    store = client if client is not None else _client_from_settings(settings, base_url)
    if isinstance(store, FirestoreStore):
        emit("Direct Firestore sync enabled (bypassing Vercel API).")
    uploader = imgbb if imgbb is not None else _image_store_from_settings(settings)

    live_titles: list[str] = []
    live_buckets: list[Any] = []
    if fetch_live_metadata and store is not None and not dry_run and not edit_only:
        try:
            metadata = store.fetch_metadata()
            live_titles = store.live_categories(metadata)
            live_buckets = store.live_buckets(metadata)
        except PrimeHubAPIError as exc:
            logger.warning("Live metadata unavailable: %s", exc)

    if max_work == 0:
        report.scanned = len(folders)
        return report

    if edit_only:
        emit(
            "Edit-only: har design check; PASS skip; sirf FAIL/missed theek. "
            "Saari pics dubara nahi katein gi. Upload nahi."
        )
        for folder in folders:
            report.scanned += 1
            if not folder_needs_collage_edit(folder):
                emit(
                    f"  skip {folder_label(folder)} "
                    "(folder naam mein one/onepair/oneset/onepiece/onepack nahi)"
                )
                report.skipped += 1
                report.folders.append(
                    FolderSyncResult(folder=str(folder), action="skip")
                )
                continue
            try:
                _mode, files = prepare_folder_files(folder, settings)
            except Exception as exc:
                message = f"{folder}: {exc}"
                logger.warning("Edit-only crop failed: %s", message)
                report.errors.append(message)
                report.folders.append(
                    FolderSyncResult(folder=str(folder), action="error", error=str(exc))
                )
                continue
            emit(f"  cropped {folder_label(folder)} ({len(files)} file(s), no upload)")
            if not files:
                emit(
                    f"  warning {folder_label(folder)}: koi design_*.webp nahi bani — "
                    "collage sources ya Gemini boxes check karo"
                )
            report.folders.append(
                FolderSyncResult(
                    folder=str(folder),
                    action="edit_only",
                    processed=len(files),
                )
            )
        return report

    pending: list[Path] = []
    for folder in folders:
        report.scanned += 1
        files = list(list_sync_files(folder))
        delta = memory.inspect(folder, files)
        if delta.is_skip and not force:
            try:
                repaired = _repair_recorded_category(
                    folder,
                    settings,
                    memory=memory,
                    store=store,
                    live_titles=live_titles,
                    recorded=delta.recorded,
                    dry_run=dry_run,
                )
            except Exception as exc:
                message = f"{folder}: {exc}"
                logger.warning("Category repair failed: %s", message)
                emit(f"  warning: {exc} — continuing")
                report.errors.append(message)
                report.folders.append(
                    FolderSyncResult(folder=str(folder), action="error", error=str(exc))
                )
                continue
            if repaired is not None:
                report.folders.append(repaired)
                report.appended += 1
                continue
            logger.info("Up-to-date: %s", folder.name)
            result = FolderSyncResult(
                folder=str(folder),
                action="skip",
                slug=(delta.recorded.slug if delta.recorded else ""),
                product_id=(delta.recorded.product_id if delta.recorded else ""),
                skipped_images=len(delta.unchanged_files),
            )
            report.folders.append(result)
            report.skipped += 1
            continue
        pending.append(folder)
    if max_work is not None:
        pending = pending[:max_work]

    total = len(pending)
    wait_between_folders = folder_delay_seconds(settings, dry_run=dry_run)
    image_wait = wait_between_folders
    if total:
        emit(f"Human-paced catalog-sync: {total} folder(s) to process, {report.skipped} already synced.")

    for index, folder in enumerate(pending, start=1):
        emit(f"[Folder {index}/{total}] Processing: {folder_label(folder)}")
        try:
            result = _sync_one(
                folder,
                settings,
                memory=memory,
                store=store,
                uploader=uploader,
                live_titles=live_titles,
                live_buckets=live_buckets,
                dry_run=dry_run,
                enricher=enricher,
                force=force,
                max_images=resolve_max_images(settings, max_images),
                image_delay=image_wait,
            )
        except Exception as exc:
            message = f"{folder}: {exc}"
            logger.warning("Catalog sync failed: %s", message)
            emit(f"  warning: {exc} — saving progress and continuing")
            report.errors.append(message)
            report.folders.append(
                FolderSyncResult(folder=str(folder), action="error", error=str(exc))
            )
            if index < total and wait_between_folders:
                emit(f"  waiting {wait_between_folders:.1f}s before next folder")
                pause(wait_between_folders)
            continue
        report.folders.append(result)
        report.new_images += result.processed
        if result.action == "create":
            report.created += 1
        elif result.action in {"append", "update"}:
            report.appended += 1
        if result.error:
            report.errors.append(f"{folder}: {result.error}")
            emit(f"  warning: {result.error} — continuing")
        elif not dry_run:
            status = result.http_status or 200
            emit(
                f"  OK HTTP {status} {result.action} "
                f"id={result.product_id or '-'} — saved catalog_state.json"
            )
        if index < total and wait_between_folders:
            emit(f"  waiting {wait_between_folders:.1f}s before next folder")
            pause(wait_between_folders)
    return report


def _recorded_product_ids(recorded: TrackedProduct | None) -> list[str]:
    if recorded is None:
        return []
    seen: set[str] = set()
    ids: list[str] = []
    for item in recorded.images:
        ident = str(item.product_id or "").strip()
        if ident and ident not in seen:
            seen.add(ident)
            ids.append(ident)
    root = str(recorded.product_id or "").strip()
    if root and root not in seen:
        ids.append(root)
    return ids


def _repair_recorded_category(
    folder: Path,
    settings: Settings,
    *,
    memory: CatalogState,
    store: PrimeHubClient | None,
    live_titles: list[str],
    recorded: TrackedProduct | None,
    dry_run: bool,
) -> FolderSyncResult | None:
    """Fix a wrong category on already-synced cards without touching R2 images."""
    if recorded is None:
        return None
    parsed = parse_product_folder(
        folder, default_category=settings.primehub_default_category
    )
    category = match_category(
        parsed.category_hint,
        live_titles,
        default=settings.primehub_default_category,
    )
    stored_path = Path(recorded.folder)
    path_changed = stored_path.resolve() != Path(folder).resolve()
    if not category or (recorded.category == category and not path_changed):
        return None
    product_ids = _recorded_product_ids(recorded)
    if recorded.category != category:
        emit(
            f"  category repair: {recorded.category or '(empty)'} -> {category} "
            f"({len(product_ids)} product(s), images unchanged)"
        )
    if path_changed:
        emit(f"  path repair: {stored_path} -> {folder}")
    fields = {"category": category, "isWholesale": bool(parsed.wholesale)}
    if not dry_run:
        if store is None or not hasattr(store, "update_fields"):
            raise PrimeHubAPIError("Store cannot update product categories in place.")
        if recorded.category != category:
            for product_id in product_ids:
                store.update_fields(product_id, fields)
        if path_changed:
            memory.relocate(stored_path, folder, category=category)
        else:
            memory.remember(replace(recorded, category=category))
    return FolderSyncResult(
        folder=str(folder),
        action="category",
        slug=recorded.slug,
        product_id=recorded.product_id,
        processed=0,
        skipped_images=len(recorded.images),
    )


def _sync_one(
    folder: Path,
    settings: Settings,
    *,
    memory: CatalogState,
    store: PrimeHubClient | None,
    uploader: Any | None,
    live_titles: list[str],
    live_buckets: list[Any],
    dry_run: bool,
    enricher: Callable[..., Any] | None = None,
    force: bool = False,
    max_images: int | None = None,
    image_delay: float = 0.0,
) -> FolderSyncResult:
    files = list(list_sync_files(folder))
    delta = memory.inspect(folder, files)
    if delta.is_skip and not force:
        logger.info("Up-to-date: %s", folder.name)
        return FolderSyncResult(
            folder=str(folder),
            action="skip",
            slug=(delta.recorded.slug if delta.recorded else ""),
            product_id=(delta.recorded.product_id if delta.recorded else ""),
            skipped_images=len(delta.unchanged_files),
        )

    parsed = parse_product_folder(
        folder, default_category=settings.primehub_default_category
    )
    category = match_category(
        parsed.category_hint,
        live_titles,
        default=settings.primehub_default_category,
    )
    mode, files = prepare_folder_files(folder, settings)
    if mode == MODE_SPLIT_GROUP3:
        emit(
            "  Rehan QA: each design inspected one-by-one; FAIL crops are not saved; "
            "lifestyle photos keep their own background"
        )
    if mode == MODE_EDIT_ONLY:
        emit(f"  edit folder: saved {len(files)} design crop(s), skip upload")
        return FolderSyncResult(
            folder=str(folder),
            action="edit_only",
            processed=len(files),
        )

    action = "update" if delta.is_skip and force else delta.action
    split_already = bool(delta.recorded and delta.recorded.is_split)
    if force or not split_already:
        work = list(files)
    elif mode == MODE_ONE_PER_IMAGE:
        work = list(delta.new_files)
    else:
        work = list(files)
    groups = product_groups(mode, work)
    if max_images is not None and mode == MODE_ONE_PER_IMAGE:
        groups = groups[: max(0, int(max_images))]
    elif max_images is not None:
        capped = work[: max(0, int(max_images))]
        groups = product_groups(mode, capped)
    skipped_overflow = max(0, len(work) - sum(len(group) for group in groups))

    if dry_run:
        return FolderSyncResult(
            folder=str(folder),
            action=action,
            slug=product_slug(parsed, delta.recorded),
            processed=sum(len(group) for group in groups),
            skipped_images=len(delta.unchanged_files) if split_already else skipped_overflow,
        )

    if store is None:
        raise PrimeHubAPIError("PRIMEHUB_API_KEY is not configured")
    if uploader is None:
        raise R2Error(
            "Cloudflare R2 is not configured. Set R2_ACCOUNT_ID, R2_BUCKET_NAME, "
            "R2_PUBLIC_BASE_URL, R2_ACCESS_KEY_ID, and R2_SECRET_ACCESS_KEY."
        )

    recorded = delta.recorded
    if (
        recorded
        and recorded.product_id
        and not recorded.is_split
        and hasattr(store, "delete_product")
    ):
        emit(f"  removing merged product {recorded.product_id}")
        store.delete_product(recorded.product_id)

    tracked_by_name = {item.name: item for item in (recorded.images if recorded else [])}
    image_notes: list[dict[str, Any]] = []
    last_created: dict[str, Any] = {}
    first_bytes: bytes | None = None
    first_payload: dict[str, Any] | None = None
    processed_count = 0

    adult_all = should_use_adult_allsize(parsed.folder_name, parsed.folder)
    total_groups = len(groups)
    used_product_ids: set[str] = set()
    for group_index, group in enumerate(groups, start=1):
        urls: list[str] = []
        group_notes: list[tuple[Path, Any, str]] = []
        for image in group:
            emit(f"  Photo {image.name} (card {group_index}/{total_groups})")
            processed = process_product_image(image, folder=folder)
            if first_bytes is None:
                first_bytes = processed.data
            url, _cached = uploader.resolve_processed(
                image,
                processed.data,
                processed.filename,
                upload=True,
                refresh=force,
            )
            if not url:
                raise R2Error(f"No URL returned for {image.name}")
            if not is_storefront_image_url(url, settings.r2_public_base_url):
                raise R2Error(f"Expected R2 or legacy ImgBB CDN URL, got {url}")
            urls.append(url)
            group_notes.append((image, processed, url))
            if image_delay and image is not group[-1]:
                pause(image_delay)

        if recorded and recorded.description:
            description = recorded.description
            base_title = card_base_title(recorded.title or parsed.title)
        else:
            enrichment = (enricher or _enrich_copy)(parsed, settings, first_bytes)
            description = enrichment.description
            base_title = enrichment.title
        if mode == MODE_ONE_PER_IMAGE:
            image = group[0]
            set_no = files.index(image) + 1 if image in files else group_index
        else:
            set_no = None
        payload = build_product_payload(
            parsed,
            urls,
            live_category=category,
            live_buckets=live_buckets,
            title=base_title,
            description=description,
            set_index=set_no,
            all_adult_sizes=adult_all,
            design_variants=len(urls) > 1,
            hero_cover=is_cover_all(group[0]),
        )
        prior_file = group[1] if len(group) > 1 and is_cover_all(group[0]) else group[0]
        prior = tracked_by_name.get(prior_file.name)
        product_id = str((prior.product_id if prior else "") or "")
        if product_id in used_product_ids:
            product_id = ""
        try:
            created = store.create_product(payload, product_id=product_id or None)
        except TypeError:
            created = store.create_product(payload)
        status = int(created.get("http_status") or 200)
        if status not in (200, 201):
            raise PrimeHubAPIError(f"Product write -> HTTP {status}")
        created_id = str(created.get("id") or "")
        if created_id:
            used_product_ids.add(created_id)
        created_slug = str(created.get("slug") or payload.get("slug") or "")
        card_title = str(payload.get("title") or "")
        for image, processed, url in group_notes:
            tracked = TrackedImage.from_file(
                image,
                url=url,
                product_id=created_id,
                slug=created_slug,
                title=card_title,
            )
            tracked_by_name[image.name] = tracked
            processed_count += 1
            note = _image_note(image, processed, url)
            note["product_id"] = tracked.product_id
            note["slug"] = tracked.slug
            note["title"] = tracked.title
            image_notes.append(note)
        ordered = [tracked_by_name[path.name] for path in files if path.name in tracked_by_name]
        remembered = TrackedProduct(
            folder=folder_key_safe(parsed.folder),
            folder_name=parsed.folder_name,
            slug=str(ordered[0].slug if ordered else payload.get("slug") or ""),
            product_id=str(ordered[0].product_id if ordered else created.get("id") or ""),
            title=str(ordered[0].title if ordered else payload.get("title") or parsed.title),
            description=description,
            category=category,
            images=ordered,
        )
        memory.remember(remembered)
        recorded = remembered
        last_created = created
        first_payload = first_payload or payload
        emit(
            f"  OK HTTP {status} card {group_index} id={created_id or '-'} — saved catalog_state.json"
        )
        if group_index < total_groups and image_delay:
            emit(f"  waiting {image_delay:.1f}s before next card")
            pause(image_delay)

    return FolderSyncResult(
        folder=str(folder),
        action=action,
        slug=str(last_created.get("slug") or (recorded.slug if recorded else "")),
        product_id=str(
            (recorded.product_id if recorded else "") or last_created.get("id") or ""
        ),
        processed=processed_count,
        skipped_images=skipped_overflow,
        http_status=int(last_created.get("http_status") or 200),
        images=image_notes,
    )


def _image_note(image: Path, processed: Any, url: str) -> dict[str, Any]:
    return {
        "file": image.name,
        "style": processed.style,
        "margin": processed.margin,
        "ev": processed.ev,
        "url": url,
        "original_width": processed.original_width,
        "original_height": processed.original_height,
        **processed.compressed.summary(),
    }


def _append_payload(
    parsed: ParsedFolder,
    recorded: TrackedProduct,
    gallery: list[str],
    category: str,
    live_buckets: list[Any],
    max_images: int | None = None,
) -> dict[str, Any]:
    """Reuse stored sales copy; only the image list changes."""
    payload = build_product_payload(
        parsed,
        gallery,
        live_category=recorded.category or category,
        live_buckets=live_buckets,
        title=recorded.title or parsed.title,
        description=recorded.description or None,
        max_images=max_images,
    )
    return lock_recorded_copy(payload, recorded)


def _remembered_product(
    parsed: ParsedFolder,
    payload: dict[str, Any],
    created: dict[str, Any],
    category: str,
    images: list[TrackedImage],
    recorded: TrackedProduct | None = None,
) -> TrackedProduct:
    seen: set[str] = set()
    unique: list[TrackedImage] = []
    for item in images:
        key = item.sha256 or item.name
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return TrackedProduct(
        folder=folder_key_safe(parsed.folder),
        folder_name=parsed.folder_name,
        slug=str(
            (recorded.slug if recorded and recorded.slug else "")
            or created.get("slug")
            or payload.get("slug")
            or ""
        ),
        product_id=str(
            (recorded.product_id if recorded and recorded.product_id else "")
            or created.get("id")
            or ""
        ),
        title=str(
            (recorded.title if recorded and recorded.title else "")
            or payload.get("title")
            or parsed.title
        ),
        description=str(
            (recorded.description if recorded and recorded.description else "")
            or payload.get("description")
            or ""
        ),
        category=category,
        images=unique,
    )


def product_slug(parsed: ParsedFolder, recorded: TrackedProduct | None = None) -> str:
    """Prefer a stored slug; otherwise avoid colliding Price_* / Allsize titles."""
    if recorded and recorded.slug:
        return recorded.slug
    if _weak_stem(parsed.stem):
        return slugify(parsed.folder_name)
    return slugify(parsed.title)


def _weak_stem(stem: str) -> bool:
    text = (stem or "").strip().lower()
    if not text or text.startswith("price ") or text in {"allsize", "all size"}:
        return True
    compact = re.sub(r"[\s.\-_]+", "", text)
    return compact.isdigit()


def folder_key_safe(folder: Path) -> str:
    try:
        return str(Path(folder).resolve())
    except OSError:
        return str(folder)
