"""DROP v1.2.0 name standardization."""

from __future__ import annotations

import json
import unicodedata
from functools import lru_cache
from importlib import resources
__all__ = ["normalize_name"]


@lru_cache(maxsize=1)
def _load_map(filename: str) -> dict[str, str]:
    data = resources.files("drop_normalize.data").joinpath(filename).read_text(encoding="utf-8")
    return json.loads(data)


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
