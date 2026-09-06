"""Sequential ImgBB uploader with hash cache, retry, and multi-key rotation."""
from __future__ import annotations

import base64
import io
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

from PIL import Image

from rehan_bot.ai.errors import ProviderErrorKind, classify_status
from rehan_bot.ai.key_pool import RoundRobinKeyPool

from .image_cache import ImageUploadCache
from .webp import WEBP_CACHE_VARIANT, CompressedImage, compress_to_webp

logger = logging.getLogger("rehan_bot.primehub.imgbb")

IMGBB_ENDPOINT = "https://api.imgbb.com/1/upload"
IMGBB_JPEG_VARIANT = "ibb-jpeg-permanent-v1"
_CDN_PREFIX = "https://i.ibb.co/"
_VIEWER = re.compile(r"^https?://ibb\.co/", re.I)
_TOKEN_QUERY = re.compile(
    r"[?&](expiration|expires|exp|token|signature|sig|X-Goog-Expires)=",
    re.I,
)
_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


def is_permanent_cdn_url(url: str) -> bool:
    """True only for a raw ``https://i.ibb.co/.../file.ext`` link."""
    text = (url or "").strip()
    if not text or _TOKEN_QUERY.search(text) or _VIEWER.match(text):
        return False
    if "?" in text or "#" in text:
        return False
    return text.startswith(_CDN_PREFIX) and "/" in text[len(_CDN_PREFIX) :]


def permanent_cdn_url(body: dict) -> str:
    """Prefer ``display_url`` / ``data.image.url`` when they are i.ibb.co CDN files."""
    data = (body.get("data") or {}) if isinstance(body, dict) else {}
    if not isinstance(data, dict):
        return ""
    image = data.get("image") if isinstance(data.get("image"), dict) else {}
    candidates = (
        data.get("display_url"),
        (image or {}).get("url"),
        data.get("url"),
        (image or {}).get("display_url"),
    )
    for item in candidates:
        url = str(item or "").strip()
        if is_permanent_cdn_url(url):
            return url
    return ""


def probe_cdn_url(url: str, *, timeout: float = 20.0, attempts: int = 3) -> bool:
    """Cold-fetch like a phone: reject viewer pages, tokens, and ImgBB 404 placeholders."""
    if not is_permanent_cdn_url(url):
        return False
    last_error: Exception | None = None
    for attempt in range(max(1, attempts)):
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "User-Agent": _MOBILE_UA,
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = int(getattr(response, "status", 200) or 200)
                content_type = str(response.headers.get("Content-Type") or "")
                head = response.read(32)
        except urllib.error.HTTPError as exc:
            last_error = exc
            logger.warning("CDN probe HTTP %s for %s", exc.code, url)
        except urllib.error.URLError as exc:
            last_error = exc
            logger.warning("CDN probe network error for %s: %s", url, exc)
        else:
            if status == 200 and _looks_like_image(content_type, head):
                return True
            last_error = ImgBBError(f"not a live image ({status} {content_type})")
        if attempt + 1 < attempts:
            time.sleep(1.0)
    if last_error:
        logger.warning("CDN probe failed for %s: %s", url, last_error)
    return False


def _looks_like_image(content_type: str, head: bytes) -> bool:
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime and not mime.startswith("image/"):
        return False
    return (
        head.startswith(b"\xff\xd8\xff")
        or head.startswith(b"\x89PNG")
        or head.startswith(b"GIF8")
        or (head.startswith(b"RIFF") and b"WEBP" in head[:16])
    )


def jpeg_for_imgbb(data: bytes, filename: str = "") -> tuple[bytes, str]:
    """ImgBB WebP files often 404 later; upload JPEG for a stable CDN object."""
    image = Image.open(io.BytesIO(data)).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=88, optimize=True)
    stem = Path(filename or "image.jpg").stem or "image"
    return buffer.getvalue(), f"{stem}.jpg"


class ImgBBError(RuntimeError):
    """Raised when every ImgBB key failed to upload a file."""


