"""Validate a response against the JSON Schema an MCP tool declared.

`jsonschema` does the validation; this module maps its errors onto the MCPR
detector codes and adds the one check `jsonschema` does not do: fields present
in the response but absent from the schema (a silent-drift signal even when
``additionalProperties`` is not ``false``).
"""

from __future__ import annotations

import re
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from .models import Severity, Violation

__all__ = [
    "MISSING_FIELD_CODE",
    "EXTRA_FIELD_CODE",
    "TYPE_MISMATCH_CODE",
    "SCHEMA_VIOLATION_CODE",
    "ERROR_SCHEMA_CODE",
    "validate_response",
    "validate_error_response",
]

MISSING_FIELD_CODE = "MCPR001"
EXTRA_FIELD_CODE = "MCPR002"
TYPE_MISMATCH_CODE = "MCPR003"
SCHEMA_VIOLATION_CODE = "MCPR004"
ERROR_SCHEMA_CODE = "MCPR005"

_JSON_TYPES = {
    "null",
    "boolean",
    "object",
    "array",
    "number",
    "string",
    "integer",
}


def _pointer(path: Any) -> str:
    parts = list(path)
    return "".join(f"[{p!r}]" if isinstance(p, int) else f".{p}" for p in parts).lstrip(".") or "$"


def _severity_for(error: ValidationError) -> Severity:
    if error.validator == "required":
        return Severity.HIGH
    if error.validator == "type":
        return Severity.MEDIUM
    return Severity.MEDIUM


def _code_for(error: ValidationError) -> str:
    if error.validator == "required":
        return MISSING_FIELD_CODE
    if error.validator == "type":
        return TYPE_MISMATCH_CODE
    return SCHEMA_VIOLATION_CODE


def _missing_names(error: ValidationError) -> list[str]:
    """Pull the field names out of a ``required`` error.

    ``jsonschema`` only puts the schema's full ``required`` list in the message,
    which reads badly once most of those fields are present.
    """
    try:
        schema = error.schema
    except AttributeError:
        return []
    required = schema.get("required") if isinstance(schema, dict) else None
    if not isinstance(required, list):
        return []
    instance = error.instance if isinstance(error.instance, dict) else {}
    absent = [name for name in required if isinstance(name, str) and name not in instance]
    return absent or [str(name) for name in required]


def _matches_pattern(key: str, patterns: Any) -> bool:
    """True when ``key`` matches any declared ``patternProperties`` regex."""
    if not isinstance(patterns, dict):
        return False
    return any(re.search(pattern, key) for pattern in patterns if isinstance(pattern, str))


def _array_prefix(prefix: str, index: int) -> str:
    return f"{prefix[:-1] if prefix.endswith('.') else prefix}[{index}]."


def _extra_fields_in_array(instance: list, schema: dict, prefix: str) -> list[str]:
    """Descend into ``items``/``prefixItems`` subschemas of an array (issue #27)."""
    extra: list[str] = []
    items = schema.get("items")
    prefix_items = schema.get("prefixItems")
    if isinstance(prefix_items, list):
        for index, item_schema in enumerate(prefix_items):
            if index < len(instance):
                extra.extend(
                    _extra_fields(instance[index], item_schema, _array_prefix(prefix, index))
                )
        if isinstance(items, dict):
            for index in range(len(prefix_items), len(instance)):
                extra.extend(_extra_fields(instance[index], items, _array_prefix(prefix, index)))
    elif isinstance(items, dict):
        for index, item in enumerate(instance):
            extra.extend(_extra_fields(item, items, _array_prefix(prefix, index)))
    return extra


def _extra_fields(instance: Any, schema: Any, prefix: str = "") -> list[str]:
    """Report declared object fields the schema never mentions.

    Only descends into subschemas the schema actually describes, so a response
    with a free-form bag of extra keys yields one violation, not hundreds.

    A key is declared when it is in ``properties`` or matches a
    ``patternProperties`` regex (issue #18). When ``additionalProperties`` is a
    schema (dict), extra fields are valid if they pass that schema --
    ``jsonschema`` already validates them, so they must not be reported here
    (issue #17).
    """
    if not isinstance(schema, dict):
        return []
    if isinstance(instance, list):
        return _extra_fields_in_array(instance, schema, prefix)
    if not isinstance(instance, dict):
        return []
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return []
    patterns = schema.get("patternProperties")
    additional = schema.get("additionalProperties")
    if isinstance(additional, dict):
        # additionalProperties is a schema -- jsonschema validates extra fields
        # against it. Reporting them here would be a false positive.
        return []
    if additional is False:
        # additionalProperties: false -- jsonschema already reports undeclared
        # fields as MCPR004. Reporting them again as MCPR002 is duplicate noise
        # (issue #16). Still descend into subschemas below.
        extra = []
    else:
        extra = [
            f"{prefix}{key}"
            for key in instance
            if key not in properties and not _matches_pattern(key, patterns)
        ]
    for key, value in instance.items():
        if key in properties:
            extra.extend(_extra_fields(value, properties[key], f"{prefix}{key}."))
        elif isinstance(patterns, dict) and key in patterns and isinstance(patterns[key], dict):
            # A pattern-matching key is declared: descend into its subschema so
            # nested undeclared fields are still reported.
            extra.extend(_extra_fields(value, patterns[key], f"{prefix}{key}."))
    return extra


def validate_response(response: Any, schema: dict, tool: str | None = None) -> list[Violation]:
    """Validate one MCP tool response against its declared output schema.

    Returns a list of violations, empty when the response matches the schema.
    Raises ``jsonschema.exceptions.SchemaError`` if the schema itself is invalid.
    """
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    errors = sorted(validator.iter_errors(response), key=lambda e: list(e.absolute_path))

    violations = [
        Violation(
            code=_code_for(error),
            severity=_severity_for(error),
            message=error.message,
            path=_pointer(error.absolute_path),
            tool=tool,
        )
        for error in errors
        if error.validator != "required"
    ]

    # ``jsonschema`` raises one ``required`` error per absent property; report them
    # as one violation per path so a response missing N fields reads as one problem.
    missing: dict[tuple, list[str]] = {}
    for error in errors:
        if error.validator == "required":
            names = missing.setdefault(tuple(error.absolute_path), [])
            names.extend(name for name in _missing_names(error) if name not in names)
    violations.extend(
        Violation(
            code=MISSING_FIELD_CODE,
            severity=Severity.HIGH,
            message=f"missing required field(s): {', '.join(names)}",
            path=_pointer(path),
            tool=tool,
        )
        for path, names in sorted(missing.items())
    )

    for path in _extra_fields(response, schema):
        violations.append(
            Violation(
                code=EXTRA_FIELD_CODE,
                severity=Severity.HIGH,
                message=f"field not declared in schema: {path}",
                path=path,
                tool=tool,
            )
        )
    return violations


def validate_error_response(
    response: Any, schema: dict, tool: str | None = None
) -> list[Violation]:
    """Validate an MCP *error* payload against the server's declared error schema."""
    return [
        Violation(
            code=ERROR_SCHEMA_CODE,
            severity=violation.severity,
            message=f"error response does not match error schema: {violation.message}",
            path=violation.path,
            tool=tool,
        )
        for violation in validate_response(response, schema, tool=tool)
    ]
