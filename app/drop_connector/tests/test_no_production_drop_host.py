"""T11.4 — tests and deploy configs must not target production DROP API."""

from __future__ import annotations

import re
from pathlib import Path

from drop_connector.config import DEFAULT_DROP_API_BASE_URL

REPO_ROOT = Path(__file__).resolve().parents[3]
SANDBOX_DROP_API_BASE_URL = "https://api.drop.privacy.ca.gov/sandbox"
PRODUCTION_DROP_URL_PATTERN = re.compile(
    r"https://api\.drop\.privacy\.ca\.gov(?!/sandbox)"
)

# Negative-validation tests may mention the bare production host.
ALLOWED_PRODUCTION_URL_PATHS = frozenset(
    {
        REPO_ROOT / "app/drop_connector/tests/test_config.py",
        REPO_ROOT / "app/drop_connector/tests/test_no_production_drop_host.py",
    }
)


def _find_production_drop_urls(path: Path) -> list[str]:
    violations: list[str] = []
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        if PRODUCTION_DROP_URL_PATTERN.search(line):
            violations.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    return violations


def test_connector_default_is_sandbox():
    assert DEFAULT_DROP_API_BASE_URL == SANDBOX_DROP_API_BASE_URL
    assert "/sandbox" in DEFAULT_DROP_API_BASE_URL


def test_cloudbuild_uses_sandbox_drop_host_only():
    cloudbuild_dir = REPO_ROOT / "infra/cloudbuild"
    violations: list[str] = []
    for path in sorted(cloudbuild_dir.glob("*.yaml")):
        text = path.read_text()
        if "drop.privacy.ca.gov" not in text:
            continue
        violations.extend(_find_production_drop_urls(path))
    assert not violations, "Production DROP host in cloudbuild:\n" + "\n".join(violations)


def test_drop_connector_tests_use_sandbox_only():
    tests_dir = REPO_ROOT / "app/drop_connector/tests"
    violations: list[str] = []
    for path in sorted(tests_dir.glob("test_*.py")):
        if path in ALLOWED_PRODUCTION_URL_PATHS:
            continue
        violations.extend(_find_production_drop_urls(path))
    assert not violations, "Production DROP host in connector tests:\n" + "\n".join(
        violations
    )
