"""US state acronym normalization for BQ filters, rematch, and refresh enqueue.

Assumption A10: served jurisdictions are USPS 50 states + DC until Jose confirms
a different MDR/DROP source of truth (Q6).
"""

from __future__ import annotations

# Fixed allowlist — USPS 50 states + District of Columbia (A10).
USPS_STATES_PLUS_DC: frozenset[str] = frozenset(
    {
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "DC",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
    }
)

# Small explicit alias table — full names / common variants → USPS.
_STATE_ALIASES: dict[str, str] = {
    "CALIFORNIA": "CA",
    "NEW YORK": "NY",
    "TEXAS": "TX",
    "FLORIDA": "FL",
    "DISTRICT OF COLUMBIA": "DC",
    "WASHINGTON DC": "DC",
    "WASHINGTON D.C.": "DC",
}


class InvalidStateAcronymError(ValueError):
    """Raised when a value cannot be normalized to a served USPS state code."""


def served_state_acronyms() -> frozenset[str]:
    """Return the MDR/DROP-served state allowlist (A10: 50 + DC)."""
    return USPS_STATES_PLUS_DC


def normalize_state_acronym(
    value: str,
    *,
    require_served: bool = True,
) -> str:
    """Trim, upper-case, apply known aliases; optionally enforce allowlist.

    Args:
        value: Raw state string (acronym or known alias).
        require_served: When True (default), reject codes outside
            ``USPS_STATES_PLUS_DC``. When False, accept any two-letter code
            after normalize (for transitional call sites).

    Returns:
        Normalized two-letter USPS acronym.

    Raises:
        InvalidStateAcronymError: empty, unresolvable, or not on allowlist.
    """
    if value is None:
        raise InvalidStateAcronymError("state is required")

    raw = str(value).strip().upper()
    if not raw:
        raise InvalidStateAcronymError("state is required")

    # Strip trailing period from abbreviations like "D.C."
    collapsed = " ".join(raw.replace(".", " ").split())
    mapped = _STATE_ALIASES.get(collapsed) or _STATE_ALIASES.get(raw)
    if mapped is not None:
        code = mapped
    elif len(raw) == 2 and raw.isalpha():
        code = raw
    else:
        raise InvalidStateAcronymError(f"unrecognized state: {value!r}")

    if require_served and code not in USPS_STATES_PLUS_DC:
        raise InvalidStateAcronymError(f"state not in served allowlist: {code}")

    return code
