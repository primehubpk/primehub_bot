"""Write PrimeHub products straight to Firestore, bypassing the Vercel API."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

from rehan_bot.config import Settings

from .client import PrimeHubAPIError
from .price_buckets import LiveBucket

logger = logging.getLogger("rehan_bot.primehub.firestore_sync")

_DROP_FIELDS = {"priceBucketLabels", "sourceFolder", "http_status"}
_T = TypeVar("_T")


def _retry_quota(operation: str, fn: Callable[[], _T], attempts: int = 2) -> _T:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            text = str(exc)
            last = exc
            if "429" not in text and "RESOURCE_EXHAUSTED" not in text and "Quota exceeded" not in text:
                raise
            delay = min(2 ** attempt, 45)
            logger.warning("%s quota/retry in %ss (%s)", operation, delay, text[:180])
            time.sleep(delay)
    raise last if last else PrimeHubAPIError(f"{operation} failed.")


class FirestoreStore:
    """Duck-types PrimeHubClient using firebase-admin."""

    def __init__(self, db: Any) -> None:
        self._db = db

    def fetch_metadata(self) -> dict[str, Any]:
        def _read() -> dict[str, Any]:
            settings_snap = self._db.collection("settings").document("main").get()
            return settings_snap.to_dict() if settings_snap.exists else {}

        try:
            settings = _retry_quota("Firestore settings/main", _read)
        except Exception as exc:
            raise PrimeHubAPIError(f"Firestore metadata read failed: {exc}") from exc

        raw_buckets = settings.get("priceBuckets") if isinstance(settings, dict) else []
        price_buckets: list[dict[str, Any]] = []
        if isinstance(raw_buckets, list):
            for bucket in raw_buckets:
                if not isinstance(bucket, dict) or bucket.get("active") is False:
                    continue
                label = str(bucket.get("title") or bucket.get("label") or "").strip()
                ident = str(bucket.get("id") or label).strip()
                if not ident:
                    continue
                row: dict[str, Any] = {"id": ident, "label": label or ident}
                amount = bucket.get("amount", bucket.get("maxPrice"))
                if amount not in (None, ""):
                    row["maxPrice"] = int(amount)
                if bucket.get("type"):
                    row["type"] = str(bucket.get("type"))
                price_buckets.append(row)

        categories: list[str] = []
        try:
            for doc in self._db.collection("categories").stream():
                data = doc.to_dict() or {}
                if data.get("active") is False:
                    continue
                title = str(data.get("title") or "").strip()
                if title:
                    categories.append(title)
        except Exception as exc:
            logger.warning("Firestore categories read failed: %s", exc)

        return {
            "success": True,
            "storeName": str((settings or {}).get("storeName") or "PrimeHub"),
            "categories": categories,
            "priceBuckets": price_buckets,
        }

    def live_categories(self, metadata: dict[str, Any] | None = None) -> list[str]:
        data = metadata if metadata is not None else self.fetch_metadata()
        raw = data.get("categories") or []
        return [str(item).strip() for item in raw if str(item).strip()]

    def live_buckets(self, metadata: dict[str, Any] | None = None) -> list[LiveBucket]:
        data = metadata if metadata is not None else self.fetch_metadata()
        buckets: list[LiveBucket] = []
        for item in data.get("priceBuckets") or []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or item.get("title") or "").strip()
            ident = str(item.get("id") or label).strip()
            if not ident:
                continue
            max_price = item.get("maxPrice", item.get("amount"))
            buckets.append(
                LiveBucket(
                    id=ident,
                    label=label or ident,
                    max_price=int(max_price) if max_price not in (None, "") else None,
                )
            )
        return buckets

    def create_product(
        self, payload: dict[str, Any], product_id: str = ""
    ) -> dict[str, Any]:
        body = firestore_document(payload)
        slug = str(body.get("slug") or "").strip()
        if not slug:
            raise PrimeHubAPIError("Firestore product write needs a slug.")
        now = datetime.now(timezone.utc).isoformat()
        body["updatedAt"] = now
        collection = self._db.collection("products")

        doc_id = (product_id or "").strip()
        ref = collection.document(doc_id) if doc_id else collection.document()
        created = not bool(doc_id)
        if created:
            body.setdefault("createdAt", now)
        try:
            ref.set(body, merge=True)
        except Exception as exc:
            raise PrimeHubAPIError(
                f"Firestore products/{ref.id} set failed: {exc}"
            ) from exc
        logger.info(
            "Firestore %s products/%s slug=%s",
            "create" if created else "update",
            ref.id,
            slug,
        )
        return _ok(ref.id, slug, created)

    def get_product(self, product_id: str) -> dict[str, Any] | None:
        doc_id = (product_id or "").strip()
        if not doc_id:
            return None

        def _read() -> dict[str, Any] | None:
            snap = self._db.collection("products").document(doc_id).get()
            return snap.to_dict() if snap.exists else None

        try:
            return _retry_quota(f"Firestore products/{doc_id} get", _read)
        except Exception as exc:
            raise PrimeHubAPIError(f"Firestore products/{doc_id} get failed: {exc}") from exc

    def list_products(self) -> list[tuple[str, dict[str, Any]]]:
        def _read() -> list[tuple[str, dict[str, Any]]]:
            rows: list[tuple[str, dict[str, Any]]] = []
            for doc in self._db.collection("products").stream():
                rows.append((doc.id, doc.to_dict() or {}))
            return rows

        try:
            return _retry_quota("Firestore products list", _read)
        except Exception as exc:
            raise PrimeHubAPIError(f"Firestore products list failed: {exc}") from exc

    def update_fields(self, product_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Merge a few product fields (category repair) without rewriting images."""
        doc_id = (product_id or "").strip()
        if not doc_id:
            raise PrimeHubAPIError("Firestore update needs a product id.")
        body = {key: value for key, value in dict(fields).items() if value is not None}
        if not body:
            raise PrimeHubAPIError("Firestore update needs at least one field.")
        body["updatedAt"] = datetime.now(timezone.utc).isoformat()
        try:
            _retry_quota(
                f"Firestore products/{doc_id} update",
                lambda: self._db.collection("products").document(doc_id).set(body, merge=True),
            )
        except Exception as exc:
            raise PrimeHubAPIError(
                f"Firestore products/{doc_id} update failed: {exc}"
            ) from exc
        logger.info("Firestore update products/%s fields=%s", doc_id, sorted(body))
        return _ok(doc_id, str(body.get("slug") or ""), created=False)

    def delete_product(self, product_id: str) -> None:
        doc_id = (product_id or "").strip()
        if not doc_id:
            return
        try:
            self._db.collection("products").document(doc_id).delete()
        except Exception as exc:
            raise PrimeHubAPIError(
                f"Firestore products/{doc_id} delete failed: {exc}"
            ) from exc
        logger.info("Firestore delete products/%s", doc_id)


