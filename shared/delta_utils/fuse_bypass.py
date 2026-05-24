"""Databricks FUSE Volume bypass utilities for delta-rs writes."""

from __future__ import annotations

import logging
import os
import shutil
from contextlib import contextmanager
from pathlib import Path
from deltalake import DeltaTable

log = logging.getLogger(__name__)


@contextmanager
def local_tmp_delta_path(path: str | Path):
    """Context manager to bypass FUSE rename limitations in Databricks Serverless.

    If the target path is a FUSE volume (starts with '/Volumes' or '/dbfs'), this
    copies the existing Delta table to local '/tmp', yields the local temp path
    for delta-rs mutations (merge, write, delete), and syncs/overwrites the
    result back to FUSE on success.

    For all other paths, it yields the original path directly.
    """
    path_str = str(path)
    is_fuse = path_str.startswith("/Volumes") or path_str.startswith("/dbfs")

    if not is_fuse:
        yield path
        return

    import uuid

    # Create a unique directory under /tmp to avoid concurrent task conflicts
    tmp_dir = Path("/tmp") / f"delta_fuse_bypass_{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    leaf_name = Path(path_str).name
    tmp_path = tmp_dir / leaf_name

    # 1. If the source Delta table exists on FUSE, copy its entire contents to local temp
    if DeltaTable.is_deltatable(path_str):
        log.info(
            "Copying Delta table from FUSE '%s' to local temp '%s'", path_str, tmp_path
        )
        shutil.copytree(path_str, tmp_path, symlinks=False, ignore=None)

    try:
        # 2. Yield the local tmp path for mutations
        yield tmp_path

        # 3. Sync changes back to FUSE if a table was written
        if os.path.exists(tmp_path) and DeltaTable.is_deltatable(str(tmp_path)):
            log.info(
                "Syncing Delta table back from local temp '%s' to FUSE '%s'",
                tmp_path,
                path_str,
            )
            if os.path.exists(path_str):
                shutil.rmtree(path_str)
            os.makedirs(os.path.dirname(path_str), exist_ok=True)
            shutil.copytree(tmp_path, path_str, symlinks=False, ignore=None)
            log.info("Successfully synced Delta table back to FUSE '%s'", path_str)
        else:
            log.info(
                "No Delta table written at '%s', skipping FUSE sync-back", tmp_path
            )

    finally:
        # Clean up local temp directory
        try:
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir)
        except Exception as e:
            log.warning("Failed to clean up local temp directory %s: %s", tmp_dir, e)
