"""Validation of responses against declared schemas."""

from __future__ import annotations

import pytest
from jsonschema.exceptions import SchemaError

from mcp_response_guard import Severity, validate_error_response, validate_response

SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "size": {"type": "integer"},
        "content": {"type": "string"},
    },
    "required": ["path", "size"],
}


def test_matching_response_has_no_violations():
    response = {"path": "/etc/hosts", "size": 42, "content": "127.0.0.1 localhost"}
    assert validate_response(response, SCHEMA) == []


def test_missing_required_field_is_high_severity():
    response = {"content": "x"}
    codes = [(v.code, v.severity) for v in validate_response(response, SCHEMA)]
    assert codes == [("MCPR001", Severity.HIGH)]


def test_missing_required_field_names_only_absent_fields():
    response = {"path": "/etc/hosts"}
    violations = validate_response(response, SCHEMA)
    assert len(violations) == 1
    assert "size" in violations[0].message
    assert "path" not in violations[0].message


def test_type_mismatch_is_medium_severity():
    violations = validate_response({"path": "/etc/hosts", "size": "42"}, SCHEMA)
    assert [(v.code, v.severity) for v in violations] == [("MCPR003", Severity.MEDIUM)]
    assert violations[0].path == "size"


def test_undeclared_field_is_detected_even_when_additional_properties_is_not_false():
    response = {"path": "/etc/hosts", "size": 42, "encoding": "utf-8"}
    violations = validate_response(response, SCHEMA)
    assert [(v.code, v.path) for v in violations] == [("MCPR002", "encoding")]


def test_undeclared_nested_field_reports_its_full_path():
    schema = {
        "type": "object",
        "properties": {"meta": {"type": "object", "properties": {"id": {"type": "integer"}}}},
    }
    response = {"meta": {"id": 1, "nested": {"deep": True}}}
    violations = validate_response(response, schema)
    assert [(v.code, v.path) for v in violations] == [("MCPR002", "meta.nested")]


def test_boolean_is_not_accepted_as_integer():
    # bool subclasses int in Python; JSON Schema says they are different types.
    violations = validate_response({"path": "a", "size": True}, SCHEMA)
    assert [v.code for v in violations] == ["MCPR003"]


def test_additional_properties_false_does_not_report_duplicate_violations():
    # Issue #16: when additionalProperties is false, jsonschema already reports
    # undeclared fields as MCPR004. _extra_fields must not report them again
    # as MCPR002 -- that is duplicate noise for the same field.
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    }
    response = {"name": "test", "extra": "value"}
    violations = validate_response(response, schema)
    # Only MCPR004 from jsonschema, no duplicate MCPR002
    assert [v.code for v in violations] == ["MCPR004"]


def test_additional_properties_as_schema_does_not_report_extra_fields():
    # Issue #17: when additionalProperties is a schema (dict), extra fields
    # are valid if they pass that schema. jsonschema already validates them,
    # so _extra_fields must not report them as MCPR002.
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "additionalProperties": {"type": "integer"},
    }
    response = {"name": "test", "count": 42}
    assert validate_response(response, schema) == []


def test_additional_properties_as_schema_still_reports_type_mismatch():
    # When additionalProperties is a schema and the extra field fails it,
    # jsonschema reports the type error (MCPR003), not MCPR002.
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "additionalProperties": {"type": "integer"},
    }
    response = {"name": "test", "count": "not-an-integer"}
    violations = validate_response(response, schema)
    assert [v.code for v in violations] == ["MCPR003"]


def test_free_form_object_is_not_flooded_with_extra_field_violations():
    # Only descends into subschemas the schema describes.
    schema = {"type": "object", "properties": {"items": {"type": "array"}}}
    violations = validate_response({"items": [{"a": 1}, {"b": 2}]}, schema)
    assert violations == []


def test_tool_name_is_recorded_on_violations():
    violations = validate_response({}, SCHEMA, tool="filesystem.read_file")
    assert violations[0].tool == "filesystem.read_file"


def test_invalid_schema_raises():
    with pytest.raises(SchemaError):
        validate_response({}, {"type": "not-a-type"})


def test_error_response_violations_are_tagged_mcpr005():
    violations = validate_error_response({"message": "boom"}, SCHEMA, tool="fs")
    assert {v.code for v in violations} == {"MCPR005"}
    assert "error response" in violations[0].message
    assert violations[0].tool == "fs"


def test_matching_error_response_is_clean():
    error_schema = {
        "type": "object",
        "properties": {"message": {"type": "string"}},
        "required": ["message"],
    }
    assert validate_error_response({"message": "boom"}, error_schema) == []


def test_pattern_property_field_is_not_reported_as_extra():
    # Issue #18: a field matching a declared patternProperties regex is valid,
    # so _extra_fields must not report it as MCPR002.
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "patternProperties": {"^x-": {"type": "string"}},
    }
    response = {"a": "hello", "x-extra": "world"}
    assert validate_response(response, schema) == []


def test_field_matching_no_pattern_is_still_extra():
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "patternProperties": {"^x-": {"type": "string"}},
    }
    response = {"a": "hello", "y-extra": "world"}
    assert [(v.code, v.path) for v in validate_response(response, schema)] == [
        ("MCPR002", "y-extra")
    ]


def test_pattern_property_field_is_still_type_checked():
    # A pattern-matching field is valid, but it must still satisfy its subschema.
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "patternProperties": {"^x-": {"type": "string"}},
    }
    response = {"a": "hello", "x-extra": 1}
    assert [(v.code, v.path) for v in validate_response(response, schema)] == [
        ("MCPR003", "x-extra")
    ]


def test_nested_pattern_property_field_is_not_extra():
    schema = {
        "type": "object",
        "properties": {
            "meta": {
                "type": "object",
                "patternProperties": {"^x-": {"type": "string"}},
            }
        },
    }
    response = {"meta": {"x-trace": "abc"}}
    assert validate_response(response, schema) == []
