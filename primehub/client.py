"""Authenticated PrimeHub store API client (metadata + product create)."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urljoin

from .price_buckets import LiveBucket


class PrimeHubAPIError(RuntimeError):
    """Raised when the store API rejects a request."""


class PrimeHubClient:
    """Talk to ``/api/v1/store/*`` with the same ``x-api-key`` as metadata GET."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 30.0,
        protection_bypass: str = "",
        write_delay_seconds: float = 0.0,
    ) -> None:
        self._base_url = (base_url or "").rstrip("/") + "/"
        self._api_key = (api_key or "").strip()
        self._timeout_seconds = timeout_seconds
        self._protection_bypass = (protection_bypass or "").strip()
        self._write_delay_seconds = max(0.0, float(write_delay_seconds))

    def fetch_metadata(self) -> dict[str, Any]:
        return self._request("GET", "api/v1/store/metadata")

    def create_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = dict(payload)
        body.pop("priceBucketLabels", None)
        body.pop("sourceFolder", None)
        result = self._request("POST", "api/v1/store/products", body)
        status = int(result.get("http_status") or 200)
        if status not in (200, 201):
            raise PrimeHubAPIError(
                f"POST {urljoin(self._base_url, 'api/v1/store/products')} "
                f"-> HTTP {status}: expected 200 or 201"
            )
        if self._write_delay_seconds:
            time.sleep(self._write_delay_seconds)
        return result

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

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._api_key:
            raise PrimeHubAPIError(
                "PRIMEHUB_API_KEY is empty. Set it (or NEXTJS_SERVICE_TOKEN) in .env."
            )
        url = urljoin(self._base_url, path.lstrip("/"))
        headers = {
            "Accept": "application/json",
            "x-api-key": self._api_key,
        }
        if self._protection_bypass:
            headers["x-vercel-protection-bypass"] = self._protection_bypass
            headers["x-vercel-set-bypass-cookie"] = "true"
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                status = int(getattr(response, "status", 200) or 200)
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            if exc.code == 401 and "Protected deployment" in detail:
                raise PrimeHubAPIError(
                    f"{method} {url} -> HTTP 401: Vercel Deployment Protection is on. "
                    "Disable SSO on this preview, or set VERCEL_PROTECTION_BYPASS "
                    "(Protection Bypass for Automation) in .env."
                ) from exc
            raise PrimeHubAPIError(f"{method} {url} -> HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise PrimeHubAPIError(f"{method} {url} unavailable: {exc}") from exc

        if not raw.strip():
            return {"http_status": status}
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and parsed.get("success") is False:
            error = parsed.get("error") or {}
            raise PrimeHubAPIError(str(error.get("message") or parsed))
        if isinstance(parsed, dict):
            parsed.setdefault("http_status", status)
            return parsed
        return {"data": parsed, "http_status": status}
