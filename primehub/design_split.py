"""Split collage photos into one premium 1:1 crop per design."""
from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from rehan_bot.ai.errors import ProviderErrorKind
from rehan_bot.ai.key_pool import RoundRobinKeyPool
from rehan_bot.ai.parsing import gemini_text, json_object
from rehan_bot.ai.transport import JsonTransport
from rehan_bot.ai.vision import VisionPreprocessor
from rehan_bot.config import Settings

from .ai_enricher import GEMINI_FLASH_MODEL
from .folder_mode import COVER_ALL_STEM, DESIGN_PREFIX, is_cover_all, is_generated_design
from .pacing import emit
from .studio_look import (
    _jewellery_components,
    crop_is_healthy,
    frame_full_scene,
    heal_neighbor_jewellery,
    inspect_card_crop,
    save_listing_webp,
    scene_keeps_native_background,
    shave_dirty_edges,
)
from .webp import DEFAULT_QUALITY, MAX_WIDTH, TARGET_BYTES, compress_image_to_webp

logger = logging.getLogger("rehan_bot.primehub.design_split")

_STUDIO = (248, 244, 238)
_BACKDROP = Path(__file__).resolve().parents[3] / "runtime" / "studio" / "jewellery_premium_backdrop.png"
_QA_PROMPT = (
    "This is one jewellery listing photo. Reply JSON only: "
    '{"pass":true,"reason":"ok"} or {"pass":false,"reason":"short English"}. '
    "A matching set (necklace with its own earrings, or tika with earrings) "
    "is ONE design — PASS. "
    "FAIL if a neighbor cell leaks in, two different designs from a collage, "
    "or the piece is badly chopped. "
    "PASS if one complete shoppable design fills the photo. "
    "Square letterbox padding is OK."
)
_DETECT_PROMPT = (
    "Count shoppable designs a customer would buy separately. "
    "A matching set (necklace with its earrings, tika set, or box of matching bits) "
    "is ONE design — wrap the WHOLE cell. "
    "A 3x3 or 2x2 collage of different colours/styles is many designs. "
    "Return JSON only: "
    '{"designs":[{"id":1,"box":[x,y,w,h]}]}. '
    "box is normalized 0-1, x,y top-left. "
    "Each box MUST wrap the FULL cell: jewellery plus empty cream around it "
    "in that cell. Never crop tight around only the pendant. "
    "Never return the white gap between cells. "
    "If the photo is already one product or one matching set, return one box."
)


def collage_sources(folder: Path) -> list[Path]:
    from .folder_parser import list_image_files

    return [
        path
        for path in list_image_files(folder, limit=None)
        if not is_generated_design(path)
        and not is_cover_all(path)
        and not path.stem.lower().startswith("cover")
    ]


def existing_designs(folder: Path) -> list[Path]:
    from .folder_parser import list_image_files

    files = [
        path
        for path in list_image_files(folder, limit=None)
        if is_generated_design(path)
    ]
    files.sort(key=lambda path: path.name.lower())
    return files


def _split_log_path(folder: Path) -> Path:
    return Path(folder) / ".rehan_split.json"


def _load_split_state(folder: Path) -> dict[str, Any]:
    path = _split_log_path(folder)
    if not path.is_file():
        return {"done": [], "last_written": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"done": [], "last_written": []}
    if not isinstance(raw, dict):
        return {"done": [], "last_written": []}
    done = raw.get("done") if isinstance(raw.get("done"), list) else []
    last = raw.get("last_written") if isinstance(raw.get("last_written"), list) else []
    cover_with = raw.get("cover_with") if isinstance(raw.get("cover_with"), list) else []
    return {
        "done": [str(name) for name in done],
        "last_written": [str(name) for name in last],
        "cover_with": [str(name) for name in cover_with],
    }


def _save_split_state(folder: Path, state: dict[str, Any]) -> None:
    path = _split_log_path(folder)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _load_split_log(folder: Path) -> dict[str, bool]:
    return {name: True for name in _load_split_state(folder)["done"]}


def _save_split_log(folder: Path, done: dict[str, bool]) -> None:
    state = _load_split_state(folder)
    state["done"] = sorted(done)
    _save_split_state(folder, state)


def last_written_designs(folder: Path) -> list[Path]:
    names = _load_split_state(folder)["last_written"]
    paths = [Path(folder) / name for name in names]
    return [path for path in paths if path.is_file()]


