"""Local jewelry studio scenes — no image-gen API, jewelry pixels stay real."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from .image_pipeline import apply_protected_ev
from .webp import TARGET_BYTES, compress_image_to_webp

BACKDROP_PATH = (
    Path(__file__).resolve().parents[3] / "runtime" / "studio" / "jewellery_premium_backdrop.png"
)

SCENE_VELVET_CARD = "velvet_card"
SCENE_CUTOUT = "cutout"


def scene_for_folder(folder: Path | str) -> str:
    """Pick a display style from the product folder name (local, no vision API)."""
    name = Path(folder).name.lower().replace("-", " ").replace("_", " ")
    if any(token in name for token in ("watch", "clock")):
        return SCENE_VELVET_CARD
    if any(
        token in name
        for token in ("ear", "airring", "jhumka", "bali", "hoop", "stud")
    ):
        return SCENE_VELVET_CARD
    return SCENE_VELVET_CARD


def crop_is_healthy(image: Image.Image) -> bool:
    """Reject empty / blown-out crops before compositing."""
    if image.width < 40 or image.height < 40:
        return False
    sample = image.convert("RGB").resize((48, 48), Image.Resampling.BILINEAR)
    pixels = list(sample.getdata())
    mean = tuple(sum(channel[i] for channel in pixels) / len(pixels) for i in range(3))
    var = sum(sum((px[i] - mean[i]) ** 2 for i in range(3)) for px in pixels) / len(pixels)
    if var < 90:
        return False
    if mean[0] > 248 and mean[1] > 248 and mean[2] > 248:
        return False
    return True


def _sat(pixel: tuple[int, ...]) -> float:
    red, green, blue = pixel[0] / 255.0, pixel[1] / 255.0, pixel[2] / 255.0
    return max(red, green, blue) - min(red, green, blue)


def _metal_components(rgb: Image.Image, metal_floor: float = 0.32) -> list[tuple[int, int, int, int, int]]:
    """Return (area, minx, miny, maxx, maxy) for gold blobs on a small mask."""
    width, height = rgb.size
    scale = min(1.0, 160 / max(width, height))
    small = rgb.resize(
        (max(1, int(width * scale)), max(1, int(height * scale))),
        Image.Resampling.BILINEAR,
    )
    sw, sh = small.size
    pixels = small.load()
    metal = [[_sat(pixels[x, y]) >= metal_floor for x in range(sw)] for y in range(sh)]
    seen = [[False] * sw for _ in range(sh)]
    blobs: list[tuple[int, int, int, int, int]] = []
    for y in range(sh):
        for x in range(sw):
            if not metal[y][x] or seen[y][x]:
                continue
            stack = [(x, y)]
            seen[y][x] = True
            count = 0
            minx = maxx = x
            miny = maxy = y
            while stack:
                cx, cy = stack.pop()
                count += 1
                minx = min(minx, cx)
                maxx = max(maxx, cx)
                miny = min(miny, cy)
                maxy = max(maxy, cy)
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if 0 <= nx < sw and 0 <= ny < sh and metal[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            blobs.append((count, minx, miny, maxx, maxy))
    return blobs, sw, sh


def _is_wood_pixel(pixel: tuple[int, ...]) -> bool:
    red, green, blue = pixel[0], pixel[1], pixel[2]
    return (
        red > blue + 22
        and 95 < red < 225
        and 75 < green < 195
        and (red - green) < 70
        and _sat(pixel) < 0.42
    )


def _is_jewellery_pixel(pixel: tuple[int, ...]) -> bool:
    if _is_wood_pixel(pixel):
        return False
    return _sat(pixel) >= 0.30


def _jewellery_components(rgb: Image.Image) -> tuple[list[tuple[int, int, int, int, int]], int, int]:
    width, height = rgb.size
    scale = min(1.0, 160 / max(width, height))
    small = rgb.resize(
        (max(1, int(width * scale)), max(1, int(height * scale))),
        Image.Resampling.BILINEAR,
    )
    sw, sh = small.size
    pixels = small.load()
    jewel = [[_is_jewellery_pixel(pixels[x, y]) for x in range(sw)] for y in range(sh)]
    seen = [[False] * sw for _ in range(sh)]
    blobs: list[tuple[int, int, int, int, int]] = []
    for y in range(sh):
        for x in range(sw):
            if not jewel[y][x] or seen[y][x]:
                continue
            stack = [(x, y)]
            seen[y][x] = True
            count = 0
            minx = maxx = x
            miny = maxy = y
            while stack:
                cx, cy = stack.pop()
                count += 1
                minx = min(minx, cx)
                maxx = max(maxx, cx)
                miny = min(miny, cy)
                maxy = max(maxy, cy)
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if 0 <= nx < sw and 0 <= ny < sh and jewel[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            blobs.append((count, minx, miny, maxx, maxy))
    return blobs, sw, sh


def _linen_fill(rgb: Image.Image) -> tuple[int, int, int]:
    sample = rgb.resize((48, 48), Image.Resampling.BILINEAR)
    fabric = [px for px in sample.getdata() if _sat(px) < 0.14 and not _is_jewellery_pixel(px)]
    if len(fabric) < 8:
        return _corner_fill(rgb)
    return (
        int(sum(px[0] for px in fabric) / len(fabric)),
        int(sum(px[1] for px in fabric) / len(fabric)),
        int(sum(px[2] for px in fabric) / len(fabric)),
    )


def _blob_is_neighbor(
    area: int,
    minx: int,
    miny: int,
    maxx: int,
    maxy: int,
    sw: int,
    sh: int,
    largest: int,
) -> bool:
    if maxy <= int(sh * 0.21):
        return True
    if miny <= int(sh * 0.04) and maxy <= int(sh * 0.40) and area < largest * 0.85:
        return True
    if miny >= int(sh * 0.80):
        return True
    if area >= largest * 0.20:
        return False
    top = miny <= sh * 0.06
    bot = maxy >= sh * 0.94
    side = maxx <= sw * 0.10 or minx >= sw * 0.90
    return top or bot or side


def _linen_patch(rgb: Image.Image) -> Image.Image:
    width, height = rgb.size
    best = None
    best_score = -1
    size = max(24, min(width, height) // 8)
    for top in (int(height * 0.12), int(height * 0.40), int(height * 0.62)):
        for left in (int(width * 0.08), int(width * 0.55)):
            box = (
                max(0, left),
                max(0, top),
                min(width, left + size),
                min(height, top + size),
            )
            if box[2] - box[0] < 12 or box[3] - box[1] < 12:
                continue
            patch = rgb.crop(box)
            sample = patch.resize((16, 16), Image.Resampling.BILINEAR)
            pixels = list(sample.getdata())
            fabric = sum(1 for px in pixels if _sat(px) < 0.16 and not _is_jewellery_pixel(px))
            if fabric > best_score:
                best_score = fabric
                best = patch
    return best if best is not None and best_score >= 80 else Image.new("RGB", (32, 32), _linen_fill(rgb))


def _paint_mask_with_linen(rgb: Image.Image, mask: Image.Image) -> Image.Image:
    patch = _linen_patch(rgb.convert("RGB"))
    base = Image.new("RGB", rgb.size)
    pw, ph = max(1, patch.width), max(1, patch.height)
    for y in range(0, rgb.height, ph):
        for x in range(0, rgb.width, pw):
            base.paste(patch, (x, y))
    alpha = mask.convert("L")
    return Image.composite(base, rgb.convert("RGB"), alpha)


def _wood_rod_row(rgb: Image.Image) -> int | None:
    width, height = rgb.size
    probe = rgb.resize((64, height), Image.Resampling.BILINEAR)
    pixels = probe.load()
    best_y = 0
    best = 0
    for y in range(int(height * 0.05), int(height * 0.55)):
        wood = sum(1 for x in range(64) if _is_wood_pixel(pixels[x, y]))
        if wood > best:
            best = wood
            best_y = y
    if best < 32:
        return None
    return best_y


def heal_neighbor_jewellery(image: Image.Image) -> Image.Image:
    """Erase leftover neighbor jewellery using this photo's own linen — keep the real pair."""
    rgb = image.convert("RGB")
    width, height = rgb.size
    mask = Image.new("L", rgb.size, 0)
    mask_px = mask.load()
    pixels = rgb.load()
    rod = _wood_rod_row(rgb)
    above = (rod - max(3, height // 70)) if rod is not None else int(height * 0.07)
    for y in range(max(0, above)):
        for x in range(width):
            pixel = pixels[x, y]
            if _is_wood_pixel(pixel):
                continue
            if _is_jewellery_pixel(pixel):
                mask_px[x, y] = 255
    if mask.getbbox() is not None:
        mask = mask.filter(ImageFilter.MaxFilter(9))
    scale = min(1.0, 220 / max(width, height))
    sw = max(1, int(width * scale))
    sh = max(1, int(height * scale))
    small = rgb.resize((sw, sh), Image.Resampling.BILINEAR)
    sp = small.load()
    jewel = [[_is_jewellery_pixel(sp[x, y]) for x in range(sw)] for y in range(sh)]
    seed_y = int(sh * 0.36)
    reached = [[False] * sw for _ in range(sh)]
    stack: list[tuple[int, int]] = []
    for y in range(seed_y, sh):
        for x in range(sw):
            if jewel[y][x]:
                reached[y][x] = True
                stack.append((x, y))
    while stack:
        cx, cy = stack.pop()
        for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
            if 0 <= nx < sw and 0 <= ny < sh and jewel[ny][nx] and not reached[ny][nx]:
                reached[ny][nx] = True
                stack.append((nx, ny))
    drop_small = Image.new("L", (sw, sh), 0)
    ds = drop_small.load()
    extra = False
    for y in range(sh):
        for x in range(sw):
            if jewel[y][x] and not reached[y][x]:
                ds[x, y] = 255
                extra = True
    if extra:
        drop_full = drop_small.resize(rgb.size, Image.Resampling.BILINEAR)
        mask = ImageChops.lighter(mask, drop_full)
    if mask.getbbox() is None:
        return rgb
    return _paint_mask_with_linen(rgb, mask)


def trim_neighbor_leaks(image: Image.Image) -> Image.Image:
    """Drop small gold blobs on the card edge (pair above/beside), keep the main pair."""
    rgb = image.convert("RGB")
    blobs, sw, sh = _metal_components(rgb)
    if not blobs:
        return rgb
    largest = max(blob[0] for blob in blobs)
    kept: list[tuple[int, int, int, int, int]] = []
    for area, minx, miny, maxx, maxy in blobs:
        top_orphan = miny <= sh * 0.06 and maxy <= sh * 0.28 and area < largest * 0.5
        bot_orphan = miny >= sh * 0.72 and area < largest * 0.5
        side_orphan = (maxx <= sw * 0.12 or minx >= sw * 0.88) and area < largest * 0.4
        if top_orphan or bot_orphan or side_orphan:
            continue
        if area < largest * 0.16:
            continue
        kept.append((area, minx, miny, maxx, maxy))
    if not kept:
        kept = [max(blobs, key=lambda item: item[0])]
    minx = min(item[1] for item in kept)
    miny = min(item[2] for item in kept)
    maxx = max(item[3] for item in kept)
    maxy = max(item[4] for item in kept)
    pad_x = max(2, int((maxx - minx) * 0.12))
    pad_y = max(2, int((maxy - miny) * 0.10))
    scale_x = rgb.width / sw
    scale_y = rgb.height / sh
    box = (
        max(0, int((minx - pad_x) * scale_x)),
        max(0, int((miny - pad_y) * scale_y)),
        min(rgb.width, int((maxx + 1 + pad_x) * scale_x)),
        min(rgb.height, int((maxy + 1 + pad_y) * scale_y)),
    )
    if box[2] - box[0] < 24 or box[3] - box[1] < 24:
        return rgb
    return rgb.crop(box)


def _band_metal_ratio(rgb: Image.Image, side: str, frac: float = 0.07) -> float:
    width, height = rgb.size
    band_w = max(3, int(width * frac))
    band_h = max(3, int(height * frac))
    if side == "top":
        strip = rgb.crop((0, 0, width, band_h))
    elif side == "bottom":
        strip = rgb.crop((0, height - band_h, width, height))
    elif side == "left":
        strip = rgb.crop((0, 0, band_w, height))
    else:
        strip = rgb.crop((width - band_w, 0, width, height))
    sample = strip.resize((48, 48), Image.Resampling.BILINEAR)
    pixels = list(sample.getdata())
    metal = sum(1 for px in pixels if _sat(px) >= 0.32)
    return metal / max(1, len(pixels))


def _inner_band_metal_ratio(rgb: Image.Image, side: str, frac: float = 0.07) -> float:
    width, height = rgb.size
    band_w = max(3, int(width * frac))
    band_h = max(3, int(height * frac))
    if side == "top":
        strip = rgb.crop((0, band_h, width, min(height, band_h * 2)))
    elif side == "bottom":
        strip = rgb.crop((0, max(0, height - band_h * 2), width, height - band_h))
    elif side == "left":
        strip = rgb.crop((band_w, 0, min(width, band_w * 2), height))
    else:
        strip = rgb.crop((max(0, width - band_w * 2), 0, width - band_w, height))
    if strip.width < 2 or strip.height < 2:
        return 0.0
    sample = strip.resize((48, 48), Image.Resampling.BILINEAR)
    pixels = list(sample.getdata())
    metal = sum(1 for px in pixels if _sat(px) >= 0.32)
    return metal / max(1, len(pixels))


def _edge_has_orphan_jewellery(rgb: Image.Image, side: str) -> bool:
    """True when gold on the rim is leftover (velvet gap), not the pair itself."""
    outer = _band_metal_ratio(rgb, side)
    if outer < 0.09:
        return False
    inner = _inner_band_metal_ratio(rgb, side)
    return inner < 0.07 or inner < outer * 0.5


def inspect_card_crop(image: Image.Image) -> tuple[bool, str]:
    """One-by-one pass. Fail only leftover jewellery, not a pair that fills the card."""
    if not crop_is_healthy(image):
        return False, "empty or damaged crop"
    rgb = image.convert("RGB")
    faults = [
        f"{side} leftover jewellery"
        for side in ("top", "bottom", "left", "right")
        if _edge_has_orphan_jewellery(rgb, side)
    ]
    if faults:
        return False, "; ".join(faults)
    return True, "pass"


def shave_dirty_edges(image: Image.Image, *, max_steps: int = 12) -> Image.Image:
    rgb = image.convert("RGB")
    for _ in range(max_steps):
        ok, _reason = inspect_card_crop(rgb)
        if ok:
            return rgb
        width, height = rgb.size
        if width < 70 or height < 70:
            break
        shaved = False
        step_y = max(2, int(height * 0.04))
        step_x = max(2, int(width * 0.04))
        if _edge_has_orphan_jewellery(rgb, "top"):
            rgb = rgb.crop((0, step_y, width, height))
            shaved = True
            width, height = rgb.size
        if _edge_has_orphan_jewellery(rgb, "bottom"):
            rgb = rgb.crop((0, 0, width, height - step_y))
            shaved = True
            width, height = rgb.size
        if _edge_has_orphan_jewellery(rgb, "left"):
            rgb = rgb.crop((step_x, 0, width, height))
            shaved = True
            width, height = rgb.size
        if _edge_has_orphan_jewellery(rgb, "right"):
            rgb = rgb.crop((0, 0, width - step_x, height))
            shaved = True
        if not shaved:
            break
    return rgb


def _rounded(image: Image.Image, radius: int) -> Image.Image:
    rgb = image.convert("RGB")
    mask = Image.new("L", rgb.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, rgb.width - 1, rgb.height - 1), radius=radius, fill=255)
    rgba = rgb.convert("RGBA")
    rgba.putalpha(mask)
    return rgba


def _fit(image: Image.Image, max_side: int) -> Image.Image:
    ratio = min(max_side / max(1, image.width), max_side / max(1, image.height))
    size = (max(1, int(image.width * ratio)), max(1, int(image.height * ratio)))
    return image.resize(size, Image.Resampling.LANCZOS)


def _corner_fill(rgb: Image.Image) -> tuple[int, int, int]:
    width, height = rgb.size
    inset = max(2, min(width, height) // 20)
    patches = [
        rgb.crop((inset, inset, inset + 8, inset + 8)),
        rgb.crop((width - inset - 8, inset, width - inset, inset + 8)),
        rgb.crop((inset, height - inset - 8, inset + 8, height - inset)),
        rgb.crop((width - inset - 8, height - inset - 8, width - inset, height - inset)),
    ]
    pixels: list[tuple[int, int, int]] = []
    for patch in patches:
        pixels.extend(patch.resize((4, 4), Image.Resampling.BILINEAR).getdata())
    if not pixels:
        return (232, 222, 210)
    return (
        int(sum(px[0] for px in pixels) / len(pixels)),
        int(sum(px[1] for px in pixels) / len(pixels)),
        int(sum(px[2] for px in pixels) / len(pixels)),
    )


def scene_keeps_native_background(image: Image.Image) -> bool:
    """True when the photo already has a boutique set (wood rack, linen, silk)."""
    rgb = image.convert("RGB")
    width, height = rgb.size
    left = rgb.crop((0, int(height * 0.15), max(8, int(width * 0.12)), int(height * 0.85)))
    sample = left.resize((16, 32), Image.Resampling.BILINEAR)
    pixels = list(sample.getdata())
    wood = sum(
        1
        for px in pixels
        if px[0] > px[2] + 20 and 90 < px[0] < 230 and 70 < px[1] < 200
    )
    return wood / max(1, len(pixels)) >= 0.18


def frame_full_scene(image: Image.Image, *, side: int = 1200) -> Image.Image:
    """Keep the whole display photo for the product cover (every pair visible)."""
    rgb = image.convert("RGB")
    fill = _corner_fill(rgb)
    edge = max(rgb.width, rgb.height)
    square = ImageOps.pad(rgb, (edge, edge), color=fill, centering=(0.5, 0.48))
    out = square.resize((side, side), Image.Resampling.LANCZOS)
    return apply_protected_ev(out, 0.04)


def frame_keep_native_background(crop: Image.Image, *, side: int = 1200) -> Image.Image:
    """Keep the photo's own linen/wood; do not paste a different studio backdrop."""
    crop = heal_neighbor_jewellery(crop.convert("RGB"))
    crop = shave_dirty_edges(crop, max_steps=4)
    if not crop_is_healthy(crop):
        raise ValueError("Crop looks empty or damaged; skip compositing")
    ok, reason = inspect_card_crop(crop)
    if not ok:
        raise ValueError(f"Rehan FAIL: {reason}")
    rgb = crop.convert("RGB")
    fill = _corner_fill(rgb)
    edge = max(rgb.width, rgb.height)
    square = ImageOps.pad(rgb, (edge, edge), color=fill, centering=(0.5, 0.42))
    out = square.resize((side, side), Image.Resampling.LANCZOS)
    return apply_protected_ev(out, 0.04)


def frame_design_card(
    crop: Image.Image, *, keep_native: bool = False, side: int = 1200
) -> Image.Image:
    if keep_native:
        return frame_keep_native_background(crop, side=side)
    return frame_on_velvet_card(crop, side=side)


def frame_on_velvet_card(crop: Image.Image, *, side: int = 1200) -> Image.Image:
    """Keep the pair on its display board; sit that card in the boutique set."""
    crop = shave_dirty_edges(trim_neighbor_leaks(crop))
    if not crop_is_healthy(crop):
        raise ValueError("Crop looks empty or damaged; skip compositing")
    ok, reason = inspect_card_crop(crop)
    if not ok:
        raise ValueError(f"Rehan FAIL: {reason}")
    if BACKDROP_PATH.is_file():
        with Image.open(BACKDROP_PATH) as opened:
            scene = ImageOps.fit(opened.convert("RGB"), (side, side), Image.Resampling.LANCZOS)
    else:
        scene = Image.new("RGB", (side, side), (244, 238, 230))
    card = _fit(crop.convert("RGB"), int(side * 0.62))
    card = _rounded(card, radius=max(18, card.width // 28))
    canvas = scene.convert("RGBA")
    ox = (side - card.width) // 2
    oy = (side - card.height) // 2 + int(side * 0.04)
    shadow = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    blob = Image.new("L", (card.width + 40, card.height + 28), 0)
    draw = ImageDraw.Draw(blob)
    draw.rounded_rectangle((8, 8, blob.width - 8, blob.height - 8), radius=28, fill=70)
    blob = blob.filter(ImageFilter.GaussianBlur(18))
    shadow.paste((28, 20, 14, 60), (ox - 12, oy + 18), blob)
    canvas = Image.alpha_composite(canvas, shadow)
    canvas.paste(card, (ox, oy), card)
    return apply_protected_ev(canvas.convert("RGB"), 0.06)


def save_listing_webp(image: Image.Image, dest: Path, original: Path) -> Path:
    dest = Path(dest)
    compressed = compress_image_to_webp(
        image,
        dest,
        original_bytes=original.stat().st_size if original.exists() else 0,
        max_width=1200,
        quality=90,
        target_bytes=TARGET_BYTES,
    )
    dest.write_bytes(compressed.data)
    return dest
