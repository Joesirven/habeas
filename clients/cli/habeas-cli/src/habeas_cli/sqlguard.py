"""SELECT-only SQL validation."""

from __future__ import annotations

import sqlglot
from sqlglot import exp


class UnsafeSqlError(ValueError):
    pass


def assert_select_only(sql: str) -> str:
    """Parse SQL and reject anything that is not a read-only SELECT."""
    statements = sqlglot.parse(sql, read="postgres")
    if len(statements) != 1:
        raise UnsafeSqlError("exactly one SQL statement is allowed")

    statement = statements[0]
    if isinstance(statement, exp.Command):
        raise UnsafeSqlError("DDL and commands are not allowed")

    if not isinstance(statement, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise UnsafeSqlError("only SELECT queries are allowed")

    for node in statement.walk():
        if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create)):
            raise UnsafeSqlError("mutating statements are not allowed")

    return sql.strip()