def recheck_existing_designs(folder: Path, settings: Settings | None = None) -> int:
    """Open every saved design and print PASS/FAIL. Do not rewrite cards here."""
    target = Path(folder)
    designs = existing_designs(target)
    total = len(designs)
    if not total:
        return 0
    emit(f"  Rehan QA: {total} design photo(s) — aik aik check, rewrite nahi")
    failed = 0
    for index, path in enumerate(designs, start=1):
        with Image.open(path) as opened:
            rgb = ImageOps.exif_transpose(opened).convert("RGB")
        ok, reason = inspect_card_crop(rgb)
        if ok:
            emit(f"  Check {path.name} ({index}/{total}) PASS")
            continue
        failed += 1
        emit(f"  Check {path.name} ({index}/{total}) FAIL ({reason}) — file nahi chheri")
    return failed


def _repair_listing_card(rgb: Image.Image) -> Image.Image:
    width, height = rgb.size
    inset_x = max(8, int(width * 0.08))
    inset_y = max(8, int(height * 0.08))
    tighter = rgb.crop((inset_x, inset_y, width - inset_x, height - inset_y))
    return shave_dirty_edges(heal_neighbor_jewellery(tighter))


def _qa_listing_card(
    rgb: Image.Image, path: Path, settings: Settings | None
) -> tuple[bool, str]:
    ok, reason = inspect_card_crop(rgb)
    if not ok:
        return ok, reason
    judged = _gemini_json(rgb, _QA_PROMPT, path, settings)
    if not judged:
        return True, "pass"
    if judged.get("pass") is False:
        return False, str(judged.get("reason") or "vision fail")
    return True, str(judged.get("reason") or "pass")


def _dark_ratio(image: Image.Image) -> float:
    sample = image.convert("RGB").resize((48, 48), Image.Resampling.BILINEAR)
    pixels = list(sample.getdata())
    dark = sum(1 for red, green, blue in pixels if (red + green + blue) / 3 < 85)
    return dark / max(len(pixels), 1)


def _prefer_product_column(
    image: Image.Image, boxes: list[tuple[float, float, float, float]]
) -> list[tuple[float, float, float, float]]:
    """Keep product cells when the other column is on-head / lifestyle shots."""
    if len(boxes) < 4:
        return boxes
    columns: dict[float, list[tuple[float, float, float, float]]] = {}
    for box in boxes:
        columns.setdefault(round(box[0], 2), []).append(box)
    if len(columns) != 2:
        return boxes
    scored: list[tuple[float, list[tuple[float, float, float, float]]]] = []
    for group in columns.values():
        ratios = [_dark_ratio(_crop_box(image, box)) for box in group]
        scored.append((sum(ratios) / max(len(ratios), 1), group))
    scored.sort(key=lambda item: item[0])
    if scored[1][0] > scored[0][0] + 0.08:
        return scored[0][1]
    return boxes


def _lifestyle_product_panels(
    image: Image.Image,
) -> list[tuple[float, float, float, float]]:
    """2×3 collage: keep the product column when the other is on-head shots."""
    rows = [(0.008, 0.318), (0.342, 0.312), (0.672, 0.322)]
    raw: list[tuple[float, float, float, float]] = []
    for y, height in rows:
        raw.append((0.010, y, 0.458, height))
        raw.append((0.478, y, 0.518, height))
    kept = _prefer_product_column(image, raw)
    if len(raw) == 6 and len(kept) == 3:
        return kept
    return []


def _adjust_box_from_reason(
    box: tuple[float, float, float, float], reason: str
) -> tuple[float, float, float, float]:
    x, y, w, h = box
    text = (reason or "").lower()
    if any(token in text for token in ("left", "leak", "neighbor", "another", "collage", "two", "edge")):
        x = min(0.88, x + 0.04)
        w = max(0.16, w - 0.045)
    if "right" in text:
        w = max(0.14, w - 0.03)
    if any(token in text for token in ("cut", "half", "cropped", "missing")):
        x = max(0.0, x - 0.02)
        y = max(0.0, y - 0.02)
        w = min(1.0 - x, w + 0.04)
        h = min(1.0 - y, h + 0.04)
    if "top" in text:
        y = min(0.88, y + 0.02)
        h = max(0.14, h - 0.02)
    if "bottom" in text:
        h = max(0.14, h - 0.02)
    return (x, y, min(1.0 - x, w), min(1.0 - y, h))


