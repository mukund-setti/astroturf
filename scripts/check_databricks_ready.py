#!/usr/bin/env python3
"""Check Databricks environment readiness without assuming credentials exist."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

DEFAULT_CATALOG = "workspace"
DEFAULT_SCHEMA_NAMES = ("bronze", "silver", "gold", "demo")
DEFAULT_FM_ENDPOINT = "databricks-bge-large-en"
DEFAULT_VS_ENDPOINT = "astroturf-vs-endpoint"


def load_simple_env(path: str = ".env") -> None:
    """Load key=value pairs from .env, preserving already-exported values."""
    env_path = Path(path)
    if not env_path.exists():
        return
    with env_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def masked(value: str | None) -> str:
    if not value:
        return "MISSING"
    return value[:8] + "..." if len(value) > 8 else "SET"


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    host = _normalize_host(os.environ.get("DATABRICKS_HOST"))
    token = os.environ.get("DATABRICKS_TOKEN")
    http_path = os.environ.get("DATABRICKS_HTTP_PATH")
    catalog = args.catalog

    report: dict[str, Any] = {
        "status": "INCOMPLETE",
        "catalog": catalog,
        "steps": {},
        "remediations": [],
    }

    _check_environment(report, host=host, token=token, http_path=http_path)
    has_sdk = _check_imports(report)
    has_credentials = bool(host and token)

    if has_credentials:
        _check_http_connectivity(report, host=host, token=token, timeout=args.timeout)
        _check_unity_catalog(
            report,
            host=host,
            token=token,
            catalog=catalog,
            timeout=args.timeout,
        )
        _check_foundation_model(
            report,
            host=host,
            token=token,
            endpoint=args.foundation_model_endpoint,
            timeout=args.timeout,
        )
    else:
        _skip(report, "connectivity", "Missing Databricks host or token.")
        _skip(report, "unity_catalog", "Missing Databricks host or token.")
        _skip(report, "foundation_model", "Missing Databricks host or token.")

    if has_credentials and has_sdk:
        _check_vector_search(
            report,
            host=host,
            token=token,
            endpoint=args.vector_search_endpoint,
            timeout=args.timeout,
        )
    else:
        _skip(
            report,
            "vector_search",
            "Missing credentials or Databricks Vector Search package.",
        )

    if has_credentials and http_path and report["steps"]["imports"]["sql_connector"]:
        _check_sql_warehouse(
            report,
            host=host,
            token=token,
            http_path=http_path,
            timeout=args.timeout,
        )
    else:
        _skip(
            report,
            "sql_warehouse",
            "DATABRICKS_HTTP_PATH is not configured or SQL connector is missing.",
        )

    statuses = [step["status"] for step in report["steps"].values()]
    if "FAIL" in statuses:
        report["status"] = "FAILED"
    elif "WARNING" in statuses:
        report["status"] = "WARNING"
    else:
        report["status"] = "READY"
    return report


def _check_environment(
    report: dict[str, Any],
    *,
    host: str | None,
    token: str | None,
    http_path: str | None,
) -> None:
    missing = [
        name
        for name, value in (("DATABRICKS_HOST", host), ("DATABRICKS_TOKEN", token))
        if not value
    ]
    status = "FAIL" if missing else "PASS"
    report["steps"]["environment"] = {
        "status": status,
        "variables": {
            "DATABRICKS_HOST": host or "MISSING",
            "DATABRICKS_TOKEN": masked(token),
            "DATABRICKS_HTTP_PATH": "SET" if http_path else "MISSING",
            "DATABRICKS_CATALOG": os.environ.get("DATABRICKS_CATALOG", "MISSING"),
        },
    }
    if missing:
        report["remediations"].append(
            "Set DATABRICKS_HOST and DATABRICKS_TOKEN in your shell, secret scope, "
            "or local .env before running live Databricks checks."
        )


def _check_imports(report: dict[str, Any]) -> bool:
    details: dict[str, str] = {}
    vector_search_ok = False
    sdk_ok = _import_ok("databricks.sdk")
    sql_ok = _import_ok("databricks.sql")
    vector_search_ok = _import_ok("databricks.vector_search.client")
    details["databricks-sdk"] = "INSTALLED" if sdk_ok else "MISSING"
    details["databricks-sql-connector"] = "INSTALLED" if sql_ok else "MISSING"
    details["databricks-vectorsearch"] = "INSTALLED" if vector_search_ok else "MISSING"
    status = "PASS" if sdk_ok else "FAIL"
    report["steps"]["imports"] = {
        "status": status,
        "details": details,
        "sdk": sdk_ok,
        "sql_connector": sql_ok,
        "vector_search": vector_search_ok,
    }
    if not sdk_ok:
        report["remediations"].append(
            "Install Databricks client packages with `uv sync` or "
            "`pip install databricks-sdk databricks-sql-connector "
            "databricks-vectorsearch`."
        )
    return vector_search_ok


def _check_http_connectivity(
    report: dict[str, Any], *, host: str, token: str, timeout: float
) -> None:
    step = {"status": "PASS", "details": {}}
    try:
        data = _get_json(host, token, "/api/2.0/preview/scim/v2/Me", timeout)
        step["details"]["current_user"] = data.get("userName") or data.get("id")
    except Exception as exc:
        step["status"] = "FAIL"
        step["details"]["error"] = _compact_error(exc)
        report["remediations"].append(
            "Verify DATABRICKS_HOST points at the workspace URL and "
            "DATABRICKS_TOKEN is active."
        )
    report["steps"]["connectivity"] = step


def _check_unity_catalog(
    report: dict[str, Any], *, host: str, token: str, catalog: str, timeout: float
) -> None:
    step = {"status": "PASS", "details": {"catalog": catalog, "schemas": {}}}
    try:
        _get_json(host, token, f"/api/2.1/unity-catalog/catalogs/{catalog}", timeout)
        missing = []
        for schema_name in DEFAULT_SCHEMA_NAMES:
            full_name = f"{catalog}.{schema_name}"
            try:
                _get_json(
                    host,
                    token,
                    f"/api/2.1/unity-catalog/schemas/{full_name}",
                    timeout,
                )
                step["details"]["schemas"][schema_name] = "FOUND"
            except Exception:
                step["details"]["schemas"][schema_name] = "MISSING"
                missing.append(schema_name)
        if missing:
            step["status"] = "WARNING"
            report["remediations"].append(
                f"Create missing Unity Catalog schemas under {catalog}: "
                + ", ".join(missing)
                + "."
            )
    except Exception as exc:
        step["status"] = "FAIL"
        step["details"]["error"] = _compact_error(exc)
        report["remediations"].append(
            f"Confirm the Unity Catalog `{catalog}` exists and your principal "
            "has USE CATALOG permission."
        )
    report["steps"]["unity_catalog"] = step


def _check_foundation_model(
    report: dict[str, Any], *, host: str, token: str, endpoint: str, timeout: float
) -> None:
    step = {"status": "PASS", "details": {"endpoint": endpoint}}
    try:
        data = _get_json(host, token, f"/api/2.0/serving-endpoints/{endpoint}", timeout)
        state = data.get("state") or {}
        step["details"]["state"] = state
    except Exception as exc:
        step["status"] = "WARNING"
        step["details"]["error"] = _compact_error(exc)
        report["remediations"].append(
            f"Confirm Foundation Model endpoint `{endpoint}` is available in "
            "this workspace and region."
        )
    report["steps"]["foundation_model"] = step


def _check_vector_search(
    report: dict[str, Any], *, host: str, token: str, endpoint: str, timeout: float
) -> None:
    step = {"status": "PASS", "details": {"endpoint": endpoint}}
    try:
        _get_json(host, token, f"/api/2.0/vector-search/endpoints/{endpoint}", timeout)
    except Exception as exc:
        step["status"] = "WARNING"
        step["details"]["error"] = _compact_error(exc)
        report["remediations"].append(
            f"Create or verify Vector Search endpoint `{endpoint}` before "
            "running Databricks Vector Search clustering."
        )
    report["steps"]["vector_search"] = step


def _check_sql_warehouse(
    report: dict[str, Any], *, host: str, token: str, http_path: str, timeout: float
) -> None:
    step = {"status": "PASS", "details": {}}
    try:
        from databricks import sql

        connection = sql.connect(
            server_hostname=host.replace("https://", "").replace("http://", ""),
            http_path=http_path,
            access_token=token,
            _socket_timeout=timeout,
        )
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchall()
        cursor.close()
        connection.close()
        step["details"]["query"] = "SELECT 1"
    except Exception as exc:
        step["status"] = "FAIL"
        step["details"]["error"] = _compact_error(exc)
        report["remediations"].append(
            "Check DATABRICKS_HTTP_PATH, warehouse state, and SQL warehouse permissions."
        )
    report["steps"]["sql_warehouse"] = step


def _skip(report: dict[str, Any], name: str, reason: str) -> None:
    report["steps"][name] = {"status": "SKIP", "reason": reason}


def _get_json(host: str, token: str, path: str, timeout: float) -> dict[str, Any]:
    url = host.rstrip("/") + path
    with httpx.Client(timeout=timeout) as client:
        response = client.get(url, headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
        return response.json()


def _normalize_host(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().rstrip("/")
    if not value:
        return None
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    return value


def _import_ok(module_name: str) -> bool:
    try:
        __import__(module_name)
    except Exception:
        return False
    return True


def _compact_error(exc: BaseException) -> str:
    text = str(exc).replace("\n", " ").strip()
    return text[:500] if text else exc.__class__.__name__


def print_human(report: dict[str, Any]) -> None:
    labels = {"PASS": "PASS", "WARNING": "WARN", "FAIL": "FAIL", "SKIP": "SKIP"}
    print()
    print("=" * 60)
    print("DATABRICKS READINESS CHECK")
    print("=" * 60)
    for name, step in report["steps"].items():
        status = step["status"]
        print(f"[{labels.get(status, status)}] {name.replace('_', ' ').title()}")
        details = step.get("details") or step.get("variables") or {}
        if details:
            for key, value in details.items():
                print(f"  - {key}: {value}")
        if step.get("reason"):
            print(f"  - reason: {step['reason']}")
        if step.get("error"):
            print(f"  - error: {step['error']}")
    print("=" * 60)
    print(f"OVERALL READINESS: {report['status']}")
    print("=" * 60)
    if report["remediations"]:
        print()
        print("Remediation steps:")
        for item in report["remediations"]:
            print(f"  * {item}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON only")
    parser.add_argument(
        "--catalog",
        default=os.environ.get("DATABRICKS_CATALOG", DEFAULT_CATALOG),
        help="Unity Catalog name to check",
    )
    parser.add_argument(
        "--foundation-model-endpoint",
        default=DEFAULT_FM_ENDPOINT,
        help="Foundation Model serving endpoint to check",
    )
    parser.add_argument(
        "--vector-search-endpoint",
        default=DEFAULT_VS_ENDPOINT,
        help="Vector Search endpoint to check",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="HTTP timeout in seconds for live checks",
    )
    parser.add_argument("--no-env-file", action="store_true", help="Do not load .env")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.no_env_file:
        load_simple_env()
    report = build_report(args)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print_human(report)
    return 0 if report["status"] != "FAILED" else 1


if __name__ == "__main__":
    sys.exit(main())
