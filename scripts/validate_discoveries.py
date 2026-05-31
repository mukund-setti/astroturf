#!/usr/bin/env python3
"""scripts/validate_discoveries.py

Validate every docket in the discovery catalog against its source API
(regulations.gov v4 or FCC ECFS) and write the results back to the
`validation_status`, `validated_comment_count`, `validation_source`,
and `validated_at` columns of `docket_catalog`.

Why this exists
---------------
The discovery catalog blends three sources:
  1. Real public dockets pulled live from regulations.gov / ECFS.
  2. Real public dockets seeded by SQL (e.g. CFPB-2016-0025).
  3. Synthetic fallback seeds for offline demos (e.g. the original 23-562
     and FDA-2023-N-1200 entries in 002_seed_docket_catalog.sql).

When a reviewer one-clicks "Request analysis" on category 3, the pipeline
runs against an API that has never heard of the docket, returns zero rows,
and the older deployed notebook quietly reports SUCCESS. The UI then has
no honest way to say "this seed isn't real" without this validator's data.

Run modes
---------
  python scripts/validate_discoveries.py            # validate all dockets
  python scripts/validate_discoveries.py --docket-id 17-108
  python scripts/validate_discoveries.py --source ecfs

Requires `DATA_GOV_API_KEY` (canonical) or `REGULATIONS_GOV_API_KEY`
(deprecated alias) to be set. Without a key the validator can still run
against ECFS public endpoints but regulations.gov calls will be skipped
with a warning.

Database connection: reads `DATABASE_URL` (Postgres / Supabase) from env.
If unset, prints the validation results to stdout instead of writing to
the catalog so you can dry-run safely.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.api_keys import resolve_data_gov_api_key  # noqa: E402

log = logging.getLogger("validate_discoveries")

REGULATIONS_GOV_BASE = "https://api.regulations.gov/v4"
ECFS_BASE = "https://publicapi.fcc.gov/ecfs"

ValidationStatus = str  # "validated_real" | "validated_empty" | "not_found" | "error"


@dataclass
class ValidationResult:
    docket_id: str
    source: str
    status: ValidationStatus
    comment_count: int | None
    detail: str


def validate_regulations_gov(client: httpx.Client, docket_id: str) -> ValidationResult:
    """Hit regulations.gov v4 /comments endpoint with the docket filter and
    read the totalElements from the paginated meta. Returns 'not_found' when
    the API errors with 404, 'validated_real' / 'validated_empty' otherwise.
    """
    try:
        res = client.get(
            "/comments",
            params={
                "filter[docketId]": docket_id,
                "page[size]": 1,
            },
        )
    except Exception as exc:
        return ValidationResult(
            docket_id, "regulations_gov", "error", None, f"HTTP exception: {exc}"
        )

    if res.status_code == 404:
        return ValidationResult(
            docket_id, "regulations_gov", "not_found", 0, "regulations.gov returned 404"
        )
    if res.status_code != 200:
        return ValidationResult(
            docket_id,
            "regulations_gov",
            "error",
            None,
            f"status={res.status_code} body={res.text[:200]}",
        )

    try:
        body = res.json()
    except Exception as exc:
        return ValidationResult(
            docket_id, "regulations_gov", "error", None, f"JSON parse: {exc}"
        )

    total = (body.get("meta") or {}).get("totalElements")
    if total is None:
        return ValidationResult(
            docket_id,
            "regulations_gov",
            "error",
            None,
            f"missing meta.totalElements; keys={list(body.keys())}",
        )

    total_int = int(total)
    if total_int > 0:
        return ValidationResult(
            docket_id,
            "regulations_gov",
            "validated_real",
            total_int,
            f"{total_int} comments on record",
        )
    return ValidationResult(
        docket_id,
        "regulations_gov",
        "validated_empty",
        0,
        "docket exists but has no public comments",
    )


def validate_ecfs(
    client: httpx.Client, docket_id: str, api_key: str | None
) -> ValidationResult:
    """ECFS uses ?proceedings.name=<docket_id>. totalRows is on
    filings_metadata. The public API requires the api_key query param;
    a missing key shows up as a 401-style JSON error body, not a 401 HTTP
    status, so we have to inspect the body."""
    if not api_key:
        return ValidationResult(
            docket_id, "ecfs", "error", None, "no api_key available for ECFS"
        )
    try:
        res = client.get(
            "/filings",
            params={
                "api_key": api_key,
                "proceedings.name": docket_id,
                "limit": 1,
            },
        )
    except Exception as exc:
        return ValidationResult(
            docket_id, "ecfs", "error", None, f"HTTP exception: {exc}"
        )

    try:
        body = res.json()
    except Exception as exc:
        return ValidationResult(docket_id, "ecfs", "error", None, f"JSON parse: {exc}")

    if isinstance(body, dict) and body.get("error"):
        return ValidationResult(
            docket_id,
            "ecfs",
            "error",
            None,
            f"ecfs error: {body['error']}",
        )

    total = ((body or {}).get("filings_metadata") or {}).get("totalRows")
    if total is None:
        filings = body.get("filings", []) if isinstance(body, dict) else []
        total_int = len(filings)
    else:
        total_int = int(total)

    if total_int > 0:
        return ValidationResult(
            docket_id, "ecfs", "validated_real", total_int, f"{total_int} filings"
        )
    return ValidationResult(
        docket_id,
        "ecfs",
        "not_found",
        0,
        "no filings returned; treating as synthetic/missing proceeding",
    )


def validate_docket(
    docket: dict[str, Any],
    *,
    regs_client: httpx.Client,
    ecfs_client: httpx.Client,
    api_key: str | None,
) -> ValidationResult:
    source = (docket.get("source") or "").lower()
    docket_id = docket["docket_id"]
    if source == "regulations_gov":
        return validate_regulations_gov(regs_client, docket_id)
    if source == "ecfs":
        return validate_ecfs(ecfs_client, docket_id, api_key)
    return ValidationResult(
        docket_id, source, "error", None, f"unknown source: {source!r}"
    )


def load_dockets_from_db() -> list[dict[str, Any]] | None:
    """Returns rows from docket_catalog if DATABASE_URL is set, else None."""
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if not db_url:
        return None
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        log.warning(
            "psycopg2 not installed; "
            "skipping DB read. Install with `pip install psycopg2-binary`."
        )
        return None

    with (
        psycopg2.connect(db_url) as conn,
        conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur,
    ):
        cur.execute("SELECT docket_id, source FROM docket_catalog ORDER BY docket_id")
        return [dict(r) for r in cur.fetchall()]


def write_results_to_db(results: list[ValidationResult]) -> int:
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if not db_url:
        return 0
    try:
        import psycopg2
    except ImportError:
        return 0

    now = datetime.now(timezone.utc)
    with psycopg2.connect(db_url) as conn, conn.cursor() as cur:
        for r in results:
            cur.execute(
                """
                UPDATE docket_catalog
                SET validation_status = %s,
                    validated_comment_count = %s,
                    validation_source = %s,
                    validated_at = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE docket_id = %s
                """,
                (
                    r.status,
                    r.comment_count,
                    f"{r.source}_api",
                    now,
                    r.docket_id,
                ),
            )
        conn.commit()
    return len(results)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--docket-id",
        help="Validate only this docket_id (otherwise validate all)",
    )
    parser.add_argument(
        "--source",
        choices=["regulations_gov", "ecfs"],
        help="Restrict to this source",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't write results back to docket_catalog; print only.",
    )
    parser.add_argument(
        "--seed-list",
        action="store_true",
        help="Validate the hard-coded canonical seed list instead of reading from DB",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    api_key = resolve_data_gov_api_key(required=False)
    if not api_key:
        log.warning(
            "No DATA_GOV_API_KEY / REGULATIONS_GOV_API_KEY in env. "
            "regulations.gov calls will be rate-limited to anonymous quota; "
            "ECFS calls will be skipped entirely."
        )

    if args.seed_list:
        dockets = [
            {"docket_id": "CFPB-2016-0025", "source": "regulations_gov"},
            {"docket_id": "17-108", "source": "ecfs"},
            {"docket_id": "FTC-2023-0007", "source": "regulations_gov"},
            {"docket_id": "EPA-HQ-OAR-2021-0317", "source": "regulations_gov"},
        ]
    else:
        dockets = load_dockets_from_db()
        if dockets is None:
            log.error(
                "DATABASE_URL not set and --seed-list not passed. "
                "Set DATABASE_URL or use --seed-list to validate the canonical list."
            )
            return 2

    if args.docket_id:
        dockets = [d for d in dockets if d["docket_id"] == args.docket_id]
    if args.source:
        dockets = [d for d in dockets if d["source"] == args.source]

    if not dockets:
        log.warning("No dockets matched the filter; nothing to validate.")
        return 0

    headers = {"X-Api-Key": api_key} if api_key else {}
    results: list[ValidationResult] = []
    with (
        httpx.Client(
            base_url=REGULATIONS_GOV_BASE, headers=headers, timeout=20.0
        ) as regs_client,
        httpx.Client(base_url=ECFS_BASE, timeout=20.0) as ecfs_client,
    ):
        for d in dockets:
            r = validate_docket(
                d,
                regs_client=regs_client,
                ecfs_client=ecfs_client,
                api_key=api_key,
            )
            log.info(
                "  %s (%s) -> %s | count=%s | %s",
                r.docket_id,
                r.source,
                r.status,
                r.comment_count,
                r.detail,
            )
            results.append(r)

    summary = {}
    for r in results:
        summary.setdefault(r.status, 0)
        summary[r.status] += 1
    log.info("Validation summary: %s", json.dumps(summary, sort_keys=True))

    if args.dry_run:
        log.info("Dry-run mode: not writing back to docket_catalog.")
        return 0

    written = write_results_to_db(results)
    if written:
        log.info("Wrote %d validation rows to docket_catalog.", written)
    else:
        log.warning(
            "No rows written to docket_catalog. "
            "Set DATABASE_URL and ensure psycopg2 is installed."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
