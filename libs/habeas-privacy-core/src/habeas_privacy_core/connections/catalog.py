"""KD20 vertical catalog helpers — pure Python mirror of seeded DB catalog.

Unit tests can rely on these constants without a database connection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = [
    "APPROACH_LIVE",
    "APPROACH_UPLOAD",
    "CATALOG_BINDINGS",
    "CATALOG_VERTICALS",
    "MATCHING_SYSTEM_COLOR_TOKENS",
    "MATCHING_SYSTEM_LABELS",
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
    "get_bindings_for_system",
    "get_bindings_for_vertical",
    "get_vertical",
    "is_approach_allowed",
    "TEST_MATCHING_SYSTEM_LABELS",
    "list_matching_review_systems",
    "list_verticals",
    "matching_system_color_token",
    "matching_system_label",
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

# Systems that accept template CSV Upload (includes Paylocity Upload mode).
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
        frozenset({APPROACH_LIVE}),
    ),
    VerticalSystemBinding(
        VERTICAL_PEOPLE_HR,
        "hr_alumni",
        frozenset({APPROACH_UPLOAD, APPROACH_LIVE}),
    ),
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
