"""Unit tests for shared.delta_utils.backend.

Pure dispatcher logic. Does not require PySpark or a Spark session — uses
``monkeypatch`` to fake the active-session probe.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.delta_utils import backend as backend_mod


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts with an unset ASTROTURF_DELTA_BACKEND env var."""
    monkeypatch.delenv(backend_mod.ENV_VAR, raising=False)


def test_get_configured_backend_defaults_to_auto() -> None:
    assert backend_mod.get_configured_backend() == "auto"


def test_get_configured_backend_reads_env_lowercased(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(backend_mod.ENV_VAR, "Spark")
    assert backend_mod.get_configured_backend() == "spark"
    monkeypatch.setenv(backend_mod.ENV_VAR, "DELTA_RS")
    assert backend_mod.get_configured_backend() == "delta_rs"
    monkeypatch.setenv(backend_mod.ENV_VAR, "  AUTO  ")
    assert backend_mod.get_configured_backend() == "auto"


def test_get_configured_backend_rejects_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(backend_mod.ENV_VAR, "duck-db")
    with pytest.raises(ValueError, match="Invalid ASTROTURF_DELTA_BACKEND"):
        backend_mod.get_configured_backend()


def test_looks_like_databricks_path_examples() -> None:
    assert backend_mod.looks_like_databricks_path(
        "/Volumes/astroturf/demo/exports/_lakehouse/bronze/raw_comments"
    )
    assert backend_mod.looks_like_databricks_path("/dbfs/tmp/x")
    assert backend_mod.looks_like_databricks_path("dbfs:/tmp/x")
    assert not backend_mod.looks_like_databricks_path("./data/bronze/raw_comments")
    assert not backend_mod.looks_like_databricks_path(
        r"C:\example\astroturf\data\bronze\raw_comments"
    )
    # Path objects work too — Path stringification is consistent.
    assert backend_mod.looks_like_databricks_path(
        Path("/Volumes/astroturf/demo/exports/_lakehouse/bronze/raw_comments")
    )


def _fake_active_session(value):
    """Return a callable for monkeypatch.setattr that mimics getActiveSession."""

    def _resolve():
        return value

    return _resolve


def test_resolve_backend_auto_local_path_returns_delta_rs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # auto + local path -> delta_rs regardless of whether Spark is active.
    monkeypatch.setattr(
        backend_mod, "_active_spark_session", _fake_active_session(object())
    )
    assert backend_mod.resolve_backend("./data/bronze/raw_comments") == "delta_rs"


def test_resolve_backend_auto_fuse_path_no_session_falls_back(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # auto + FUSE path + NO active Spark session -> delta_rs (with a warning).
    monkeypatch.setattr(
        backend_mod, "_active_spark_session", _fake_active_session(None)
    )
    with caplog.at_level("WARNING"):
        choice = backend_mod.resolve_backend("/Volumes/x/y/z")
    assert choice == "delta_rs"
    assert any("no active Spark session" in r.message for r in caplog.records)


def test_resolve_backend_auto_fuse_path_with_session_uses_spark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        backend_mod, "_active_spark_session", _fake_active_session(object())
    )
    assert backend_mod.resolve_backend("/Volumes/x/y/z") == "spark"


def test_resolve_backend_explicit_spark_overrides_path_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(backend_mod.ENV_VAR, "spark")
    monkeypatch.setattr(
        backend_mod, "_active_spark_session", _fake_active_session(None)
    )
    # Even on a local path with no Spark session, explicit "spark" wins.
    # (Caller is responsible for ensuring a Spark session actually exists.)
    assert backend_mod.resolve_backend("./data/bronze/raw_comments") == "spark"


def test_resolve_backend_explicit_delta_rs_overrides_path_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(backend_mod.ENV_VAR, "delta_rs")
    monkeypatch.setattr(
        backend_mod, "_active_spark_session", _fake_active_session(object())
    )
    # Even on a Databricks path with a live Spark session, explicit "delta_rs"
    # wins — used for rollback scenarios.
    assert backend_mod.resolve_backend("/Volumes/x/y/z") == "delta_rs"


def test_should_use_spark_is_resolve_backend_eq_spark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        backend_mod, "_active_spark_session", _fake_active_session(object())
    )
    assert backend_mod.should_use_spark("/Volumes/x/y/z") is True
    assert backend_mod.should_use_spark("./data/x") is False
