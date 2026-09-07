"""DROP v1.2.0 standardization and hashing for external vertical extracts."""

from __future__ import annotations

import base64
import hashlib
import re
import unicodedata
from datetime import date, datetime

__all__ = [
    "assert_opaque_hash",
    "email_hash_from_raw",
    "hash_std",
    "ndz_hash_from_parts",
    "phone_hash_from_raw",
    "standardize_dob",
    "standardize_email",
    "standardize_name",
    "standardize_phone",
    "standardize_zip",
]

# SHA-256 digest → standard Base64 is always 44 characters with one trailing '='.
_SHA256_B64_LEN = 44
_E164_DIGIT_MIN = 7
_E164_DIGIT_MAX = 15
_PHONE_PUNCT = frozenset("+-().")

_WHITESPACE = re.compile(r"\s+")
_NON_DIGIT = re.compile(r"\D")
_NON_ALNUM = re.compile(r"[^a-zA-Z0-9]")
_YYYYMMDD = re.compile(r"^\d{8}$")
_MONTH_DAY_YEAR = re.compile(
    r"^(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})$"
)
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_SLASH_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")

# DROP v1.2.0 transliteration maps (from drop_normalize data/*.json)
_SPECIAL_LATIN: dict[str, str] = {
    "ß": "ss",
    "æ": "ae",
    "œ": "oe",
    "ø": "o",
    "ð": "d",
    "þ": "th",
    "ł": "l",
    "đ": "d",
    "ħ": "h",
    "ŋ": "n",
    "ı": "i",
    "ĳ": "ij",
    "ŀ": "l",
}
_GREEK: dict[str, str] = {
    "α": "a",
    "β": "v",
    "γ": "g",
    "δ": "d",
    "ε": "e",
    "ζ": "z",
    "η": "i",
    "θ": "th",
    "ι": "i",
    "κ": "k",
    "λ": "l",
    "μ": "m",
    "ν": "n",
    "ξ": "x",
    "ο": "o",
    "π": "p",
    "ρ": "r",
    "σ": "s",
    "ς": "s",
    "τ": "t",
    "υ": "y",
    "φ": "f",
    "χ": "ch",
    "ψ": "ps",
    "ω": "o",
    "ά": "a",
    "έ": "e",
    "ί": "i",
    "ή": "i",
    "ύ": "y",
    "ό": "o",
    "ώ": "o",
    "ϊ": "i",
    "ΐ": "i",
    "ϋ": "y",
    "ΰ": "y",
}
_CYRILLIC: dict[str, str] = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "yo",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "kh",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "shch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
    "є": "e",
    "і": "i",
    "ї": "i",
    "ґ": "g",
    "ў": "u",
}


def hash_std(value: str) -> str:
    """Hash a standardized string: SHA-256 over UTF-8, output Base64."""
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def assert_opaque_hash(value: str, *, label: str) -> str:
    """Return a stripped opaque CPPA hash, or raise ``ValueError``.

    Requires SHA-256 digest Base64 shape (length 44, trailing ``=``, body
    alphanumeric / ``+`` / ``/``). Also rejects empty / whitespace-only values,
    internal whitespace, ``@`` (email plaintext), and digit-heavy phone-like
    strings as belt-and-suspenders. Exception messages never include the
    rejected value — only ``{label} must not contain plaintext``.
    """
    if not isinstance(value, str):
        value = str(value)
    cleaned = value.strip()
    if not cleaned or any(ch.isspace() for ch in cleaned):
        raise ValueError(f"{label} must not contain plaintext")
    if "@" in cleaned:
        raise ValueError(f"{label} must not contain plaintext")
    if _looks_like_phone_plaintext(cleaned):
        raise ValueError(f"{label} must not contain plaintext")
    if not _is_sha256_b64_shape(cleaned):
        raise ValueError(f"{label} must not contain plaintext")
    return cleaned


def _is_sha256_b64_shape(value: str) -> bool:
    if len(value) != _SHA256_B64_LEN or not value.endswith("="):
        return False
    body = value[:-1]
    return all(ch.isalnum() or ch in "+/" for ch in body)


def _looks_like_phone_plaintext(value: str) -> bool:
    """True when *value* resembles national / E.164 phone digits, not a digest."""
    if _is_sha256_b64_shape(value):
        return False
    digits = _NON_DIGIT.sub("", value)
    if not (_E164_DIGIT_MIN <= len(digits) <= _E164_DIGIT_MAX):
        return False
    significant = [ch for ch in value if not ch.isspace()]
    if not significant:
        return False
    phone_like = sum(1 for ch in significant if ch.isdigit() or ch in _PHONE_PUNCT)
    return (phone_like / len(significant)) >= 0.8


