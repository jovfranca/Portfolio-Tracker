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

## GitHub issue access protocol:
- The GitHub issue and its full comment/follow-up thread are the source of truth for the task.
- Read them BEFORE inspecting or editing implementation code.
- Prefer the GitHub CLI (`gh`) for repository issues and PRs. Do not use generic web search as a fallback for repository content.
- Start with the direct command needed for the task, e.g.:
  `gh issue view <issue> --comments`
- If `gh` fails:
  1. diagnose the failure once (`gh auth status`, repository remote, and the exact CLI error);
  2. distinguish authentication/network/proxy problems from an invalid command or repository problem;
  3. retry only if there is a concrete fix available in the current environment.
- Do not spend time cycling through `gh`, web search, and browser routes that cannot access the repository.
- If the issue still cannot be read, STOP before making code changes and report the exact blocker. Never implement an issue from its number/title alone or from guessed requirements.
- If the issue text has already been provided directly in the task/context, use that instead of trying to retrieve it again.

Issue interpretation:
- After reading the issue and all follow-up comments, extract the current acceptance criteria and treat later follow-ups as amendments to the original issue.
- Resolve apparent conflicts in favor of the latest explicit requirement.
- Before editing, make a short scoped implementation plan based on those requirements.
- Keep the implementation limited to the requested behavior unless a supporting change is necessary for correctness.