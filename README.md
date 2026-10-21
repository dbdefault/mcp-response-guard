

# MCP Response Guard

> Runtime schema validation and drift detection for MCP server responses.
> Catch tool outputs that deviate from their declared JSON schemas.

MCP (Model Context Protocol) servers declare tool schemas — but their actual
outputs drift. A server returns a field it never declared, drops a required
one, changes a field's type, or quietly reshapes its payload between calls.
`mcp-response-guard` validates a response against the schema the server
declared, and fingerprints response shapes over time so silent drift surfaces
even when the response is still technically valid.

## Status

Working CLI, Python API and test suite. Alpha.

## Install

```bash
pip install git+https://github.com/yunaremaia/mcp-response-guard.git
```

Not on PyPI. Python 3.10+.

## CLI

### `check` — validate one response against its schema

```bash
mcp-response-guard check resp.json --schema schema.json --tool fs.read
```

| Option | Meaning |
|--------|---------|
| `--schema PATH` | JSON Schema the tool declared (required) |
| `--tool NAME` | Tool name recorded on each violation |
| `--format` | `text` (default), `json` or `sarif` |
| `--output PATH` | Write the report to a file instead of stdout |

Exits `1` when there are violations, `0` when the response matches.

### `record` — check a response for drift, then store it as the new baseline

```bash
mcp-response-guard record resp.json --tool fs.read --baseline .drift_log.db
```

| Option | Meaning |
|--------|---------|
| `--tool NAME` | Tool the response came from (required) |
| `--baseline PATH` | Baseline store, created if missing (default `.drift_log.db`) |
| `--no-update` | Compare only; leave the stored baseline untouched |
| `--format`, `--output` | As for `check` |

The first `record` for a tool establishes its baseline and reports no drift.
Later records are compared against it; a field that appeared, disappeared or
changed type is `MCPR004`. Exits `1` on drift.

### `report` — list the baselines stored in a file

```bash
mcp-response-guard report .drift_log.db
```

Same `--format` and `--output` options. A missing or empty store is not an
error.

## Detector codes

| Code | Severity | Description |
|------|----------|-------------|
| MCPR001 | HIGH | Response is missing a field the schema declares as required. One violation per path, naming every absent field. |
| MCPR002 | HIGH | Response contains a field the schema does not declare — caught even when `additionalProperties` is not `false`. |
| MCPR003 | MEDIUM | Response field has a different JSON type than the schema declares. |
| MCPR004 | LOW / MEDIUM | Response shape differs from the recorded baseline (LOW), or it violates another schema constraint such as `enum` or `minLength` (MEDIUM). A type change between baseline and response is MEDIUM. |
| MCPR005 | MEDIUM | Error response does not match the error schema the server declared. |

## Python API

```python
from mcp_response_guard import DriftTracker, Severity, validate_response, validate_error_response

violations = validate_response({"path": "/etc/hosts"}, schema, tool="fs.read")
if violations:
    for v in violations:
        print(v.code, v.severity.value, v.path, v.message)

error_violations = validate_error_response(error_payload, error_schema, tool="fs.read")

tracker = DriftTracker(".drift_log.db")
drift = tracker.check("fs.read", response)   # compare only
drift = tracker.record("fs.read", response)  # compare, then store as the new baseline
```

`to_sarif(violations)` renders a SARIF 2.1.0 log for GitHub Code Scanning;
`write_sarif(violations, path)` writes it, creating parent directories.

## CI gate

`check` and `record` exit non-zero on violations, so they drop straight into a
pipeline:

```yaml
- run: mcp-response-guard record fixtures/fs_read.json --tool fs.read
- run: mcp-response-guard check live_response.json --schema schemas/read.json \
    --format sarif --output results.sarif
```

This repository's own CI runs `ruff check .` and `pytest -q` on Python
3.10–3.13.

## Related tools

- [`mcp-guard`](https://github.com/yunaremaia/mcp-guard) — validates MCP server
  configurations and tool schemas at build/CI time, with SARIF output.
- [`vibeguard`](https://github.com/yunaremaia/vibeguard) — audits agent
  configuration for prompt-injection and secret exposure, with SARIF output.

## Roadmap

- [ ] Baseline auto-learning (first N calls establish the baseline)
- [ ] Alerting (Slack/email) on drift
- [ ] OpenTelemetry spans for violation tracing
- [ ] Live MCP client integration, instead of validating recorded payloads

## License

MIT
