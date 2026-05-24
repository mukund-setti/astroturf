"""AttributionAgent - cluster representative text -> gold.campaign_attributions.

MVP scope: ``offline_seed`` mode only. The agent reads a curated seed registry
of candidate entities + template phrases for one docket, matches each phrase
against the representative text of each cluster (exact + fuzzy), and emits
**evidence packets** to ``gold.campaign_attributions``.

See ADR-0015 for the full policy. Key invariants enforced here:

- ``confidence_score`` is hard-capped strictly below 1.0.
- ``confidence_label`` is forced to ``needs_review`` when the score is below
  0.50 or when the evidence type is ``llm_hypothesis``.
- ``reasoning_summary`` is generated mechanically from the matched fields;
  it never invents entities.
- No causality claims. The reasoning_summary uses the words "Candidate
  source", "Evidence match", "Likely campaign origin" only.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal

import mlflow
import pyarrow as pa
import pyarrow.compute as pc
from deltalake import DeltaTable

from shared.delta_utils.attribution import (
    delete_attribution_scope,
    merge_campaign_attributions,
)
from shared.delta_utils.silver import load_delta_as_pyarrow
from shared.schemas.campaign_attributions import (
    CampaignAttribution,
    campaign_attributions_arrow_schema,
)

log = logging.getLogger(__name__)

DEFAULT_CLUSTERS_PATH = "./data/gold/comment_clusters"
DEFAULT_MEMBERSHIPS_PATH = "./data/gold/comment_cluster_memberships"
DEFAULT_PARSED_COMMENTS_PATH = "./data/silver/parsed_comments"
DEFAULT_ATTRIBUTIONS_PATH = "./data/gold/campaign_attributions"
DEFAULT_SEED_DIR = "./evals/fixtures/attribution"

CONFIDENCE_SCORE_MAX = 0.95
EXACT_MATCH_BASE_SCORE = 0.85
FUZZY_MATCH_BASE_SCORE = 0.65
REGISTRY_ONLY_BASE_SCORE = 0.35
MULTI_PHRASE_BONUS = 0.10
FUZZY_RATIO_THRESHOLD = 0.85
NEEDS_REVIEW_BELOW = 0.50

EVIDENCE_EXCERPT_RADIUS = 120

Mode = Literal["offline_seed", "web_research", "llm_assisted"]


@dataclass
class AttributionInput:
    docket_id: str
    cluster_ids: list[str] | None = None
    max_clusters: int | None = None
    mode: Mode = "offline_seed"
    confidence_threshold: float = 0.0
    seed_path: str | None = None
    clusters_path: str = DEFAULT_CLUSTERS_PATH
    memberships_path: str = DEFAULT_MEMBERSHIPS_PATH
    parsed_comments_path: str = DEFAULT_PARSED_COMMENTS_PATH
    attributions_path: str = DEFAULT_ATTRIBUTIONS_PATH
    replace_scope: bool = True


@dataclass
class AttributionOutput:
    docket_id: str
    rows_written: int
    metadata: dict[str, Any] = field(default_factory=dict)


class AttributionAgent:
    """Detect candidate campaign-origin entities for clusters in a docket.

    MVP runs in ``offline_seed`` mode only. Other modes are accepted but
    refuse to execute until their tooling is configured — agents must not
    silently no-op (CLAUDE.md design rule #2).
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    def run(self, inputs: AttributionInput) -> AttributionOutput:
        start_time = time.monotonic()
        self._validate_inputs(inputs)

        if inputs.mode != "offline_seed":
            raise NotImplementedError(
                f"AttributionAgent mode '{inputs.mode}' is reserved for a "
                "future ADR. The MVP only supports 'offline_seed' (ADR-0015). "
                "Configure the appropriate tooling and a follow-up ADR before "
                "enabling other modes."
            )

        log.info(
            "Starting AttributionAgent docket=%s mode=%s",
            inputs.docket_id,
            inputs.mode,
        )

        seed = _load_seed_registry(inputs)
        clusters = self._load_clusters(inputs)
        cluster_text_by_id = self._load_representative_text(inputs, clusters)

        attributions: list[CampaignAttribution] = []
        for cluster_row in clusters:
            cluster_id = str(cluster_row["cluster_id"])
            text = cluster_text_by_id.get(cluster_id) or ""
            attributions.extend(
                _attributions_for_cluster(
                    cluster_id=cluster_id,
                    docket_id=inputs.docket_id,
                    text=text,
                    seed=seed,
                    confidence_threshold=inputs.confidence_threshold,
                )
            )

        rows_written = 0
        deleted = 0
        if attributions:
            arrow = _attributions_to_arrow(attributions)
            if inputs.replace_scope:
                deleted = delete_attribution_scope(
                    inputs.attributions_path,
                    campaign_attributions_arrow_schema(),
                    docket_id=inputs.docket_id,
                    cluster_ids=[a.cluster_id for a in attributions]
                    if inputs.cluster_ids
                    else None,
                )
            metrics = merge_campaign_attributions(inputs.attributions_path, arrow)
            rows_written = metrics["inserted"] + metrics["updated"]

        duration = time.monotonic() - start_time
        metadata = {
            "clusters_considered": len(clusters),
            "attributions_emitted": len(attributions),
            "rows_written": rows_written,
            "deleted_prior_rows": deleted,
            "duration_seconds": duration,
            "mode": inputs.mode,
            "needs_review_count": sum(
                1 for a in attributions if a.confidence_label == "needs_review"
            ),
            "high_confidence_count": sum(
                1 for a in attributions if a.confidence_label == "high"
            ),
        }
        _log_mlflow(inputs, metadata)

        log.info(
            "AttributionAgent complete. Clusters=%d Attributions=%d Written=%d Duration=%.2fs",
            len(clusters),
            len(attributions),
            rows_written,
            duration,
        )

        return AttributionOutput(
            docket_id=inputs.docket_id,
            rows_written=rows_written,
            metadata=metadata,
        )

    def _validate_inputs(self, inputs: AttributionInput) -> None:
        if not inputs.docket_id:
            raise ValueError("docket_id is required")
        if inputs.max_clusters is not None and inputs.max_clusters < 1:
            raise ValueError("max_clusters must be positive when provided")
        if not 0.0 <= inputs.confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be in [0.0, 1.0]")

    def _load_clusters(self, inputs: AttributionInput) -> list[dict[str, Any]]:
        if not DeltaTable.is_deltatable(inputs.clusters_path):
            raise FileNotFoundError(
                f"gold.comment_clusters not found at {inputs.clusters_path}. "
                "Run the clustering agent first."
            )
        table = load_delta_as_pyarrow(inputs.clusters_path)
        filtered = table.filter(pc.field("docket_id") == inputs.docket_id)
        rows = filtered.select(
            ["cluster_id", "representative_comment_id", "cluster_size"]
        ).to_pylist()
        if inputs.cluster_ids:
            wanted = set(inputs.cluster_ids)
            rows = [row for row in rows if str(row["cluster_id"]) in wanted]
        rows.sort(key=lambda r: (-int(r["cluster_size"]), str(r["cluster_id"])))
        if inputs.max_clusters is not None:
            rows = rows[: inputs.max_clusters]
        return rows

    def _load_representative_text(
        self,
        inputs: AttributionInput,
        clusters: list[dict[str, Any]],
    ) -> dict[str, str]:
        if not clusters:
            return {}
        rep_ids = sorted({str(row["representative_comment_id"]) for row in clusters})
        if not DeltaTable.is_deltatable(inputs.parsed_comments_path):
            log.warning(
                "silver.parsed_comments not found at %s; attribution will "
                "operate on empty text and emit registry-only matches.",
                inputs.parsed_comments_path,
            )
            return {row["cluster_id"]: "" for row in clusters}

        parsed = load_delta_as_pyarrow(inputs.parsed_comments_path)
        parsed = parsed.filter(pc.field("docket_id") == inputs.docket_id)
        parsed_pylist = parsed.select(
            ["comment_id", "raw_text", "normalized_text"]
        ).to_pylist()
        text_by_comment: dict[str, str] = {}
        for entry in parsed_pylist:
            cid = str(entry["comment_id"])
            if cid not in rep_ids:
                continue
            text_by_comment[cid] = (
                entry.get("raw_text") or entry.get("normalized_text") or ""
            )
        result: dict[str, str] = {}
        for row in clusters:
            rep_id = str(row["representative_comment_id"])
            result[str(row["cluster_id"])] = text_by_comment.get(rep_id, "")
        return result


def _load_seed_registry(inputs: AttributionInput) -> dict[str, Any]:
    if inputs.seed_path is not None:
        path = Path(inputs.seed_path)
    else:
        slug = inputs.docket_id.lower().replace("-", "_")
        path = Path(DEFAULT_SEED_DIR) / f"fcc_{slug}_known_sources.json"
        if not path.exists():
            # try a generic name
            path = Path(DEFAULT_SEED_DIR) / f"{slug}_known_sources.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Attribution seed registry not found for docket={inputs.docket_id}. "
            f"Looked for {path}. Create one under {DEFAULT_SEED_DIR}/ or pass "
            "seed_path explicitly."
        )
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if "sources" not in data:
        raise ValueError(
            f"Seed registry at {path} is missing required 'sources' field."
        )
    return data


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _confidence_label_for(score: float) -> str:
    if score < NEEDS_REVIEW_BELOW:
        return "needs_review"
    if score >= 0.80:
        return "high"
    if score >= 0.60:
        return "medium"
    return "low"


