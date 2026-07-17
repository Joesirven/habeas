"""DROP v1.2.0 NDZ composite hashing."""

from __future__ import annotations

from drop_normalize.dob import normalize_dob
from drop_normalize.hashing import hash_std
from drop_normalize.names import normalize_name
from drop_normalize.zipcode import normalize_zip

__all__ = ["ndz_concatenated_hash", "ndz_field_hashes"]


def ndz_field_hashes(
    first_name: str | None,
    last_name: str | None,
    dob: str | None,
    zip_code: str | None,
) -> dict[str, str | None]:
    """Return standardized values and per-field Base64 hashes for NDZ debugging."""
    fn_std = normalize_name(first_name)
    ln_std = normalize_name(last_name)
    dob_std = normalize_dob(dob)
    zip_std = normalize_zip(zip_code)

    return {
        "first_name_std": fn_std,
        "last_name_std": ln_std,
        "dob_std": dob_std,
        "zip_std": zip_std,
        "first_name_hash": hash_std(fn_std) if fn_std is not None else None,
        "last_name_hash": hash_std(ln_std) if ln_std is not None else None,
        "dob_hash": hash_std(dob_std) if dob_std is not None else None,
        "zip_hash": hash_std(zip_std) if zip_std is not None else None,
    }


def ndz_concatenated_hash(
    first_name: str | None,
    last_name: str | None,
    dob: str | None,
    zip_code: str | None,
) -> str | None:
    """Composite NDZ hash: hash(fn)||hash(ln)||hash(dob)||hash(zip), then hash again."""
    fields = ndz_field_hashes(first_name, last_name, dob, zip_code)
    parts = [
        fields["first_name_hash"],
        fields["last_name_hash"],
        fields["dob_hash"],
        fields["zip_hash"],
    ]
    if any(part is None for part in parts):
        return None

    concatenated = "".join(parts)  # type: ignore[arg-type]
    return hash_std(concatenated)
