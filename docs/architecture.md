# Architecture

## Agents
- IngestionAgent: regulations.gov to bronze Delta
- ParserAgent: bronze to silver (text normalization, PDF extraction)
- EmbeddingAgent: silver to vector index
- ClusteringAgent: vectors to gold clusters (MinHash + cosine)
- AttributionAgent: clusters to campaign origin (tool-using LLM agent)
- MigrationAgent: clusters x final rule text to verbatim migration findings

## Data flow
regulations.gov API
  -> bronze.raw_comments (Delta, partitioned by docket_id)
  -> silver.parsed_comments (Delta, with normalized text)
  -> silver.comment_embeddings (Delta + Vector Search index)
  -> gold.comment_clusters (Delta, with template + size + confidence)
  -> gold.campaign_attributions (Delta, with origin URL + confidence)
  -> gold.rule_migrations (Delta, with section-level citations)

## Orchestration
- Local dev: orchestrator/local.py runs agents sequentially with checkpointing
- Production: Databricks Workflow (infra/workflows/main.yml) with task dependencies
