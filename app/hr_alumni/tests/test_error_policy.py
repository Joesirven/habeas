"""Sheet worker error classification from core."""

from habeas_privacy_core.sheet_worker.error_policy import SheetWorkerErrorClassifier
from habeas_privacy_core.workflow.error_policy import ErrorDisposition


def test_sheet_worker_error_classifier_retryable():
    classifier = SheetWorkerErrorClassifier()
    assert classifier.classify("rate_limit_exceeded") == ErrorDisposition.RETRYABLE


def test_sheet_worker_error_classifier_terminal_error():
    classifier = SheetWorkerErrorClassifier()
    assert classifier.classify("permission_denied") == ErrorDisposition.TERMINAL_ERROR
