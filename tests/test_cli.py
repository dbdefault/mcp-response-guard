"""CLI behaviour, including exit codes that a CI gate would rely on."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from mcp_response_guard import __version__
from mcp_response_guard.cli import main

SCHEMA = {
    "type": "object",
    "properties": {"path": {"type": "string"}, "size": {"type": "integer"}},
    "required": ["path", "size"],
}


@pytest.fixture
def runner():
    return CliRunner()


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_version_matches_package_metadata(runner):
    result = runner.invoke(main, ["--version"])
    assert __version__ in result.output


def test_check_exits_zero_on_matching_response(runner, tmp_path):
    schema = _write(tmp_path / "schema.json", SCHEMA)
    response = _write(tmp_path / "resp.json", {"path": "/etc/hosts", "size": 42})
    result = runner.invoke(main, ["check", response, "--schema", schema])
    assert result.exit_code == 0
    assert "OK" in result.output


def test_check_exits_one_on_violation(runner, tmp_path):
    schema = _write(tmp_path / "schema.json", SCHEMA)
    response = _write(tmp_path / "resp.json", {"path": "/etc/hosts"})
    result = runner.invoke(main, ["check", response, "--schema", schema, "--tool", "fs.read"])
    assert result.exit_code == 1
    assert "MCPR001" in result.output


def test_check_json_output_is_machine_readable(runner, tmp_path):
    schema = _write(tmp_path / "schema.json", SCHEMA)
    response = _write(tmp_path / "resp.json", {"path": "/etc/hosts"})
    result = runner.invoke(main, ["check", response, "--schema", schema, "--format", "json"])
    payload = json.loads(result.output)
    assert payload[0]["code"] == "MCPR001"
    assert payload[0]["severity"] == "HIGH"


def test_check_sarif_output(runner, tmp_path):
    schema = _write(tmp_path / "schema.json", SCHEMA)
    response = _write(tmp_path / "resp.json", {"path": "/etc/hosts"})
    result = runner.invoke(main, ["check", response, "--schema", schema, "--format", "sarif"])
    assert json.loads(result.output)["version"] == "2.1.0"


def test_check_writes_output_file(runner, tmp_path):
    schema = _write(tmp_path / "schema.json", SCHEMA)
    response = _write(tmp_path / "resp.json", {"path": "/etc/hosts"})
    out = tmp_path / "out" / "results.sarif"
    result = runner.invoke(
        main, ["check", response, "--schema", schema, "--format", "sarif", "--output", str(out)]
    )
    assert result.exit_code == 1
    assert out.is_file()


def test_check_text_output_writes_violations_to_file(runner, tmp_path):
    """--output must be honored for text format when there are violations (#34)."""
    schema = _write(tmp_path / "schema.json", SCHEMA)
    response = _write(tmp_path / "resp.json", {"path": "/etc/hosts"})
    out = tmp_path / "out" / "report.txt"
    result = runner.invoke(
        main,
        [
            "check",
            response,
            "--schema",
            schema,
            "--tool",
            "fs.read",
            "--format",
            "text",
            "--output",
            str(out),
        ],
    )
    assert result.exit_code == 1
    assert out.is_file()
    content = out.read_text(encoding="utf-8")
    assert "MCPR001" in content


def test_check_text_output_writes_ok_to_file(runner, tmp_path):
    """--output must capture the OK line for a clean text check (#34)."""
    schema = _write(tmp_path / "schema.json", SCHEMA)
    response = _write(tmp_path / "resp.json", {"path": "/etc/hosts", "size": 42})
    out = tmp_path / "out" / "ok.txt"
    result = runner.invoke(
        main,
        ["check", response, "--schema", schema, "--format", "text", "--output", str(out)],
    )
    assert result.exit_code == 0
    assert out.is_file()
    assert "OK: response matches schema" in out.read_text(encoding="utf-8")


def test_record_text_output_writes_violations_to_file(runner, tmp_path):
    """--output must be honored for text format on record drift (#34)."""
    store = str(tmp_path / "drift.db")
    first = _write(tmp_path / "a.json", {"path": "/a"})
    second = _write(tmp_path / "b.json", {"path": "/a", "inode": 7})
    runner.invoke(main, ["record", first, "--tool", "fs.read", "--baseline", store])
    out = tmp_path / "out" / "drift.txt"
    result = runner.invoke(
        main,
        [
            "record",
            second,
            "--tool",
            "fs.read",
            "--baseline",
            store,
            "--format",
            "text",
            "--output",
            str(out),
        ],
    )
    assert result.exit_code == 1
    assert out.is_file()
    assert "MCPR004" in out.read_text(encoding="utf-8")


def test_check_reports_missing_response_file(runner, tmp_path):
    schema = _write(tmp_path / "schema.json", SCHEMA)
    result = runner.invoke(main, ["check", str(tmp_path / "nope.json"), "--schema", schema])
    assert result.exit_code != 0
    assert "not found" in result.output


def test_check_reports_invalid_json(runner, tmp_path):
    schema = _write(tmp_path / "schema.json", SCHEMA)
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    result = runner.invoke(main, ["check", str(bad), "--schema", schema])
    assert result.exit_code != 0
    assert "not valid JSON" in result.output


def test_record_establishes_then_reports_drift(runner, tmp_path):
    store = str(tmp_path / "drift.db")
    first = _write(tmp_path / "a.json", {"path": "/a"})
    second = _write(tmp_path / "b.json", {"path": "/a", "inode": 7})

    ok = runner.invoke(main, ["record", first, "--tool", "fs.read", "--baseline", store])
    assert ok.exit_code == 0
    assert "baseline recorded" in ok.output

    drift = runner.invoke(main, ["record", second, "--tool", "fs.read", "--baseline", store])
    assert drift.exit_code == 1
    assert "MCPR004" in drift.output


def test_record_no_update_leaves_baseline_untouched(runner, tmp_path):
    store = str(tmp_path / "drift.db")
    first = _write(tmp_path / "a.json", {"path": "/a"})
    # Drift is a *shape* change, not a value change: "/a" and "/b" fingerprint
    # identically. Adding a field is what makes this response drift.
    other = _write(tmp_path / "b.json", {"path": "/b", "inode": 7})
    runner.invoke(main, ["record", first, "--tool", "fs.read", "--baseline", store])
    result = runner.invoke(
        main, ["record", other, "--tool", "fs.read", "--baseline", store, "--no-update"]
    )
    assert result.exit_code == 1
    from mcp_response_guard.drift import DriftTracker
    tracker = DriftTracker(store)
    assert tracker.baseline("fs.read") == shape_for({"path": "/a"})


def shape_for(payload):
    from mcp_response_guard import shape_of

    return shape_of(payload)


def test_report_lists_stored_tools(runner, tmp_path):
    store = str(tmp_path / "drift.db")
    response = _write(tmp_path / "a.json", {"path": "/a"})
    runner.invoke(main, ["record", response, "--tool", "fs.read", "--baseline", store])
    result = runner.invoke(main, ["report", store])
    assert "fs.read" in result.output


def test_report_on_missing_store_is_not_an_error(runner, tmp_path):
    result = runner.invoke(main, ["report", str(tmp_path / "nope.json")])
    assert result.exit_code == 0
    assert "No baselines" in result.output


def test_report_rejects_a_corrupt_store(runner, tmp_path):
    store = tmp_path / "drift.db"
    store.write_text("{nope", encoding="utf-8")
    result = runner.invoke(main, ["report", str(store)])
    assert result.exit_code != 0
    assert "not a valid SQLite database" in result.output


def test_report_json_output(runner, tmp_path):
    store = str(tmp_path / "drift.db")
    response = _write(tmp_path / "a.json", {"path": "/a"})
    runner.invoke(main, ["record", response, "--tool", "fs.read", "--baseline", store])
    result = runner.invoke(main, ["report", store, "--format", "json"])
    assert "fs.read" in json.loads(result.output)