def _crop_until_gemini_pass(
    rgb: Image.Image,
    box: tuple[float, float, float, float],
    path: Path,
    settings: Settings | None,
    *,
    max_tries: int = 5,
) -> tuple[Image.Image | None, tuple[float, float, float, float], str]:
    current = box
    last = "untried"
    for attempt in range(max_tries):
        piece = _crop_box(rgb, current)
        if not _looks_like_product(piece):
            last = "not a product"
            current = _adjust_box_from_reason(current, last)
            continue
        try:
            studio = frame_full_scene(piece)
        except ValueError as exc:
            last = str(exc)
            current = _adjust_box_from_reason(current, last)
            continue
        ok, reason = _qa_listing_card(studio, path, settings)
        if ok:
            if attempt:
                emit(f"  Gemini PASS {path.name} after {attempt + 1} tries")
            return studio, current, reason
        last = reason
        logger.info("Rehan FAIL try %s %s: %s", attempt + 1, path.name, reason)
        emit(f"  Gemini FAIL try {attempt + 1}: {reason} — recrop")
        current = _adjust_box_from_reason(current, reason)
    return None, current, last


def batch_uses_hero_cover(folder: Path, batch: list[Path]) -> bool:
    names = set(_load_split_state(folder).get("cover_with") or [])
    if not names or not batch:
        return False
    return {path.name for path in batch} <= names


def write_hero_cover(folder: Path, source: Path | None = None) -> Path | None:
    """Save cover_all.webp from the collage that shows every pair."""
    target = Path(folder)
    dest = target / f"{COVER_ALL_STEM}.webp"
    if dest.is_file() and source is None:
        return dest
    chosen = source or _hero_collage_source(target)
    if chosen is None or not chosen.is_file():
        return None
    with Image.open(chosen) as opened:
        rgb = ImageOps.exif_transpose(opened).convert("RGB")
    framed = frame_full_scene(rgb)
    save_listing_webp(framed, dest, chosen)
    return dest


def _hero_collage_source(folder: Path) -> Path | None:
    sources = collage_sources(folder)
    if not sources:
        return None
    for path in reversed(sources):
        with Image.open(path) as opened:
            rgb = ImageOps.exif_transpose(opened).convert("RGB")
        if scene_keeps_native_background(rgb):
            return path
    return sources[-1]


def _next_design_index(folder: Path) -> int:
    numbers: list[int] = []
    for path in existing_designs(folder):
        stem = path.stem.replace(DESIGN_PREFIX, "", 1)
        if stem.isdigit():
            numbers.append(int(stem))
    return max(numbers, default=0) + 1


def split_source_into_folder(
    folder: Path,
    source: Path,
    settings: Settings | None = None,
    *,
    dest: Path | None = None,
) -> list[Path]:
    """Inspect each pair from one collage; write only PASS cards."""
    target = Path(dest or folder)
    target.mkdir(parents=True, exist_ok=True)
    crops = split_collage_image(source, settings)
    written: list[Path] = []
    counter = _next_design_index(target)
    for data in crops:
        path = target / f"{DESIGN_PREFIX}{counter:02d}.webp"
        path.write_bytes(data)
        logger.info("Rehan PASS %s from %s", path.name, source.name)
        written.append(path)
        counter += 1
    if not written:
        logger.warning("Rehan wrote 0 designs from %s", source.name)
        return []
    log = _load_split_log(target)
    log[source.name] = True
    state = _load_split_state(target)
    state["done"] = sorted(log)
    state["last_written"] = [path.name for path in written]
    _save_split_state(target, state)
    return written


def split_collages_in_folder(
    folder: Path,
    settings: Settings | None = None,
    *,
    dest: Path | None = None,
    force: bool = False,
) -> list[Path]:
    """Write design_01.webp … into ``dest`` (defaults to the same folder)."""
    target = Path(dest or folder)
    target.mkdir(parents=True, exist_ok=True)
    already = existing_designs(target)
    sources = collage_sources(folder)
    if not sources:
        return already
    log = _load_split_log(target)
    # Operator deleted design_*.webp but .rehan_split.json still says done.
    redo_empty = force or not already
    pending = sources if redo_empty else [path for path in sources if path.name not in log]
    if not pending:
        return already
    written = list(already)
    if redo_empty:
        written = []
    for source in pending:
        written.extend(split_source_into_folder(folder, source, settings, dest=target))
    if written:
        state = _load_split_state(target)
        state["last_written"] = [path.name for path in written]
        _save_split_state(target, state)
    return written or existing_designs(target)