class ImgBBUploader:
    """Upload images one-by-one; reuse cached URLs whenever the bytes match."""

    def __init__(
        self,
        api_keys: tuple[str, ...] | list[str],
        cache: ImageUploadCache | None = None,
        delay_seconds: float = 1.2,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        verify_live: Callable[[str], bool] | None = None,
    ) -> None:
        keys = tuple(key.strip() for key in api_keys if key and str(key).strip())
        if not keys:
            raise ImgBBError(
                "No ImgBB API keys configured. Set IMGBB_API_KEY or IMGBB_API_KEYS."
            )
        self._pool = RoundRobinKeyPool(keys)
        self._cache = cache or ImageUploadCache()
        self._delay_seconds = max(0.0, delay_seconds)
        self._timeout_seconds = timeout_seconds
        self._max_retries = max(1, max_retries)
        self._last_network_at = 0.0
        self._verify_live = verify_live or probe_cdn_url

    def resolve_url(
        self, image_path: Path, *, upload: bool = True, refresh: bool = False
    ) -> tuple[str, bool]:
        """Return ``(url, from_cache)`` for the original file bytes."""
        cached = "" if refresh else (self._cache.lookup(image_path) or "")
        if cached and self._accept_live(cached):
            logger.info("ImgBB cache hit for %s", image_path.name)
            return cached, True
        if not upload:
            return "", False
        url = self._upload_with_retry(image_path)
        url = self._require_live(url, image_path.name)
        self._cache.remember(image_path, url)
        return url, False

    def resolve_optimized(
        self, image_path: Path, *, upload: bool = True
    ) -> tuple[str, bool, CompressedImage]:
        """Compress to WebP, then reuse or upload the optimized bytes."""
        compressed = compress_to_webp(image_path)
        cached = self._cache.lookup_bytes(
            compressed.data, variant=WEBP_CACHE_VARIANT
        )
        if cached:
            logger.info(
                "ImgBB WebP cache hit for %s (%s bytes)",
                image_path.name,
                compressed.size_bytes,
            )
            return cached, True, compressed
        if not upload:
            return "", False, compressed
        url = self._upload_with_retry(
            image_path, data=compressed.data, filename=compressed.filename
        )
        self._cache.remember_bytes(
            compressed.data,
            url,
            source_path=image_path,
            name=compressed.filename,
            variant=WEBP_CACHE_VARIANT,
        )
        logger.info(
            "ImgBB uploaded WebP %s (%s bytes, q%s, %sx%s)",
            compressed.filename,
            compressed.size_bytes,
            compressed.quality,
            compressed.width,
            compressed.height,
        )
        return url, False, compressed

    def resolve_processed(
        self,
        image_path: Path,
        data: bytes,
        filename: str,
        *,
        upload: bool = True,
        refresh: bool = False,
    ) -> tuple[str, bool]:
        """Upload processed pixels as a permanent JPEG CDN object."""
        cached = ""
        if not refresh:
            cached = (
                self._cache.lookup_bytes(data, variant=IMGBB_JPEG_VARIANT)
                or self._cache.lookup_bytes(data, variant=WEBP_CACHE_VARIANT)
                or ""
            )
        if cached and self._accept_live(cached):
            logger.info("ImgBB processed cache hit for %s", filename or image_path.name)
            return cached, True
        if cached:
            logger.warning(
                "Cached ImgBB URL is dead or not a permanent CDN link; re-uploading %s",
                filename or image_path.name,
            )
        if not upload:
            return "", False
        jpeg, jpeg_name = jpeg_for_imgbb(data, filename or image_path.name)
        url = self._upload_with_retry(image_path, data=jpeg, filename=jpeg_name)
        url = self._require_live(url, jpeg_name)
        self._cache.remember_bytes(
            data,
            url,
            source_path=image_path,
            name=jpeg_name,
            variant=IMGBB_JPEG_VARIANT,
        )
        return url, False

    def resolve_many(
        self, image_paths: list[Path] | tuple[Path, ...], *, upload: bool = True
    ) -> list[str]:
        urls: list[str] = []
        for path in image_paths:
            url, _cached = self.resolve_url(path, upload=upload)
            if url:
                urls.append(url)
        return urls

    def _upload_with_retry(
        self,
        image_path: Path,
        data: bytes | None = None,
        filename: str = "",
    ) -> str:
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            for state in self._pool.iter_round():
                self._respect_rate_limit()
                try:
                    url = self._post(
                        image_path, state.key, data=data, filename=filename
                    )
                except ImgBBError as exc:
                    last_error = exc
                    kind = _classify_message(str(exc))
                    self._pool.failure(state, kind)
                    logger.warning(
                        "ImgBB key failed for %s (%s): %s",
                        image_path.name,
                        kind.value,
                        exc,
                    )
                    continue
                self._pool.success(state)
                return url
            time.sleep(min(4.0, 2**attempt))
        raise ImgBBError(
            f"ImgBB upload failed for {image_path.name}: {last_error}"
        )

    def _post(
        self,
        image_path: Path,
        api_key: str,
        data: bytes | None = None,
        filename: str = "",
    ) -> str:
        raw = data if data is not None else image_path.read_bytes()
        name = (filename or image_path.name).rsplit(".", 1)[0]
        # Permanent lifetime: do not send `expiration` (0 or omitted = never expire).
        payload = urllib.parse.urlencode(
            {
                "key": api_key,
                "name": name,
                "image": base64.b64encode(raw).decode("ascii"),
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            IMGBB_ENDPOINT,
            data=payload,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise ImgBBError(f"HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ImgBBError(f"network error: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ImgBBError("ImgBB returned non-JSON") from exc

        url = permanent_cdn_url(body)
        if not url:
            raise ImgBBError(
                f"ImgBB response missing permanent i.ibb.co URL: {body!r}"[:240]
            )
        return url

    def _accept_live(self, url: str) -> bool:
        return is_permanent_cdn_url(url) and bool(self._verify_live(url))

    def _require_live(self, url: str, name: str) -> str:
        if self._accept_live(url):
            return url
        raise ImgBBError(
            f"ImgBB returned a non-live or non-permanent URL for {name}: {url}"
        )

    def _respect_rate_limit(self) -> None:
        if self._delay_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_network_at
        remaining = self._delay_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_network_at = time.monotonic()


def _classify_message(message: str) -> ProviderErrorKind:
    lowered = message.lower()
    if "429" in lowered or "rate" in lowered:
        return ProviderErrorKind.RATE_LIMIT
    if "401" in lowered or "403" in lowered:
        return ProviderErrorKind.AUTHENTICATION
    if "timeout" in lowered:
        return ProviderErrorKind.TIMEOUT
    code = _http_code(message)
    if code is not None:
        return classify_status(code)
    return ProviderErrorKind.UNAVAILABLE


def _http_code(message: str) -> int | None:
    if not message.startswith("HTTP "):
        return None
    try:
        return int(message.split()[1].rstrip(":"))
    except (IndexError, ValueError):
        return None
