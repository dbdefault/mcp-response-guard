"""Shape fingerprints, drift comparison and baseline persistence."""
from __future__ import annotations

import json
import sqlite3

import pytest

from mcp_response_guard import DriftTracker, Severity, compare_shapes, shape_of


def test_shape_of_flattens_nested_objects():
    assert shape_of({"a": 1, "b": {"c": "x"}}) == {
        "$": "object",
        "$.a": "integer",
        "$.b": "object",
        "$.b.c": "string",
    }


def test_shape_of_uses_array_item_shape_not_the_count():
    # A uniform array fingerprints by item shape, not by how many items it has.
    one = shape_of({"items": [{"id": 1}]})
    two = shape_of({"items": [{"id": 1}, {"id": 2}]})
    assert one["$.items[0].id"] == "integer"
    assert two["$.items[0].id"] == "integer"


def test_shape_of_distinguishes_null_from_string():
    assert shape_of({"a": None})["$.a"] == "null"
    assert shape_of({"a": "x"})["$.a"] == "string"


def test_compare_reports_added_field():
    violations = compare_shapes(
        {"$": "object", "$.a": "integer"}, {"$": "object", "$.a": "integer", "$.b": "string"}
    )
    assert len(violations) == 1
    assert violations[0].code == "MCPR004"
    assert violations[0].severity is Severity.LOW
    assert violations[0].path == "$.b"


def test_compare_reports_removed_field():
    violations = compare_shapes({"$": "object", "$.a": "integer"}, {"$": "object"})
    assert [v.path for v in violations] == ["$.a"]
    assert "absent from this response" in violations[0].message


def test_compare_reports_type_change_as_medium():
    violations = compare_shapes({"$.a": "integer"}, {"$.a": "string"})
    assert violations[0].severity is Severity.MEDIUM
    assert "integer" in violations[0].message and "string" in violations[0].message


def test_compare_of_identical_shapes_is_clean():
    shape = shape_of({"a": 1, "b": [2]})
    assert compare_shapes(shape, shape_of({"a": 1, "b": [2]})) == []


def test_first_record_establishes_baseline_without_drift():
    tracker = DriftTracker()
    assert tracker.record("fs.read", {"path": "/a"}) == []
    assert tracker.baseline("fs.read") == shape_of({"path": "/a"})


def test_drift_against_previous_baseline():
    tracker = DriftTracker()
    tracker.record("fs.read", {"path": "/a"})
    violations = tracker.record("fs.read", {"path": "/a", "inode": 7})
    assert [v.code for v in violations] == ["MCPR004"]
    assert violations[0].tool == "fs.read"


def test_record_updates_the_baseline():
    tracker = DriftTracker()
    tracker.record("fs.read", {"path": "/a"})
    tracker.record("fs.read", {"path": "/a", "inode": 7})
    assert tracker.check("fs.read", {"path": "/a", "inode": 7}) == []


def test_check_does_not_mutate_the_baseline():
    tracker = DriftTracker()
    tracker.record("fs.read", {"path": "/a"})
    assert tracker.check("fs.read", {"path": "/b", "extra": 1}) != []
    assert tracker.baseline("fs.read") == shape_of({"path": "/a"})


def test_baselines_persist_across_trackers(tmp_path):
    store = tmp_path / "drift.db"
    DriftTracker(store).record("fs.read", {"path": "/a"})
    assert DriftTracker(store).baseline("fs.read") == shape_of({"path": "/a"})


def test_baselines_are_kept_per_tool(tmp_path):
    store = tmp_path / "drift.db"
    tracker = DriftTracker(store)
    tracker.record("fs.read", {"path": "/a"})
    tracker.record("git.status", {"branch": "main"})
    assert set(tracker.baselines) == {"fs.read", "git.status"}


def test_store_file_is_valid_sqlite(tmp_path):
    store = tmp_path / "nested" / "drift.db"
    DriftTracker(store).record("fs.read", {"path": "/a"})
    conn = sqlite3.connect(str(store))
    rows = conn.execute("SELECT tool, shape FROM baselines").fetchall()
    conn.close()
    assert len(rows) == 1
    tool, shape_json = rows[0]
    assert tool == "fs.read"
    assert json.loads(shape_json) == shape_of({"path": "/a"})


def test_unknown_tool_has_no_drift():
    assert DriftTracker().check("never.seen", {"a": 1}) == []


def test_corrupt_store_raises_value_error(tmp_path):
    store = tmp_path / "drift.db"
    store.write_text("not a database")
    with pytest.raises(ValueError, match="not a valid SQLite database"):
        DriftTracker(store)


def test_shape_of_records_later_array_elements_with_type_drift():
    # Issue #19: the second array element is a string while the first is an
    # object. Both element shapes must be recorded, or drift in later elements
    # is invisible to compare_shapes.
    shape = shape_of({"items": [{"id": 1, "name": "a"}, "invalid_string"]})
    assert shape["$.items[1]"] == "string"


def test_shape_of_samples_up_to_three_elements():
    shape = shape_of({"items": [1, 2, 3, 4, 5]})
    assert "$.items[0]" in shape
    assert "$.items[1]" in shape
    assert "$.items[2]" in shape
    assert "$.items[3]" not in shape


def test_shape_of_uniform_array_fingerprints_each_sampled_item():
    # A uniform array fingerprints the shape of each sampled element.
    shape = shape_of({"items": [{"id": 1}, {"id": 2}]})
    assert shape["$.items[0]"] == "object"
    assert shape["$.items[0].id"] == "integer"
    assert shape["$.items[1]"] == "object"
    assert shape["$.items[1].id"] == "integer"


def test_drift_tracker_detects_type_drift_in_later_array_element():
    tracker = DriftTracker()
    tracker.record("tool", {"items": [{"id": 1, "name": "a"}]})
    violations = tracker.check("tool", {"items": [{"id": 1, "name": "a"}, "bad"]})
    assert [v.code for v in violations] == ["MCPR004"]
    assert violations[0].path == "$.items[1]"
