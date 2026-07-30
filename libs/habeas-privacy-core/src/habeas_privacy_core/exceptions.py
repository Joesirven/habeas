"""Library-wide exceptions."""


class PrivacyCoreError(Exception):
    """Base error for habeas-privacy-core."""


class DropAccessTypeRejectedError(PrivacyCoreError):
    """intake_source='drop' can only ever request delete (KTD10/R16, ADR-32).

    DROP is a suppression-only channel — access/combined request_type would
    imply a reproduction fulfillment path that DROP intake cannot support.
    """
