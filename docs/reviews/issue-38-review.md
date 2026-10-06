Review of issue #38 — 2026-10-05

**Ready for PR with the reviewed working-tree changes included.** No unresolved
blockers were found in this review.

Compared `feat/38-consolidation-optimization` at
`14b0cb859b4c049b87c9947db76ee8d90b6acdeb`, including the existing uncommitted
changes and new fixed-income files, against `develop` at
`b48b4f4785798aeb567717b67697ab5958a693b4`.
Read [issue #38](https://github.com/jovfranca/Portfolio-Tracker/issues/38), both
GitHub follow-up comments, and the supplied attachments. GitHub initially failed
because the sandbox proxy refused connections; `gh` access succeeded outside
the sandbox before code changes.

Verified findings and fixes from this review:

- **P2 — Fresh benchmark observations left rebuilt lots pending.** During a
  next-day checkpoint extension, fetching a benchmark period creates a new
  `FixedIncomeInvalidation` after the consolidation function has loaded its
  invalidation map. The replay incorporated that observation but failed to clear
  the newly created invalidation, reporting an incomplete update and stale lot.
  `src/fixed_income_history.py` now consumes the new invalidation when the rebuilt
  suffix covers its boundary. The regression reproduces two successive explicit
  updates with provider observations fetched during each update.
- **P2 — Deleting the last market trade left a permanent unbuilt position.**
  After explicit consolidation removed obsolete snapshots and invalidations,
  retained asset metadata still produced an unknown/pending position. An empty
  portfolio consequently remained pending indefinitely. Overview now omits
  metadata-only assets when they have neither activity, snapshots, nor pending
  invalidation. Pending deletions still retain saved values until the explicit
  update. Regression coverage includes the unbuilt deletion case, PostgreSQL
  CRUD of a previously consolidated position, and the real browser workflow.
- **P2 — Updating one instrument replayed unrelated clean activity.** The
  quote-refresh pass called `position_now` on every clean market position simply
  to obtain its quantity. It now reads the latest saved quantity instead.
  The targeted-consolidation regression explicitly fails if the unrelated ARKK
  activity is replayed while PETR4 is being updated; its snapshots also remain
  unchanged.
- **Missing/stale browser coverage.** The real-API market and XLSX-import tests
  still expected automatic live calculations, and one database assertion expected
  the permanent pending state after deletion. Updated tests assert unknown values
  before the first update, saved values through pending edits/deletions, explicit
  update request counts, and the final empty portfolio after consolidation.

Each behavioral finding was reproduced with a failing regression before the fix.
No financial formula changes were required for these corrections.

The two blockers from the previous review are resolved by the existing
working-tree implementation and verified here:

- Fixed-income consolidation persists contractual-currency lot snapshots and
  resumable checkpoints. Reporting reads saved state; pending movement edits and
  deletions preserve consolidated values. Tests prohibit contractual replay from
  overview, history, performance and lot reads, and cover targeted lot suffixes,
  benchmark revisions, first consolidation, and display-currency projection.
- Market positions with activity but no canonical snapshots report explicit
  pending/unbuilt values. Tests cover new positions, previously built portfolios,
  pending edits/deletions and first consolidation, including same-day activity.
  GET guards prohibit canonical `position_now`/`position_history` reconstruction.
  Instrument metadata without any activity is not itself a holding.

The accounting-currency, dated-FX, ambiguity handling, per-position invalidation,
checkpoint reuse and financial regression suites remain passing. The reviewed
writes do not calculate overview or trigger consolidation, and display-currency
changes do not alter canonical history.

Verification:

- Full Python suite with `RUN_DB_TESTS=1`: **351 passed**. Only the two existing
  FastAPI/Starlette deprecation warnings remain.
- Frontend `npm run build`: **passed**.
- Edge/Playwright: **all 17 tests passed across final runs**. The full run passed
  16 tests; after correcting the market test's empty-state locator, its focused
  rerun passed. Coverage includes real-API market CRUD, fixed-income movement
  CRUD and imports, plus mocked reporting/currency-switching UI contracts.
- Fresh Alembic migrations through **0025**: **passed**.
- Populated **0022 -> 0023 -> 0024 -> 0025** upgrade: **passed** with synthetic
  market activity and a fixed-income lot. Trades, contracts and movements were
  preserved; old derived histories were removed and targeted rebuilds scheduled.
- The PostgreSQL migration regression also verifies 0025 preserves market
  snapshots and source movements while scheduling fixed-income histories.
- `alembic check`: **no schema drift**. `git diff --check`: **passed**.

All database verification used a newly initialized PostgreSQL cluster at
`.local/pg-review38-oct05`, bound to `127.0.0.1:55439`, with databases
`review38_test`, `review38_upgrade`, and `review38_browser`. The persistent/local
development database was not used or modified. The review API and cluster were
stopped after verification; synthetic databases and logs remain under `.local`.
Windows sandbox restrictions initially prevented PostgreSQL startup, pytest
temporary-directory access, and Playwright worker creation. Rerunning those
operations outside the sandbox resolved them. No verification remains blocked.

This review includes uncommitted and untracked implementation files, notably
migration 0025, `src/fixed_income_history.py`, and its migration test. Include
those files when preparing the PR; the committed branch alone does not contain
the full reviewed implementation.
