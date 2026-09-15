# Repository working rules

## Validate changes

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm run build
```

Set `RUN_DB_TESTS=1` only against a migrated test database. Follow
`docs/setup.md` for database and browser tests.

## Code boundaries

- Keep financial calculations pure in `src/domain.py`.
- Keep SQLAlchemy models in `src/models/` and schema changes in Alembic migrations.
- Keep provider calls in `src/api/market_data.py`.
- Keep `src/main.py` limited to application assembly.
- Do not add abstractions until a current use case needs them.

## Safety and compatibility

- Add regression tests before changing calculations, imports, or persistence behavior.
- Keep structural refactors separate from deliberate financial behavior changes.
- Never commit `.env`, database dumps, backups, access tokens, or real financial data.
- Treat `src/db/*.pkl` as private legacy sources. Do not add new pickle persistence.
- Do not rewrite applied Alembic migrations; add a new migration.
- Do not silently combine values in different currencies or claim tax accuracy.
