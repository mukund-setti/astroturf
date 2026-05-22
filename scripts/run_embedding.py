#!/usr/bin/env python3
"""run_embedding.py — CLI wrapper around EmbeddingAgent."""

import argparse
import logging
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.embedding.agent import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_EMBEDDINGS_PATH,
    DEFAULT_MODEL,
    DEFAULT_PARSED_PATH,
    EmbeddingAgent,
    EmbeddingInput,
    LocalSentenceTransformerBackend,
    MockBackend,
)


def load_simple_env() -> None:
    """Load environment variables from a local .env file using simple rules."""
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip().strip('"').strip("'")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute embeddings for substantive parsed comments."
    )
    parser.add_argument("--docket", required=True, help="Regulations.gov docket ID")
    parser.add_argument("--parsed-path", default=DEFAULT_PARSED_PATH)
    parser.add_argument("--embeddings-path", default=DEFAULT_EMBEDDINGS_PATH)
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Embedding model name (e.g. BAAI/bge-large-en-v1.5)",
    )
    parser.add_argument(
        "--backend",
        choices=["local", "mock"],
        default="local",
        help="Embedding backend (local sentence-transformers or deterministic mock)",
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument(
        "--force-reembed",
        action="store_true",
        help="Re-embed every candidate even if the text_hash matches.",
    )
    parser.add_argument("--log-level", default="INFO")

    args = parser.parse_args()

    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    load_simple_env()

    if args.backend == "local":
        backend = LocalSentenceTransformerBackend(model_name=args.model)
    else:
        backend = MockBackend(model_name=args.model)

    print(f"Starting EmbeddingAgent for docket: {args.docket}")
    print(f"Parsed path:     {args.parsed_path}")
    print(f"Embeddings path: {args.embeddings_path}")
    print(f"Model:           {args.model}")
    print(f"Backend:         {args.backend}")

    agent = EmbeddingAgent(backend=backend)
    inputs = EmbeddingInput(
        docket_id=args.docket,
        parsed_path=args.parsed_path,
        embeddings_path=args.embeddings_path,
        model_name=args.model,
        batch_size=args.batch_size,
        max_rows=args.max_rows,
        force_reembed=args.force_reembed,
    )

    try:
        output = agent.run(inputs)
    except Exception as e:
        print(f"\nERROR: Embedding failed: {e}", file=sys.stderr)
        sys.exit(1)

    print("\n" + "=" * 50)
    print("EMBEDDING SUMMARY")
    print("=" * 50)
    print(f"Docket ID:           {output.docket_id}")
    print(f"Candidates Total:    {output.metadata.get('candidates_total', 0)}")
    print(f"Cache Hits:          {output.metadata.get('skipped_cache_hit', 0)}")
    print(f"Corrupt Skipped:     {output.metadata.get('skipped_corrupt', 0)}")
    print(f"Embedded:            {output.metadata.get('embedded_count', 0)}")
    print(f"  New:               {output.metadata.get('new_count', 0)}")
    print(f"  Stale Re-embedded: {output.metadata.get('stale_reembedded_count', 0)}")
    print(f"Rows Written:        {output.rows_written}")
    print(f"Duration:            {output.metadata.get('duration_seconds', 0.0):.2f}s")
    print(f"Embedding Dim:       {output.metadata.get('embedding_dim', 0)}")
    print(f"Embedding Model:     {output.metadata.get('embedding_model', '')}")
    print(f"Backend:             {output.metadata.get('backend', '')}")
    print("=" * 50)


if __name__ == "__main__":
    main()
