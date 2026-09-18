"""Strict argument validation against a tool's declared JSON schema.

A deliberately small validator: the Brain only ever emits flat argument objects,
and a dependency-free checker keeps the failure message precise enough for the
model to repair its own call on the next turn.
"""

from __future__ import annotations

from typing import Any

from spectra_schemas import ToolError

_TYPE_MAP: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list, tuple),
    "object": (dict,),
}


def validate_args(tool: str, schema: dict[str, Any], args: dict[str, Any] | None) -> dict[str, Any]:
    """Return a NEW argument dict with defaults applied, or raise ``ToolError``."""
    supplied = dict(args or {})
    properties: dict[str, Any] = schema.get("properties", {})
    required: list[str] = list(schema.get("required", []))

    if schema.get("additionalProperties") is False:
        unknown = sorted(set(supplied) - set(properties))
        if unknown:
            raise ToolError(
                tool,
                f"unknown argument(s) {unknown}; accepted arguments are {sorted(properties)}",
            )

    missing = [name for name in required if supplied.get(name) in (None, "")]
    if missing:
        raise ToolError(tool, f"missing required argument(s) {missing}")

    cleaned: dict[str, Any] = {}
    for name, spec in properties.items():
        if name not in supplied or supplied[name] is None:
            if "default" in spec:
                cleaned[name] = spec["default"]
            continue
        cleaned[name] = _check_value(tool, name, spec, supplied[name])
    return cleaned


def _check_value(tool: str, name: str, spec: dict[str, Any], value: Any) -> Any:
    expected = spec.get("type")
    coerced = _coerce(expected, value)
    allowed = _TYPE_MAP.get(str(expected))
    if allowed and not isinstance(coerced, allowed):
        raise ToolError(tool, f"argument '{name}' must be a {expected}, got {type(value).__name__}")
    if expected == "integer" and isinstance(coerced, bool):
        raise ToolError(tool, f"argument '{name}' must be an integer, got boolean")

    _check_enum(tool, name, spec, coerced)
    _check_bounds(tool, name, spec, coerced)
    if expected == "array":
        return _check_items(tool, name, spec, list(coerced))
    return coerced


def _coerce(expected: Any, value: Any) -> Any:
    if expected == "integer" and isinstance(value, float) and value.is_integer():
        return int(value)
    if expected == "number" and isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    return value


def _check_enum(tool: str, name: str, spec: dict[str, Any], value: Any) -> None:
    choices = spec.get("enum")
    if choices and value not in choices:
        raise ToolError(tool, f"argument '{name}' must be one of {choices}, got {value!r}")


def _check_bounds(tool: str, name: str, spec: dict[str, Any], value: Any) -> None:
    if isinstance(value, str):
        minimum_length = spec.get("minLength")
        if minimum_length is not None and len(value.strip()) < minimum_length:
            raise ToolError(tool, f"argument '{name}' must be at least {minimum_length} character(s)")
        return
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        low, high = spec.get("minimum"), spec.get("maximum")
        if low is not None and value < low:
            raise ToolError(tool, f"argument '{name}' must be >= {low}, got {value}")
        if high is not None and value > high:
            raise ToolError(tool, f"argument '{name}' must be <= {high}, got {value}")


def _check_items(tool: str, name: str, spec: dict[str, Any], values: list[Any]) -> list[Any]:
    item_spec = spec.get("items") or {}
    item_type = item_spec.get("type")
    allowed = _TYPE_MAP.get(str(item_type))
    max_items = spec.get("maxItems")
    if max_items is not None and len(values) > max_items:
        raise ToolError(tool, f"argument '{name}' accepts at most {max_items} item(s)")
    if not allowed:
        return values
    for index, item in enumerate(values):
        if not isinstance(item, allowed):
            raise ToolError(tool, f"argument '{name}[{index}]' must be a {item_type}")
    return values
