"""Build the exact Firestore product document the admin ProductForm saves."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .folder_parser import ParsedFolder, size_guide_block
from .price_buckets import LiveBucket, resolve_bucket_ids, wanted_bucket_labels
from .sizes import (
    ADULT_SIZE_ORDER,
    PAIR_CHIP,
    SIZE_CHIPS,
    SizeChip,
    path_mentions_kids,
    resolve_size_chips,
    should_use_adult_allsize,
)

_SET_SUFFIX = re.compile(r"\s*[-–]\s*set\s+\d+\s*$", re.I)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower().strip())
    return slug.strip("-")


def card_base_title(title: str) -> str:
    """Strip a previous Set N suffix and a trailing Box / Deal marketing tail."""
    text = _SET_SUFFIX.sub("", (title or "").strip())
    text = re.sub(r"\s+Box\s*[-–].*$", "", text, flags=re.I)
    text = re.sub(r"\s+Box$", "", text, flags=re.I)
    return text.strip() or (title or "").strip()


def set_card_title(title: str, index: int) -> str:
    """Build a standalone card title such as ``20 Dozen Velvet Glass Bangles - Set 2``."""
    base = card_base_title(title)
    return f"{base} - Set {max(1, int(index))}"


def make_id() -> str:
    return datetime.now(timezone.utc).strftime("%H%M%S%f")[-8:]


def design_labels(count: int) -> list[str]:
    return [f"Design {index}" for index in range(1, max(0, count) + 1)]


def build_description(
    parsed: ParsedFolder,
    sales_copy: str = "",
    *,
    chips: tuple[SizeChip, ...] | list[SizeChip] | None = None,
) -> str:
    body = (sales_copy or "").strip()
    if not body:
        body = (
            f"{parsed.title}\n\n"
            "Stocked and published on the PrimeHub storefront."
        )
    if "Size guide" in body:
        return body
    resolved = (
        tuple(chips)
        if chips is not None
        else parsed.size_chips
    )
    if not resolved or all(chip.token == PAIR_CHIP.token for chip in resolved):
        return body
    kids = path_mentions_kids(parsed.folder_name, str(parsed.folder))
    guide = size_guide_block(parsed.size, kids=kids, chips=resolved)
    if not guide:
        return body
    return f"{body}\n\n{guide}".strip()


def _variant_matrix(
    chips: tuple[SizeChip, ...] | list[SizeChip],
    colors: list[tuple[str, str]],
    price: int,
    stock: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if chips:
        for color_name, url in colors:
            for chip in chips:
                rows.append(
                    {
                        "id": make_id(),
                        "label": f"{color_name} / {chip.label}",
                        "color": color_name,
                        "size": chip.label,
                        "stock": stock,
                        "imageUrl": url,
                        "sku": "",
                        "price": str(price),
                        "salePrice": "",
                        "active": True,
                    }
                )
        return rows
    for color_name, url in colors:
        rows.append(
            {
                "id": make_id(),
                "label": color_name,
                "color": color_name,
                "size": "",
                "stock": stock,
                "imageUrl": url,
                "sku": "",
                "price": str(price),
                "salePrice": "",
                "active": True,
            }
        )
    return rows


def build_product_payload(
    parsed: ParsedFolder,
    images: list[str],
    *,
    live_category: str = "",
    live_buckets: list[LiveBucket] | tuple[LiveBucket, ...] = (),
    stock: int = 30,  # root + every variantMatrix row (admin ProductsManager)
    published: bool = True,
    featured: bool = True,
    now: datetime | None = None,
    title: str | None = None,
    description: str | None = None,
    max_images: int | None = None,
    set_index: int | None = None,
    all_adult_sizes: bool = False,
    design_variants: bool | None = None,
    hero_cover: bool = False,
) -> dict[str, Any]:
    """Return the document ``useProductsManager.save()`` writes on create."""
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    gallery = [url for url in images if url]
    if max_images is not None:
        gallery = gallery[: max(1, int(max_images))]
    cover = gallery[0] if gallery else ""
    shots = gallery[1:] if hero_cover and len(gallery) > 1 else gallery
    category = live_category or parsed.category_hint
    price = parsed.original_price
    on_hand = max(0, int(stock))
    use_all_adult = all_adult_sizes or should_use_adult_allsize(
        parsed.folder_name, parsed.folder
    )
    if use_all_adult and not path_mentions_kids(parsed.folder_name, str(parsed.folder)):
        chips = tuple(SIZE_CHIPS[numeric] for numeric in ADULT_SIZE_ORDER)
    else:
        chips = resolve_size_chips(
            parsed.folder_name, selected=parsed.size, folder_path=parsed.folder
        )
    use_designs = bool(design_variants)
    if use_designs and not chips:
        chips = (PAIR_CHIP,)
    size_values = [chip.label for chip in chips]
    bucket_ids = resolve_bucket_ids(price, live_buckets, wholesale=parsed.wholesale)
    display_title = (title or parsed.title).strip() or parsed.title
    if set_index is not None:
        display_title = set_card_title(display_title, set_index)
    if use_designs and shots:
        colors = list(zip(design_labels(len(shots)), shots))
    elif gallery:
        colors = [("As shown", cover)]
    else:
        colors = []
    color_names = [name for name, _url in colors]
    color_images = {name: url for name, url in colors if url}
    has_size = bool(chips)
    has_color_choice = use_designs and len(colors) > 1
    has_variants = has_size or has_color_choice
    if not has_variants:
        colors = []
        color_names = []
        color_images = {"As shown": cover} if cover else {}
        matrix: list[dict[str, Any]] = []
    else:
        if not has_color_choice and has_size:
            colors = [("As shown", cover)] if cover else colors
            color_names = [name for name, _url in colors]
            color_images = {name: url for name, url in colors if url}
        matrix = _variant_matrix(chips, colors, price, on_hand)

    return {
        "title": display_title,
        "slug": slugify(display_title),
        "price": price,
        "originalPrice": price,
        "description": build_description(
            parsed, description or "", chips=chips
        ),
        "category": category,
        "stock": on_hand,
        "videoUrl": "",
        "imageUrl": cover,
        "images": gallery,
        "colorImages": color_images,
        "variantColors": (
            [{"name": name, "imageUrl": url} for name, url in colors] if has_variants else []
        ),
        "variantSizes": size_values,
        "variantOptions": [
            {
                "id": "color",
                "name": "Color",
                "values": color_names if has_variants else [],
            },
            {"id": "size", "name": "Size", "values": size_values},
        ],
        "variantMatrix": matrix,
        "hasVariants": has_variants,
        "featured": featured,
        "published": published,
        "isWholesale": parsed.wholesale,
        "priceBucketIds": bucket_ids,
        "priceBucketLabels": wanted_bucket_labels(price, wholesale=parsed.wholesale),
        "isFlashSale": False,
        "isWeekendSpecial": False,
        "createdAt": stamp,
        "updatedAt": stamp,
        "sourceFolder": parsed.folder_name,
    }
