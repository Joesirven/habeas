"""DROP v1.2.0 name standardization."""

from __future__ import annotations

import json
import unicodedata
import zipfile
from functools import lru_cache
from pathlib import Path

__all__ = ["normalize_name"]


@lru_cache(maxsize=1)
def _load_map(filename: str) -> dict[str, str]:
    """Load transliteration JSON from package data (source tree or --py-files zip)."""
    here = Path(__file__)
    # Source / extracted layout
    candidate = here.parent / "data" / filename
    if candidate.is_file():
        return json.loads(candidate.read_text(encoding="utf-8"))

    # Spark --py-files: __file__ looks like .../drop_normalize.zip/drop_normalize/names.py
    parts = here.parts
    if ".zip" in here.as_posix() or any(p.endswith(".zip") for p in parts):
        zip_path = None
        inner_prefix = []
        for i, part in enumerate(parts):
            if part.endswith(".zip"):
                zip_path = Path(*parts[: i + 1])
                inner_prefix = list(parts[i + 1 : -1])  # drop_normalize
                break
        if zip_path is not None and zip_path.is_file():
            member = "/".join([*inner_prefix, "data", filename])
            with zipfile.ZipFile(zip_path) as zf:
                return json.loads(zf.read(member).decode("utf-8"))

    raise FileNotFoundError(f"transliteration map not found: {filename} (from {here})")


def _apply_char_map(text: str, mapping: dict[str, str]) -> str:
    if not mapping:
        return text
    keys = sorted(mapping.keys(), key=len, reverse=True)
    for char in keys:
        text = text.replace(char, mapping[char])
    return text


def normalize_name(value: str | None) -> str | None:
    """Standardize a first or last name per DROP v1.2.0."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)

    result = value.lower()

    result = _apply_char_map(result, _load_map("transliteration_special_latin.json"))
    result = _apply_char_map(result, _load_map("transliteration_el.json"))
    result = _apply_char_map(result, _load_map("transliteration_cyr.json"))

    result = unicodedata.normalize("NFKD", result)
    result = "".join(ch for ch in result if not unicodedata.combining(ch))

    result = "".join(ch for ch in result if ch.isalnum())

    return result if result else None
