"""Command line interface: validate responses, record baselines, report drift."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from . import __version__
from .drift import DriftTracker
from .models import Severity, Violation
from .sarif import to_sarif
from .validate import validate_response

_SEVERITY_STYLE = {Severity.HIGH: "red", Severity.MEDIUM: "yellow", Severity.LOW: "cyan"}


def _load_json(path: str | Path, label: str):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise click.ClickException(f"{label} file not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"{label} file is not valid JSON ({path}): {exc}") from None


def _write_out(out: str, payload: str) -> None:
    """Write a report to ``out``, creating parent directories as needed."""
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _echo_text(message: str, out: str | None) -> None:
    """Emit a text-format line to ``out`` or to stdout."""
    if out:
        _write_out(out, message + "\n")
    else:
        click.echo(message)


def _echo_violations(violations: list[Violation], fmt: str, out: str | None) -> None:
    if fmt == "json":
        payload = json.dumps([v.as_dict() for v in violations], indent=2)
        if out:
            _write_out(out, payload + "\n")
        else:
            click.echo(payload)
        return
    if fmt == "sarif":
        payload = json.dumps(to_sarif(violations), indent=2)
        if out:
            _write_out(out, payload + "\n")
        else:
            click.echo(payload)
        return
    if out:
        if not violations:
            return
        lines = [f"{v.code} {v.severity.value}: {v.message}" for v in violations]
        _write_out(out, "\n".join(lines) + "\n")
        return
    for violation in violations:
        click.secho(
            f"{violation.code} {violation.severity.value}: {violation.message}",
            fg=_SEVERITY_STYLE[violation.severity],
            err=True,
        )


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """Validate MCP tool responses against their declared schemas."""


@main.command()
@click.argument("response", type=click.Path())
@click.option("--schema", "schema_path", required=True, help="JSON Schema file the tool declared.")
@click.option("--tool", default=None, help="Tool name, recorded on each violation.")
@click.option("--format", "fmt", type=click.Choice(["text", "json", "sarif"]), default="text")
@click.option("--output", "out", default=None, help="Write the report here instead of stdout.")
def check(response, schema_path, tool, fmt, out) -> None:
    """Validate RESPONSE (a JSON file) against SCHEMA. Exit 1 on violations."""
    violations = validate_response(
        _load_json(response, "response"), _load_json(schema_path, "schema"), tool=tool
    )
    _echo_violations(violations, fmt, out)
    if violations:
        sys.exit(1)
    if fmt == "text":
        _echo_text("OK: response matches schema", out)


@main.command()
@click.argument("response", type=click.Path())
@click.option("--tool", required=True, help="Tool name the response came from.")
@click.option(
    "--baseline",
    type=click.Path(),
    default=".drift_log.db",
    show_default=True,
    help="Baseline store, created if missing.",
)
@click.option("--format", "fmt", type=click.Choice(["text", "json", "sarif"]), default="text")
@click.option("--output", "out", default=None, help="Write the report here instead of stdout.")
@click.option(
    "--no-update",
    is_flag=True,
    help="Compare only; leave the stored baseline untouched.",
)
def record(response, tool, baseline, fmt, out, no_update) -> None:
    """Check RESPONSE for shape drift, then store it as the tool's new baseline."""
    payload = _load_json(response, "response")
    try:
        tracker = DriftTracker(baseline)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from None
    violations = tracker.check(tool, payload) if no_update else tracker.record(tool, payload)
    _echo_violations(violations, fmt, out)
    if violations:
        sys.exit(1)
    if fmt == "text":
        if not no_update:
            _echo_text(f"OK: baseline recorded for {tool} in {baseline}", out)
        else:
            _echo_text(f"OK: {tool} matches baseline", out)


@main.command()
@click.argument("baseline", type=click.Path())
@click.option("--format", "fmt", type=click.Choice(["text", "json", "sarif"]), default="text")
@click.option("--output", "out", default=None, help="Write the report here instead of stdout.")
def report(baseline, fmt, out) -> None:
    """List the tool baselines stored in BASELINE."""
    try:
        tracker = DriftTracker(baseline)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from None
    if not tracker.baselines:
        click.echo(f"No baselines stored in {baseline}")
        return
    if fmt == "text":
        for tool, shape in sorted(tracker.baselines.items()):
            click.echo(f"{tool}: {len(shape)} fields")
        return
    payload = json.dumps(tracker.baselines, indent=2, sort_keys=True) + "\n"
    if out:
        _write_out(out, payload)
    else:
        click.echo(payload, nl=False)


if __name__ == "__main__":
    main()
