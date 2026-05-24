"""Resolve the api.data.gov key used by the regulations.gov and ECFS clients.

Both sources are fronted by the same api.data.gov gateway and accept the same
key — see ADR-0012. The canonical env var is ``DATA_GOV_API_KEY``; the legacy
``REGULATIONS_GOV_API_KEY`` is honored as a deprecated fallback during the
transition.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

_DEPRECATION_LOGGED = False


def resolve_data_gov_api_key(*, required: bool = True) -> str | None:
    """Return the api.data.gov key from env, preferring ``DATA_GOV_API_KEY``.

    Logs a deprecation warning (once per process) when only the legacy name
    is set. Raises ``RuntimeError`` if no key is set and ``required`` is True;
    returns ``None`` when not required and unset (lets callers warn instead of
    raising — ParserAgent uses this when constructed against mock HTTP).
    """
    api_key = os.environ.get("DATA_GOV_API_KEY")
    if api_key:
        return api_key

    legacy = os.environ.get("REGULATIONS_GOV_API_KEY")
    if legacy:
        global _DEPRECATION_LOGGED
        if not _DEPRECATION_LOGGED:
            log.warning(
                "REGULATIONS_GOV_API_KEY is deprecated; rename to DATA_GOV_API_KEY "
                "in your .env. Falling back to REGULATIONS_GOV_API_KEY for now. "
                "See ADR-0012."
            )
            _DEPRECATION_LOGGED = True
        return legacy

    if required:
        raise RuntimeError(
            "DATA_GOV_API_KEY is not set (and REGULATIONS_GOV_API_KEY fallback "
            "is also unset). Required to fetch comments from regulations.gov or "
            "the FCC ECFS public API. See docs/ecfs-setup.md."
        )
    return None
