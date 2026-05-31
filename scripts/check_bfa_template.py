#!/usr/bin/env python3
"""Phase 1 known-answer benchmark: did the Broadband for America template land in a cluster?

See docs/operations/ecfs-setup.md for the validation methodology. This script reads
gold.comment_clusters for docket 17-108, locates the largest cluster, looks
up its representative comment in silver.parsed_comments, and checks for the
canonical BFA template phrase. If the phrase isn't present in the largest
few clusters' representatives, the script optionally runs the diagnostic
ECFS query to distinguish sampling variance from data absence.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pyarrow.compute as pc  # noqa: E402

from deltalake import DeltaTable  # noqa: E402

BFA_PHRASE = (
    "unprecedented regulatory power the obama administration imposed on the internet"
)
DOCKET = "17-108"
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-large-en-v1.5"


def load_simple_env():
    """Load environment variables from a local .env file using simple rules."""
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    os.environ[key] = val


def main() -> int:
    load_simple_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docket", default=DOCKET)
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--clusters-path", default="./data/gold/comment_clusters")
    parser.add_argument(
        "--memberships-path", default="./data/gold/comment_cluster_memberships"
    )
    parser.add_argument("--parsed-path", default="./data/silver/parsed_comments")
    parser.add_argument(
        "--top-n",
        type=int,
        default=10,
        help="Inspect the N largest clusters' representatives.",
    )
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="If template not found, run the ECFS q=text_data:... diagnostic query.",
    )
    args = parser.parse_args()

    clusters_t = DeltaTable(args.clusters_path).to_pyarrow_table()
    parsed_t = DeltaTable(args.parsed_path).to_pyarrow_table()

    docket_clusters = clusters_t.filter(
        (pc.field("docket_id") == args.docket)
        & (pc.field("embedding_model") == args.embedding_model)
    )
    print(f"=== Clusters for docket={args.docket} model={args.embedding_model} ===")
    print(f"Total clusters: {docket_clusters.num_rows}")

    if docket_clusters.num_rows == 0:
        print("ERROR: No clusters found.")
        return 1

    # Sort by cluster_size DESC
    rows = docket_clusters.to_pylist()
    rows.sort(key=lambda r: r["cluster_size"], reverse=True)

    parsed_by_id = {
        r["comment_id"]: r["raw_text"]
        for r in parsed_t.filter(pc.field("docket_id") == args.docket).to_pylist()
    }

    bfa_found = False
    bfa_cluster = None

    for i, cluster in enumerate(rows[: args.top_n]):
        rep_id = cluster["representative_comment_id"]
        rep_text = parsed_by_id.get(rep_id, "") or ""
        norm = " ".join(rep_text.lower().split())
        has_bfa = BFA_PHRASE in norm
        if has_bfa and not bfa_found:
            bfa_found = True
            bfa_cluster = cluster
        marker = "  *** BFA TEMPLATE FOUND ***" if has_bfa else ""
        print(
            f"#{i + 1}: cluster_id={cluster['cluster_id'][:12]}  "
            f"size={cluster['cluster_size']}  rep_id={rep_id}{marker}"
        )
        print(
            f"     mean_sim={cluster['mean_similarity']:.4f} "
            f"min_sim={cluster['min_similarity']:.4f}"
        )
        print(f"     rep_text[:300]: {rep_text[:300].replace(chr(10), ' ')}")
        print()

    if bfa_found:
        print("=" * 70)
        print("RESULT: BFA template detected in cluster representative.")
        print(f"  cluster_id: {bfa_cluster['cluster_id']}")
        print(f"  cluster_size: {bfa_cluster['cluster_size']}")
        print(
            f"  representative_comment_id: {bfa_cluster['representative_comment_id']}"
        )
        print("=" * 70)
        return 0

    print("=" * 70)
    print("BFA template NOT found in top-N cluster representatives.")
    print("=" * 70)

    if not args.diagnostic:
        print("Pass --diagnostic to run the ECFS targeted query and distinguish")
        print(
            "sampling variance from data absence (see docs/operations/ecfs-setup.md)."
        )
        return 2

    # Diagnostic: query ECFS directly for the phrase
    import httpx  # noqa: E402

    from shared.api_keys import resolve_data_gov_api_key  # noqa: E402

    api_key = resolve_data_gov_api_key(required=True)
    url = "https://publicapi.fcc.gov/ecfs/filings"
    params = {
        "api_key": api_key,
        "proceedings.name": args.docket,
        "q": 'text_data:"unprecedented regulatory power"',
        "limit": 5,
    }
    print(f"Diagnostic query: q={params['q']!r}")
    response = httpx.get(url, params=params, timeout=30.0)
    if response.status_code != 200:
        print(f"Diagnostic query failed: HTTP {response.status_code}")
        return 3
    body = response.json()
    filings = body.get("filing") or []
    print(f"Diagnostic returned {len(filings)} hits.")
    if filings:
        first = filings[0]
        print(f"Sample id_submission: {first.get('id_submission')}")
        text = first.get("text_data", "") or ""
        print(f"Sample text[:300]: {text[:300]}")
        print()
        print("=> Sampling variance: BFA campaign comments exist in 17-108 but the")
        print("   chosen window/slice missed them. Phase 2 should expand the window.")
    else:
        print("=> Data absence: BFA campaign comments are not in the public API for")
        print("   this docket. Pick a different known-answer benchmark.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
