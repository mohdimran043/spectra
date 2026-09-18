"""JSON Schema helpers for agent tool contracts.

Tool input/output schemas are declared once, validated at the boundary, and
exported for documentation and for the frontend.  Keeping the builders here
stops twenty tool modules from each inventing their own schema dialect.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

JsonSchema = dict[str, Any]


def obj(
    properties: dict[str, JsonSchema],
    *,
    required: Iterable[str] = (),
    description: str = "",
    additional: bool = False,
) -> JsonSchema:
    schema: JsonSchema = {
        "type": "object",
        "properties": properties,
        "additionalProperties": additional,
    }
    required_list = list(required)
    if required_list:
        schema["required"] = required_list
    if description:
        schema["description"] = description
    return schema


def string(description: str = "", *, enum: Iterable[str] | None = None, default: str | None = None) -> JsonSchema:
    schema: JsonSchema = {"type": "string"}
    if description:
        schema["description"] = description
    if enum is not None:
        schema["enum"] = list(enum)
    if default is not None:
        schema["default"] = default
    return schema


def integer(description: str = "", *, minimum: int | None = None, maximum: int | None = None,
            default: int | None = None) -> JsonSchema:
    schema: JsonSchema = {"type": "integer"}
    if description:
        schema["description"] = description
    if minimum is not None:
        schema["minimum"] = minimum
    if maximum is not None:
        schema["maximum"] = maximum
    if default is not None:
        schema["default"] = default
    return schema


def number(description: str = "", *, minimum: float | None = None, maximum: float | None = None,
           default: float | None = None) -> JsonSchema:
    schema: JsonSchema = {"type": "number"}
    if description:
        schema["description"] = description
    if minimum is not None:
        schema["minimum"] = minimum
    if maximum is not None:
        schema["maximum"] = maximum
    if default is not None:
        schema["default"] = default
    return schema


def boolean(description: str = "", *, default: bool | None = None) -> JsonSchema:
    schema: JsonSchema = {"type": "boolean"}
    if description:
        schema["description"] = description
    if default is not None:
        schema["default"] = default
    return schema


def array(items: JsonSchema, description: str = "", *, max_items: int | None = None) -> JsonSchema:
    schema: JsonSchema = {"type": "array", "items": items}
    if description:
        schema["description"] = description
    if max_items is not None:
        schema["maxItems"] = max_items
    return schema
