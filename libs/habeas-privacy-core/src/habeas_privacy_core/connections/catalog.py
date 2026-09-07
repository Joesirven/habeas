"""KD20 vertical catalog helpers — pure Python mirror of seeded DB catalog.

Unit tests can rely on these constants without a database connection.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final

__all__ = [
    "APPROACH_LIVE",
    "APPROACH_UPLOAD",
    "CATALOG_BINDINGS",
    "CATALOG_VERTICALS",
    "CONNECTION_METHOD_LABELS",
    "LIST_CAPABILITY_SOURCE_CATALOG",
    "LIST_CAPABILITY_SOURCE_MAPPING",
    "ListCapability",
    "MANUAL_UPLOAD_LABEL",
    "MATCHING_SYSTEM_COLOR_TOKENS",
    "MATCHING_SYSTEM_LABELS",
    "NDZ_CANONICAL_KEYS",
    "UPLOAD_ONLY_SYSTEMS",
    "UPLOAD_SYSTEMS",
    "SHEET_SYSTEMS",
    "UPLOAD_TEMPLATE_OPTIONAL_HEADERS",
    "UPLOAD_TEMPLATE_REQUIRED_HEADERS",
    "VERTICAL_BIZDEV",
    "VERTICAL_COMMUNICATIONS",
    "VERTICAL_DATA",
    "VERTICAL_PEOPLE_HR",
    "VERTICAL_TECH",
    "VERTICAL_TEST",
    "MatchingReviewSystem",
    "VerticalCatalogEntry",
    "VerticalSystemBinding",
    "connection_method_label",
    "derive_list_capability",
    "filter_dbt_select",
    "get_bindings_for_system",
    "get_bindings_for_vertical",
    "get_vertical",
    "intersect_flood_and_capability",
    "is_approach_allowed",
    "list_capability_from_metadata",
    "TEST_MATCHING_SYSTEM_LABELS",
    "list_matching_review_systems",
    "list_verticals",
    "matching_system_color_token",
    "matching_system_label",
    "upload_allowed",
]

APPROACH_LIVE: Final[str] = "live"
APPROACH_UPLOAD: Final[str] = "upload"

VERTICAL_COMMUNICATIONS: Final[str] = "communications"
VERTICAL_PEOPLE_HR: Final[str] = "people_hr"
VERTICAL_TECH: Final[str] = "tech"
VERTICAL_BIZDEV: Final[str] = "bizdev"
VERTICAL_DATA: Final[str] = "data"
VERTICAL_TEST: Final[str] = "test"

UPLOAD_TEMPLATE_REQUIRED_HEADERS: Final[dict[str, tuple[str, ...]]] = {
    "axios_headquarters": ("first_name", "last_name", "email"),
    "bizdev_contacts": ("first_name", "last_name", "email"),
    "hr_alumni": ("first_name", "last_name", "email"),
    "lever": ("first_name", "last_name", "email"),
    "paylocity": ("first_name", "last_name", "email"),
}

UPLOAD_TEMPLATE_OPTIONAL_HEADERS: Final[dict[str, tuple[str, ...]]] = {
    "axios_headquarters": ("phone", "submitted_at", "notes"),
    "bizdev_contacts": ("phone", "company", "source", "submitted_at", "notes"),
    "hr_alumni": (
        "phone",
        "address",
        "city",
        "state",
        "nickname",
        "left_at",
        "employee_id",
    ),
    "paylocity": ("employee_id", "dob", "phone", "city", "state"),
}

# Systems that accept template CSV Upload (Paylocity Upload mode + Lever
# live-fail CSV fallback). Identifier headers only — not a Lever REST extract.
UPLOAD_SYSTEMS: Final[frozenset[str]] = frozenset(UPLOAD_TEMPLATE_REQUIRED_HEADERS)
# Upload-only systems — no Live approach. Axios HQ stays upload-every-batch.
# Alumni and Contact Us allow Live via owner Google OAuth (not service-account share).
UPLOAD_ONLY_SYSTEMS: Final[frozenset[str]] = frozenset({"axios_headquarters"})
SHEET_SYSTEMS: Final[frozenset[str]] = frozenset(
    {"google_sheets", "bizdev_contacts", "hr_alumni"}
)

# Matching-review titles (inbox / matching-by-system). Slugs stay catalog ids.
# Contact Us + Alumni are the Google Sheet sources for BizDev / People-HR.
MATCHING_SYSTEM_LABELS: Final[dict[str, str]] = {
    "axios_headquarters": "Axios HQ",
    "paylocity": "Paylocity",
    "lever": "Lever",
    "auth0": "Auth0",
    "google_sheets": "Google Sheets",
    "bizdev_contacts": "Contact Us Google Sheet",
    "hr_alumni": "Alumni Google Sheet",
    "cassandra": "CA DROP",
}

# Test vertical simulation — internal slugs stay catalog ids; labels are not
# CA DROP or Alumni. CA DROP is the request source, never a Test system title.
TEST_MATCHING_SYSTEM_LABELS: Final[dict[str, str]] = {
    "cassandra": "System A",
    "hr_alumni": "System B",
}

# Habeas-adjacent tokens for inbox color + title (no purple / terracotta).
MATCHING_SYSTEM_COLOR_TOKENS: Final[dict[str, str]] = {
    "axios_headquarters": "mid",
    "paylocity": "navy",
    "lever": "light",
    "auth0": "slate",
    "google_sheets": "sky",
    "bizdev_contacts": "teal",
    "hr_alumni": "slate",
    "cassandra": "navy",
}

# Owner-wizard method labels (display-only; APPROACH_LIVE stays "live").
# Canonical slugs only — alias axios_hq via _SYSTEM_ALIASES, not this map.
MANUAL_UPLOAD_LABEL: Final[str] = "Manual upload"

CONNECTION_METHOD_LABELS: Final[dict[str, str]] = {
    "paylocity": "SFTP",
    "lever": "Lever API",
    "auth0": "Management API",
    "hr_alumni": "Google sign-in",
    "bizdev_contacts": "Google sign-in",
    "google_sheets": "Google Sheets",
    "alumni_google_sheet": "Google Sheets",
    "contact_us_google_sheet": "Google Sheets",
}

_SYSTEM_ALIASES: Final[dict[str, str]] = {
    "axios_hq": "axios_headquarters",
}


@dataclass(frozen=True)
class VerticalCatalogEntry:
    vertical_id: str
    display_label: str
    view_only: bool
    sort_order: int


@dataclass(frozen=True)
class VerticalSystemBinding:
    vertical_id: str
    system: str
    allowed_approaches: frozenset[str]


@dataclass(frozen=True)
class MatchingReviewSystem:
    """One matching-review identity: (vertical, system) from KD20 bindings."""

    vertical_id: str
    vertical_label: str
    system: str
    system_label: str
    color_token: str


CATALOG_VERTICALS: Final[tuple[VerticalCatalogEntry, ...]] = (
    VerticalCatalogEntry(VERTICAL_COMMUNICATIONS, "Communications", False, 10),
    VerticalCatalogEntry(VERTICAL_PEOPLE_HR, "People/HR", False, 20),
    VerticalCatalogEntry(VERTICAL_TECH, "Tech", False, 30),
    VerticalCatalogEntry(VERTICAL_BIZDEV, "BizDev", False, 40),
    VerticalCatalogEntry(VERTICAL_DATA, "Data", True, 50),
    VerticalCatalogEntry(VERTICAL_TEST, "Test vertical", False, 60),
)

CATALOG_BINDINGS: Final[tuple[VerticalSystemBinding, ...]] = (
    VerticalSystemBinding(
        VERTICAL_COMMUNICATIONS,
        "axios_headquarters",
        frozenset({APPROACH_UPLOAD}),
    ),
    VerticalSystemBinding(
        VERTICAL_PEOPLE_HR,
        "paylocity",
        frozenset({APPROACH_UPLOAD, APPROACH_LIVE}),
    ),
    VerticalSystemBinding(
        VERTICAL_PEOPLE_HR,
        "lever",
        frozenset({APPROACH_UPLOAD, APPROACH_LIVE}),
    ),
    VerticalSystemBinding(
        VERTICAL_PEOPLE_HR,
        "hr_alumni",
        frozenset({APPROACH_UPLOAD, APPROACH_LIVE}),
    ),
    # Auth0 keeps APPROACH_UPLOAD (SPA complete-wizard quirk); upload_allowed is False.
    VerticalSystemBinding(
        VERTICAL_TECH,
        "auth0",
        frozenset({APPROACH_LIVE, APPROACH_UPLOAD}),
    ),
    VerticalSystemBinding(
        VERTICAL_BIZDEV,
        "bizdev_contacts",
        frozenset({APPROACH_UPLOAD, APPROACH_LIVE}),
    ),
    VerticalSystemBinding(
        VERTICAL_DATA,
        "cassandra",
        frozenset(),
    ),
    # Simulation vertical — two data systems (internal slugs). Display labels
    # are System A / System B. CA DROP is the request source, not a Test title.
    VerticalSystemBinding(
        VERTICAL_TEST,
        "cassandra",
        frozenset(),
    ),
    VerticalSystemBinding(
        VERTICAL_TEST,
        "hr_alumni",
        frozenset({APPROACH_UPLOAD, APPROACH_LIVE}),
    ),
)

_VERTICAL_BY_ID: Final[dict[str, VerticalCatalogEntry]] = {
    entry.vertical_id: entry for entry in CATALOG_VERTICALS
}

_BINDINGS_BY_VERTICAL: Final[dict[str, tuple[VerticalSystemBinding, ...]]] = {}
_BINDINGS_BY_SYSTEM: Final[dict[str, tuple[VerticalSystemBinding, ...]]] = {}

for _binding in CATALOG_BINDINGS:
    _BINDINGS_BY_VERTICAL.setdefault(_binding.vertical_id, []).append(_binding)
    _BINDINGS_BY_SYSTEM.setdefault(_binding.system, []).append(_binding)

for _vertical_id, _bindings in list(_BINDINGS_BY_VERTICAL.items()):
    _BINDINGS_BY_VERTICAL[_vertical_id] = tuple(_bindings)

for _system, _bindings in list(_BINDINGS_BY_SYSTEM.items()):
    _BINDINGS_BY_SYSTEM[_system] = tuple(_bindings)


def get_vertical(vertical_id: str) -> VerticalCatalogEntry:
    """Return a catalog vertical by id."""
    try:
        return _VERTICAL_BY_ID[vertical_id]
    except KeyError as exc:
        raise ValueError(f"unknown vertical: {vertical_id}") from exc


def list_verticals() -> list[VerticalCatalogEntry]:
    """Return catalog verticals in sort order."""
    return list(CATALOG_VERTICALS)


def get_bindings_for_vertical(vertical_id: str) -> list[VerticalSystemBinding]:
    """Return active system bindings for a vertical."""
    get_vertical(vertical_id)
    return list(_BINDINGS_BY_VERTICAL.get(vertical_id, ()))


def get_bindings_for_system(system: str) -> list[VerticalSystemBinding]:
    """Return vertical bindings that include a system."""
    return list(_BINDINGS_BY_SYSTEM.get(system, ()))


def is_approach_allowed(vertical_id: str, system: str, approach: str) -> bool:
    """Return whether an approach is allowed for a vertical-system pair."""
    for binding in get_bindings_for_vertical(vertical_id):
        if binding.system == system:
            return approach in binding.allowed_approaches
    return False


def _canonical_system(system: str) -> str:
    normalized = system.strip().lower()
    return _SYSTEM_ALIASES.get(normalized, normalized)


def matching_system_label(system: str, *, vertical_id: str | None = None) -> str:
    """Inbox / matching-by-system title for a catalog system slug.

    Test vertical uses System A / System B. Other verticals keep the real
    connection name (Alumni Google Sheet, Paylocity, CA DROP on Data, …).
    """
    normalized = system.strip().lower()
    vertical = (vertical_id or "").strip().lower()
    if vertical == VERTICAL_TEST and normalized in TEST_MATCHING_SYSTEM_LABELS:
        return TEST_MATCHING_SYSTEM_LABELS[normalized]
    if normalized in MATCHING_SYSTEM_LABELS:
        return MATCHING_SYSTEM_LABELS[normalized]
    return normalized.replace("_", " ").title() if normalized else system


def connection_method_label(system: str) -> str | None:
    """Owner-wizard method label for a catalog system slug."""
    canonical = _canonical_system(system)
    return CONNECTION_METHOD_LABELS.get(canonical)


def upload_allowed(system: str) -> bool:
    """Advertise-Upload flag for owner wizard cards.

    True only when template headers exist in ``UPLOAD_TEMPLATE_REQUIRED_HEADERS``.
    Do not infer Upload from ``allowed_approaches`` / ``APPROACH_UPLOAD``. Auth0
    may still bind ``APPROACH_UPLOAD`` (SPA complete-wizard quirk) while this
    returns False — keep that binding; do not add Auth0 here.
    """
    return _canonical_system(system) in UPLOAD_TEMPLATE_REQUIRED_HEADERS


def matching_system_color_token(system: str) -> str:
    """Color token for inbox system chrome (maps to frontend classes)."""
    return MATCHING_SYSTEM_COLOR_TOKENS.get(system.strip().lower(), "slate")


def list_matching_review_systems(
    *,
    vertical_ids: frozenset[str] | None = None,
) -> list[MatchingReviewSystem]:
    """Catalog (vertical, system) pairs for matching inbox fan-out and filters.

    Includes Contact Us (``bizdev_contacts``) and Alumni (``hr_alumni``).
    Unscoped calls (``vertical_ids`` is None) omit ``VERTICAL_TEST`` so Legal
    and admin inboxes do not clone the assignment-scoped simulation. Pass
    ``vertical_ids`` that include ``test`` to include System A / System B.
    """
    allowed = None
    if vertical_ids is not None:
        allowed = {vertical_id.strip().lower() for vertical_id in vertical_ids if vertical_id.strip()}
    rows: list[MatchingReviewSystem] = []
    for binding in CATALOG_BINDINGS:
        if allowed is not None:
            if binding.vertical_id not in allowed:
                continue
        elif binding.vertical_id == VERTICAL_TEST:
            continue
        vertical = get_vertical(binding.vertical_id)
        rows.append(
            MatchingReviewSystem(
                vertical_id=binding.vertical_id,
                vertical_label=vertical.display_label,
                system=binding.system,
                system_label=matching_system_label(
                    binding.system, vertical_id=binding.vertical_id
                ),
                color_token=matching_system_color_token(binding.system),
            )
        )
    return rows


LIST_CAPABILITY_SOURCE_MAPPING: Final[str] = "mapping"
LIST_CAPABILITY_SOURCE_CATALOG: Final[str] = "catalog"

# NDZ enablement requires the four canonical parts. full_name is UI convenience
# only and never turns NDZ on by itself (KD5 / A1).
NDZ_CANONICAL_KEYS: Final[tuple[str, ...]] = (
    "first_name",
    "last_name",
    "dob",
    "zip",
)


@dataclass(frozen=True)
class ListCapability:
    """Derived Email / Phone / NDZ support. Owners never toggle these."""

    email: bool
    phone: bool
    ndz: bool
    source: str

    @property
    def enabled_kinds(self) -> tuple[str, ...]:
        kinds: list[str] = []
        if self.email:
            kinds.append("email")
        if self.phone:
            kinds.append("phone")
        if self.ndz:
            kinds.append("ndz")
        return tuple(kinds)

    @property
    def enabled_list_types(self) -> tuple[str, ...]:
        types: list[str] = []
        if self.email:
            types.append("Email")
        if self.phone:
            types.append("Phone")
        if self.ndz:
            types.append("NDZ")
        return tuple(types)

    def allows_list_type(self, list_type: str) -> bool:
        return str(list_type) in self.enabled_list_types

    def as_dict(self) -> dict[str, Any]:
        return {
            "email": self.email,
            "phone": self.phone,
            "ndz": self.ndz,
            "source": self.source,
            "enabled_list_types": list(self.enabled_list_types),
        }


def _mapping_has(mapping: dict[str, str], key: str) -> bool:
    value = mapping.get(key)
    return isinstance(value, str) and bool(value.strip())


def derive_list_capability(
    system: str,
    column_mapping: dict[str, str] | None = None,
) -> ListCapability:
    """Email when ``email`` mapped; Phone when ``phone`` mapped; NDZ iff all four.

    Auth0 is catalog email+phone, NDZ never. CA DROP / Cassandra is never a
    capability source. Partial NDZ stays off; save is still allowed.
    """
    canonical = _canonical_system(system)
    if canonical == "auth0":
        return ListCapability(
            email=True,
            phone=True,
            ndz=False,
            source=LIST_CAPABILITY_SOURCE_CATALOG,
        )
    if canonical == "cassandra":
        return ListCapability(
            email=False,
            phone=False,
            ndz=False,
            source=LIST_CAPABILITY_SOURCE_CATALOG,
        )
    mapping = {
        str(key).strip(): str(value).strip()
        for key, value in (column_mapping or {}).items()
        if str(key).strip() and str(value).strip()
    }
    return ListCapability(
        email=_mapping_has(mapping, "email"),
        phone=_mapping_has(mapping, "phone"),
        ndz=all(_mapping_has(mapping, key) for key in NDZ_CANONICAL_KEYS),
        source=LIST_CAPABILITY_SOURCE_MAPPING,
    )


def _column_mapping_from_metadata(metadata: dict[str, Any] | None) -> dict[str, str] | None:
    if not metadata:
        return None
    raw = metadata.get("column_mapping")
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict):
        return None
    out: dict[str, str] = {}
    for key, value in raw.items():
        canonical = str(key).strip()
        source = str(value).strip()
        if canonical and source:
            out[canonical] = source
    return out or None


def list_capability_from_metadata(
    system: str,
    metadata: dict[str, Any] | None = None,
) -> ListCapability:
    """Recompute capability from persisted mapping (or Auth0 catalog)."""
    return derive_list_capability(system, _column_mapping_from_metadata(metadata))


def intersect_flood_and_capability(
    flood: list[str],
    capability: ListCapability,
) -> list[str]:
    """Flood valve ∩ mapped/catalog capability. Empty means never enqueue."""
    allowed = set(capability.enabled_list_types)
    return [item for item in flood if item in allowed]


def filter_dbt_select(
    models: tuple[str, ...],
    capability: ListCapability,
) -> tuple[str, ...]:
    """Keep staging models; drop per-kind marts the capability does not enable."""
    enabled = set(capability.enabled_kinds)
    kept: list[str] = []
    for model in models:
        kind: str | None = None
        if model.endswith("_email_hash"):
            kind = "email"
        elif model.endswith("_phone_hash"):
            kind = "phone"
        elif model.endswith("_ndz_hash"):
            kind = "ndz"
        if kind is None or kind in enabled:
            kept.append(model)
    return tuple(kept)