def split_collage_image(
    path: Path,
    settings: Settings | None = None,
    *,
    columns: int | None = None,
    rows: int | None = None,
    board: tuple[float, float, float, float] | None = None,
) -> list[bytes]:
    with Image.open(path) as opened:
        rgb = ImageOps.exif_transpose(opened).convert("RGB")
    if columns and rows:
        boxes = _grid_on_board(columns, rows, board)
    else:
        boxes = _even_grid_guess(rgb)
        if len(boxes) >= 4:
            logger.info("Rehan even grid %s: %s cells", path.name, len(boxes))
        else:
            detected = _detect_boxes(rgb, path, settings)
            boxes = [
                box for box in detected if _looks_like_product(_crop_box(rgb, box))
            ]
            if (
                len(detected) == 1
                and len(boxes) == 1
                and not looks_like_multi_design(rgb)
            ):
                logger.info("Rehan skip split %s: already one product/set", path.name)
                return []
            if len(boxes) < 2:
                boxes = _prefer_product_column(
                    rgb, _layout_boxes_from_jewellery(rgb)
                )
            if len(boxes) < 2:
                boxes = _lifestyle_product_panels(rgb)
                if boxes:
                    logger.info(
                        "Rehan lifestyle/product panels %s: %s cells",
                        path.name,
                        len(boxes),
                    )
        if len(boxes) < 2:
            logger.info("Rehan skip split %s: no full display cells", path.name)
            return []
    crops: list[bytes] = []
    total = len(boxes)
    for index, box in enumerate(boxes, start=1):
        emit(f"  Gemini check {index}/{total} {path.name}")
        studio, _used, reason = _crop_until_gemini_pass(rgb, box, path, settings)
        if studio is None:
            logger.warning(
                "Rehan FAIL skip crop %s from %s: %s", index, path.name, reason
            )
            continue
        fake = path.with_name(f"{path.stem}-design.webp")
        compressed = compress_image_to_webp(
            studio,
            fake,
            original_bytes=path.stat().st_size,
            max_width=MAX_WIDTH,
            quality=DEFAULT_QUALITY,
            target_bytes=TARGET_BYTES,
        )
        crops.append(compressed.data)
    return crops


def looks_like_multi_design(image: Image.Image) -> bool:
    """True when the photo is a collage of separate colours/designs, not one set."""
    blobs, sw, sh = _jewellery_components(image)
    min_area = max(18, int(sw * sh * 0.004))
    kept = [blob for blob in blobs if blob[0] >= min_area]
    if len(kept) >= 4:
        return True
    if len(kept) < 3:
        return False
    areas = [blob[0] for blob in kept]
    if max(areas) > 2.4 * min(areas):
        return False
    centers_x = [((blob[1] + blob[3]) / 2) / max(sw, 1) for blob in kept]
    left = sum(1 for x in centers_x if x < 0.48)
    right = len(centers_x) - left
    return left >= 1 and right >= 1


def _gemini_json(
    image: Image.Image,
    prompt: str,
    path: Path,
    settings: Settings | None,
) -> dict[str, Any] | None:
    if settings is None:
        return None
    keys = tuple(getattr(settings, "gemini_api_key_pool", ()) or ())
    if not keys:
        return None
    try:
        preprocessor = VisionPreprocessor(max_dimension=900, quality=80)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=82)
        vision = preprocessor.prepare(buffer.getvalue())
        pool = RoundRobinKeyPool(keys)
        transport = JsonTransport(45.0)
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": vision.mime_type,
                                "data": vision.base64_data,
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1},
        }
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{GEMINI_FLASH_MODEL}:generateContent"
        )
        last: Exception | None = None
        for state in pool.round_keys():
            try:
                data = transport.post(
                    "gemini",
                    url,
                    {"x-goog-api-key": state.key, "Content-Type": "application/json"},
                    payload,
                )
                parsed = json_object(gemini_text(data))
                pool.success(state)
                return parsed if isinstance(parsed, dict) else None
            except Exception as exc:
                last = exc
                kind = getattr(exc, "kind", ProviderErrorKind.UNKNOWN)
                pool.failure(
                    state,
                    kind if isinstance(kind, ProviderErrorKind) else ProviderErrorKind.UNKNOWN,
                )
        if last:
            logger.warning("Gemini QA failed for %s: %s", path.name, last)
    except Exception as exc:
        logger.warning("Gemini QA skipped for %s: %s", path.name, exc)
    return None


