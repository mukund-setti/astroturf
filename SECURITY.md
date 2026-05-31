# Security

Astroturf is intended to be safe to publish as source code. Secrets must be supplied at runtime and must never be committed.

## Do Not Commit

- `.env`, `.env.local`, `.env.production`, or other environment files with real values.
- Databricks personal access tokens, service-principal secrets, workspace hostnames tied to private deployments, warehouse HTTP paths, job IDs, or cookies.
- PostgreSQL/Supabase/Neon/Railway connection URLs.
- api.data.gov keys, OpenAI/Anthropic/Gemini keys, Vercel tokens, private SSH keys, or service-account JSON files.
- Generated Delta tables, Parquet exports, MLflow local state, logs, or local UI control-plane JSON stores.

## Local Development

Copy placeholders from `.env.example` and `ui/.env.example`, then fill values locally:

```powershell
Copy-Item .env.example .env
Copy-Item ui\.env.example ui\.env.local
```

The default local UI mode is `ASTROTURF_DATA_MODE=mock`, which does not require Databricks credentials.

## Databricks

For Databricks notebooks/jobs, provide secrets through Databricks secret scopes, job parameters, cluster environment variables, or another runtime secret mechanism. Databricks Apps and hosted web deployments should receive secrets from the deployment platform at runtime.

Do not hardcode `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `DATABRICKS_HTTP_PATH`, `DATABRICKS_JOB_ID`, or database URLs in notebooks, scripts, docs, or committed config files.

## Reporting

If you find a committed secret, revoke it first, then remove it from the repository and history before making the repository public.
