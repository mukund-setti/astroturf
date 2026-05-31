#!/usr/bin/env python3
"""Diagnose Astroturf medallion Delta tables on Databricks.

Walks one or more Unity Catalog catalogs, classifies each entry under the
``bronze`` / ``silver`` / ``gold`` / ``demo`` schemas as a view or a real
managed/external Delta table, and reports DESCRIBE DETAIL / DESCRIBE HISTORY
for every underlying path-based Delta table behind the views.

Read-only. Performs no mutations.

Why this exists
---------------
Every analytic "table" exposed in Unity Catalog under ``<catalog>.bronze.*``,
``<catalog>.silver.*``, and ``<catalog>.gold.*`` for this project is actually
a ``CREATE OR REPLACE VIEW`` over a ``delta.`<fuse_path>``` location (see
``notebooks/databricks/web_analysis_job.py::_register_delta_view``). The
durable storage lives under ``/Volumes/.../{bronze,silver,gold}/...`` Delta
paths. Confusing the view layer with the underlying storage produces wrong
operational conclusions ("the table is corrupt", "we need to RESTORE",
"saveAsTable will solve this"). This tool surfaces both layers in one pass
so the next operator does not re-learn this the hard way.

Usage
-----
Quick check across the two catalogs we use today::

    python scripts/diagnose_delta_paths.py --catalog astroturf --catalog workspace

Deeper history dive on a single catalog::

    python scripts/diagnose_delta_paths.py --catalog astroturf \
        --include-history-versions 50

The tool requires either ``DATABRICKS_TOKEN`` in the environment or a
configured Databricks CLI profile (``~/.databrickscfg``). It uses the
Statement Execution API against a serverless SQL warehouse; pass
``--warehouse-id`` to target a different warehouse.
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx


DEFAULT_WAREHOUSE_ID = "395e3efad4d3fd98"
DEFAULT_CATALOGS = ("astroturf", "workspace")
DEFAULT_SCHEMAS = ("bronze", "silver", "gold", "demo")
DEFAULT_HISTORY_LIMIT = 15

# Path-based tables we want a row-count breakdown for (where it's meaningful).
_DOCKET_GROUPED_TABLES = ("raw_comments", "parsed_comments")


def _load_host(cli_value: str | None) -> str:
    if cli_value:
        return cli_value.rstrip("/")
    env = os.environ.get("DATABRICKS_HOST")
    if env:
        return env.rstrip("/")
    cfg_path = Path.home() / ".databrickscfg"
    if cfg_path.exists():
        cfg = configparser.ConfigParser()
        cfg.read(cfg_path)
        for section_name in cfg.sections():
            host = cfg[section_name].get("host")
            if host:
                return host.rstrip("/")
        # ``.databrickscfg`` can declare bare ``host = ...`` lines above any
        # ``[section]`` header (the CLI tolerates that). configparser won't
        # surface those as defaults without a [DEFAULT] header, so walk the
        # file by hand for the bare-host fallback.
        for raw in cfg_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith((";", "#", "[")):
                continue
            if line.lower().startswith("host"):
                _, _, value = line.partition("=")
                value = value.strip().rstrip("/")
                if value:
                    return value
    raise RuntimeError(
        "Could not resolve a Databricks host. Set --host, DATABRICKS_HOST, "
        "or configure ~/.databrickscfg."
    )


def _load_token() -> str:
    env = os.environ.get("DATABRICKS_TOKEN")
    if env:
        return env
    raise RuntimeError(
        "DATABRICKS_TOKEN not set. Use `databricks auth token --output json` "
        "and pipe the access_token, or set DATABRICKS_TOKEN directly."
    )


def _execute(
    client: httpx.Client,
    host: str,
    token: str,
    statement: str,
    warehouse_id: str,
    *,
    wait_timeout_s: int = 90,
) -> dict[str, Any]:
    """Run a SQL statement, polling until completion or ``wait_timeout_s``."""
    url = f"{host}/api/2.0/sql/statements"
    payload = {
        "warehouse_id": warehouse_id,
        "statement": statement,
        "wait_timeout": "30s",
        "on_wait_timeout": "CONTINUE",
        "disposition": "INLINE",
        "format": "JSON_ARRAY",
    }
    r = client.post(url, json=payload, headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    data = r.json()
    statement_id = data["statement_id"]

    deadline = time.monotonic() + wait_timeout_s
    while data["status"]["state"] in ("PENDING", "RUNNING"):
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"Statement {statement_id} timed out after {wait_timeout_s}s"
            )
        time.sleep(2.0)
        g = client.get(
            f"{host}/api/2.0/sql/statements/{statement_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        g.raise_for_status()
        data = g.json()

    if data["status"]["state"] != "SUCCEEDED":
        return {
            "ok": False,
            "state": data["status"]["state"],
            "error": data.get("status", {}).get("error", {}),
            "columns": [],
            "rows": [],
        }

    schema = data["manifest"]["schema"]
    columns = [c["name"] for c in schema["columns"]]
    rows = data.get("result", {}).get("data_array") or []
    return {"ok": True, "state": "SUCCEEDED", "columns": columns, "rows": rows}


def _show_tables(
    client, host, token, warehouse_id, catalog: str, schema: str
) -> list[str]:
    out = _execute(
        client, host, token, f"SHOW TABLES IN {catalog}.{schema}", warehouse_id
    )
    if not out["ok"]:
        return []
    cols = out["columns"]
    name_idx = cols.index("tableName") if "tableName" in cols else 1
    return [r[name_idx] for r in out["rows"]]


def _show_create(client, host, token, warehouse_id, full: str) -> str | None:
    out = _execute(client, host, token, f"SHOW CREATE TABLE {full}", warehouse_id)
    if not out["ok"] or not out["rows"]:
        return None
    return out["rows"][0][0] or None


def _extract_delta_path(view_sql: str) -> str | None:
    match = re.search(r"delta\.`([^`]+)`", view_sql)
    return match.group(1) if match else None


def _safe_print_table(out: dict[str, Any]) -> str:
    if not out["ok"]:
        err = out.get("error") or {}
        msg = err.get("message") or err.get("error_code") or str(out.get("state"))
        return f"  _query failed_: `{msg}`\n"
    if not out["rows"]:
        return "  _(no rows)_\n"
    cols = out["columns"]
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    for row in out["rows"]:
        cells = []
        for v in row:
            if v is None:
                cells.append("")
            elif isinstance(v, (dict, list)):
                cells.append("`" + json.dumps(v, sort_keys=True)[:80] + "`")
            else:
                s = str(v)
                if len(s) > 120:
                    s = s[:117] + "..."
                cells.append(s.replace("|", "\\|"))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _format_detail(detail: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if not detail["ok"] or not detail["rows"]:
        out.append(_safe_print_table(detail))
        return out
    cols = detail["columns"]
    row = detail["rows"][0]
    keys = (
        "format",
        "id",
        "name",
        "location",
        "partitionColumns",
        "clusteringColumns",
        "numFiles",
        "sizeInBytes",
        "createdAt",
        "lastModified",
        "minReaderVersion",
        "minWriterVersion",
        "tableFeatures",
        "properties",
    )
    for k in keys:
        if k in cols:
            v = row[cols.index(k)]
            if isinstance(v, (dict, list)):
                v = json.dumps(v, sort_keys=True)
            out.append(f"- **{k}**: `{v}`")
    out.append("")
    return out


def _diagnose(
    args: argparse.Namespace,
) -> str:
    host = _load_host(args.host)
    token = _load_token()
    warehouse_id = args.warehouse_id

    print(f"Host: {host}", flush=True)
    print(f"Warehouse: {warehouse_id}", flush=True)
    print(f"Catalogs: {', '.join(args.catalog)}", flush=True)

    report: list[str] = []
    report.append("# Delta path diagnosis report\n")
    report.append(f"- Host: `{host}`\n- Warehouse: `{warehouse_id}`\n")
    report.append("Read-only. No mutations performed.\n")

    path_targets: list[tuple[str, str]] = []  # (view_name, fuse_path)

    with httpx.Client(timeout=60.0) as client:
        for cat in args.catalog:
            report.append(f"\n## Catalog `{cat}`\n")
            for sch in args.schema:
                tables = _show_tables(client, host, token, warehouse_id, cat, sch)
                if not tables:
                    report.append(
                        f"### `{cat}.{sch}` — _no entries or schema missing_\n"
                    )
                    continue
                report.append(f"### `{cat}.{sch}` — {len(tables)} entr(y/ies)\n")
                report.append(", ".join(f"`{t}`" for t in tables) + "\n")
                for t in tables:
                    full = f"{cat}.{sch}.{t}"
                    create_sql = _show_create(client, host, token, warehouse_id, full)
                    if not create_sql:
                        report.append(f"- `{full}` — _SHOW CREATE returned nothing_\n")
                        continue
                    upper = create_sql.upper()
                    if "CREATE VIEW" in upper or "CREATE OR REPLACE VIEW" in upper:
                        underlying = _extract_delta_path(create_sql)
                        report.append(
                            f"- `{full}` is a **VIEW**; underlying = `{underlying}`\n"
                        )
                        if underlying:
                            path_targets.append((full, underlying))
                    else:
                        report.append(
                            f"- `{full}` is a **TABLE** (managed or external).\n"
                        )
                        if args.include_managed_table_history:
                            detail = _execute(
                                client,
                                host,
                                token,
                                f"DESCRIBE DETAIL {full}",
                                warehouse_id,
                            )
                            report.extend(_format_detail(detail))
                            hist = _execute(
                                client,
                                host,
                                token,
                                f"DESCRIBE HISTORY {full} LIMIT {args.include_history_versions}",
                                warehouse_id,
                            )
                            report.append(
                                f"\n#### `{full}` — DESCRIBE HISTORY (last {args.include_history_versions})\n"
                            )
                            report.append(_safe_print_table(hist))

        report.append("\n## Underlying path-based Delta tables\n")
        seen: set[str] = set()
        for full, path in path_targets:
            if path in seen:
                continue
            seen.add(path)
            report.append(f"\n### `{path}`\n")
            report.append(f"- Backs view(s): `{full}`\n")

            detail = _execute(
                client,
                host,
                token,
                f"DESCRIBE DETAIL delta.`{path}`",
                warehouse_id,
            )
            report.extend(_format_detail(detail))
            if not detail["ok"]:
                continue

            hist = _execute(
                client,
                host,
                token,
                f"DESCRIBE HISTORY delta.`{path}` LIMIT {args.include_history_versions}",
                warehouse_id,
            )
            report.append(
                f"\n#### `{path}` — DESCRIBE HISTORY (last {args.include_history_versions})\n"
            )
            if hist["ok"] and hist["rows"]:
                keep = (
                    "version",
                    "timestamp",
                    "userName",
                    "operation",
                    "operationMetrics",
                    "operationParameters",
                    "isBlindAppend",
                )
                cols = hist["columns"]
                idx = [cols.index(k) for k in keep if k in cols]
                trimmed = {
                    "ok": True,
                    "columns": [cols[i] for i in idx],
                    "rows": [[r[i] for i in idx] for r in hist["rows"]],
                }
                report.append(_safe_print_table(trimmed))
            else:
                report.append(_safe_print_table(hist))

            verq = _execute(
                client,
                host,
                token,
                "SELECT MIN(version) AS minv, MAX(version) AS maxv, "
                "COUNT(DISTINCT version) AS nver "
                f"FROM (DESCRIBE HISTORY delta.`{path}`)",
                warehouse_id,
            )
            report.append(f"\n#### `{path}` — version contiguity check\n")
            report.append(_safe_print_table(verq))

            if any(t in path for t in _DOCKET_GROUPED_TABLES):
                counts = _execute(
                    client,
                    host,
                    token,
                    f"SELECT docket_id, COUNT(*) AS n FROM delta.`{path}` "
                    "GROUP BY docket_id ORDER BY n DESC LIMIT 25",
                    warehouse_id,
                )
                report.append(f"\n#### `{path}` — top dockets by row count\n")
                report.append(_safe_print_table(counts))

    return "\n".join(report)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Diagnose Astroturf medallion Delta tables on Databricks."
    )
    p.add_argument(
        "--catalog",
        action="append",
        default=None,
        help=(
            "Unity Catalog name to inspect. Pass multiple times for several "
            f"catalogs. Defaults to {', '.join(DEFAULT_CATALOGS)}."
        ),
    )
    p.add_argument(
        "--schema",
        action="append",
        default=None,
        help=(
            "Schema to walk within each catalog. Pass multiple times. "
            f"Defaults to {', '.join(DEFAULT_SCHEMAS)}."
        ),
    )
    p.add_argument(
        "--include-history-versions",
        type=int,
        default=DEFAULT_HISTORY_LIMIT,
        help=(
            "Number of DESCRIBE HISTORY rows to fetch per Delta table. "
            f"Defaults to {DEFAULT_HISTORY_LIMIT}."
        ),
    )
    p.add_argument(
        "--include-managed-table-history",
        action="store_true",
        help=(
            "Also dump DESCRIBE DETAIL/HISTORY for catalog-managed tables, "
            "not just for path-based tables behind views."
        ),
    )
    p.add_argument("--host", default=None, help="Databricks workspace URL override.")
    p.add_argument(
        "--warehouse-id",
        default=os.environ.get("ASTROTURF_DIAGNOSE_WAREHOUSE_ID")
        or DEFAULT_WAREHOUSE_ID,
        help=(
            "Serverless SQL warehouse ID to run the diagnosis queries on. "
            "Defaults to the Astroturf starter warehouse; override with "
            "ASTROTURF_DIAGNOSE_WAREHOUSE_ID or --warehouse-id."
        ),
    )
    p.add_argument(
        "--output",
        default=None,
        help="Write the Markdown report to this path; default is stdout.",
    )
    args = p.parse_args(argv)
    if not args.catalog:
        args.catalog = list(DEFAULT_CATALOGS)
    if not args.schema:
        args.schema = list(DEFAULT_SCHEMAS)
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = _diagnose(args)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"Wrote {out_path} ({out_path.stat().st_size} bytes)", flush=True)
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
