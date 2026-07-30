"""Auth0 error policy classification."""

import pytest

from auth0.error_policy import Auth0ErrorClassifier
from habeas_privacy_core.workflow.error_policy import ErrorDisposition, classify_with


@pytest.mark.parametrize(
    ("error_code", "expected"),
    [
        ("user_not_found", ErrorDisposition.TERMINAL_SUCCESS),
        ("already_blocked", ErrorDisposition.TERMINAL_SUCCESS),
        ("rate_limited", ErrorDisposition.RETRYABLE),
        ("permission_denied", ErrorDisposition.TERMINAL_ERROR),
        ("mystery_error", ErrorDisposition.ABANDON),
    ],
)
def test_auth0_error_classifier(error_code, expected):
    classifier = Auth0ErrorClassifier()
    assert classifier.classify(error_code) == expected


def test_auth0_error_policy_terminal_action():
    action = classify_with(Auth0ErrorClassifier(), "user_not_found")
    assert action.terminal_status == "success"
    assert action.should_insert_retry is False
