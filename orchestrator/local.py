"""Local orchestrator for dev runs. Production uses Databricks Workflows."""
import argparse
import logging

# Import others as they're implemented.

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def run_pipeline(docket_id: str) -> None:
    log.info("Starting pipeline for docket=%s", docket_id)
    # IngestionAgent -> ParserAgent -> EmbeddingAgent -> ClusteringAgent
    # -> AttributionAgent -> MigrationAgent
    raise NotImplementedError


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--docket", required=True)
    args = parser.parse_args()
    run_pipeline(args.docket)
