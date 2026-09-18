"""The SQL security boundary.

Everything the Database Agent (or any other caller) wants to run against a
customer database passes through :class:`SqlGuard` first.  The guard is
*allow-list shaped*: a statement is rejected unless it is provably a single
read-only ``SELECT`` over approved tables, with a bounded row count.

Checks, in order:

1. **One statement only** - comments are normalised away first, so
   ``SELECT 1; DROP TABLE t`` and ``SELECT 1 -- \\n; DROP TABLE t`` both parse
   as two statements and are rejected.  This blocks stacked-query injection.
2. **SELECT / WITH ... SELECT only** - anything else is refused by statement
   type, not by string matching.
3. **Forbidden keywords** - DROP, DELETE, UPDATE, INSERT, ALTER, TRUNCATE,
   CREATE, GRANT, REVOKE, MERGE, CALL, EXEC, COPY, ATTACH, PRAGMA, ``INTO``
   (which covers ``INTO OUTFILE`` / ``INTO DUMPFILE``) and friends.  The scan
   runs on the comment-stripped text with string literals and quoted
   identifiers masked, so ``DR/**/OP`` and ``-- \\nDROP`` are caught while a
   legitimate ``WHERE name = 'Drop Table Inc'`` is not.
4. **Table allow-list** - every identifier used in FROM/JOIN must be in the
   per-source allow-list (CTE names defined by the same statement are allowed).
5. **Row cap** - a missing top-level LIMIT is appended, an oversized one is
   lowered to ``settings.sql_max_rows``.
6. **Bound parameters only** - values are never concatenated into SQL.
   :func:`SqlGuard.build_select` emits placeholders plus a params mapping, and
   ``?``-style placeholders are rewritten to named ones.

:class:`~spectra_connectors.sql_session.ReadOnlySession` (re-exported here) adds
the runtime half: statement timeout plus a hard fetch cap.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

import sqlparse
from spectra_config import get_settings
from spectra_config.logging import get_logger
from sqlparse.sql import Identifier, IdentifierList, Statement, Token
from sqlparse.tokens import CTE, DML, Keyword, Number

from .errors import SqlGuardError
from .sql_session import ReadOnlySession
from .sql_types import ValidatedSql

log = get_logger(__name__)

__all__ = ["SqlGuard", "ValidatedSql", "ReadOnlySession", "quote_identifier", "FORBIDDEN_KEYWORDS"]

GENERIC = "generic"
POSTGRES = "postgres"
MYSQL = "mysql"
SQLITE = "sqlite"

#: Keywords that can never appear in a read-only statement.  ``INTO`` covers
#: ``SELECT ... INTO OUTFILE`` (MySQL file write) and ``SELECT ... INTO t``
#: (PostgreSQL table creation).
FORBIDDEN_KEYWORDS: frozenset[str] = frozenset(
    {
        "ALTER", "ATTACH", "BEGIN", "BENCHMARK", "CALL", "COMMIT", "COPY", "CREATE",
        "DEALLOCATE", "DELETE", "DETACH", "DO", "DROP", "DUMPFILE", "EXEC", "EXECUTE",
        "GRANT", "INSERT", "INTO", "LOAD_FILE", "LOCK", "MERGE", "OUTFILE", "PRAGMA",
        "PREPARE", "REINDEX", "RENAME", "REVOKE", "ROLLBACK", "SAVEPOINT", "SET",
        "SHUTDOWN", "SLEEP", "TRUNCATE", "UNLOCK", "UPDATE", "UPSERT", "VACUUM",
        "XP_CMDSHELL",
    }
)

_KEYWORD_SCAN = re.compile(r"\b(" + "|".join(sorted(FORBIDDEN_KEYWORDS)) + r")\b", re.IGNORECASE)
_LITERAL_SCAN = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|`(?:[^`]|``)*`", re.DOTALL)
_NAMED_PARAM = re.compile(r"(?<![:\w]):([A-Za-z_][A-Za-z0-9_]*)")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_EXECUTABLE_COMMENT = re.compile(r"/\*!")
_ORDER_DIRECTIONS = frozenset({"ASC", "DESC"})
_JOIN_SOURCES = frozenset({"FROM", "JOIN", "STRAIGHT_JOIN"})
_QUOTES: Mapping[str, tuple[str, str]] = {
    POSTGRES: ('"', '"'),
    SQLITE: ('"', '"'),
    MYSQL: ("`", "`"),
    GENERIC: ('"', '"'),
}


def quote_identifier(name: str, dialect: str = GENERIC) -> str:
    """Quote a *validated* identifier for ``dialect``."""
    if not _IDENTIFIER_RE.match(name or ""):
        raise SqlGuardError(f"invalid identifier {name!r}: expected ^[A-Za-z_][A-Za-z0-9_]{{0,63}}$")
    open_quote, close_quote = _QUOTES.get(dialect, _QUOTES[GENERIC])
    return f"{open_quote}{name}{close_quote}"


class SqlGuard:
    """Validates and rewrites statements for one source."""

    def __init__(
        self,
        allowed_tables: Sequence[str] | None = None,
        *,
        max_rows: int | None = None,
        dialect: str = GENERIC,
    ) -> None:
        settings = get_settings()
        self._max_rows = int(max_rows or settings.sql_max_rows)
        self._dialect = dialect
        self._allowed: frozenset[str] | None = (
            None if allowed_tables is None else frozenset(name.lower() for name in allowed_tables)
        )

    @property
    def max_rows(self) -> int:
        return self._max_rows

    @property
    def dialect(self) -> str:
        return self._dialect

    @property
    def allowed_tables(self) -> frozenset[str] | None:
        return self._allowed

    def with_tables(self, allowed_tables: Sequence[str]) -> SqlGuard:
        """Return a new guard restricted to ``allowed_tables`` (never mutates)."""
        return SqlGuard(allowed_tables, max_rows=self._max_rows, dialect=self._dialect)

    # -- validation -------------------------------------------------------
    def validate(
        self,
        sql: str,
        params: Mapping[str, Any] | Sequence[Any] | None = None,
    ) -> ValidatedSql:
        """Return a :class:`ValidatedSql` or raise :class:`SqlGuardError`."""
        if not sql or not sql.strip():
            raise SqlGuardError("empty statement")
        if _EXECUTABLE_COMMENT.search(sql):
            raise SqlGuardError("MySQL executable comments (/*! ... */) are not allowed")

        normalised = sqlparse.format(sql, strip_comments=True).strip().rstrip(";").strip()
        if not normalised:
            raise SqlGuardError("statement contains no executable SQL once comments are removed")

        statement = self._single_statement(normalised)
        self._assert_select(statement)
        self._assert_no_forbidden_keywords(normalised)

        cte_names = _collect_cte_names(statement)
        tables = _collect_tables(statement) - cte_names
        self._assert_tables_allowed(tables)

        capped_sql, limit = self._enforce_limit(statement, normalised)
        final_sql, bound = _bind_parameters(capped_sql, params)
        return ValidatedSql(sql=final_sql, params=bound, tables=frozenset(tables), limit=limit)

    def _single_statement(self, normalised: str) -> Statement:
        parsed = [stmt for stmt in sqlparse.parse(normalised) if _is_meaningful(stmt)]
        if not parsed:
            raise SqlGuardError("statement contains no executable SQL")
        if len(parsed) > 1:
            raise SqlGuardError(
                f"only one statement may be executed, found {len(parsed)} "
                "(stacked statements are blocked)"
            )
        return parsed[0]

    @staticmethod
    def _assert_select(statement: Statement) -> None:
        first = statement.token_first(skip_cm=True, skip_ws=True)
        if first is None:
            raise SqlGuardError("statement contains no executable SQL")
        if first.ttype is CTE:
            if statement.get_type() != "SELECT":
                raise SqlGuardError("WITH clauses are only allowed in front of a SELECT")
            return
        if first.ttype is not DML or first.normalized.upper() != "SELECT":
            kind = statement.get_type()
            label = kind if kind != "UNKNOWN" else first.normalized.upper()
            raise SqlGuardError(f"only SELECT statements are permitted, got {label}")

    @staticmethod
    def _assert_no_forbidden_keywords(normalised: str) -> None:
        masked = _LITERAL_SCAN.sub("''", normalised)
        found = sorted({match.group(1).upper() for match in _KEYWORD_SCAN.finditer(masked)})
        if found:
            raise SqlGuardError(f"forbidden keyword(s) in statement: {', '.join(found)}")

    def _assert_tables_allowed(self, tables: set[str]) -> None:
        if self._allowed is None:
            return
        denied = sorted(
            name for name in tables if not self._is_allowed(name)
        )
        if denied:
            allowed = ", ".join(sorted(self._allowed)) or "<none>"
            raise SqlGuardError(
                f"table(s) not in the allow-list for this source: {', '.join(denied)} (allowed: {allowed})"
            )

    def _is_allowed(self, name: str) -> bool:
        if self._allowed is None:
            return True
        lowered = name.lower()
        bare = lowered.rsplit(".", 1)[-1]
        return lowered in self._allowed or bare in self._allowed

    def _enforce_limit(self, statement: Statement, normalised: str) -> tuple[str, int]:
        index = _top_level_limit_index(statement)
        if index is None:
            return f"{normalised} LIMIT {self._max_rows}", self._max_rows
        parts = [str(token) for token in statement.tokens]
        value_index, current = _limit_value(statement, index)
        if value_index is None or current is None:
            raise SqlGuardError("LIMIT must be followed by an integer literal")
        if current <= self._max_rows:
            return normalised, current
        parts[value_index] = _rewrite_limit(parts[value_index], self._max_rows)
        log.info("sql_guard.limit_lowered", requested=current, applied=self._max_rows)
        return "".join(parts), self._max_rows

    # -- safe statement construction --------------------------------------
    def build_select(
        self,
        table: str,
        columns: Sequence[str] | None = None,
        where: Mapping[str, Any] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
    ) -> ValidatedSql:
        """Build a parameterised SELECT.  Values are *always* bound, never inlined."""
        if not self._is_allowed(table):
            raise SqlGuardError(f"table {table!r} is not in the allow-list for this source")
        select_list = "*" if not columns else ", ".join(self._quote(name) for name in columns)
        clauses = [f"SELECT {select_list} FROM {self._quote_qualified(table)}"]
        params: dict[str, Any] = {}
        for ordinal, (column, value) in enumerate(dict(where or {}).items()):
            placeholder = f"w{ordinal}"
            prefix = "WHERE" if ordinal == 0 else "AND"
            clauses.append(f"{prefix} {self._quote(column)} = :{placeholder}")
            params[placeholder] = value
        if order_by:
            clauses.append(f"ORDER BY {self._order_by(order_by)}")
        clauses.append(f"LIMIT {self._bounded(limit)}")
        return self.validate(" ".join(clauses), params)

    def _bounded(self, limit: int | None) -> int:
        if limit is None:
            return self._max_rows
        if limit < 1:
            raise SqlGuardError(f"limit must be >= 1, got {limit}")
        return min(int(limit), self._max_rows)

    def _quote(self, name: str) -> str:
        return quote_identifier(name, self._dialect)

    def _quote_qualified(self, table: str) -> str:
        parts = table.split(".")
        if len(parts) > 2:
            raise SqlGuardError(f"invalid table name {table!r}")
        return ".".join(self._quote(part) for part in parts)

    def _order_by(self, order_by: str) -> str:
        pieces = order_by.split()
        if len(pieces) > 2:
            raise SqlGuardError(f"invalid ORDER BY clause {order_by!r}")
        column = self._quote(pieces[0])
        if len(pieces) == 1:
            return column
        direction = pieces[1].upper()
        if direction not in _ORDER_DIRECTIONS:
            raise SqlGuardError(f"invalid sort direction {pieces[1]!r}")
        return f"{column} {direction}"


# -- parsing helpers ------------------------------------------------------
def _is_meaningful(statement: Statement) -> bool:
    return bool(str(statement).strip().strip(";").strip())


def _identifier_name(token: Identifier) -> str | None:
    real = token.get_real_name()
    if not real:
        return None
    parent = token.get_parent_name()
    return f"{parent}.{real}" if parent else real


def _collect_cte_names(statement: Statement) -> set[str]:
    """Names defined by a leading ``WITH`` clause - those are not real tables."""
    names: set[str] = set()
    expecting = False
    for token in statement.tokens:
        if token.is_whitespace:
            continue
        if token.ttype is CTE:
            expecting = True
            continue
        if not expecting:
            continue
        if token.ttype is Keyword and token.normalized.upper() == "RECURSIVE":
            continue
        for identifier in _as_identifiers(token):
            name = identifier.get_real_name()
            if name:
                names.add(name.lower())
        expecting = False
    return names


def _as_identifiers(token: Token) -> list[Identifier]:
    if isinstance(token, IdentifierList):
        return [item for item in token.get_identifiers() if isinstance(item, Identifier)]
    if isinstance(token, Identifier):
        return [token]
    return []


def _collect_tables(node: Token) -> set[str]:
    """Recursively collect every table referenced in FROM/JOIN clauses."""
    found: set[str] = set()
    _collect_tables_into(getattr(node, "tokens", []), found)
    return found


def _collect_tables_into(tokens: Sequence[Token], found: set[str]) -> None:
    expecting = False
    for token in tokens:
        if token.is_whitespace:
            continue
        if token.ttype is Keyword and token.normalized.upper() in _JOIN_SOURCES:
            expecting = True
            continue
        if token.ttype is Keyword and token.normalized.upper().endswith("JOIN"):
            expecting = True
            continue
        if expecting and token.ttype is None:
            _record_sources(token, found)
            expecting = False
            continue
        expecting = False
        if token.is_group:
            _collect_tables_into(token.tokens, found)


def _record_sources(token: Token, found: set[str]) -> None:
    identifiers = _as_identifiers(token)
    if not identifiers:
        _collect_tables_into(getattr(token, "tokens", []), found)
        return
    for identifier in identifiers:
        if any(sub.is_group and not isinstance(sub, Identifier) for sub in identifier.tokens):
            _collect_tables_into(identifier.tokens, found)
            continue
        name = _identifier_name(identifier)
        if name:
            found.add(name.lower())


def _top_level_limit_index(statement: Statement) -> int | None:
    for index, token in enumerate(statement.tokens):
        if token.ttype is Keyword and token.normalized.upper() == "LIMIT":
            return index
    return None


def _limit_value(statement: Statement, limit_index: int) -> tuple[int | None, int | None]:
    """Locate the effective row-count token after a top-level LIMIT."""
    for index in range(limit_index + 1, len(statement.tokens)):
        token = statement.tokens[index]
        if token.is_whitespace:
            continue
        if token.ttype in Number:
            return index, int(str(token))
        if isinstance(token, IdentifierList):
            numbers = [str(item).strip() for item in token.get_identifiers()]
            if len(numbers) == 2 and all(part.isdigit() for part in numbers):
                # MySQL "LIMIT <offset>, <count>" - the count is what we cap.
                return index, int(numbers[1])
        return None, None
    return None, None


def _rewrite_limit(original: str, max_rows: int) -> str:
    if "," in original:
        offset = original.split(",", 1)[0].strip()
        return f"{offset}, {max_rows}"
    return str(max_rows)


def _bind_parameters(
    sql: str,
    params: Mapping[str, Any] | Sequence[Any] | None,
) -> tuple[str, dict[str, Any]]:
    """Normalise placeholders and assert every one of them is bound."""
    if params is None:
        bound: dict[str, Any] = {}
    elif isinstance(params, Mapping):
        bound = {str(key): value for key, value in params.items()}
    elif isinstance(params, (list, tuple)):
        sql, bound = _convert_positional(sql, params)
    else:
        raise SqlGuardError("params must be a mapping or a sequence")

    if "?" in _LITERAL_SCAN.sub("''", sql):
        raise SqlGuardError("positional '?' placeholders require a sequence of parameter values")
    required = {match.group(1) for match in _NAMED_PARAM.finditer(_LITERAL_SCAN.sub("''", sql))}
    missing = sorted(required - set(bound))
    if missing:
        raise SqlGuardError(f"missing bound value(s) for placeholder(s): {', '.join(missing)}")
    return sql, {key: value for key, value in bound.items() if key in required}


def _convert_positional(sql: str, values: Sequence[Any]) -> tuple[str, dict[str, Any]]:
    """Rewrite ``?`` placeholders to ``:p0`` style so values stay bound."""
    literals: list[str] = []

    def _stash(match: re.Match[str]) -> str:
        literals.append(match.group(0))
        return f"\x00{len(literals) - 1}\x00"

    masked = _LITERAL_SCAN.sub(_stash, sql)
    count = masked.count("?")
    if count != len(values):
        raise SqlGuardError(f"statement has {count} '?' placeholder(s) but {len(values)} value(s) were given")
    bound = {f"p{index}": value for index, value in enumerate(values)}
    for index in range(count):
        masked = masked.replace("?", f":p{index}", 1)
    restored = re.sub(r"\x00(\d+)\x00", lambda m: literals[int(m.group(1))], masked)
    return restored, bound
