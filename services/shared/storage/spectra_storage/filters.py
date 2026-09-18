"""Payload filter compilation shared by every retrieval backend.

SPECTRA's retrieval layer passes one filter dialect to *all* stores so the
search service never branches on the active backend.  A filter is a flat
``{payload_field: condition}`` mapping where the condition is either

* a scalar - equality (``{"source_id": "src_a"}``),
* a list/tuple/set - membership (``{"modality": ["document", "image"]}``), or
* an explicit operator dict - ``{"permissions": {"any": ["analyst"]}}``.

Payload fields are frequently *list valued* (``permissions``, ``entities``),
so every operator degrades to "do the two value sets overlap?" when the stored
value is a list.  That is exactly what Qdrant's ``MatchAny`` and OpenSearch's
``terms`` do, which keeps embedded and distributed results identical.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

OP_EQ = "eq"
OP_IN = "in"
OP_ANY = "any"
SUPPORTED_OPERATORS = (OP_EQ, OP_IN, OP_ANY)

_LIST_TYPES = (list, tuple, set, frozenset)


@dataclass(frozen=True)
class FilterCondition:
    """One compiled predicate over a single payload field."""

    field: str
    operator: str
    values: tuple[Any, ...]

    @property
    def single(self) -> Any:
        return self.values[0]


class FilterError(ValueError):
    """Raised when a caller supplies a filter this layer cannot honour."""


def compile_filters(filters: Mapping[str, Any] | None) -> tuple[FilterCondition, ...]:
    """Turn the raw filter mapping into an immutable tuple of predicates."""
    if not filters:
        return ()
    if not isinstance(filters, Mapping):
        raise FilterError(f"filters must be a mapping, got {type(filters).__name__}")
    return tuple(_compile_one(str(field), raw) for field, raw in filters.items())


def _compile_one(field: str, raw: Any) -> FilterCondition:
    if isinstance(raw, Mapping):
        return _compile_operator_form(field, raw)
    if isinstance(raw, _LIST_TYPES):
        values = tuple(_normalise(v) for v in raw)
        if not values:
            raise FilterError(f"filter {field!r} has an empty value list")
        return FilterCondition(field=field, operator=OP_IN, values=values)
    return FilterCondition(field=field, operator=OP_EQ, values=(_normalise(raw),))


def _compile_operator_form(field: str, raw: Mapping[str, Any]) -> FilterCondition:
    if len(raw) != 1:
        raise FilterError(f"filter {field!r} must carry exactly one operator, got {sorted(raw)}")
    operator, value = next(iter(raw.items()))
    if operator not in SUPPORTED_OPERATORS:
        raise FilterError(f"filter {field!r} uses unsupported operator {operator!r}")
    if operator == OP_EQ:
        return FilterCondition(field=field, operator=OP_EQ, values=(_normalise(value),))
    if not isinstance(value, _LIST_TYPES):
        raise FilterError(f"filter {field!r} operator {operator!r} needs a list value")
    values = tuple(_normalise(v) for v in value)
    if not values:
        raise FilterError(f"filter {field!r} operator {operator!r} has an empty value list")
    return FilterCondition(field=field, operator=operator, values=values)


def _normalise(value: Any) -> Any:
    """Collapse enums to their wire value so JSON payloads compare equal."""
    raw = getattr(value, "value", value)
    if isinstance(raw, (str, int, float, bool)) or raw is None:
        return raw
    return str(raw)


def matches_payload(payload: Mapping[str, Any] | None, conditions: Sequence[FilterCondition]) -> bool:
    """True when ``payload`` satisfies every compiled condition (logical AND)."""
    if not conditions:
        return True
    data = payload or {}
    for condition in conditions:
        if condition.field not in data:
            return False
        if not _condition_matches(data[condition.field], condition):
            return False
    return True


def _condition_matches(stored: Any, condition: FilterCondition) -> bool:
    stored_values = _as_value_set(stored)
    wanted = {_normalise(v) for v in condition.values}
    if condition.operator == OP_EQ and not isinstance(stored, _LIST_TYPES):
        return _normalise(stored) == condition.single
    return bool(stored_values & wanted)


def _as_value_set(stored: Any) -> set[Any]:
    if isinstance(stored, _LIST_TYPES):
        return {_normalise(v) for v in stored}
    return {_normalise(stored)}


def describe(conditions: Iterable[FilterCondition]) -> str:
    """Human-readable rendering used in structured log lines."""
    return ", ".join(f"{c.field} {c.operator} {list(c.values)}" for c in conditions) or "none"
