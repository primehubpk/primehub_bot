"""Walk product folders, upload images, and POST Firestore-shaped JSON."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rehan_bot.config import Settings

from .ai_enricher import ProductEnrichment, enrich_product, fallback_enrichment
from .catalog_state import CatalogState, TrackedImage, TrackedProduct, folder_key
from .categories import match_category
from .client import PrimeHubAPIError, PrimeHubClient
from .firestore_sync import FirestoreStore, store_from_settings
from .folder_parser import (
    ParsedFolder,
    discover_product_folders,
    list_image_files,
    parse_product_folder,
)
from .image_pipeline import process_product_image
from .pacing import emit, folder_delay_seconds, folder_label, image_delay_seconds, pause
from .payload import build_product_payload, card_base_title
from .price_buckets import LiveBucket
from .r2 import R2Uploader
from .sizes import should_use_adult_allsize

logger = logging.getLogger("rehan_bot.primehub.uploader")


@dataclass
class ProductPreview:
    folder: str
    parsed: dict[str, Any]
    payload: dict[str, Any]
    images: list[dict[str, Any]]
    cached_images: int
    pending_uploads: int
    enrichment: dict[str, Any] = field(default_factory=dict)


@dataclass
class UploadReport:
    dry_run: bool
    previews: list[ProductPreview] = field(default_factory=list)
    created: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "count": len(self.previews),
            "products": [
                {
                    "folder": item.folder,
                    "parsed": item.parsed,
                    "images": item.images,
                    "cached_images": item.cached_images,
                    "pending_uploads": item.pending_uploads,
                    "enrichment": item.enrichment,
                    "payload": item.payload,
                }
                for item in self.previews
            ],
            "created": self.created,
            "errors": self.errors,
        }


def _work_folders(
    root: Path,
    settings: Settings,
    *,
    limit: int | None = None,
    force: bool = False,
) -> list[Path]:
    """Return NEW/MODIFIED product folders, skipping catalog_state matches.

    ``--limit N`` means process N work items, not "stop after scanning N folders".
    """
    discovered = discover_product_folders(Path(root))
    memory = CatalogState(settings.catalog_state_path)
    selected: list[Path] = []
    max_work = None if limit is None else max(0, int(limit))
    if max_work == 0:
        return []
    for folder in discovered:
        files = list_image_files(folder, limit=None)
        if memory.inspect(folder, files).is_skip and not force:
            logger.info("Up-to-date: %s", folder.name)
            continue
        selected.append(folder)
        if max_work is not None and len(selected) >= max_work:
            break
    return selected


def _client_from_settings(
    settings: Settings, base_url: str | None = None
) -> PrimeHubClient | FirestoreStore | None:
    direct = store_from_settings(settings)
    if direct is not None:
        return direct
    if not settings.primehub_auth_key:
        return None
    return PrimeHubClient(
        (base_url or settings.primehub_base_url),
        settings.primehub_auth_key,
        protection_bypass=str(getattr(settings, "vercel_protection_bypass", "") or ""),
        write_delay_seconds=0.0,
    )


def _image_store_from_settings(settings: Settings) -> R2Uploader | None:
    return R2Uploader.from_settings(settings)


def _enrich_copy(
    parsed: ParsedFolder, settings: Settings, first_webp: bytes | None
) -> ProductEnrichment:
    first = parsed.image_files[0] if parsed.image_files else None
    if first is None:
        return fallback_enrichment(parsed)
    try:
        return enrich_product(
            parsed, settings, image_path=first, image_bytes=first_webp
        )
    except Exception as exc:
        logger.warning("AI enricher failed, using folder copy: %s", exc)
        return fallback_enrichment(parsed)


def _parsed_summary(parsed: ParsedFolder) -> dict[str, Any]:
    return {
        "folder_name": parsed.folder_name,
        "stem": parsed.stem,
        "title": parsed.title,
        "original_price": parsed.original_price,
        "size_token": parsed.size.token if parsed.size else "",
        "size_label": parsed.size_label,
        "category_hint": parsed.category_hint,
        "wholesale": parsed.wholesale,
        "image_files": [path.name for path in parsed.image_files],
    }


def upload_products(
    root: Path,
    settings: Settings,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    fetch_live_metadata: bool = True,
    base_url: str | None = None,
    force: bool = False,
    max_images: int | None = None,
) -> UploadReport:
    folders = _work_folders(Path(root), settings, limit=limit, force=force)
    gallery_limit = settings.split_image_limit(max_images)

    report = UploadReport(dry_run=dry_run)
    memory = CatalogState(settings.catalog_state_path)
    client = _client_from_settings(settings, base_url=base_url)
    blob_store = _image_store_from_settings(settings)

    live_titles: list[str] = []
    live_buckets: list[LiveBucket] = []
    if fetch_live_metadata and client is not None and not dry_run:
        try:
            metadata = client.fetch_metadata()
            live_titles = client.live_categories(metadata)
            live_buckets = client.live_buckets(metadata)
        except PrimeHubAPIError as exc:
            logger.warning("Live metadata unavailable, using folder hints: %s", exc)
    elif fetch_live_metadata and client is not None and dry_run:
        try:
            metadata = client.fetch_metadata()
            live_titles = client.live_categories(metadata)
            live_buckets = client.live_buckets(metadata)
        except PrimeHubAPIError:
            live_titles, live_buckets = [], []

    total = len(folders)
    image_wait = 0.0 if dry_run else image_delay_seconds(settings)
    folder_wait = folder_delay_seconds(settings, dry_run=dry_run)
    if total:
        emit(f"Human-paced upload: {total} folder(s) to process.")

    for index, folder in enumerate(folders, start=1):
        emit(f"[Folder {index}/{total}] Processing: {folder_label(folder)}")
        try:
            parsed = parse_product_folder(
                folder, default_category=settings.primehub_default_category
            )
            category = match_category(
                parsed.category_hint,
                live_titles,
                default=settings.primehub_default_category,
            )
            image_notes: list[dict[str, Any]] = []
            urls: list[str] = []
            cached = 0
            pending = 0
            first_webp: bytes | None = None
            files = list_image_files(folder, limit=None)
            delta = memory.inspect(folder, files)
            recorded = memory.get(folder)
            split_already = bool(recorded and recorded.is_split)
            to_process = (
                list(files)
                if force or not split_already
                else list(delta.new_files)
            )
            if gallery_limit is not None:
                to_process = to_process[:gallery_limit]
            if (
                recorded
                and recorded.product_id
                and not recorded.is_split
                and not dry_run
                and client is not None
                and hasattr(client, "delete_product")
            ):
                emit(f"  removing merged product {recorded.product_id}")
                client.delete_product(recorded.product_id)
            tracked_by_name = {item.name: item for item in (recorded.images if recorded else [])}
            last_payload: dict[str, Any] = {}
            for image_index, image in enumerate(to_process):
                set_no = files.index(image) + 1 if image in files else image_index + 1
                emit(f"  Photo {set_no}/{len(files)}: {image.name}")
                processed = process_product_image(image, folder=folder)
                if first_webp is None:
                    first_webp = processed.data
                if blob_store is None:
                    pending += 1
                    image_notes.append(
                        {
                            "file": image.name,
                            "url": "",
                            "source": "pending-no-key",
                            **processed.compressed.summary(),
                        }
                    )
                    if image_index + 1 < len(to_process) and folder_wait:
                        pause(folder_wait)
                    continue
                url, from_cache = blob_store.resolve_processed(
                    image,
                    processed.data,
                    processed.filename,
                    upload=not dry_run,
                    refresh=force,
                )
                if from_cache:
                    cached += 1
                    source = "cache-webp"
                elif url:
                    source = "uploaded-webp"
                else:
                    pending += 1
                    source = "pending"
                if recorded and recorded.description:
                    description = recorded.description
                    base_title = card_base_title(recorded.title or parsed.title)
                else:
                    enrichment = _enrich_copy(parsed, settings, first_webp)
                    description = enrichment.description
                    base_title = enrichment.title
                payload = build_product_payload(
                    parsed,
                    [url] if url else [],
                    live_category=category,
                    live_buckets=live_buckets,
                    title=base_title,
                    description=description,
                    max_images=1,
                    set_index=set_no,
                    all_adult_sizes=should_use_adult_allsize(
                        parsed.folder_name, parsed.folder
                    ),
                )
                last_payload = payload
                image_notes.append(
                    {
                        "file": image.name,
                        "url": url,
                        "source": source,
                        "title": payload.get("title"),
                        "slug": payload.get("slug"),
                        **processed.compressed.summary(),
                    }
                )
                if dry_run or not url:
                    if image_index + 1 < len(to_process) and folder_wait:
                        pause(folder_wait)
                    continue
                if client is None:
                    raise PrimeHubAPIError("PRIMEHUB_API_KEY is not configured")
                prior = tracked_by_name.get(image.name)
                product_id = str((prior.product_id if prior else "") or "")
                try:
                    created = client.create_product(payload, product_id=product_id)
                except TypeError:
                    created = client.create_product(payload)
                status = int(created.get("http_status") or 200)
                if status not in (200, 201):
                    raise PrimeHubAPIError(f"Product write -> HTTP {status}")
                tracked = TrackedImage.from_file(
                    image,
                    url=url,
                    product_id=str(created.get("id") or ""),
                    slug=str(created.get("slug") or payload.get("slug") or ""),
                    title=str(payload.get("title") or ""),
                )
                tracked_by_name[image.name] = tracked
                ordered = [
                    tracked_by_name[path.name]
                    for path in files
                    if path.name in tracked_by_name
                ]
                recorded = TrackedProduct(
                    folder=folder_key(folder),
                    folder_name=parsed.folder_name,
                    slug=str(ordered[0].slug if ordered else payload.get("slug") or ""),
                    product_id=str(ordered[0].product_id if ordered else created.get("id") or ""),
                    title=str(ordered[0].title if ordered else payload.get("title") or parsed.title),
                    description=description,
                    category=category,
                    images=ordered,
                )
                memory.remember(recorded)
                report.created.append(created)
                image_notes[-1]["product_id"] = tracked.product_id
                emit(
                    f"  OK HTTP {status} Set {set_no} id={tracked.product_id or '-'} — saved catalog_state.json"
                )
                if image_index + 1 < len(to_process) and folder_wait:
                    emit(f"  waiting {folder_wait:.1f}s before next photo")
                    pause(folder_wait)

            report.previews.append(
                ProductPreview(
                    folder=str(folder),
                    parsed=_parsed_summary(parsed),
                    payload=last_payload,
                    images=image_notes,
                    cached_images=cached,
                    pending_uploads=pending,
                    enrichment={"title": last_payload.get("title", "")},
                )
            )
        except Exception as exc:
            message = f"{folder}: {exc}"
            logger.warning("Product upload failed: %s", message)
            emit(f"  warning: {exc} — saving progress and continuing")
            report.errors.append(message)
        if index < total and folder_wait:
            emit(f"  waiting {folder_wait:.1f}s before next folder")
            pause(folder_wait)

    return report


def dumps_report(report: UploadReport) -> str:
    return json.dumps(report.to_json(), ensure_ascii=False, indent=2)
