# Changelog

All notable changes to Hive are documented here. Releases correspond to GitHub tags and follow [semantic versioning](https://semver.org/).

See the [GitHub releases page](https://github.com/warlordofmars/hive/releases) for full release notes generated from merged PRs.

## [Unreleased]

_Changes accumulated on `development` since v0.22.0. Will be rolled into the next release._

## v0.22.0 — 2026-04-18

### Added

#### MCP surface

- Every MCP tool response carries the caller's quota and rate-limit state under a top-level `_meta.hive` block (`memory_quota.{used,limit,remaining}` + `rate_limit.{per_minute_limit,per_day_limit}`) so well-behaved agents can self-throttle before hitting a hard limit. New docs page `/docs/concepts/quotas` documents the schema. `memory_history` now returns `{versions, count}` instead of a bare list for a consistent structured-content envelope. (#453)
- Long-running tools (`search_memories`, `summarize_context`) emit MCP `notifications/progress` events at major stages; supporting clients render progress indicators. Best-effort — falls through on clients that don't support it. (#449)
- `remember(key, value, …, version=)` accepts an optimistic-lock token from a prior `recall`/`list_memories` response; concurrent-write conflicts raise a `ToolError` with the current state JSON-encoded so agents can compare-and-retry. (#391)
- `search_memories` now hybrid-retrieves: weighted blend of semantic similarity, term-frequency keyword match, and half-life recency decay against `last_accessed_at`/`updated_at`. Three optional `w_semantic/w_keyword/w_recency` params re-normalise to 1.0. Per-signal sub-scores exposed for debugging + agent-side re-ranking. (#481)
- `summarize_context` synthesises memories via MCP Sampling — the client's own model produces the briefing, with a deterministic concat fallback for clients that don't support sampling. (#448)
- New `redact_memory(key, reason=None)` tool tombstones a value while preserving the record: sets `Memory.redacted_at`, replaces value with `__redacted__`, writes the pre-redaction value to the audit log. `recall` on a redacted memory returns a sentinel; `list_memories` + `search_memories` skip redacted items by default (opt-in via `include_redacted`). (#400)
- `Memory.recall_count` + `last_accessed_at` — bumped atomically on every successful `recall`; surfaced on list/search results for ranking, dashboards, and memory-decay scoring. (#394)

#### Compliance & observability

- `log_audit_event` is now called from every memory-touching tool, producing an immutable `AUDIT#` trail separate from the user-visible activity log. Audit items carry a DynamoDB TTL (`HIVE_AUDIT_RETENTION_DAYS`, default 365) and a new `GET /api/admin/audit-log` endpoint exposes them with `client_id` / `event_type` / date-range filters. (#395)
- `POST /api/csp-report` receives browser CSP violation reports (both legacy `application/csp-report` and modern `application/reports+json`), logs them structured to CloudWatch, and emits a `CSPViolations` EMF metric (aggregate + per-directive drill-down). Unauthenticated by design; per-IP rate-limited. Admin dashboard gets a "Security" section showing the count. (#488)

#### Dev experience & CI

- Release Drafter keeps a draft GitHub release current as PRs merge into `development`, grouped by category label — no more hand-maintained `[Unreleased]`. Label-check workflow now requires a category label on every linked issue. (#420)
- `release-milestone-watcher` workflow opens a "Release: cut vX.Y" tracking issue when any `vX.Y` milestone drains to zero open non-epic issues. Pairs with the in-session stop condition. (#484, #512)

### Meta

- CLAUDE.md: design-review workflow + product-decision section. (#506)
- CLAUDE.md: milestone preference added to the issue selection algorithm. (#514)

## v0.21.0 — 2026-04-18

## v0.21.0 — 2026-04-18

### Added

#### MCP surface

- New `ping` tool for connectivity and auth health checks (#411)
- New `list_tags` tool for tag-space discovery (#415)
- New `relate_memories(key, top_k)` tool — semantic traversal from a memory to its nearest neighbours (#465)
- New `remember_if_absent(key, value, tags?, ttl_seconds?)` — conditional write only when the key doesn't already exist (#466)
- `search_memories` gained `min_score` (score threshold) and `filter_tags` (tag-intersection filter) parameters (#412, #444)
- `remember` enforces a UTF-8 byte-size cap on `value` (default 10 KB, configurable via `HIVE_MAX_VALUE_BYTES`) (#403)
- Every tool now advertises title + `readOnlyHint` / `destructiveHint` / `idempotentHint` / `openWorldHint` so capable clients can auto-approve read-only calls and confirm destructive ones (#469)
- `list_memories` and `search_memories` responses now include `owner_client_id`; the memory browser renders a "by {client name}" attribution badge on every card (#463)

#### Compliance & privacy

- GDPR Article 20 / CCPA §1798.100 data export: `GET /api/account/export` streams a JSON bundle with the user's profile, memories, OAuth clients, and the last 90 days of activity; rate-limited to one export per 5 min (#468)
- Opt-in GA4 cookie consent banner — no tracking script loads until the visitor clicks Accept; choice persisted in `localStorage`, revocable via a footer "Cookie preferences" link (#467)
- New `/subprocessors` page listing AWS, Google OAuth, and Google Analytics with purpose, data categories, and location; cross-linked from Privacy §4 and the FAQ (#470)

#### Infrastructure, security, & observability

- CloudFront response-headers policy: HSTS, `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, and a `Content-Security-Policy-Report-Only` draft; enforcing CSP tracked separately (#473)
- New CloudWatch alarms: Lambda throttles (MCP + API), DynamoDB user errors, and Bearer-token auth failures; every prod alarm now pages both on firing and on recovery (OK actions); first-deploy runbook documents the SNS subscription flow (#474)
- Backup / restore runbook for prod DynamoDB PITR recovery — when-to, pre-flight, restore, swap, validation, cleanup, post-mortem template, and annual drill guidance (#478)
- SEO: `robots.txt` + `sitemap.xml` for marketing SPA + VitePress-generated docs sitemap (#443)
- Open Graph + Twitter Card metadata across marketing and docs pages so shared links render proper preview cards (#455)

#### Dev experience & CI

- Key-naming conventions docs page with the recommended `{domain}:{entity-type}/{entity-id}:{attribute}` pattern and examples (#408)
- `main`-branch guard: PRs to `main` from anything other than `development` or `release/*` fail a required status check, preventing another v0.20.0-style release-bypass (#477)
- Dependabot now runs daily for pip and npm (github-actions stays weekly) and passing Dependabot PRs auto-merge (#432, #445)
- ChatGPT joins the supported-clients list everywhere; Claude Desktop setup now leads with the Custom Connector URL flow (mcp-remote JSON kept as a legacy fallback) (#485)

### Fixed

- Pricing page claimed "unlimited memories" while the free-tier quota is 500 (#404)
- Privacy Policy / Terms referenced `privacy@hive.so` and `hello@hive.so` on a domain we don't own; switched to `@warlordofmars.net` (#431)
- Marketing home page's "3-step setup" described a flow that doesn't exist ("register a client", "one-line snippet"); rewritten to match `SetupPanel` and the docs, including the browser-OAuth step (#471)

### Meta

- CLAUDE.md: deterministic selection algorithm for the autonomous issue queue (#461)
- CLAUDE.md: label taxonomy (status / priority / size / area) and milestone policy; enforced at PR merge via `label-check.yml` (#462, #464)
- CLAUDE.md: autonomous agent halts and surfaces `HUMAN_INPUT_REQUIRED` when the active release milestone drains (#483)
- CHANGELOG: retroactive v0.20.0 entry documenting what actually shipped there (#476)

## v0.20.0 — 2026-04-17

> **Note**: v0.20.0 was cut from a single PR that bypassed the normal release-branch workflow. The intended scope of this milestone (compliance work, accuracy audit, MCP annotations, etc.) was merged to `development` after the tag was already pushed and will ship in v0.21.0. This entry documents what actually shipped in v0.20.0. See #475 for the branch-protection follow-up to prevent this recurring.

### Added

- Terms of Service and Privacy Policy marketing pages (#401)

## v0.19.1 — 2026-04-13

### Fixed

- Omit `client_secret` from DCR response for public clients — `mcp-remote` Zod schema rejected `null` value, breaking Claude Desktop connections (#373)
- MCP auth: `Meta.get()` error and missing HTTP 401 for OAuth clients (#371, #372)
- E2e tests: accept HTTP 401 as valid auth rejection (#375)

## v0.19.0 — 2026-04-12

### Added

- Python and JavaScript client SDKs (#349)
- API key authentication (`hive_sk_` tokens) for programmatic access without OAuth (#339)
- Memory versioning — previous values preserved on overwrite (#342)
- Per-memory TTL at creation time (#341)
- Bulk memory operations: `forget_all`, `export`, `import` (#340)
- Per-user usage quotas for free tier (#333)
- Per-client rate limiting with 429 + Retry-After (#331)
- GDPR account deletion via `DELETE /api/account` (#330)
- OpenAPI/Swagger UI on management API (#329)
- Responsive mobile layout for management UI (#337)
- Improved UsersPanel: pagination, search, and user detail (#338)
- Migrated UI to shadcn/ui component library (#334)
- SLO error budget burn rate alarms and CloudWatch dashboard (#346)
- WAF enabled on dev environment (#344)
- Lambda provisioned concurrency for MCP function in prod (#351)
- Slack notifications for CI/CD pipeline events (#350)
- Weekly DynamoDB PITR backup restore test (#348)
- E2e tests for cost data in admin dashboard (#345)
- Hardened repo against malicious contributions (#343)

### Fixed

- Sign in button border not visible in marketing site navbar (#327, #332)
- Orange active indicator missing from Docs nav link on docs site (#326)
- Dashboard chart x-axis labels cut off (#328)
- E2e race conditions in memory creation and tag filter tests (#335, #336)
- Dashboard e2e cost section assertions (#345, #347, #352, #353)

### Chore

- CLAUDE.md autonomous issue workflow guidelines (#324, #325)

## v0.18.0 — 2026-04-11

### Added

- Live CloudWatch log viewer in admin UI: group/window/filter controls, level badge toggles, expandable rows, 10 s polling with pause/resume (#291, #295, #296, #297, #298)
- Tag picker with autocomplete suggestions for memory filter in MemoryBrowser (#292)
- Relative timestamps on Dashboard last-refreshed indicator (#294)
- Keyboard navigation for memory card list (Arrow keys, Enter, Escape) (#294)

### Fixed

- Docs site visual design unified with marketing site navbar (#289)
- Accessibility and JS quality improvements across admin UI (#288)
- Conditional hooks and chart legend overlap in AppShell/Dashboard (#285)
- Empty state guard for unauthenticated AppShell renders (#286)

## v0.17.1 — 2026-04-10

### Fixed

- Pass `VITE_GA_MEASUREMENT_ID` to `inv deploy` steps so GA4 tag is correctly substituted in deployed `index.html` (#243)

## v0.17.0 — 2026-04-09

### Added

- Google Analytics 4 integration: `page_view` on route changes, `tab_view` on app tab switches, `cta_click` on "Get started" buttons (#240)
- GA4 is disabled in local dev and when `VITE_GA_MEASUREMENT_ID` is unset — no tracking in development

## v0.16.1 — 2026-04-08

### Fixed

- Upgrade `cryptography` 46.0.6 → 46.0.7 to address CVE-2026-39892 (#237)

## v0.16.0 — 2026-04-08

### Added

- Marketing site expanded with Pricing, FAQ, Use Cases, MCP Client Compatibility, Changelog, and Status pages (#231, #232, #234)
- Shared `PageLayout` component with consistent header/footer nav across all marketing pages (#231)
- `ChangelogPage` parses `CHANGELOG.md` at build time and renders versioned sections with color-coded change groups (#234)
- `StatusPage` performs a live health check against `GET /health` with refresh and checked-at time display (#234)
- shadcn/ui component foundation with Tailwind v4 design tokens matching VitePress docs site branding (#228)

### Fixed

- Tailwind utility classes (`mx-auto`) overridden by unlayered CSS reset — moved reset into `@layer base` (#229)
- Flash of light background on dark-mode page load — synchronous inline theme script applied before first paint (#230)
- E2e mobile menu toggle test replaced fixed 300ms wait with condition-based `wait_for` (#235)

## v0.15.0 — 2026-04-07

### Added

- VitePress user-facing documentation site hosted at `/docs` (#201)
- CloudFront routing for `/docs/*` with clean URL rewriting — VitePress `cleanUrls` output served correctly without trailing-slash issues (#201, #204, #205)
- Docs site themed to match marketing site: dark navy navbar, orange accent, Hive logo/favicon (#203, #207, #220)
- Docs navbar with Docs and Sign in links rendered as plain `<a>` elements (bypasses Vue Router so navigation works correctly across site boundaries) (#209, #210, #213, #214, #221, #222)
- `/docs` and `/docs/` redirect to `what-is-hive` first doc page (#215)
- Playwright e2e test suite for docs site: routing, navbar appearance, nav link clicks, logo/Sign in navigation, mobile hamburger (#204, #209, #210, #211, #213, #214, #221, #222)

### Fixed

- Dark mode toggle and GitHub icon removed from docs navbar (#223, #224)
- Logo navigates to marketing page root (Vue Router SPA interception bypassed) (#213)
- Sign in button positioned at far right of navbar next to Docs link (#222)

## v0.14.0 — 2026-04-06

### Added

- Semantic memory search via Amazon S3 Vectors + Bedrock Titan Embeddings V2 — new `search_memories` MCP tool and `GET /api/memories?search=` API endpoint return memories ranked by cosine similarity (#193, #194)
- Debounced semantic search input in Memory Browser UI with match score badges (#193, #194)

### Fixed

- SetupPanel tab and JSON panel colors were hardcoded light-mode values and did not render correctly in dark mode (#196)

## v0.13.1 — 2026-04-06

### Fixed

- LoginPage tagline still referenced "Claude agents" after #184 — updated to "AI agents" (#188)

## v0.13.0 — 2026-04-06

### Added

- Scheduled synthetic traffic workflow generating real CloudWatch metrics every 15 minutes (#154)
- E2E tests for CloudWatch metrics dashboard, including admin API and UI validation (#157)
- Dark mode support with OS preference detection and manual toggle; CSS design tokens via Tailwind v4 (#175)
- Visual identity — logo, favicon, and social preview image (#173)
- Make Google auth bypass conditional on `test_email` param for safer e2e testing (#170, #171)

### Fixed

- MCP client setup instructions for Claude Desktop and Claude Code (#169)
- Marketing page layout: logo, wordmark, 2×2 feature grid, consistent 1100px content width (#178–#181)
- Dark mode applied to all routes (LoginPage, HomePage) via `useTheme` at App root (#182, #183)

### Changed

- Broadened messaging from Claude-specific to MCP-compatible; added Cursor and Continue setup docs and onboarding snippets (#184)

## Earlier releases

See [GitHub releases](https://github.com/warlordofmars/hive/releases) for the full history.