def _detect_boxes(
    image: Image.Image, path: Path, settings: Settings | None
) -> list[tuple[float, float, float, float]]:
    if settings is None:
        return []
    keys = tuple(getattr(settings, "gemini_api_key_pool", ()) or ())
    if not keys:
        return []
    try:
        preprocessor = VisionPreprocessor(max_dimension=1400, quality=85)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=88)
        vision = preprocessor.prepare(buffer.getvalue())
        pool = RoundRobinKeyPool(keys)
        transport = JsonTransport(45.0)
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": _DETECT_PROMPT},
                        {
                            "inline_data": {
                                "mime_type": vision.mime_type,
                                "data": vision.base64_data,
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1},
        }
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{GEMINI_FLASH_MODEL}:generateContent"
        )
        last: Exception | None = None
        for state in pool.round_keys():
            try:
                data = transport.post(
                    "gemini",
                    url,
                    {"x-goog-api-key": state.key, "Content-Type": "application/json"},
                    payload,
                )
                parsed = json_object(gemini_text(data))
                pool.success(state)
                return _boxes_from_json(parsed, size=image.size)
            except Exception as exc:
                last = exc
                kind = getattr(exc, "kind", ProviderErrorKind.UNKNOWN)
                pool.failure(state, kind if isinstance(kind, ProviderErrorKind) else ProviderErrorKind.UNKNOWN)
        if last:
            logger.warning("Gemini design detect failed for %s: %s", path.name, last)
    except Exception as exc:
        logger.warning("Design detect skipped for %s: %s", path.name, exc)
    return []


def _scale_box(
    x: float, y: float, w: float, h: float, size: tuple[int, int] | None
) -> tuple[float, float, float, float]:
    """Accept 0-1, 0-100 percent, or pixel boxes."""
    if size is None:
        return x, y, w, h
    width, height = size
    peak = max(abs(x), abs(y), abs(w), abs(h), abs(x + w), abs(y + h))
    if peak <= 1.5:
        return x, y, w, h
    if peak <= 110:
        return x / 100.0, y / 100.0, w / 100.0, h / 100.0
    return x / max(width, 1), y / max(height, 1), w / max(width, 1), h / max(height, 1)


