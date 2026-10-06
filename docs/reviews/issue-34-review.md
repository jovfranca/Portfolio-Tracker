Review of issue #34 — 2026-10-05

**Ready for PR with the reviewed working-tree changes included.** No unresolved
code blockers were found. Live Google sign-in is an explicit verification limit
described below.

Compared `feat/34-multi-user-authentication`, including all existing modified and
untracked implementation files, against freshly fetched `origin/develop` at
`fcb73ea4f28aa5375571ce517e123539609eb941`. Local `develop` and the branch HEAD
both point to that commit; the issue implementation is currently uncommitted.
Read [issue #34](https://github.com/jovfranca/Portfolio-Tracker/issues/34), checked
its comments (none), and read the attached issue description. The restricted
proxy initially prevented GitHub access; `gh` succeeded outside the sandbox
before implementation changes.

Verified findings and fixes:

- **P2 — Migrated private instruments were missing from authenticated search.**
  Migration `0026` preserves non-catalog instruments with origin `MIGRATED` and
  assigns them to the initial financial space. Authenticated search included
  `CATALOG` and `CUSTOM` but excluded these retained identities. Search now also
  includes `MIGRATED`, subject to the existing household visibility check. The
  regression verifies the owning user's result and an independent user's empty
  result.
- **P2 — Concurrent invitation acceptance could fail to create shared access.**
  Two distinct invitations for the same user and space could both observe no
  membership and attempt insertion. PostgreSQL rejected the second insertion
  with a unique-constraint violation, which the API would return as 503. A real
  PostgreSQL regression reproduced this failure. Acceptance now locks the
  household before checking/inserting the membership; both invitations are
  consumed successfully while exactly one membership is retained.
- **P2 — Acceptance and revocation used conflicting lock order.** Acceptance
  locked the invitation before inserting a membership, whose household foreign
  key requires a lock. Revocation locked the household before updating the
  invitation. Concurrent operations could block each other. A second PostgreSQL
  regression reproduced a revocation lock timeout while acceptance was in
  progress. The household-first acceptance order resolves this cycle and the
  regression verifies that an already-started revocation completes, acceptance
  returns 404, and no membership is created.

Each finding was reproduced by a failing regression before its correction.
The fixes touch instrument search and invitation handling only. No financial
formula or migration changes were required.

The review checked backend session validation, Google identity verification and
linking, personal/shared space creation, membership roles and revocation,
disabled-user rejection, CSRF/origin protection, private instrument visibility,
and nested portfolio/resource isolation. The implementation keeps identities
separate from financial ownership and leaves financial calculations independent
of authentication. Existing tests cover source records, shared access, fixed
income, imports, manual prices/events, and the authenticated browser shell.

Validation:

- Baseline default backend suite: **326 passed, 56 skipped**.
- Final full suite with `RUN_DB_TESTS=1`: **385 passed**, including PostgreSQL
  API, persistence, migration, and invitation concurrency tests.
- Focused authentication/provider/migration suite after the fixes: **34 passed**.
- Frontend production build: passed.
- Real Microsoft Edge/Playwright suite against the isolated review API:
  **18 passed**, covering authentication and the existing financial workflows.
- Applied the complete Alembic chain through `0026` to a fresh isolated database;
  the populated synthetic identity migration regression also passed, including
  preservation of source, derived, and shared rows and its guarded downgrade.
- Final `alembic check`: **No new upgrade operations detected**.
- `git diff --check`: passed.

Database verification used a newly initialized PostgreSQL cluster under
`.local/pg-review34-oct05`, bound to `127.0.0.1:55444`, with database
`review34_test`. Browser verification used the same synthetic database and an
API on port `8044`. The persistent development database was not modified.
Windows sandbox restrictions initially blocked PostgreSQL startup, Playwright
worker spawning, and pytest temporary-directory access. Authorized runs outside
the sandbox completed the checks; no database or browser verification remains
blocked by those restrictions. The review services were stopped afterward.

Verification limit: no `GOOGLE_CLIENT_ID` is configured in the environment or
local configuration, so live Google account sign-in and deployed origin/client
configuration could not be exercised. Automated tests exercise Google's actual
JWT verifier using synthetic RSA-signed tokens and local certificate responses,
including signature, audience, issuer, expiry, nonce, subject, and email
authority checks. API tests cover repeated identity resolution, linking,
conflicting links, and single-use challenges. This review does not claim a live
OAuth deployment test.

The new PostgreSQL concurrency cases create committed synthetic identities so
separate connections can observe them, and remove their own records afterward.
Run them only against a separately migrated test database as required by
`AGENTS.md`.
