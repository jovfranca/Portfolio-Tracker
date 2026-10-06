Review of issue #34 and Settings follow-up — 2026-10-06

Ready for PR with the reviewed working-tree changes included. No unresolved
implementation or database-verification blockers remain. Live Google sign-in
is a verification limit described below.

Compared `feat/34-multi-user-authentication` at `2838954`, including the existing
modified and untracked Settings implementation, against `develop` at
`fcb73ea4f28aa5375571ce517e123539609eb941`. Refreshed `origin/develop` and confirmed
it matches local `develop`. Read the original
[issue #34](https://github.com/jovfranca/Portfolio-Tracker/issues/34) and its full
[Settings follow-up](https://github.com/jovfranca/Portfolio-Tracker/issues/34#issuecomment-6027118149)
before inspecting implementation code. GitHub access initially failed through
the sandbox proxy at `127.0.0.1:9`; the CLI succeeded outside that restriction.

Verified findings and fixes:

- **P2 — EDITOR and VIEWER could not see the selected space's members.**
  The follow-up requires a member roster with controls appropriate to each role.
  Both the API and Settings page restricted the entire roster to OWNER.
  API regressions reproduced 403 for existing EDITOR/VIEWER members, and browser
  regressions reproduced the missing roster. The read endpoint now requires
  membership; Settings shows the roster without administrative actions for
  EDITOR/VIEWER. Role changes, removal, invitation listing/creation/revocation,
  and last-owner protection retain their OWNER checks. Tests also verify that
  unrelated and removed members receive 404 and non-owners cannot administer.
- **P2 — An expired session during account refresh left Settings authenticated.**
  The frontend suppressed session-expiration events for every `/auth/` endpoint,
  including `/auth/me`. A Settings mutation followed by an unauthorized account
  refresh therefore left account and administration UI displayed with stale
  authentication state. A browser regression reproduced this behavior.
  Unauthorized `/auth/me` responses now clear the shell and return to login,
  while failed login attempts retain their existing behavior.

Each finding was reproduced by failing regressions before its fix. Updated the
authentication documentation and existing roster expectations. Preserved the
pre-existing Settings work. No financial calculation or migration was changed.

The review covered server-side session validation, cookie/CSRF protections,
Google identity verification and explicit linking, personal/shared spaces,
role changes and membership revocation, indirect resource isolation, private
instrument scope, migration preservation, and the amended Settings workflows.
No additional meaningful security, data-integrity, regression, or complexity
finding was verified.

Validation:

- Baseline default backend suite: **338 passed, 58 skipped**.
- Final full backend suite with `RUN_DB_TESTS=1`: **398 passed**, including
  PostgreSQL persistence, API, migration, and invitation concurrency cases.
- Focused authentication suite after the fixes: **29 passed**.
- Complete Microsoft Edge/Playwright suite: **24 passed**, including real-API
  financial workflows, Settings administration, role visibility, and expiry.
- Frontend production build: passed.
- Applied the full Alembic chain through `0026` to two fresh isolated databases.
  The populated synthetic identity-migration preservation/downgrade test passed.
- Final `alembic check`: **No new upgrade operations detected**.
- `git diff --check`: passed.

Database verification used a new PostgreSQL cluster at
`.local/pg-review34-oct06`, bound to `127.0.0.1:55446`. Backend tests used
`review34_test`; browser tests used the separately migrated
`review34_browser_test`, served on port `8047`. The persistent/local development
database was not modified. Review APIs and the cluster were stopped afterward.

Windows sandbox restrictions initially prevented PostgreSQL startup, Playwright
worker spawning (`spawn EPERM`), and pytest temporary-directory access
(`WinError 5`, even with a workspace temporary directory). Authorized runs
outside the sandbox completed these checks. No environment blocker remains.

Verification limit: a Google client is configured locally, but interactive
sign-in with a real Google account and the live provider/client/origin setup
were not exercised. Provider tests use Google's actual JWT verifier with
synthetic signed tokens and local certificate responses; API tests cover
identity resolution, repeated login, linking, conflicts, and single-use
challenges. Browser linking and acceptance use simulated provider state;
real API acceptance and permission checks have backend coverage. This report
does not claim a completed live two-Google-user workflow.
