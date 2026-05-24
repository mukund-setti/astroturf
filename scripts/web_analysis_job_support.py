"""Shared helpers for the Databricks web analysis job and local smoke tests."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import date
from typing import Any, Mapping


EMBEDDING_MODEL = "databricks-bge-large-en"
DEFAULT_VECTOR_ENDPOINT_NAME = "astroturf-vs-endpoint"


@dataclass(frozen=True)
class WebAnalysisJobParams:
    docket_id: str
    source: str
    topic_id: str
    agency_id: str
    start_date: date | None
    end_date: date | None
    expected_scale: int
    request_id: str
    catalog: str
    data_root: str
    repo_path: str
    vector_index_name: str
    clustering_mode: str
    similarity_threshold: float
    dry_run: bool


@dataclass(frozen=True)
class WebAnalysisPaths:
    raw_comments_path: str
    parsed_path: str
    details_path: str
    attachments_path: str
    embeddings_path: str
    clusters_path: str
    memberships_path: str


@dataclass(frozen=True)
class WebAnalysisAgentInputs:
    ingestion: Any
    parser: Any
    embedding: Any
    clustering: Any


def sanitize_regulations_gov_api_key(value: str | None) -> str:
    """Trim safe outer whitespace and remove embedded NUL bytes from an API key."""
    api_key = (value or "").strip().replace("\x00", "")
    if not api_key:
        raise RuntimeError(
            "REGULATIONS_GOV_API_KEY resolved but is empty after sanitization."
        )
    return api_key


def parse_web_analysis_params(raw: Mapping[str, str]) -> WebAnalysisJobParams:
    docket_id = _required(raw, "docket_id")
    source = _required(raw, "source")
    topic_id = _required(raw, "topic_id")
    agency_id = _required(raw, "agency_id")
    request_id = _required(raw, "request_id")
    catalog = _required(raw, "catalog")
    data_root = _required(raw, "data_root").rstrip("/\\")
    repo_path = _required(raw, "repo_path").rstrip("/\\")

    if source not in {"regulations_gov", "ecfs"}:
        raise ValueError(
            f"Unsupported source={source!r}. Supported hosted web analysis sources "
            "are 'regulations_gov' and 'ecfs'."
        )

    if data_root.startswith("/Volumes/") and "/bronze/raw_imports" in data_root:
        raise ValueError(
            "Hosted analysis job cannot use sample-loader raw_imports path. "
            "Use web_analysis_job."
        )

    vector_index_name = _optional(raw, "vector_index_name")
    if not vector_index_name:
        vector_index_name = f"{catalog}.silver.comment_embeddings_bge_large_index"

    clustering_mode = _optional(raw, "clustering_mode") or "vector_search"
    if clustering_mode not in {"vector_search", "local"}:
        raise ValueError("clustering_mode must be either 'vector_search' or 'local'.")

    return WebAnalysisJobParams(
        docket_id=docket_id,
        source=source,
        topic_id=topic_id,
        agency_id=agency_id,
        start_date=_optional_date("start_date", _optional(raw, "start_date")),
        end_date=_optional_date("end_date", _optional(raw, "end_date")),
        expected_scale=_expected_scale(_optional(raw, "expected_scale") or "1000"),
        request_id=request_id,
        catalog=catalog,
        data_root=data_root,
        repo_path=repo_path,
        vector_index_name=vector_index_name,
        clustering_mode=clustering_mode,
        similarity_threshold=float(_optional(raw, "similarity_threshold") or "0.92"),
        dry_run=_parse_bool(_optional(raw, "dry_run")),
    )


def build_web_analysis_paths(params: WebAnalysisJobParams) -> WebAnalysisPaths:
    data_root = params.data_root
    return WebAnalysisPaths(
        raw_comments_path=f"{data_root}/bronze/raw_comments",
        parsed_path=f"{data_root}/silver/parsed_comments",
        details_path=f"{data_root}/silver/comment_details",
        attachments_path=f"{data_root}/silver/comment_attachments",
        embeddings_path=f"{data_root}/silver/comment_embeddings",
        clusters_path=f"{data_root}/gold/comment_clusters",
        memberships_path=f"{data_root}/gold/comment_cluster_memberships",
    )


def build_agent_inputs(
    params: WebAnalysisJobParams,
    paths: WebAnalysisPaths | None = None,
) -> WebAnalysisAgentInputs:
    """Construct agent input objects using the currently imported agent schemas."""
    from agents.clustering.agent import ClusteringInput
    from agents.embedding.agent import EmbeddingInput
    from agents.ingestion.agent import IngestionInput
    from agents.parser.agent import ParserInput

    paths = paths or build_web_analysis_paths(params)

    ingestion_values = {
        "docket_id": params.docket_id,
        "source": params.source,
        "max_comments": params.expected_scale,
        "start_date": params.start_date,
        "end_date": params.end_date,
    }
    parser_values = {
        "docket_id": params.docket_id,
        "bronze_path": paths.raw_comments_path,
        "silver_path": paths.parsed_path,
        "details_path": paths.details_path,
        "attachments_path": paths.attachments_path,
        "max_rows": params.expected_scale,
        "force_enrich": False,
    }
    embedding_values = {
        "docket_id": params.docket_id,
        "parsed_path": paths.parsed_path,
        "embeddings_path": paths.embeddings_path,
        "model_name": EMBEDDING_MODEL,
        "batch_size": 16,
        "max_rows": params.expected_scale,
        "force_reembed": False,
    }
    clustering_values = {
        "docket_id": params.docket_id,
        "embedding_model": EMBEDDING_MODEL,
        "embeddings_path": paths.embeddings_path,
        "clusters_path": paths.clusters_path,
        "memberships_path": paths.memberships_path,
        "clustering_version": (
            "v1_vector_search_cosine"
            if params.clustering_mode == "vector_search"
            else "v1_connected_components_cosine"
        ),
        "similarity_threshold": params.similarity_threshold,
        "max_rows": params.expected_scale,
        "allow_mock": False,
        "clustering_mode": params.clustering_mode,
        "vector_index_name": (
            params.vector_index_name
            if params.clustering_mode == "vector_search"
            else None
        ),
    }

    return WebAnalysisAgentInputs(
        ingestion=_construct_dataclass(IngestionInput, ingestion_values),
        parser=_construct_dataclass(ParserInput, parser_values),
        embedding=_construct_dataclass(EmbeddingInput, embedding_values),
        clustering=_construct_dataclass(ClusteringInput, clustering_values),
    )


def agent_inputs_as_safe_dict(inputs: WebAnalysisAgentInputs) -> dict[str, Any]:
    return {
        "ingestion": asdict(inputs.ingestion),
        "parser": asdict(inputs.parser),
        "embedding": asdict(inputs.embedding),
        "clustering": asdict(inputs.clustering),
    }


def _construct_dataclass(cls: type[Any], values: dict[str, Any]) -> Any:
    if not is_dataclass(cls):
        raise TypeError(f"{cls.__name__} must be a dataclass.")

    field_names = {field.name for field in fields(cls)}
    unknown = sorted(set(values) - field_names)
    if unknown:
        raise RuntimeError(
            f"{cls.__name__} does not define expected field(s): {unknown}. "
            "Sync the Databricks repo/job code with the local repository."
        )
    return cls(**values)


def _required(raw: Mapping[str, str], name: str) -> str:
    value = _optional(raw, name)
    if not value:
        raise ValueError(f"Missing required Databricks job parameter: {name}")
    return value


def _optional(raw: Mapping[str, str], name: str) -> str:
    return str(raw.get(name, "")).strip()


def _optional_date(name: str, value: str) -> date | None:
    if not value or value.lower() == "null":
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid Databricks job parameter {name}={value!r}; expected YYYY-MM-DD."
        ) from exc


def _expected_scale(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid Databricks job parameter expected_scale={value!r}; "
            "expected integer."
        ) from exc
    if parsed < 1:
        raise ValueError("expected_scale must be at least 1.")
    return parsed


def _parse_bool(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "y"}
