"""Source-specific ingestion modules for IngestionAgent.

Each module exposes a per-source client and a ``run_*_ingestion`` function that
the IngestionAgent dispatches to based on the ``source`` field of
``IngestionInput``. See ADR-0012 for the multi-source bronze unification.
"""