def _boxes_from_json(
    raw: dict[str, Any], size: tuple[int, int] | None = None
) -> list[tuple[float, float, float, float]]:
    rows = raw.get("designs") or raw.get("boxes") or []
    boxes: list[tuple[float, float, float, float]] = []
    if not isinstance(rows, list):
        return boxes
    for item in rows:
        if not isinstance(item, dict):
            continue
        box = item.get("box") or item.get("bbox") or []
        if not isinstance(box, list) or len(box) < 4:
            continue
        try:
            x, y, w, h = (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
        except (TypeError, ValueError):
            continue
        x, y, w, h = _scale_box(x, y, w, h, size)
        if w <= 0.04 or h <= 0.04:
            continue
        # Pendant-only / gap slices are tiny; a real card/cell fills the board.
        if (w * h) < 0.025:
            continue
        boxes.append((max(0.0, x), max(0.0, y), min(1.0, w), min(1.0, h)))
    return boxes


def _cluster_axis(values: list[float], gap: float) -> list[list[float]]:
    if not values:
        return []
    ordered = sorted(values)
    groups = [[ordered[0]]]
    for value in ordered[1:]:
        if value - groups[-1][-1] > gap:
            groups.append([value])
        else:
            groups[-1].append(value)
    return groups


def _layout_boxes_from_jewellery(
    image: Image.Image,
) -> list[tuple[float, float, float, float]]:
    """Full cells from real jewellery positions (row x col), not a fixed 2x3 grid."""
    blobs, sw, sh = _jewellery_components(image)
    min_area = max(10, int(sw * sh * 0.002))
    kept = [blob for blob in blobs if blob[0] >= min_area]
    if len(kept) < 2:
        return []
    xs = [((blob[1] + blob[3]) / 2) / max(sw, 1) for blob in kept]
    ys = [((blob[2] + blob[4]) / 2) / max(sh, 1) for blob in kept]
    col_groups = _cluster_axis(xs, 0.14)
    row_groups = _cluster_axis(ys, 0.16)
    columns = len(col_groups)
    rows = len(row_groups)
    if columns < 1 or rows < 1:
        return []
    if columns * rows < 2 or columns * rows > 16:
        return []
    minx = min(blob[1] for blob in kept) / max(sw, 1)
    maxx = max(blob[3] for blob in kept) / max(sw, 1)
    miny = min(blob[2] for blob in kept) / max(sh, 1)
    maxy = max(blob[4] for blob in kept) / max(sh, 1)
    pad = 0.06
    board = (
        max(0.0, minx - pad),
        max(0.0, miny - pad),
        min(1.0, maxx - minx + 2 * pad),
        min(1.0, maxy - miny + 2 * pad),
    )
    return _grid_on_board(columns, rows, board)


def _gutter_score(image: Image.Image, columns: int, rows: int) -> float:
    width, height = image.size
    gray = image.convert("L")
    total = 0.0
    count = 0
    for col in range(1, columns):
        x = int(width * col / columns)
        strip = gray.crop((max(0, x - 3), 0, min(width, x + 4), height))
        total += sum(strip.getdata()) / max(strip.width * strip.height, 1)
        count += 1
    for row in range(1, rows):
        y = int(height * row / rows)
        strip = gray.crop((0, max(0, y - 3), width, min(height, y + 4)))
        total += sum(strip.getdata()) / max(strip.width * strip.height, 1)
        count += 1
    return total / max(count, 1)


def _even_grid_guess(
    image: Image.Image,
) -> list[tuple[float, float, float, float]]:
    """Pick a collage grid from bright gutters, not a guessed earring rack."""
    ranked: list[tuple[float, int, list[tuple[float, float, float, float]]]] = []
    for columns, rows in ((3, 3), (3, 2), (2, 3), (2, 2), (4, 2), (2, 4)):
        boxes = _grid_on_board(
            columns, rows, (0.004, 0.004, 0.992, 0.992), pad_frac=0.045
        )
        if not all(_looks_like_product(_crop_box(image, box)) for box in boxes):
            continue
        ranked.append((_gutter_score(image, columns, rows), len(boxes), boxes))
    ranked.sort(reverse=True)
    if not ranked or ranked[0][0] < 205:
        return []
    top = ranked[0][0]
    close = [item for item in ranked if item[0] >= top - 8]
    close.sort(key=lambda item: item[1], reverse=True)
    return _prefer_product_column(image, close[0][2])


def _lifestyle_pair_boxes() -> list[tuple[float, float, float, float]]:
    """2×3 earring rack: one box per pair, hooks included, neighbors excluded."""
    return [
        (0.175, 0.095, 0.300, 0.215),
        (0.505, 0.095, 0.305, 0.215),
        (0.160, 0.325, 0.310, 0.200),
        (0.478, 0.258, 0.355, 0.300),
        (0.145, 0.498, 0.345, 0.328),
        (0.500, 0.558, 0.345, 0.300),
    ]


def _grid_on_board(
    columns: int,
    rows: int,
    board: tuple[float, float, float, float] | None = None,
    *,
    pad_frac: float = 0.08,
) -> list[tuple[float, float, float, float]]:
    """Grid of pair boxes on the velvet stand, not the whole photo."""
    bx, by, bw, bh = board or (0.14, 0.10, 0.70, 0.78)
    cell_w = bw / columns
    cell_h = bh / rows
    pad_x = cell_w * pad_frac
    pad_y = cell_h * pad_frac
    boxes: list[tuple[float, float, float, float]] = []
    for row in range(rows):
        for col in range(columns):
            x = bx + col * cell_w + pad_x
            y = by + row * cell_h + pad_y
            boxes.append((x, y, cell_w - 2 * pad_x, cell_h - 2 * pad_y))
    return boxes


def _grid_boxes(
    size: tuple[int, int], columns: int = 2, rows: int = 3
) -> list[tuple[float, float, float, float]]:
    return _grid_on_board(columns, rows, (0.08, 0.07, 0.84, 0.86))


def _crop_box(image: Image.Image, box: tuple[float, float, float, float]) -> Image.Image:
    width, height = image.size
    x, y, w, h = box
    left = int(x * width)
    top = int(y * height)
    right = int((x + w) * width)
    bottom = int((y + h) * height)
    left = max(0, min(width - 2, left))
    top = max(0, min(height - 2, top))
    right = max(left + 2, min(width, right))
    bottom = max(top + 2, min(height, bottom))
    return image.crop((left, top, right, bottom))


def _looks_like_product(image: Image.Image) -> bool:
    if image.width < 24 or image.height < 24:
        return False
    sample = image.convert("L").resize((32, 32), Image.Resampling.BILINEAR)
    pixels = list(sample.getdata())
    mean = sum(pixels) / len(pixels)
    var = sum((value - mean) ** 2 for value in pixels) / len(pixels)
    return var > 80


def _cutout(image: Image.Image) -> Image.Image:
    try:
        from rembg import remove
    except Exception:
        return _matte_stand(image)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    raw = remove(buffer.getvalue())
    cut = Image.open(io.BytesIO(raw)).convert("RGBA")
    return cut


def _sat(pixel: tuple[int, ...]) -> float:
    red, green, blue = pixel[0] / 255.0, pixel[1] / 255.0, pixel[2] / 255.0
    return max(red, green, blue) - min(red, green, blue)


def _matte_stand(image: Image.Image, metal_floor: float = 0.34) -> Image.Image:
    """Drop low-saturation display-board pixels; keep gold/enamel jewelry."""
    rgb = image.convert("RGB")
    width, height = rgb.size
    pixels = rgb.load()
    alpha = Image.new("L", rgb.size, 0)
    layer = alpha.load()
    kept = 0
    for y in range(height):
        for x in range(width):
            if _sat(pixels[x, y]) >= metal_floor:
                layer[x, y] = 255
                kept += 1
    if kept < 80:
        return rgb.convert("RGBA")
    alpha = alpha.filter(ImageFilter.GaussianBlur(0.6))
    rgba = rgb.convert("RGBA")
    rgba.putalpha(alpha)
    bbox = alpha.getbbox()
    if bbox:
        pad = 10
        rgba = rgba.crop(
            (
                max(0, bbox[0] - pad),
                max(0, bbox[1] - pad),
                min(width, bbox[2] + pad),
                min(height, bbox[3] + pad),
            )
        )
    return rgba


def _fit_subject(subject: Image.Image, max_side: int) -> Image.Image:
    subject = subject.convert("RGBA")
    ratio = min(max_side / max(1, subject.width), max_side / max(1, subject.height))
    size = (max(1, int(subject.width * ratio)), max(1, int(subject.height * ratio)))
    return subject.resize(size, Image.Resampling.LANCZOS)


def _backdrop_canvas(side: int) -> Image.Image:
    if _BACKDROP.is_file():
        with Image.open(_BACKDROP) as opened:
            fitted = ImageOps.fit(opened.convert("RGB"), (side, side), Image.Resampling.LANCZOS)
            return fitted
    return Image.new("RGB", (side, side), _STUDIO)


def _studio_frame(image: Image.Image, side: int = 1200) -> Image.Image:
    cut = _cutout(image)
    subject = cut.convert("RGBA") if cut.mode != "RGBA" else cut
    subject = _fit_subject(subject, int(side * 0.78))
    canvas = _backdrop_canvas(side).convert("RGBA")
    ox = (side - subject.width) // 2
    oy = int(side * 0.52) - subject.height // 2
    oy = max(int(side * 0.08), min(oy, side - subject.height - int(side * 0.06)))
    shadow = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    blob = Image.new("L", (subject.width, max(8, subject.height // 7)), 0)
    draw = ImageDraw.Draw(blob)
    draw.ellipse((6, 1, blob.width - 6, blob.height - 2), fill=80)
    blob = blob.filter(ImageFilter.GaussianBlur(14))
    shadow.paste((30, 22, 16, 55), (ox, oy + subject.height - blob.height // 2), blob)
    canvas = Image.alpha_composite(canvas, shadow)
    canvas.paste(subject, (ox, oy), subject)
    return canvas.convert("RGB")
