# Issue #41 branch review — 2026-10-06

The original review below is retained as history. The [2026-10-07 follow-up
review](#follow-up-review--2026-10-07) records the implementation and verification
of the four gaps identified here.

The confirmed defects below are fixed and covered by regressions. The branch is
not ready for a PR claiming the complete scope of issue #41: the acceptance gaps
listed below remain. A draft PR can make the delivered scope and those gaps explicit.

## Scope and requirements

Reviewed `feat/41-ui-refactor`, including its existing uncommitted changes, against
`develop` and freshly fetched `origin/develop`. All three commit references point
to `1b01e2d63045713e528c40a5051b9cb88bd62800`; the refactor and review fixes are
working-tree changes, not branch commits.

Read [issue #41](https://github.com/jovfranca/Portfolio-Tracker/issues/41) completely
before inspecting implementation code. GitHub returned no follow-up comments.
The initial CLI failure was a refused connection to the sandbox proxy
`127.0.0.1:9`. Removing that proxy for an approved process restored CLI access;
the stored authentication worked on that connection.

Used the supplied handoff architecture for navigation and reviewed the brand and
mockup references. The attachment is reference material, not a separate request
to implement every mockup feature. Financial semantics remain governed by the
existing backend and tests. Canonical assets, typography and palette are checked
by the existing brand regression tests. The review adds no migration and changes
no financial calculation or persistence rule.

## Verified findings and fixes

| Priority | Finding | Fix and evidence |
| --- | --- | --- |
| P1 | Creating a portfolio could select the new portfolio while the mutation still reloaded the old context. A later old response overwrote the displayed overview: the new empty portfolio showed the previous portfolio's value. | `PortfoliosPage` completes the mutation reload before selecting the newly created portfolio. A browser regression delayed the old response and reproduced `120,00` under the new selection instead of `0,00`; it passes after the fix. |
| P2 | Position detail filtered transactions by displayed ticker. Transactions entered/imported under an alias did not match the canonical symbol, so transactions, instrument metadata and the scoped creation action could disappear. Instrument detail used the same text comparison for related positions. | Market position projections now include `instrument_id` in unbuilt, pending and consolidated states. Both detail pages use that identity. An authenticated API test verifies an `ALIAS` transaction with a `CANONICAL` position; the browser regression verifies transaction, creation-action and related-position links. Both failed before the fix. |
| P2 | Overview combined current portfolio value with acquisition cost and result from the last historical closing snapshot. Changes since that snapshot made the cards describe different valuation dates without saying so. | Cost and result now use the existing current reporting-currency summary. The historical accumulated return explicitly shows its date. The browser regression reproduced a historical cost of `100,00` instead of the current `110,00`. No calculation was added to the frontend. |
| P2 | Rolling month/year periods used `Date.setMonth` with the original day of month. Invalid target dates overflowed into the following month. | Period boundaries clamp to the last valid target-month day. Browser coverage verifies March 31 → February 29 and February 29 → February 28 of the previous year. Before the fix the first case started on March 2. |
| P2 | Performance's asset breakdown explicitly excluded fixed income and provided no lot breakdown or links, despite including fixed income in portfolio totals. | Performance reuses the existing lot table alongside market positions. Its values keep their supplied currency labels and gross-value semantics. A browser regression verifies navigation to `/fixed-income/:lotId`; it failed before the fix. |

The app/import browser fixtures also now wait for creation to finish and for the new
portfolio to be selected before doing a full browser navigation. Previously it
could interrupt that asynchronous flow and import into the previously selected
test portfolio. All records involved were synthetic and in the review database.

## Remaining acceptance gaps

These are implementation gaps, not failures to obtain GitHub or PostgreSQL access.
Documenting a limitation does not itself satisfy the corresponding acceptance criterion.

| Requirement | Current implementation and blocker |
| --- | --- |
| §14: invitation acceptance shows the financial space, inviter and role, with Accept/Reject | `InvitationPage.tsx` asks the recipient to check these details with the sender and offers acceptance or navigation away. There is no invitation-preview or rejection API. `HouseholdInvitation` does not persist an inviter and its status constraint only permits PENDING/ACCEPTED/REVOKED. Completing this needs an authenticated preview contract and a defined rejection/audit lifecycle; navigating away must not be described as rejection. |
| §11: FX history, used pairs and missing dates; detailed market-data status | `FxPanel` only queries one currency/type/date at a time. The current HTTP contract exposes single-date lookup and backfill, not the required history/coverage projection. Status links identify categories, but do not provide complete date/pair coverage diagnostics or the last successful synchronization time. Supporting projections are still needed; a historical closing date is not an update timestamp. |
| §13: financial-space list includes member count, portfolio count and status | The list currently shows name, role and actions. The underlying records exist, but the space/session projection does not supply these counts/status and the UI does not render them. This is a remaining page-completeness item, not a need for a new financial rule. |
| §3: Overview includes a period result | The page shows current accumulated monetary result and a dated accumulated historical return. It has no selected-period result experience. The period analytics API currently returns return percentage and net contributions, not a monetary period-result projection. Its definition must respect existing flows and valuation semantics. |

Other limits are documented in `docs/quintrion-ui.md`: production local-password
signup/recovery, Apple, account/profile lifecycle, portfolio/space archival,
manual-price deletion, manual FX correction, corporate-event approval states,
transaction origin/audit metadata and benchmark comparison. Requirements expressly
conditional on existing support should not be treated as implemented; nor should
the UI simulate successful unsupported operations. Invitation metadata/rejection
and the coverage views above are explicit gaps in the requested full experience.

## Verification

- Default repository command: **351 passed, 58 skipped**. Skips are the opt-in database tests.
- Full suite with `RUN_DB_TESTS=1`: **409 passed** against the isolated migrated PostgreSQL database.
- `npm run build`: passed.
- Final Playwright suite: **36 passed**, including five new browser regressions.
- Inspected desktop, mobile and dark-theme screenshots; core navigation and layout fit the viewport.
- `alembic current`: `0026 (head)`; `alembic check`: no new upgrade operations.
- `git diff --check`: passed.

Initialized a separate PostgreSQL cluster at `.local/review41-pgdata`, bound to
`127.0.0.1:55441`, and created `review41_test` and `review41_browser`. Applied
`alembic upgrade head` to both empty databases. Browser tests used the isolated
API at port 8041. The review services were stopped after verification. No persistent
development database was modified.

Sandbox restricted-token/process-spawn errors initially prevented PostgreSQL and
Playwright startup; approved execution resolved them. Pytest temporary-directory
ACL errors were likewise resolved with approved execution. These are resolved
environment restrictions, not outstanding verification blockers.

Browser and financial-provider regressions use synthetic data and controlled
provider responses. Live Google sign-in and real provider availability were not
verified by this review. Two existing FastAPI/Starlette deprecation warnings remain.

The final legacy-brand search found only documented compatibility references:
repository links, existing database/volume identifiers, authentication cookies,
the `X-Aurion-Request` protocol header and migration from `aurion-household` local
storage. These are intentionally retained; no product branding regression was found.

No commit, push or PR was created.

## Follow-up review — 2026-10-07

Read issue #41 and its complete follow-up comment before inspecting implementation
code. The follow-up narrowed this work to the four functional gaps recorded above;
the dedicated Overview visual-convergence pass remains a subsequent step. The
four functional gaps are now implemented and covered by regressions.

### Delivered behavior

- Invitation recipients can preview the financial space, inviter, role, email,
  expiry and lifecycle state before accepting or rejecting. Both decisions
  require the existing verified, matching recipient identity. Rejection persists
  `REJECTED` without creating membership or modifying portfolio records; acceptance
  retains household membership behavior. Accepted, rejected, revoked and expired
  invitations have deliberate terminal handling. Decisions use the existing lock
  order, including concurrent acceptance/rejection coverage. Migration `0027`
  adds nullable inviter/decision audit fields and the rejection state; it leaves
  legacy audit information unknown instead of inventing it. Its downgrade keeps
  rejected tokens unusable by mapping them to revoked.
- The FX page exposes the portfolio's required conversion pairs, stored FX/PTAX
  history, sources, retrieval timestamps and missing required dates. Coverage
  follows the existing BRL bridge and historical fallback rules, preserves frozen
  transaction FX, and includes holdings, income and fixed-income requirements.
  Missing history, unresolved accounting currencies and pending consolidation are
  explicit. Data status also links to these diagnostics. Observation dates and
  retrieval timestamps have separate labels; last successful synchronization is
  explicitly unknown because there is no persisted completed-sync event. The
  read-only projection does not call providers or change conversion rules.
- Financial spaces show name, current role, member count, portfolio count and
  their supported active state. Counts come from aggregate backend projections
  without frontend requests for every space. The list refreshes on entry and
  mutation; the existing one-space/multiple-space selector behavior remains.
- Overview and Performance share period controls and calendar boundaries.
  Overview's monetary period result is supplied by backend analytics, using the
  sum of existing daily valuation numerators:
  `closing value + daily income - opening value - net flow`. Buys, fees, sales,
  fixed-income contributions/redemptions and income retain their existing
  semantics. Opening value is zero only at actual portfolio inception; later
  periods require the previous closing snapshot. Reporting currency and effective
  closed-day boundaries are returned explicitly. Missing inputs, gaps, pending
  history, mixed currencies or incomplete boundaries produce an unknown result,
  not a fabricated zero. Current accumulated metrics remain separate.

The supporting contracts and limitations are documented in `docs/quintrion-ui.md`.
No archival state, tax interpretation or unsupported synchronization success was
added. Existing migrations were not rewritten.

### Final verification

- Default repository pytest command: **372 passed, 60 skipped**.
- Complete suite with `RUN_DB_TESTS=1`: **432 passed**, including migration
  upgrade/downgrade, identity/membership, invitation races, period calculations,
  fixed-income/FX and API regressions.
- `npm run build`: passed, including the configured TypeScript check.
- Complete Playwright suite: **44 passed**, including eight follow-up regressions
  and existing desktop/mobile/dark-theme coverage.
- Visually inspected invitation preview, financial-space list, Overview period
  result, FX coverage/history and data-status screenshots.
- Fresh `alembic upgrade head` on both isolated databases: passed;
  `alembic current`: `0027 (head)`;
  `alembic check`: no new upgrade operations.
- `python -m compileall -q src migrations tests`: passed.
- `git diff --check`: passed. The repository has no separate configured lint
  command; no additional lint result is claimed.

Validation used a new isolated PostgreSQL cluster at
`.local/followup41-pgdata`, bound to `127.0.0.1:55442`, with migrated
`followup41_test` and `followup41_browser` databases. Browser tests used the
isolated API on port 8042 and synthetic records. The development database and
`.env` were not modified. Restricted-token/process-spawn and pytest temporary
directory ACL restrictions were resolved using approved execution. Both isolated
services were stopped after verification. Two existing FastAPI/Starlette
deprecation warnings remain.

For a real deployment, apply migration `0027` before restarting the API. Manually
verify the invitation journey with actual Google identities and inspect FX
coverage after real provider refreshes; tests use controlled provider responses
and do not establish live provider availability. The separately requested Overview
visual-convergence pass remains deferred. No commit, push or PR was created.

## Independent branch and follow-up review — 2026-10-07

Reviewed commit `7c9e3da` on `feat/41-ui-refactor` and the existing follow-up
working-tree changes against `develop` and freshly fetched `origin/develop`, both
at `1b01e2d`. Read the complete issue and its sole follow-up comment first. The
previous review history above is preserved; this section records a new verification
run and two additional defects found and fixed during this review.

GitHub CLI initially failed through the unavailable proxy `127.0.0.1:9`, and
`gh auth status` reported an invalid token on that connection. The connected
GitHub integration supplied the complete issue/comment thread. An approved direct
connection with proxy variables cleared only for that process subsequently restored
CLI access and fetched `develop`; no persistent authentication or proxy settings
were changed.

### Verified additional findings

| Priority | Finding | Fix and regression evidence |
| --- | --- | --- |
| P2 | FX coverage treated a previously consolidated fixed-income lot as having complete requirements after editing its application date. Backdating the application omitted the earlier FX dates, so the screen could claim complete coverage while the source ledger required missing observations. Retained snapshots after deletion also lacked the provisional flag. | `src/fx_reporting.py` checks existing instrument invalidations and stale lot snapshots, retains saved-history requirements, and adds the edited source date range. An authenticated API regression failed with `requirements_status = complete` before the fix; it now verifies pending state, both missing backdated dates, retained requirements after deletion, and removal after explicit consolidation. Future snapshots are excluded consistently with existing reporting. |
| P2 | `/invite/%` threw an uncaught `URIError` in `App.tsx`, leaving the authenticated application blank instead of intentionally handling an invalid invitation. | Token decoding tolerates malformed encoding and sends the invalid token through the authenticated preview contract. A Playwright regression failed because the invitation heading never rendered before the fix; it now verifies the error state, absent decision buttons, and no browser page errors. |

Neither fix changes financial formulas, conversion rules, membership permissions,
or source records. Regression tests were added and reproduced each defect before
implementation changes.

### Follow-up acceptance assessment

All four functional gaps in the latest comment are resolved within the existing
working-tree implementation, with the FX correction above:

- Invitations expose recipient-authorized preview metadata and persistent
  rejection, with explicit terminal states. Acceptance retains membership-only
  behavior; matching verified identity, space permissions, and concurrent
  acceptance/rejection/revocation remain covered.
- Portfolio FX diagnostics expose required pairs, history, missing dates,
  fallback references and providers. Edited/unbuilt requirements are explicitly
  provisional. Observation retrieval times remain distinct from synchronization;
  a completed synchronization timestamp is truthfully modeled as unknown.
- Financial-space counts, current role and supported active status come from
  server aggregates. Browser coverage verifies the list and single/multiple-space
  context behavior without per-space member requests.
- Monetary period result is calculated in `src/domain.py` from dated portfolio
  values, daily income and net flows, including fixed-income projections. The
  shared Overview/Performance period controls retain calendar clamping. Missing
  opening snapshots, required inputs, dates, FX and pending history remain unknown.

### Verification evidence

- Default pytest suite: **373 passed, 60 skipped**; skips are opt-in PostgreSQL tests.
- Complete suite with `RUN_DB_TESTS=1`: **433 passed**. This includes PostgreSQL
  invitation concurrency, migration upgrade/downgrade and existing financial/data
  integrity tests. A restricted run initially encountered temporary-directory ACL
  errors; an approved run with a fresh directory completed successfully.
- Focused FX regressions after extending deletion coverage: **7 passed**.
- Frontend TypeScript/build: passed after the invitation fix.
- Complete Playwright suite: **45 passed**, including the new malformed-token
  regression and existing responsive/theme coverage.
- Applied `alembic upgrade head` to two fresh isolated databases;
  `alembic current`: **0027 (head)**; `alembic check`: **no new upgrade operations**.
- Visually inspected browser screenshots for invitation preview, space list,
  Overview period result, FX history/coverage and data status.
- `git diff --check`: passed. Legacy-brand search found only the previously
  documented compatibility headers/cookies/storage and documentation references.

Database verification used a new cluster at `.local/audit41-pgdata`, bound only
to `127.0.0.1:55443`, with `audit41_test` and `audit41_browser`. The isolated browser
API ran on port `8043`. PostgreSQL startup needed approved execution because the
restricted token could not start the server. No development database or `.env`
was modified. Review services were stopped after verification.

### Readiness and remaining scope

No unresolved functional defect or verification blocker was found in the four-gap
follow-up. It is ready for the explicitly scheduled Overview visual-convergence
pass. It is **not yet ready for the final Issue #41 PR**: the latest comment
requires that visual pass and a subsequent final readiness review before creating
the PR. Conditional backend limitations listed earlier remain accurately disclosed;
this review does not claim live Google sign-in or real provider availability.

No commit, push or PR was created.

## Overview visual pass — 2026-10-07

Implemented the latest [Overview Visual Pass (Revised) follow-up](https://github.com/jovfranca/Portfolio-Tracker/issues/41#issuecomment-6049705621)
after reading the issue and complete comment thread. Direct GitHub CLI access was
restored by clearing the unavailable proxy variables for the approved command;
authentication and persistent proxy settings were not changed. Existing
uncommitted functional follow-up work was preserved.

### Scope and acceptance

- Overview now gives the interactive chart roughly two thirds of the desktop
  upper row, beside stacked total-value, annualized-return and monetary-gain
  cards. Allocation and the latest five ledger activities form the lower row.
  Laptop, mobile and dark-theme layouts preserve the same hierarchy.
- The sidebar has an edge chevron, clean group dividers and compact branding.
  The top bar keeps portfolio/financial-space context, a readable truthful update
  indicator, a light refresh action and a gradient Add action without repeating
  the page title. Existing routes, bottom navigation and dialogs remain in use.
- The lazy-loaded ECharts chart supports return/value modes, period presets,
  date/value hover with crosshair and highlighted points, a draggable navigator,
  Ctrl-wheel zoom and Ctrl+Shift-wheel movement. Ordinary scrolling remains
  available. Preset/date controls, a restore action and a disclosed data table
  provide alternatives to pointer gestures. Zoom survives mode and theme changes.
- Portfolio return series and annualization are opt-in additions to the existing
  analytics endpoint. Pure calculations stay in `src/domain.py`; annualization
  uses actual inclusive coverage days and a 365-day year. The preexisting period
  result formula and default API response contract are preserved. Zoomed metric
  windows are recalculated by the backend; the chart caption states its original
  cumulative-return baseline separately from the inspected window.
- CDI comparison uses only stored canonical BRL daily observations, with the
  existing Brazilian business-day calendar. Required missing observations and
  pending portfolio history remain unknown; gaps are not bridged. The benchmark
  array supports extension, while IBOV and USD alternatives stay explicitly
  unavailable. No provider, persistence format or migration was introduced.
- The total-value card shows calendar-month monetary gain; the annualized card
  links to Performance and retains daily/monthly/annual/inception summaries. The
  monetary-gain selector defaults to 1M and uses existing backend period results.
  Optional mini bars were omitted because the available contract does not supply
  granular monetary results. Allocation switches between asset class and currency,
  without inventing geography or percentages for unavailable/negative values.
- Activities use five actual market/fixed-income ledger records with original
  denominations. Dates are displayed without invented times. BRL and USD use
  explicit currency prefixes and their respective number formats. Successful
  refresh times are session-local; after reload, the saved history date is shown
  instead of claiming a persisted synchronization time.

### Verification and visual correction

- Default pytest suite: **382 passed, 60 skipped** (opt-in database tests).
- Complete suite against a fresh migrated database with `RUN_DB_TESTS=1`:
  **442 passed**, including nine new Overview analytics regressions.
- Complete Playwright suite: **50 passed**. After final caption and contrast/layer
  corrections, all **5 focused Overview browser tests passed again**.
- Final `npm run build`: passed, including `tsc -b`. ECharts is loaded separately;
  Vite reports its 552 kB chart chunk exceeds the 500 kB advisory threshold
  (189 kB gzip). This is a remaining build warning, not a suppressed check.
- Fresh database upgrade: **0027 (head)**; `alembic check`: **no new upgrade
  operations**. No schema change belongs to this visual pass.
- `python -m compileall -q src migrations tests` and `git diff --check`: passed.
  No separate lint command is configured. Two existing FastAPI/Starlette
  deprecation warnings remain.
- Inspected desktop, mobile, dark-theme and hover screenshots against the supplied
  Quintrion references and identity assets. The correction pass fixed initial
  chart rendering, preserved zoom, localized chart accessibility, raised the
  donut's center label above the canvas, and improved dark-theme action contrast.
  Existing canonical brand assets were retained.
- `frontend/test-results/overview-real-desktop.png` and
  `frontend/test-results/overview-real-mobile.png` show persisted synthetic
  fixed-income lots and movements calculated through the real backend, rather
  than mocked totals. Mixed allocation, USD, missing data, benchmark gaps, card
  navigation, chart interactions and widths 1280/1024/768/390/320 also have browser
  coverage. Screenshot artifacts are local and ignored by Git.

Validation used a new cluster at `.local/visual41-pgdata`, bound to
`127.0.0.1:55444`, with migrated `visual41_test` and `visual41_browser` databases.
The isolated API ran on port 8044. All records were synthetic; the development
database, `.env` and private legacy sources were not modified. Test services were
stopped after verification.

No unresolved Overview regression was found by these checks. Manually review the
final desktop/mobile appearance with a representative portfolio and the supplied
visual references; real provider availability and complete CDI observation
coverage are not established by controlled tests. The final Issue #41 readiness
review remains a separate step before any PR. No commit, push or PR was created.

## Branch review after Overview visual pass — 2026-10-07

Reviewed `feat/41-ui-refactor` at `7c9e3da`, including the existing uncommitted
and untracked follow-up implementation, against `develop` and freshly fetched
`origin/develop`, both at `1b01e2d`. Read issue #41 and both complete follow-up
comments; the latest [Overview Visual Pass (Revised)](https://github.com/jovfranca/Portfolio-Tracker/issues/41#issuecomment-6049705621)
governs the visual scope and its no-PR stop condition. Earlier review history
above is retained. GitHub's refused sandbox proxy connection was resolved through
approved CLI execution; authentication and persistent proxy settings were unchanged.

### Confirmed findings and fixes

| Priority | Finding | Fix and regression evidence |
| --- | --- | --- |
| P2 | Restoring a zoomed custom chart period reset the navigator but retained the narrower dates and backend KPI window. Editing one date after zoom also retained the other boundary only in the metrics, leaving the chart on a different window. | Custom restoration copies the original chart boundaries back to the inspected selection. Date edits synchronize both boundaries before resetting the chart. The new Playwright regression reproduced September 2 instead of September 1 after restoration, and September 30 instead of September 29 in the chart after editing. It now passes through both interactions and checks the backend metric context. |
| P2 | CDI comparison compounded only dates having portfolio snapshots. A missing portfolio date silently omitted that business day's CDI return, or failed to detect its missing observation. | `cdi_return_series()` evaluates every intervening calendar day using the existing BR business-day calendar and stored observations, emitting points on the available chart dates. Missing required CDI observations keep subsequent values unknown. A unit regression reproduced 4.03% instead of 6.1106% when a Monday snapshot was absent; it now checks both complete stored observations and a missing intervening observation. Portfolio aggregate completeness remains governed by the existing historical checks. |
| P2 | The visual pass removed the largest-positions list required by issue #41 §3. A link to the ordinary Positions page did not retain that Overview acceptance criterion. | Restored five positions ordered by available backend reporting-currency values inside “Mais sobre a carteira”, preserving the primary dashboard composition. Unknown values are explicitly disclosed and excluded from ranking. The new browser regression failed because the section was absent; it now checks ordering, the five-row limit, currency prefixes, unknown-value disclosure, market-detail navigation, fixed-income routing and mobile fit. |

No source records, accounting/conversion rules, authorization model, applied
migrations or provider behavior were changed by these review fixes. The CDI fix
is limited to the new comparison projection. Financial calculations remain pure
in `src/domain.py`; no authoritative metric was moved into React.

### Acceptance and visual assessment

The four functional gaps from the first follow-up remain implemented: authenticated
invitation preview and persistent rejection, portfolio FX history/coverage,
server-projected space counts/status and backend monetary period results.
Regression coverage continues to exercise permissions, invitation races and
unknown/pending financial states.

Compared available supplied Quintrion mockup/brand materials and the latest
comment's composition with fresh desktop, mobile, dark-theme and hover captures.
The chart remains the desktop anchor beside three stacked KPIs; allocation and
five real ledger activities occupy the lower row. Sidebar chevrons, horizontal
context labels, truthful update text, actions, currency prefixes, crosshair,
tooltip, period/navigator controls and specified card navigation are covered.
The restored secondary table was also visually inspected on desktop and mobile.
Screenshots include `overview-real-desktop.png`, `overview-real-mobile.png`,
`overview-chart-hover.png` and `overview-largest-mobile.png` under the ignored
`frontend/test-results` directory. Real-backend captures use persisted synthetic
fixed-income records and their actual calculated valuations.

No further blocking visual or functional defect was identified. Broader page
redesign, optional gain mini-bars, new benchmark providers, geography without
data, fabricated activity times and persisted synchronization timestamps remain
outside this pass. Existing conditional backend limitations remain disclosed in
`docs/quintrion-ui.md`; this review does not establish live Google/provider availability.

### Verification

- Required default pytest command after the calculation fix: **383 passed,
  60 skipped**; skips are opt-in PostgreSQL tests.
- Full suite with `RUN_DB_TESTS=1`: **443 passed**, including migration
  upgrade/downgrade, PostgreSQL invitation concurrency and financial/API regressions.
- Focused analytics and period-result tests: **18 passed**.
- Final frontend TypeScript/build: **passed**. The existing ECharts chunk advisory
  remains: approximately 552 kB minified / 189 kB gzip; no warning was suppressed.
- Final complete Playwright suite after all fixes: **52 passed**. Responsive
  coverage includes widths 1280, 1024, 768, 390 and 320; the new secondary table
  also passes its 390px overflow check.
- Applied `alembic upgrade head` to two newly created isolated databases:
  **0027 (head)**. `alembic check`: **no new upgrade operations**.
- `python -m compileall -q src migrations tests` and `git diff --check`: **passed**.
- Legacy-brand search found only previously documented protocol/storage/cookie,
  repository and historical-documentation compatibility references.

Verification used a new cluster at `.local/recheck41-pgdata`, bound only to
`127.0.0.1:55445`, with `recheck41_test` and `recheck41_browser`. The browser API
ran on port `8045`. The persistent development database, `.env` and private legacy
sources were untouched. PostgreSQL/browser process-spawn restrictions and pytest
temporary-directory ACL failures were resolved using approved execution; the
successful results above are reruns, not claims that the restricted runs passed.
Two existing FastAPI/Starlette deprecation warnings remain. Review services were
stopped after verification.

### Readiness

The reviewed working-tree implementation has no remaining confirmed blocking
finding or verification blocker and is ready for PR review/preparation. Include
the existing untracked implementation, tests and migration when preparing the
branch; they are part of the reviewed result, not yet committed branch content.
The latest follow-up's explicit instruction to stop before creating the final
PR remains respected. No commit, push or PR was created.