def firestore_document(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop API-only keys; keep the admin/storefront product fields."""
    return {
        key: value
        for key, value in dict(payload).items()
        if key not in _DROP_FIELDS and value is not None
    }


def _ok(doc_id: str, slug: str, created: bool) -> dict[str, Any]:
    return {
        "success": True,
        "id": doc_id,
        "slug": slug,
        "created": created,
        "http_status": 200,
    }


def store_from_settings(settings: Settings) -> FirestoreStore | None:
    db = _init_db(settings)
    if db is None:
        return None
    return FirestoreStore(db)


def _init_db(settings: Settings) -> Any | None:
    file_path = str(getattr(settings, "firebase_service_account_file", "") or "").strip()
    raw_key = str(getattr(settings, "firebase_service_account_key", "") or "").strip()
    if not file_path and not raw_key:
        return None

    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
    except ImportError as exc:
        raise PrimeHubAPIError(
            "firebase-admin is not installed. Run: pip install firebase-admin"
        ) from exc

    if firebase_admin._apps:
        return firestore.client()

    if file_path:
        path = Path(file_path)
        if not path.is_file():
            raise PrimeHubAPIError(f"FIREBASE_SERVICE_ACCOUNT_FILE not found: {path}")
        cred = credentials.Certificate(str(path))
    else:
        try:
            cred = credentials.Certificate(json.loads(raw_key))
        except json.JSONDecodeError as exc:
            raise PrimeHubAPIError("FIREBASE_SERVICE_ACCOUNT_KEY is not valid JSON.") from exc

    firebase_admin.initialize_app(cred)
    return firestore.client()
