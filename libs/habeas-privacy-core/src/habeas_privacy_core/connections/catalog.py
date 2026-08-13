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
    "UPLOAD_ONLY_SYSTEMS",
    "UPLOAD_SYSTEMS",
    "UPLOAD_TEMPLATE_OPTIONAL_HEADERS",
    "UPLOAD_TEMPLATE_REQUIRED_HEADERS",
    "VERTICAL_BIZDEV",
    "VERTICAL_COMMUNICATIONS",
    "VERTICAL_DATA",
    "VERTICAL_PEOPLE_HR",
    "VERTICAL_TECH",
    "VerticalCatalogEntry",
    "VerticalSystemBinding",
    "get_bindings_for_system",
    "get_bindings_for_vertical",
    "get_vertical",
    "is_approach_allowed",
    "list_verticals",
]

APPROACH_LIVE: Final[str] = "live"
APPROACH_UPLOAD: Final[str] = "upload"

VERTICAL_COMMUNICATIONS: Final[str] = "communications"
VERTICAL_PEOPLE_HR: Final[str] = "people_hr"
VERTICAL_TECH: Final[str] = "tech"
VERTICAL_BIZDEV: Final[str] = "bizdev"
VERTICAL_DATA: Final[str] = "data"

UPLOAD_TEMPLATE_REQUIRED_HEADERS: Final[dict[str, tuple[str, ...]]] = {
    "bizdev_contacts": ("first_name", "last_name", "email"),
    "hr_alumni": ("first_name", "last_name", "email"),
    "paylocity": ("first_name", "last_name", "email"),
}

UPLOAD_TEMPLATE_OPTIONAL_HEADERS: Final[dict[str, tuple[str, ...]]] = {
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
# Upload-only systems — no Live credential invite (KD14).
UPLOAD_ONLY_SYSTEMS: Final[frozenset[str]] = frozenset({"bizdev_contacts", "hr_alumni"})


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


CATALOG_VERTICALS: Final[tuple[VerticalCatalogEntry, ...]] = (
    VerticalCatalogEntry(VERTICAL_COMMUNICATIONS, "Communications", False, 10),
    VerticalCatalogEntry(VERTICAL_PEOPLE_HR, "People/HR", False, 20),
    VerticalCatalogEntry(VERTICAL_TECH, "Tech", False, 30),
    VerticalCatalogEntry(VERTICAL_BIZDEV, "BizDev", False, 40),
    VerticalCatalogEntry(VERTICAL_DATA, "Data", True, 50),
)

CATALOG_BINDINGS: Final[tuple[VerticalSystemBinding, ...]] = (
    VerticalSystemBinding(
        VERTICAL_COMMUNICATIONS,
        "mailchimp",
        frozenset({APPROACH_LIVE, APPROACH_UPLOAD}),
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
        frozenset({APPROACH_UPLOAD}),
    ),
    VerticalSystemBinding(
        VERTICAL_TECH,
        "auth0",
        frozenset({APPROACH_LIVE, APPROACH_UPLOAD}),
    ),
    VerticalSystemBinding(
        VERTICAL_BIZDEV,
        "bizdev_contacts",
        frozenset({APPROACH_UPLOAD}),
    ),
    VerticalSystemBinding(
        VERTICAL_DATA,
        "cassandra",
        frozenset(),
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
