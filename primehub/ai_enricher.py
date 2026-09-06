"""Vision-powered PrimeHub title and description (Gemini 2.0 Flash, then OpenAI)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rehan_bot.ai.errors import ProviderError, ProviderErrorKind
from rehan_bot.ai.key_pool import RoundRobinKeyPool
from rehan_bot.ai.parsing import gemini_text, json_object, openai_output_text
from rehan_bot.ai.transport import JsonTransport
from rehan_bot.ai.vision import VisionImage, VisionPreprocessor
from rehan_bot.config import Settings

from .folder_parser import ParsedFolder

logger = logging.getLogger("rehan_bot.primehub.ai_enricher")

# gemini-2.0-flash was retired; Google now routes that class to 3.6 Flash.
GEMINI_FLASH_MODEL = "gemini-3.6-flash"
_ENRICHER_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class ProductEnrichment:
    """Sales copy extracted from the first product photo."""

    title: str
    description: str
    colors: tuple[str, ...] = ()
    finish: str = ""
    pattern: str = ""
    occasion: str = ""
    source: str = "fallback"

    def summary(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "colors": list(self.colors),
            "finish": self.finish,
            "pattern": self.pattern,
            "occasion": self.occasion,
            "source": self.source,
        }


def fallback_enrichment(parsed: ParsedFolder) -> ProductEnrichment:
    """Folder-only copy when vision is unavailable."""
    category = parsed.category_hint or "Bangles"
    occasion = "Partywear, Eid, and daily wear"
    description = (
        f"{parsed.title} — boxed glass bangles ready for gifting and resale.\n\n"
        f"• Material: {category}\n"
        f"• Box Packaging: {parsed.stem} deal, stocked for fast dispatch\n"
        f"• Occasions: {occasion}"
    )
    return ProductEnrichment(
        title=parsed.title,
        description=description,
        colors=(),
        finish="",
        pattern="",
        occasion=occasion,
        source="fallback",
    )


def build_enrichment_prompt(parsed: ParsedFolder) -> str:
    size = parsed.size_label or "not specified"
    return (
        "You are a Pakistani jewelry merchandiser writing PrimeHub product copy. "
        "Inspect the bangle photo and return exactly one JSON object, no markdown.\n"
        "Extract:\n"
        '- colors: short shopper phrases such as "Multicolor", "Velvet finish", '
        '"Gold shimmer", "Bridal mix"\n'
        "- finish: surface look (velvet, glossy, matte, metallic)\n"
        "- pattern: design notes (plain, mixed, kundan-style, floral)\n"
        '- occasion: Partywear, Eid, Daily wear, Bridal, or a short mix\n'
        "Then write:\n"
        "- title: attractive sales title under 80 characters. Example: "
        '"Multicolor Velvet Glass Bangles Box - 20 Dozen Partywear Deal"\n'
        "- description: one short hook sentence, then bullet points for "
        "Material, Box Packaging, Colors, and Occasions. Do not include a size guide.\n"
        "Keep the folder quantity, category, and price honest. Do not invent a "
        "different dozen count or material.\n"
        f"Folder stem: {parsed.stem}\n"
        f"Folder title: {parsed.title}\n"
        f"Category: {parsed.category_hint}\n"
        f"Price PKR: {parsed.original_price}\n"
        f"Size: {size}\n"
        "JSON keys: colors, finish, pattern, occasion, title, description."
    )


def parse_enrichment(
    raw: dict[str, Any], parsed: ParsedFolder, source: str
) -> ProductEnrichment:
    """Normalize a model JSON object onto ``ProductEnrichment``."""
    fallback = fallback_enrichment(parsed)
    colors = raw.get("colors") or []
    if isinstance(colors, str):
        color_list = [part.strip() for part in colors.split(",") if part.strip()]
    else:
        color_list = [str(item).strip() for item in colors if str(item).strip()]
    title = str(raw.get("title") or "").strip() or fallback.title
    if len(title) > 90:
        title = title[:87].rstrip(" -|,") + "…"
    description = str(raw.get("description") or "").strip() or fallback.description
    return ProductEnrichment(
        title=title,
        description=description,
        colors=tuple(color_list),
        finish=str(raw.get("finish") or "").strip(),
        pattern=str(raw.get("pattern") or "").strip(),
        occasion=str(raw.get("occasion") or "").strip(),
        source=source,
    )


class ProductVisionEnricher:
    """Gemini 2.0 Flash first, then the configured Gemini model, then OpenAI."""

    def __init__(
        self,
        gemini_keys: tuple[str, ...] = (),
        openai_keys: tuple[str, ...] = (),
        gemini_model: str = GEMINI_FLASH_MODEL,
        fallback_gemini_model: str = "",
        openai_model: str = "gpt-4.1-mini",
        timeout_seconds: float = _ENRICHER_TIMEOUT_SECONDS,
        transport: JsonTransport | None = None,
    ) -> None:
        self._gemini_keys = RoundRobinKeyPool(gemini_keys) if gemini_keys else None
        self._openai_keys = RoundRobinKeyPool(openai_keys) if openai_keys else None
        models = [gemini_model]
        if fallback_gemini_model and fallback_gemini_model != gemini_model:
            models.append(fallback_gemini_model)
        self._gemini_models = tuple(models)
        self._openai_model = openai_model
        self._transport = transport or JsonTransport(timeout_seconds)
        self._preprocessor = VisionPreprocessor(max_dimension=1200, quality=80)

    @classmethod
    def from_settings(cls, settings: Settings) -> ProductVisionEnricher:
        configured = str(getattr(settings, "gemini_model", "") or "").strip()
        return cls(
            gemini_keys=settings.gemini_api_key_pool,
            openai_keys=settings.openai_api_key_pool,
            gemini_model=GEMINI_FLASH_MODEL,
            fallback_gemini_model=configured,
            openai_model=str(getattr(settings, "openai_model", "") or "gpt-4.1-mini"),
            timeout_seconds=_ENRICHER_TIMEOUT_SECONDS,
        )

    def enrich(
        self,
        image_path: Path,
        parsed: ParsedFolder,
        image_bytes: bytes | None = None,
    ) -> ProductEnrichment:
        """Inspect the first photo. On any failure, return folder-based copy."""
        fallback = fallback_enrichment(parsed)
        try:
            raw = image_bytes if image_bytes else Path(image_path).read_bytes()
            vision = self._preprocessor.prepare(raw)
        except Exception as exc:
            logger.warning("Vision preprocess failed for %s: %s", image_path, exc)
            return fallback

        prompt = build_enrichment_prompt(parsed)
        last_error = ""
        if self._gemini_keys is not None:
            for model in self._gemini_models:
                for attempt in range(2):
                    try:
                        data = self._gemini(vision, prompt, model)
                        return parse_enrichment(data, parsed, f"gemini:{model}")
                    except Exception as exc:
                        last_error = str(exc)
                        logger.warning(
                            "Gemini enricher (%s) failed (attempt %s): %s",
                            model,
                            attempt + 1,
                            exc,
                        )
                        if "invalid_request" in last_error:
                            break
        if self._openai_keys is not None:
            try:
                data = self._openai(vision, prompt)
                return parse_enrichment(data, parsed, f"openai:{self._openai_model}")
            except Exception as exc:
                last_error = str(exc)
                logger.warning("OpenAI enricher failed: %s", exc)
        if last_error:
            logger.warning("Using folder fallback copy: %s", last_error)
        return fallback

    def _gemini(self, image: VisionImage, prompt: str, model: str) -> dict[str, Any]:
        assert self._gemini_keys is not None
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": image.mime_type,
                                "data": image.base64_data,
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.4,
            },
        }
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
        )
        last_error: ProviderError | None = None
        for state in self._gemini_keys.round_keys():
            try:
                data = self._transport.post(
                    "gemini",
                    url,
                    {
                        "x-goog-api-key": state.key,
                        "Content-Type": "application/json",
                    },
                    payload,
                )
                parsed = json_object(gemini_text(data))
                self._gemini_keys.success(state)
                return parsed
            except ProviderError as exc:
                last_error = exc
                self._gemini_keys.failure(state, exc.kind)
                if exc.kind in {
                    ProviderErrorKind.INVALID_REQUEST,
                    ProviderErrorKind.TIMEOUT,
                    ProviderErrorKind.UNAVAILABLE,
                }:
                    break
            except Exception as exc:
                last_error = ProviderError(
                    ProviderErrorKind.UNKNOWN, str(exc), "gemini"
                )
                self._gemini_keys.failure(state, last_error.kind)
        raise last_error or ProviderError(
            ProviderErrorKind.UNAVAILABLE, "Gemini enricher had no keys", "gemini"
        )

    def _openai(self, image: VisionImage, prompt: str) -> dict[str, Any]:
        assert self._openai_keys is not None
        payload = {
            "model": self._openai_model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_image",
                            "image_url": (
                                f"data:{image.mime_type};base64,{image.base64_data}"
                            ),
                            "detail": "low",
                        },
                    ],
                }
            ],
            "text": {"format": {"type": "json_object"}},
        }
        last_error: ProviderError | None = None
        for state in self._openai_keys.round_keys():
            try:
                data = self._transport.post(
                    "openai",
                    "https://api.openai.com/v1/responses",
                    {
                        "Authorization": f"Bearer {state.key}",
                        "Content-Type": "application/json",
                    },
                    payload,
                )
                parsed = json_object(openai_output_text(data))
                self._openai_keys.success(state)
                return parsed
            except ProviderError as exc:
                last_error = exc
                self._openai_keys.failure(state, exc.kind)
                if exc.kind in {
                    ProviderErrorKind.INVALID_REQUEST,
                    ProviderErrorKind.TIMEOUT,
                    ProviderErrorKind.UNAVAILABLE,
                }:
                    break
            except Exception as exc:
                last_error = ProviderError(
                    ProviderErrorKind.UNKNOWN, str(exc), "openai"
                )
                self._openai_keys.failure(state, last_error.kind)
        raise last_error or ProviderError(
            ProviderErrorKind.UNAVAILABLE, "OpenAI enricher had no keys", "openai"
        )


def enrich_product(
    parsed: ParsedFolder,
    settings: Settings,
    image_path: Path | None = None,
    image_bytes: bytes | None = None,
) -> ProductEnrichment:
    """Public helper used by the uploader."""
    first = image_path or (parsed.image_files[0] if parsed.image_files else None)
    if first is None:
        return fallback_enrichment(parsed)
    return ProductVisionEnricher.from_settings(settings).enrich(
        first, parsed, image_bytes=image_bytes
    )
