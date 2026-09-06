"""Map folder size tokens onto PrimeHub variant chips."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SIZE_GUIDE_ORDER = ("2.8", "2.6", "2.4", "2.2")
ADULT_SIZE_ORDER = ("2.2", "2.4", "2.6", "2.8")
KIDS_SIZE_ORDER = ("8", "10", "12")
_ALLSIZE_HINTS = (
    "allsize",
    "all size",
    "all-size",
    "onesize",
    "one size",
    "mixed size",
    "assorted",
    "general",
)


@dataclass(frozen=True)
class SizeChip:
    """One storefront size chip plus the short numeric form."""

    token: str
    numeric: str
    label: str


PAIR_CHIP = SizeChip("onepair", "1", "One pair")


SIZE_CHIPS: dict[str, SizeChip] = {
    "28": SizeChip("28", "2.8", "2.8 - Large (Dhai size / Healthy hand)"),
    "2.8": SizeChip("2.8", "2.8", "2.8 - Large (Dhai size / Healthy hand)"),
    "26": SizeChip("26", "2.6", "2.6 - Sawa 2 (Regular standard size)"),
    "2.6": SizeChip("2.6", "2.6", "2.6 - Sawa 2 (Regular standard size)"),
    "24": SizeChip("24", "2.4", "2.4 - Ponay 2 / Apda 2 size"),
    "2.4": SizeChip("2.4", "2.4", "2.4 - Ponay 2 / Apda 2 size"),
    "22": SizeChip("22", "2.2", "2.2 - Small inch (Bareek hand / 10-13 year baby girl)"),
    "2.2": SizeChip("2.2", "2.2", "2.2 - Small inch (Bareek hand / 10-13 year baby girl)"),
    "210": SizeChip("210", "2.10", "2.10"),
    "2.10": SizeChip("2.10", "2.10", "2.10"),
}

KIDS_SIZE_CHIPS: dict[str, SizeChip] = {
    "8": SizeChip("8", "8", "8 number — 1–3 year baby, normal hand"),
    "10": SizeChip("10", "10", "10 number — 3–5 year baby, normal hand"),
    "12": SizeChip("12", "12", "12 number — 5–8 year baby, normal hand"),
}

_SIZE_TOKEN_RE = re.compile(
    r"(?:^|[_\-\s])((?:2\.(?:10|8|6|4|2))|(?:210|28|26|24|22))(?=$|[_\-\s])"
)
_KIDS_SIZE_TOKEN_RE = re.compile(r"(?:^|[_\-\s])(8|10|12)(?=$|[_\-\s])")


def _haystack(*parts: str) -> str:
    return " ".join((part or "").lower().replace("-", " ").replace("_", " ") for part in parts)


def path_mentions_kids(folder_name: str, folder_path: str = "") -> bool:
    return "kids" in _haystack(folder_name, folder_path)


def normalize_size_token(raw: str | None) -> str:
    """Return the canonical token key, or an empty string."""
    token = (raw or "").strip().lower().lstrip("_")
    if token in SIZE_CHIPS:
        return token
    compact = token.replace(" ", "")
    if compact in SIZE_CHIPS:
        return compact
    return ""


def resolve_size(raw: str | None) -> SizeChip | None:
    """Map a folder token such as ``_28`` or ``2.6`` to a chip."""
    key = normalize_size_token(raw)
    chip = SIZE_CHIPS.get(key)
    if chip is not None:
        return chip
    token = (raw or "").strip().lower().lstrip("_")
    return KIDS_SIZE_CHIPS.get(token)


def extract_size_tokens(folder_name: str) -> tuple[str, ...]:
    """Return every adult size token embedded in a folder name, in order."""
    return tuple(_SIZE_TOKEN_RE.findall(f"_{folder_name}_"))


def extract_kids_size_tokens(folder_name: str) -> tuple[str, ...]:
    return tuple(_KIDS_SIZE_TOKEN_RE.findall(f"_{folder_name}_"))


def extract_size_token(folder_name: str) -> str:
    """Pull the trailing / embedded size token from a folder name."""
    if path_mentions_kids(folder_name):
        kids = extract_kids_size_tokens(folder_name)
        if kids:
            return str(kids[-1])
    matches = extract_size_tokens(folder_name)
    if not matches:
        return ""
    return str(matches[-1])


def looks_like_general_stock(folder_name: str) -> bool:
    haystack = (folder_name or "").lower().replace("_", " ").replace("-", " ")
    return any(hint in haystack for hint in _ALLSIZE_HINTS)


def _unique_chips(items: list[SizeChip]) -> tuple[SizeChip, ...]:
    seen: set[str] = set()
    out: list[SizeChip] = []
    for chip in items:
        if chip.numeric in seen:
            continue
        seen.add(chip.numeric)
        out.append(chip)
    return tuple(out)


def resolve_size_chips(
    folder_name: str,
    selected: SizeChip | None = None,
    *,
    folder_path: str | Path = "",
) -> tuple[SizeChip, ...]:
    """Sizes only when the folder/path actually names them.

    Watches / jewellery without 2.2–2.8 (or kids 8/10/12) get no size chips.
    """
    path_text = str(folder_path or "")
    if path_mentions_kids(folder_name, path_text):
        tokens = extract_kids_size_tokens(folder_name)
        chips = _unique_chips(
            [KIDS_SIZE_CHIPS[token] for token in tokens if token in KIDS_SIZE_CHIPS]
        )
        if looks_like_general_stock(folder_name) or not chips:
            return tuple(KIDS_SIZE_CHIPS[key] for key in KIDS_SIZE_ORDER)
        return chips

    tokens = extract_size_tokens(folder_name)
    chips = _unique_chips([chip for token in tokens if (chip := resolve_size(token))])
    if looks_like_general_stock(folder_name):
        return tuple(SIZE_CHIPS[numeric] for numeric in ADULT_SIZE_ORDER)
    if selected is not None and len(chips) <= 1:
        return (selected,)
    return chips


def should_use_adult_allsize(folder_name: str, folder_path: str | Path = "") -> bool:
    """True only for non-kids folders that ask for allsize / mixed adult sizes."""
    if path_mentions_kids(folder_name, str(folder_path or "")):
        return False
    return looks_like_general_stock(folder_name)


def size_guide_lines(*, kids: bool = False) -> tuple[str, ...]:
    """Customer-facing size guide."""
    if kids:
        return tuple(KIDS_SIZE_CHIPS[key].label for key in KIDS_SIZE_ORDER)
    seen: list[str] = []
    for numeric in _SIZE_GUIDE_ORDER:
        chip = SIZE_CHIPS[numeric]
        if chip.label not in seen:
            seen.append(chip.label)
    return tuple(seen)
