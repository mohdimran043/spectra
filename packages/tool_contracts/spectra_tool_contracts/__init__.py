"""Shared JSON Schema builders and validation for SPECTRA agent tools."""

from .schema import JsonSchema, array, boolean, integer, number, obj, string
from .validate import SchemaViolation, apply_defaults, validate

__all__ = [
    "JsonSchema",
    "SchemaViolation",
    "apply_defaults",
    "array",
    "boolean",
    "integer",
    "number",
    "obj",
    "string",
    "validate",
]
