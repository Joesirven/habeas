"""Cassandra vendor adapters — restricted_person_id suppression only."""

from cassandra.adapters.stub import suppress_restricted_person_id

__all__ = ["suppress_restricted_person_id"]
