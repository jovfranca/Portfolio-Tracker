Issue #34: local login failure investigation — 2026-10-05

**Fixed and verified.** Read the complete GitHub issue and its comment thread
(no comments) before editing. The change remains scoped to usable local
authentication and serving the current frontend entry page.

Root cause:

- The existing local configuration had no `GOOGLE_CLIENT_ID`, no
  `DEV_AUTH_ENABLED`, and no `DEV_AUTH_TOKEN`. The effective defaults intentionally
  disable local authentication and require secure cookies. `start-local.ps1`
  launched ordinary Uvicorn without supplying or requesting a login method.
- `/api/auth/config` therefore correctly reported no Google provider and
  `dev_enabled: false`. The UI had only a disabled Google button. There was no
  credential submission to fail: the application offered no usable login path.
- The earlier review's tests explicitly enabled development login, supplied a
  synthetic key, and disabled secure cookies for HTTP. Those tests verified an
  already-configured server, missing the normal launcher with the user's existing
  pre-authentication configuration. The previous invitation/search fixes do not
  address this startup gap.
- The asset 404s refer to filenames from a previous build. The current HTML points
  to different files, which returned 200 in the supplied log and in verification.
  The HTML response previously lacked a cache policy, allowing stale entry pages
  to reference files removed by a later build. This is separate from the login
  configuration failure. A 401 from `/api/auth/me` before login is expected.

Smallest robust correction:

- The existing PowerShell launcher delegates its API step to
  `scripts.start_local_api`. With no configured login, this Python process asks
  for a development key using a hidden terminal prompt. The entered key enables
  the existing development authentication flow for this process only. Users log
  in as **local** to resolve the existing migrated user and space.
- The helper binds HTTP to `127.0.0.1:8000` and sets HTTP-compatible session
  cookies inside that process. It preserves configured Google/development login,
  does not write `.env`, does not alter the calling shell's environment, and does
  not print credentials. Empty/oversized keys and prompts that would echo input
  stop startup rather than leaving an unusable server or exposing credentials.
- Development credential comparison uses UTF-8 bytes so a key containing
  non-ASCII characters does not raise `TypeError` in `compare_digest`.
- The HTML entry response now uses `Cache-Control: no-store`. Missing assets
  continue returning 404; they are not disguised as a successful HTML response.
  A hard reload is still needed for HTML cached before this fix.

Regression considerations:

- Ordinary `uvicorn src.main:app` retains disabled development authentication
  and HTTPS-only cookie defaults. Merely importing the helper changes no settings.
- Configured Google login does not automatically enable development login.
  Configured development credentials are not replaced or prompted for again.
- Backend authentication, CSRF checks, membership roles and space isolation
  remain enforced. Local startup does not bypass them.
- Noninteractive local startup needs configured credentials. Unconfigured
  interactive startup requires choosing a key for each server execution.
- No schema, migration, financial formula, or financial persistence changes were
  made for this fix. The persistent development database was not modified.

Verification:

- Default backend suite: **335 passed, 58 skipped**.
- Focused startup/authentication/provider/PostgreSQL/migration suite:
  **42 passed** against an isolated database where applicable.
- Frontend production build: passed.
- Actual Windows terminal startup with all authentication settings disabled:
  the hidden prompt accepted a synthetic key without echoing it, then started
  the API. For verification only, the server port was redirected to `8045` while
  retaining the loopback bind, avoiding the user's normal application port.
- Real Edge/Playwright authentication workflow on that server: **1 passed**,
  covering invalid login, successful login, restoration, space switching and
  logout. It used the credentials entered into the actual startup prompt.
- Fresh PostgreSQL database `review34_login_test` on the isolated review cluster
  at `127.0.0.1:55444`: migrations through `0026` applied; `alembic check` found
  no schema drift. The local startup regression also verifies that **local**
  resolves an existing initial user and can access that user's retained portfolio.
- `git diff --check`: passed. Review API and isolated PostgreSQL were stopped
  after verification.

To retry: stop the old API, run `scripts/start-local.ps1 -SkipBuild`, enter a key
at the hidden terminal prompt, hard-refresh the browser once, and log in with
username **local** and that key. Google still requires a real client ID and its
authorized-origin configuration; this correction does not provision a Google
OAuth client.
