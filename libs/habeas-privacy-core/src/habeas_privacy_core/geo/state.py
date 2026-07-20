"""US state acronym normalization for BQ filters, rematch, and refresh enqueue.

Assumption A10: served jurisdictions are USPS 50 states + DC until Jose confirms
a different MDR/DROP source of truth (Q6).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal, Mapping

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


# CA DROP sandbox default when payload and filename omit state — only if
# DROP_ALLOW_DEFAULT_REQUESTOR_STATE=CA is set (local sandbox; never default-on).
DEFAULT_DROP_REQUESTOR_STATE = "CA"
DROP_ALLOW_DEFAULT_REQUESTOR_STATE_ENV = "DROP_ALLOW_DEFAULT_REQUESTOR_STATE"

_FILENAME_STATE_TOKEN = re.compile(r"(?:^|_)([A-Za-z]{2})(?=_|\.|$)")

RequestorStateSource = Literal["payload", "filename", "default"]


def served_state_acronyms() -> frozenset[str]:
    """Return the MDR/DROP-served state allowlist (A10: 50 + DC)."""
    return USPS_STATES_PLUS_DC


def resolve_drop_requestor_state(
    *,
    raw_payload: Mapping[str, Any] | None = None,
    source_csv_filename: str | None = None,
) -> tuple[str, RequestorStateSource]:
    """Resolve DROP ``requestor_state`` for thin-spine insert.

    Preference order:
    1. ``raw_payload`` keys ``requestor_state`` / ``state`` (normalized)
    2. USPS token in ``source_csv_filename`` (e.g. ``broker_TX_EMAIL.csv``)
    3. Explicit sandbox override only: env ``DROP_ALLOW_DEFAULT_REQUESTOR_STATE=CA``
       → ``DEFAULT_DROP_REQUESTOR_STATE`` with source ``default``

    Raises:
        InvalidStateAcronymError: state missing from payload and filename and
            sandbox override is off or not ``CA``.
    """
    if raw_payload:
        for key in ("requestor_state", "state"):
            value = raw_payload.get(key)
            if value is None or str(value).strip() == "":
                continue
            try:
                return normalize_state_acronym(str(value)), "payload"
            except InvalidStateAcronymError:
                continue

    if source_csv_filename:
        stem = Path(source_csv_filename).name
        for match in _FILENAME_STATE_TOKEN.finditer(stem):
            token = match.group(1)
            try:
                return normalize_state_acronym(token), "filename"
            except InvalidStateAcronymError:
                continue

    override_raw = os.environ.get(DROP_ALLOW_DEFAULT_REQUESTOR_STATE_ENV, "").strip()
    if not override_raw:
        raise InvalidStateAcronymError(
            "requestor_state is required when payload and filename omit state; "
            f"set {DROP_ALLOW_DEFAULT_REQUESTOR_STATE_ENV}=CA for local sandbox only"
        )
    try:
        override = normalize_state_acronym(override_raw)
    except InvalidStateAcronymError as exc:
        raise InvalidStateAcronymError(
            f"{DROP_ALLOW_DEFAULT_REQUESTOR_STATE_ENV} must be "
            f"{DEFAULT_DROP_REQUESTOR_STATE}; got {override_raw!r}"
        ) from exc
    if override != DEFAULT_DROP_REQUESTOR_STATE:
        raise InvalidStateAcronymError(
            f"{DROP_ALLOW_DEFAULT_REQUESTOR_STATE_ENV} must be "
            f"{DEFAULT_DROP_REQUESTOR_STATE}; got {override}"
        )
    return DEFAULT_DROP_REQUESTOR_STATE, "default"


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
