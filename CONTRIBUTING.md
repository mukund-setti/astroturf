# Contributing

Thanks for taking a look at Astroturf.

## Development Setup

```powershell
uv sync
.uv-test-venv\Scripts\python.exe -m pytest
.uv-test-venv\Scripts\python.exe -m ruff check .
.uv-test-venv\Scripts\python.exe -m ruff format --check .
```

For the UI:

```powershell
cd ui
npm install
npm run lint
npx tsc --noEmit
npm run build
```

## Guidelines

- Keep agent outputs idempotent and replayable.
- Do not commit secrets, generated Delta tables, MLflow local state, raw exports, or logs.
- Add or update tests for behavior changes.
- Keep notebooks thin; put reusable logic in Python modules.
- Treat attribution and migration outputs as evidence requiring human review, not accusations.
