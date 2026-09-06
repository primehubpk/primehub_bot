"""Parse a product folder name into title, price, size, and category hint."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .categories import category_from_path, looks_like_wholesale, wholesale_from_path
from .sizes import (
    SIZE_CHIPS,
    SizeChip,
    extract_size_token,
    resolve_size,
    resolve_size_chips,
    size_guide_lines,
)

_MODE_WORDS = re.compile(
    r"(?i)\b(?:one\s*pair|all\s*images?|edit\s*folder)\b"
)

_PRICE_RE = re.compile(r"(?i)(?:^|[_\-\s])price[_\-\s]*(\d+)(?:$|[_\-\s])")
_BARE_PRICE_RE = re.compile(r"(?:^|[_\-\s])(\d{2,6})(?:$|[_\-\s])")
_NOT_A_PRICE = {"8", "10", "12", "22", "24", "26", "28", "210"}
_COMPOUNDS = (
    (re.compile(r"(?i)dozen\s*box"), "Dozen Box"),
    (re.compile(r"(?i)\bph\s*deals?\b"), "Ph Deals"),
)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


@dataclass(frozen=True)
class ParsedFolder:
    """Everything we can read from a product folder before uploading."""

    folder: Path
    folder_name: str
    stem: str
    title: str
    original_price: int
    size: SizeChip | None
    category_hint: str
    wholesale: bool
    image_files: tuple[Path, ...]

    @property
    def size_label(self) -> str:
        return self.size.label if self.size else ""

    @property
    def size_chips(self) -> tuple[SizeChip, ...]:
        return resolve_size_chips(
            self.folder_name, selected=self.size, folder_path=self.folder
        )


def humanize_stem(raw: str) -> str:
    """Turn ``20Dozenbox`` into ``20 Dozen Box``."""
    text = (raw or "").replace("-", " ").replace("_", " ").strip()
    text = re.sub(r"(?<=\d)(?=[A-Za-z])", " ", text)
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    for pattern, replacement in _COMPOUNDS:
        text = pattern.sub(replacement, text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    return " ".join(part.capitalize() if part.islower() else part for part in text.split())


def _strip_price_and_size(folder_name: str) -> str:
    text = _PRICE_RE.sub(" ", folder_name)
    token = extract_size_token(folder_name)
    if token:
        text = re.sub(rf"(?i)[_\-\s]*{re.escape(token)}\s*$", "", text)
    text = _MODE_WORDS.sub(" ", text)
    return re.sub(r"[_\-\s]+", " ", text).strip()


def extract_price_from_path(path: Path | str) -> int | None:
    current = Path(path)
    for item in [current, *current.parents]:
        found = extract_price(item.name)
        if found is not None:
            return found
    return None


def extract_price(folder_name: str) -> int | None:
    """Read ``_price_1200``, ``Price_999``, or a bare amount like ``_499_allsize``."""
    match = _PRICE_RE.search(folder_name)
    if match:
        return int(match.group(1))
    candidates: list[int] = []
    for item in _BARE_PRICE_RE.finditer(f"_{folder_name}_"):
        raw = item.group(1)
        if raw in _NOT_A_PRICE or raw in SIZE_CHIPS:
            continue
        amount = int(raw)
        if amount < 50:
            continue
        candidates.append(amount)
    return candidates[-1] if candidates else None


def list_image_files(folder: Path, limit: int | None = None) -> tuple[Path, ...]:
    if not folder.is_dir():
        return ()
    files = [
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    files.sort(key=lambda path: path.name.lower())
    if limit is None:
        return tuple(files)
    return tuple(files[: max(0, int(limit))])


def _display_category(category: str) -> str:
    return " ".join(part.capitalize() for part in (category or "").split())


def build_title(stem: str, category: str) -> str:
    """Append the category when it is not already part of the stem."""
    title = stem.strip()
    extra = _display_category(category)
    if not extra:
        return title
    if extra.lower() in title.lower():
        return title
    return f"{title} {extra}".strip()


def parse_folder_name(
    folder_name: str,
    *,
    category_hint: str = "",
    default_category: str = "Glass bangles",
    inherited_price: int | None = None,
) -> tuple[str, int, SizeChip | None, str, bool]:
    """Parse just the folder name (no filesystem)."""
    price = extract_price(folder_name)
    if price is None:
        price = inherited_price
    if price is None:
        raise ValueError(f"Folder name has no _price_NNNN token: {folder_name!r}")
    size = resolve_size(extract_size_token(folder_name))
    stem = humanize_stem(_strip_price_and_size(folder_name))
    if not stem:
        stem = f"Price {price}"
    hint = category_hint or default_category
    wholesale = looks_like_wholesale(folder_name)
    return stem, price, size, hint, wholesale


def parse_product_folder(
    folder: Path,
    *,
    default_category: str = "Glass bangles",
) -> ParsedFolder:
    """Parse one on-disk product folder."""
    path = Path(folder)
    hint = category_from_path(path, default=default_category)
    inherited = extract_price_from_path(path.parent)
    stem, price, size, category, _folder_wholesale = parse_folder_name(
        path.name,
        category_hint=hint,
        default_category=default_category,
        inherited_price=inherited,
    )
    title = build_title(stem, category)
    return ParsedFolder(
        folder=path,
        folder_name=path.name,
        stem=stem,
        title=title,
        original_price=price,
        size=size,
        category_hint=category,
        wholesale=wholesale_from_path(path) or _folder_wholesale,
        image_files=list_image_files(path),
    )


def looks_like_product_folder(path: Path) -> bool:
    """A product folder has a price token, or images plus a parseable name."""
    if not path.is_dir():
        return False
    if extract_price(path.name) is not None:
        return True
    return bool(list_image_files(path)) and bool(humanize_stem(path.name))


def discover_product_folders(root: Path) -> list[Path]:
    """If ``root`` is one product, return it; otherwise return child products."""
    path = Path(root)
    if not path.exists():
        raise FileNotFoundError(f"Product directory does not exist: {path}")
    if looks_like_product_folder(path):
        return [path]
    children = sorted(
        (child for child in path.iterdir() if looks_like_product_folder(child)),
        key=lambda item: item.name.lower(),
    )
    if not children:
        raise ValueError(f"No product folders found under {path}")
    return children


def discover_product_tree(root: Path) -> list[Path]:
    """Walk nested category folders and return every priced product directory."""
    from .folder_mode import is_all_image_container

    path = Path(root)
    if not path.exists():
        raise FileNotFoundError(f"Product directory does not exist: {path}")
    found: list[Path] = []
    for candidate in [path, *path.rglob("*")]:
        if not candidate.is_dir():
            continue
        if not list_image_files(candidate, limit=1):
            continue
        if is_all_image_container(candidate):
            has_inner = any(
                child.is_dir() and bool(list_image_files(child, limit=1))
                for child in candidate.iterdir()
            )
            if has_inner:
                continue
            if extract_price_from_path(candidate) is None:
                continue
            found.append(candidate.resolve())
            continue
        own_price = extract_price(candidate.name)
        parent_is_all = is_all_image_container(candidate.parent)
        if own_price is None and not parent_is_all:
            continue
        if extract_price_from_path(candidate) is None:
            continue
        found.append(candidate.resolve())
    unique = sorted({item for item in found}, key=lambda item: str(item).lower())
    if not unique:
        raise ValueError(f"No product folders found under {path}")
    return unique


def size_guide_block(
    selected: SizeChip | None,
    *,
    kids: bool = False,
    chips: tuple[SizeChip, ...] | list[SizeChip] | None = None,
) -> str:
    if chips is not None and not chips:
        return ""
    heading = (
        "Size guide (kids numbers):"
        if kids
        else "Size guide (measure inner diameter):"
    )
    lines = [heading]
    lines.extend(f"• {line}" for line in size_guide_lines(kids=kids))
    if selected:
        lines.append("")
        lines.append(f"This piece: {selected.label}.")
    return "\n".join(lines)
