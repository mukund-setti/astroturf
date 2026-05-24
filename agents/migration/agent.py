"""MigrationAgent - cluster text x final rule text -> gold.rule_migrations.

MVP scope: ``local_text`` mode only. Loads a local final-rule text fixture,
chunks it into sections, and emits per-phrase **language overlap** rows
against the cluster representative text. See ADR-0015.

Invariants enforced here:

- Every emitted row carries a non-empty ``caveat_text``.
- ``claim_scope`` never exceeds ``possible_influence``, and only ``exact``
  matches with 12+ word phrases are eligible for ``possible_influence``.
- ``confidence_score`` is strictly below 1.0.
- Federal Register / web modes are accepted but refuse to execute until
  configured, in line with CLAUDE.md design rule #2.
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

from shared.delta_utils.migration import (
    delete_migration_scope,
    merge_rule_migrations,
)
from shared.delta_utils.silver import load_delta_as_pyarrow
from shared.schemas.rule_migrations import (
    RuleMigration,
    rule_migrations_arrow_schema,
)

log = logging.getLogger(__name__)

DEFAULT_CLUSTERS_PATH = "./data/gold/comment_clusters"
DEFAULT_MEMBERSHIPS_PATH = "./data/gold/comment_cluster_memberships"
DEFAULT_PARSED_COMMENTS_PATH = "./data/silver/parsed_comments"
DEFAULT_MIGRATIONS_PATH = "./data/gold/rule_migrations"

CONFIDENCE_SCORE_MAX = 0.95
EXACT_BASE_SCORE = 0.80
NEAR_EXACT_BASE_SCORE = 0.65
SEMANTIC_BASE_SCORE = 0.45

EXACT_RATIO_THRESHOLD = 1.0
NEAR_EXACT_RATIO_THRESHOLD = 0.90
SEMANTIC_RATIO_THRESHOLD = 0.75

POSSIBLE_INFLUENCE_MIN_WORDS = 12
NEEDS_REVIEW_BELOW = 0.50

DEFAULT_PHRASE_MIN_WORDS = 6
DEFAULT_PHRASE_MAX_WORDS = 30
DEFAULT_SIMILARITY_THRESHOLD = SEMANTIC_RATIO_THRESHOLD

CAVEAT_DEFAULT = (
    "Language overlap only — this is a phrase-level match between the "
    "campaign cluster text and the final rule text. It does NOT establish "
    "causality, lobbying influence, or that rule authors adopted the "
    "language from the cluster. Manual review required."
)

Mode = Literal["local_text", "federal_register_api"]


@dataclass
class MigrationInput:
    docket_id: str
    final_rule_text_path: str | None = None
    final_rule_text: str | None = None
    final_rule_document_id: str = ""
    final_rule_url: str | None = None
    cluster_ids: list[str] | None = None
    max_clusters: int | None = None
    mode: Mode = "local_text"
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD
    phrase_min_words: int = DEFAULT_PHRASE_MIN_WORDS
    phrase_max_words: int = DEFAULT_PHRASE_MAX_WORDS
    clusters_path: str = DEFAULT_CLUSTERS_PATH
    memberships_path: str = DEFAULT_MEMBERSHIPS_PATH
    parsed_comments_path: str = DEFAULT_PARSED_COMMENTS_PATH
    migrations_path: str = DEFAULT_MIGRATIONS_PATH
    replace_scope: bool = True
    max_rows_per_cluster: int = 5


@dataclass
class MigrationOutput:
    docket_id: str
    rows_written: int
    metadata: dict[str, Any] = field(default_factory=dict)


class MigrationAgent:
    """Detect language overlap between clusters and final rule text.

    MVP runs in ``local_text`` mode only. ``federal_register_api`` is
    accepted but refuses to execute until tooling is configured.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    def run(self, inputs: MigrationInput) -> MigrationOutput:
        start_time = time.monotonic()
        self._validate_inputs(inputs)

        if inputs.mode != "local_text":
            raise NotImplementedError(
                f"MigrationAgent mode '{inputs.mode}' is reserved for a "
                "future ADR. The MVP only supports 'local_text' (ADR-0015). "
                "Configure a Federal Register fetcher and a follow-up ADR "
                "before enabling other modes."
            )

        log.info(
            "Starting MigrationAgent docket=%s mode=%s",
            inputs.docket_id,
            inputs.mode,
        )

        final_text = self._load_final_rule_text(inputs)
        sections = _split_sections(final_text)
        document_id = inputs.final_rule_document_id or _document_id_for(
            inputs, final_text
        )

        clusters = self._load_clusters(inputs)
        cluster_text_by_id = self._load_representative_text(inputs, clusters)

        migrations: list[RuleMigration] = []
        for cluster_row in clusters:
            cluster_id = str(cluster_row["cluster_id"])
            text = cluster_text_by_id.get(cluster_id) or ""
            migrations.extend(
                _migrations_for_cluster(
                    cluster_id=cluster_id,
                    docket_id=inputs.docket_id,
                    cluster_text=text,
                    sections=sections,
                    final_rule_document_id=document_id,
                    final_rule_url=inputs.final_rule_url,
                    similarity_threshold=inputs.similarity_threshold,
                    phrase_min_words=inputs.phrase_min_words,
                    phrase_max_words=inputs.phrase_max_words,
                    max_rows_per_cluster=inputs.max_rows_per_cluster,
                )
            )

        rows_written = 0
        deleted = 0
        if migrations:
            arrow = _migrations_to_arrow(migrations)
            if inputs.replace_scope:
                deleted = delete_migration_scope(
                    inputs.migrations_path,
                    rule_migrations_arrow_schema(),
                    docket_id=inputs.docket_id,
                    cluster_ids=[m.cluster_id for m in migrations]
                    if inputs.cluster_ids
                    else None,
                )
            metrics = merge_rule_migrations(inputs.migrations_path, arrow)
            rows_written = metrics["inserted"] + metrics["updated"]

        duration = time.monotonic() - start_time
        metadata = {
            "clusters_considered": len(clusters),
            "migrations_emitted": len(migrations),
            "rows_written": rows_written,
            "deleted_prior_rows": deleted,
            "duration_seconds": duration,
            "mode": inputs.mode,
            "match_type_counts": _count_by_attr(migrations, "match_type"),
            "claim_scope_counts": _count_by_attr(migrations, "claim_scope"),
            "needs_review_count": sum(
                1 for m in migrations if m.confidence_label == "needs_review"
            ),
        }
        _log_mlflow(inputs, metadata)

        log.info(
            "MigrationAgent complete. Clusters=%d Migrations=%d Written=%d Duration=%.2fs",
            len(clusters),
            len(migrations),
            rows_written,
            duration,
        )

        return MigrationOutput(
            docket_id=inputs.docket_id,
            rows_written=rows_written,
            metadata=metadata,
        )

    def _validate_inputs(self, inputs: MigrationInput) -> None:
        if not inputs.docket_id:
            raise ValueError("docket_id is required")
        if inputs.max_clusters is not None and inputs.max_clusters < 1:
            raise ValueError("max_clusters must be positive when provided")
        if not 0.0 < inputs.similarity_threshold <= 1.0:
            raise ValueError("similarity_threshold must be in (0.0, 1.0]")
        if inputs.phrase_min_words < 3:
            raise ValueError("phrase_min_words must be at least 3")
        if inputs.phrase_max_words < inputs.phrase_min_words:
            raise ValueError("phrase_max_words must be >= phrase_min_words")
        if inputs.mode == "local_text" and not (
            inputs.final_rule_text or inputs.final_rule_text_path
        ):
            raise ValueError(
                "MigrationAgent local_text mode requires either "
                "final_rule_text or final_rule_text_path."
            )

    def _load_final_rule_text(self, inputs: MigrationInput) -> str:
        if inputs.final_rule_text is not None:
            return inputs.final_rule_text
        path = Path(inputs.final_rule_text_path or "")
        if not path.exists():
            raise FileNotFoundError(
                f"Final rule text fixture not found at {path}. "
                "Pass --final-rule-text or use the bundled fixture under "
                "evals/fixtures/migration/."
            )
        return path.read_text(encoding="utf-8")

    def _load_clusters(self, inputs: MigrationInput) -> list[dict[str, Any]]:
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
        inputs: MigrationInput,
        clusters: list[dict[str, Any]],
    ) -> dict[str, str]:
        if not clusters:
            return {}
        rep_ids = sorted({str(row["representative_comment_id"]) for row in clusters})
        if not DeltaTable.is_deltatable(inputs.parsed_comments_path):
            log.warning(
                "silver.parsed_comments not found at %s; migration will "
                "operate on empty cluster text.",
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


_SECTION_HEADER_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Split rule text into ``(section_name, section_body)`` tuples.

    Sections are delimited by ``## Section ...`` headers (used by the local
    fixture). Lines starting with ``#`` (single ``#``) are treated as comments
    and removed. Text before the first header (if any) becomes the
    ``__preamble__`` section.
    """
    cleaned_lines = [
        line for line in text.splitlines() if not line.lstrip().startswith("# ")
    ]
    cleaned = "\n".join(line for line in cleaned_lines if line.strip() != "#")
    matches = list(_SECTION_HEADER_RE.finditer(cleaned))
    if not matches:
        return [("__preamble__", cleaned.strip())]
    sections: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        preamble = cleaned[: matches[0].start()].strip()
        if preamble:
            sections.append(("__preamble__", preamble))
    for i, match in enumerate(matches):
        name = match.group(1).strip()
        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(cleaned)
        body = cleaned[body_start:body_end].strip()
        if body:
            sections.append((name, body))
    return sections


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _confidence_label_for(score: float) -> str:
    if score < NEEDS_REVIEW_BELOW:
        return "needs_review"
    if score >= 0.75:
        return "high"
    if score >= 0.60:
        return "medium"
    return "low"


def _candidate_phrases(text: str, min_words: int, max_words: int) -> list[str]:
    """Generate candidate phrases from a piece of text.

    For the MVP we slide a sentence-window over the input: each sentence is
    one candidate, and if the sentence is longer than ``max_words`` we also
    emit a leading slice of ``max_words`` tokens. We dedupe by normalized
    form.
    """
    if not text:
        return []
    # Sentence-ish split.
    sentences = re.split(r"(?<=[.!?])\s+", text)
    seen: set[str] = set()
    phrases: list[str] = []
    for sentence in sentences:
        cleaned = sentence.strip()
        if not cleaned:
            continue
        words = cleaned.split()
        if len(words) < min_words:
            continue
        candidates = [cleaned]
        if len(words) > max_words:
            candidates.append(" ".join(words[:max_words]))
        for cand in candidates:
            key = _normalize_text(cand)
            if not key or key in seen:
                continue
            seen.add(key)
            phrases.append(cand)
    return phrases


def _best_match(
    cluster_phrase: str, sections: list[tuple[str, str]]
) -> tuple[str | None, str | None, float]:
    """Return the best ``(section_name, rule_phrase, ratio)`` for a cluster phrase."""
    if not cluster_phrase:
        return (None, None, 0.0)
    normalized_phrase = _normalize_text(cluster_phrase)
    best_ratio = 0.0
    best_section: str | None = None
    best_rule_phrase: str | None = None
    for section_name, section_body in sections:
        normalized_body = _normalize_text(section_body)
        if not normalized_body:
            continue
        if normalized_phrase in normalized_body:
            return (section_name, cluster_phrase, 1.0)
        body_sentences = re.split(r"(?<=[.!?])\s+", section_body)
        for sentence in body_sentences:
            cleaned = sentence.strip()
            if not cleaned:
                continue
            ratio = SequenceMatcher(
                None, normalized_phrase, _normalize_text(cleaned)
            ).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_section = section_name
                best_rule_phrase = cleaned
    return (best_section, best_rule_phrase, best_ratio)


def _migration_id(
    cluster_id: str,
    final_rule_document_id: str,
    cluster_phrase: str,
    rule_phrase: str,
) -> str:
    h = hashlib.sha256()
    for part in (cluster_id, final_rule_document_id, cluster_phrase, rule_phrase):
        h.update(part.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def _document_id_for(inputs: MigrationInput, text: str) -> str:
    if inputs.final_rule_text_path:
        return Path(inputs.final_rule_text_path).stem
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"local_text_{digest[:12]}"


def _migrations_for_cluster(
    *,
    cluster_id: str,
    docket_id: str,
    cluster_text: str,
    sections: list[tuple[str, str]],
    final_rule_document_id: str,
    final_rule_url: str | None,
    similarity_threshold: float,
    phrase_min_words: int,
    phrase_max_words: int,
    max_rows_per_cluster: int,
) -> list[RuleMigration]:
    now = datetime.now(timezone.utc)
    out: list[RuleMigration] = []
    seen_keys: set[tuple[str, str]] = set()

    phrases = _candidate_phrases(
        cluster_text,
        min_words=phrase_min_words,
        max_words=phrase_max_words,
    )

    matches: list[tuple[str, str | None, str | None, float]] = []
    for phrase in phrases:
        section_name, rule_phrase, ratio = _best_match(phrase, sections)
        if ratio < similarity_threshold:
            continue
        if rule_phrase is None:
            continue
        matches.append((phrase, section_name, rule_phrase, ratio))

    matches.sort(key=lambda item: item[3], reverse=True)
    matches = matches[:max_rows_per_cluster]

    for cluster_phrase, section_name, rule_phrase, ratio in matches:
        if rule_phrase is None:
            continue
        key = (_normalize_text(cluster_phrase), _normalize_text(rule_phrase))
        if key in seen_keys:
            continue
        seen_keys.add(key)

        if ratio >= EXACT_RATIO_THRESHOLD:
            match_type = "exact"
            base = EXACT_BASE_SCORE
        elif ratio >= NEAR_EXACT_RATIO_THRESHOLD:
            match_type = "near_exact"
            base = NEAR_EXACT_BASE_SCORE
        else:
            match_type = "semantic"
            base = SEMANTIC_BASE_SCORE

        score = min(base, CONFIDENCE_SCORE_MAX)
        label = _confidence_label_for(score)

        word_count = len(cluster_phrase.split())
        if match_type == "exact" and word_count >= POSSIBLE_INFLUENCE_MIN_WORDS:
            claim_scope = "possible_influence"
            caveat_text = (
                "Possible influence signal — exact phrase overlap between "
                "cluster text and final rule text. This does NOT establish "
                "that the cluster influenced the rule. Manual review and "
                "additional independent evidence are required before drawing "
                "any causal conclusion."
            )
        else:
            claim_scope = "phrase_overlap"
            caveat_text = CAVEAT_DEFAULT

        out.append(
            RuleMigration(
                migration_id=_migration_id(
                    cluster_id,
                    final_rule_document_id,
                    cluster_phrase,
                    rule_phrase,
                ),
                cluster_id=cluster_id,
                docket_id=docket_id,
                final_rule_document_id=final_rule_document_id,
                final_rule_url=final_rule_url,
                final_rule_section=section_name,
                cluster_phrase=cluster_phrase,
                rule_phrase=rule_phrase,
                similarity_score=round(float(ratio), 6),
                match_type=match_type,  # type: ignore[arg-type]
                confidence_score=score,
                confidence_label=label,  # type: ignore[arg-type]
                claim_scope=claim_scope,  # type: ignore[arg-type]
                caveat_text=caveat_text,
                created_at=now,
                metadata_json=json.dumps(
                    {
                        "cluster_phrase_word_count": word_count,
                        "rule_phrase_word_count": len(rule_phrase.split()),
                        "similarity_threshold": similarity_threshold,
                    },
                    sort_keys=True,
                ),
            )
        )
    return out


def _migrations_to_arrow(rows: list[RuleMigration]) -> pa.Table:
    schema = rule_migrations_arrow_schema()
    columns: dict[str, list[Any]] = {name: [] for name in schema.names}
    for row in rows:
        data = row.model_dump()
        for name in columns:
            columns[name].append(data[name])
    return pa.Table.from_pydict(columns, schema=schema)


def _count_by_attr(rows: list[RuleMigration], attr: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = getattr(row, attr)
        counts[value] = counts.get(value, 0) + 1
    return counts


def _log_mlflow(inputs: MigrationInput, metadata: dict[str, Any]) -> None:
    try:
        with mlflow.start_run(run_name=f"migration-{inputs.docket_id}"):
            mlflow.log_param("docket_id", inputs.docket_id)
            mlflow.log_param("mode", inputs.mode)
            mlflow.log_param("max_clusters", inputs.max_clusters)
            mlflow.log_param("similarity_threshold", inputs.similarity_threshold)
            for key in (
                "clusters_considered",
                "migrations_emitted",
                "rows_written",
                "deleted_prior_rows",
                "duration_seconds",
                "needs_review_count",
            ):
                value = metadata.get(key, 0)
                if isinstance(value, (int, float)):
                    mlflow.log_metric(key, value)
    except Exception as exc:  # pragma: no cover - mlflow is best-effort
        log.warning("MLflow logging failed for MigrationAgent: %s", exc)
