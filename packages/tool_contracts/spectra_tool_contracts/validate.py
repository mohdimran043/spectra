"""Minimal, dependency-free JSON Schema validation for tool arguments.

Only the subset the tool contracts actually use is supported (object/array/
string/number/integer/boolean, required, enum, minimum/maximum, maxItems,
additionalProperties).  That keeps validation exact and auditable rather than
pulling a large validator in for six keywords.
"""

from __future__ import annotations

from typing import Any

from .schema import JsonSchema

_TYPES: dict[str, type | tuple[type, ...]] = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
}


class SchemaViolation(ValueError):
    """Raised when arguments do not match the declared tool schema."""

    def __init__(self, path: str, message: str) -> None:
        super().__init__(f"{path or '<root>'}: {message}")
        self.path = path
        self.message = message


def validate(value: Any, schema: JsonSchema, path: str = "") -> None:
    expected = schema.get("type")
    if expected:
        python_type = _TYPES.get(expected)
        if python_type is None:
            raise SchemaViolation(path, f"unsupported schema type {expected!r}")
        if expected == "integer" and isinstance(value, bool):
            raise SchemaViolation(path, "expected integer, got boolean")
        if expected == "number" and isinstance(value, bool):
            raise SchemaViolation(path, "expected number, got boolean")
        if not isinstance(value, python_type):
            raise SchemaViolation(path, f"expected {expected}, got {type(value).__name__}")

    if (enum := schema.get("enum")) is not None and value not in enum:
        raise SchemaViolation(path, f"value must be one of {enum}")

    if expected == "object":
        _validate_object(value, schema, path)
    elif expected == "array":
        _validate_array(value, schema, path)
    elif expected in {"integer", "number"}:
        _validate_bounds(value, schema, path)


def _validate_object(value: dict, schema: JsonSchema, path: str) -> None:
    properties: dict[str, JsonSchema] = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in value:
            raise SchemaViolation(_join(path, key), "is required")
    if schema.get("additionalProperties") is False:
        unknown = sorted(set(value) - set(properties))
        if unknown:
            raise SchemaViolation(path, f"unknown properties: {', '.join(unknown)}")
    for key, sub_schema in properties.items():
        if key in value:
            validate(value[key], sub_schema, _join(path, key))


def _validate_array(value: list, schema: JsonSchema, path: str) -> None:
    max_items = schema.get("maxItems")
    if max_items is not None and len(value) > max_items:
        raise SchemaViolation(path, f"at most {max_items} items allowed, got {len(value)}")
    item_schema = schema.get("items")
    if item_schema:
        for index, item in enumerate(value):
            validate(item, item_schema, f"{path}[{index}]")


def _validate_bounds(value: float, schema: JsonSchema, path: str) -> None:
    minimum, maximum = schema.get("minimum"), schema.get("maximum")
    if minimum is not None and value < minimum:
        raise SchemaViolation(path, f"must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise SchemaViolation(path, f"must be <= {maximum}")


def apply_defaults(value: dict, schema: JsonSchema) -> dict:
    """Return a NEW dict with declared defaults filled in."""
    out = dict(value)
    for key, sub in schema.get("properties", {}).items():
        if key not in out and "default" in sub:
            out[key] = sub["default"]
    return out


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key
