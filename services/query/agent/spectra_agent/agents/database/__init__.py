"""Database Agent - the systems of record.

Looks a value up in the connected enterprise databases, runs a single capped
read-only SELECT when the caller is permitted to, describes a database's schema
so the Brain can aim the next query, and fetches one record by primary key.
Every row it returns becomes citable evidence with its table and key attached.

Switched off with the ``database`` deployment flag.
"""

from __future__ import annotations

from .tools import (
    DATABASE_TOOLS,
    GetDatabaseRecordTool,
    GetDatabaseSchemaTool,
    QueryDatabaseTool,
    connector_for,
)

__all__ = [
    "DATABASE_TOOLS",
    "GetDatabaseRecordTool",
    "GetDatabaseSchemaTool",
    "QueryDatabaseTool",
    "connector_for",
]
