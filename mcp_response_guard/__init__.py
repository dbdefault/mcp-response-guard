"""Runtime schema validation and drift detection for MCP tool responses."""

from __future__ import annotations

__version__ = "0.2.0"

from .drift import DriftTracker, compare_shapes, shape_of
from .models import Severity, Violation
from .sarif import to_sarif, write_sarif
from .validate import validate_error_response, validate_response

__all__ = [
    "__version__",
    "DriftTracker",
    "Severity",
    "Violation",
    "compare_shapes",
    "shape_of",
    "to_sarif",
    "validate_error_response",
    "validate_response",
    "write_sarif",
]
