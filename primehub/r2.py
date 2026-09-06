"""Cloudflare R2 uploads via the S3 API (boto3). New photos only; ImgBB URLs stay as-is."""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

from rehan_bot.config import Settings

from .cdn import is_r2_public_url
from .image_cache import ImageUploadCache
from .webp import WEBP_CACHE_VARIANT

logger = logging.getLogger("rehan_bot.primehub.r2")

_SAFE_STEM = re.compile(r"[^a-zA-Z0-9._-]+")


class R2Error(RuntimeError):
    """Raised when a Cloudflare R2 upload cannot complete."""


def object_key(filename: str, data: bytes) -> str:
    stem = _SAFE_STEM.sub("-", Path(filename or "image.webp").stem).strip("-") or "image"
    digest = hashlib.sha256(data).hexdigest()[:12]
    return f"products/{stem}-{digest}.webp"


def public_object_url(public_base: str, key: str) -> str:
    return f"{public_base.rstrip('/')}/{key.lstrip('/')}"


class R2Uploader:
    """Put processed WebP bytes in the PrimeHub R2 bucket and return the public URL."""

    def __init__(
        self,
        *,
        account_id: str,
        bucket: str,
        public_base: str,
        access_key_id: str,
        secret_access_key: str,
        cache: ImageUploadCache | None = None,
    ) -> None:
        account = (account_id or "").strip()
        self._bucket = (bucket or "").strip()
        self._public_base = (public_base or "").rstrip("/")
        access = (access_key_id or "").strip()
        secret = (secret_access_key or "").strip()
        if not all([account, self._bucket, self._public_base, access, secret]):
            raise R2Error(
                "Cloudflare R2 is not configured. Set R2_ACCOUNT_ID, R2_BUCKET_NAME, "
                "R2_PUBLIC_BASE_URL, R2_ACCESS_KEY_ID, and R2_SECRET_ACCESS_KEY."
            )
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:
            raise R2Error("boto3 is not installed. Run: pip install boto3") from exc
        self._client = boto3.client(
            "s3",
            endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
            aws_access_key_id=access,
            aws_secret_access_key=secret,
            region_name="auto",
            config=Config(signature_version="s3v4"),
        )
        self._cache = cache or ImageUploadCache()

    @classmethod
    def from_settings(cls, settings: Settings) -> R2Uploader | None:
        if not getattr(settings, "r2_is_configured", False):
            return None
        return cls(
            account_id=settings.r2_account_id,
            bucket=settings.r2_bucket_name,
            public_base=settings.r2_public_base_url,
            access_key_id=settings.r2_access_key_id,
            secret_access_key=settings.r2_secret_access_key,
            cache=ImageUploadCache(settings.imgbb_cache_path),
        )

    def resolve_processed(
        self,
        image_path: Path,
        data: bytes,
        filename: str,
        *,
        upload: bool = True,
        refresh: bool = False,
    ) -> tuple[str, bool]:
        name = filename or image_path.name
        cached = "" if refresh else (
            self._cache.lookup_bytes(data, variant=WEBP_CACHE_VARIANT) or ""
        )
        if cached and is_r2_public_url(cached, self._public_base):
            logger.info("R2 cache hit for %s", name)
            return cached, True
        if not upload:
            return "", False
        key = object_key(name, data)
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType="image/webp",
                CacheControl="public, max-age=31536000, immutable",
            )
        except Exception as exc:
            raise R2Error(f"R2 put_object failed for {name}: {exc}") from exc
        url = public_object_url(self._public_base, key)
        self._cache.remember_bytes(
            data,
            url,
            source_path=image_path,
            name=Path(name).with_suffix(".webp").name,
            variant=WEBP_CACHE_VARIANT,
        )
        logger.info("R2 uploaded %s -> %s (%s bytes)", name, url, len(data))
        return url, False
