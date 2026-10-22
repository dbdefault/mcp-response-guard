# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Descend into array `items`/`prefixItems` schemas when reporting undeclared
  fields, so array element drift is reported as `MCPR002` (#27).

## [0.2.0] - 2026-10-11

### Added

- SQLite-backed `DriftTracker` storage for persistent baseline tracking across runs.
- `.github/FUNDING.yml` for GitHub Sponsors.

### Fixed

- Skip `_extra_fields` when `additionalProperties` is a schema or `false` (#16, #17).
- Update CLI default and tests for the SQLite store.
- Remove unused `Path` import.

## [0.1.0] - 2026-10-06

First working release.

### Added

- `mcp_response_guard` package with runtime schema validation, response shape
  fingerprints and baseline drift comparison.
- Detector codes MCPR001 (missing required field), MCPR002 (undeclared field),
  MCPR003 (type mismatch), MCPR004 (shape drift and other schema constraints),
  MCPR005 (error response off-schema).
- `mcp-response-guard check` — validate one response against its declared schema.
- `mcp-response-guard record` — compare a response against the stored baseline
  for a tool and update it; `--no-update` compares without writing.
- `mcp-response-guard report` — list the tool baselines in a store.
- `text`, `json` and SARIF 2.1.0 output, with `--output` writing to a file.
- Non-zero exit codes on violations, so `check` and `record` work as CI gates.
- Python API: `validate_response`, `validate_error_response`, `DriftTracker`,
  `shape_of`, `compare_shapes`, `to_sarif`, `write_sarif`.
- GitHub Actions CI: `ruff check` and `pytest` on Python 3.10, 3.11, 3.12, 3.13.

### Changed

- README rewritten to document the shipped tool. The previous version described
  an unimplemented proposal.
