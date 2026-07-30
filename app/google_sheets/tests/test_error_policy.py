"""Error policy classification."""

from habeas_privacy_core.workflow.error_policy import ErrorDisposition, classify_with

from google_sheets.error_policy import GoogleSheetsErrorClassifier


def test_classifies_retryable_errors():
    action = classify_with(GoogleSheetsErrorClassifier(), "rate_limit_exceeded")
    assert action.disposition is ErrorDisposition.RETRYABLE
    assert action.should_insert_retry is True


def test_classifies_terminal_success():
    action = classify_with(GoogleSheetsErrorClassifier(), "not_found")
    assert action.disposition is ErrorDisposition.TERMINAL_SUCCESS
    assert action.terminal_status == "success"


def test_classifies_terminal_error():
    action = classify_with(GoogleSheetsErrorClassifier(), "permission_denied")
    assert action.disposition is ErrorDisposition.TERMINAL_ERROR
    assert action.terminal_status == "abandoned"