def standardize_email(value: str | None) -> str | None:
    """Remove all whitespace and lowercase."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)

    result = _WHITESPACE.sub("", value).lower()
    return result if result else None


def standardize_phone(value: str | None) -> str | None:
    """Strip non-numeric characters; keep last 10 digits (or all if fewer)."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)

    digits = _NON_DIGIT.sub("", value)
    if not digits:
        return None

    if len(digits) > 10:
        digits = digits[-10:]

    return digits


def _apply_char_map(text: str, mapping: dict[str, str]) -> str:
    if not mapping:
        return text
    keys = sorted(mapping.keys(), key=len, reverse=True)
    for char in keys:
        text = text.replace(char, mapping[char])
    return text


def standardize_name(value: str | None) -> str | None:
    """Standardize a first or last name per DROP v1.2.0."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)

    result = value.lower()
    result = _apply_char_map(result, _SPECIAL_LATIN)
    result = _apply_char_map(result, _GREEK)
    result = _apply_char_map(result, _CYRILLIC)
    result = unicodedata.normalize("NFKD", result)
    result = "".join(ch for ch in result if not unicodedata.combining(ch))
    result = "".join(ch for ch in result if ch.isalnum())
    return result if result else None


def _format_date(d: date) -> str:
    return d.strftime("%Y%m%d")


def standardize_dob(value: str | date | datetime | None) -> str | None:
    """Convert to YYYYMMDD (four-digit year)."""
    if value is None:
        return None

    if isinstance(value, datetime):
        return _format_date(value.date())
    if isinstance(value, date):
        return _format_date(value)

    text = str(value).strip()
    if not text:
        return None

    if _YYYYMMDD.match(text):
        return text

    iso = _ISO_DATE.match(text)
    if iso:
        return f"{iso.group(1)}{iso.group(2)}{iso.group(3)}"

    slash = _SLASH_DATE.match(text)
    if slash:
        month, day, year = int(slash.group(1)), int(slash.group(2)), int(slash.group(3))
        try:
            return _format_date(date(year, month, day))
        except ValueError:
            return None

    month_day_year = _MONTH_DAY_YEAR.match(text)
    if month_day_year:
        try:
            parsed = datetime.strptime(
                f"{month_day_year.group('month')} {month_day_year.group('day')} "
                f"{month_day_year.group('year')}",
                "%B %d %Y",
            )
            return _format_date(parsed.date())
        except ValueError:
            return None

    for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
            return _format_date(parsed.date())
        except ValueError:
            continue

    return None


def standardize_zip(value: str | None) -> str | None:
    """Alphanumeric only, lowercase, strip leading zeros, first five characters."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)

    text = value.strip()
    if not text:
        return None

    if "-" in text:
        text = text.split("-", 1)[0]

    text = _NON_ALNUM.sub("", text).lower()
    if not text:
        return None

    text = text.lstrip("0") or "0"
    return text[:5]


def email_hash_from_raw(value: str | None) -> str | None:
    """Standardize an email and return its DROP hash, or None when empty."""
    standardized = standardize_email(value)
    if standardized is None:
        return None
    return hash_std(standardized)


def phone_hash_from_raw(value: str | None) -> str | None:
    """Standardize a phone number and return its DROP hash, or None when empty."""
    standardized = standardize_phone(value)
    if standardized is None:
        return None
    return hash_std(standardized)


def ndz_hash_from_parts(
    first_name: str | None,
    last_name: str | None,
    dob: str | date | datetime | None,
    zip_code: str | None,
) -> str | None:
    """Composite NDZ hash: hash(fn)||hash(ln)||hash(dob)||hash(zip), then hash again.

    Matches drop_normalize.ndz_concatenated_hash. Returns None if any part is missing.
    """
    fn_std = standardize_name(first_name)
    ln_std = standardize_name(last_name)
    dob_std = standardize_dob(dob)
    zip_std = standardize_zip(zip_code)

    if fn_std is None or ln_std is None or dob_std is None or zip_std is None:
        return None

    concatenated = (
        hash_std(fn_std) + hash_std(ln_std) + hash_std(dob_std) + hash_std(zip_std)
    )
    return hash_std(concatenated)
