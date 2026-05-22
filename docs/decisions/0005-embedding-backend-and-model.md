# ADR-0005: Embedding Model Selection, Backend Abstraction, and Vector Search Index Mapping

- Status: Proposed
- Date: 2026-05-21

## Context

To run coordinated public comment campaign detection, the system must perform semantic analysis on submitted comments. This requires translating natural language into dense vector representations. 

We need to balance several constraints:
1. **Model Consistency**: Local development must produce vector embeddings that are byte-identical to our production deployment to avoid expensive and complex re-embedding cycles when moving from dev to production.
2. **Infrastructure Abstraction**: Production runs will leverage Databricks Foundation Model APIs for speed and scalability, while local development must run hermetically without requiring Databricks workspace network dependencies.
3. **Delta Table Schema Design**: We must decide how to represent vector embeddings in Delta. A fixed-size PyArrow list (`pa.list_(pa.float32(), 1024)`) is highly efficient but locks us into a single dimension. A variable-size list (`pa.list_(pa.float32())`) offers the flexibility to store embeddings from multiple models (with different dimensions) in the same table, using a compound primary key of `(comment_id, embedding_model)`.
4. **Databricks Vector Search Constraints**: Databricks Vector Search (VS) indexes require a fixed-dimension dense vector field at index creation time. If a Delta table contains variable-size or multi-dimension lists, VS cannot index the table directly without query-level filtering.

## Decision

We make the following technical decisions:

1. **Embedding Model Selection**: We adopt `BAAI/bge-large-en-v1.5` as our canonical embedding model. When run locally via the `sentence-transformers` library, this produces 1024-dimensional float vectors that are byte-identical to the production-grade `databricks-bge-large-en` Foundation Model API endpoint on Databricks.
2. **Backend Abstraction**: We abstract all embedding operations behind an `EmbeddingBackend` base class. We will implement two concrete backends, switched via runtime config:
   - `LocalSentenceTransformerBackend`: Loads and runs the model locally via PyTorch / Hugging Face.
   - `DatabricksFoundationModelBackend`: Databricks SDK routing to the production Foundation Model endpoint, mock-tested locally before live Databricks validation.
3. **Variable-Size Delta Representation**: We represent the `embedding_vector` in `silver.comment_embeddings` using the variable-size **`pa.list_(pa.float32())`** PyArrow type (Spark `ArrayType(FloatType)`).
4. **Vector Search Mapping Strategy**: To resolve the fixed-dimension index requirement in Databricks Vector Search, we will filter the source Delta table by `embedding_model` during the Vector Search Index sync step. This maps a single, model-specific slice of the Delta table to its own respective fixed-dimension VS index.

## Consequences

### Positive
- **Byte-Identity Dev/Prod Parity**: Embeddings generated locally on a developer's Windows/macOS machine exactly match production embeddings. This guarantees deterministic local unit tests, clustering logic, and model validation.
- **Delta Table Future-Proofing**: We do not lock the `silver.comment_embeddings` table to a single dimension. If we adopt a different model (e.g. OpenAI's 1536-dim `text-embedding-3-large` or a fast 384-dim local model), those vectors can coexist in the same table under a different `embedding_model` primary key component.
- **Clean Dev Setup**: The `LocalSentenceTransformerBackend` lazily downloads the model weights (~1.3GB) on first use, keeping the setup lightweight.

### Negative / Risks
- **Databricks Vector Search Mapping Complexity**: Because the Delta table column is defined as variable-size, Databricks Vector Search cannot index the raw table blindly. 
  - *Mitigation*: We trade Delta storage flexibility for downstream index configuration. The Vector Search pipeline must create one distinct Vector Search Index per model (e.g., `comment_embeddings_bge_large` indexing `SELECT * FROM silver.comment_embeddings WHERE embedding_model = 'BAAI/bge-large-en-v1.5'`). This is the correct separation of concerns, keeping storage generic and indexing specific.
- **Local Dependency Overhead**: `sentence-transformers` brings in heavy dependencies (`torch`, `transformers`). We mitigate memory bloat in unit tests by fully mocking the backend with deterministic unit-normalized vector generation.

## Alternatives Considered

1. **Fixed-Size PyArrow Column (`pa.list_(pa.float32(), 1024)`)**:
   - *Why Rejected*: While highly efficient, it locks the table to 1024 dimensions. Changing or comparing models would require a destructive table migration or creating entirely separate Delta tables for each model, defeating the purpose of the `(comment_id, embedding_model)` compound PK.
2. **Unified API client with no abstraction**:
   - *Why Rejected*: Hardcodes the embedding source, complicating Databricks promotion and requiring deep mocks in unit tests.