def _excerpt_around(text: str, needle: str) -> str | None:
    if not text or not needle:
        return None
    idx = _normalize_text(text).find(_normalize_text(needle))
    if idx < 0:
        return None
    start = max(0, idx - EVIDENCE_EXCERPT_RADIUS)
    end = min(len(text), idx + len(needle) + EVIDENCE_EXCERPT_RADIUS)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


def _attribution_id(
    cluster_id: str, entity_name: str, matched_phrase: str | None, evidence_type: str
) -> str:
    h = hashlib.sha256()
    for part in (cluster_id, entity_name, matched_phrase or "", evidence_type):
        h.update(part.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def _attributions_for_cluster(
    *,
    cluster_id: str,
    docket_id: str,
    text: str,
    seed: dict[str, Any],
    confidence_threshold: float,
) -> list[CampaignAttribution]:
    now = datetime.now(timezone.utc)
    out: list[CampaignAttribution] = []
    normalized_text = _normalize_text(text)

    for source in seed.get("sources", []):
        entity_name = str(source.get("entity_name", "")).strip()
        if not entity_name:
            continue
        entity_type = str(source.get("entity_type", "unknown") or "unknown").strip()
        if entity_type not in {
            "trade_association",
            "advocacy_group",
            "company",
            "unknown",
            "other",
        }:
            entity_type = "other"
        url = source.get("url") or None
        phrases = [str(p) for p in (source.get("template_phrases") or [])]

        exact_hits: list[str] = []
        fuzzy_hits: list[tuple[str, float]] = []

        for phrase in phrases:
            if not phrase.strip():
                continue
            normalized_phrase = _normalize_text(phrase)
            if not normalized_phrase:
                continue
            if normalized_phrase in normalized_text:
                exact_hits.append(phrase)
                continue
            ratio = SequenceMatcher(None, normalized_phrase, normalized_text).ratio()
            if ratio >= FUZZY_RATIO_THRESHOLD:
                fuzzy_hits.append((phrase, ratio))

        if exact_hits:
            base = EXACT_MATCH_BASE_SCORE
            if len(exact_hits) > 1:
                base = min(CONFIDENCE_SCORE_MAX, base + MULTI_PHRASE_BONUS)
            base = min(base, CONFIDENCE_SCORE_MAX)
            primary_phrase = exact_hits[0]
            excerpt = _excerpt_around(text, primary_phrase)
            evidence_type: str = "exact_phrase_match"
            reasoning = (
                f"Candidate source: {entity_name}. Evidence match: cluster "
                f"representative text contains the exact template phrase "
                f"'{_truncate(primary_phrase, 120)}'."
                + (
                    f" {len(exact_hits) - 1} additional exact phrase(s) also matched."
                    if len(exact_hits) > 1
                    else ""
                )
                + " Likely campaign origin only — manual review required."
            )
            score = base
            label = _confidence_label_for(score)
            if score < confidence_threshold:
                continue
            out.append(
                CampaignAttribution(
                    attribution_id=_attribution_id(
                        cluster_id, entity_name, primary_phrase, evidence_type
                    ),
                    cluster_id=cluster_id,
                    docket_id=docket_id,
                    candidate_entity_name=entity_name,
                    candidate_entity_type=entity_type,  # type: ignore[arg-type]
                    candidate_url=url,
                    evidence_type=evidence_type,  # type: ignore[arg-type]
                    matched_phrase=primary_phrase,
                    evidence_excerpt=excerpt,
                    confidence_score=score,
                    confidence_label=label,  # type: ignore[arg-type]
                    reasoning_summary=reasoning,
                    reviewed_status="unreviewed",
                    created_at=now,
                    metadata_json=json.dumps(
                        {
                            "exact_phrase_count": len(exact_hits),
                            "fuzzy_phrase_count": len(fuzzy_hits),
                        },
                        sort_keys=True,
                    ),
                )
            )
        elif fuzzy_hits:
            primary_phrase, ratio = max(fuzzy_hits, key=lambda item: item[1])
            base = min(FUZZY_MATCH_BASE_SCORE, CONFIDENCE_SCORE_MAX)
            evidence_type = "fuzzy_phrase_match"
            excerpt = _excerpt_around(text, primary_phrase)
            reasoning = (
                f"Candidate source: {entity_name}. Evidence match: cluster "
                f"text fuzzy-matches a known template phrase "
                f"(ratio={ratio:.2f}). Likely campaign origin only — manual "
                "review required."
            )
            score = base
            label = _confidence_label_for(score)
            if score < confidence_threshold:
                continue
            out.append(
                CampaignAttribution(
                    attribution_id=_attribution_id(
                        cluster_id, entity_name, primary_phrase, evidence_type
                    ),
                    cluster_id=cluster_id,
                    docket_id=docket_id,
                    candidate_entity_name=entity_name,
                    candidate_entity_type=entity_type,  # type: ignore[arg-type]
                    candidate_url=url,
                    evidence_type=evidence_type,  # type: ignore[arg-type]
                    matched_phrase=primary_phrase,
                    evidence_excerpt=excerpt,
                    confidence_score=score,
                    confidence_label=label,  # type: ignore[arg-type]
                    reasoning_summary=reasoning,
                    reviewed_status="unreviewed",
                    created_at=now,
                    metadata_json=json.dumps(
                        {"fuzzy_ratio": round(ratio, 4)},
                        sort_keys=True,
                    ),
                )
            )
        elif phrases:
            base = REGISTRY_ONLY_BASE_SCORE
            evidence_type = "known_campaign_registry"
            reasoning = (
                f"Candidate source: {entity_name}. Registry entry exists for "
                "this docket but no template phrase matched the cluster "
                "representative text. Low-confidence candidate — needs manual "
                "review."
            )
            score = base
            label = _confidence_label_for(score)
            if score < confidence_threshold:
                continue
            out.append(
                CampaignAttribution(
                    attribution_id=_attribution_id(
                        cluster_id, entity_name, None, evidence_type
                    ),
                    cluster_id=cluster_id,
                    docket_id=docket_id,
                    candidate_entity_name=entity_name,
                    candidate_entity_type=entity_type,  # type: ignore[arg-type]
                    candidate_url=url,
                    evidence_type=evidence_type,  # type: ignore[arg-type]
                    matched_phrase=None,
                    evidence_excerpt=None,
                    confidence_score=score,
                    confidence_label=label,  # type: ignore[arg-type]
                    reasoning_summary=reasoning,
                    reviewed_status="unreviewed",
                    created_at=now,
                    metadata_json=json.dumps(
                        {"phrases_in_registry": len(phrases)},
                        sort_keys=True,
                    ),
                )
            )

    return out


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _attributions_to_arrow(rows: list[CampaignAttribution]) -> pa.Table:
    schema = campaign_attributions_arrow_schema()
    columns: dict[str, list[Any]] = {name: [] for name in schema.names}
    for row in rows:
        data = row.model_dump()
        for name in columns:
            columns[name].append(data[name])
    return pa.Table.from_pydict(columns, schema=schema)


def _log_mlflow(inputs: AttributionInput, metadata: dict[str, Any]) -> None:
    try:
        with mlflow.start_run(run_name=f"attribution-{inputs.docket_id}"):
            mlflow.log_param("docket_id", inputs.docket_id)
            mlflow.log_param("mode", inputs.mode)
            mlflow.log_param("max_clusters", inputs.max_clusters)
            mlflow.log_param("confidence_threshold", inputs.confidence_threshold)
            for key in (
                "clusters_considered",
                "attributions_emitted",
                "rows_written",
                "deleted_prior_rows",
                "duration_seconds",
                "needs_review_count",
                "high_confidence_count",
            ):
                mlflow.log_metric(key, metadata.get(key, 0))
    except Exception as exc:  # pragma: no cover - mlflow is best-effort
        log.warning("MLflow logging failed for AttributionAgent: %s", exc)
