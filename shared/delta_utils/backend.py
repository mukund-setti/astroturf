"""Backend selection for Delta writes.

Astroturf supports two Delta writer backends:

* ``delta_rs`` — pure-Python writes via the ``deltalake`` library. Used for
  local Windows development, unit tests, and any code path that does not
  have a Spark session available. Works against local filesystem paths.

* ``spark`` — JVM-backed Spark writes via the ``delta-spark`` package and the
  active ``pyspark.sql.SparkSession``. Used inside Databricks notebooks and
  jobs where Spark is already available. Reads/writes against Unity Catalog
  Volume FUSE paths (``/Volumes/.../...``) without the
  copy-out/write/copy-back round-trip that the old delta-rs FUSE bypass
  required (see ADR-0017).

Routing is controlled by ``ASTROTURF_DELTA_BACKEND``:

* ``auto`` (default) — use Spark when (a) the target path looks like a
  Databricks Volumes/DBFS path and (b) an active Spark session is detected;
  otherwise fall back to ``delta_rs``.
* ``spark`` — always use Spark. Caller's responsibility to ensure a session
  exists.
* ``delta_rs`` — always use delta-rs. Useful for forcing legacy behavior
  during a rollback, or for local-only smoke tests.

This module is intentionally Spark-import-free at module level so importing it
does not pull PySpark into local-only test sessions.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

Backend = Literal["delta_rs", "spark"]
BackendChoice = Literal["delta_rs", "spark", "auto"]

ENV_VAR = "ASTROTURF_DELTA_BACKEND"
_VALID_CHOICES: tuple[BackendChoice, ...] = ("auto", "spark", "delta_rs")
_DATABRICKS_PATH_PREFIXES = ("/Volumes/", "/dbfs/", "dbfs:/")


def get_configured_backend() -> BackendChoice:
    """Return the configured backend choice from the environment.

    Falls back to ``auto`` when the env var is unset. Raises ``ValueError``
    for an unrecognised value rather than silently picking a default — a
    misspelled flag is exactly the kind of silent-failure CLAUDE.md
    prohibits.
    """
    raw = (os.environ.get(ENV_VAR) or "auto").strip().lower()
    if raw not in _VALID_CHOICES:
        raise ValueError(
            f"Invalid {ENV_VAR}={raw!r}. Allowed values: {', '.join(_VALID_CHOICES)}."
        )
    return raw  # type: ignore[return-value]


def looks_like_databricks_path(path: str | Path) -> bool:
    """True for FUSE Volume / DBFS paths that the Spark backend should own.

    Normalises backslashes to forward slashes before checking, so callers
    that pass a ``WindowsPath("/Volumes/...")`` from a Windows process
    (constructed for a remote Linux Databricks target) still match.
    """
    s = str(path).replace("\\", "/")
    return any(s.startswith(prefix) for prefix in _DATABRICKS_PATH_PREFIXES)


def _active_spark_session():
    """Return the active SparkSession, or None.

    Wrapped in a try/except so this module is safe to import on a machine
    that does not have PySpark installed.
    """
    try:
        from pyspark.sql import SparkSession  # noqa: WPS433
    except Exception:
        return None
    try:
        return SparkSession.getActiveSession()
    except Exception:
        return None


def resolve_backend(path: str | Path) -> Backend:
    """Decide which backend to use for ``path`` given the env configuration.

    ``auto`` policy:
      - Databricks-looking path AND Spark session active -> ``spark``
      - Otherwise -> ``delta_rs``
    """
    choice = get_configured_backend()
    if choice == "spark":
        return "spark"
    if choice == "delta_rs":
        return "delta_rs"
    if not looks_like_databricks_path(path):
        return "delta_rs"
    if _active_spark_session() is None:
        log.warning(
            "ASTROTURF_DELTA_BACKEND=auto and path %s looks like a Databricks "
            "FUSE path, but no active Spark session was found. Falling back "
            "to delta_rs — this will hit the FUSE round-trip and is almost "
            "certainly not what you want on Databricks. Either run inside a "
            "notebook with a Spark session or set ASTROTURF_DELTA_BACKEND=spark.",
            path,
        )
        return "delta_rs"
    return "spark"


def should_use_spark(path: str | Path) -> bool:
    """Convenience wrapper for the common ``backend == 'spark'`` check."""
    return resolve_backend(path) == "spark"
